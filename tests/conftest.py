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


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Nothing here may reach the user's own folders, login or sockseek."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SETDL_MIXXX_LOGIN", str(home / "mixxx-login.conf"))
    for name in ("SOCKSEEK", "SETDL_DATA_DIR", "SETDL_MUSIC_DIR", "SETDL_WEB_DIST", "TL2MIXXX_MUSIC_DIR",
                 "FAKE_SOCKSEEK_MISSING", "FAKE_SOCKSEEK_HANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("FAKE_SOCKSEEK_LOG", str(tmp_path / "sockseek.log"))


@pytest.fixture
def fake_sockseek(tmp_path) -> Path:
    exe = tmp_path / "bin" / "sockseek"
    exe.parent.mkdir()
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_sockseek.py"}" "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


@pytest.fixture
def app(tmp_path, fake_sockseek):
    a = App(tmp_path / "data", music_dir=str(tmp_path / "music"), sockseek=str(fake_sockseek),
            stop_grace=2.0, kill_after=5.0)
    yield a
    a.shutdown()


class Client:
    """The page's side: every call with the token, Host and Origin a browser would send."""

    def __init__(self, server: Server):
        self.server = server
        self.port = server.port
        self.token = server.token

    def raw(self, method, path, body=None, headers=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
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

    def call(self, method, path, body=None, headers=None, token=True):
        status, data, resp = self.raw(method, path, body, headers, token)
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
    """The fixture set, downloaded once with "Pressure" missing on Soulseek."""
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "Pressure")
    client.login()
    job = client.wait_job(client.download(draft=client.draft()["id"])["id"])
    assert job["state"] == "done", job
    monkeypatch.setenv("FAKE_SOCKSEEK_MISSING", "")
    return job
