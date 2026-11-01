import json
from urllib.parse import quote

from conftest import FIXTURE, SET_NAME

SET = quote(SET_NAME)


def tracks(client):
    return client.ok("GET", f"/api/sets/{SET}/tracks")


def row(data, title):
    return next(t for t in data["tracks"] if t["title"] == title)


def fix(client, track, **body):
    data = client.ok("POST", f"/api/sets/{SET}/tracks/{track['row']}/fix",
                     {"identity": track["identity"], **body})
    return client.wait_job(data["job"]["id"])


def test_a_sets_tracks(client, downloaded, tmp_path):
    data = tracks(client)
    assert data["set"] == SET_NAME and data["title"] == SET_NAME and data["mashups"] == "components"
    assert (data["found"], data["missing"]) == (6, 1) and len(data["tracks"]) == 10
    pressure = row(data, "Pressure")
    assert pressure["status"] == "missing" and pressure["reason"] == "no search results"
    assert pressure["search"] == "Saltmarsh - Pressure" and pressure["identity"] == "saltmarsh|pressure"
    ghosts = row(data, "Ghosts")
    assert ghosts["status"] == "found" and ghosts["file"] == str(tmp_path / "music" / SET_NAME / "Kettle - Ghosts.mp3")
    assert ghosts["fix"] is None and not ghosts["fix_in_use"] and ghosts["retry_query"] == ""
    unknown = next(t for t in data["tracks"] if t["display"] == "ID - ID")
    assert unknown["status"] == "skipped" and unknown["identity"].startswith("|id@")


def test_search_again_finds_a_missing_track(client, downloaded, tmp_path):
    pressure = row(tracks(client), "Pressure")
    job = fix(client, pressure, query="Saltmarsh Pressure VIP")
    assert job["state"] == "done", job
    assert job["kind"] == "fix" and job["set"] == SET_NAME and job["row"] == pressure["row"]
    assert job["title"] == 'Saltmarsh - Pressure: search again for "Saltmarsh Pressure VIP"'
    assert (job["result"]["found"], job["result"]["missing"]) == (7, 0)
    assert job["message"] == "All 7 tracks have a file."
    after = row(tracks(client), "Pressure")
    assert after["status"] == "found" and after["fix"]["query"] == "Saltmarsh Pressure VIP" and after["fix_in_use"]
    assert client.ok("GET", f"/api/sets/{SET}")["missing"] == 0


def test_a_picked_result_from_a_search(client, downloaded, tmp_path):
    ghosts = row(tracks(client), "Ghosts")
    search = client.wait_job(client.ok("POST", "/api/searches", {"query": ghosts["search"]})["job"]["id"])
    pick = search["result"]["results"][0]
    job = fix(client, ghosts, link=pick["link"], query=search["result"]["query"])
    assert job["state"] == "done", job
    after = row(tracks(client), "Ghosts")
    assert after["fix_in_use"] and after["file"].endswith(pick["name"]) and after["fix"]["link"] == pick["link"]
    assert after["fix"]["source"] == "soulseek"
    # Downloads go through the Soulseek queue and take the login
    assert any("-c " in line for line in job["log"])


def test_own_file_for_an_id(client, downloaded, tmp_path):
    unknown = next(t for t in tracks(client)["tracks"] if t["display"] == "ID - ID")
    upload = client.ok("POST", "/api/uploads?name=" + quote("kettle unreleased.wav"), b"RIFFmine")["upload"]
    assert upload["name"] == "kettle unreleased.wav" and upload["size"] == 8
    job = fix(client, unknown, upload=upload["id"])
    assert job["state"] == "done", job
    assert not any("-c " in line for line in job["log"])     # no Soulseek needed
    after = next(t for t in tracks(client)["tracks"] if t["row"] == unknown["row"])
    assert after["status"] == "found" and after["fix"]["source"] == "own"
    assert (tmp_path / "music" / SET_NAME / "kettle unreleased.wav").read_bytes() == b"RIFFmine"
    assert not any((tmp_path / "data" / "work" / "uploads").iterdir())   # used up


def test_undo(client, downloaded):
    ghosts = row(tracks(client), "Ghosts")
    fix(client, ghosts, link="slsk://a/b/Other.mp3")
    assert row(tracks(client), "Ghosts")["file"].endswith("Other.mp3")
    job = fix(client, ghosts, clear=True)
    assert job["state"] == "done"
    assert row(tracks(client), "Ghosts")["file"] == ghosts["file"]


