import os
from urllib.parse import quote

import pytest

from conftest import FIXTURE, SET_NAME
from setdl import drafts
from setdl.server import TOKEN_HEADER


def test_api_needs_the_token(client):
    assert client.get("/api/state", token=False)[0] == 401
    status, data = client.get("/api/state", token=False, headers={TOKEN_HEADER: "wrong"})
    assert status == 401 and data["error"]["code"] == "bad_token"
    assert client.get("/api/state", token=False, headers={TOKEN_HEADER: "ü" * 10})[0] == 401
    assert client.get("/api/state")[0] == 200
    # Even for paths that don't exist: nothing about the API without it
    assert client.get("/api/nope", token=False)[0] == 401
    assert client.get("/api/nope")[0] == 404


@pytest.mark.parametrize("host", ["evil.example:{port}", "127.0.0.1:1", "localhost", "127.0.0.1",
                                  "0.0.0.0:{port}", "[::1]:{port}", ""])
def test_other_hosts_are_refused(client, host):
    """DNS rebinding: a page whose name points at 127.0.0.1 still sends its own name as Host."""
    host = host.format(port=client.port)
    for path in ("/api/state", "/"):
        status, data = client.call("GET", path, headers={"Host": host})
        assert status == 403 and data["error"]["code"] == "bad_host", (path, host)


def test_localhost_works_too(client):
    assert client.get("/api/state", headers={"Host": f"localhost:{client.port}"})[0] == 200


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://127.0.0.1:1"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_other_origins_are_refused(client, headers):
    status, data = client.post("/api/searches", {"query": "x"}, headers=headers)
    assert status == 403 and data["error"]["code"] == "bad_origin"
    assert client.get("/", headers=headers)[0] == 403


def test_own_origin_is_accepted(client):
    own = {"Origin": f"http://127.0.0.1:{client.port}", "Sec-Fetch-Site": "same-origin"}
    assert client.get("/api/state", headers=own)[0] == 200
    assert client.get("/api/state", headers={"Origin": f"http://localhost:{client.port}"})[0] == 200


def test_dev_origin_only_when_asked(app, tmp_path):
    from conftest import Client
    from setdl.server import Server
    import threading
    s = Server(app, web_dir=tmp_path / "none", dev_origins=("http://localhost:5173",))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        c = Client(s)
        vite = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"}
        assert c.get("/api/state", headers=vite)[0] == 200
        assert s.page_url("http://localhost:5173").startswith("http://localhost:5173/#token=")
    finally:
        s.close()


def test_set_ids_cannot_leave_the_music_folder(client, downloaded, app, tmp_path):
    music = tmp_path / "music"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "_tracklist.html").write_bytes(FIXTURE.read_bytes())
    os.symlink(outside, music / "linked set")
    (tmp_path / "_tracklist.html").write_bytes(FIXTURE.read_bytes())   # the music folder's parent
    cases = {"..": 400, ".": 400, "%2E%2E": 400, "..%2F..%2Fetc": 400, "a%2Fb": 400, "a%5Cb": 400,
             "%00": 400, quote("linked set"): 403, "nope": 404}
    for set_id, expected in cases.items():
        for method, path in (("GET", f"/api/sets/{set_id}"), ("GET", f"/api/sets/{set_id}/tracks")):
            status, data = client.call(method, path)
            assert status == expected, (set_id, path, status, data)
        status, _ = client.post(f"/api/sets/{set_id}/tracks/1/fix", {"identity": "x", "clear": True})
        assert status == expected, set_id
        status, _ = client.post("/api/downloads", {"set": set_id.replace("%2E", ".").replace("%2F", "/")})
        assert status in (400, 403, 404), set_id
    # A link to elsewhere isn't listed either
    assert [s["id"] for s in client.ok("GET", "/api/sets")["sets"]] == [SET_NAME]
    assert client.get(f"/api/sets/{quote(SET_NAME)}")[0] == 200


