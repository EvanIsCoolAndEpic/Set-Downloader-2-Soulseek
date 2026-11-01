import os
import stat

from conftest import SET_NAME

PASSWORD = "Pa55 word-XYZZY"


def test_no_login_refuses_soulseek_jobs(client):
    state = client.ok("GET", "/api/state")
    assert state["login"] == {"source": "none", "username": None, "path": None}
    draft = client.draft()
    status, data = client.post("/api/downloads", {"draft": draft["id"]})
    assert status == 409 and data["error"]["code"] == "login_required"
    status, data = client.post("/api/searches", {"query": "Kettle - Ghosts"})
    assert status == 409 and data["error"]["code"] == "login_required"
    assert client.ok("GET", "/api/jobs")["jobs"] == []


def test_saved_login_is_private_and_write_only(client, app, tmp_path, capfd):
    data = client.ok("PUT", "/api/login", {"username": "  tester ", "password": PASSWORD})
    path = tmp_path / "data" / "sockseek.conf"
    assert data["login"] == {"source": "app", "username": "tester", "path": str(path)}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    text = path.read_text()
    assert "username = tester\n" in text and f"password = {PASSWORD}\n" in text
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".part")] == []
    # Saved again (another password): still 0600, even with a loose umask
    old = os.umask(0)
    try:
        client.login("tester", "another one")
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    client.login("tester", PASSWORD)
    job = client.wait_job(client.ok("POST", "/api/searches", {"query": "Kettle - Ghosts"})["job"]["id"])
    assert job["state"] == "done"
    # sockseek got the file, not the password
    assert f"-c {path}" in (tmp_path / "sockseek.log").read_text()
    seen = [client.get("/api/state")[1], client.get("/api/jobs")[1], client.get(f"/api/jobs/{job['id']}")[1]]
    assert all(PASSWORD not in repr(x) for x in seen)
    assert any(f"-c {path}" in line for line in job["log"])
    out = capfd.readouterr()
    assert PASSWORD not in out.out + out.err


def test_bad_logins_are_refused(client, tmp_path):
    for body in ({"username": "", "password": "x"}, {"username": "a", "password": ""},
                 {"username": "a", "password": "x\non-complete = rm -rf ~"},
                 {"username": "a\nb", "password": "x"}, {"username": "a", "password": " padded "},
                 {"username": "a", "password": 5}, {"username": "a" * 101, "password": "x"}):
        status, data = client.put("/api/login", body)
        assert status == 400 and data["error"]["code"] == "bad_login", body
    assert not (tmp_path / "data" / "sockseek.conf").exists()


def test_mixxx_login_is_used_without_being_read(client, tmp_path):
    mixxx = tmp_path / "home" / "mixxx-login.conf"
    mixxx.write_text("username = mixxxuser\npassword = MIXXX-SECRET\n")
    mixxx.chmod(0o600)
    state = client.ok("GET", "/api/state")
    assert state["login"] == {"source": "mixxx", "username": None, "path": str(mixxx)}
    job = client.wait_job(client.ok("POST", "/api/searches", {"query": "Kettle - Ghosts"})["job"]["id"])
    assert job["state"] == "done"
    assert f"-c {mixxx}" in (tmp_path / "sockseek.log").read_text()
    everything = repr([client.get("/api/state")[1], client.get(f"/api/jobs/{job['id']}")[1]])
    assert "MIXXX-SECRET" not in everything and "mixxxuser" not in everything
    # The app's own login wins once there is one; removing it falls back again
    client.login()
    assert client.ok("GET", "/api/state")["login"]["source"] == "app"
    assert client.ok("DELETE", "/api/login")["login"]["source"] == "mixxx"
    assert mixxx.read_text().startswith("username = mixxxuser")   # untouched


def test_login_change_is_an_event(client, app):
    q = app.bus.subscribe()
    client.login()
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()[1])
    app.bus.unsubscribe(q)
    assert "state" in kinds


def test_retry_needs_login_too(client, downloaded):
    client.ok("DELETE", "/api/login")
    status, data = client.post("/api/downloads", {"set": SET_NAME})
    assert status == 409 and data["error"]["code"] == "login_required"
