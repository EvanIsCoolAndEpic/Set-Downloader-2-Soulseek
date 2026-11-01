"""Where things are: the app's own folder, the music folder, the programs it runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def frozen() -> bool:
    """Running as the built app (PyInstaller), not from source."""
    return bool(getattr(sys, "frozen", False))


def default_data_dir() -> Path:
    """Settings, the Soulseek login and scratch files ($SETDL_DATA_DIR overrides)."""
    env = os.environ.get("SETDL_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "set-downloader"


def default_music_dir() -> Path:
    """Where sets go unless the settings say otherwise: the same folder the Mixxx fork and
    tl2mixxx use, so sets downloaded there show up ($SETDL_MUSIC_DIR overrides)."""
    env = os.environ.get("SETDL_MUSIC_DIR")
    return Path(env).expanduser() if env else Path.home() / "Music" / "1001Tracklists"


def mixxx_login_path() -> Path:
    """The Soulseek login the Mixxx fork saves ($SETDL_MIXXX_LOGIN overrides, for tests).
    Only ever checked for existence and handed to sockseek with -c: never read here."""
    env = os.environ.get("SETDL_MIXXX_LOGIN")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Mixxx" / "1001tracklists-sockseek.conf"
    return Path.home() / ".mixxx" / "1001tracklists-sockseek.conf"


def tl2mixxx_command() -> list[str]:
    """How to run the tl2mixxx CLI. The built app has no "python -m": its own executable runs
    tl2mixxx when its first argument is --tl2mixxx (see app.main). From source, -I keeps the
    child from importing anything from its working folder or PYTHON* variables."""
    if frozen():
        return [sys.executable, "--tl2mixxx"]
    return [sys.executable, "-I", "-u", "-X", "utf8", "-m", "tl2mixxx"]


def bundled_sockseek() -> Path | None:
    """The sockseek shipped inside the app: Set Downloader.app/Contents/Resources/sockseek."""
    if not frozen():
        return None
    exe = Path(sys.executable).resolve()
    candidates = [exe.parent.parent / "Resources" / "sockseek"]
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "sockseek")
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def web_dist_dir() -> Path:
    """The built UI ($SETDL_WEB_DIST overrides): web/dist from source, web/dist inside the app."""
    env = os.environ.get("SETDL_WEB_DIST")
    if env:
        return Path(env).expanduser()
    if frozen():
        exe = Path(sys.executable).resolve()
        for c in (exe.parent.parent / "Resources" / "web" / "dist",
                  Path(getattr(sys, "_MEIPASS", exe.parent)) / "web" / "dist"):
            if c.is_dir():
                return c
    return Path(__file__).resolve().parent.parent / "web" / "dist"


def extend_path() -> None:
    """An app started from the Finder gets a bare PATH: add where sockseek usually is, so it
    can be found automatically (the same places the Mixxx fork looks)."""
    home = Path.home()
    extra = ["/opt/homebrew/bin", "/usr/local/bin", str(home / ".local" / "bin"), str(home / ".dotnet" / "tools")]
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    os.environ["PATH"] = os.pathsep.join(dirs + [d for d in extra if d not in dirs])
