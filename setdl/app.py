"""Set Downloader's entry point.

    set-downloader                  the app, in its own window
    set-downloader --browser        serve it and open it in the web browser instead (development)
    set-downloader --tl2mixxx ...   run the tl2mixxx CLI and exit: how the built app runs its jobs,
                                    since it has no "python -m tl2mixxx"
    set-downloader --helper ...     the app's own job commands (helpers.py)

Both of the last two import an updated yt-dlp first, if the app passed one (ytdlp.py).
"""

from __future__ import annotations

import sys


def run_tl2mixxx(args: list[str]) -> int:
    # UTF-8 whatever the locale (an app started from the Finder may have none): track names
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    from .ytdlp import prefer_from_env
    prefer_from_env()
    from tl2mixxx.cli import main as tl2mixxx_main
    return tl2mixxx_main(args)


def run_helper(args: list[str]) -> int:
    from .ytdlp import prefer_from_env
    prefer_from_env()
    from .helpers import main as helper_main
    return helper_main(args)


def build_parser():
    import argparse

    from . import APP_NAME, __version__
    p = argparse.ArgumentParser(prog="set-downloader", description=f"{APP_NAME}: any tracklist in, its tracks downloaded.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    p.add_argument("--browser", action="store_true",
                   help="serve the app and open it in the web browser instead of a window (development)")
    p.add_argument("--no-open", action="store_true", help="with --browser: only print the address")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    p.add_argument("--data-dir", help="the app's folder for settings, the login and scratch files "
                                      "(default: ~/Library/Application Support/Set Downloader; env SETDL_DATA_DIR)")
    p.add_argument("--music-dir", help="where sets go, for this launch (default: the setting, else "
                                       "~/Music/1001Tracklists; env SETDL_MUSIC_DIR)")
    p.add_argument("--sockseek", help="the sockseek program to use, for this launch")
    p.add_argument("--web-dir", help="the built UI to serve (default: web/dist; env SETDL_WEB_DIST)")
    p.add_argument("--dev-origin", action="append", default=[], metavar="URL",
                   help="also accept requests from this origin, e.g. a Vite dev server that proxies "
                        "/api: http://localhost:5173 (repeatable)")
    p.add_argument("--verbose", action="store_true", help="log every request (never headers or bodies)")
    p.add_argument("--debug", action="store_true", help="window: allow the web inspector")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--tl2mixxx"]:
        return run_tl2mixxx(argv[1:])
    if argv[:1] == ["--helper"]:
        return run_helper(argv[1:])

    import signal
    import threading
    import webbrowser
    from pathlib import Path

    from . import APP_NAME, paths
    from .core import App
    from .server import Server

    args = build_parser().parse_args(argv)
    paths.extend_path()
    app = App(Path(args.data_dir).expanduser() if args.data_dir else paths.default_data_dir(),
              music_dir=args.music_dir, sockseek=args.sockseek)
    server = Server(app, port=args.port, web_dir=Path(args.web_dir).expanduser() if args.web_dir else None,
                    dev_origins=tuple(args.dev_origin), verbose=args.verbose)
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    url = server.page_url()
    try:
        if args.browser:
            print(f"{APP_NAME} is running at {url}", flush=True)
            for origin in server.dev_origins:
                print(f"  dev server: {server.page_url(origin)}", flush=True)
            print("Press Ctrl+C to quit.", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            done = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: done.set())
            while not done.wait(0.5):
                pass
        else:
            import webview
            webview.create_window(APP_NAME, url, width=1200, height=800, min_size=(880, 600), text_select=True)
            webview.start(debug=args.debug)
    finally:
        server.close()
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
