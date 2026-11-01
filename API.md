# Set Downloader API

The window (pywebview) shows the built UI from `web/dist`, served by a small Python HTTP server on
`127.0.0.1` at a free port. The UI talks to that server through the JSON API below. tl2mixxx and
sockseek do the work: every download, search and fix is a tl2mixxx process that the server runs
and streams to the page.

Everything here is relative to the page's own origin (`/api/...`), so the UI never needs to know
the port.

## Contents

- [The basics](#the-basics): token, errors, limits, live events, CSP
- [Endpoints at a glance](#endpoints-at-a-glance)
- [State and settings](#state-and-settings)
- [Soulseek login](#soulseek-login)
- [Drafts: a dropped page or pasted text](#drafts-a-dropped-page-or-pasted-text)
- [Downloads](#downloads)
- [Sets](#sets)
- [Searching Soulseek](#searching-soulseek)
- [Fixing a track](#fixing-a-track)
- [Uploads](#uploads-the-users-own-audio-file)
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
| A dropped page (`POST /api/drafts/page`) | 20 MB (`limits.page_bytes`) |
| Pasted text, as JSON (`POST /api/drafts/text`) | 2 MB (`limits.text_bytes`) |
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

Track names come from web pages and from Soulseek, so treat them as untrusted text and render them
as text (React does this by default).

---

## Endpoints at a glance

| Method | Path | What it does |
|---|---|---|
| GET | `/api/state` | App state: settings, login, sockseek, music folder, job counts, limits |
| PUT | `/api/settings` | Change settings |
| PUT | `/api/login` | Save the Soulseek login |
| DELETE | `/api/login` | Forget the app's Soulseek login |
| POST | `/api/drafts/page?name=…` | A dropped page or `.txt` file (raw body) → draft |
| POST | `/api/drafts/text` | Pasted text → draft |
| GET | `/api/drafts/{id}` | A draft, recomputed |
| DELETE | `/api/drafts/{id}` | Throw a draft away |
| POST | `/api/downloads` | Download a draft's set, or retry a set |
| GET | `/api/sets` | Every set in the music folder |
| GET | `/api/sets/{set}` | One set |
| GET | `/api/sets/{set}/tracks` | A set's tracks, with the file each one has |
| POST | `/api/sets/{set}/tracks/{row}/fix` | Fix one track |
| POST | `/api/searches` | Search Soulseek (a queued job) |
| POST | `/api/uploads?name=…` | Upload an audio file of the user's own (raw body) |
| DELETE | `/api/uploads/{id}` | Throw an upload away |
| GET | `/api/jobs` | All jobs, newest first |
| GET | `/api/jobs/{id}` | One job, with its log |
| POST | `/api/jobs/{id}/stop` | Stop a job, or take it out of the queue |
| GET | `/api/events` | Live events (Server-Sent Events) |
| POST | `/api/reveal` | Show a set or file in the Finder |
| POST | `/api/open-url` | Open a web address in the browser |

`{set}` is a set's id, its folder name, URL-encoded (`encodeURIComponent`). `{id}` values are
generated by the server.

---

## State and settings

### `GET /api/state`

```json
{
  "app": {"name": "Set Downloader", "version": "0.1.0"},
  "settings": {"music_dir": "/Users/you/Music/1001Tracklists", "sockseek": "", "mashups": "components"},
  "music_dir": {"path": "/Users/you/Music/1001Tracklists", "exists": true},
  "login": {"source": "mixxx", "username": null, "path": "/Users/you/Library/Application Support/Mixxx/1001tracklists-sockseek.conf"},
  "sockseek": {"path": "/opt/homebrew/bin/sockseek", "source": "automatic", "setting": "", "found": true, "error": null},
  "jobs": {"running": 1, "queued": 0},
  "limits": {"page_bytes": 20971520, "text_bytes": 2097152, "upload_bytes": 629145600, "query_chars": 300}
}
```

- `settings`: what is saved.
  - `music_dir`: each set gets a folder in here. The default is `~/Music/1001Tracklists`, the same
    folder the Mixxx fork and tl2mixxx use, so sets already downloaded there show up.
  - `sockseek`: `""` means find it automatically.
  - `mashups`: the default for new sets (see [Mashups](#mashups)).
- `music_dir.exists`: `false` until the first download creates the folder.
- `login`: see [Soulseek login](#soulseek-login).
- `sockseek`: the program that is used.
  - `source` is `"setting"` (the path in the settings), `"automatic"` (`$SOCKSEEK` or `PATH`),
    `"bundled"` (the copy inside the app), or `null` when none was found.
  - When `found` is `false`, `error` says why (for example, the path in the settings doesn't exist).
    Downloads and searches then fail with `409 sockseek_missing`.
- `jobs`: how many jobs are running (including stopping) and how many are queued.

### `PUT /api/settings`

Send any subset of the settings:

```json
{"music_dir": "/Volumes/Music/Sets", "sockseek": "", "mashups": "both"}
```

- `music_dir`: a full path. `~/…` is expanded. It doesn't have to exist yet, but it can't be a file
  or `/`.
- `sockseek`: a full path to an executable file, or `""` to find it automatically.
- `mashups`: `"components"`, `"original"` or `"both"`.

The response is `200` with the whole state, as `GET /api/state` returns it. A `state` event is sent
too. Jobs that are already queued or running keep the settings they started with.

| Status | code | When |
|---|---|---|
| 400 | `bad_music_dir` | Not a full path, `/`, an existing file, or has control characters |
| 400 | `bad_sockseek` | Not a full path, or no executable file there |
| 400 | `bad_mashups` | Not one of the three choices |
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

## Drafts: a dropped page or pasted text

A draft is a parsed tracklist that hasn't been downloaded yet. The UI shows it, the user picks the
mashups choice, and then starts the download. Drafts live in the app's scratch folder and are
removed after 3 days.

### `POST /api/drafts/page?name={file name}`

The body is the dropped file's raw bytes: a page saved from 1001Tracklists (`.html`, `.htm`, any
encoding), or a tracklist saved as `.txt`. `name` is the file's name, URL-encoded. A name ending in
`.txt` is read as text; anything else is read as a page.

```js
await fetch(`/api/drafts/page?name=${encodeURIComponent(file.name)}`, {method: "POST", headers, body: file})
```

The response is `201` with a [draft](#the-draft-object).

| Status | code | When |
|---|---|---|
| 400 | `empty` | The file is empty |
| 413 | `too_large` | Over 20 MB |
| 422 | `not_a_tracklist` | No tracks found. `message` explains how to save the page properly |

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
| `source` | `"page"` (a saved page) or `"text"` (pasted, or a `.txt` file) |
| `title` | The set's name |
| `url` | The page's 1001Tracklists address, or `""` |
| `set` | The id the set will have (its folder name in the music folder) |
| `set_exists` | The set was downloaded before. Downloading again keeps what is there and only searches for what's missing |
| `mashups` | The suggested choice: the set's own choice if it exists, else the setting |
| `has_mashups` | Show the mashups choice only when this is `true` |
| `unidentified` | How many rows are IDs |
| `counts` | How many tracks get a file under each choice. A track played twice counts twice, but is downloaded once |
| `tracks` | Every row of the page, in order |

Each track has:

| Field | Meaning |
|---|---|
| `row` | Its row on the page (1-based, counting every row) |
| `number` | What the page shows: `"01"`, `"w/"`, or `""` for a mashup's parts |
| `kind` | `"track"`, `"with"` (a `w/` row), `"mashup"`, or `"component"` (a part of the mashup at row `mashup_of`) |
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

This queues a `download` [job](#the-job-object) in the Soulseek queue.

- `202 {"job": {...}, "already_queued": false}` when a new job was queued.
- `200 {"job": {...}, "already_queued": true}` when this set already has a queued or running
  download. The response is that job, and nothing new is queued.

While a new set's first download is queued or running, it is already listed in `GET /api/sets`
with `"pending": true`.

A download writes this into `<music dir>/<set>/`:

- the tracks,
- `<set>.m3u8`, a playlist in set order,
- `_missing.csv`,
- sockseek's `_index.csv`,
- a copy of the page (`_tracklist.html` or `_tracklist.txt`).

| Status | code | When |
|---|---|---|
| 400 | `bad_download` | Neither or both of `draft` and `set` |
| 400 | `bad_mashups` | Not one of the three choices |
| 400 | `bad_set_id` | Not a folder name |
| 403 | `outside_music_dir` | The set's folder isn't inside the music folder (a link to elsewhere) |
| 404 | `no_draft` | No such draft |
| 404 | `not_found` | No such set |
| 409 | `login_required` | No Soulseek login |
| 409 | `sockseek_missing` | sockseek wasn't found |
| 422 | `not_a_tracklist` | The draft can't be parsed anymore |

Wording from the Mixxx fork: "Retrying only searches for what's still missing, then rebuilds the
playlist in set order. Downloads that finish later on Soulseek can be picked up just by retrying."

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
| `fix` | `null`, or what the user fixed: `query` (another search), `file`, `source` (`"soulseek"` or `"own"`), `link`, `updated`. Only the keys that have a value are present |
| `fix_in_use` | The file in use is the one the fix gave it |
| `retry_query` | What a retry searches for instead of `search` (`""` = its own search) |

Status wording, as the Mixxx fork's Fix Tracks dialog words it. Check these in order:

| Condition | Status text |
|---|---|
| `status == "found"` and `fix_in_use` | "Your file" (`fix.source == "own"`) or "Picked on Soulseek" |
| `status == "found"` and `fix.file` | "Found, but {reason}" (the fix's file is gone; a download stands in) |
| `status == "found"` | "Found" |
| `status == "missing"` | "Missing: {reason}", plus ` (retries search for "{retry_query}")` when `retry_query` isn't empty |
| `status == "skipped"` | "Not searched (ID)" |

The dialog's default view is "Missing and Fixed Tracks": rows that are `selectable` and either
missing, skipped or have a `fix`. Its other view is "All Tracks". When nothing is missing, it starts
on "All Tracks".

Its summary line is "{found} of {found+missing} tracks have a file. Pick a track to search Soulseek
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
| `{"identity": "...", "query": "Saltmarsh Pressure VIP"}` | Search again with other words and download the best match. If nothing is found, the query is kept, so retrying the set searches for it this way | yes |
| `{"identity": "...", "upload": "<upload id>"}` | Use the user's own file (see [Uploads](#uploads-the-users-own-audio-file)). It is copied into the set's folder, and the upload is used up | no |
| `{"identity": "...", "clear": true}` | Undo the fix: back to what the set's search found. The files stay in the folder | no |

The response is `202 {"job": {...}}`, a `fix` job with `set` and `row`.

- Soulseek fixes wait in the Soulseek queue.
- The others start right away.
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
| 400 | `bad_link` | `link` isn't an `slsk://` link |
| 400 | `bad_query` | As for searches |
| 403 / 404 | | As for `GET /api/sets/{set}` |
| 404 | `no_upload` | No such upload (or it was used already) |
| 409 | `login_required`, `sockseek_missing` | Link and query fixes only |

A path that isn't a number (`/tracks/abc/fix`) is a plain `404 not_found`.

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

## Jobs

Downloads, searches and fixes are jobs. Each one is a tl2mixxx process; its output is the job's log.

Soulseek jobs (`download`, `search`, and fixes with `link`/`query`) run **one at a time**, in the
order they were asked for: one Soulseek login can only be logged in once. Other fixes start right
away. No two jobs work on the same set at once.

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
| `kind` | `"download"`, `"search"` or `"fix"` |
| `title` | What to show. A download: the set's name. A search: `Search: "query"`. A fix: `Kettle - Ghosts: download the picked file` / `search again for "..."` / `use x.wav` / `undo the fix` |
| `set` | The set it works on (`null` for searches) |
| `row` | A fix's track row (else `null`) |
| `state` | `queued` → `running` → `done` / `failed` / `stopped`. In between there may be `stopping` (Stop was pressed; tl2mixxx is wrapping up) |
| `waiting` | While `queued`: `"soulseek"` (behind another Soulseek job) or `"set"` (another job is busy with this set) |
| `ahead` | While waiting in the Soulseek queue: how many Soulseek jobs run before it, the running one included. Otherwise `null` |
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
or `null` if the search failed or was stopped.

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
| `sets` | `{"set": "<set id>", "reason": "download"}` (or `"fix"`) | A download or fix of that set ended: its files changed. Refresh `GET /api/sets`, and the set's tracks if it is open |
| `state` | the state object (as `GET /api/state`) | Settings or the login changed |

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

**Retry missing**

`POST /api/downloads {set}`.

---

## Developing the UI

Run the backend in dev mode against scratch folders with the fake sockseek:

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

`npm run build` into `web/dist`. The server serves it at `/`: any path without a file extension
gets `index.html`, so client-side routes work. Until `web/dist/index.html` exists, a placeholder
page is shown.
