#!/usr/bin/env python3
"""Stand-in for the app's children in tests: tl2mixxx, and the app's helpers with --helper, as they
are, except that nothing reaches the network:

- yt-dlp searches (tl2mixxx.ytdl.search) return made-up results: an official "Artist - Title"
  upload named as searched and a "slowed" copy, none when the query has a word in FAKE_YTDL_MISSING
  ("|"-separated; tl2mixxx scores them, so a search with other words than the track's isn't taken);
- yt-dlp downloads (ytdl.download) write a few seconds of sine tone made with ffmpeg (a set's
  recording: 100 seconds), in the format asked for;
- covers aren't fetched (tags.fetch_cover);
- reading a video's page (inputs.video.extract) returns fixtures/ytdlp_video.json;
- reading a Spotify link fails like Spotify does when FAKE_SPOTIFY_FAIL is set, else gives a
  three-track playlist and the 100-track warning.

- FAKE_OCR=<marker file>: reading a picture fails the first time, then gives a two-track list.

FAKE_YTDL_LOG: a file each download's link is appended to. FAKE_YTDL_FAIL: downloads fail.
FAKE_YTDL_DELAY / FAKE_EXTRACT_DELAY: seconds each download / reading a page takes (to watch the
UI while they run).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent


def missing_words() -> set[str]:
    return set(filter(None, os.environ.get("FAKE_YTDL_MISSING", "").split("|")))


def fake_search(query, n=5, source="any"):
    if any(w.lower() in query.lower() for w in missing_words()):
        return [], []
    artist, _, title = query.partition(" - ")
    vid = hashlib.sha1(query.encode()).hexdigest()[:11]
    official = {"user": artist, "path": f"{query}.opus", "name": query, "format": "opus", "size": 0,
                "length": 0, "bitrate": 0, "samplerate": 48000, "bitdepth": 0, "free_slot": True, "speed": 0.0,
                "link": f"https://www.youtube.com/watch?v={vid}", "source": "youtube", "uploader": artist,
                "title": title or query, "id": vid, "official": True, "quality": "lossy, ~128-160 kbps",
                "thumbnail": ""}
    slowed = dict(official, name=f"{query} (slowed + reverb)", path=f"{query} (slowed + reverb).opus",
                  link=f"https://soundcloud.com/someone/{vid}-slowed", source="soundcloud", official=False,
                  uploader="someone", user="someone", id=vid + "s")
    return [official, slowed][:max(1, n)], []


def tone(seconds: float, out: Path) -> Path:
    from tl2mixxx import ffmpeg as ff
    subprocess.run([ff.find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libopus", "-b:a", "24k", str(out)],
                   check=True, stdin=subprocess.DEVNULL)
    return out


def fake_download(url, dest_dir, fmt="keep", *, name=None, progress=None, should_stop=None,
                  max_duration=30 * 60, stop=None):
    from tl2mixxx import ffmpeg as ff
    from tl2mixxx import ytdl
    from tl2mixxx.fixes import unique_target
    log = os.environ.get("FAKE_YTDL_LOG")
    if log:
        with open(log, "a") as f:
            f.write(url + "\n")
    if os.environ.get("FAKE_YTDL_FAIL"):
        raise ytdl.YtdlError("Video unavailable")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    delay = float(os.environ.get("FAKE_YTDL_DELAY") or 0)
    for i in range(1, 5):
        if should_stop and should_stop():
            raise ytdl.Stopped("stopped")
        if progress:
            progress({"status": "downloading", "downloaded_bytes": 25 * i, "total_bytes": 100})
        time.sleep(delay / 4)
    with tempfile.TemporaryDirectory(dir=dest_dir, prefix=".fake-yt-") as tmp:
        got = tone(100 if max_duration is None else 3, Path(tmp) / "audio.opus")
        final = got if fmt == ff.KEEP else ff.convert(got, fmt)
        target = unique_target(dest_dir, ytdl.safe_name(name or "track") + final.suffix)
        shutil.move(str(final), target)
    source = "soundcloud" if "soundcloud" in url else "youtube"
    return target, {"name": name or "track", "link": url, "source": source, "thumbnail": ""}


def fake_extract(url, *, comments=True, max_comments=300, time_limit=30, flat=True):
    time.sleep(float(os.environ.get("FAKE_EXTRACT_DELAY") or 0))
    info = json.loads((HERE / "fixtures" / "ytdlp_video.json").read_text(encoding="utf-8"))
    if not comments:
        info["comments"] = []
    return info, []


def fake_spotify(url):
    from tl2mixxx.inputs.candidates import InputError
    from tl2mixxx.tracklist import NORMAL, Track, Tracklist
    if os.environ.get("FAKE_SPOTIFY_FAIL") or "unreadable" in url:
        raise InputError("Spotify didn't answer. Export the playlist with Exportify (https://exportify.app) "
                         "and use the .csv instead.")
    tl = Tracklist(title="Late Night Selects", url=url, source_kind="spotify")
    for i, (a, t) in enumerate([("Kettle", "Ghosts"), ("Saltmarsh", "Pressure"), ("Four Tet", "Baby")], 1):
        tl.tracks.append(Track(index=i, number=str(i).zfill(2), kind=NORMAL, artist=a, title=t, search_artist=a))
    return tl, ["Spotify's page only lists the first 100 tracks: export the playlist with Exportify "
                "(https://exportify.app) for all of them."]


def fake_observations(path):
    """FAKE_OCR=<marker file>: Vision's first reading fails (as it can in a program new to it), the
    next ones read a two-track list."""
    from tl2mixxx.inputs.candidates import InputError
    marker = Path(os.environ["FAKE_OCR"])
    if not marker.exists():
        marker.write_text("failed once")
        raise InputError(f"Couldn't read the picture {Path(path).name}: The operation couldn't be completed. "
                         "(TextRecognition.CRImageReaderError error 1.)")
    return [("01. Kettle - Ghosts", 0.1, 0.8, 0.5, 0.05), ("02. Saltmarsh - Pressure", 0.1, 0.7, 0.5, 0.05)]


def main(argv):
    from tl2mixxx import tags, ytdl
    from tl2mixxx.inputs import ocr, video, web
    if os.environ.get("FAKE_OCR"):
        ocr.observations = fake_observations
    tags.fetch_cover = lambda url, square=False: None
    ytdl.search = fake_search
    ytdl.download = fake_download
    ytdl.available = lambda: True
    video.extract = fake_extract
    web.spotify = fake_spotify
    if argv[:1] == ["--helper"]:
        from setdl.helpers import main as helper_main
        return helper_main(argv[1:])
    from tl2mixxx.cli import main as tl2mixxx_main
    return tl2mixxx_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
