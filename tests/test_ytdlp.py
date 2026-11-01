"""yt-dlp: the version in use, and updating it from GitHub's releases (faked here: a made-up
release whose "yt-dlp" zip holds a tiny yt_dlp package)."""

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import pytest

from setdl import ytdlp

API = ytdlp.RELEASES_API
ZIP_URL = "https://github.com/yt-dlp/yt-dlp/releases/download/2099.01.01/yt-dlp"
SUMS_URL = "https://github.com/yt-dlp/yt-dlp/releases/download/2099.01.01/SHA2-256SUMS"


def release_zip(version="2099.01.01") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("__main__.py", "print('yt-dlp')\n")
        z.writestr("yt_dlp/__init__.py", "")
        z.writestr("yt_dlp/version.py", f"__version__ = {version!r}\n")
    return b"#!/usr/bin/env python3\n" + buf.getvalue()    # like the release: a zip with a #! line


@pytest.fixture
def github(monkeypatch):
    """A made-up latest release. Returns the files it serves, to change in a test."""
    data = release_zip()
    files = {
        API: json.dumps({"tag_name": "2099.01.01", "assets": [
            {"name": "yt-dlp", "browser_download_url": ZIP_URL},
            {"name": "SHA2-256SUMS", "browser_download_url": SUMS_URL},
            {"name": "yt-dlp_macos", "browser_download_url": ZIP_URL + "_macos"}]}).encode(),
        ZIP_URL: data,
        SUMS_URL: f"{'0' * 64}  yt-dlp_macos\n{hashlib.sha256(data).hexdigest()}  yt-dlp\n".encode(),
    }
    asked = []

    def fetch(url, limit=ytdlp.MAX_BYTES):
        asked.append(url)
        ytdlp.check_url(url)
        if url not in files:
            raise ytdlp.UpdateError(f"GitHub answered 404 for {url}.")
        return files[url]
    monkeypatch.setattr(ytdlp, "fetch", fetch)
    files["asked"] = asked
    return files


def wait_ytdlp(client, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.ok("GET", "/api/state")["ytdlp"]
        if not status["updating"]:
            return status
        time.sleep(0.1)
    raise AssertionError("still updating")


def test_the_built_in_version(client):
    import importlib.metadata
    status = client.ok("GET", "/api/state")["ytdlp"]
    assert status["version"] == importlib.metadata.version("yt-dlp") and status["source"] == "bundled"
    assert not status["updating"] and status["error"] == ""


def test_updating(client, app, github, tmp_path):
    status, data = client.post("/api/ytdlp/update")
    assert status == 202 and data["ytdlp"]["updating"]
    status = wait_ytdlp(client)
    assert status["error"] == "" and status["message"] == "Updated to yt-dlp 2099.01.01."
    assert status["version"] == "2099.01.01" and status["source"] == "updated" and status["updated"]
    kept = tmp_path / "data" / "yt-dlp" / "yt-dlp-2099.01.01.zip"
    assert kept.is_file()
    # The app's children import it before the built-in one
    env = app.child_env()
    assert env[ytdlp.ENV] == str(kept)
    out = subprocess.run([*app.helper_command, "ytdlp-version"], env=env, capture_output=True, text=True, timeout=60)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["version"] == "2099.01.01" and got["from_zip"], out
    # tl2mixxx too (through the app's own entry)
    code = ("import sys; sys.argv=['x']; from setdl import app; from setdl.ytdlp import prefer_from_env; "
            "prefer_from_env(); import yt_dlp.version; print(yt_dlp.version.__version__)")
    out = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "2099.01.01", out.stderr
    # Asking again: nothing to download
    client.post("/api/ytdlp/update")
    assert wait_ytdlp(client)["message"] == "Already up to date: yt-dlp 2099.01.01."
    # Back to the built-in one
    status, data = client.call("DELETE", "/api/ytdlp/update")
    assert status == 200 and data["ytdlp"]["source"] == "bundled" and not kept.exists()
    assert ytdlp.ENV not in app.child_env()


def test_a_download_that_doesnt_match_the_checksum_isnt_used(client, github, tmp_path):
    github[ZIP_URL] = release_zip("2099.06.06")
    client.post("/api/ytdlp/update")
    status = wait_ytdlp(client)
    assert "checksum" in status["error"] and status["source"] == "bundled"
    assert not list((tmp_path / "data").glob("yt-dlp/*.zip"))


def test_a_download_that_doesnt_start_isnt_used(client, github, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("yt_dlp/__init__.py", "raise ImportError('broken')\n")
        z.writestr("yt_dlp/version.py", "__version__ = '2099.01.01'\n")
    github[ZIP_URL] = buf.getvalue()
    github[SUMS_URL] = f"{hashlib.sha256(buf.getvalue()).hexdigest()}  yt-dlp\n".encode()
    client.post("/api/ytdlp/update")
    status = wait_ytdlp(client)
    assert "didn't start" in status["error"] and status["source"] == "bundled"
    assert not list((tmp_path / "data").glob("yt-dlp/*.zip"))


def test_not_the_library(client, github):
    github[ZIP_URL] = b"not a zip"
    github[SUMS_URL] = f"{hashlib.sha256(b'not a zip').hexdigest()}  yt-dlp\n".encode()
    client.post("/api/ytdlp/update")
    assert "isn't the yt-dlp library" in wait_ytdlp(client)["error"]


def test_github_unreachable(client, github):
    del github[API]
    client.post("/api/ytdlp/update")
    assert "404" in wait_ytdlp(client)["error"]


def test_only_githubs_hosts():
    for url in ("http://github.com/x", "https://evil.example/yt-dlp", "https://github.com.evil.example/x",
                "file:///etc/passwd"):
        with pytest.raises(ytdlp.UpdateError):
            ytdlp.check_url(url)
    ytdlp.check_url("https://objects.githubusercontent.com/github-production-release-asset/x")


def test_the_checksum_line():
    assert ytdlp.expected_sha256("a" * 64 + "  yt-dlp.exe\n" + "B" * 64 + "  yt-dlp\n") == "b" * 64
    with pytest.raises(ytdlp.UpdateError):
        ytdlp.expected_sha256("a" * 64 + "  yt-dlp_macos\n")


def test_the_update_needs_the_token(client):
    assert client.post("/api/ytdlp/update", token=False)[0] == 401
