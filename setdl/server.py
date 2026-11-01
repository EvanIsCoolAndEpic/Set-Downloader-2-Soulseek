"""The HTTP server the window talks to: the built UI and a JSON API, on 127.0.0.1 only.

- Every API call needs this launch's random token in the X-SetDL-Token header. The page gets it
  from its own address (#token=...), which only the window (or the URL printed in dev mode) has.
- The Host must be 127.0.0.1 or localhost with the server's port, so a web page can't reach the
  server under a name of its own (DNS rebinding).
- Requests from another origin are refused (Origin and Sec-Fetch-Site).
- Bodies have size limits, and set ids, drafts and uploads resolve inside the music folder or the
  app's scratch folder only (see sets.py, drafts.py).
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import queue
import re
import secrets
import socketserver
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import APP_NAME, __version__, paths
from .core import App
from .drafts import PAGE_LIMIT, TEXT_LIMIT, UPLOAD_LIMIT
from .errors import ApiError, bad_request
from .sets import inside

TOKEN_HEADER = "X-SetDL-Token"
JSON_LIMIT = 256 * 1024
PING_SECONDS = 15
MAX_ROW = 100_000

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".wasm": "application/wasm",
         ".webp": "image/webp", ".jpg": "image/jpeg", ".map": "application/json", ".txt": "text/plain"}

PLACEHOLDER = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{APP_NAME}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; margin: 0;
         display: grid; place-items: center; min-height: 100vh; background: Canvas; color: CanvasText; }}
  main {{ max-width: 34rem; padding: 2rem; }}
  code {{ font-family: ui-monospace, Menlo, monospace; font-size: 13px; }}
</style></head>
<body><main>
  <h1>{APP_NAME}</h1>
  <p>The app is running, but its interface hasn't been built yet. Build it with
  <code>npm run build</code> in <code>web/</code>, then reload.</p>
  <p>The API is up: see <code>API.md</code>.</p>
</main></body></html>
""".encode("utf-8")