def test_reveal_stays_in_the_music_folder(client, downloaded, monkeypatch, tmp_path):
    shown = []
    monkeypatch.setattr("setdl.core.reveal_in_finder", shown.append)
    folder = tmp_path / "music" / SET_NAME
    assert client.post("/api/reveal", {"set": SET_NAME})[0] == 200
    track = next(folder.glob("*.mp3"))
    assert client.post("/api/reveal", {"path": str(track)})[0] == 200
    assert client.post("/api/reveal", {})[0] == 200
    assert shown == [folder.resolve(), track.resolve(), (tmp_path / "music").resolve()]
    for path in ("/etc/passwd", str(folder / ".." / ".." / "data"), str(tmp_path)):
        assert client.post("/api/reveal", {"path": path})[0] == 403, path
    assert client.post("/api/reveal", {"path": "relative/file.mp3"})[0] == 400
    assert client.post("/api/reveal", {"path": str(folder / "gone.mp3")})[0] == 404
    assert len(shown) == 3


def test_drafts_and_uploads_stay_in_the_scratch_folder(client, downloaded):
    for bad in ("..", "../../etc", "0123456789abcdeg", "0123456789ABCDEF", "x" * 16):
        assert client.get(f"/api/drafts/{quote(bad, safe='')}")[0] == 404
        assert client.delete(f"/api/uploads/{quote(bad, safe='')}")[0] == 404
        status, data = client.post(f"/api/sets/{quote(SET_NAME)}/tracks/5/fix",
                                   {"identity": "kettle|ghosts", "upload": bad})
        assert status == 404 and data["error"]["code"] == "no_upload"
        assert client.post("/api/downloads", {"draft": bad})[0] == 404
    # An upload's name can't climb out either
    status, data = client.post("/api/uploads?name=" + quote("../../evil.mp3"), b"ID3x")
    assert status == 201 and data["upload"]["name"] == "evil.mp3"


def test_body_limits(client, monkeypatch):
    status, data = client.post("/api/searches", b"x", headers={"Content-Length": str(10 ** 9)})
    assert status == 413 and data["error"]["code"] == "too_large"
    monkeypatch.setattr("setdl.server.PAGE_LIMIT", 1000)
    status, data = client.post("/api/drafts/page?name=a.html", b"<html>" + b"x" * 2000)
    assert status == 413
    monkeypatch.setattr("setdl.server.UPLOAD_LIMIT", 10)
    assert client.post("/api/uploads?name=a.mp3", b"x" * 11)[0] == 413
    assert client.post("/api/searches", b"[1, 2]")[0] == 400
    assert client.post("/api/searches", b"{not json")[0] == 400


def test_upload_needs_a_name(client):
    status, data = client.post("/api/uploads", b"ID3x")
    assert status == 400 and data["error"]["code"] == "bad_name"
    assert client.post("/api/uploads?name=a.mp3", b"")[0] == 400


def test_server_still_works_after_refused_bodies(client):
    """A body left unread closes the connection instead of becoming the next request."""
    status, data = client.post("/api/uploads?name=notes.txt", b"hello")
    assert status == 415 and data["error"]["code"] == "not_audio"
    assert client.get("/api/state")[0] == 200


def test_unknown_methods_and_paths(client):
    assert client.call("PATCH", "/api/state")[0] == 405
    assert client.call("DELETE", "/api/state")[0] == 405
    assert client.call("OPTIONS", "/api/state")[0] == 405
    assert client.call("POST", "/")[0] == 405


def test_no_secrets_in_responses_or_headers(client):
    status, data, resp = client.raw("GET", "/api/state")
    assert client.token.encode() not in data
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    assert resp.getheader("Cache-Control") == "no-store"
    status, data, resp = client.raw("GET", "/", token=False)
    assert client.token.encode() not in data and "frame-ancestors 'none'" in resp.getheader("Content-Security-Policy")


def test_ids_are_hex(tmp_path):
    assert drafts.ID_PATTERN.fullmatch(drafts.new_id())
