# Set Downloader

Paste anything with a tracklist in it: a YouTube or SoundCloud link (the description, chapters and
comments are read and ranked), a Mixcloud show, a Spotify or Apple Music playlist, an Exportify
CSV, a screenshot, a saved 1001Tracklists page, an M3U playlist or CUE sheet, or plain text. Set Downloader turns it into a clean
tracklist and downloads each track into `~/Music/1001Tracklists/<set>/`, with a playlist in set
order: from Soulseek first, then YouTube for what Soulseek doesn't have, then cut out of the set's
recording. It can convert the files to one format and tag them, retry what's missing, and fix single
tracks: search again, pick a result, find it on YouTube, cut it from the set, or use your own file.

[tl2mixxx](../tl2mixxx) and [sockseek](https://github.com/fiso64/sockseek) do the work, with yt-dlp
and ffmpeg. This app is the window around them: a Python backend (`setdl/`) serving a web UI
(`web/`) in a pywebview window. The API is described in [API.md](API.md).

## Where tracks come from

Settings > Where tracks come from lists the sources in the order they're tried; each can be turned
off (with the Soulseek account under a ban, say, turn Soulseek off and everything comes from
YouTube):

1. **Soulseek**: lossless when someone shares it. Quality: lossless only, best available, or fast.
2. **YouTube**: YouTube Music, YouTube and SoundCloud, through yt-dlp. Only results that surely are
   the track are taken on their own; they're lossy (about 128 to 160 kbps) and labelled so.
3. **Cut from the set**: for a set with a recording and track times (a YouTube mix), what's still
   missing (and the IDs) is cut out of the recording.

After a download, the missing tracks go through the next sources on their own, as queued jobs, then
the files are converted (keep, FLAC, AIFF, MP3 320, WAV) and tagged if the settings say so. This
also happens when Soulseek refuses the login; the set then says why: a wrong password, a refused
account, or a network Soulseek is blocking (its server hangs up before any login, which it does
after too many logins from one network: switch Wi-Fi). YouTube jobs run beside the Soulseek queue (they
don't need the login) but one at a time, and a job waiting for a busy set lets the others go first.
Links, redirects, recordings and covers are only fetched from addresses on the internet, never
from the Mac itself or the local network. The track list
says where each file came from, and the set's header sums it up ("28 Soulseek, 4 YouTube, 2 from
the mix, 3 missing"). In a track's Fix panel: Find on YouTube (scored results to pick from), Cut
from the set, and Bandcamp and Beatport links to buy it.

yt-dlp needs updating when YouTube changes: Settings > yt-dlp > Update yt-dlp downloads the latest
release from yt-dlp's GitHub releases into the app's folder, checks its checksum and that it runs,
and uses it from then on; the built-in one stays as the fallback.

## Missing tracks

A track can be missing because its file is named differently on Soulseek: a Soulseek search only
finds files whose path has every word searched for, so "ft. Guest" or "(Remixer Remix)" can hide a
file that is there. **Find renamed tracks** (on a set) and **Find likely matches** (in a track's Fix
panel) try a ladder of broader searches (without the featured artists, the remixer as the artist,
artist and title, the title alone, a wildcard past filtered names) in one Soulseek session, then
score every file found on its title, artist, version (the right remix, edit or acappella), length
and quality (tl2mixxx's `match.py`, `tl2mixxx suggest`). Files that surely are the track are
downloaded and kept as its fix (Undo still works); the rest are listed, with why, for you to pick.
A plain retry also searches harder for what's still missing (sockseek's `--remove-ft`,
`--artist-maybe-wrong`, `--desperate`).

## Run

Open `dist/Set Downloader.app` (build it with `scripts/build-app.sh`). It has Python, tl2mixxx,
sockseek, yt-dlp and ffmpeg inside, so it runs from anywhere: drag it to Applications if you like. `./run.sh` starts it
from the source folder instead.

## Build

```sh
scripts/build-app.sh      # web UI, then PyInstaller into dist/Set Downloader.app, then sockseek
```

sockseek comes from `../tl2mixxx/dist/1001tracklists-tools/sockseek` (`SOCKSEEK=<path>` picks
another). The app looks for sockseek in this order: the path in Settings, one on your PATH, the one
inside the app.

tl2mixxx imports yt-dlp, mutagen, imageio-ffmpeg and macOS Vision only when they're needed, so the
script names them for PyInstaller (yt-dlp with all its extractors and its metadata, for the version
Settings shows; imageio-ffmpeg's ffmpeg binary; pyobjc's Vision for pictures), leaves Set Copy
out, and at the end runs the built app's tl2mixxx and yt-dlp and the ffmpeg inside to check they
are there. The app is about 205 MB, most of it sockseek (117 MB) and ffmpeg (49 MB); Apple
Silicon only, like the ffmpeg it bundles.

## Develop

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e "../tl2mixxx[media,ocr]" -e . pytest pyinstaller
.venv/bin/python -m pytest                    # fake sockseek and fake yt-dlp: never the real Soulseek or YouTube
.venv/bin/set-downloader                      # the app, in its window
.venv/bin/set-downloader --browser            # or served to your browser (prints the address)
```

The tests use `tests/fake_sockseek.py` for sockseek and, for the YouTube, recording and
paste-anything parts, `tests/fake_tl2mixxx.py`: tl2mixxx as it is with yt-dlp's searches and
downloads faked (ffmpeg sine tones). The one test that reads a picture uses macOS Vision.

To work against scratch folders with the fake sockseek instead of your own music folder and login
(turn YouTube off in Settings to stay offline, or see "Developing the UI" in API.md):

```sh
SETDL_MIXXX_LOGIN=/nonexistent .venv/bin/set-downloader --browser --data-dir /tmp/setdl/data \
    --music-dir /tmp/setdl/music --sockseek "$PWD/tests/fake_sockseek.py"
```

## Layout

| Path | What |
|---|---|
| `setdl/app.py` | Entry point: window, `--browser` dev mode, `--tl2mixxx` (runs the tl2mixxx CLI; how the app runs its jobs) and `--helper` (the app's own job commands) |
| `setdl/server.py` | HTTP server: token, Host and Origin checks, routes, static files, Server-Sent Events |
| `setdl/core.py` | The app's logic behind the API: drafts, downloads and the sources after Soulseek, fixes |
| `setdl/jobs.py` | tl2mixxx child processes: the Soulseek and YouTube lanes, Stop, live output and progress |
| `setdl/resolve.py` | Paste anything: links and dropped files checked, `tl2mixxx resolve` run on them |
| `setdl/sets.py`, `drafts.py` | Sets in the music folder; drafts (resolved, pages, text) and uploads |
| `setdl/helpers.py` | `--helper take` (download a video picked in Find on YouTube) and `ytdlp-version` |
| `setdl/ytdlp.py` | The yt-dlp in use, updating it from GitHub, making children import the update |
| `setdl/settings.py`, `login.py`, `paths.py` | Settings, the Soulseek login file, locations |

The app keeps its settings, Soulseek login (`sockseek.conf`, mode 0600), an updated yt-dlp
(`yt-dlp/`) and scratch files in `~/Library/Application Support/Set Downloader/`. Recordings
downloaded to cut tracks from are kept in tl2mixxx's cache (`~/Library/Caches/tl2mixxx`, 2 GB
at most: the least recently used go first). Without a login of its own, it uses the one the
Mixxx fork saved.
