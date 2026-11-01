"""yt-dlp: which copy tl2mixxx uses, and updating it.

tl2mixxx uses yt-dlp as a library. The app has one built in, and YouTube changes often enough that
it goes stale. "Update yt-dlp" downloads the latest release from yt-dlp's own GitHub releases: the
"yt-dlp" file, which is the library zipped (it also runs as a program with Python). It's checked
against the release's SHA2-256SUMS, then a child process must import it and report its version.
Only then is it kept, in <data dir>/yt-dlp/, and the app's children import it before the built-in
copy (prefer()). The built-in copy stays as the fallback: "Use the built-in one" forgets the update.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .jobs import iso
from .settings import read_json, write_json

ENV = "SETDL_YTDLP"     # the updated copy, for the app's children (see prefer_from_env)
RELEASES_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
ASSET = "yt-dlp"        # the platform-independent release: the library as a zip
SUMS = "SHA2-256SUMS"
# Where a release and its files may come from (downloads redirect to githubusercontent.com)
HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com",
         "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"}
MAX_BYTES = 40 * 1024 * 1024
TIMEOUT = 30


class UpdateError(RuntimeError):
    pass


# ------------------------------------------------------------------ in the children

class _PreferZip(importlib.abc.MetaPathFinder):
    """Finds yt_dlp and its modules in the updated copy first (also ahead of PyInstaller's
    importer, which holds the built-in one). Anything not in the zip falls through."""

    def __init__(self, path: str):
        self.path = path

    def find_spec(self, name, path=None, target=None):
        if name != "yt_dlp" and not name.startswith("yt_dlp."):
            return None
        return importlib.machinery.PathFinder.find_spec(name, [self.path] if path is None else path, target)


def prefer(path: str | Path) -> None:
    if not any(isinstance(f, _PreferZip) for f in sys.meta_path):
        sys.meta_path.insert(0, _PreferZip(str(path)))


def prefer_from_env() -> None:
    """In a child the app started: use the updated yt-dlp if the app passed one."""
    path = os.environ.get(ENV)
    if path and Path(path).is_file():
        prefer(path)


# ------------------------------------------------------------------ downloading

class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in HOSTS:
        raise UpdateError(f"The download went somewhere unexpected ({u.hostname or url}).")


def fetch(url: str, limit: int = MAX_BYTES) -> bytes:
    """A file from GitHub over HTTPS, redirects included, at most limit bytes (tests replace this)."""
    check_url(url)
    opener = urllib.request.build_opener(_CheckedRedirects)
    req = urllib.request.Request(url, headers={"User-Agent": "Set-Downloader", "Accept": "*/*"})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            chunks, total = [], 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UpdateError("The download is much bigger than yt-dlp should be.")
                chunks.append(chunk)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"GitHub answered {e.code} for {urllib.parse.urlsplit(url).path}.") from None
    except (urllib.error.URLError, OSError) as e:
        why = getattr(e, "reason", e)
        raise UpdateError(f"Couldn't reach GitHub ({why}). Check the internet connection.") from None
    return b"".join(chunks)


def expected_sha256(sums: str, name: str = ASSET) -> str:
    """The checksum SHA2-256SUMS lists for a file ("<hex>  <name>" lines)."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise UpdateError(f"The release's {SUMS} doesn't list {name}.")


def bundled_version() -> str | None:
    """The built-in yt-dlp's version, from its package metadata ("" if there's no metadata to read;
    None if it isn't there at all)."""
    import importlib.metadata
    import importlib.util
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        return "" if importlib.util.find_spec("yt_dlp") is not None else None
    except (ImportError, ValueError):
        return None


# ------------------------------------------------------------------ the app's side

