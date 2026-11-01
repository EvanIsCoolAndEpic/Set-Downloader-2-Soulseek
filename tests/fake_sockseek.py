#!/usr/bin/env python3
"""Stand-in for the sockseek CLI used by the end-to-end tests.

Understands just what tl2mixxx passes: <csv> --input-type csv -o DIR --index-path FILE
[--name-format FMT] [...]. "Downloads" every row whose title isn't listed in the
FAKE_SOCKSEEK_MISSING env var (separated by '|'), and writes an index in sockseek's
real format. Rows already marked done in an existing index are left alone, like sockseek.

FAKE_SOCKSEEK_HANG=PIDFILE: "download" the first row, write our pid to PIDFILE, then hang
until killed (for testing cancellation).

Also, like sockseek, a search string with --print json-all prints made-up results (one
.mp3, one .flac and a cover image for each query; none when the query has a word listed in
FAKE_SOCKSEEK_MISSING), and a slsk://user/path input downloads that file into -o.
"""
import json
import csv
import os
import sys
import time
from pathlib import Path


def fake_results(query, missing):
    """Made-up results for a search: none when the query has a word listed in missing."""
    if any(word in query for word in missing):
        return []
    folder = f"Music\\{query}"
    return [
        {"User": {"Username": "alice", "UploadSpeed": 2.5, "HasFreeUploadSlot": True},
         "File": {"Length": 301, "Filename": f"{folder}\\01 {query}.flac", "Size": 31000000,
                  "SampleRate": 44100, "BitDepth": 16}},
        {"User": {"Username": "bob", "UploadSpeed": 0.4, "HasFreeUploadSlot": False},
         "File": {"Length": 299, "Filename": f"{folder}\\{query} (Radio Edit).mp3", "Size": 9000000,
                  "Bitrate": 320}},
        {"User": {"Username": "bob", "UploadSpeed": 0.4, "HasFreeUploadSlot": False},
         "File": {"Filename": f"{folder}\\cover.jpg", "Size": 50000}},
    ]


def main(argv):
    opts = {}
    i = 1
    while i < len(argv):
        if argv[i] in ("-o", "--index-path", "--input-type", "--name-format", "--print", "-c"):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            i += 1
    missing = set(filter(None, os.environ.get("FAKE_SOCKSEEK_MISSING", "").split("|")))
    with open(os.environ.get("FAKE_SOCKSEEK_LOG", os.devnull), "a") as log:
        log.write(" ".join(argv) + "\n")
    if os.environ.get("FAKE_SOCKSEEK_LOGIN_REFUSED"):
        # Like Soulseek refusing the login: sockseek says so and tries again, for ever
        while True:
            print("[error] [soulseek] Failed to ensure Soulseek connection and login: System.TimeoutException",
                  file=sys.stderr, flush=True)
            time.sleep(0.2)

    if opts.get("--print") == "json-all" and opts.get("--input-type") == "csv":
        # Several searches in one run (a CSV of titles): one line of results each, in order
        for row in csv.DictReader(Path(argv[0]).open(encoding="utf-8")):
            print(json.dumps(fake_results(row["Title"], missing)))
        return 0
    if opts.get("--print") == "json-all":
        print(json.dumps(fake_results(argv[0], missing)))
        return 0
    out = Path(opts["-o"])
    index = Path(opts["--index-path"])
    out.mkdir(parents=True, exist_ok=True)
    header = "filepath,artist,album,title,length,tracktype,state,failurereason"

    if argv[0].startswith("slsk://"):
        name = argv[0].rsplit("/", 1)[-1]
        if any(word in name for word in missing):
            index.write_text(f'{header}\n,,,"{name}",-1,0,2,4\n', encoding="utf-8")
            return 0
        (out / name).write_bytes(b"ID3picked")
        index.write_text(f'{header}\n"./{name}",,,"{name}",-1,0,1,0\n', encoding="utf-8")
        return 0

    csv_path = Path(argv[0])

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    lines = [header]

    def q(s):
        return f'"{s.replace(chr(34), chr(34) * 2)}"' if ("," in s or '"' in s) else s

    for r in rows:
        name = f"{r['Artist']} - {r['Title']}.mp3" if r["Artist"] else f"{r['Title']}.mp3"
        target = out / name.replace("/", "_")
        if r["Title"] in missing:
            lines.append(",".join([ "", q(r["Artist"]), "", q(r["Title"]), r.get("Length") or "-1", "0", "2", "9"]))
            continue
        state = "3" if target.exists() else "1"
        target.write_bytes(b"ID3fake")
        lines.append(",".join([q("./" + target.name), q(r["Artist"]), "", q(r["Title"]),
                               r.get("Length") or "-1", "0", state, "0"]))
        if os.environ.get("FAKE_SOCKSEEK_HANG"):
            # sockseek updates its index as it goes, so a cancelled run keeps what finished.
            index.write_text("\n".join(lines) + "\n", encoding="utf-8")
            Path(os.environ["FAKE_SOCKSEEK_HANG"]).write_text(str(os.getpid()))
            print("fake sockseek: hanging", flush=True)
            while True:
                time.sleep(1)
    index.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
    print(f"fake sockseek: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
