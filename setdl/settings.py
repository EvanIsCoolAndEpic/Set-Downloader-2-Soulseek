"""The app's settings (settings.json) and what it remembers per set (sets.json), both in its
own folder."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .errors import bad_request

MASHUPS = ("components", "original", "both")


@dataclass
class Settings:
    music_dir: str            # each set gets a folder in here
    sockseek: str = ""        # path to sockseek; "" = find it automatically
    mashups: str = "components"


def write_json(path: Path, data: dict) -> None:
    """Write a JSON file in one go, so a crash can't leave half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def has_control_chars(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def check_music_dir(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Choose a folder for the sets.", "bad_music_dir")
    if has_control_chars(value):
        raise bad_request("The music folder's path has characters a folder can't have.", "bad_music_dir")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise bad_request("Give the music folder's full path, like /Users/you/Music/1001Tracklists.",
                          "bad_music_dir")
    path = Path(os.path.normpath(path))
    if path == Path(path.anchor):
        raise bad_request("The music folder can't be the whole disk.", "bad_music_dir")
    if path.exists() and not path.is_dir():
        raise bad_request(f"{path} is a file, not a folder.", "bad_music_dir")
    return str(path)


def check_sockseek(value: object) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    if not isinstance(value, str) or has_control_chars(value):
        raise bad_request("That isn't a path to a program.", "bad_sockseek")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise bad_request("Give sockseek's full path, or leave it empty to find it automatically.",
                          "bad_sockseek")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise bad_request(f"There's no program at {path}.", "bad_sockseek")
    return str(path)


def check_mashups(value: object) -> str:
    if value not in MASHUPS:
        raise bad_request('mashups is one of "components", "original" or "both".', "bad_mashups")
    return str(value)


CHECKS = {"music_dir": check_music_dir, "sockseek": check_sockseek, "mashups": check_mashups}


class SettingsStore:
    """settings.json. Values given on the command line (dev mode) replace the saved ones for
    this launch; saving writes what is in use."""

    def __init__(self, path: Path, default_music_dir: Path, overrides: dict | None = None):
        self.path = path
        self._lock = threading.Lock()
        saved = read_json(path)
        values = {"music_dir": str(default_music_dir)}
        for f in fields(Settings):
            v = saved.get(f.name)
            if isinstance(v, str) and (f.name != "mashups" or v in MASHUPS):
                values[f.name] = v
        values.update({k: v for k, v in (overrides or {}).items() if v is not None})
        self._settings = Settings(**values)

    def get(self) -> Settings:
        with self._lock:
            return Settings(**asdict(self._settings))

    def update(self, changes: dict) -> Settings:
        unknown = sorted(set(changes) - set(CHECKS))
        if unknown:
            raise bad_request(f"Unknown setting: {', '.join(unknown)}", "unknown_setting")
        checked = {k: CHECKS[k](v) for k, v in changes.items()}
        with self._lock:
            for k, v in checked.items():
                setattr(self._settings, k, v)
            write_json(self.path, asdict(self._settings))
            return Settings(**asdict(self._settings))


class SetPrefs:
    """What the user chose per set (only the mashups choice for now), by the set's folder."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def mashups(self, folder: Path, default: str) -> str:
        with self._lock:
            value = read_json(self.path).get(str(folder), {}).get("mashups")
        return value if value in MASHUPS else default

    def set_mashups(self, folder: Path, mashups: str) -> None:
        with self._lock:
            data = read_json(self.path)
            entry = data.get(str(folder))
            entry = entry if isinstance(entry, dict) else {}
            if entry.get("mashups") == mashups:
                return
            entry["mashups"] = mashups
            data[str(folder)] = entry
            write_json(self.path, data)
