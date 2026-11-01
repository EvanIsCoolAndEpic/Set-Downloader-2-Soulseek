import os
import re
import signal
import subprocess
import sys
import threading
import urllib.request

import pytest

from conftest import FIXTURE, SET_NAME, Client
from setdl import paths
from setdl.server import TOKEN_HEADER, Server


def test_multi_call_runs_tl2mixxx(tmp_path):
    out = subprocess.run([sys.executable, "-m", "setdl", "--tl2mixxx", "parse", str(FIXTURE)],
                         capture_output=True, text=True, cwd=tmp_path, timeout=60)
    assert out.returncode == 0, out.stderr
    assert SET_NAME in out.stdout and "7 of 10 rows will be searched" in out.stdout
    out = subprocess.run([sys.executable, "-m", "setdl", "--tl2mixxx", "--version"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.startswith("tl2mixxx ")


def test_tl2mixxx_command(monkeypatch):
    cmd = paths.tl2mixxx_command()
    assert cmd[0] == sys.executable and cmd[-3:] == ["-m", "setdl", "--tl2mixxx"] and "-I" in cmd
    assert paths.helper_command()[-1] == "--helper"
    # The built app runs itself
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.tl2mixxx_command() == [sys.executable, "--tl2mixxx"]
    assert paths.helper_command() == [sys.executable, "--helper"]


def test_bundled_sockseek_in_the_app(monkeypatch, tmp_path):
    app = tmp_path / "Set Downloader.app" / "Contents"
    (app / "MacOS").mkdir(parents=True)
    (app / "Resources").mkdir()
    exe = app / "MacOS" / "Set Downloader"
    exe.write_text("")
    assert paths.bundled_sockseek() is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert paths.bundled_sockseek() is None
    sockseek = app / "Resources" / "sockseek"
    sockseek.write_text("#!/bin/sh\n")
    sockseek.chmod(0o755)
    assert paths.bundled_sockseek() == sockseek.resolve()


def test_browser_mode(tmp_path):
    """The dev mode: serves, prints the address with the token, quits cleanly on SIGTERM."""
    env = dict(os.environ, SETDL_MIXXX_LOGIN=str(tmp_path / "none.conf"))
    proc = subprocess.Popen([sys.executable, "-m", "setdl", "--browser", "--no-open",
                             "--data-dir", str(tmp_path / "data"), "--music-dir", str(tmp_path / "music"),
                             "--web-dir", str(tmp_path / "web")],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        line = proc.stdout.readline()
        m = re.search(r"(http://127\.0\.0\.1:\d+)/#token=(\S+)", line)
        assert m, line
        req = urllib.request.Request(m.group(1) + "/api/state", headers={TOKEN_HEADER: m.group(2)})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert b'"music_dir"' in resp.read()
    finally:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(15) == 0


def test_settings(client, tmp_path):
    state = client.ok("GET", "/api/state")
    assert state["settings"]["music_dir"] == str(tmp_path / "music") and state["settings"]["mashups"] == "components"
    assert state["sockseek"]["source"] == "setting" and state["sockseek"]["found"]
    assert state["music_dir"]["exists"] is False and state["limits"]["upload_bytes"] > 0
    new = tmp_path / "elsewhere"
    state = client.ok("PUT", "/api/settings", {"music_dir": str(new), "mashups": "both", "sockseek": ""})
    assert state["settings"] == {"music_dir": str(new), "sockseek": "", "mashups": "both", "sources": ["soulseek"],
                                 "quality": "best", "format": "keep", "tags": False}
    assert state["sockseek"]["found"] is False
    saved = (tmp_path / "data" / "settings.json").read_text()
    assert str(new) in saved
    for body, code in (({"music_dir": "relative/dir"}, "bad_music_dir"), ({"music_dir": "/"}, "bad_music_dir"),
                       ({"music_dir": str(FIXTURE)}, "bad_music_dir"), ({"mashups": "all"}, "bad_mashups"),
                       ({"sockseek": "/no/such/sockseek"}, "bad_sockseek"), ({"sockseek": str(FIXTURE)}, "bad_sockseek"),
                       ({"colour": "red"}, "unknown_setting")):
        status, data = client.put("/api/settings", body)
        assert status == 400 and data["error"]["code"] == code, body
    home = os.environ["HOME"]
    state = client.ok("PUT", "/api/settings", {"music_dir": "~/Sets"})
    assert state["settings"]["music_dir"] == os.path.join(home, "Sets")


def test_saved_settings_come_back(tmp_path, fake_sockseek):
    from setdl.core import App
    a = App(tmp_path / "data", sockseek=str(fake_sockseek))
    assert a.settings.get().music_dir == str(tmp_path / "home" / "Music" / "1001Tracklists")
    a.update_settings({"music_dir": str(tmp_path / "m"), "mashups": "original"})
    a.shutdown()
    b = App(tmp_path / "data")
    assert b.settings.get().music_dir == str(tmp_path / "m") and b.settings.get().mashups == "original"
    b.shutdown()


def serve(app, web_dir):
    s = Server(app, web_dir=web_dir)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_the_built_ui_is_served(app, tmp_path):
    web = tmp_path / "web" / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><div id=root></div>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "web" / "secret.txt").write_text("no")
    s = serve(app, web)
    try:
        c = Client(s)
        status, body, resp = c.raw("GET", "/", token=False)
        assert status == 200 and b"id=root" in body and "default-src 'self'" in resp.getheader("Content-Security-Policy")
        status, body, resp = c.raw("GET", "/assets/app.js", token=False)
        assert status == 200 and resp.getheader("Content-Type").startswith("text/javascript")
        assert c.raw("GET", "/sets/some-route", token=False)[1].startswith(b"<!doctype html>")   # the page's routes
        assert c.raw("HEAD", "/", token=False)[0] == 200
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/missing.js"):
            assert c.raw("GET", path, token=False)[0] == 404, path
    finally:
        s.close()


def test_placeholder_until_the_ui_is_built(client):
    status, body, resp = client.raw("GET", "/", token=False)
    assert status == 200 and b"Set Downloader" in body and b"npm run build" in body


def test_open_url(client, monkeypatch):
    opened = []
    monkeypatch.setattr("setdl.core.open_url", opened.append)
    assert client.post("/api/open-url", {"url": "https://www.1001tracklists.com/tracklist/x.html"})[0] == 200
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "slsk://a/b", "/Applications/Calculator.app"):
        assert client.post("/api/open-url", {"url": bad})[0] == 400
    assert opened == ["https://www.1001tracklists.com/tracklist/x.html"]


@pytest.mark.parametrize("name", ["settings.json", "sets.json"])
def test_broken_saved_files_are_ignored(tmp_path, name):
    from setdl.core import App
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / name).write_text("{not json")
    a = App(tmp_path / "data", music_dir=str(tmp_path / "m"))
    assert a.settings.get().mashups == "components"
    assert a.mashups_for(tmp_path / "m" / "x") == "components"
    a.shutdown()
