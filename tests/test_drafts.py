from conftest import FIXTURE, SET_NAME

TEXT = """Four Tet @ Somewhere 2026-10-30
01. Kettle - Ghosts [RINSE]
02. Saltmarsh - Pressure
w/ Vox Unit - Say It (Acappella)
03. ID - ID
"""


def test_a_dropped_page_becomes_a_draft(client):
    draft = client.draft()
    assert draft["title"] == SET_NAME and draft["set"] == SET_NAME and not draft["set_exists"]
    assert draft["source"] == "page" and draft["url"].startswith("https://www.1001tracklists.com/")
    assert draft["has_mashups"] and draft["unidentified"] == 2
    assert draft["counts"] == {"components": 7, "original": 6, "both": 8}
    rows = {t["row"]: t for t in draft["tracks"]}
    assert len(rows) == 10
    mashup = next(t for t in rows.values() if t["kind"] == "mashup")
    assert mashup["downloads"] == {"components": False, "original": True, "both": True}
    part = next(t for t in rows.values() if t["kind"] == "component")
    assert part["downloads"] == {"components": True, "original": False, "both": True}
    assert part["mashup_of"] == mashup["row"]
    unknown = next(t for t in rows.values() if t["display"] == "ID - ID")
    assert unknown["unidentified"] and not any(unknown["downloads"].values())
    first = rows[1]
    assert first["number"] == "01" and first["duration"] == 372 and first["label"] == "SPEEDBUMP"
    # Read again later
    assert client.ok("GET", f"/api/drafts/{draft['id']}")["title"] == SET_NAME


def test_pasted_text_becomes_a_draft(client):
    draft = client.ok("POST", "/api/drafts/text", {"text": TEXT})
    assert draft["source"] == "text" and draft["title"] == "Four Tet @ Somewhere 2026-10-30"
    assert [t["display"] for t in draft["tracks"]] == [
        "Kettle - Ghosts", "Saltmarsh - Pressure", "Vox Unit - Say It (Acappella)", "ID - ID"]
    assert draft["counts"]["components"] == 3 and not draft["has_mashups"]
    # A name given separately; and text without one is named after when it was pasted
    named = client.ok("POST", "/api/drafts/text", {"text": TEXT, "title": "My name"})
    assert named["title"] == "My name"
    untitled = client.ok("POST", "/api/drafts/text", {"text": "01. Kettle - Ghosts\n02. A - B\n"})
    assert untitled["title"].startswith("Pasted tracklist 20")


def test_a_dropped_txt_file_is_text(client, tmp_path):
    path = tmp_path / "my set.txt"
    path.write_text(TEXT)
    draft = client.draft(path)
    assert draft["source"] == "text" and draft["file"] == "my set.txt" and len(draft["tracks"]) == 4


def test_not_a_tracklist(client):
    status, data = client.post("/api/drafts/page?name=x.html", b"<html><body>hello</body></html>")
    assert status == 422 and data["error"]["code"] == "not_a_tracklist" and "No tracks found" in data["error"]["message"]
    status, data = client.post("/api/drafts/text", {"text": "just words\nno tracks here"})
    assert status == 422
    assert client.post("/api/drafts/text", {"text": "   "})[0] == 400
    assert client.post("/api/drafts/page?name=x.html", b"")[0] == 400


def test_a_draft_of_a_set_downloaded_before(client, downloaded):
    draft = client.draft()
    assert draft["set_exists"] and draft["set"] == SET_NAME


def test_deleting_a_draft(client):
    draft = client.draft()
    assert client.ok("DELETE", f"/api/drafts/{draft['id']}") == {"ok": True}
    assert client.get(f"/api/drafts/{draft['id']}")[0] == 404
    assert client.delete(f"/api/drafts/{draft['id']}")[0] == 404


def test_page_in_another_encoding(client, tmp_path):
    page = FIXTURE.read_text(encoding="utf-8").replace("Fog Machine", "Fög Machine").encode("cp1252")
    status, draft = client.post("/api/drafts/page?name=x.html", page)
    assert status == 201 and draft["tracks"][0]["title"].startswith("Fög Machine")
