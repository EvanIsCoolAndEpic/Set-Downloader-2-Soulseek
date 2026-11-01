"""Telling a network Soulseek has banned apart from a refused account, against fake servers on this
Mac (the tests never reach the real Soulseek server)."""

import socket
import threading

import pytest

from setdl import jobs


class FakeServer:
    """Accepts connections on 127.0.0.1. "hangup": closes each one at once, like Soulseek's server
    for a banned network. "hold": keeps it open, waiting for a login that never comes."""

    def __init__(self, mode: str):
        self.mode = mode
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.address = "127.0.0.1:%d" % self.sock.getsockname()[1]
        self.connections = 0
        self.received = b""
        self.held: list[socket.socket] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            if self.mode == "hangup":
                conn.close()
            else:
                self.held.append(conn)
                threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn: socket.socket) -> None:
        try:
            while data := conn.recv(1024):
                self.received += data
        except OSError:
            pass

    def close(self) -> None:
        self.sock.close()
        for conn in self.held:
            conn.close()


@pytest.fixture
def soulseek():
    made = []

    def make(mode):
        made.append(FakeServer(mode))
        return made[-1]

    yield make
    for s in made:
        s.close()


def closed_port() -> str:
    with socket.create_server(("127.0.0.1", 0)) as s:
        return "127.0.0.1:%d" % s.getsockname()[1]


def test_a_server_that_hangs_up_at_once_means_the_network_is_blocked(soulseek):
    assert jobs.server_check(soulseek("hangup").address, wait=2) == "blocked"


def test_a_server_that_waits_for_the_login_means_the_network_is_fine(soulseek):
    fake = soulseek("hold")
    assert jobs.server_check(fake.address, wait=0.3) == "open"
    assert fake.received == b""     # nothing is sent: no login


def test_no_server_means_unreachable():
    assert jobs.server_check(closed_port(), wait=1) == "unreachable"
    assert jobs.server_check("not an address", wait=1) == "unreachable"


def test_the_reason_follows_the_server(soulseek, monkeypatch):
    monkeypatch.setattr(jobs, "SERVER_WAIT", 0.3)
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", soulseek("hangup").address)
    assert jobs.refused_login_reason() == jobs.NETWORK_BLOCKED
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", soulseek("hold").address)
    assert jobs.refused_login_reason() == jobs.LOGIN_REFUSED
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", closed_port())
    assert jobs.refused_login_reason() == jobs.SERVER_UNREACHABLE
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", "")
    assert jobs.refused_login_reason() == jobs.LOGIN_REFUSED


def test_a_refused_login_on_a_blocked_network_says_so(client, soulseek, monkeypatch):
    fake = soulseek("hangup")
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", fake.address)
    monkeypatch.setenv("FAKE_SOCKSEEK_LOGIN_REFUSED", "1")
    client.login()
    job = client.wait_job(client.download(draft=client.draft()["id"])["id"], timeout=30)
    assert job["state"] == "failed"
    assert job["message"] == jobs.NETWORK_BLOCKED and job["error"] == jobs.NETWORK_BLOCKED
    assert fake.connections == 1    # one look, after sockseek stopped


def test_a_refused_login_on_a_fine_network_blames_the_account(client, soulseek, monkeypatch):
    monkeypatch.setattr(jobs, "SERVER_WAIT", 0.3)
    monkeypatch.setenv("SETDL_SOULSEEK_SERVER", soulseek("hold").address)
    monkeypatch.setenv("FAKE_SOCKSEEK_LOGIN_REFUSED", "1")
    client.login()
    job = client.wait_job(client.download(draft=client.draft()["id"])["id"], timeout=30)
    assert job["state"] == "failed" and job["message"] == jobs.LOGIN_REFUSED