# method, path pattern (matched before decoding), handler name
ROUTES = [
    ("GET", r"/api/state", "get_state"),
    ("PUT", r"/api/settings", "put_settings"),
    ("PUT", r"/api/login", "put_login"),
    ("DELETE", r"/api/login", "delete_login"),
    ("POST", r"/api/drafts/page", "post_draft_page"),
    ("POST", r"/api/drafts/text", "post_draft_text"),
    ("GET", r"/api/drafts/([^/]+)", "get_draft"),
    ("DELETE", r"/api/drafts/([^/]+)", "delete_draft"),
    ("POST", r"/api/downloads", "post_download"),
    ("GET", r"/api/sets", "get_sets"),
    ("GET", r"/api/sets/([^/]+)", "get_set"),
    ("GET", r"/api/sets/([^/]+)/tracks", "get_tracks"),
    ("POST", r"/api/sets/([^/]+)/tracks/([0-9]{1,6})/fix", "post_fix"),
    ("POST", r"/api/searches", "post_search"),
    ("POST", r"/api/uploads", "post_upload"),
    ("DELETE", r"/api/uploads/([^/]+)", "delete_upload"),
    ("GET", r"/api/jobs", "get_jobs"),
    ("GET", r"/api/jobs/([^/]+)", "get_job"),
    ("POST", r"/api/jobs/([^/]+)/stop", "post_stop"),
    ("GET", r"/api/events", "get_events"),
    ("POST", r"/api/reveal", "post_reveal"),
    ("POST", r"/api/open-url", "post_open_url"),
]
COMPILED = [(m, re.compile(p), name) for m, p, name in ROUTES]


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, app: App, *, port: int = 0, token: str | None = None, web_dir: Path | None = None,
                 dev_origins: tuple[str, ...] = (), verbose: bool = False):
        super().__init__(("127.0.0.1", port), Handler)
        self.app = app
        self.token = token or secrets.token_urlsafe(32)
        self.port = self.server_address[1]
        self.web_dir = Path(web_dir) if web_dir else paths.web_dist_dir()
        self.dev_origins = {o.rstrip("/") for o in dev_origins}
        self.verbose = verbose
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{h}" for h in self.hosts} | self.dev_origins
        self.closing = threading.Event()

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks up the host's name (socket.getfqdn), which can hang on an
        # mDNS lookup for seconds or for good: the name is never used, so it's skipped
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def page_url(self, base: str | None = None) -> str:
        """The address the window opens: the token goes in the fragment, which is never sent to
        the server or written in its logs."""
        return f"{(base or self.url).rstrip('/')}/#token={self.token}"

    def close(self) -> None:
        self.closing.set()
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"SetDownloader/{__version__}"
    sys_version = ""
    server: Server

    # ------------------------------------------------------------------ plumbing

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

    def log_message(self, format, *args):  # noqa: A002 (BaseHTTPRequestHandler's name)
        # Request lines only, and only when asked: never headers (the token) or bodies (the login)
        if self.server.verbose:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")

    def _handle(self, method: str) -> None:
        self._sent = False
        self._body_read = False
        try:
            url = urlsplit(self.path)
            self._query = parse_qs(url.query)
            self._check_host()
            self._check_origin()
            path = url.path
            if path == "/api" or path.startswith("/api/"):
                self._check_token()
                self._route(method, path)
            elif method in ("GET", "HEAD"):
                self._static(path, head=method == "HEAD")
            else:
                raise ApiError(405, "method_not_allowed", f"{method} isn't allowed here.")
        except ApiError as e:
            if not self._sent:
                self._send_json(e.status, e.to_dict())
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:
            traceback.print_exc()
            if not self._sent:
                self._send_json(500, {"error": {"code": "internal",
                                                "message": f"Something went wrong in {APP_NAME}: {e}"}})

    def _check_host(self) -> None:
        if self.headers.get("Host", "") not in self.server.hosts:
            raise ApiError(403, "bad_host", "Requests must be addressed to 127.0.0.1 or localhost.")

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.origins:
            raise ApiError(403, "bad_origin", "Requests from other web pages are refused.")
        site = self.headers.get("Sec-Fetch-Site")
        if site and site not in ("same-origin", "none") and origin not in self.server.dev_origins:
            raise ApiError(403, "bad_origin", "Requests from other web pages are refused.")

    def _check_token(self) -> None:
        given = self.headers.get(TOKEN_HEADER, "").encode("latin-1", "replace")
        if not hmac.compare_digest(given, self.server.token.encode("ascii")):
            raise ApiError(401, "bad_token", f"Missing or wrong {TOKEN_HEADER} header.")

    def _route(self, method: str, path: str) -> None:
        allowed = []
        for m, pattern, name in COMPILED:
            match = pattern.fullmatch(path)
            if not match:
                continue
            if m != method:
                allowed.append(m)
                continue
            getattr(self, name)(*(unquote(g) for g in match.groups()))
            return
        if allowed:
            raise ApiError(405, "method_not_allowed", f"Use {' or '.join(sorted(set(allowed)))} here.")
        raise ApiError(404, "not_found", "There's no such API endpoint.")

    def _common_headers(self, cache: str = "no-store") -> None:
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")

    def _send(self, status: int, body: bytes, content_type: str, *, cache: str = "no-store",
              html: bool = False, head: bool = False) -> None:
        if not self._body_read and (self.headers.get("Content-Length", "0") not in ("", "0")
                                    or self.headers.get("Transfer-Encoding")):
            # The body wasn't read: it can't be left for the next request on this connection
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._common_headers(cache)
        if html:
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self._sent = True
        if not head:
            self.wfile.write(body)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _length(self, limit: int) -> int:
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "length_required", "Send the body with a Content-Length, not chunked.")
        raw = self.headers.get("Content-Length")
        if raw is None:
            return 0   # HTTP/1.1: no length and not chunked = no body
        try:
            n = int(raw)
        except ValueError:
            raise bad_request("Content-Length isn't a number.")
        if n < 0:
            raise bad_request("Content-Length isn't a number.")
        if n > limit:
            raise ApiError(413, "too_large", f"That's too big: the limit is {limit // (1024 * 1024) or 1} MB.")
        return n

    def _body(self, limit: int) -> bytes:
        n = self._length(limit)
        data = self.rfile.read(n) if n else b""
        self._body_read = True
        if len(data) != n:
            self.close_connection = True
            raise bad_request("The request body didn't arrive in full.", "incomplete")
        return data

    def _json(self, limit: int = JSON_LIMIT) -> dict:
        raw = self._body(limit)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise bad_request("The body isn't valid JSON.", "bad_json")
        if not isinstance(data, dict):
            raise bad_request("The body must be a JSON object.", "bad_json")
        return data

    def _param(self, name: str) -> str | None:
        values = self._query.get(name)
        return values[0] if values else None

    # ------------------------------------------------------------------ the built UI

    def _static(self, path: str, head: bool) -> None:
        root = self.server.web_dir
        index = root / "index.html"
        if not index.is_file():
            self._send(200, PLACEHOLDER, "text/html; charset=utf-8", cache="no-cache", html=True, head=head)
            return
        rel = unquote(path).lstrip("/")
        if "\x00" in rel:
            raise ApiError(404, "not_found", "Not found.")
        root_resolved = root.resolve()
        target = (root_resolved / rel).resolve() if rel else index.resolve()
        if not inside(root_resolved, target):
            raise ApiError(404, "not_found", "Not found.")
        if not target.is_file():
            if "." in rel.rsplit("/", 1)[-1]:
                raise ApiError(404, "not_found", "Not found.")
            target = index.resolve()   # a route of the page itself
        suffix = target.suffix.lower()
        ctype = TYPES.get(suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype, cache="no-cache", html=suffix == ".html", head=head)

    # ------------------------------------------------------------------ API: state and settings

    def get_state(self) -> None:
        self._send_json(200, self.server.app.state())

    def put_settings(self) -> None:
        self._send_json(200, self.server.app.update_settings(self._json()))

    def put_login(self) -> None:
        body = self._json()
        self._send_json(200, {"login": self.server.app.save_login(body.get("username"), body.get("password"))})

    def delete_login(self) -> None:
        self._body(JSON_LIMIT)
        self._send_json(200, {"login": self.server.app.clear_login()})

    # ------------------------------------------------------------------ API: drafts

    def post_draft_page(self) -> None:
        name = self._param("name") or "tracklist.html"
        data = self._body(PAGE_LIMIT)
        self._send_json(201, self.server.app.create_draft_page(name, data))

    def post_draft_text(self) -> None:
        body = self._json(TEXT_LIMIT)
        self._send_json(201, self.server.app.create_draft_text(body.get("text"), body.get("title")))

    def get_draft(self, draft_id: str) -> None:
        self._send_json(200, self.server.app.get_draft(draft_id))

    def delete_draft(self, draft_id: str) -> None:
        self._body(JSON_LIMIT)
        self._send_json(200, self.server.app.delete_draft(draft_id))

    # ------------------------------------------------------------------ API: sets and jobs

    def post_download(self) -> None:
        body = self._json()
        app = self.server.app
        job, already = app.start_download(draft=body.get("draft"), set_id=body.get("set"),
                                          mashups=body.get("mashups"))
        self._send_json(200 if already else 202, {"job": app.jobs.snapshot(job), "already_queued": already})

    def get_sets(self) -> None:
        self._send_json(200, self.server.app.list_sets())

    def get_set(self, set_id: str) -> None:
        self._send_json(200, self.server.app.get_set(set_id))

    def get_tracks(self, set_id: str) -> None:
        self._send_json(200, self.server.app.set_tracks(set_id))

    def post_fix(self, set_id: str, row: str) -> None:
        body = self._json()
        n = int(row)
        if not 1 <= n <= MAX_ROW:
            raise bad_request("row is the track's row number.", "bad_row")
        app = self.server.app
        job = app.start_fix(set_id, n, body.get("identity"), link=body.get("link"), query=body.get("query"),
                            upload=body.get("upload"), clear=body.get("clear", False))
        self._send_json(202, {"job": app.jobs.snapshot(job)})

    def post_search(self) -> None:
        body = self._json()
        app = self.server.app
        job = app.start_search(body.get("query"))
        self._send_json(202, {"job": app.jobs.snapshot(job)})

    def post_upload(self) -> None:
        name = self._param("name")
        if not name:
            raise bad_request('Give the file\'s name: POST /api/uploads?name=<file name>.', "bad_name")
        length = self._length(UPLOAD_LIMIT)
        # Streamed to disk. If it fails part way, the rest of the body is unread and _send closes
        # the connection.
        upload = self.server.app.save_upload(name, self.rfile, length)
        self._body_read = True
        self._send_json(201, {"upload": upload})

    def delete_upload(self, upload_id: str) -> None:
        self._body(JSON_LIMIT)
        self._send_json(200, self.server.app.delete_upload(upload_id))

    def get_jobs(self) -> None:
        app = self.server.app
        self._send_json(200, {"jobs": [app.jobs.snapshot(j) for j in app.jobs.jobs()]})

    def get_job(self, job_id: str) -> None:
        self._send_json(200, self.server.app.job(job_id, log=True))

    def post_stop(self, job_id: str) -> None:
        self._body(JSON_LIMIT)
        self._send_json(200, {"job": self.server.app.stop_job(job_id)})

    def post_reveal(self) -> None:
        body = self._json()
        self._send_json(200, self.server.app.reveal(set_id=body.get("set"), path=body.get("path")))

    def post_open_url(self) -> None:
        body = self._json()
        self._send_json(200, self.server.app.open_link(body.get("url")))

    # ------------------------------------------------------------------ API: live events

    def get_events(self) -> None:
        """Server-Sent Events: "job", "log", "sets" and "state" events, as they happen."""
        job_filter = self._param("job")
        last = self.headers.get("Last-Event-ID") or self._param("after")
        after = int(last) if last and last.isdigit() else None
        bus = self.server.app.bus
        q = bus.subscribe(after)
        try:
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self._common_headers()
            self.send_header("Connection", "close")
            self.end_headers()
            self._sent = True
            self.wfile.write(b"retry: 2000\n\nevent: hello\ndata: {}\n\n")
            self.wfile.flush()
            while not self.server.closing.is_set():
                try:
                    event = q.get(timeout=PING_SECONDS)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if event is None:
                    break
                event_id, kind, data = event
                if job_filter and job_filter != (data.get("job") if kind == "log" else data.get("id")
                                                 if kind == "job" else None):
                    continue
                payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                self.wfile.write(f"id: {event_id}\nevent: {kind}\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(q)
