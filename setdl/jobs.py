"""Jobs: the tl2mixxx CLI run as a child process, its output streamed to the page as events.

Soulseek jobs (downloads, searches, fixes that download) run one at a time, in the order they were
asked for: one Soulseek login can only be logged in once, and a second sockseek would log the first
one out. Other jobs (using the user's own file, undoing a fix) start right away. Either kind waits
while another job is busy with the same set, so two jobs never change a set's files at once.

Stop works like the Mixxx fork's: tl2mixxx runs with --stop-on-eof in a process group of its own;
closing its standard input asks it to stop sockseek and report what finished, and if it hasn't
stopped after a while the whole group gets SIGTERM, then SIGKILL.
"""

from __future__ import annotations

import os
import queue
import re
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

QUEUED, RUNNING, STOPPING = "queued", "running", "stopping"
DONE, FAILED, STOPPED = "done", "failed", "stopped"
FINISHED = (DONE, FAILED, STOPPED)

MAX_LOG_LINES = 5000       # kept per job; the page gets every line live
MAX_LINE_BYTES = 8192      # longer lines are split
KEEP_FINISHED = 100        # finished jobs remembered
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


class EventBus:
    """Events for the page (Server-Sent Events): numbered, and the last ones kept so a page that
    reconnects with Last-Event-ID gets what it missed."""

    def __init__(self, keep: int = 2000):
        self._lock = threading.Lock()
        self._last_id = 0
        self._recent: deque = deque(maxlen=keep)
        self._subscribers: list[queue.Queue] = []

    def publish(self, kind: str, data: dict) -> None:
        with self._lock:
            self._last_id += 1
            event = (self._last_id, kind, data)
            self._recent.append(event)
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:   # a page that stopped reading: it misses events
                    pass

    def subscribe(self, after: int | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=20000)
        with self._lock:
            if after is not None:
                for event in self._recent:
                    if event[0] > after:
                        q.put_nowait(event)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def close(self) -> None:
        """Ends every stream (the app is quitting)."""
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass


# finish(job, exit code) -> (state, message, result)
Finisher = Callable[["Job", int], "tuple[str, str, dict | None]"]


@dataclass(eq=False)
class Job:
    kind: str                       # "download" | "search" | "fix"
    title: str                      # what the page shows, e.g. the set's name
    args: list[str]                 # tl2mixxx's arguments
    soulseek: bool = False          # runs in the Soulseek queue
    set_id: str | None = None       # the set it is about
    row: int | None = None          # a fix: the track's row
    folder: str | None = None       # the set's folder: one job at a time per folder
    key: str = ""                   # the same key = the same job ("already queued")
    finish: Finisher | None = None
    cleanup: Callable[["Job"], None] | None = None
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    state: str = QUEUED
    waiting: str | None = None      # while queued: "soulseek" (another Soulseek job) or "set"
    created: float = field(default_factory=time.time)
    started: float | None = None
    ended: float | None = None
    exit_code: int | None = None
    message: str = ""
    error: str = ""                 # the last "ERROR kind: text" tl2mixxx printed
    result: dict | None = None
    log: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    lines: int = 0
    stop_requested: bool = False
    proc: subprocess.Popen | None = field(default=None, repr=False)

    def to_dict(self, ahead: int | None = None, log: bool = False) -> dict:
        d = {
            "id": self.id, "kind": self.kind, "title": self.title, "set": self.set_id, "row": self.row,
            "state": self.state, "waiting": self.waiting, "ahead": ahead,
            "created": iso(self.created), "started": iso(self.started), "finished": iso(self.ended),
            "exit_code": self.exit_code, "message": self.message, "error": self.error,
            "result": self.result, "log_lines": self.lines,
        }
        if log:
            d["log"] = list(self.log)
        return d


