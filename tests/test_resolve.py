"""Paste anything: links read by "resolve" jobs, dropped CSVs, JSON, pictures and pages, and the
alternatives a video's comments give."""

import json
import shutil
import subprocess
import sys
from urllib.parse import quote

import pytest

from conftest import VIDEO, VIDEO_SET

pytestmark = pytest.mark.media

EXPORTIFY = (
    "Track URI,Track Name,Artist URI(s),Artist Name(s),Album URI,Album Name,Album Artist URI(s),"
    "Album Artist Name(s),Album Release Date,Album Image URL,Disc Number,Track Number,Track Duration (ms),"
    "Track Preview URL,Explicit,Popularity,ISRC,Added By,Added At,Genres,Label\n"
    "spotify:track:1aaa,Ghosts,spotify:artist:k1,Kettle,spotify:album:a1,Ghosts EP,spotify:artist:k1,Kettle,"
    "2026-03-01,,1,1,301234,,false,40,GBXYZ2600001,,,,SPEEDBUMP\n"
    "spotify:track:2bbb,Pressure,spotify:artist:s1,Saltmarsh,spotify:album:a2,Pressure,spotify:artist:s1,"
    "Saltmarsh,2025,,1,2,372000,,false,30,GBABC2500002,,,,\n")


def drop(client, name, data):
    # A picture's first reading can take a while (Vision loads its models)
    return client.call("POST", "/api/drafts/page?name=" + quote(name), data, timeout=150)


def test_a_youtube_link_is_read_by_a_job(client):
    status, data = client.post("/api/drafts/resolve", {"input": f"  {VIDEO}  "})
    assert status == 202
    job = client.wait_job(data["job"]["id"])
    assert job["kind"] == "resolve" and job["title"] == "Reading the YouTube video" and job["lane"] is None
    assert job["state"] == "done" and job["message"] == "Found 5 tracks."
    assert job["result"]["kind"] == "youtube" and job["result"]["count"] == 5
    draft = client.ok("GET", f"/api/drafts/{job['result']['draft']}")
    assert draft["source"] == "resolved" and draft["kind"] == "youtube" and draft["title"] == "Kettle | Rooftop Session"
    assert draft["origin"] == {"kind": "youtube", "name": "", "url": VIDEO}
    assert draft["recording"] == VIDEO and draft["cues"] == 5 and draft["set"] == VIDEO_SET
    assert draft["from"] == {"source": "comment", "label": "comment by @trainspotter (820 likes, pinned)"}
    assert [a["count"] for a in draft["alternatives"]] == [5, 3] and draft["picked"] == 0
    assert "tracks" not in draft["alternatives"][0]
    assert [t["cue"] for t in draft["tracks"]] == [0, 20, 40, 60, 80]
    assert draft["counts"]["components"] == 4      # the ID isn't downloaded


def test_picking_another_tracklist(client):
    draft = client.resolve(VIDEO)
    other = client.ok("POST", f"/api/drafts/{draft['id']}/pick", {"pick": 1})
    assert other["picked"] == 1 and len(other["tracks"]) == 3 and other["title"] == draft["title"]
    assert other["from"]["label"].startswith("comment by @quick")
    assert client.ok("GET", f"/api/drafts/{draft['id']}")["picked"] == 1
    status, data = client.post(f"/api/drafts/{draft['id']}/pick", {"pick": 7})
    assert status == 422 and "0 to 1" in data["error"]["message"]
    assert client.post(f"/api/drafts/{draft['id']}/pick", {"pick": "1"})[0] == 400
    text = client.resolve("01. Kettle - Ghosts\n02. A - B\n")
    assert client.post(f"/api/drafts/{text['id']}/pick", {"pick": 1})[1]["error"]["code"] == "no_alternatives"


def test_a_resolved_set_keeps_its_json(client, tmp_path):
    client.login()
    draft = client.resolve(VIDEO)
    client.settings(sources=["soulseek"])
    job = client.wait_job(client.download(draft=draft["id"])["id"])
    assert job["state"] == "done" and job["result"]["found"] == 4
    folder = tmp_path / "music" / VIDEO_SET
    assert (folder / "_tracklist.json").is_file() and not (folder / "_tracklist.html").exists()
    s = client.ok("GET", f"/api/sets/{quote(VIDEO_SET)}")
    assert s["source"] == "resolved" and s["kind"] == "youtube" and s["recording"] == VIDEO and s["cues"] == 5
    assert s["url"] == VIDEO and (s["found"], s["total"]) == (4, 4)
    # A retry works from the JSON copy
    assert client.wait_job(client.download(set=VIDEO_SET)["id"])["state"] == "done"


