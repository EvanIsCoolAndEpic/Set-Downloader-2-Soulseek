"""The app's own commands, run as child processes like tl2mixxx's (set-downloader --helper ...):

    take FOLDER --track ROW --link URL ...   download a video picked from "Find on YouTube" and keep
                                             it as the track's fix (tl2mixxx's fallback only takes
                                             the best result on its own, with --auto)
    ytdlp-version [--zip FILE]               which yt-dlp a child imports, as JSON

They use tl2mixxx as a library, print "ERROR kind: text" lines and "PROGRESS" lines like tl2mixxx,
and take its --result-json and --stop-on-eof.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def take_command(args: argparse.Namespace) -> int:
    from tl2mixxx import cli
    from tl2mixxx import fixes as fx
    from tl2mixxx import media_cli as mc
    from tl2mixxx import sockseek as ss
    from tl2mixxx import ytdl

    try:
        st = mc.load_state(args.folder, args.mashups)
    except (cli.SkipSet, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    track, why = mc.pick_track(st, args.track, args.expect_key)
    if track is None:
        print(f"ERROR fix: {why}", flush=True)
        cli.write_result_json(args.result_json, [], [why])
        return 1
    errors: list[str] = []
    stopped = False
    print(f"Track {track.number or track.index}: {track.display}", flush=True)
    try:
        path, info = ytdl.download(args.link, st.folder, args.format, name=track.display,
                                   progress=ytdl.progress_printer(f"downloading {track.display}", print),
                                   should_stop=lambda: ss.STOP.requested, stop=ss.STOP)
    except ytdl.Stopped:
        stopped = True
    except ytdl.YtdlError as e:
        errors.append(f"{track.display}: couldn't download it ({e})")
        print(f"ERROR download: couldn't download {args.link} ({e})", flush=True)
    else:
        key = fx.fix_key(track, st.ids)
        old = st.fixes.get(key, fx.Fix())
        st.fixes[key] = fx.Fix(query=args.query or old.query, file=fx.relative(st.folder, path),
                               source=args.source, link=args.link, updated=fx.now())
        st.save()
        print(f"  downloaded: {path.name}", flush=True)
        if mc.tags_ready(args):
            try:
                mc.tag_file(st, track, path, mc.Covers(), info.get("thumbnail") or "",
                            square=args.source == fx.YOUTUBE)
            except Exception as e:      # tags are a nicety: the file is there either way
                print(f"  (couldn't tag {path.name}: {e})", flush=True)
    m3u = st.folder / f"{st.folder.name}.m3u8"
    result = cli.SetResult(st.tl, st.folder, st.found, st.missing, st.tl.title, m3u if m3u.is_file() else None,
                           sockseek_exit=None, cancelled=stopped)
    cli.write_result_json(args.result_json, [result], errors, stopped=stopped or ss.STOP.requested)
    if stopped or ss.STOP.requested:
        return ss.EXIT_INTERRUPTED
    return 1 if errors else 0


def ytdlp_version_command(args: argparse.Namespace) -> int:
    from . import ytdlp
    if args.zip:
        ytdlp.prefer(args.zip)
    try:
        import yt_dlp
        from yt_dlp.version import __version__
    except Exception as e:
        print(json.dumps({"version": None, "from_zip": False, "error": str(e)}))
        return 1
    where = str(getattr(yt_dlp, "__file__", "") or "")
    zip_path = args.zip or os.environ.get(ytdlp.ENV) or ""
    from_zip = bool(zip_path) and where.startswith(str(Path(zip_path)))
    print(json.dumps({"version": __version__, "from_zip": from_zip, "path": where}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    from tl2mixxx import ffmpeg as ff
    p = argparse.ArgumentParser(prog="set-downloader --helper")
    sub = p.add_subparsers(dest="cmd", required=True)
    take = sub.add_parser("take", help="download a picked video and use it for a track")
    take.add_argument("folder")
    take.add_argument("--track", type=int, required=True, metavar="ROW")
    take.add_argument("--expect-key", metavar="KEY")
    take.add_argument("--link", required=True, help="the video's or track's address")
    take.add_argument("--source", choices=["youtube", "soundcloud"], default="youtube")
    take.add_argument("--query", default="", help="the search that found it (kept for retries)")
    take.add_argument("--format", choices=ff.CHOICES, default=ff.KEEP)
    take.add_argument("--no-tags", action="store_true")
    take.add_argument("--mashups", choices=["components", "original", "both"], default="components")
    take.add_argument("--result-json", metavar="FILE")
    take.add_argument("--stop-on-eof", action="store_true")
    version = sub.add_parser("ytdlp-version", help="which yt-dlp is imported, as JSON")
    version.add_argument("--zip", help="import this copy (a yt-dlp release zip) first")
    return p


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.cmd == "ytdlp-version":
        return ytdlp_version_command(args)
    from tl2mixxx import sockseek as ss
    ss.STOP.reset()
    restore = ss.install_stop_handlers()
    if args.stop_on_eof:
        ss.stop_when_stdin_closes()
    from tl2mixxx import net
    try:
        with net.guard():       # the picked link, its redirects and the cover: only on the internet
            return take_command(args)
    finally:
        restore()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
