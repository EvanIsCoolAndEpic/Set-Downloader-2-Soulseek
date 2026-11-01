import http.client
import json
import os
import sys
import threading
import time
from urllib.parse import quote

from conftest import SET_NAME
from setdl.server import TOKEN_HEADER


def wait_for(cond, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError("timed out")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_download_a_draft(client, downloaded, tmp_path):
    job = downloaded
    assert job["kind"] == "download" and job["set"] == SET_NAME and job["title"] == SET_NAME
    assert job["exit_code"] == 0 and job["started"] and job["finished"]
    result = job["result"]
    assert (result["found"], result["missing"], result["total"]) == (6, 1, 7)
    assert result["missing_tracks"] == [{"number": "", "artist": "Saltmarsh", "title": "Pressure",
                                         "reason": "no search results"}]
    assert job["message"] == "6 of 7 tracks have a file."
    assert job["log"][0].startswith("$ tl2mixxx run ") and "--no-mixxx" in job["log"][0]
    assert any("6/7 tracks available" in line for line in job["log"])
    folder = tmp_path / "music" / SET_NAME
    assert (folder / f"{SET_NAME}.m3u8").is_file() and (folder / "_tracklist.html").is_file()
    assert not list((tmp_path / "data" / "work" / "results").iterdir())   # the result JSON is read and removed


def test_sets_are_listed_and_retried(client, downloaded, tmp_path):
    sets = client.ok("GET", "/api/sets")
    assert sets["music_dir"] == str(tmp_path / "music")
    [s] = sets["sets"]
    assert s["id"] == SET_NAME and s["title"] == SET_NAME and s["busy"] is None
    assert (s["found"], s["missing"], s["total"]) == (6, 1, 7)
    assert s["downloaded"] and s["mashups"] == "components" and s["updated"] and s["error"] is None
    assert s["m3u"].endswith(".m3u8")
    # Retrying finds the track that has appeared since
    job = client.wait_job(client.download(set=SET_NAME)["id"])
    assert job["state"] == "done" and job["result"]["found"] == 7
    assert f"--playlist-name={SET_NAME}" in job["log"][0]
    assert client.ok("GET", f"/api/sets/{quote(SET_NAME)}")["missing"] == 0
    assert not (tmp_path / "music" / SET_NAME / "_missing.csv").exists()


def test_a_set_folder_without_downloads_counts_as_missing(client, tmp_path):
    from conftest import FIXTURE
    folder = tmp_path / "music" / "Not yet"
    folder.mkdir(parents=True)
    (folder / "_tracklist.html").write_bytes(FIXTURE.read_bytes())
    (tmp_path / "music" / "_pasted tracklists").mkdir()
    (tmp_path / "music" / "loose file.mp3").write_bytes(b"x")
    [s] = client.ok("GET", "/api/sets")["sets"]
    assert s["id"] == "Not yet" and not s["downloaded"] and (s["found"], s["missing"]) == (0, 7)


def test_mashups_choice_is_kept_per_set(client, downloaded):
    job = client.wait_job(client.download(set=SET_NAME, mashups="both")["id"])
    assert "--mashups=both" in job["log"][0]
    s = client.ok("GET", f"/api/sets/{quote(SET_NAME)}")
    assert s["mashups"] == "both" and s["total"] == 8
    tracks = client.ok("GET", f"/api/sets/{quote(SET_NAME)}/tracks")
    assert tracks["mashups"] == "both"
    assert client.post("/api/downloads", {"set": SET_NAME, "mashups": "all"})[0] == 400


def test_asking_twice_gives_the_same_job(client, monkeypatch, tmp_path):
    client.login()
    pid_file = tmp_path / "hang.pid"
    monkeypatch.setenv("FAKE_SOCKSEEK_HANG", str(pid_file))
    draft = client.draft()
    first = client.download(draft=draft["id"])
    status, data = client.post("/api/downloads", {"draft": draft["id"]})
    assert status == 200 and data["already_queued"] and data["job"]["id"] == first["id"]
    wait_for(pid_file.exists)
    status, data = client.delete(f"/api/drafts/{draft['id']}")
    assert status == 409 and data["error"]["code"] == "draft_in_use"
    client.ok("POST", f"/api/jobs/{first['id']}/stop")
    assert client.wait_job(first["id"])["state"] == "stopped"


def test_a_search_waits_for_the_download_and_stop_keeps_what_finished(client, monkeypatch, tmp_path):
    client.login()
    pid_file = tmp_path / "hang.pid"
    monkeypatch.setenv("FAKE_SOCKSEEK_HANG", str(pid_file))
    download = client.download(draft=client.draft()["id"])
    wait_for(pid_file.exists)
    sockseek_pid = int(pid_file.read_text())
    assert client.ok("GET", f"/api/jobs/{download['id']}")["state"] == "running"
    # Not on disk yet (tl2mixxx keeps the page at the end), but listed as pending
    pending = client.ok("GET", f"/api/sets/{quote(SET_NAME)}")
    assert pending["busy"] == "running" and pending["pending"] and (pending["found"], pending["total"]) == (0, 7)
    assert [s["id"] for s in client.ok("GET", "/api/sets")["sets"]] == [SET_NAME]
    status, data = client.get(f"/api/sets/{quote(SET_NAME)}/tracks")
    assert status == 409 and data["error"]["code"] == "not_ready"

    search = client.ok("POST", "/api/searches", {"query": "Kettle - Ghosts"})["job"]
    assert search["state"] == "queued" and search["waiting"] == "soulseek" and search["ahead"] == 1
    another = client.ok("POST", "/api/searches", {"query": "Saltmarsh - Pressure"})["job"]
    assert another["ahead"] == 2
    time.sleep(1.0)
    assert client.ok("GET", f"/api/jobs/{search['id']}")["state"] == "queued"   # one login: it waits

    # A queued job just leaves the queue
    stopped = client.ok("POST", f"/api/jobs/{another['id']}/stop")["job"]
    assert stopped["state"] == "stopped" and stopped["message"] == "Stopped before it started."
    assert client.ok("GET", f"/api/jobs/{search['id']}")["ahead"] == 1

    # The running download stops (closing tl2mixxx's stdin), keeping the track that finished
    t0 = time.monotonic()
    assert client.ok("POST", f"/api/jobs/{download['id']}/stop")["job"]["state"] == "stopping"
    done = client.wait_job(download["id"])
    assert done["state"] == "stopped" and done["exit_code"] == 130
    assert time.monotonic() - t0 < 2.0   # tl2mixxx stopped on its own: no SIGTERM needed
    assert done["result"]["found"] == 1 and done["result"]["cancelled"]
    assert done["message"].startswith("Stopped. What had finished downloading is kept.")
    wait_for(lambda: not alive(sockseek_pid))

    # Then the search runs
    found = client.wait_job(search["id"])
    assert found["state"] == "done" and found["started"] >= done["finished"]
    assert [r["format"] for r in found["result"]["results"]] == ["flac", "mp3"]
    assert found["result"]["results"][0]["link"].startswith("slsk://alice/")
    assert found["message"] == '2 result(s) for "Kettle - Ghosts", best first.'


def test_stop_reaches_a_stuck_process_group(app, client, monkeypatch, tmp_path):
    """If tl2mixxx doesn't stop when its stdin closes, the whole group is terminated."""
    stuck = tmp_path / "stuck.py"
    child_pid = tmp_path / "child.pid"
    stuck.write_text(
        "import os, signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"   # ignores both stdin closing and SIGTERM
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"open({str(child_pid)!r}, 'w').write(str(p.pid))\n"
        "print('stuck', flush=True)\n"
        "time.sleep(600)\n")
    from setdl.jobs import Job
    app.jobs.command = [sys.executable, str(stuck)]
    app.jobs.stop_grace, app.jobs.kill_after = 0.5, 0.5
    job = app.jobs.submit(Job(kind="download", title="stuck", args=[], soulseek=True))
    wait_for(child_pid.exists)
    pid = int(child_pid.read_text())
    client.ok("POST", f"/api/jobs/{job.id}/stop")
    finished = client.wait_job(job.id, timeout=10)
    assert finished["state"] == "stopped" and finished["exit_code"] == -9
    wait_for(lambda: not alive(pid))


def test_a_fix_waits_for_its_sets_download(client, downloaded, monkeypatch, tmp_path):
    tracks = client.ok("GET", f"/api/sets/{quote(SET_NAME)}/tracks")["tracks"]
    ghosts = next(t for t in tracks if t["title"] == "Ghosts")
    pid_file = tmp_path / "hang.pid"
    monkeypatch.setenv("FAKE_SOCKSEEK_HANG", str(pid_file))
    retry = client.download(set=SET_NAME)
    wait_for(pid_file.exists)
    upload = client.ok("POST", "/api/uploads?name=ghosts.wav", b"RIFFmine")["upload"]
    fix = client.ok("POST", f"/api/sets/{quote(SET_NAME)}/tracks/{ghosts['row']}/fix",
                    {"identity": ghosts["identity"], "upload": upload["id"]})["job"]
    assert not fix["waiting"] or fix["waiting"] == "set"      # not in the Soulseek queue
    wait_for(lambda: client.ok("GET", f"/api/jobs/{fix['id']}")["waiting"] == "set")
    assert client.ok("GET", f"/api/jobs/{fix['id']}")["state"] == "queued"
    client.ok("POST", f"/api/jobs/{retry['id']}/stop")
    assert client.wait_job(retry["id"])["state"] == "stopped"
    fixed = client.wait_job(fix["id"])
    assert fixed["state"] == "done", fixed
    assert (tmp_path / "music" / SET_NAME / "ghosts.wav").read_bytes() == b"RIFFmine"
    assert client.delete(f"/api/uploads/{upload['id']}")[0] == 404          # used up


def read_events(client, path, until, timeout=30):
    """Reads Server-Sent Events the way the page does (fetch with the token header)."""
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=timeout)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{client.port}", TOKEN_HEADER: client.token})
    resp = conn.getresponse()
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
    events, current = [], {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = resp.fp.readline().decode("utf-8").rstrip("\n")
        if line == "":
            if "event" in current:
                data = json.loads(current.get("data", "{}"))
                events.append((current["event"], data, current.get("id")))
                if until(current["event"], data):
                    break
            current = {}
        elif not line.startswith(":") and ": " in line:
            k, v = line.split(": ", 1)
            current[k] = v
    conn.close()
    return events


def test_live_events(client):
    client.login()
    box = {}

    def listen():
        box["events"] = read_events(client, "/api/events",
                                    lambda kind, d: kind == "job" and d["state"] == "done")
    t = threading.Thread(target=listen)
    t.start()
    time.sleep(0.3)
    job = client.ok("POST", "/api/searches", {"query": "Kettle - Ghosts"})["job"]
    t.join(30)
    events = box["events"]
    assert events[0][0] == "hello"
    states = [d["state"] for kind, d, _ in events if kind == "job" and d["id"] == job["id"]]
    assert states[0] == "queued" and "running" in states and states[-1] == "done"
    logs = [d for kind, d, _ in events if kind == "log"]
    assert logs[0]["job"] == job["id"] and logs[0]["n"] == 1 and logs[0]["line"].startswith("$ tl2mixxx search")
    assert any("Searching Soulseek for: Kettle - Ghosts" in d["line"] for d in logs)
    done = [d for kind, d, _ in events if kind == "job" and d["state"] == "done"][0]
    assert done["result"]["results"]
    ids = [int(i) for _, _, i in events if i]
    assert ids == sorted(ids)

    # Reconnecting with Last-Event-ID replays what came after it; ?job= filters
    replay = read_events(client, f"/api/events?job={job['id']}&after={ids[0]}",
                         lambda kind, d: kind == "job" and d["state"] == "done", timeout=5)
    assert [k for k, _, _ in replay][0] == "hello" and len(replay) > 2
    assert all(d.get("job", d.get("id")) == job["id"] for k, d, _ in replay if k != "hello")


def test_sets_event_after_a_download(client, app, downloaded):
    q = app.bus.subscribe()
    job = client.wait_job(client.download(set=SET_NAME)["id"])
    assert job["state"] == "done"
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert ("sets", {"set": SET_NAME, "reason": "download"}) in [(k, d) for _, k, d in events]


def test_jobs_list_newest_first(client, downloaded):
    client.wait_job(client.ok("POST", "/api/searches", {"query": "Kettle - Ghosts"})["job"]["id"])
    jobs = client.ok("GET", "/api/jobs")["jobs"]
    assert [j["kind"] for j in jobs] == ["search", "download"]
    assert "log" not in jobs[0]
    assert client.get("/api/jobs/nope")[0] == 404
    assert client.post("/api/jobs/nope/stop")[0] == 404


def test_sockseek_missing(client, app):
    client.login()
    app.settings._settings.sockseek = ""
    status, data = client.post("/api/searches", {"query": "x"})
    assert status == 409 and data["error"]["code"] == "sockseek_missing"
    assert client.ok("GET", "/api/state")["sockseek"]["found"] is False


def test_a_refused_login_stops_the_download_and_says_why(client, monkeypatch):
    client.login()
    monkeypatch.setenv("FAKE_SOCKSEEK_LOGIN_REFUSED", "1")
    job = client.wait_job(client.download(draft=client.draft()["id"])["id"], timeout=30)
    assert job["state"] == "failed"
    assert "isn't letting this account log in" in job["message"]
