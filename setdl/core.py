"""The app without its window: settings, the Soulseek login, sets, drafts and jobs. The HTTP server
(server.py) is a thin layer over this."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from tl2mixxx import cli
from tl2mixxx import sockseek as ss
from tl2mixxx.tracklist import parse_file

from . import APP_NAME, __version__, paths
from .drafts import PAGE_LIMIT, TEXT_LIMIT, UPLOAD_LIMIT, Drafts, Uploads, draft_info, remove_old
from .errors import ApiError, bad_request, conflict, not_found
from .jobs import DONE, FAILED, STOPPED, EventBus, Job, JobManager, iso
from .login import APP_LOGIN_NAME, Login
from .sets import SetLibrary, inside, music_root, read_tracks, set_folder
from .settings import SetPrefs, SettingsStore, check_mashups, has_control_chars

MAX_QUERY = 300
EXIT_STOPPED = ss.EXIT_INTERRUPTED   # tl2mixxx's exit code when it was stopped
# sockseek's broader searches, for retries (see start_download)
RETRY_SEARCH = ["--remove-ft", "--artist-maybe-wrong", "--desperate"]


def child_env() -> dict:
    env = dict(os.environ)
    env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    return env


def reveal_in_finder(path: Path) -> None:
    """Show a file or folder in the Finder (tests replace this)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        target = path if path.is_dir() else path.parent
        subprocess.Popen(["xdg-open", str(target)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url: str) -> None:
    """Open a web address in the user's browser (tests replace this)."""
    import webbrowser
    webbrowser.open(url)


def check_query(query: object, what: str = "search") -> str:
    """A Soulseek search as tl2mixxx and sockseek take it: a positional argument, so it can't
    start with "-" (it would be read as an option)."""
    if not isinstance(query, str) or not query.strip():
        raise bad_request(f"Type what to {what} for.", "bad_query")
    query = " ".join(query.split())
    if has_control_chars(query) or len(query) > MAX_QUERY:
        raise bad_request("That search is too long or has characters a search can't have.", "bad_query")
    if query.startswith("-"):
        raise bad_request('A search can\'t start with "-".', "bad_query")
    return query


def read_result(path: Path | None) -> dict | None:
    """The --result-json tl2mixxx wrote (and remove it)."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        path.unlink(missing_ok=True)
    return data if isinstance(data, dict) else None


def no_result_message(job: Job, code: int) -> str:
    """Why there is no result (the wording follows the Mixxx fork's)."""
    if job.stop_requested or code == EXIT_STOPPED:
        return "Stopped."
    if code == 2:
        return "tl2mixxx didn't accept the command (exit code 2). See the log for details."
    why = f": {job.error}" if job.error else ". See the log for details."
    return f"tl2mixxx exited with code {code} and no result{why}"


class App:
    def __init__(self, data_dir: Path, *, music_dir: str | None = None, sockseek: str | None = None,
                 mixxx_login: Path | None = None, command: list[str] | None = None,
                 stop_grace: float = 3.0, kill_after: float = 10.0):
        self.data_dir = Path(data_dir).expanduser()
        self.work_dir = self.data_dir / "work"
        for sub in ("drafts", "uploads", "results"):
            (self.work_dir / sub).mkdir(parents=True, exist_ok=True)
        self.settings = SettingsStore(self.data_dir / "settings.json", paths.default_music_dir(),
                                      {"music_dir": music_dir, "sockseek": sockseek})
        self.set_prefs = SetPrefs(self.data_dir / "sets.json")
        self.login = Login(self.data_dir / APP_LOGIN_NAME, mixxx_login or paths.mixxx_login_path())
        self.drafts = Drafts(self.work_dir / "drafts")
        self.uploads = Uploads(self.work_dir / "uploads")
        for sub in ("drafts", "uploads"):
            remove_old(self.work_dir / sub, 3 * 24 * 3600)
        self.library = SetLibrary()
        # Sets whose first download is running: no folder with a page copy yet (tl2mixxx writes
        # that at the end), but the page lists them already. Set id -> summary.
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self.bus = EventBus()
        self.command = command or paths.tl2mixxx_command()
        self.jobs = JobManager(self.bus, self.command, self.work_dir, child_env,
                               stop_grace=stop_grace, kill_after=kill_after)

    def shutdown(self) -> None:
        self.jobs.shutdown()
        self.bus.close()

    # ------------------------------------------------------------------ state and settings

    def music_dir(self) -> Path:
        return Path(self.settings.get().music_dir)

    def sockseek_status(self) -> dict:
        """Which sockseek is used: the one in the settings, else one found automatically ($SOCKSEEK
        or PATH), else the one built into the app."""
        setting = self.settings.get().sockseek
        if setting:
            p = Path(setting)
            ok = p.is_file() and os.access(p, os.X_OK)
            return {"path": setting if ok else None, "source": "setting" if ok else None,
                    "setting": setting, "found": ok,
                    "error": None if ok else f"There's no program at {setting}."}
        try:
            found = ss.find_sockseek(None)
            return {"path": found, "source": "automatic", "setting": "", "found": True, "error": None}
        except ss.SockseekNotFound:
            pass
        bundled = paths.bundled_sockseek()
        if bundled:
            return {"path": str(bundled), "source": "bundled", "setting": "", "found": True, "error": None}
        return {"path": None, "source": None, "setting": "", "found": False,
                "error": "sockseek wasn't found. Set its location in the settings."}

    def state(self) -> dict:
        s = self.settings.get()
        music = Path(s.music_dir)
        return {
            "app": {"name": APP_NAME, "version": __version__},
            "settings": {"music_dir": s.music_dir, "sockseek": s.sockseek, "mashups": s.mashups},
            "music_dir": {"path": s.music_dir, "exists": music.is_dir()},
            "login": self.login.status(),
            "sockseek": self.sockseek_status(),
            "jobs": {"running": sum(j.state in ("running", "stopping") for j in self.jobs.jobs()),
                     "queued": sum(j.state == "queued" for j in self.jobs.jobs())},
            "limits": {"page_bytes": PAGE_LIMIT, "text_bytes": TEXT_LIMIT, "upload_bytes": UPLOAD_LIMIT,
                       "query_chars": MAX_QUERY},
        }

    def update_settings(self, changes: dict) -> dict:
        self.settings.update(changes)
        self.bus.publish("state", self.state())
        return self.state()

    def save_login(self, username: object, password: object) -> dict:
        self.login.save(username, password)
        self.bus.publish("state", self.state())
        return self.login.status()

    def clear_login(self) -> dict:
        self.login.clear()
        self.bus.publish("state", self.state())
        return self.login.status()

    def _soulseek_args(self) -> tuple[list[str], list[str]]:
        """tl2mixxx's --sockseek option and what goes after "--" to sockseek: no progress bars
        (there's no terminal) and the login. Refuses when either is missing."""
        status = self.sockseek_status()
        if not status["found"]:
            raise conflict(status["error"], "sockseek_missing")
        login = self.login.config_path()
        if login is None:
            raise conflict("Downloading from Soulseek needs a Soulseek login. Enter one in the settings.",
                           "login_required")
        return [f"--sockseek={status['path']}"], ["--", "--no-progress", "-c", str(login)]

    def _result_path(self, job_id: str) -> Path:
        return self.work_dir / "results" / f"{job_id}.json"

    # ------------------------------------------------------------------ sets

    def mashups_for(self, folder: Path) -> str:
        return self.set_prefs.mashups(folder, self.settings.get().mashups)

    def list_sets(self) -> dict:
        busy = self.jobs.busy_sets()
        sets = []
        for folder in self.library.folders(self.music_dir()):
            entry = self.library.summary(folder, self.mashups_for(folder))
            entry["busy"] = busy.get(folder.name)
            entry["pending"] = False
            sets.append(entry)
        listed = {e["id"] for e in sets}
        sets += [dict(e, busy=busy.get(e["id"], "queued")) for e in self._pending_sets() if e["id"] not in listed]
        sets.sort(key=lambda e: e["updated_ts"], reverse=True)
        return {"music_dir": str(self.music_dir()), "sets": sets}

    def _pending_sets(self) -> list[dict]:
        """The sets whose first download is queued or running (and not yet on disk)."""
        busy = self.jobs.busy_sets()
        root = str(music_root(self.music_dir()))
        with self._pending_lock:
            for set_id in [k for k in self._pending if k not in busy]:   # its job ended or never ran
                del self._pending[set_id]
            return [dict(e) for e in self._pending.values() if str(Path(e["folder"]).parent) == root]

    def get_set(self, set_id: object) -> dict:
        try:
            folder = set_folder(self.music_dir(), set_id)
        except ApiError as e:
            pending = next((p for p in self._pending_sets() if e.status == 404 and p["id"] == set_id), None)
            if pending is None:
                raise
            return dict(pending, busy=self.jobs.busy_sets().get(pending["id"]))
        entry = self.library.summary(folder, self.mashups_for(folder))
        entry["busy"] = self.jobs.busy_sets().get(folder.name)
        entry["pending"] = False
        return entry

    def set_tracks(self, set_id: object) -> dict:
        try:
            folder = set_folder(self.music_dir(), set_id)
        except ApiError as e:
            if e.status == 404 and any(p["id"] == set_id for p in self._pending_sets()):
                raise conflict("The set's first download is still running: its tracks are listed when "
                               "it finishes.", "not_ready")
            raise
        mashups = self.mashups_for(folder)
        data = read_tracks(self.command, folder, mashups, self.work_dir, child_env())
        rows = data["tracks"]
        return {
            "set": folder.name, "folder": data.get("folder", str(folder)), "title": data.get("title", ""),
            "mashups": mashups,
            "found": sum(r.get("status") == "found" for r in rows),
            "missing": sum(r.get("status") == "missing" for r in rows),
            "tracks": rows,
        }

    def reveal(self, set_id: object = None, path: object = None) -> dict:
        """Show a set's folder, or a file in the music folder, in the Finder."""
        root = music_root(self.music_dir())
        if set_id is not None:
            target = set_folder(self.music_dir(), set_id)
        elif path is not None:
            if not isinstance(path, str) or not path or has_control_chars(path) or not Path(path).is_absolute():
                raise bad_request("path is a full path to a file in the music folder.", "bad_path")
            target = Path(path).resolve()
            if not inside(root, target):
                raise ApiError(403, "outside_music_dir", "Only files in the music folder can be shown.")
            if not target.exists():
                raise not_found("That file isn't there anymore.", "no_file")
        else:
            if not root.is_dir():
                raise not_found("The music folder doesn't exist yet.", "no_music_dir")
            target = root
        reveal_in_finder(target)
        return {"ok": True, "path": str(target)}

    def open_link(self, url: object) -> dict:
        if not isinstance(url, str) or not url.lower().startswith(("https://", "http://")) \
                or has_control_chars(url) or len(url) > 2000:
            raise bad_request("Only web addresses (https://...) can be opened.", "bad_url")
        open_url(url)
        return {"ok": True}

    # ------------------------------------------------------------------ drafts

    def create_draft_page(self, name: str, data: bytes) -> dict:
        draft_id = self.drafts.create_page(name, data)
        return self.get_draft(draft_id)

    def create_draft_text(self, text: object, title: object = None) -> dict:
        draft_id = self.drafts.create_text(text, title)
        return self.get_draft(draft_id)

    def get_draft(self, draft_id: object) -> dict:
        page = self.drafts.page(draft_id)
        info = draft_info(str(draft_id), self.drafts.source(str(draft_id)), page, self.music_dir(),
                          self.settings.get().mashups)
        if info["set_exists"]:
            # What the set was downloaded with before
            info["mashups"] = self.mashups_for(music_root(self.music_dir()) / info["set"])
        return info

    def delete_draft(self, draft_id: object) -> dict:
        page = self.drafts.page(draft_id)
        if any(str(page) in job.args for job in self.jobs.jobs() if job.state not in (DONE, FAILED, STOPPED)):
            raise conflict("This draft is being downloaded: it's needed until that starts and finishes.",
                           "draft_in_use")
        self.drafts.delete(draft_id)
        return {"ok": True}

    # ------------------------------------------------------------------ jobs

    def start_download(self, draft: object = None, set_id: object = None,
                       mashups: object = None) -> tuple[Job, bool]:
        """Download a draft's set, or retry a set (only what's still missing is searched for).
        Returns the job and whether it was queued already."""
        if (draft is None) == (set_id is None):
            raise bad_request('Give either "draft" or "set".', "bad_download")
        music = music_root(self.music_dir())
        if draft is not None:
            page = self.drafts.page(draft)
            try:
                tl = parse_file(page)
            except (ValueError, OSError) as e:
                raise ApiError(422, "not_a_tracklist", str(e))
            folder = cli.set_folder(music, tl.title, tl)
            if folder.parent != music:
                raise ApiError(403, "outside_music_dir", "The set's folder isn't in the music folder.")
            title = tl.title
            extra: list[str] = []
            new_set = cli.page_copy(folder) is None
        else:
            folder = set_folder(music, set_id)
            page = cli.page_copy(folder)
            title = self.library.summary(folder, self.mashups_for(folder))["title"]
            # The same folder even if it was renamed: tl2mixxx names it after this
            extra = [f"--playlist-name={folder.name}"]
            new_set = False
        mashups = check_mashups(mashups) if mashups is not None else self.mashups_for(folder)
        key = f"download:{folder}"
        running = self.jobs.active(key)
        if running is not None:
            return running, True
        sockseek, after = self._soulseek_args()
        if not new_set:
            # A retry only searches for what's still missing, so it can afford to try harder:
            # without "feat." credits, without the artist, and by artist or title alone
            after += RETRY_SEARCH
        music.mkdir(parents=True, exist_ok=True)
        self.set_prefs.set_mashups(folder, mashups)
        job = Job(kind="download", title=title, args=[], soulseek=True, set_id=folder.name,
                  folder=str(folder), key=key)
        result = self._result_path(job.id)
        job.args = ["run", str(page), "--no-mixxx", f"--music-dir={music}", f"--mashups={mashups}",
                    *extra, f"--result-json={result}", "--stop-on-eof", *sockseek, *after]
        job.finish = lambda j, code: self._finish_set_job(j, code, result, folder)
        if new_set:
            self._add_pending(folder, tl, mashups, self.drafts.source(str(draft)))
        return self.jobs.submit(job), False

    def _add_pending(self, folder: Path, tl, mashups: str, source: str) -> None:
        total = len(cli.choose_tracks(tl, mashups, {}))
        now = time.time()
        with self._pending_lock:
            self._pending[folder.name] = {
                "id": folder.name, "name": folder.name, "title": tl.title, "url": tl.url, "source": source,
                "folder": str(folder), "m3u": "", "mashups": mashups, "downloaded": False, "found": 0,
                "missing": total, "total": total, "error": None, "pending": True,
                "updated": iso(now), "updated_ts": now}

    def start_search(self, query: object) -> Job:
        query = check_query(query)
        sockseek, after = self._soulseek_args()
        job = Job(kind="search", title=f'Search: "{query}"', args=[], soulseek=True)
        result = self._result_path(job.id)
        job.args = ["search", query, f"--result-json={result}", "--stop-on-eof", *sockseek, *after]
        job.finish = lambda j, code: self._finish_search(j, code, result, query)
        return self.jobs.submit(job)

    def start_fix(self, set_id: object, row: object, identity: object, *, link: object = None,
                  query: object = None, upload: object = None, clear: object = False) -> Job:
        """Fix one track: download a picked Soulseek result (link, with the query that found it),
        search again (query), use the user's uploaded file, or undo the fix (clear)."""
        folder = set_folder(self.music_dir(), set_id)
        if not isinstance(row, int) or isinstance(row, bool) or row < 1:
            raise bad_request("row is the track's row number.", "bad_row")
        if not isinstance(identity, str) or not identity or has_control_chars(identity):
            raise bad_request('identity is the track\'s "identity" from its tracks.', "bad_identity")
        if sum(bool(x) for x in (clear, upload, link or query)) != 1:
            raise bad_request('Give one of "link" (with "query" if it came from a search), "query", '
                              '"upload" or "clear".', "bad_fix")
        args = ["fix", str(folder), f"--track={row}", f"--expect-key={identity}"]
        cleanup = None
        soulseek = False
        if clear:
            if clear is not True:
                raise bad_request("clear is true or left out.", "bad_fix")
            args.append("--clear")
            what = "undo the fix"
        elif upload:
            path = self.uploads.path(upload)
            args.append(f"--file={path}")
            what = f"use {path.name}"
            cleanup = lambda j: self._drop_upload(upload)
        else:
            if link is not None:
                if not isinstance(link, str) or not link.startswith("slsk://") or has_control_chars(link) \
                        or len(link) > 4000:
                    raise bad_request("link is an slsk:// link from a search's results.", "bad_link")
                args.append(f"--link={link}")
            if query is not None:
                query = check_query(query)
                args.append(f"--query={query}")
            what = "download the picked file" if link else f'search again for "{query}"'
            soulseek = True
        mashups = self.mashups_for(folder)
        args.append(f"--mashups={mashups}")
        after: list[str] = []
        if soulseek:
            sockseek, after = self._soulseek_args()
            args += sockseek
        job = Job(kind="fix", title=f"{self._track_display(folder, row)}: {what}", args=[], soulseek=soulseek,
                  set_id=folder.name, folder=str(folder), row=row, cleanup=cleanup)
        result = self._result_path(job.id)
        job.args = args + [f"--result-json={result}", "--stop-on-eof", *after]
        job.finish = lambda j, code: self._finish_set_job(j, code, result, folder)
        return self.jobs.submit(job)

    def start_suggest(self, set_id: object, row: object = None, identity: object = None) -> Job:
        """Look for missing tracks under other names: one track (row, its identity) gets its likely
        files listed; without a row, every missing track is looked for and the files that surely
        are the track are downloaded and kept as its fix."""
        folder = set_folder(self.music_dir(), set_id)
        args = ["suggest", str(folder)]
        if row is None:
            args += ["--missing", "--auto"]
            title = "Find renamed tracks"
        else:
            if not isinstance(row, int) or isinstance(row, bool) or row < 1:
                raise bad_request("row is the track's row number.", "bad_row")
            if not isinstance(identity, str) or not identity or has_control_chars(identity):
                raise bad_request('identity is the track\'s "identity" from its tracks.', "bad_identity")
            args += [f"--track={row}", f"--expect-key={identity}"]
            title = f"{self._track_display(folder, row)}: likely matches"
        sockseek, after = self._soulseek_args()
        args += [f"--mashups={self.mashups_for(folder)}", *sockseek]
        job = Job(kind="suggest", title=title, args=[], soulseek=True, set_id=folder.name, folder=str(folder),
                  row=row if isinstance(row, int) else None)
        result = self._result_path(job.id)
        job.args = args + [f"--result-json={result}", "--stop-on-eof", *after]
        job.finish = lambda j, code: self._finish_suggest(j, code, result, folder)
        return self.jobs.submit(job)

    def _finish_suggest(self, job: Job, code: int, result_path: Path, folder: Path) -> tuple[str, str, dict | None]:
        data = read_result(result_path)
        tracks = (data or {}).get("tracks") or []
        taken = [t for t in tracks if t.get("taken")]
        if taken:
            self.library.forget(folder)
            self.bus.publish("sets", {"set": folder.name, "reason": job.kind})
        if job.stop_requested or code == EXIT_STOPPED:
            return STOPPED, "Stopped. Files already downloaded are kept.", {"tracks": tracks}
        if data is None:
            return FAILED, no_result_message(job, code), None
        errors = [str(e) for e in data.get("errors") or []]
        if job.row is not None:
            found = tracks[0]["candidates"] if tracks else []
            sure = sum(1 for c in found if c.get("confidence") == "high")
            message = (f"{len(found)} likely file(s), {sure} that surely are the track." if found else
                       "Nothing found under other names. You can still search with your own words.")
        else:
            message = (f"Found {len(taken)} of {len(tracks)} missing track(s) under other names." if tracks
                       else "Nothing is missing.")
        if errors:
            message += " " + " ".join(f"Error: {e}" for e in errors)
        return (DONE if code == 0 or taken else FAILED), message, {"tracks": tracks}

    @staticmethod
    def _track_display(folder: Path, row: int) -> str:
        """ "Artist - Title" of a set's row, for the job's title."""
        try:
            tl = parse_file(cli.page_copy(folder))
        except (ValueError, OSError, TypeError):
            return f"Row {row}"
        track = next((t for t in tl.tracks if t.index == row), None)
        if track is None:
            raise bad_request(f"The set has no row {row}.", "bad_row")
        return track.display

    def _drop_upload(self, upload_id: str) -> None:
        try:
            self.uploads.delete(upload_id)
        except ApiError:
            pass

    def save_upload(self, name: str, stream, length: int) -> dict:
        return self.uploads.save(name, stream, length)

    def delete_upload(self, upload_id: object) -> dict:
        self.uploads.delete(upload_id)
        return {"ok": True}

    def stop_job(self, job_id: str) -> dict:
        job = self.jobs.stop(job_id)
        if job is None:
            raise not_found("There's no such job.", "no_job")
        return self.jobs.snapshot(job)

    def job(self, job_id: str, log: bool = False) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise not_found("There's no such job.", "no_job")
        return self.jobs.snapshot(job, log=log)

    # ------------------------------------------------------------------ results

    def _finish_set_job(self, job: Job, code: int, result_path: Path, folder: Path) -> tuple[str, str, dict | None]:
        """A download's or fix's result: what the set has now."""
        self.library.forget(folder)
        with self._pending_lock:
            self._pending.pop(folder.name, None)
        data = read_result(result_path)
        stopped = job.stop_requested or code == EXIT_STOPPED
        if data is None:
            state = STOPPED if stopped else FAILED
            out = (state, no_result_message(job, code), None)
        else:
            errors = [str(e) for e in data.get("errors") or []]
            sets = data.get("sets") or []
            s = sets[0] if sets else None
            result = {"set": folder.name, "title": job.title, "found": 0, "missing": 0, "total": 0,
                      "cancelled": bool(data.get("cancelled")), "errors": errors, "missing_tracks": []}
            if s:
                result.update(title=s.get("title") or job.title, found=len(s.get("found") or []),
                              missing=len(s.get("missing") or []), total=s.get("total") or 0,
                              missing_tracks=[{k: t.get(k) for k in ("number", "artist", "title", "reason")}
                                              for t in s.get("missing") or []])
            lines = []
            if s:
                lines.append(f"{result['found']} of {result['total']} tracks have a file."
                             if result["missing"] else f"All {result['total']} tracks have a file.")
            lines += [f"Error: {e}" for e in errors]
            if stopped or result["cancelled"]:
                state = STOPPED
                lines.insert(0, "Stopped. What had finished downloading is kept.")
            elif code == 0:
                state = DONE
            else:
                state = FAILED
            if not lines:
                lines.append(no_result_message(job, code))
            out = (state, " ".join(lines), result)
        self.bus.publish("sets", {"set": folder.name, "reason": job.kind})
        return out

    def _finish_search(self, job: Job, code: int, result_path: Path, query: str) -> tuple[str, str, dict | None]:
        data = read_result(result_path)
        if job.stop_requested or code == EXIT_STOPPED:
            return STOPPED, "Search stopped.", None
        if code != 0 or data is None:
            why = job.error or f"exit code {code}"
            return FAILED, f"The search failed: {why}", None
        results = data.get("results") or []
        message = (f'{len(results)} result(s) for "{query}", best first.' if results else
                   f'Nothing found for "{query}". Try fewer or other words, e.g. without the featured '
                   "artists or the label.")
        return DONE, message, {"query": query, "results": results}

