# Set Downloader API

The window (pywebview) shows the built UI from `web/dist`, served by a small Python HTTP server on
`127.0.0.1` at a free port. The UI talks to that server through the JSON API below. tl2mixxx,
sockseek, yt-dlp and ffmpeg do the work: every download, search, fix and reading of a link is a
tl2mixxx process (or one of the app's own helpers) that the server runs and streams to the page.

Everything here is relative to the page's own origin (`/api/...`), so the UI never needs to know
the port.

## Contents

- [The basics](#the-basics): token, errors, limits, live events, CSP
- [Endpoints at a glance](#endpoints-at-a-glance)
- [State and settings](#state-and-settings)
- [Soulseek login](#soulseek-login)
- [Drafts: paste anything](#drafts-paste-anything)
- [Downloads](#downloads) (and [what comes after Soulseek](#after-soulseek-youtube-the-recording-finishing))
- [Sets](#sets)
- [Searching Soulseek](#searching-soulseek)
- [Fixing a track](#fixing-a-track)
- [Find on YouTube, cut from the set, finish files](#find-on-youtube-cut-from-the-set-finish-files)
- [Uploads](#uploads-the-users-own-audio-file)
- [yt-dlp](#yt-dlp)
- [Jobs](#jobs)
- [Live events (SSE)](#live-events-server-sent-events)
- [Show in Finder, open a link](#show-in-finder-open-a-link)
- [Typical flows](#typical-flows)
- [Developing the UI](#developing-the-ui)

---

## The basics

### The token

The window opens `http://127.0.0.1:<port>/#token=<token>`. The token is random for each launch.
Because it is in the URL fragment, it is never sent to the server and never appears in its logs.

On load, the page:

1. reads it from `location.hash` (`new URLSearchParams(location.hash.slice(1)).get("token")`),
2. keeps it in `sessionStorage`, so a reload still works,
3. removes it from the address bar (`history.replaceState(null, "", location.pathname)`).

Every `/api/...` request must send it in the header **`X-SetDL-Token: <token>`**. Without it, or
with a wrong one, the answer is `401 bad_token`. Static files (`/`, `/assets/...`) don't need it.

The server also refuses (`403`) a request when:

- its `Host` isn't `127.0.0.1:<port>` or `localhost:<port>` (`bad_host`), or
- it carries an `Origin` other than the page's own, or `Sec-Fetch-Site` is `cross-site` or
  `same-site` (`bad_origin`).

Normal `fetch()` calls from the page pass all of these. Don't set `mode: "no-cors"`.

### Requests and responses

- Request bodies are JSON (`Content-Type: application/json`). The exceptions are the two raw-file
  uploads (`POST /api/drafts/page` and `POST /api/uploads`), which take the file's bytes as the body.
  A `File` or `Blob` from a drop or an `<input type=file>` can be passed straight to `fetch` as the
  `body`.
- Every response is JSON (`application/json; charset=utf-8`), except the event stream.
- Times are ISO 8601 strings with the local UTC offset, e.g. `"2026-10-31T20:15:04+01:00"`.
  `null` means not yet.
- Durations (`duration`, `cue`, `length`) are whole seconds. `size` is in bytes.

### Errors

Every error has the same shape:

```json
{"error": {"code": "login_required", "message": "Downloading from Soulseek needs a Soulseek login. Enter one in the settings."}}
```

`message` is written for people and can be shown as is. `code` is for the UI's own logic. These can
happen on any endpoint:

| Status | code | When |
|---|---|---|
| 400 | `bad_request`, `bad_json`, `incomplete` | Malformed body, not a JSON object, or the body was cut short |
| 401 | `bad_token` | Missing or wrong `X-SetDL-Token` |
| 403 | `bad_host`, `bad_origin` | See [The token](#the-token) |
| 404 | `not_found` | No such endpoint |
| 405 | `method_not_allowed` | The path exists, but not with this method |
| 411 | `length_required` | A chunked request body (send a `Content-Length` instead) |
| 413 | `too_large` | The body is over the limit (see below) |
| 500 | `internal` | A bug. `message` says what failed |

Each endpoint below lists its own errors.

### Size limits

The limits are also in `GET /api/state` → `limits`. Check sizes before uploading: when a body is too
big, the server answers `413` and closes the connection without reading the rest. Depending on
timing, the browser may report that as a network error instead of the 413.

| What | Limit |
|---|---|
| A dropped file: page, list, CSV, JSON or picture (`POST /api/drafts/page`) | 20 MB (`limits.page_bytes`) |
| Pasted text or a link, as JSON (`POST /api/drafts/text`, `POST /api/drafts/resolve`) | 2 MB (`limits.text_bytes`) |
| An audio file (`POST /api/uploads`) | 600 MB (`limits.upload_bytes`) |
| Any other JSON body | 256 KB |
| A Soulseek search | 300 characters (`limits.query_chars`) |

### Content Security Policy

The served HTML has this CSP:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
font-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none';
form-action 'none'; frame-ancestors 'none'
```

What this means for the UI:

- Bundle fonts, icons and images into the build. Nothing loads from a CDN or from Google Fonts.
- Don't use inline `<script>` tags. Vite's normal build output is fine.
- Inline styles are allowed.

Track names come from web pages, comments, pictures and Soulseek, so treat them as untrusted text
and render them as text (React does this by default).

### What the page sends is checked

- Links to read (`POST /api/drafts/resolve`) must be `http(s)://` addresses on the web: no other
  scheme, no user name in them, no IP addresses, `localhost` or `.local` names, and no name that
  resolves to the Mac or the local network (`localtest.me`). A `spotify:` URI is turned into its
  `https://open.spotify.com/...` page.
- Where a link redirects, and every address tl2mixxx and the app's helper fetch (pages, videos,
  recordings, covers named in a shared tracklist), is checked when the connection is made: only
  addresses on the internet, never loopback or the local network. A proxy set in macOS is still used.
- A tracklist's `recording` is used only when it's a web address (a shared `.json` can't point the
  cut at a file on the Mac).
- Nothing the page sends reaches tl2mixxx as a path: dropped files are written into the draft's
  own folder first, and pasted text that isn't one link is parsed as text (a path pasted in is
  just text, never opened).
- Pictures must be PNG, JPEG or HEIC by their first bytes.
- Links picked from Find on YouTube must be YouTube or SoundCloud addresses.
- `yt-dlp` updates come only from GitHub over HTTPS (redirects checked), must match the release's
  SHA2-256SUMS and must import in a child before they're used.

---

## Endpoints at a glance

| Method | Path | What it does |
|---|---|---|
| GET | `/api/state` | App state: settings, login, sockseek, music folder, job counts, limits |
| PUT | `/api/settings` | Change settings |
| PUT | `/api/login` | Save the Soulseek login |
| DELETE | `/api/login` | Forget the app's Soulseek login |
| POST | `/api/drafts/resolve` | Paste anything: a link (read by a `resolve` job) or text → draft |
| POST | `/api/drafts/page?name=…` | A dropped file (raw body): page, `.txt`, Exportify `.csv`, `.json`, picture → draft |
| POST | `/api/drafts/text` | Pasted text → draft |
| GET | `/api/drafts/{id}` | A draft, recomputed |
| DELETE | `/api/drafts/{id}` | Throw a draft away |
| POST | `/api/drafts/{id}/pick` | Take another of the tracklists a link gave |
| POST | `/api/downloads` | Download a draft's set, or retry a set (Soulseek, then YouTube, the recording, finishing) |
| GET | `/api/sets` | Every set in the music folder |
| GET | `/api/sets/{set}` | One set |
| GET | `/api/sets/{set}/tracks` | A set's tracks, with the file each one has |
| POST | `/api/sets/{set}/tracks/{row}/fix` | Fix one track (a Soulseek result, a picked video, a search, a file, undo) |
| POST | `/api/sets/{set}/tracks/{row}/suggest` | Likely files under other names on Soulseek |
| POST | `/api/sets/{set}/suggest` | Find renamed tracks for every missing track |
| POST | `/api/sets/{set}/tracks/{row}/fallback` | Find on YouTube (YouTube Music, YouTube, SoundCloud) |
| POST | `/api/sets/{set}/tracks/{row}/cut` | Cut one track out of the set's recording |
| POST | `/api/sets/{set}/finish` | Convert a set's files and write their tags |
| POST | `/api/searches` | Search Soulseek (a queued job) |
| POST | `/api/uploads?name=…` | Upload an audio file of the user's own (raw body) |
| DELETE | `/api/uploads/{id}` | Throw an upload away |
| GET | `/api/jobs` | All jobs, newest first |
| GET | `/api/jobs/{id}` | One job, with its log |
| POST | `/api/jobs/{id}/stop` | Stop a job, or take it out of the queue |
| GET | `/api/events` | Live events (Server-Sent Events) |
| POST | `/api/reveal` | Show a set or file in the Finder |
| POST | `/api/open-url` | Open a web address in the browser |
| POST | `/api/ytdlp/update` | Update yt-dlp from its GitHub releases |
| DELETE | `/api/ytdlp/update` | Use the built-in yt-dlp again |

`{set}` is a set's id, its folder name, URL-encoded (`encodeURIComponent`). `{id}` values are
generated by the server.

---

## State and settings

### `GET /api/state`

```json
{
  "app": {"name": "Set Downloader", "version": "0.1.0"},
  "settings": {"music_dir": "/Users/you/Music/1001Tracklists", "sockseek": "", "mashups": "components",
               "sources": ["soulseek", "youtube", "mix"], "quality": "best", "format": "keep", "tags": true},
  "music_dir": {"path": "/Users/you/Music/1001Tracklists", "exists": true},
  "login": {"source": "mixxx", "username": null, "path": "/Users/you/Library/Application Support/Mixxx/1001tracklists-sockseek.conf"},
  "sockseek": {"path": "/opt/homebrew/bin/sockseek", "source": "automatic", "setting": "", "found": true, "error": null},
  "ytdlp": {"version": "2026.10.26", "source": "bundled", "bundled": "2026.10.26", "updated": null,
            "updating": false, "step": "", "message": "", "error": "", "checked": null},
  "jobs": {"running": 1, "queued": 0},
  "limits": {"page_bytes": 20971520, "text_bytes": 2097152, "upload_bytes": 629145600, "query_chars": 300}
}
```

- `settings`: what is saved.
  - `music_dir`: each set gets a folder in here. The default is `~/Music/1001Tracklists`, the same
    folder the Mixxx fork and tl2mixxx use, so sets already downloaded there show up.
  - `sockseek`: `""` means find it automatically.
  - `mashups`: the default for new sets (see [Mashups](#mashups)).
  - `sources`: where tracks come from, the ones turned on, always in this order: `"soulseek"`,
    `"youtube"` (YouTube Music, YouTube and SoundCloud), `"mix"` (cut out of the set's
    recording). See [After Soulseek](#after-soulseek-youtube-the-recording-finishing).
  - `quality`: what Soulseek downloads. `"lossless"` (only FLAC, WAV, AIFF: sockseek
    `--format flac,wav,aiff,aif --pref-format flac`), `"best"` (lossless preferred:
    `--pref-format flac,wav,aiff,aif`) or `"fast"` (the first good file: `--fast-search
    --search-timeout 2500`, and one YouTube search per track instead of two). A file picked from a
    search is downloaded whatever this says.
  - `format`: what a set's files end up as: `"keep"`, `"flac"`, `"aiff"`, `"mp3"` (320 kbps) or
    `"wav"` (tl2mixxx `finish --format`; also how YouTube downloads and cuts are saved).
  - `tags`: write names, the set as the album, the position as the track number, where the file
    came from and a cover.
- `music_dir.exists`: `false` until the first download creates the folder.
- `login`: see [Soulseek login](#soulseek-login).
- `sockseek`: the program that is used.
  - `source` is `"setting"` (the path in the settings), `"automatic"` (`$SOCKSEEK` or `PATH`),
    `"bundled"` (the copy inside the app), or `null` when none was found.
  - When `found` is `false`, `error` says why (for example, the path in the settings doesn't exist).
    Downloads and searches then fail with `409 sockseek_missing`.
- `ytdlp`: the yt-dlp tl2mixxx uses (see [yt-dlp](#yt-dlp)).
- `jobs`: how many jobs are running (including stopping) and how many are queued.

### `PUT /api/settings`

Send any subset of the settings:

```json
{"music_dir": "/Volumes/Music/Sets", "sockseek": "", "mashups": "both",
 "sources": ["youtube", "mix"], "quality": "lossless", "format": "aiff", "tags": true}
```

- `music_dir`: a full path. `~/…` is expanded. It doesn't have to exist yet, but it can't be a file
  or `/`.
- `sockseek`: a full path to an executable file, or `""` to find it automatically.
- `mashups`: `"components"`, `"original"` or `"both"`.
- `sources`: a list of `"soulseek"`, `"youtube"`, `"mix"` (any order; it's kept in that order).
  An empty list is allowed (nothing can be downloaded then: say so).
- `quality`: `"lossless"`, `"best"` or `"fast"`. `format`: `"keep"`, `"flac"`, `"aiff"`, `"mp3"`,
  `"wav"`. `tags`: `true` or `false`.

The response is `200` with the whole state, as `GET /api/state` returns it. A `state` event is sent
too. Jobs that are already queued or running keep the settings they started with.

| Status | code | When |
|---|---|---|
| 400 | `bad_music_dir` | Not a full path, `/`, an existing file, or has control characters |
| 400 | `bad_sockseek` | Not a full path, or no executable file there |
| 400 | `bad_mashups` | Not one of the three choices |
| 400 | `bad_sources`, `bad_quality`, `bad_format`, `bad_tags` | Not one of the choices above |
| 400 | `unknown_setting` | Any other key |

### Mashups

A mashup row on a 1001Tracklists page ("Kettle vs. Saltmarsh - Ghosts vs. Pressure (DJ Edit)") is
usually followed by its parts (the source tracks). The choice is:

- `components` (the default): download the parts. DJ edits are rarely on Soulseek.
- `original`: download the mashup itself.
- `both`: download both.

Each set remembers the choice it was last downloaded with. A set's tracks, its counts and its
retries use that choice.

---

## Soulseek login

sockseek logs in to Soulseek with a config file passed with `-c`. Which file is used:

1. The app's own file, `~/Library/Application Support/Set Downloader/sockseek.conf`, when it has a
   username. This file is written by `PUT /api/login` with mode `0600`.
2. Otherwise, the file the Mixxx fork saved, if it exists:
   `~/Library/Application Support/Mixxx/1001tracklists-sockseek.conf`. It is used as it is. The
   app never reads it, so its username is unknown (`null`).
3. Otherwise, none. Downloads, searches and Soulseek fixes then fail with `409 login_required`.

The `login` object appears in `GET /api/state` and in the login responses:

```json
{"source": "app", "username": "djname", "path": "/Users/you/Library/Application Support/Set Downloader/sockseek.conf"}
{"source": "mixxx", "username": null, "path": "/Users/you/Library/Application Support/Mixxx/1001tracklists-sockseek.conf"}
{"source": "none", "username": null, "path": null}
```

The password is never sent back by any endpoint and never written to any log.

Wording from the Mixxx fork, for the login form: "Use a different account than in your regular
Soulseek client (e.g. Nicotine+): two programs logged in with the same account keep disconnecting
each other. If the name is new, Soulseek creates the account the first time it logs in."

For `source: "mixxx"`, show something like "Using the login from Mixxx's 1001Tracklists settings",
and offer to enter another one.

### `PUT /api/login`

```json
{"username": "djname", "password": "secret"}
```

The response is `200 {"login": {...}}` (see above), and a `state` event is sent.

| Status | code | When |
|---|---|---|
| 400 | `bad_login` | The username or password is empty or too long (100 / 200 characters), either one has a line break, tab or other control character, or the password starts or ends with a space |

### `DELETE /api/login`

Forgets the app's own login. The Mixxx fork's file is used again if there is one. The response is
`200 {"login": {...}}`, and a `state` event is sent.

---

## Drafts: paste anything

A draft is a parsed tracklist that hasn't been downloaded yet. The UI shows it, where it came from
and, when a link gave several, the other tracklists to pick from; the user picks the mashups
choice, and then starts the download. Drafts live in the app's scratch folder and are removed
after 3 days.

Anything that isn't a saved 1001Tracklists page or plain text is read by `tl2mixxx resolve`, and
the draft keeps the tracklist JSON it made. A set downloaded from it keeps that JSON as
`_tracklist.json` (a saved page stays `_tracklist.html`, text `_tracklist.txt`).

### `POST /api/drafts/resolve`

One input for anything pasted: a link or a tracklist.

```json
{"input": "https://www.youtube.com/watch?v=abcdefghijk", "title": "optional"}
```

- **A link** (one line, no spaces: `https://...`, `www.x.com/...`, `x.com/...` or
  `spotify:playlist:...`): YouTube or SoundCloud (the description, the chapters and the top
  comments, ranked; a playlist becomes one track per video), Mixcloud, Spotify and Apple Music
  playlists and albums, any other page yt-dlp reads. Reading one takes a while (comments: up to
  30 seconds), so it's a `resolve` [job](#jobs): `202 {"job": {...}}`. When the job is `done`, its
  `result.draft` is the new draft's id (`GET /api/drafts/{id}`). When it `failed`, its `message`
  says why in tl2mixxx's words, and for a Spotify link `result.help` says how to use Exportify
  instead (show it with a button that opens `https://exportify.app`). Stopping it throws the
  draft away.
- **Anything else** is a pasted tracklist, read at once: `201 {"draft": {...}}`, as
  `POST /api/drafts/text` would.

The `resolve` job's `result`:

```json
{"draft": "9f1c2ab04d7e3f10", "kind": "youtube", "url": "https://www.youtube.com/watch?v=abcdefghijk",
 "help": "", "title": "Kettle | Rooftop Session", "count": 24}
```

`kind` is what the link is: `youtube`, `youtube-playlist`, `soundcloud`, `mixcloud`, `spotify`,
`apple` or `link`. On failure, `draft` is `null` and there's no `title` or `count`.

| Status | code | When |
|---|---|---|
| 400 | `empty` | Nothing pasted |
| 400 | `bad_title` | `title` isn't a string |
| 400 | `bad_url` | A link that isn't on the web: another scheme (`file:`, `ftp:`...), an IP address, `localhost`, a `.local` name or one that resolves to the Mac or the local network, a user name in it |
| 413 | `too_large` | Over 2 MB |
| 422 | `save_the_page` | A 1001Tracklists link: their terms don't allow fetching pages. `message` says to save the page and drop it |
| 422 | `not_a_tracklist` | Text with no track lines |

Help wording for Spotify, from the UI: "Spotify playlists over 100 tracks: export them with
Exportify and drop the .csv here."

### `POST /api/drafts/page?name={file name}`

The body is the dropped file's raw bytes. `name` is the file's name, URL-encoded; its extension
says what it is:

| Extension | Read as |
|---|---|
| `.html`, `.htm` | A page saved from 1001Tracklists (any encoding). Another page (a saved Spotify or Apple Music page, any page with a list) goes to `tl2mixxx resolve` |
| `.txt` | A tracklist as text (also UTF-16, like rekordbox's playlist export), an M3U playlist or a CUE sheet |
| `.csv` | An Exportify export (tracks; saved albums are listed but not downloaded yet), or any CSV with artist and title columns. The set is named after the file (`Liked_Songs.csv` is "Liked Songs") |
| `.json` | A tracklist JSON (`tl2mixxx resolve`'s, or any `{"title", "tracks": [{"artist", "title"}]}`) |
| `.png`, `.jpg`, `.jpeg`, `.heic`, `.heif` | A screenshot of a tracklist, read with macOS Vision. Named after the file. Takes a few seconds; the first picture after the app was installed or updated takes about half a minute (Vision compiles its models), and if Vision fails that first reading the app reads it once more, in a new process |
| anything else | A page |

```js
await fetch(`/api/drafts/page?name=${encodeURIComponent(file.name)}`, {method: "POST", headers, body: file})
```

The response is `201` with a [draft](#the-draft-object). A picture pasted from the clipboard has no
name: give it one, e.g. `Screenshot 2026-10-31 at 21.04.png`.

| Status | code | When |
|---|---|---|
| 400 | `empty` | The file is empty |
| 413 | `too_large` | Over 20 MB |
| 415 | `not_an_image` | A picture's name, but not a PNG, JPEG or HEIC file |
| 422 | `not_a_tracklist` | No tracks found. `message` says why (tl2mixxx's words), e.g. how to save the page properly |
| 504 | `resolve_timeout` | Reading it took too long (45 s, a picture 180 s) |

### `POST /api/drafts/text`

```json
{"text": "Four Tet @ Somewhere 2026-10-30\n01. Kettle - Ghosts [RINSE]\nw/ Vox Unit - Say It\n...", "title": "optional"}
```

The set's name is the first line that isn't a track. Each track is a line of its own:
`01. Artist - Title [LABEL]`, `w/ Artist - Title` (played on top of the previous track),
`[12:34] 02. ...` (with a cue time), or `ID - ID` (unidentified). Mashups can't be told apart in
text.

- `title`, if given, becomes the first line, so it is the set's name.
- With no name at all, the set is named "Pasted tracklist YYYY-MM-DD HH.MM.SS".

The response is `201` with a [draft](#the-draft-object).

| Status | code | When |
|---|---|---|
| 400 | `empty` | No text |
| 400 | `bad_title` | `title` isn't a string |
| 413 | `too_large` | Over 2 MB |
| 422 | `not_a_tracklist` | No track lines found |

Placeholder and help wording from the Mixxx fork: "Paste the tracklist: the set's name on the first
line, then one track per line, like "01. Artist - Title [LABEL]" or "w/ Artist - Title" for a track
played on top."

### `POST /api/drafts/{id}/pick`

```json
{"pick": 1}
```

Takes another of the tracklists a link gave (`alternatives[].pick`), without reading the link
again. The response is `200` with the draft.

| Status | code | When |
|---|---|---|
| 400 | `bad_pick` | Not a whole number from 0 |
| 404 | `no_draft` | No such draft |
| 409 | `no_alternatives` | A saved page or text: nothing to pick from |
| 422 | `not_a_tracklist` | No such alternative (`message` says how many there are) |

### `GET /api/drafts/{id}`

Returns the draft, recomputed. `set_exists` and the counts follow the current music folder and any
fixes made since. The response is `200` with a draft, or `404 no_draft`.

### `DELETE /api/drafts/{id}`

The response is `200 {"ok": true}`.

| Status | code | When |
|---|---|---|
| 404 | `no_draft` | No such draft |
| 409 | `draft_in_use` | A queued or running download is using it |

### The draft object

```json
{
  "id": "9f1c2ab04d7e3f10",
  "source": "page",
  "file": "tracklist.html",
  "title": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
  "url": "https://www.1001tracklists.com/tracklist/abc123/dj-example-warehouse.html",
  "set": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
  "set_exists": false,
  "mashups": "components",
  "has_mashups": true,
  "unidentified": 2,
  "counts": {"components": 7, "original": 6, "both": 8},
  "kind": "1001tracklists",
  "origin": {},
  "picked": 0,
  "from": null,
  "alternatives": [],
  "warnings": [],
  "recording": "",
  "cues": 2,
  "albums": 0,
  "tracks": [
    {"row": 1, "number": "01", "kind": "track", "artist": "Northern Lights & Kettle ft. Mara",
     "title": "Fog Machine (Extended Mix)", "display": "Northern Lights & Kettle ft. Mara - Fog Machine (Extended Mix)",
     "label": "SPEEDBUMP", "duration": 372, "cue": null, "unidentified": false, "mashup_of": null,
     "downloads": {"components": true, "original": true, "both": true}},
    {"row": 4, "number": "03", "kind": "mashup", "artist": "Kettle vs. Saltmarsh", "title": "Ghosts vs. Pressure (DJ Example Edit)",
     "display": "...", "label": "", "duration": null, "cue": 3735, "unidentified": false, "mashup_of": null,
     "downloads": {"components": false, "original": true, "both": true}},
    {"row": 5, "number": "", "kind": "component", "artist": "Kettle", "title": "Ghosts", "display": "Kettle - Ghosts",
     "label": "", "duration": 284, "cue": null, "unidentified": false, "mashup_of": 4,
     "downloads": {"components": true, "original": false, "both": true}},
    {"row": 7, "number": "04", "kind": "track", "artist": "ID", "title": "ID", "display": "ID - ID",
     "label": "", "duration": null, "cue": null, "unidentified": true, "mashup_of": null,
     "downloads": {"components": false, "original": false, "both": false}}
  ]
}
```

| Field | Meaning |
|---|---|
| `source` | `"page"` (a saved 1001Tracklists page), `"text"` (pasted, or a `.txt` file) or `"resolved"` (anything else, kept as tl2mixxx's JSON) |
| `title` | The set's name |
| `url` | The page's 1001Tracklists address, or `""` |
| `set` | The id the set will have (its folder name in the music folder) |
| `set_exists` | The set was downloaded before. Downloading again keeps what is there and only searches for what's missing |
| `mashups` | The suggested choice: the set's own choice if it exists, else the setting |
| `has_mashups` | Show the mashups choice only when this is `true` |
| `unidentified` | How many rows are IDs |
| `counts` | How many tracks get a file under each choice. A track played twice counts twice, but is downloaded once |
| `kind` | Where the tracklist came from: `1001tracklists`, `youtube`, `soundcloud`, `mixcloud`, `exportify`, `spotify`, `apple`, `text`, `image` (a picture), `csv`, `web`, or `""` |
| `origin` | What was read: `{"kind": "youtube" \| "csv" \| "image" \| "json" \| "page" \| ..., "name": "<file>", "url": "<link>"}`. `{}` for a saved 1001Tracklists page and text |
| `alternatives` | When a link gave several tracklists (the description, the chapters, each comment, comments pieced together): `{pick, source, label, count, cues, likes, author, pinned, by_uploader, score}` each, best first, without their tracks. Empty when there was only one |
| `picked` | Which alternative this is (`POST /api/drafts/{id}/pick` changes it) |
| `from` | The taken alternative's `{source, label}`: `source` is `description`, `chapters`, `comment`, `comments` (pieced together from several) or `sections` (Mixcloud's own list); `label` is e.g. `"comment by @x (820 likes, pinned)"`. Also set when it was the only one; there `source` can also be `playlist`, `text`, `csv`, `image`, `page`, `json`, `spotify` or `apple`. `null` for a saved 1001Tracklists page or pasted text read without `resolve` |
| `warnings` | Things to tell the user, e.g. "Spotify's page only lists the first 100 tracks: ..." or "Read from a picture: check the names." |
| `recording` | The set's recording (the video a list came from) when it's a web address, or `""`. Tracks with a `cue` can be cut out of it |
| `cues` | How many rows have a time |
| `albums` | How many rows are whole albums (`kind: "album"`, from saved albums): listed, not downloaded |
| `tracks` | Every row of the page, in order |

How the UI says where a list came from: "From the comments on {title}, 24 tracks with times",
"From the description of {title}", "Pieced together from the comments on {title}", "Exportify:
Liked Songs, 312 tracks", "Spotify: {title}", "From a screenshot", "From pasted text", "From a saved
1001Tracklists page".

Each track has:

| Field | Meaning |
|---|---|
| `row` | Its row on the page (1-based, counting every row) |
| `number` | What the page shows: `"01"`, `"w/"`, or `""` for a mashup's parts |
| `kind` | `"track"`, `"with"` (a `w/` row), `"mashup"`, `"component"` (a part of the mashup at row `mashup_of`), or `"album"` (a whole album: not downloaded) |
| `display` | `"Artist - Title"` |
| `label` | The record label, or `""` |
| `duration` | Seconds, or `null` |
| `cue` | Seconds into the set, or `null` |
| `unidentified` | `true` for an ID. IDs aren't downloaded, unless a fix gave one a file |
| `downloads` | Whether it gets a file under each mashups choice |

---

## Downloads

### `POST /api/downloads`

To download a draft's set:

```json
{"draft": "9f1c2ab04d7e3f10", "mashups": "components"}
```

To retry a set (search again for what's still missing):

```json
{"set": "DJ Example @ Warehouse Project, Manchester 2026-10-01"}
```

`mashups` is optional. It defaults to the set's own choice, or the setting for a new set, and is
remembered for the set.

This queues a `download` [job](#the-job-object) in the Soulseek queue, and when it ends, the steps
[after Soulseek](#after-soulseek-youtube-the-recording-finishing). With Soulseek turned off in the
settings, the first job is one of those steps instead.

- `202 {"job": {...}, "already_queued": false}` when a new job was queued.
- `200 {"job": {...}, "already_queued": true}` when this set's download (or a step after it) is
  queued or running. The response is that job, and nothing new is queued.

While a new set's first download is queued or running, it is already listed in `GET /api/sets`
with `"pending": true`.

A download writes this into `<music dir>/<set>/`:

- the tracks,
- `<set>.m3u8`, a playlist in set order,
- `_missing.csv`,
- sockseek's `_index.csv`,
- a copy of the page (`_tracklist.html`, `_tracklist.txt`, or `_tracklist.json` for anything
  `tl2mixxx resolve` read).

| Status | code | When |
|---|---|---|
| 400 | `bad_download` | Neither or both of `draft` and `set` |
| 400 | `bad_mashups` | Not one of the three choices |
| 400 | `bad_set_id` | Not a folder name |
| 403 | `outside_music_dir` | The set's folder isn't inside the music folder (a link to elsewhere) |
| 404 | `no_draft` | No such draft |
| 404 | `not_found` | No such set |
| 409 | `login_required` | No Soulseek login (Soulseek is on) |
| 409 | `sockseek_missing` | sockseek wasn't found (Soulseek is on) |
| 409 | `no_sources` | Soulseek is off, and neither YouTube nor cutting from the recording can get anything (both off, or no recording with times) |
| 409 | `nothing_missing` | Soulseek is off, and every track that can be downloaded has a file |
| 422 | `not_a_tracklist` | The draft can't be parsed anymore |

Wording from the Mixxx fork: "Retrying only searches for what's still missing, then rebuilds the
playlist in set order. Downloads that finish later on Soulseek can be picked up just by retrying."

### After Soulseek: YouTube, the recording, finishing

When a download job ends (not when the user stopped it), the set goes on through the sources
turned on in the settings, as queued jobs of their own, one after the other. That includes a
download that failed because Soulseek refused the login: the steps after it don't need it.

Such a download ends `failed`, its `error` and `message` saying why. A wrong password is
sockseek's own message. For any other refusal the app looks at the server once, after sockseek
has stopped: one connection to `server.slsknet.org:2242` that sends nothing. A server that hangs up
at once means Soulseek is blocking this network (it bans a network for a while after too many
logins from it), no connection means the server can't be reached, and a server that waits for
the login means the account itself was refused. The page shows the set's last failed Soulseek job
above its tracks. `SETDL_SOULSEEK_SERVER=host:port` points the check elsewhere; empty turns it off
(the tests do, and use fake servers).

1. `fallback`: `tl2mixxx fallback --missing --auto`. Each missing track is looked for on YouTube
   Music, YouTube and SoundCloud; a result that surely is the track is downloaded (lossy, about
   128 to 160 kbps), saved in the set's format, tagged, and kept as the track's fix
   (`source: "youtube"` or `"soundcloud"`). Only when tracks are missing and `"youtube"` is on.
2. `cut`: `tl2mixxx cut --missing`. What is still missing, and the IDs, are cut out of the set's
   recording, each from its time to the next track's (`source: "mix"`, files named
   "Artist - Title (from the mix)"). A recording that's a link is downloaded once, into tl2mixxx's
   cache. Only when `"mix"` is on, the set has a `recording` and a missing track or ID has a time.
3. `finish`: `tl2mixxx finish --all`: every file converted to the set's `format`, and with `tags`,
   tagged. Only when `format` isn't `"keep"` or `tags` is on.

The steps use the settings from when the download was asked for. Stopping any of them stops the
rest. YouTube jobs (`fallback`, `cut`) run in a lane of their own: beside a Soulseek
job, but one at a time among themselves. They don't need the Soulseek login.

A file from YouTube or the recording is a stand-in: tl2mixxx keeps it as the track's fix, so a
retry doesn't look for that track on Soulseek again. Undo the fix to look again.

---

## Sets

### `GET /api/sets`

Lists every set in the music folder: each folder directly inside it that holds a copy of a set's
page. Folders whose names start with `.` or `_` are skipped. The newest set (most recently changed)
comes first.

```json
{
  "music_dir": "/Users/you/Music/1001Tracklists",
  "sets": [
    {
      "id": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
      "name": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
      "title": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
      "url": "https://www.1001tracklists.com/tracklist/abc123/dj-example-warehouse.html",
      "source": "page",
      "kind": "1001tracklists",
      "recording": "",
      "cues": 2,
      "folder": "/Users/you/Music/1001Tracklists/DJ Example @ Warehouse Project, Manchester 2026-10-01",
      "m3u": "/Users/you/Music/1001Tracklists/DJ Example @ .../DJ Example @ ....m3u8",
      "mashups": "components",
      "downloaded": true,
      "found": 6, "missing": 1, "total": 7,
      "error": null,
      "updated": "2026-10-31T20:15:04+01:00",
      "updated_ts": 1793474104.2,
      "busy": null,
      "pending": false
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | Use it in `/api/sets/{set}` (URL-encoded) and in `POST /api/downloads` |
| `name` | The folder's name (same as `id`) |
| `title` | The set's name from its page |
| `url` | The page the list came from: a 1001Tracklists page, the YouTube video, the Spotify playlist... |
| `source` | `"page"`, `"text"` or `"resolved"`: which copy the set keeps (`_tracklist.html`, `.txt`, `.json`) |
| `kind` | Where the tracklist came from, as in a [draft](#the-draft-object). The UI names the link after it ("1001Tracklists page", "YouTube video", "Spotify") |
| `recording` | The set's recording, or `""`: with it, tracks with a time can be cut out of it |
| `cues` | How many rows have a time |
| `m3u` | The playlist, or `""` before the first download finishes |
| `downloaded` | sockseek has run for it at least once |
| `found` / `missing` / `total` | Tracks with a file, without one, and all of them, under the set's mashups choice. IDs without a file aren't counted |
| `error` | Set when the set's page can't be read. The counts are then 0 |
| `updated` | When the set's files last changed |
| `updated_ts` | The same, in seconds since 1970, for sorting |
| `busy` | `"running"` or `"queued"` while a job is working on the set, else `null` |
| `pending` | `true` while a new set's first download hasn't finished: its folder isn't complete yet. Its tracks aren't available until then |

The list is cheap to call again: summaries are cached until the set's files change. Refresh it on
`sets` events (see [Live events](#live-events-server-sent-events)).

### `GET /api/sets/{set}`

The response is `200` with one set, as above. This includes pending sets.

| Status | code | When |
|---|---|---|
| 400 | `bad_set_id` | Empty, `.`, `..`, or contains `/`, `\` or NUL |
| 403 | `outside_music_dir` | The folder is a link to somewhere outside the music folder |
| 404 | `not_found` | No such set |

### `GET /api/sets/{set}/tracks`

A set's tracks, with the file each one has. This is what Fix Tracks works from. It comes from
`tl2mixxx tracks` and takes a moment (around half a second), so call it when a set is opened and
after a fix or download of that set ends. Not on every event.

```json
{
  "set": "DJ Example @ ...", "folder": "/Users/you/Music/1001Tracklists/DJ Example @ ...",
  "title": "DJ Example @ ...", "mashups": "components",
  "found": 6, "missing": 1,
  "tracks": [
    {"row": 5, "number": "", "kind": "component", "artist": "Kettle", "title": "Ghosts", "display": "Kettle - Ghosts",
     "label": "", "duration": 284, "cue": null, "unidentified": false, "selectable": true,
     "key": "kettle|ghosts", "search": "Kettle - Ghosts", "identity": "kettle|ghosts",
     "status": "found", "retry_query": "", "reason": "",
     "file": "/Users/you/Music/1001Tracklists/DJ Example @ .../Kettle - Ghosts.mp3",
     "fix": null, "fix_in_use": false},
    {"row": 6, "number": "", "kind": "component", "artist": "Saltmarsh", "title": "Pressure", "display": "Saltmarsh - Pressure",
     "label": "RINSE", "duration": null, "cue": null, "unidentified": false, "selectable": true,
     "key": "saltmarsh|pressure", "search": "Saltmarsh - Pressure", "identity": "saltmarsh|pressure",
     "status": "missing", "retry_query": "Saltmarsh - Pressure Dub", "reason": "no search results", "file": "",
     "fix": {"query": "Saltmarsh - Pressure Dub", "updated": "2026-10-31T20:20:00"}, "fix_in_use": false}
  ]
}
```

Every row of the page is listed. Track fields:

| Field | Meaning |
|---|---|
| `row`, `number`, `kind`, `artist`, `title`, `display`, `label`, `duration`, `cue`, `unidentified` | As in a draft |
| `selectable` | Part of the set under its mashups choice. Hide rows where this is `false` (a mashup whose parts are downloaded instead, or the other way round) |
| `status` | `"found"` (has a file), `"missing"` (searched, no file), or `"skipped"` (an ID with no file: never searched) |
| `file` | The file's full path, or `""` |
| `reason` | Why it's missing, e.g. `"no search results"`, `"not found on Soulseek"`, `"your file is gone: x.wav"` |
| `search` | What the set's search looks for: the starting text for "Search Soulseek for" |
| `identity` | Send it as `identity` when fixing this track |
| `fix` | `null`, or what the user fixed: `query` (another search), `file`, `source` (`"soulseek"`, `"own"`, `"youtube"`, `"soundcloud"` or `"mix"`), `link` (the slsk:// link, the video, or `"<recording>#t=<start>,<end>"` for a cut), `updated`. Only the keys that have a value are present |
| `fix_in_use` | The file in use is the one the fix gave it |
| `retry_query` | What a retry searches for instead of `search` (`""` = its own search) |

Status wording, as the Mixxx fork's Fix Tracks dialog words it. Check these in order:

Set Downloader names where a found track's file came from instead of "Found":

| Condition | Status text |
|---|---|
| `status == "found"` and `fix_in_use` | By `fix.source`: "Soulseek" (picked), "YouTube (lossy)", "SoundCloud", "Cut from the mix", "Your file" |
| `status == "found"` and `fix.file` | "Found, but {reason}" (the fix's file is gone; a download stands in) |
| `status == "found"` | "Soulseek" (the set's own download) |
| `status == "missing"` | "Missing: {reason}", plus ` (retries search for "{retry_query}")` when `retry_query` isn't empty |
| `status == "skipped"` | "Not searched (ID)" |

The dialog's default view is "Missing and Fixed Tracks": rows that are `selectable` and either
missing, skipped or have a `fix`. Its other view is "All Tracks". When nothing is missing, it starts
on "All Tracks".

The set's header sums it up by source: "28 Soulseek, 4 YouTube, 2 from the mix, 3 missing"
(SoundCloud counts as YouTube there).

The Mixxx fork's summary line is "{found} of {found+missing} tracks have a file. Pick a track to search Soulseek
with other words and choose the file yourself, or to use a file of your own. This also replaces a
wrong version." When nothing is missing: "All {found} tracks have a file. Pick a track to replace a
wrong version."

| Status | code | When |
|---|---|---|
| 400 / 403 / 404 | | As for `GET /api/sets/{set}` |
| 409 | `not_ready` | The set's first download is still running |
| 500 | `tracks_failed` | tl2mixxx couldn't read the set, e.g. a broken page copy. `message` says why |

---

## Searching Soulseek

### `POST /api/searches`

```json
{"query": "Kettle - Ghosts"}
```

`query` is either `"Artist - Title"` or any words. Whitespace is collapsed to single spaces.

This queues a `search` job in the Soulseek queue and answers `202 {"job": {...}}`. A search waits
behind a running download: one Soulseek login can only be logged in once. Its `result` is the
results:

```json
{
  "query": "Kettle - Ghosts",
  "results": [
    {"user": "alice", "path": "Music\\Kettle - Ghosts\\01 Kettle - Ghosts.flac", "name": "01 Kettle - Ghosts.flac",
     "format": "flac", "size": 31000000, "length": 301, "bitrate": 0, "samplerate": 44100, "bitdepth": 16,
     "free_slot": true, "speed": 2.5, "link": "slsk://alice/Music/Kettle - Ghosts/01 Kettle - Ghosts.flac"},
    {"user": "bob", "path": "Music\\Kettle - Ghosts\\Kettle - Ghosts (Radio Edit).mp3", "name": "Kettle - Ghosts (Radio Edit).mp3",
     "format": "mp3", "size": 9000000, "length": 299, "bitrate": 320, "samplerate": 0, "bitdepth": 0,
     "free_slot": false, "speed": 0.4, "link": "slsk://bob/Music/Kettle - Ghosts/Kettle - Ghosts (Radio Edit).mp3"}
  ]
}
```

Results are audio files only, best first (Soulseek's order).

- `length` is in seconds (0 = unknown) and `size` in bytes.
- `bitrate` is in kbps, for lossy files. `samplerate` (Hz) and `bitdepth` are for lossless files.
  0 means unknown.
- `free_slot: false` means the download may wait in the uploader's queue.
- `link` is what you send to [fix a track](#fixing-a-track).

How the Mixxx fork shows a result:

- Quality: "FLAC 16/44.1" for lossless, "MP3 320 kbps" for lossy.
- Length: green when it is within 5 seconds of the track's `duration` (tooltip "The same length as
  on the tracklist"), orange otherwise ("The tracklist says m:ss: maybe another version").
- Size: "31.0 MB".
- User: the name, plus " (queue)" when there's no free slot.

Its status line is `{n} result(s) for "{query}", best first. Green lengths match the tracklist.`
The job's `message` already says `{n} result(s) for "{query}", best first.`, or "Nothing found for
"{query}". Try fewer or other words, e.g. without the featured artists or the label."

| Status | code | When |
|---|---|---|
| 400 | `bad_query` | Empty, over 300 characters, contains control characters, or starts with `-` (tl2mixxx and sockseek would read it as an option) |
| 409 | `login_required`, `sockseek_missing` | As for downloads |

A search can be stopped like any job. While it waits in the queue its `waiting` is `"soulseek"`:
show "Waiting for the download that's running to finish..."

---

## Fixing a track

### `POST /api/sets/{set}/tracks/{row}/fix`

The body always has the track's `identity` (from its tracks) and one of the following:

| Body | What it does | Soulseek queue? |
|---|---|---|
| `{"identity": "...", "link": "slsk://...", "query": "Kettle - Ghosts"}` | Download a picked search result and use it. Send the `query` of the search that found it (`job.result.query`): it is kept for retries | yes |
| `{"identity": "...", "link": "https://www.youtube.com/watch?v=...", "query": "..."}` | Download a result picked from [Find on YouTube](#find-on-youtube-cut-from-the-set-finish-files) (its `link` and `query`): its audio, in the set's format, tagged, kept as the fix with `source` `"youtube"` or `"soundcloud"`. YouTube and SoundCloud links only | no: the YouTube lane |
| `{"identity": "...", "query": "Saltmarsh Pressure VIP"}` | Search again with other words and download the best match. If nothing is found, the query is kept, so retrying the set searches for it this way; a file the track has (a YouTube or cut stand-in) stays its file | yes |
| `{"identity": "...", "upload": "<upload id>"}` | Use the user's own file (see [Uploads](#uploads-the-users-own-audio-file)). It is copied into the set's folder, and the upload is used up | no |
| `{"identity": "...", "clear": true}` | Undo the fix: back to what the set's search found. The files stay in the folder | no |

The response is `202 {"job": {...}}`, a `fix` job with `set` and `row`.

- Soulseek fixes wait in the Soulseek queue; a picked video waits in the YouTube lane (no login
  needed). Its title ends with ": download the picked video" (or "track", for SoundCloud).
- The others start right away.
- When the settings convert files or write tags, a fix that worked (not an undo, not a picked
  video, which is saved finished) is followed by a `finish` job for that row.
- Either kind waits (`waiting: "set"`) while another job is busy with the same set, such as its
  download.

When the job ends, a `sets` event is sent. Its `result` is like a download's: what the set has now.

`identity` is checked by tl2mixxx. If the set's page was imported again and its rows moved, the
fix is refused, and the job ends as `failed` with a message like `row 5 is now "…", not the track
you chose: the set was imported again since. Choose the track again.` Reload the tracks and let the
user pick again.

Button wording from the Mixxx fork:

- "Download Selected": "Downloads this file into the set's folder and uses it for the track. A file
  that's there already is kept."
- "Use My Own File...": "A file you found yourself: it's copied into the set's folder."
- "Undo Fix": "Goes back to what the set's search found (the files stay in the folder)."

Its hint: "Nothing right? Leave it missing."

| Status | code | When |
|---|---|---|
| 400 | `bad_row` | Row 0, over 100000, or "The set has no row N." |
| 400 | `bad_identity` | Missing `identity` |
| 400 | `bad_fix` | Not exactly one of link/query, upload, clear; or `clear` isn't `true` |
| 400 | `bad_link` | `link` isn't an `slsk://` link, or a YouTube or SoundCloud link |
| 400 | `bad_query` | As for searches |
| 403 / 404 | | As for `GET /api/sets/{set}` |
| 404 | `no_upload` | No such upload (or it was used already) |
| 409 | `login_required`, `sockseek_missing` | Link and query fixes only |

A path that isn't a number (`/tracks/abc/fix`) is a plain `404 not_found`.

---

## Find on YouTube, cut from the set, finish files

### `POST /api/sets/{set}/tracks/{row}/fallback`

```json
{"identity": "kettle|ghosts"}
```

Find on YouTube: `tl2mixxx fallback --track ROW` looks on YouTube Music, YouTube and SoundCloud
(two searches, the most precise first) and scores every result like a likely file. Nothing is
downloaded. It's a `fallback` job with `row` set, in the YouTube lane (no login, beside Soulseek).
Its `result`:

```json
{"version": 1, "folder": "...", "set": "...", "source": "any", "errors": [], "stopped": false,
 "tracks": [{"row": 5, "identity": "kettle|ghosts", "display": "Kettle - Ghosts",
   "queries": [{"query": "Kettle - Ghosts", "results": 8, "failed": false}],
   "candidates": [{"name": "Kettle - Ghosts", "link": "https://www.youtube.com/watch?v=...", "source": "youtube",
     "uploader": "Kettle", "official": true, "length": 301, "format": "opus", "bitrate": 160,
     "quality": "lossy, 160 kbps opus", "thumbnail": "https://i.ytimg.com/...", "score": 0.97,
     "confidence": "high", "reasons": ["title matches", "artist matches", "official upload", "lossy, 160 kbps opus"],
     "substitute": false, "query": "Kettle - Ghosts", "user": "Kettle", "size": 0, "free_slot": true, ...}],
   "taken": null}]}
```

Candidates have a Soulseek result's keys (so the same list shows them) plus `source`, `uploader`,
`official` (YouTube Music songs and "Artist - Topic" channels), `quality` and `thumbnail`.
`confidence` and `reasons` are as for likely matches; "slowed", "reaction", a 15-minute "track" and
so on make it `low`. To use one: [fix](#fixing-a-track) with its `link` and `query`.

The job's `message`: "{n} result(s) on YouTube and SoundCloud, {k} that surely are the track." or
"Nothing found on YouTube or SoundCloud."

| Status | code | When |
|---|---|---|
| 400 | `bad_row`, `bad_identity` | As for fixes; also an ID (no name to look for) |
| 403 / 404 | | As for `GET /api/sets/{set}` |

A row that holds another track now ends the job as `failed` ("not the track you chose").

### `POST /api/sets/{set}/tracks/{row}/cut`

```json
{"identity": "kettle|ghosts"}
```

Cuts the track out of the set's recording, from its time to the next track's (the last one to the
end): `tl2mixxx cut --track ROW`, a `cut` job with `row` set. The file is saved in the set's
format, tagged, and kept as the fix (`source: "mix"`). A recording that's a link is downloaded
once (into tl2mixxx's cache), in the YouTube lane. Its `result`:

```json
{"version": 1, "folder": "...", "set": "...", "recording": {"source": "https://...", "file": "/.../recordings/3f2a.opus", "duration": 3900.0},
 "tracks": [{"row": 5, "identity": "...", "display": "Kettle - Ghosts", "start": 0.0, "end": 271.0,
             "file": "/.../Kettle - Ghosts (from the mix).opus", "skipped": null}],
 "errors": [], "stopped": false}
```

`skipped` says why a track wasn't cut ("no cue time...", "only 3 s until the next track"). The
job's `message`: "Cut {n} track(s) out of the set's recording." Show the button only when the set
has a `recording` and the track a `cue`.

| Status | code | When |
|---|---|---|
| 400 | `bad_row`, `bad_identity` | As for fixes |
| 409 | `no_recording` | The set has no recording |
| 409 | `no_cue` | The tracklist doesn't say when this track plays |

### `POST /api/sets/{set}/finish`

Converts every file of the set to the settings' `format` and, with `tags`, writes their tags
(`tl2mixxx finish --all`): for a set downloaded before the settings changed. A `finish` job; asking
again while one runs answers that one. Its `result`:

```json
{"version": 1, "folder": "...", "set": "...", "format": "aiff", "tags": true, "errors": [], "stopped": false,
 "files": [{"row": 1, "display": "...", "file": "/.../x.aiff", "converted": true, "tagged": true,
            "old_file": "/.../x.flac", "note": "was mp3 (lossy): converting doesn't make it lossless"}]}
```

The job's `message`: "Converted {n} file(s) to AIFF, tagged {k}." or "The files were finished
already." Converting rewrites sockseek's index, the fixes and the playlist, then removes the old
file; a playlist already imported into Mixxx still points at the old names.

| Status | code | When |
|---|---|---|
| 409 | `nothing_to_finish` | `format` is `"keep"` and `tags` is off |

Buy links: the fix panel also links to a Bandcamp search (`https://bandcamp.com/search?q=...&item_type=t`)
and a Beatport search (`https://www.beatport.com/search?q=...`), opened with `POST /api/open-url`.

---

## Uploads (the user's own audio file)

### `POST /api/uploads?name={file name}`

The body is the file's raw bytes. `name` is its name, URL-encoded. Only the name is kept, never a
folder. The extension must be one of: mp3, flac, wav, aiff, aif, m4a, aac, ogg, opus, alac, wma.

```js
const r = await fetch(`/api/uploads?name=${encodeURIComponent(file.name)}`, {method: "POST", headers, body: file})
const {upload} = await r.json()   // then: fix {identity, upload: upload.id}
```

The response is `201 {"upload": {"id": "4be0…", "name": "kettle unreleased.wav", "size": 48211022}}`.

Uploads are used up by a fix. Unused ones are removed after 3 days.

| Status | code | When |
|---|---|---|
| 400 | `bad_name` | No `name` |
| 400 | `empty` | Empty file |
| 400 | `incomplete` | The body was cut short |
| 413 | `too_large` | Over 600 MB |
| 415 | `not_audio` | Not an audio file |

### `DELETE /api/uploads/{id}`

The response is `200 {"ok": true}`, or `404 no_upload`.

---

## yt-dlp

tl2mixxx reads YouTube, SoundCloud and Mixcloud with yt-dlp, used as a library. The app has one
built in; `state.ytdlp` says which is in use:

| Field | Meaning |
|---|---|
| `version` | The version tl2mixxx imports, or `null` (not installed, or still being read) |
| `source` | `"updated"` (downloaded with Update yt-dlp), `"bundled"` (built in), or `null` (none) |
| `bundled` | The built-in one's version |
| `updated` | When the update in use was downloaded |
| `updating`, `step` | An update is running, and what it's doing ("Downloading yt-dlp 2026.11.02") |
| `message`, `error` | How the last update ended: "Updated to yt-dlp 2026.11.02.", "Already up to date: ...", or why it failed |

### `POST /api/ytdlp/update`

Starts updating in the background and answers `202 {"ytdlp": {...}}` at once (`updating: true`).
A `state` event comes as it goes and when it ends. It:

1. asks GitHub for yt-dlp's latest release (`api.github.com/repos/yt-dlp/yt-dlp/releases/latest`);
2. stops there if that's the version in use;
3. downloads the release's `yt-dlp` file (the library as a zip, which also runs as a program) and
   its `SHA2-256SUMS`, over HTTPS from GitHub only (redirects checked), at most 40 MB;
4. checks the checksum and that it is the library;
5. has a child process import it and report its version;
6. keeps it in `<data dir>/yt-dlp/` and removes older ones.

From then on every tl2mixxx process imports it before the built-in copy. Asking while an update
runs changes nothing.

### `DELETE /api/ytdlp/update`

Forgets the update: the built-in yt-dlp is used again. `200 {"ytdlp": {...}}`, or
`409 ytdlp_updating` while an update runs.

---

## Jobs

Downloads, searches, fixes and the rest are jobs. Each one is a tl2mixxx process (or one of the
app's helpers); its output is the job's log.

Jobs run in lanes:

- **Soulseek** (`download`, `search`, `suggest`, and fixes with an `slsk://` link or a query): **one
  at a time**, in the order they were asked for: one Soulseek login can only be logged in once.
- **YouTube** (`fallback`, `cut`, a fix with a picked video): one at a time among themselves,
  beside the Soulseek lane. No login.
- The rest (`resolve`, `finish`, fixes with an upload or undo) start right away.

No two jobs change the same set's files at once. A queued job waiting for its set (`waiting:
"set"`) doesn't hold up its lane: the jobs behind it for other sets start first.

### The job object

```json
{
  "id": "a1b2c3d4e5f6",
  "kind": "download",
  "title": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
  "set": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
  "row": null,
  "state": "done",
  "waiting": null,
  "ahead": null,
  "created": "2026-10-31T20:14:58+01:00",
  "started": "2026-10-31T20:14:58+01:00",
  "finished": "2026-10-31T20:15:04+01:00",
  "exit_code": 0,
  "message": "6 of 7 tracks have a file.",
  "error": "",
  "result": {
    "set": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
    "title": "DJ Example @ Warehouse Project, Manchester 2026-10-01",
    "found": 6, "missing": 1, "total": 7,
    "cancelled": false,
    "errors": [],
    "missing_tracks": [{"number": "", "artist": "Saltmarsh", "title": "Pressure", "reason": "no search results"}]
  },
  "log_lines": 26
}
```

| Field | Meaning |
|---|---|
| `kind` | `"download"`, `"search"`, `"fix"`, `"suggest"`, `"resolve"` (reading a link), `"fallback"` (YouTube), `"cut"` (from the recording) or `"finish"` (converting and tagging) |
| `title` | What to show. A download and the steps after it: the set's name. A search: `Search: "query"`. A fix: `Kettle - Ghosts: download the picked file` / `download the picked video` / `search again for "..."` / `use x.wav` / `undo the fix`. A link: `Reading the YouTube video`. A track's: `Kettle - Ghosts: find on YouTube` / `cut from the set` / `finish` |
| `set` | The set it works on (`null` for searches and links) |
| `row` | The track's row, for a fix and a track's fallback, cut or finish (else `null`: the set's download and its steps) |
| `lane` | `"soulseek"`, `"youtube"` or `null` (started right away) |
| `state` | `queued` → `running` → `done` / `failed` / `stopped`. In between there may be `stopping` (Stop was pressed; tl2mixxx is wrapping up) |
| `waiting` | While `queued`: `"soulseek"` or `"youtube"` (behind another job of its lane) or `"set"` (another job is busy with this set) |
| `ahead` | While waiting in its lane: how many jobs of the lane run before it, the running one included. Otherwise `null` |
| `progress` | While it runs, when tl2mixxx says how far it is: `{"fraction": 0.42, "text": "downloading Kettle - Ghosts"}` (from its `PROGRESS` lines, which aren't in the log). Otherwise `null` |
| `exit_code` | tl2mixxx's exit code: 0 = fine, 130 = stopped, 1 = errors, negative = killed by a signal |
| `message` | A one-line summary to show when it ends (see below) |
| `error` | The last error tl2mixxx reported (`"ERROR kind: text"` lines), or `""` |
| `result` | Set when it ends, if there is one (see below) |
| `log_lines` | How many log lines so far |

`result` for downloads and fixes (or `null` if tl2mixxx gave none):

| Field | Meaning |
|---|---|
| `set`, `title` | The set |
| `found`, `missing`, `total` | What the set has now |
| `cancelled` | The job was stopped |
| `errors` | Error texts, e.g. a fix refused because the rows moved |
| `missing_tracks` | `{number, artist, title, reason}` for each track without a file (`number` is `""` for a mashup's parts) |

`result` for searches is `{"query": "...", "results": [...]}` (see [Searching Soulseek](#searching-soulseek)),
or `null` if the search failed or was stopped. For `resolve`, see
[Paste anything](#post-apidraftsresolve); for `fallback`, `cut` and `finish`, see
[Find on YouTube, cut, finish](#find-on-youtube-cut-from-the-set-finish-files) (a set's
`fallback --missing --auto` result is the same shape, with `taken` set for each track downloaded).

`message` examples:

- "6 of 7 tracks have a file."
- "All 7 tracks have a file."
- "Stopped. What had finished downloading is kept. 3 of 7 tracks have a file."
- "Error: Kettle - Ghosts: couldn't download "x" (no search results)"
- "Stopped before it started."
- "The search failed: …"
- "tl2mixxx exited with code 1 and no result: <error>"

### `GET /api/jobs`

`200 {"jobs": [job, ...]}`, newest first, without logs. Active jobs are listed, and the last 100
finished ones.

### `GET /api/jobs/{id}`

`200` with the job plus `"log": ["line", ...]` (its last 5000 lines). The first line is the command,
e.g. `$ tl2mixxx run /…/tracklist.html --no-mixxx --music-dir=… -- --no-progress -c /…/sockseek.conf`
(never a password). Use this to fill a log view; the [event stream](#live-events-server-sent-events)
then adds new lines. Answers `404 no_job` if there is no such job.

### `POST /api/jobs/{id}/stop`

- **Queued**: it leaves the queue at once and becomes `stopped` ("Stopped before it started.").
- **Running**: it becomes `stopping`. tl2mixxx's standard input is closed, which asks it to stop
  sockseek and keep what finished. It then becomes `stopped`, with a result for what finished. If it
  hasn't stopped after 3 seconds, its whole process group gets SIGTERM, and after 10 more, SIGKILL.
- **Finished**: nothing changes.

The response is `200 {"job": {...}}`, or `404 no_job`.

Wording from the Mixxx fork, while stopping: "Stopping... (what has finished downloading is still
imported)".

---

## Live events (Server-Sent Events)

### `GET /api/events`

This is a `text/event-stream` with every change, as it happens. Optional query parameters:

- `job={id}`: only that job's `job` and `log` events.
- `after={event id}`: replay what came after that event. The `Last-Event-ID` header works the same.

`EventSource` can't send the token header, so read the stream with `fetch`:

```js
async function listen(token, onEvent, signal) {
  let lastId = null
  for (;;) {
    try {
      const headers = {"X-SetDL-Token": token}
      if (lastId) headers["Last-Event-ID"] = lastId
      const res = await fetch("/api/events", {headers, signal})
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buf = ""
      for (;;) {
        const {value, done} = await reader.read()
        if (done) break
        buf += value
        let i
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2)
          const ev = {}
          for (const line of block.split("\n")) {
            if (line.startsWith(":")) continue            // keep-alive
            const j = line.indexOf(": ")
            if (j > 0) ev[line.slice(0, j)] = line.slice(j + 2)
          }
          if (ev.id) lastId = ev.id
          if (ev.event) onEvent(ev.event, JSON.parse(ev.data || "{}"))
        }
      }
    } catch (e) { if (signal?.aborted) return }
    await new Promise(r => setTimeout(r, 2000))           // reconnect; Last-Event-ID replays what was missed
  }
}
```

Event types:

| event | data | When |
|---|---|---|
| `hello` | `{}` | Right after connecting (no `id`) |
| `job` | a job object (no log) | A job is queued, starts, starts waiting, moves up the queue, is stopping, or ends |
| `log` | `{"job": "<id>", "n": 12, "line": "..."}` | A line of a job's output. `n` counts from 1 per job; the first line is the command |
| `sets` | `{"set": "<set id>", "reason": "download"}` (or `"fix"`, `"suggest"`, `"fallback"`, `"cut"`, `"finish"`) | A job that changes that set's files ended. Refresh `GET /api/sets`, and the set's tracks if it is open |
| `state` | the state object (as `GET /api/state`) | Settings, the login or yt-dlp's status changed |

Every event except `hello` has an increasing `id`. The server keeps the last 2000 events for
replay. A `: ping` comment comes every 15 seconds, and `retry: 2000` asks for reconnects after 2
seconds.

Log lines have ANSI colours removed. A line redrawn in place keeps its last version.

---

## Show in Finder, open a link

### `POST /api/reveal`

Runs `open -R` (reveal in the Finder). Send one of:

- `{"set": "<set id>"}`: the set's folder.
- `{"path": "/full/path/to/a/file"}`: a file or folder inside the music folder, e.g. a track's
  `file`.
- `{}`: the music folder itself.

The response is `200 {"ok": true, "path": "<what was shown>"}`.

| Status | code | When |
|---|---|---|
| 400 | `bad_path` | `path` isn't a full path |
| 403 | `outside_music_dir` | The path is outside the music folder |
| 404 | `no_file` | The file isn't there anymore |
| 404 | `no_music_dir` | The music folder doesn't exist yet |
| 400 / 403 / 404 | | For `set`, as for `GET /api/sets/{set}` |

### `POST /api/open-url`

```json
{"url": "https://www.1001tracklists.com/tracklist/abc123/x.html"}
```

Opens the address in the user's browser, e.g. a set's `url`. Only `http://` and `https://`
addresses are accepted. The response is `200 {"ok": true}`, or `400 bad_url`.

---

## Typical flows

**Start-up**

1. `GET /api/state`.
2. If `login.source == "none"`, ask for a Soulseek login (`PUT /api/login`).
3. If `sockseek.found` is `false`, show `sockseek.error` and a field for its path
   (`PUT /api/settings`).
4. `GET /api/sets`, `GET /api/jobs`.
5. Open the event stream.

**Add a set**

1. The user drops a file, or pastes text.
2. Check its size against `limits`, then `POST /api/drafts/page?name=…` (or `/api/drafts/text`).
3. Show the draft: title, tracks, and for `has_mashups`, the three choices with `counts`.
4. If `set_exists`, say it was downloaded before and only what's missing is searched for.
5. Start: `POST /api/downloads {draft, mashups}`.
6. Follow the job with `job`/`log` events. The set appears in the list right away (`pending`).
7. When it ends, a `sets` event arrives: refresh the list.

Prevent the browser's own drop handling, or WKWebView opens the file:
`window.addEventListener("dragover", e => e.preventDefault())`, and the same for `drop`.

**Fix tracks**

1. Open a set: `GET /api/sets/{set}/tracks`.
2. Pick a row. Fill "Search Soulseek for" with `fix.query`, else `search` (empty for an ID).
3. Search: `POST /api/searches {query}`, then wait for the job's `done` event; `result.results`
   has the results. If the user picks another track meanwhile, stop that search.
4. Download Selected: `POST …/tracks/{row}/fix {identity, link, query: <that search's query>}`.
5. Use My Own File: `POST /api/uploads?name=…`, then `fix {identity, upload}`.
6. Undo Fix: `fix {identity, clear: true}`.
7. When the fix job ends (`job` event with `state` done/failed, plus a `sets` event), reload the
   tracks and show the job's `message`.

**Paste anything**

1. `POST /api/drafts/resolve {input}`. A `201` has the draft; a `202` has a `resolve` job.
2. Follow the job (`job` events). Show what's being read and a Stop button.
3. `done`: `GET /api/drafts/{result.draft}`. `failed`: show `message`, and `result.help` for
   Spotify with an Exportify button.
4. Show the draft with where it came from (`kind`, `from`, `origin`) and, when there are
   `alternatives`, a switcher: `POST /api/drafts/{id}/pick {pick}`.

**Retry missing**

`POST /api/downloads {set}`: Soulseek (if on), then YouTube, the recording and finishing, as the
settings say.

**A track from YouTube**

1. `POST /api/sets/{set}/tracks/{row}/fallback {identity}`, wait for the job.
2. Show `result.tracks[0].candidates` with their confidence and reasons.
3. Download selected: `POST .../tracks/{row}/fix {identity, link, query}` with the candidate's.

---

## Developing the UI

Run the backend in dev mode against scratch folders with the fake sockseek (with YouTube on in
the settings, a download then looks on the real YouTube for what's missing: turn it off, or see
below):

```sh
cd /Users/evanegan/Downloads/set-downloader
SETDL_MIXXX_LOGIN=/nonexistent \
  .venv/bin/set-downloader --browser --port 8765 \
    --data-dir /tmp/setdl-dev/data --music-dir /tmp/setdl-dev/music \
    --sockseek "$PWD/tests/fake_sockseek.py" \
    --dev-origin http://localhost:5173
```

It prints the address with the token, plus a `dev server:` address for the Vite origin. Then enter
any login in the UI. The fake sockseek "downloads" every track instantly as a tiny file, searches
return two results, and `slsk://` links download.

| Variable | Effect on the fake sockseek |
|---|---|
| `FAKE_SOCKSEEK_MISSING="Pressure"` | That title is not found, and searches with that word find nothing |
| `FAKE_SOCKSEEK_HANG=/tmp/x.pid` | Downloads hang after the first track, to try Stop and the queue |

Proxy `/api` from Vite with Host rewriting. Streaming works through the proxy:

```js
// vite.config.js
export default {server: {proxy: {"/api": {target: "http://127.0.0.1:8765", changeOrigin: true}}}}
```

Open the printed `http://localhost:5173/#token=…` address. `--dev-origin` lets the server accept
that origin. Without it, the server only accepts its own.

To work on the YouTube and recording parts without the network, run the app with
`tests/fake_tl2mixxx.py` as tl2mixxx: it fakes yt-dlp's searches and downloads (ffmpeg sine tones),
reading a video (`tests/fixtures/ytdlp_video.json`) and Spotify, and writes no covers:

```python
# dev.py: python dev.py /tmp/setdl-dev
import os, sys
from setdl.core import App
from setdl.server import Server
os.environ |= {"SETDL_MIXXX_LOGIN": "/nonexistent", "TL2MIXXX_CACHE_DIR": f"{sys.argv[1]}/cache"}
fake = ["/path/to/set-downloader/.venv/bin/python", "/path/to/set-downloader/tests/fake_tl2mixxx.py"]
app = App(f"{sys.argv[1]}/data", music_dir=f"{sys.argv[1]}/music", sockseek="/path/to/fake/sockseek",
          command=fake, helper_command=fake + ["--helper"])
server = Server(app, port=8765, token="dev")
print(server.page_url())
server.serve_forever()
```

| Variable | Effect on the fake tl2mixxx |
|---|---|
| `FAKE_YTDL_MISSING="Baby"` | Searches with that word find nothing on YouTube |
| `FAKE_YTDL_FAIL=1` | Downloads from YouTube fail |
| `FAKE_YTDL_DELAY=3`, `FAKE_EXTRACT_DELAY=3` | Each download / reading a link takes that many seconds |
| `FAKE_SPOTIFY_FAIL=1` | Spotify links can't be read (also any link with "unreadable" in it) |

`npm run build` into `web/dist`. The server serves it at `/`: any path without a file extension
gets `index.html`, so client-side routes work. Until `web/dist/index.html` exists, a placeholder
page is shown.
