"""Sources and quality: YouTube and cutting from the set's recording after Soulseek, finishing the
files, and the fix panel's Find on YouTube, Cut from the set and picked videos. yt-dlp is faked
(fake_tl2mixxx.py); the audio is ffmpeg's sine tone."""

import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from conftest import SET_NAME, VIDEO, VIDEO_SET, FINISHED

pytestmark = pytest.mark.media

SET = quote(SET_NAME)


def tracks(client, set_name=SET_NAME):
    return client.ok("GET", f"/api/sets/{quote(set_name)}/tracks")["tracks"]


def row(data, title):
    return next(t for t in data if t["title"] == title)


def sockseek_calls(tmp_path):
    log = tmp_path / "sockseek.log"
    return log.read_text().splitlines() if log.exists() else []


def test_settings_for_sources_and_quality(client, tmp_path):
    s = client.ok("GET", "/api/state")["settings"]
    assert (s["sources"], s["quality"], s["format"], s["tags"]) == (["soulseek", "youtube", "mix"], "best", "keep", True)
    state = client.settings(sources=["mix", "soulseek"], quality="lossless", format="aiff", tags=False)
    assert state["settings"]["sources"] == ["soulseek", "mix"]      # always in their own order
    assert (state["settings"]["quality"], state["settings"]["format"], state["settings"]["tags"]) == ("lossless", "aiff", False)
    for bad in ({"sources": ["napster"]}, {"sources": "youtube"}, {"quality": "best-ish"}, {"format": "ogg"},
                {"tags": "yes"}):
        status, data = client.put("/api/settings", bad)
        assert status == 400 and data["error"]["code"].startswith("bad_"), bad
    # Kept for the next launch
    from setdl.settings import SettingsStore
    saved = SettingsStore(tmp_path / "data" / "settings.json", tmp_path).get()
    assert saved.sources == ["soulseek", "mix"] and saved.format == "aiff" and saved.tags is False


def test_missing_tracks_go_to_youtube_after_soulseek(client, monkeypatch, tmp_path):
    client.login()
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "Pressure")
    client.settings(sources=["soulseek", "youtube"], tags=False)
    download = client.download(draft=client.draft()["id"])
    jobs = client.wait_idle()
    kinds = [j["kind"] for j in reversed(jobs)]
    assert kinds == ["download", "fallback"]
    fallback = jobs[0]
    assert fallback["state"] == "done" and fallback["lane"] == "youtube" and fallback["set"] == SET_NAME
    assert fallback["message"] == "Found 1 of 1 missing track(s) on YouTube and SoundCloud."
    assert fallback["progress"] is None and not any(l.startswith("PROGRESS") for l in
                                                     client.ok("GET", f"/api/jobs/{fallback['id']}")["log"])
    pressure = row(tracks(client), "Pressure")
    assert pressure["status"] == "found" and pressure["fix"]["source"] == "youtube" and pressure["fix_in_use"]
    assert pressure["fix"]["link"].startswith("https://www.youtube.com/watch?v=")
    assert Path(pressure["file"]).suffix == ".opus" and Path(pressure["file"]).stat().st_size > 1000
    assert client.ok("GET", f"/api/sets/{SET}")["missing"] == 0
    assert download["id"] != fallback["id"]


def test_soulseek_turned_off(client, tmp_path):
    # No login needed, sockseek never runs, and the set's folder is there at once
    client.settings(sources=["youtube"], tags=False)
    status, data = client.post("/api/downloads", {"draft": client.draft()["id"]})
    assert status == 202 and data["job"]["kind"] == "fallback"
    assert client.ok("GET", f"/api/sets/{SET}")["pending"] is False
    client.wait_idle()
    assert sockseek_calls(tmp_path) == []
    s = client.ok("GET", f"/api/sets/{SET}")
    # "Bus Stop Dub" (played twice) is searched as "Saltmarsh - Bus Stop", and a result that
    # isn't surely the track isn't taken
    assert (s["found"], s["missing"]) == (5, 2)
    rows = tracks(client)
    assert {t["fix"]["source"] for t in rows if t["status"] == "found"} == {"youtube"}
    assert {t["title"] for t in rows if t["status"] == "missing"} == {"Bus Stop Dub"}
    client.settings(sources=["mix"])
    status, data = client.post("/api/downloads", {"set": SET_NAME})
    assert status == 409 and data["error"]["code"] == "no_sources"


def test_no_source_left(client):
    client.settings(sources=["mix"])
    status, data = client.post("/api/downloads", {"draft": client.draft()["id"]})
    assert status == 409 and data["error"]["code"] == "no_sources"