def test_pasted_text_is_a_draft_right_away(client):
    status, data = client.post("/api/drafts/resolve", {"input": "Night drive\n01. Kettle - Ghosts\n02. A - B\n"})
    assert status == 201 and data["draft"]["source"] == "text" and data["draft"]["kind"] == "text"
    assert data["draft"]["title"] == "Night drive" and data["draft"]["origin"] == {}


@pytest.mark.parametrize("text", ["file:///etc/passwd", "ftp://example.com/list.txt", "http://127.0.0.1:8080/x",
                                  "https://localhost/x", "https://[::1]/x", "https://printer.local/list",
                                  "https://user:pw@example.com/x", "http://localtest.me/admin",
                                  "http://127.0.0.1.nip.io/", "lvh.me/x"])
def test_only_web_links_are_read(client, text):
    status, data = client.post("/api/drafts/resolve", {"input": text})
    assert status == 400 and data["error"]["code"] == "bad_url"
    assert not client.jobs("resolve")


def test_a_path_is_text_and_never_read(client, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("01. Kettle - Ghosts\n02. Saltmarsh - Pressure\n")
    status, data = client.post("/api/drafts/resolve", {"input": str(secret)})
    assert status == 422 and data["error"]["code"] == "not_a_tracklist"


def test_links_without_https_and_spotify_addresses(client):
    draft = client.resolve("youtube.com/watch?v=rooftop0001")
    assert draft["origin"]["url"] == "https://youtube.com/watch?v=rooftop0001"
    spotify = client.resolve("spotify:playlist:37i9dQZF1DX")
    assert spotify["origin"]["url"] == "https://open.spotify.com/playlist/37i9dQZF1DX"
    assert spotify["kind"] == "spotify" and len(spotify["tracks"]) == 3
    assert spotify["warnings"] and "Exportify" in spotify["warnings"][0]


def test_a_spotify_link_that_cant_be_read_points_to_exportify(client, monkeypatch):
    monkeypatch.setenv("FAKE_SPOTIFY_FAIL", "1")
    data = client.ok("POST", "/api/drafts/resolve", {"input": "https://open.spotify.com/playlist/abc"})
    job = client.wait_job(data["job"]["id"])
    assert job["state"] == "failed" and "Exportify" in job["message"]
    assert job["result"]["kind"] == "spotify" and "exportify.app" in job["result"]["help"]
    assert job["result"]["draft"] is None


def test_a_1001tracklists_link_asks_for_the_saved_page(client):
    status, data = client.post("/api/drafts/resolve", {"input": "https://www.1001tracklists.com/tracklist/x/y.html"})
    assert status == 422 and data["error"]["code"] == "save_the_page" and "Save Page As" in data["error"]["message"]


def test_stopping_a_resolve_job_throws_its_draft_away(client, app):
    data = client.ok("POST", "/api/drafts/resolve", {"input": VIDEO})
    client.ok("POST", f"/api/jobs/{data['job']['id']}/stop")
    job = client.wait_job(data["job"]["id"])
    assert job["state"] in ("stopped", "done")
    if job["state"] == "stopped":
        assert not [p for p in (app.work_dir / "drafts").iterdir() if (p / "draft.json").exists()]


def test_an_exportify_csv(client):
    status, draft = drop(client, "Liked_Songs.csv", EXPORTIFY.encode())
    assert status == 201, draft
    assert draft["source"] == "resolved" and draft["kind"] == "exportify" and draft["title"] == "Liked Songs"
    assert draft["origin"] == {"kind": "csv", "name": "Liked_Songs.csv", "url": ""}
    assert [t["display"] for t in draft["tracks"]] == ["Kettle - Ghosts", "Saltmarsh - Pressure"]
    assert draft["tracks"][0]["duration"] == 301
    # Only one tracklist, but resolve still says where it came from
    assert draft["alternatives"] == [] and draft["from"] == {"source": "csv", "label": "Liked_Songs.csv"}


def test_a_tracklist_json(client):
    data = {"title": "From another app", "tracks": [{"artist": "Kettle", "title": "Ghosts"}, {"title": "Baby"}]}
    status, draft = drop(client, "list.json", json.dumps(data).encode())
    assert status == 201 and draft["kind"] == "" and draft["title"] == "From another app"
    assert len(draft["tracks"]) == 2
    status, err = drop(client, "list.json", b"{not json")
    assert status == 422 and err["error"]["code"] == "not_a_tracklist"


def test_a_page_that_isnt_1001tracklists(client):
    page = b"<html><body><h1>My mix</h1><p>01. Kettle - Ghosts</p><p>02. Saltmarsh - Pressure</p></body></html>"
    status, draft = drop(client, "mix.html", page)
    assert status == 201 and draft["source"] == "resolved" and len(draft["tracks"]) == 2


def test_pictures_are_checked_before_reading(client):
    status, data = drop(client, "list.png", b"not really a picture")
    assert status == 415 and data["error"]["code"] == "not_an_image"


def test_a_picture_vision_fails_to_read_at_first_is_read_again(client, tmp_path, monkeypatch):
    marker = tmp_path / "vision-failed"
    monkeypatch.setenv("FAKE_OCR", str(marker))
    status, draft = drop(client, "shot.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    assert status == 201, draft
    assert marker.is_file() and [t["display"] for t in draft["tracks"]] == ["Kettle - Ghosts", "Saltmarsh - Pressure"]


def _ffmpeg_with_drawtext():
    return shutil.which("ffmpeg", path="/opt/homebrew/bin:/usr/local/bin")


@pytest.mark.skipif(sys.platform != "darwin" or not _ffmpeg_with_drawtext(), reason="needs macOS Vision and ffmpeg")
def test_a_screenshot(client, tmp_path):
    pytest.importorskip("Vision")
    text = tmp_path / "list.txt"
    text.write_text("Tracklist\n00:00 Kettle - Ghosts\n04:31 Saltmarsh - Bus Stop Dub\n")
    picture = tmp_path / "shot.png"
    done = subprocess.run([_ffmpeg_with_drawtext(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                           "-i", "color=c=white:s=900x200", "-vf",
                           f"drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:textfile={text}:"
                           "fontcolor=black:fontsize=36:x=30:y=20:line_spacing=18", "-frames:v", "1", str(picture)],
                          capture_output=True)
    if done.returncode != 0:
        pytest.skip("this ffmpeg has no drawtext")
    status, draft = drop(client, "Screenshot 2026-10-31 at 21.04.png", picture.read_bytes())
    assert status == 201, draft
    assert draft["kind"] == "image" and draft["origin"]["kind"] == "image"
    assert [(t["cue"], t["display"]) for t in draft["tracks"]] == [(0, "Kettle - Ghosts"), (271, "Saltmarsh - Bus Stop Dub")]
    assert draft["warnings"]


def test_the_endpoints_need_the_token(client):
    assert client.post("/api/drafts/resolve", {"input": VIDEO}, token=False)[0] == 401
    assert client.post("/api/drafts/0123456789abcdef/pick", {"pick": 0}, token=False)[0] == 401


def test_a_name_is_looked_up_for_where_it_points(monkeypatch):
    """A host name that resolves to the Mac or the local network isn't on the web (the real lookup,
    with socket.getaddrinfo faked)."""
    import socket
    from setdl import resolve as rs
    from tl2mixxx import net
    monkeypatch.setattr(rs, "_local_host", lambda host: net.resolves_local(host))
    answers = {"localtest.me": ["127.0.0.1"], "router.example": ["93.184.216.34", "192.168.1.1"],
               "v6.example": ["::1"], "www.youtube.com": ["142.250.74.46", "2a00:1450:4001:82a::200e"]}

    def fake(host, port, *args, **kwargs):
        if host not in answers:
            raise socket.gaierror(socket.EAI_NONAME, "not known")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in answers[host]]
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    for url in ("http://localtest.me/admin", "https://router.example/x", "https://v6.example/x"):
        with pytest.raises(rs.ApiError):
            rs.as_link(url)
    assert rs.as_link("https://www.youtube.com/watch?v=x") == "https://www.youtube.com/watch?v=x"
    # A name that can't be looked up is left to the job (it fails there, offline or not)
    assert rs.as_link("https://unknown.example/x") == "https://unknown.example/x"