def test_a_row_that_holds_another_track_now_is_refused(client, downloaded, tmp_path):
    ghosts = row(tracks(client), "Ghosts")
    # The page was imported again with a track added at the top: every row moves down one
    page_path = tmp_path / "music" / SET_NAME / "_tracklist.html"
    page = page_path.read_text(encoding="utf-8")
    second = page[page.index('<div id="tlp_2"'):page.index('<div id="tlp_3"')]
    added = second.replace("Saltmarsh - Bus Stop Dub", "Newcomer - Opener").replace('"tlp_2"', '"tlp_0"')
    first = page.index('<div id="tlp_1"')
    page_path.write_text(page[:first] + added + page[first:], encoding="utf-8")
    job = fix(client, ghosts, clear=True)
    assert job["state"] == "failed"
    assert job["result"]["errors"] and "the set was imported again since" in job["message"]


def test_fix_requests_are_checked(client, downloaded):
    ghosts = row(tracks(client), "Ghosts")
    url = f"/api/sets/{SET}/tracks/{ghosts['row']}/fix"
    cases = [
        ({"clear": True}, "bad_identity"),
        ({"identity": ghosts["identity"]}, "bad_fix"),
        ({"identity": ghosts["identity"], "clear": True, "query": "x"}, "bad_fix"),
        ({"identity": ghosts["identity"], "clear": "yes"}, "bad_fix"),
        ({"identity": ghosts["identity"], "link": "http://evil/x.mp3"}, "bad_link"),
        ({"identity": ghosts["identity"], "link": "--sockseek=/bin/sh"}, "bad_link"),
        ({"identity": ghosts["identity"], "query": "--file=/etc/passwd"}, "bad_query"),
        ({"identity": ghosts["identity"], "query": "-x"}, "bad_query"),
        ({"identity": ghosts["identity"], "query": "a\x00b"}, "bad_query"),
    ]
    for body, code in cases:
        status, data = client.post(url, body)
        assert status == 400 and data["error"]["code"] == code, (body, data)
    assert client.post(f"/api/sets/{SET}/tracks/0/fix", {"identity": "x", "clear": True})[0] == 400
    status, data = client.post(f"/api/sets/{SET}/tracks/99/fix", {"identity": "x", "clear": True})
    assert status == 400 and data["error"]["message"] == "The set has no row 99."
    assert client.post(f"/api/sets/{SET}/tracks/abc/fix", {"identity": "x", "clear": True})[0] == 404


def test_identity_cant_become_an_option(client, downloaded):
    """--expect-key=<identity> keeps it a value whatever it says."""
    ghosts = row(tracks(client), "Ghosts")
    job = fix(client, dict(ghosts, identity="--clear"), clear=True)
    assert job["state"] == "failed" and "not the track you chose" in job["message"]


def test_searches_are_checked(client):
    client.login()
    for query, code in (("", "bad_query"), ("  ", "bad_query"), ("-rf", "bad_query"), ("x" * 301, "bad_query"),
                        (5, "bad_query"), ("a\x00b", "bad_query")):
        status, data = client.post("/api/searches", {"query": query})
        assert status == 400 and data["error"]["code"] == code, query
    job = client.wait_job(client.ok("POST", "/api/searches", {"query": "  Kettle   Ghosts "})["job"]["id"])
    assert job["result"]["query"] == "Kettle Ghosts"


def test_a_search_that_finds_nothing(client, monkeypatch):
    client.login()
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "Nothing")
    job = client.wait_job(client.ok("POST", "/api/searches", {"query": "Nothing Here"})["job"]["id"])
    assert job["state"] == "done" and job["result"]["results"] == []
    assert job["message"].startswith('Nothing found for "Nothing Here"')


def test_tracks_of_a_broken_set(client, tmp_path):
    folder = tmp_path / "music" / "Broken"
    folder.mkdir(parents=True)
    (folder / "_tracklist.html").write_text("<html>not a tracklist</html>")
    status, data = client.get("/api/sets/Broken/tracks")
    assert status == 500 and data["error"]["code"] == "tracks_failed"
    [s] = client.ok("GET", "/api/sets")["sets"]
    assert s["error"] and s["total"] == 0


def test_result_json_is_valid(client, downloaded):
    """The fix result carries tl2mixxx's own summary of the set."""
    pressure = row(tracks(client), "Pressure")
    job = fix(client, pressure, query="Saltmarsh - Pressure")
    assert json.dumps(job["result"]) and job["result"]["title"] == SET_NAME
    assert FIXTURE.exists()
