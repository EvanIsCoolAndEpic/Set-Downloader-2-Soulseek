"""The sets in the music folder: one folder each, made by "tl2mixxx run" (it holds a copy of the
set's page, sockseek's index, the tracks and the playlist). A set's id is its folder's name."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from tl2mixxx import cli
from tl2mixxx import fixes as fx
from tl2mixxx import sockseek as ss
from tl2mixxx.tracklist import parse_file

from .errors import ApiError, bad_request, not_found
from .jobs import iso


def web_recording(tl) -> str:
    """The set's recording when it's a web address. A tracklist (maybe shared) never names a file
    on this Mac: tl2mixxx cut refuses one."""
    rec = str(tl.recording or "")
    return rec if rec.lower().startswith(("https://", "http://")) else ""


def music_root(music_dir: str | Path) -> Path:
    return Path(music_dir).expanduser().resolve()


def check_set_id(set_id: object) -> str:
    """A folder name: one path component, nothing that climbs out of the music folder."""
    if (not isinstance(set_id, str) or not set_id or set_id in (".", "..") or len(set_id) > 255
            or any(c in set_id for c in "/\\\x00")):
        raise bad_request("That isn't a set's name.", "bad_set_id")
    return set_id


def set_folder(music_dir: str | Path, set_id: object) -> Path:
    """The folder of the set with this id. It must be right inside the music folder (a link
    to somewhere else doesn't count) and hold a copy of the set's page."""
    set_id = check_set_id(set_id)
    root = music_root(music_dir)
    folder = (root / set_id).resolve()
    if folder.parent != root:
        raise ApiError(403, "outside_music_dir", "That set isn't in the music folder.")
    if not folder.is_dir() or cli.page_copy(folder) is None:
        raise not_found(f'There\'s no set called "{set_id}" in the music folder.')
    return folder


def inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _stamp(folder: Path) -> tuple:
    """Changes when anything a set's summary depends on changes. The folder's own time changes
    when a file in it comes or goes (a track deleted by hand, say)."""
    names = (*cli.COPY_NAMES, ss.INDEX_NAME, fx.FIXES_NAME, f"{folder.name}.m3u8")
    return (_mtime(folder),) + tuple(_mtime(folder / n) for n in names)


def updated_time(folder: Path) -> float:
    """When the set's files last changed: its playlist, sockseek's index, the fixes or the page."""
    names = (f"{folder.name}.m3u8", ss.INDEX_NAME, fx.FIXES_NAME, *cli.COPY_NAMES)
    return max((_mtime(folder / n) for n in names), default=0.0) or _mtime(folder)


def copy_source(page: Path | None) -> str:
    """ "page" (a saved page), "text" (pasted) or "resolved" (any other input, kept as JSON)."""
    name = page.name if page else ""
    return {cli.TEXT_COPY_NAME: "text", cli.JSON_COPY_NAME: "resolved"}.get(name, "page")


def summarize(folder: Path, mashups: str) -> dict:
    """Found / missing / total for a set folder, as "tl2mixxx tracks" and a retry count them."""
    page = cli.page_copy(folder)
    out = {"id": folder.name, "name": folder.name, "title": folder.name, "url": "",
           "source": copy_source(page), "kind": "", "recording": "", "cues": 0,
           "folder": str(folder), "m3u": "", "mashups": mashups, "downloaded": False,
           "found": 0, "missing": 0, "total": 0, "error": None}
    m3u = folder / f"{folder.name}.m3u8"
    if m3u.is_file():
        out["m3u"] = str(m3u)
    try:
        try:
            r = cli.resolve_set(folder, mashups=mashups)
            tl = r.tl
            out.update(downloaded=(folder / ss.INDEX_NAME).exists(),
                       found=len(r.found), missing=len(r.missing), total=len(r.found) + len(r.missing))
        except cli.SkipSet:
            # Nothing downloaded yet: everything it will search for is missing
            tl = parse_file(page)
            chosen = cli.choose_tracks(tl, mashups, fx.by_row(tl, fx.load(folder)))
            out.update(missing=len(chosen), total=len(chosen))
        out.update(title=tl.title, url=tl.url, kind=tl.source_kind, recording=web_recording(tl),
                   cues=sum(t.cue is not None for t in tl.tracks))
    except (ValueError, OSError) as e:
        out["error"] = f"Couldn't read the set's page: {e}"
    # A pasted tracklist's copy has no title of its own (it reads as "_tracklist"): the folder's
    # name is the set's name
    if out["source"] == "text":
        out["title"] = folder.name
    return out


class SetLibrary:
    """Lists the sets of a music folder. Summaries are kept until the set's files change: reading
    a page and matching its files takes a moment."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[tuple, dict] = {}

    def summary(self, folder: Path, mashups: str) -> dict:
        key = (str(folder), mashups)
        stamp = _stamp(folder)
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[0] == stamp:
            out = dict(hit[1])
        else:
            out = summarize(folder, mashups)
            with self._lock:
                self._cache[key] = (stamp, dict(out))
        ts = updated_time(folder)
        out["updated"] = iso(ts)
        out["updated_ts"] = ts
        return out

    def forget(self, folder: Path) -> None:
        with self._lock:
            for key in [k for k in self._cache if k[0] == str(folder)]:
                del self._cache[key]

    def folders(self, music_dir: str | Path) -> list[Path]:
        """The set folders right inside the music folder (not ones starting with "." or "_",
        like the Mixxx fork's "_pasted tracklists")."""
        root = music_root(music_dir)
        try:
            entries = sorted(root.iterdir())
        except OSError:
            return []
        out = []
        for entry in entries:
            if entry.name.startswith((".", "_")):
                continue
            try:
                folder = entry.resolve()
                if folder.parent == root and folder.is_dir() and cli.page_copy(folder) is not None:
                    out.append(folder)
            except OSError:
                continue
        return out


def read_tracks(command: list[str], folder: Path, mashups: str, cwd: Path, env: dict | None = None,
                timeout: float = 120) -> dict:
    """A set's tracks with the file each one has, from "tl2mixxx tracks" (the rows Fix Tracks
    works with: status, file, fix, key, identity, fix_in_use, retry_query...)."""
    try:
        proc = subprocess.run(command + ["tracks", str(folder), f"--mashups={mashups}"],
                              stdin=subprocess.DEVNULL, capture_output=True, cwd=cwd, env=env,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ApiError(500, "tracks_failed", f"Couldn't read the set's tracks: {e}")
    if proc.returncode != 0:
        lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        why = lines[-1] if lines else f"tl2mixxx exited with code {proc.returncode}"
        raise ApiError(500, "tracks_failed", f"Couldn't read the set's tracks: {why}")
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError as e:
        raise ApiError(500, "tracks_failed", f"Couldn't read the set's tracks: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("tracks"), list):
        raise ApiError(500, "tracks_failed", "Couldn't read the set's tracks: unexpected output")
    return data
