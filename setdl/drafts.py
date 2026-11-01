"""Files the page hands over, kept in the app's scratch folder until they're used:

- drafts: a tracklist parsed to show what will be downloaded before anything starts. A dropped
  1001Tracklists page (.html), a .txt list or pasted text is kept as it is; anything else (a link,
  a CSV, a picture...) is kept as the JSON "tl2mixxx resolve" made of it (resolve.py), with the
  other tracklists it found to pick from;
- uploads: an audio file of the user's own, for fixing a track (tl2mixxx copies it into the set).
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from tl2mixxx import cli
from tl2mixxx import fixes as fx
from tl2mixxx.tracklist import ALBUM, MASHUP, Tracklist, parse_file

from .errors import ApiError, bad_request, not_found
from .sets import music_root, web_recording
from .settings import MASHUPS

PAGE_LIMIT = 20 * 1024 * 1024        # a saved page, bytes
TEXT_LIMIT = 2 * 1024 * 1024         # pasted text (the JSON body), bytes
UPLOAD_LIMIT = 600 * 1024 * 1024     # one audio file, bytes
ID_PATTERN = re.compile(r"[0-9a-f]{16}")
CHUNK = 1024 * 1024


def new_id() -> str:
    return secrets.token_hex(8)


def safe_name(name: str, default: str, max_len: int = 100) -> str:
    """A file name of its own: no folders, nothing a file name can't have."""
    name = re.split(r"[/\\]", name or "")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f\x7f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:max_len - len(ext) - 1].rstrip(" .") + "." + ext) if dot and len(ext) <= 8 else name[:max_len]
    return name or default


def remove_old(root: Path, max_age_s: float) -> None:
    """Scratch folders nobody used: drafts and uploads from earlier launches."""
    cutoff = time.time() - max_age_s
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir() and ID_PATTERN.fullmatch(entry.name) and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass


class Drafts:
    def __init__(self, root: Path):
        self.root = root

    def _folder(self, draft_id: object) -> Path:
        if not isinstance(draft_id, str) or not ID_PATTERN.fullmatch(draft_id):
            raise not_found("There's no such draft (it may be from an earlier launch).", "no_draft")
        return self.root / draft_id

    def page(self, draft_id: object) -> Path:
        """The draft's tracklist file."""
        folder = self._folder(draft_id)
        meta = folder / "draft.json"
        try:
            name = json.loads(meta.read_text(encoding="utf-8"))["file"]
        except (OSError, ValueError, KeyError, TypeError):
            raise not_found("There's no such draft (it may be from an earlier launch).", "no_draft")
        path = folder / safe_name(str(name), "tracklist.html")
        if not path.is_file():
            raise not_found("There's no such draft (it may be from an earlier launch).", "no_draft")
        return path

    def _create(self, file_name: str, data: bytes, source: str) -> str:
        draft_id = new_id()
        folder = self.root / draft_id
        folder.mkdir(parents=True)
        path = folder / file_name
        path.write_bytes(data)
        try:
            parse_file(path)
        except (ValueError, OSError) as e:
            shutil.rmtree(folder, ignore_errors=True)
            raise ApiError(422, "not_a_tracklist", str(e))
        (folder / "draft.json").write_text(json.dumps({"file": file_name, "source": source,
                                                       "created": time.time()}), encoding="utf-8")
        return draft_id

    def create_page(self, name: str, data: bytes) -> str:
        """A dropped file: a saved page, or a tracklist saved as .txt."""
        if not data.strip():
            raise bad_request("The file is empty.", "empty")
        name = safe_name(name, "tracklist.html")
        stem, dot, ext = name.rpartition(".")
        stem = stem if dot else name
        if ext.lower() == "txt" and dot:
            return self._create(f"{stem}.txt", data, "text")
        return self._create(f"{stem}.html", data, "page")

    def create_text(self, text: object, title: object = None) -> str:
        """Pasted text: the set's name on the first line, then one track per line. A title given
        separately goes first. Without either, the set is named after when it was pasted (to the
        second: two such sets must not share a folder)."""
        if not isinstance(text, str) or not text.strip():
            raise bad_request("Paste a tracklist first.", "empty")
        if title is not None and not isinstance(title, str):
            raise bad_request("title is text.", "bad_title")
        if title and title.strip():
            text = title.strip().splitlines()[0] + "\n" + text
        stem = f"Pasted tracklist {datetime.now():%Y-%m-%d %H.%M.%S}"
        return self._create(f"{stem}.txt", text.strip().encode("utf-8") + b"\n", "text")

    def delete(self, draft_id: object) -> None:
        folder = self._folder(draft_id)
        if not folder.is_dir():
            raise not_found("There's no such draft (it may be from an earlier launch).", "no_draft")
        shutil.rmtree(folder, ignore_errors=True)

    def reserve(self) -> tuple[str, Path]:
        """A folder for a draft that "tl2mixxx resolve" is making. It's no draft until
        finish_resolved (or discard) is called."""
        draft_id = new_id()
        folder = self.root / draft_id
        folder.mkdir(parents=True)
        return draft_id, folder

    def discard(self, draft_id: str) -> None:
        shutil.rmtree(self._folder(draft_id), ignore_errors=True)

    def finish_resolved(self, draft_id: str, out: Path, origin: dict, default_title: str) -> str:
        """The JSON resolve wrote becomes the draft. A tracklist without a title (a picture, say)
        is named default_title."""
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            tl = Tracklist.from_json(data)
        except (OSError, ValueError) as e:
            self.discard(draft_id)
            raise ApiError(422, "not_a_tracklist", f"tl2mixxx's tracklist couldn't be read: {e}")
        if not tl.tracks:
            self.discard(draft_id)
            raise ApiError(422, "not_a_tracklist", "No tracks found.")
        if not str(data.get("title") or "").strip():
            data["title"] = default_title
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        (out.parent / "draft.json").write_text(json.dumps({"file": out.name, "source": "resolved",
                                                           "created": time.time(), "origin": origin}),
                                               encoding="utf-8")
        return draft_id

    def meta(self, draft_id: str) -> dict:
        try:
            data = json.loads((self._folder(draft_id) / "draft.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def source(self, draft_id: str) -> str:
        source = self.meta(draft_id).get("source")
        return source if source in ("page", "text", "resolved") else "page"


def resolved_extras(page: Path) -> dict:
    """What resolve says besides the tracklist: the other tracklists it found (without their
    tracks), which one is taken and where it came from, and its warnings."""
    out = {"picked": 0, "from": None, "alternatives": [], "warnings": []}
    if page.suffix.lower() != ".json":
        return out
    try:
        data = json.loads(page.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    alternatives = data.get("alternatives") if isinstance(data.get("alternatives"), list) else []
    keys = ("pick", "source", "label", "count", "cues", "likes", "author", "pinned", "by_uploader", "score")
    out["alternatives"] = [{k: a.get(k) for k in keys} for a in alternatives if isinstance(a, dict)]
    out["picked"] = data.get("picked") if isinstance(data.get("picked"), int) else 0
    out["warnings"] = [str(w) for w in data.get("warnings") or [] if isinstance(w, str)]
    was = data.get("from")
    if isinstance(was, dict) and isinstance(was.get("source"), str):
        out["from"] = {"source": was["source"], "label": str(was.get("label") or "")}
    return out


def draft_info(draft_id: str, source: str, page: Path, music_dir: str | Path, default_mashups: str,
               origin: dict | None = None) -> dict:
    """What the page shows before downloading: the set's tracks and which ones are downloaded under
    each mashups choice, whether the set was downloaded before (into the same folder), and where
    the tracklist came from."""
    try:
        tl = parse_file(page)
    except (ValueError, OSError) as e:
        raise ApiError(422, "not_a_tracklist", str(e))
    root = music_root(music_dir)
    folder = cli.set_folder(root, tl.title, tl)
    exists = folder.parent == root and folder.is_dir() and cli.page_copy(folder) is not None
    # Fixes made before count: an ID the user gave a file is downloaded too
    fixes = fx.by_row(tl, fx.load(folder)) if exists else {}
    chosen = {m: {t.index for t in cli.choose_tracks(tl, m, fixes)} for m in MASHUPS}
    tracks = [{
        "row": t.index, "number": t.number, "kind": t.kind, "artist": t.artist, "title": t.title,
        "display": t.display, "label": t.label, "duration": t.duration, "cue": t.cue,
        "unidentified": t.unidentified, "mashup_of": t.mashup_of,
        "downloads": {m: t.index in chosen[m] for m in MASHUPS},
    } for t in tl.tracks]
    extras = resolved_extras(page)
    picked = next((a for a in extras["alternatives"] if a.get("pick") == extras["picked"]), None)
    return {
        "id": draft_id, "source": source, "file": page.name, "title": tl.title, "url": tl.url,
        "set": folder.name, "set_exists": exists, "mashups": default_mashups,
        "has_mashups": any(t.kind == MASHUP for t in tl.tracks),
        "unidentified": sum(t.unidentified for t in tl.tracks),
        "counts": {m: len(chosen[m]) for m in MASHUPS},
        "kind": tl.source_kind,
        # What was read: {"kind": "youtube" | "csv" | "image" | ..., "name": file, "url": link}
        "origin": origin or {},
        # The candidate taken: its source (description, chapters, comment, comments, sections,
        # text, csv, ...) and label
        "picked": extras["picked"], "from": ({"source": picked.get("source"), "label": picked.get("label")}
                                             if picked else extras["from"]),
        "alternatives": extras["alternatives"],
        "warnings": extras["warnings"],
        "recording": web_recording(tl),
        "cues": sum(t.cue is not None for t in tl.tracks),
        "albums": sum(t.kind == ALBUM for t in tl.tracks),
        "tracks": tracks,
    }


class Uploads:
    def __init__(self, root: Path):
        self.root = root

    def save(self, name: str, stream: BinaryIO, length: int) -> dict:
        """Store an audio file the page sends (length bytes from stream)."""
        file_name = safe_name(name, "")
        if Path(file_name).suffix.lower() not in fx.AUDIO_EXTENSIONS:
            raise ApiError(415, "not_audio", f'"{file_name or name}" isn\'t an audio file '
                           f"({', '.join(sorted(e[1:] for e in fx.AUDIO_EXTENSIONS))}).")
        if length <= 0:
            raise bad_request("The file is empty.", "empty")
        upload_id = new_id()
        folder = self.root / upload_id
        folder.mkdir(parents=True)
        path = folder / file_name
        left = length
        try:
            with path.open("wb") as f:
                while left > 0:
                    chunk = stream.read(min(CHUNK, left))
                    if not chunk:
                        raise bad_request("The upload didn't arrive in full.", "incomplete")
                    f.write(chunk)
                    left -= len(chunk)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return {"id": upload_id, "name": file_name, "size": length}

    def path(self, upload_id: object) -> Path:
        if not isinstance(upload_id, str) or not ID_PATTERN.fullmatch(upload_id):
            raise not_found("There's no such upload (it may have been used already).", "no_upload")
        folder = self.root / upload_id
        files = [p for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []
        if len(files) != 1:
            raise not_found("There's no such upload (it may have been used already).", "no_upload")
        return files[0]

    def delete(self, upload_id: object) -> None:
        path = self.path(upload_id)
        shutil.rmtree(path.parent, ignore_errors=True)
