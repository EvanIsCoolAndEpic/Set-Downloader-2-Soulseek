# Set Downloader

Drop a saved 1001Tracklists page (or paste a tracklist), and Set Downloader downloads the set's
tracks from Soulseek into `~/Music/1001Tracklists/<set>/`, with a playlist in set order. It can also
retry what's missing and fix single tracks: search again, pick a result, or use your own file.

[tl2mixxx](../tl2mixxx) and [sockseek](https://github.com/fiso64/sockseek) do the work. This app is
the window around them: a Python backend (`setdl/`) serving a web UI (`web/`) in a pywebview window.
The API is described in [API.md](API.md).

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