def test_cut_from_the_recording(client, tmp_path):
    client.settings(sources=["mix"], tags=False)
    draft = client.resolve(VIDEO)
    job = client.download(draft=draft["id"])
    assert job["kind"] == "cut" and job["lane"] == "youtube"
    client.wait_idle()
    done = client.ok("GET", f"/api/jobs/{job['id']}")
    assert done["state"] == "done" and done["message"].startswith("Cut 5 track(s)"), done
    rows = tracks(client, VIDEO_SET)
    assert all(t["fix"]["source"] == "mix" for t in rows), rows
    ghosts = row(rows, "Ghosts")
    assert ghosts["file"].endswith("Kettle - Ghosts (from the mix).opus")
    assert ghosts["fix"]["link"] == f"{VIDEO}#t=0,20"
    assert row(rows, "ID")["status"] == "found"           # an ID comes from the recording too
    # The recording was downloaded once, into the cache
    assert [l for l in (tmp_path / "ytdl.log").read_text().splitlines()] == [VIDEO]


def test_soulseek_then_youtube_then_the_recording(client, monkeypatch, tmp_path):
    client.login()
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "Pressure|Baby")
    monkeypatch.setenv("FAKE_YTDL_MISSING", "Baby")
    client.settings(tags=False)
    client.download(draft=client.resolve(VIDEO)["id"])
    jobs = client.wait_idle()
    assert [j["kind"] for j in reversed(jobs) if j["kind"] != "resolve"] == ["download", "fallback", "cut"]
    rows = tracks(client, VIDEO_SET)
    assert {t["title"]: (t["fix"] or {}).get("source", "soulseek") for t in rows} == {
        "Ghosts": "soulseek", "Pressure": "youtube", "Fog Machine": "soulseek", "ID": "mix", "Baby": "mix"}


def test_stopping_a_download_stops_what_comes_after(client, monkeypatch, tmp_path):
    client.login()
    pid_file = tmp_path / "hang.pid"
    monkeypatch.setenv("FAKE_SOCKSEEK_HANG", str(pid_file))
    job = client.download(draft=client.draft()["id"])
    deadline = time.monotonic() + 20
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    client.ok("POST", f"/api/jobs/{job['id']}/stop")
    jobs = client.wait_idle()
    assert [j["kind"] for j in jobs] == ["download"] and jobs[0]["state"] == "stopped"


def test_quality_goes_to_sockseek(client, monkeypatch, tmp_path):
    client.login()
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "Pressure")      # so the retry has something to look for
    client.settings(sources=["soulseek"], quality="lossless", tags=False)
    client.wait_job(client.download(draft=client.draft()["id"])["id"])
    assert "--format flac,wav,aiff,aif" in sockseek_calls(tmp_path)[-1]
    client.settings(quality="fast")
    client.wait_job(client.download(set=SET_NAME)["id"])
    assert "--fast-search" in sockseek_calls(tmp_path)[-1]


def test_finishing_converts_and_tags(client, tmp_path):
    client.settings(sources=["youtube"], format="mp3", tags=True)
    client.download(draft=client.draft()["id"])
    jobs = client.wait_idle()
    assert [j["kind"] for j in reversed(jobs)] == ["fallback", "finish"]
    assert jobs[0]["state"] == "done", jobs[0]
    rows = [t for t in tracks(client) if t["status"] == "found"]
    assert rows and all(t["file"].endswith(".mp3") for t in rows)
    from mutagen import File
    tags = File(row(rows, "Ghosts")["file"], easy=True)
    assert tags["title"] == ["Ghosts"] and tags["album"] == [SET_NAME]
    # Asked for later, after the format changed
    client.settings(format="flac")
    job = client.ok("POST", f"/api/sets/{SET}/finish")["job"]
    done = client.wait_job(job["id"])
    assert done["state"] == "done" and done["message"].startswith("Converted 5 file(s) to FLAC"), done
    assert all(t["file"].endswith(".flac") for t in tracks(client) if t["status"] == "found")
    client.settings(format="keep", tags=False)
    status, data = client.post(f"/api/sets/{SET}/finish")
    assert status == 409 and data["error"]["code"] == "nothing_to_finish"