class Ytdlp:
    """The yt-dlp in use, and the update. on_change() is called when the status changes."""

    def __init__(self, data_dir: Path, helper_command: list[str], cwd: Path, env: Callable[[], dict],
                 on_change: Callable[[], None] = lambda: None):
        self.dir = Path(data_dir) / "yt-dlp"
        self.helper_command = list(helper_command)
        self.cwd = cwd
        self.env = env
        self.on_change = on_change
        self._lock = threading.Lock()
        self._bundled: str | None = None
        self._bundled_read = False
        self.updating = False
        self.step = ""
        self.message = ""
        self.error = ""
        self.checked: float | None = None

    def current(self) -> dict | None:
        """The update in use: {"version", "file", "sha256", "updated"}, if there is one."""
        data = read_json(self.dir / "current.json")
        file = data.get("file")
        if not isinstance(file, str) or not data.get("version"):
            return None
        path = self.dir / Path(file).name
        return dict(data, path=str(path)) if path.is_file() else None

    def child_env(self) -> dict:
        cur = self.current()
        return {ENV: cur["path"]} if cur else {}

    def _bundled_version(self) -> str | None:
        if not self._bundled_read:
            self._bundled = bundled_version()
            self._bundled_read = True
            if self._bundled == "":
                # No metadata (the built app): ask the library itself, in the background
                threading.Thread(target=self._read_bundled, name="yt-dlp-version", daemon=True).start()
        return self._bundled

    def _read_bundled(self) -> None:
        got = self.run_check(None)
        with self._lock:
            self._bundled = got.get("version") or None if got else None
        self.on_change()

    def status(self) -> dict:
        cur = self.current()
        bundled = self._bundled_version()
        if cur:
            version, source = cur["version"], "updated"
        elif bundled is not None:
            version, source = bundled or None, "bundled"
        else:
            version, source = None, None
        return {"version": version, "source": source, "bundled": bundled or None,
                "updated": cur.get("updated") if cur else None, "updating": self.updating, "step": self.step,
                "message": self.message, "error": self.error, "checked": iso(self.checked)}

    def run_check(self, zip_path: Path | None, timeout: float = 60) -> dict | None:
        """A child imports yt-dlp (the zip, or whatever it would use) and says which version it got."""
        args = ["ytdlp-version"] + ([f"--zip={zip_path}"] if zip_path else [])
        env = dict(self.env())
        env.pop(ENV, None)
        try:
            proc = subprocess.run(self.helper_command + args, stdin=subprocess.DEVNULL, capture_output=True,
                                  cwd=self.cwd, env=env, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        lines = proc.stdout.decode("utf-8", "replace").strip().splitlines()
        try:
            data = json.loads(lines[-1]) if proc.returncode == 0 and lines else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def start_update(self) -> bool:
        """Starts updating in the background. False if an update is running already."""
        with self._lock:
            if self.updating:
                return False
            self.updating, self.step, self.message, self.error = True, "Asking GitHub for the latest release", "", ""
        self.on_change()
        threading.Thread(target=self._update, name="yt-dlp-update", daemon=True).start()
        return True

    def _set_step(self, step: str) -> None:
        with self._lock:
            self.step = step
        self.on_change()

    def _update(self) -> None:
        try:
            message = self.update()
            with self._lock:
                self.message, self.error = message, ""
        except UpdateError as e:
            with self._lock:
                self.message, self.error = "", str(e)
        except Exception as e:   # never a stuck "updating"
            with self._lock:
                self.message, self.error = "", f"The update failed: {e}"
        finally:
            with self._lock:
                self.updating, self.step, self.checked = False, "", time.time()
            self.on_change()

    def update(self) -> str:
        """Download, check and keep the latest yt-dlp. Returns what happened, for people."""
        try:
            release = json.loads(fetch(RELEASES_API, 2 * 1024 * 1024).decode("utf-8"))
        except ValueError:
            raise UpdateError("GitHub's answer about the latest release couldn't be read.") from None
        tag = str(release.get("tag_name") or "").strip()
        assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or []
                  if isinstance(a, dict)}
        if not re.fullmatch(r"[\w.\-]{1,40}", tag) or not assets.get(ASSET) or not assets.get(SUMS):
            raise UpdateError("The latest yt-dlp release doesn't have the file Set Downloader needs.")
        cur = self.current()
        if cur and cur["version"] == tag:
            return f"Already up to date: yt-dlp {tag}."
        if not cur and self._bundled_version() == tag:
            return f"The built-in yt-dlp {tag} is already the latest."
        self._set_step(f"Downloading yt-dlp {tag}")
        sums = fetch(str(assets[SUMS]), 256 * 1024).decode("utf-8", "replace")
        want = expected_sha256(sums)
        data = fetch(str(assets[ASSET]))
        if hashlib.sha256(data).hexdigest() != want:
            raise UpdateError("The download doesn't match the release's checksum, so it wasn't used.")
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            raise UpdateError("The download isn't the yt-dlp library, so it wasn't used.") from None
        if not {"yt_dlp/__init__.py", "yt_dlp/version.py"} <= names:
            raise UpdateError("The download isn't the yt-dlp library, so it wasn't used.")
        self._set_step(f"Checking yt-dlp {tag}")
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / f"yt-dlp-{tag}.zip"
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        os.replace(part, target)
        got = self.run_check(target)
        if not got or not got.get("from_zip") or not got.get("version"):
            target.unlink(missing_ok=True)
            raise UpdateError(f"yt-dlp {tag} didn't start here, so the built-in one stays in use.")
        write_json(self.dir / "current.json", {"version": str(got["version"]), "file": target.name,
                                               "sha256": want, "updated": iso(time.time())})
        for old in self.dir.glob("yt-dlp-*.zip"):
            if old != target:
                old.unlink(missing_ok=True)
        return f"Updated to yt-dlp {got['version']}."

    def revert(self) -> None:
        """Forget the update: the built-in yt-dlp is used again."""
        with self._lock:
            if self.updating:
                raise UpdateError("An update is running: wait for it to finish.")
            (self.dir / "current.json").unlink(missing_ok=True)
            for old in self.dir.glob("yt-dlp-*.zip"):
                old.unlink(missing_ok=True)
            self.message, self.error = "Using the built-in yt-dlp again.", ""
        self.on_change()
