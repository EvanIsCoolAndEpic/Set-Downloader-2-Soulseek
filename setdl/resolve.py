"""Any tracklist in ("paste anything"): what the page hands over, checked, and "tl2mixxx resolve"
run on it.

- A link (YouTube, SoundCloud, Mixcloud, Spotify, Apple Music, any page yt-dlp reads) is read by a
  "resolve" job: comments take a while. Only http(s) links are taken, and a spotify: address is
  turned into its open.spotify.com page. A 1001Tracklists link is refused here (their terms don't
  allow fetching pages: the page has to be saved).
- A dropped file: a saved page (.html), a .txt list, an Exportify .csv, a tracklist .json or a
  picture (OCR) is resolved right away, with a time limit. A saved 1001Tracklists page and text are
  read in-process as before (drafts.py), so their sets keep a copy of the page itself.
- Anything else pasted is text.

Nothing the page sends is ever handed to tl2mixxx as a path: files are written into the draft's
folder first, and text that isn't one link is a draft of its own (text never reaches resolve).
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import urllib.parse
from pathlib import Path

from .errors import ApiError, bad_request
from .settings import has_control_chars

RESOLVE_TIMEOUT = 45         # a local file: CSV, JSON, a saved page
OCR_TIMEOUT = 180            # a picture: the first one compiles Vision's models (up to a minute and a half)
MAX_URL = 2000

FILE_KINDS = {".html": "page", ".htm": "page", ".txt": "text", ".csv": "csv", ".json": "json",
              ".png": "image", ".jpg": "image", ".jpeg": "image", ".heic": "image", ".heif": "image"}
EXPORTIFY = "https://exportify.app"
SPOTIFY_HELP = (f"Export the playlist with Exportify ({EXPORTIFY}): sign in with Spotify, press Export next "
                "to the playlist, then drop the .csv file here. Exportify also gets playlists over 100 tracks.")

_HOSTED = re.compile(r"(?:www\.)?[\w-]+(?:\.[\w-]+)+/\S*", re.IGNORECASE)
_SPOTIFY_URI = re.compile(r"spotify:(playlist|album|track):(\w+)")
_SCHEME = re.compile(r"[a-z][a-z0-9+.\-]*:", re.IGNORECASE)


def file_kind(name: str) -> str | None:
    """What a dropped file is, by its extension: page, text, csv, json, image (None: not one)."""
    return FILE_KINDS.get(Path(name).suffix.lower())


def check_image(data: bytes) -> None:
    """A PNG, JPEG or HEIC picture, by its first bytes (Vision is only shown pictures)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"):
        return
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return
    raise ApiError(415, "not_an_image", "That picture isn't a PNG, JPEG or HEIC file.")


def as_link(text: str) -> str | None:
    """The input as a web address, if it is one link: https://..., www.x.com/..., x.com/...
    or spotify:playlist:... Another scheme (file:, ftp:, javascript:...) is refused."""
    s = text.strip().strip("<>")
    if not s or any(c.isspace() for c in s):
        return None
    m = _SPOTIFY_URI.fullmatch(s)
    if m:
        return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
    if s.lower().startswith(("http://", "https://")):
        url = s
    elif _HOSTED.fullmatch(s) and not _SCHEME.match(s):
        url = "https://" + s
    elif _SCHEME.match(s) and "/" in s:
        raise bad_request("Only web addresses (https://...) can be read.", "bad_url")
    else:
        return None
    u = urllib.parse.urlsplit(url)
    if len(url) > MAX_URL or has_control_chars(url) or not u.hostname or u.username or u.password:
        raise bad_request("That web address can't be read.", "bad_url")
    host = u.hostname.lower()
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal or "." not in host or host.endswith((".local", ".localhost", ".internal", ".lan")) \
            or _local_host(host):
        raise bad_request("Only addresses on the web can be read.", "bad_url")
    return url


def _local_host(host: str) -> bool:
    """A name that resolves to the Mac itself or the local network (localtest.me). Where a link
    redirects is checked when it's read: tl2mixxx connects only to addresses on the internet."""
    from tl2mixxx import net
    return net.resolves_local(host)


def link_kind(url: str) -> str:
    """tl2mixxx's name for what a link is (youtube, spotify, 1001tracklists-link...). Reads nothing."""
    from tl2mixxx.inputs import detect
    return detect(url)


def error_text(output: str) -> str:
    """What tl2mixxx said went wrong: its last "error: ..." (or "ERROR kind: ...") line."""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("error: "):
            return line[len("error: "):]
        if line.startswith("ERROR ") and ": " in line:
            return line.split(": ", 1)[1]
    return ""


def warnings_of(output: str) -> list[str]:
    return [line.strip()[len("warning: "):] for line in output.splitlines() if line.strip().startswith("warning: ")]


def run_resolve(command: list[str], source: str, out: Path, cwd: Path, env: dict, timeout: float,
                extra: list[str] | None = None) -> None:
    """tl2mixxx resolve, waited for. Raises ApiError (422 with tl2mixxx's reason) when it found
    nothing or failed."""
    try:
        proc = subprocess.run(command + ["resolve", source, f"--out={out}", *(extra or [])],
                              stdin=subprocess.DEVNULL, capture_output=True, cwd=cwd, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ApiError(504, "resolve_timeout", "Reading it took too long. Try a smaller file.") from None
    except OSError as e:
        raise ApiError(500, "resolve_failed", f"Couldn't run tl2mixxx: {e}") from None
    output = proc.stdout.decode("utf-8", "replace") + "\n" + proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0 or not out.is_file():
        why = error_text(output) or f"tl2mixxx exited with code {proc.returncode}."
        raise ApiError(422, "not_a_tracklist", why)