def test_find_on_youtube_and_download_the_pick(client, downloaded, tmp_path):
    client.settings(tags=False)
    pressure = row(tracks(client), "Pressure")
    found = client.ok("POST", f"/api/sets/{SET}/tracks/{pressure['row']}/fallback", {"identity": pressure["identity"]})
    job = client.wait_job(found["job"]["id"])
    assert job["kind"] == "fallback" and job["row"] == pressure["row"] and job["lane"] == "youtube"
    assert job["title"] == "Saltmarsh - Pressure: find on YouTube" and job["state"] == "done", job
    candidates = job["result"]["tracks"][0]["candidates"]
    assert candidates[0]["official"] and candidates[0]["confidence"] == "high" and candidates[0]["reasons"]
    assert candidates[-1]["confidence"] == "low"                  # "slowed + reverb"
    assert row(tracks(client), "Pressure")["status"] == "missing"   # nothing was downloaded
    pick = candidates[0]
    # A picked video needs no Soulseek login, and doesn't wait in its queue
    client.delete("/api/login")
    fix = client.ok("POST", f"/api/sets/{SET}/tracks/{pressure['row']}/fix",
                    {"identity": pressure["identity"], "link": pick["link"], "query": pick["query"]})["job"]
    assert fix["kind"] == "fix" and fix["lane"] == "youtube"
    assert fix["title"] == "Saltmarsh - Pressure: download the picked video"
    done = client.wait_job(fix["id"])
    assert done["state"] == "done" and done["result"]["found"] == 7, done
    assert done["log"][0].startswith("$ set-downloader take ")
    after = row(tracks(client), "Pressure")
    assert after["fix"]["source"] == "youtube" and after["fix"]["link"] == pick["link"] and after["fix_in_use"]
    assert after["fix"]["query"] == pick["query"]


def test_a_picked_video_that_cant_be_downloaded(client, downloaded, monkeypatch):
    monkeypatch.setenv("FAKE_YTDL_FAIL", "1")
    pressure = row(tracks(client), "Pressure")
    fix = client.ok("POST", f"/api/sets/{SET}/tracks/{pressure['row']}/fix",
                    {"identity": pressure["identity"], "link": "https://youtu.be/abcdefghijk"})["job"]
    done = client.wait_job(fix["id"])
    assert done["state"] == "failed" and "Video unavailable" in done["message"]
    assert row(tracks(client), "Pressure")["status"] == "missing"


@pytest.mark.parametrize("link", ["https://evil.example/watch?v=x", "http://user@youtube.com/x", "ftp://youtube.com/x",
                                  "https://youtube.com.evil.example/x"])
def test_only_youtube_and_soundcloud_links_are_picked(client, downloaded, link):
    pressure = row(tracks(client), "Pressure")
    status, data = client.post(f"/api/sets/{SET}/tracks/{pressure['row']}/fix",
                               {"identity": pressure["identity"], "link": link})
    assert status == 400 and data["error"]["code"] == "bad_link"


def test_find_on_youtube_checks_the_track(client, downloaded):
    data = tracks(client)
    unknown = next(t for t in data if t["display"] == "ID - ID")
    status, err = client.post(f"/api/sets/{SET}/tracks/{unknown['row']}/fallback", {"identity": unknown["identity"]})
    assert status == 400 and err["error"]["code"] == "bad_row"
    ghosts = row(data, "Ghosts")
    assert client.post(f"/api/sets/{SET}/tracks/{ghosts['row']}/fallback", {})[0] == 400
    assert client.post(f"/api/sets/{SET}/tracks/999/fallback", {"identity": "x"})[0] == 400
    # The row holds another track now: refused by tl2mixxx
    job = client.ok("POST", f"/api/sets/{SET}/tracks/{ghosts['row']}/fallback", {"identity": "someone|else"})["job"]
    done = client.wait_job(job["id"])
    assert done["state"] == "failed" and "not the track you chose" in done["message"]


def test_cut_one_track_from_the_set(client, tmp_path):
    client.login()
    client.settings(sources=["soulseek"], tags=False)
    client.wait_job(client.download(draft=client.resolve(VIDEO)["id"])["id"])
    rows = tracks(client, VIDEO_SET)
    baby = row(rows, "Baby")
    job = client.ok("POST", f"/api/sets/{quote(VIDEO_SET)}/tracks/{baby['row']}/cut", {"identity": baby["identity"]})["job"]
    assert job["kind"] == "cut" and job["row"] == baby["row"] and job["title"] == "Four Tet - Baby: cut from the set"
    done = client.wait_job(job["id"])
    assert done["state"] == "done", done
    after = row(tracks(client, VIDEO_SET), "Baby")
    assert after["fix"]["source"] == "mix" and after["file"].endswith("(from the mix).opus")
    assert after["fix"]["link"] == f"{VIDEO}#t=80,100"


def test_cut_needs_a_recording_and_a_time(client, downloaded):
    ghosts = row(tracks(client), "Ghosts")
    status, data = client.post(f"/api/sets/{SET}/tracks/{ghosts['row']}/cut", {"identity": ghosts["identity"]})
    assert status == 409 and data["error"]["code"] == "no_recording"


