import http.client
import json
import stat
import sys
import threading
import time
from urllib.parse import quote
from pathlib import Path

import pytest

from setdl.core import App
from setdl.server import TOKEN_HEADER, Server

HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "tracklist.html"
SET_NAME = "DJ Example @ Warehouse Project, Manchester 2026-10-01"
FINISHED = ("done", "failed", "stopped")
FAKE_TL2MIXXX = HERE / "fake_tl2mixxx.py"
VIDEO = "https://www.youtube.com/watch?v=rooftop0001"
VIDEO_SET = "Kettle Rooftop Session"     # the fixture video's title as a folder name


def pytest_configure(config):
    config.addinivalue_line("markers", "media: tl2mixxx runs with yt-dlp faked (fake_tl2mixxx.py)")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Nothing here may reach the user's own folders, login or sockseek."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SETDL_MIXXX_LOGIN", str(home / "mixxx-login.conf"))
    for name in ("SOCKSEEK", "SETDL_DATA_DIR", "SETDL_MUSIC_DIR", "SETDL_WEB_DIST", "TL2MIXXX_MUSIC_DIR",
                 "FAKE_SOCKSEEK_MISSING", "FAKE_SOCKSEEK_HANG", "SETDL_YTDLP", "FAKE_YTDL_MISSING", "FAKE_YTDL_FAIL",
                 "FAKE_SPOTIFY_FAIL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("FAKE_SOCKSEEK_LOG", str(tmp_path / "sockseek.log"))
    monkeypatch.setenv("FAKE_YTDL_LOG", str(tmp_path / "ytdl.log"))
    monkeypatch.setenv("TL2MIXXX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", "")   # never the real Soulseek server (test_network.py makes fakes)
    # No DNS lookups: these names stand for the Mac itself, every other one is on the internet
    monkeypatch.setattr("setdl.resolve._local_host", lambda host: host in LOCAL_NAMES)


LOCAL_NAMES = {"localtest.me", "lvh.me", "127.0.0.1.nip.io"}


@pytest.fixture
def fake_sockseek(tmp_path) -> Path:
    exe = tmp_path / "bin" / "sockseek"
    exe.parent.mkdir()
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_sockseek.py"}" "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


@pytest.fixture
def app(tmp_path, fake_sockseek, request):
    """The app. Tests marked "media" get tl2mixxx with yt-dlp faked (fake_tl2mixxx.py)."""
    fake = {}
    if request.node.get_closest_marker("media"):
        fake = {"command": [sys.executable, str(FAKE_TL2MIXXX)],
                "helper_command": [sys.executable, str(FAKE_TL2MIXXX), "--helper"]}
    a = App(tmp_path / "data", music_dir=str(tmp_path / "music"), sockseek=str(fake_sockseek),
            stop_grace=2.0, kill_after=5.0, **fake)
    if not fake:
        # Only Soulseek (the fake one): nothing may look on the real YouTube
        a.settings.update({"sources": ["soulseek"], "tags": False})
    yield a
    a.shutdown()


class Client:
    """The page's side: every call with the token, Host and Origin a browser would send."""

    def __init__(self, server: Server):
        self.server = server
        self.port = server.port
        self.token = server.token

    def raw(self, method, path, body=None, headers=None, token=True, timeout=30):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if token:
            h[TOKEN_HEADER] = self.token
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data, resp

    def call(self, method, path, body=None, headers=None, token=True, timeout=30):
        status, data, resp = self.raw(method, path, body, headers, token, timeout)
        ctype = resp.getheader("Content-Type", "")
        return status, (json.loads(data) if ctype.startswith("application/json") else data)

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, {} if body is None else body, **kw)

    def put(self, path, body=None, **kw):
        return self.call("PUT", path, body, **kw)

    def delete(self, path, **kw):
        return self.call("DELETE", path, **kw)

    def ok(self, method, path, body=None, expect=(200, 201, 202)):
        status, data = self.call(method, path, body)
        assert status in expect, (status, data)
        return data

    def wait_job(self, job_id, timeout=60, states=FINISHED):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.ok("GET", f"/api/jobs/{job_id}")
            if job["state"] in states:
                return job
            time.sleep(0.1)
        raise AssertionError(f"job {job_id} is still {job['state']}: {job.get('log')}")

    def login(self, username="tester", password="s3cret pass"):
        return self.ok("PUT", "/api/login", {"username": username, "password": password})

    def draft(self, path=FIXTURE):
        return self.ok("POST", "/api/drafts/page?name=" + quote(path.name), path.read_bytes())

    def settings(self, **changes):
        return self.ok("PUT", "/api/settings", changes)

    def resolve(self, text):
        """Paste anything; a link's job is waited for. Returns the draft."""
        data = self.ok("POST", "/api/drafts/resolve", {"input": text})
        if "draft" in data:
            return data["draft"]
        job = self.wait_job(data["job"]["id"])
        assert job["state"] == "done", job
        return self.ok("GET", f"/api/drafts/{job['result']['draft']}")

    def jobs(self, kind=None):
        jobs = self.ok("GET", "/api/jobs")["jobs"]
        return [j for j in jobs if kind is None or j["kind"] == kind]

    def wait_idle(self, timeout=90):
        """Until no job is queued or running (a download and the steps after it)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not [j for j in self.jobs() if j["state"] not in FINISHED]:
                time.sleep(0.3)     # a step may be about to queue the next one
                if not [j for j in self.jobs() if j["state"] not in FINISHED]:
                    return self.jobs()
            time.sleep(0.1)
        raise AssertionError(f"still busy: {[(j['kind'], j['state']) for j in self.jobs()]}")

    def download(self, **body):
        return self.ok("POST", "/api/downloads", body)["job"]


@pytest.fixture
def server(app, tmp_path):
    s = Server(app, web_dir=tmp_path / "no-web")
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.close()


@pytest.fixture
def client(server):
    return Client(server)


@pytest.fixture
def downloaded(client, monkeypatch):
    """The fixture set, downloaded once with "Pressure" missing on Soulseek (and from Soulseek only)."""
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "Pressure")
    client.settings(sources=["soulseek"], tags=False)
    client.login()
    job = client.wait_job(client.download(draft=client.draft()["id"])["id"])
    assert job["state"] == "done", job
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "")
    return job