class JobManager:
    def __init__(self, bus: EventBus, command: list[str], work_dir: Path,
                 env: Callable[[], dict] | None = None, stop_grace: float = 3.0, kill_after: float = 10.0):
        self.bus = bus
        self.command = list(command)
        self.work_dir = work_dir
        self.env = env                  # the child's environment, made when it starts
        self.stop_grace = stop_grace    # after closing stdin, before SIGTERM to the group
        self.kill_after = kill_after    # after SIGTERM, before SIGKILL
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._jobs: dict[str, Job] = {}
        self._queue: deque[Job] = deque()
        self._current: Job | None = None            # the Soulseek job that is running
        self._busy_folders: dict[str, Job] = {}
        self._closed = False
        self._worker = threading.Thread(target=self._soulseek_worker, name="soulseek-queue", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------ asking

    def submit(self, job: Job) -> Job:
        with self._lock:
            if self._closed:
                raise RuntimeError("the app is quitting")
            self._jobs[job.id] = job
            self._forget_old()
            if job.soulseek:
                self._queue.append(job)
                if self._current is not None or len(self._queue) > 1:
                    job.waiting = "soulseek"
                self._wake.notify_all()
            else:
                threading.Thread(target=self._run, args=(job,), name=f"job-{job.id}", daemon=True).start()
            self._publish(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def jobs(self) -> list[Job]:
        """Newest first."""
        with self._lock:
            return list(reversed(self._jobs.values()))

    def snapshot(self, job: Job, log: bool = False) -> dict:
        with self._lock:
            return job.to_dict(ahead=self._ahead(job), log=log)

    def active(self, key: str) -> Job | None:
        """A queued or running job with this key that isn't being stopped."""
        with self._lock:
            for job in self._jobs.values():
                if job.key == key and job.state not in FINISHED and not job.stop_requested:
                    return job
        return None

    def busy_sets(self) -> dict[str, str]:
        """Set id -> "running" or "queued", for the sets that have a job."""
        out: dict[str, str] = {}
        with self._lock:
            for job in self._jobs.values():
                if job.set_id and job.state not in FINISHED:
                    if job.state in (RUNNING, STOPPING) or out.get(job.set_id) != "running":
                        out[job.set_id] = "running" if job.state in (RUNNING, STOPPING) else "queued"
        return out

    def stop(self, job_id: str) -> Job | None:
        """Stop a running job (what finished is kept), or take a queued one out of the queue."""
        removed = False
        proc = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.state in FINISHED or job.stop_requested:
                return job
            job.stop_requested = True
            if job.state == QUEUED:
                if job in self._queue:
                    self._queue.remove(job)
                    removed = True
                self._wake.notify_all()     # one waiting for its set notices
            else:
                job.state = STOPPING
                proc = job.proc
                self._publish(job)
        if removed:
            self._finish(job, STOPPED, "Stopped before it started.", None, None)
            self._clean_up(job)
            self._publish_queue()
        elif proc is not None:
            self._start_stopper(proc)
        return job

    def shutdown(self, timeout: float = 8.0) -> None:
        """Stop everything (the app is quitting)."""
        with self._lock:
            self._closed = True
            ids = [j.id for j in self._jobs.values() if j.state not in FINISHED]
            self._wake.notify_all()
        for job_id in ids:
            self.stop(job_id)
        deadline = time.monotonic() + timeout
        for job_id in ids:
            job = self.get(job_id)
            proc = job.proc if job else None
            if proc is not None and not _wait(proc, max(0.0, deadline - time.monotonic())):
                _signal_group(proc, signal.SIGKILL)

    # ------------------------------------------------------------------ running

    def _soulseek_worker(self) -> None:
        while True:
            with self._lock:
                while not self._queue and not self._closed:
                    self._wake.wait()
                if self._closed:
                    return
                job = self._queue.popleft()
                self._current = job
                job.waiting = None
            self._publish_queue()
            try:
                self._run(job)
            finally:
                with self._lock:
                    self._current = None
                self._publish_queue()

    def _run(self, job: Job) -> None:
        try:
            if not self._claim_folder(job):
                self._finish(job, STOPPED, "Stopped before it started.", None, None)
                return
            try:
                self._execute(job)
            finally:
                self._release_folder(job)
        except Exception as e:   # a job's thread never dies quietly
            traceback.print_exc()
            self._finish(job, FAILED, f"Couldn't run the job: {e}", job.result, job.exit_code)
        finally:
            self._clean_up(job)

    def _claim_folder(self, job: Job) -> bool:
        """Wait until no other job is busy with the job's set. False if it was stopped meanwhile."""
        with self._lock:
            while True:
                if job.stop_requested:
                    return False
                if not job.folder:
                    return True
                holder = self._busy_folders.get(job.folder)
                if holder is None or holder is job:
                    self._busy_folders[job.folder] = job
                    return True
                if job.waiting != "set":
                    job.waiting = "set"
                    self._publish(job)
                self._wake.wait(0.5)

    def _release_folder(self, job: Job) -> None:
        with self._lock:
            if job.folder and self._busy_folders.get(job.folder) is job:
                del self._busy_folders[job.folder]
            self._wake.notify_all()

    def _execute(self, job: Job) -> None:
        with self._lock:
            if job.stop_requested:
                stopped = True
            else:
                stopped = False
                job.state, job.started, job.waiting = RUNNING, time.time(), None
                self._publish(job)
        if stopped:
            self._finish(job, STOPPED, "Stopped before it started.", None, None)
            return
        self._line(job, "$ " + shlex.join(["tl2mixxx", *job.args]))
        try:
            proc = subprocess.Popen(self.command + job.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=self.work_dir,
                                    env=self.env() if self.env else None,
                                    start_new_session=True)   # its own process group: Stop reaches sockseek
        except OSError as e:
            self._finish(job, FAILED, f"Couldn't start tl2mixxx: {e}", None, None)
            return
        with self._lock:
            job.proc = proc
            stop_now = job.stop_requested
        if stop_now:
            self._start_stopper(proc)
        self._pump(job, proc)
        code = proc.wait()
        if job.stop_requested or code < 0:
            _signal_group(proc, signal.SIGKILL)   # anything left of it, e.g. a sockseek on its own
        if job.finish is not None:
            state, message, result = job.finish(job, code)
        else:
            state = STOPPED if job.stop_requested else DONE if code == 0 else FAILED
            message, result = "", None
        self._finish(job, state, message, result, code)

    def _pump(self, job: Job, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        while True:
            raw = proc.stdout.readline(MAX_LINE_BYTES)
            if not raw:
                break
            text = raw.decode("utf-8", "replace").rstrip("\r\n")
            if "\r" in text:   # a line redrawn in place: what is left visible
                text = text.rsplit("\r", 1)[-1]
            self._line(job, ANSI_ESCAPE.sub("", text))
        proc.stdout.close()

    def _line(self, job: Job, text: str) -> None:
        if text.startswith("ERROR "):
            # "ERROR <kind>: <text>"
            job.error = text.split(": ", 1)[1] if ": " in text else text[6:]
        with self._lock:
            job.log.append(text)
            job.lines += 1
            n = job.lines
        self.bus.publish("log", {"job": job.id, "n": n, "line": text})

    def _start_stopper(self, proc: subprocess.Popen) -> None:
        threading.Thread(target=self._stop_process, args=(proc,), name="stop", daemon=True).start()

    def _stop_process(self, proc: subprocess.Popen) -> None:
        try:
            if proc.stdin:
                proc.stdin.close()   # --stop-on-eof: tl2mixxx stops sockseek, keeps what finished
        except OSError:
            pass
        if _wait(proc, self.stop_grace):
            return
        _signal_group(proc, signal.SIGTERM)
        if _wait(proc, self.kill_after):
            return
        _signal_group(proc, signal.SIGKILL)

    def _finish(self, job: Job, state: str, message: str, result: dict | None, code: int | None) -> None:
        with self._lock:
            job.state, job.message, job.result, job.exit_code = state, message, result, code
            job.ended = time.time()
            job.waiting = None
            job.proc = None
            self._publish(job)

    def _clean_up(self, job: Job) -> None:
        if job.cleanup is None:
            return
        try:
            job.cleanup(job)
        except Exception:
            traceback.print_exc()
        job.cleanup = None

    # ------------------------------------------------------------------ bookkeeping

    def _ahead(self, job: Job) -> int | None:
        """How many Soulseek jobs run before this queued one (the running one included)."""
        if job.state != QUEUED or job not in self._queue:
            return None
        return list(self._queue).index(job) + (1 if self._current is not None else 0)

    def _publish(self, job: Job) -> None:
        with self._lock:
            data = job.to_dict(ahead=self._ahead(job))
        self.bus.publish("job", data)

    def _publish_queue(self) -> None:
        """The queued Soulseek jobs moved up."""
        with self._lock:
            waiting = list(self._queue)
        for job in waiting:
            self._publish(job)

    def _forget_old(self) -> None:
        finished = [j for j in self._jobs.values() if j.state in FINISHED]
        for job in finished[:max(0, len(finished) - KEEP_FINISHED)]:
            del self._jobs[job.id]


def _wait(proc: subprocess.Popen, timeout: float) -> bool:
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    """Signal the job's process group (tl2mixxx leads it; sockseek is in it too)."""
    if sys.platform == "win32":
        proc.kill()
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
