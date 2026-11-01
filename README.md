# Set Downloader

Drop a saved 1001Tracklists page (or paste a tracklist), and Set Downloader downloads the set's
tracks from Soulseek into `~/Music/1001Tracklists/<set>/`, with a playlist in set order. It can also
retry what's missing and fix single tracks: search again, pick a result, or use your own file.

[tl2mixxx](../tl2mixxx) and [sockseek](https://github.com/fiso64/sockseek) do the work. This app is
the window around them: a Python backend (`setdl/`) serving a web UI (`web/`) in a pywebview window.
The API is described in [API.md](API.md).

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

Open `dist/Set Downloader.app` (build it with `scripts/build-app.sh`). It has Python, tl2mixxx and
sockseek inside, so it runs from anywhere: drag it to Applications if you like. `./run.sh` starts it
from the source folder instead.

## Build

```sh
scripts/build-app.sh      # web UI, then PyInstaller into dist/Set Downloader.app, then sockseek
```

sockseek comes from `../tl2mixxx/dist/1001tracklists-tools/sockseek` (`SOCKSEEK=<path>` picks
another). The app looks for sockseek in this order: the path in Settings, one on your PATH, the one
inside the app.

## Develop

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ../tl2mixxx -e . pytest pyinstaller
.venv/bin/python -m pytest                    # uses tests/fake_sockseek.py, never the real Soulseek
.venv/bin/set-downloader                      # the app, in its window
.venv/bin/set-downloader --browser            # or served to your browser (prints the address)
```

To work against scratch folders with the fake sockseek instead of your own music folder and login:

```sh
SETDL_MIXXX_LOGIN=/nonexistent .venv/bin/set-downloader --browser --data-dir /tmp/setdl/data \
    --music-dir /tmp/setdl/music --sockseek "$PWD/tests/fake_sockseek.py"
```

## Layout

| Path | What |
|---|---|
| `setdl/app.py` | Entry point: window, `--browser` dev mode, `--tl2mixxx` (runs the tl2mixxx CLI; how the built app runs its jobs) |
| `setdl/server.py` | HTTP server: token, Host and Origin checks, routes, static files, Server-Sent Events |
| `setdl/core.py` | The app's logic behind the API |
| `setdl/jobs.py` | tl2mixxx child processes: the Soulseek queue, Stop, live output |
| `setdl/sets.py`, `drafts.py` | Sets in the music folder; dropped pages, pasted text and uploads |
| `setdl/settings.py`, `login.py`, `paths.py` | Settings, the Soulseek login file, locations |

The app keeps its settings, Soulseek login (`sockseek.conf`, mode 0600) and scratch files in
`~/Library/Application Support/Set Downloader/`. Without a login of its own, it uses the one the
Mixxx fork saved.
