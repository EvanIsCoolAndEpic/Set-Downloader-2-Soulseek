import socket

from setdl.server import Server


def test_starting_doesnt_look_up_the_hosts_name(monkeypatch):
    # socket.getfqdn can hang on an mDNS lookup: starting the server must not need it
    def hang(*_):
        raise AssertionError("looked up the host's name")

    monkeypatch.setattr(socket, "getfqdn", hang)
    monkeypatch.setattr(socket, "gethostbyaddr", hang)
    server = Server(object(), port=0)
    try:
        assert server.server_name == "127.0.0.1"
        assert server.port > 0
    finally:
        server.server_close()