def test_youtube_jobs_run_beside_soulseek_but_one_at_a_time(client, downloaded, monkeypatch, tmp_path):
    pid_file = tmp_path / "hang.pid"
    monkeypatch.setenv("FAKE_SOCKSEEK_HANG", str(pid_file))
    retry = client.download(set=SET_NAME)
    deadline = time.monotonic() + 20
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    data = tracks(client)
    first, second = row(data, "Pressure"), row(data, "Ghosts")
    a = client.ok("POST", f"/api/sets/{SET}/tracks/{first['row']}/fallback", {"identity": first["identity"]})["job"]
    b = client.ok("POST", f"/api/sets/{SET}/tracks/{second['row']}/fallback", {"identity": second["identity"]})["job"]
    assert b["state"] == "queued" and b["waiting"] == "youtube" and b["ahead"] == 1
    assert client.wait_job(a["id"])["state"] == "done"      # while the download still runs
    assert client.ok("GET", f"/api/jobs/{retry['id']}")["state"] == "running"
    assert client.wait_job(b["id"])["state"] == "done"
    client.ok("POST", f"/api/jobs/{retry['id']}/stop")
    client.wait_job(retry["id"])


def _tone(path: Path) -> Path:
    from tl2mixxx import ffmpeg as ff
    subprocess.run([ff.find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=2", str(path)], check=True)
    return path


def test_a_fix_is_finished_too(client, downloaded, tmp_path):
    client.settings(format="flac", tags=True)
    ghosts = row(tracks(client), "Ghosts")
    wav = _tone(tmp_path / "mine.wav")
    upload = client.ok("POST", "/api/uploads?name=mine.wav", wav.read_bytes())["upload"]
    fix = client.ok("POST", f"/api/sets/{SET}/tracks/{ghosts['row']}/fix",
                    {"identity": ghosts["identity"], "upload": upload["id"]})["job"]
    assert client.wait_job(fix["id"])["state"] == "done"
    jobs = client.wait_idle()
    finish = next(j for j in jobs if j["kind"] == "finish")
    assert finish["row"] == ghosts["row"] and finish["state"] == "done", finish
    assert row(tracks(client), "Ghosts")["file"].endswith("mine.flac")


def test_a_refused_login_still_goes_on_to_youtube_and_the_cut(client, monkeypatch, tmp_path):
    """Soulseek refusing the login stops the download (by the app, not the user): YouTube and the
    cut don't need the login, so they still run."""
    client.login()
    monkeypatch.setenv("FAKE_SOCKSEEK_LOGIN_REFUSED", "1")
    monkeypatch.setenv("FAKE_YTDL_MISSING", "Baby")
    client.settings(tags=False)
    client.download(draft=client.resolve(VIDEO)["id"])
    jobs = [j for j in reversed(client.wait_idle(timeout=60)) if j["kind"] != "resolve"]
    assert [j["kind"] for j in jobs] == ["download", "fallback", "cut"]
    assert jobs[0]["state"] == "failed" and "isn't letting this account log in" in jobs[0]["message"]
    assert jobs[1]["state"] == "done" and jobs[2]["state"] == "done"
    rows = tracks(client, VIDEO_SET)
    assert {t["title"]: (t["fix"] or {}).get("source") for t in rows} == {
        "Ghosts": "youtube", "Pressure": "youtube", "Fog Machine": "youtube", "ID": "mix", "Baby": "mix"}


def test_a_job_waiting_for_its_set_doesnt_hold_up_its_lane(client, downloaded, monkeypatch, tmp_path):
    pid_file = tmp_path / "hang.pid"
    monkeypatch.setenv("FAKE_SOCKSEEK_HANG", str(pid_file))
    retry = client.download(set=SET_NAME)
    deadline = time.monotonic() + 20
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    data = tracks(client)
    ghosts, pressure = row(data, "Ghosts"), row(data, "Pressure")
    # A picked video for the set waits for the retry to let go of the set...
    take = client.ok("POST", f"/api/sets/{SET}/tracks/{ghosts['row']}/fix",
                     {"identity": ghosts["identity"], "link": "https://www.youtube.com/watch?v=" + "t" * 11})["job"]
    # ... and Find on YouTube (which changes no files) goes ahead of it in the YouTube lane
    find = client.ok("POST", f"/api/sets/{SET}/tracks/{pressure['row']}/fallback",
                     {"identity": pressure["identity"]})["job"]
    assert client.wait_job(find["id"])["state"] == "done"
    waiting = client.ok("GET", f"/api/jobs/{take['id']}")
    assert waiting["state"] == "queued" and waiting["waiting"] == "set"
    assert client.ok("GET", f"/api/jobs/{retry['id']}")["state"] == "running"
    client.ok("POST", f"/api/jobs/{retry['id']}/stop")
    client.wait_job(retry["id"])
    assert client.wait_job(take["id"])["state"] == "done"
