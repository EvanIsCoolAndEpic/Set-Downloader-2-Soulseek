"""The Soulseek login sockseek uses, handed to it with -c.

In order: the app's own file (<data dir>/sockseek.conf, written here, mode 0600), else the one the
Mixxx fork saved (used as it is: only its existence is checked, it is never read), else none.
The password is write-only: nothing here returns it.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from .errors import bad_request
from .settings import has_control_chars

APP_LOGIN_NAME = "sockseek.conf"
HEADER = ("# Soulseek login for Set Downloader.\n"
          "# Set Downloader passes this file to sockseek with -c; change it in Set Downloader.\n")


def config_value(path: Path, key: str) -> str:
    """A value of a "key = value" config file like the one written here ("" if none)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    for line in lines:
        line = line.strip()
        name, sep, value = line.partition("=")
        if sep and not line.startswith("#") and name.strip() == key:
            return value.strip()
    return ""


class Login:
    def __init__(self, app_path: Path, mixxx_path: Path):
        self.app_path = app_path
        self.mixxx_path = mixxx_path

    def _app_username(self) -> str:
        return config_value(self.app_path, "username") if self.app_path.is_file() else ""

    def status(self) -> dict:
        """Which login is in use. The Mixxx fork's username isn't shown: its file isn't read."""
        username = self._app_username()
        if username:
            return {"source": "app", "username": username, "path": str(self.app_path)}
        if self.mixxx_path.is_file():
            return {"source": "mixxx", "username": None, "path": str(self.mixxx_path)}
        return {"source": "none", "username": None, "path": None}

    def config_path(self) -> Path | None:
        """The file to pass to sockseek with -c, if there is a login."""
        if self._app_username():
            return self.app_path
        return self.mixxx_path if self.mixxx_path.is_file() else None

    def save(self, username: object, password: object) -> None:
        """Write the app's login file, readable only by the user."""
        if not isinstance(username, str) or not username.strip():
            raise bad_request("Enter your Soulseek username.", "bad_login")
        if not isinstance(password, str) or not password:
            raise bad_request("Enter your Soulseek password.", "bad_login")
        username = username.strip()
        # One "key = value" per line: a line break would add settings of its own
        if has_control_chars(username) or has_control_chars(password):
            raise bad_request("The username and password can't have line breaks or tabs.", "bad_login")
        if password != password.strip():
            raise bad_request("The password can't start or end with a space.", "bad_login")
        if len(username) > 100 or len(password) > 200:
            raise bad_request("That username or password is too long.", "bad_login")
        text = f"{HEADER}username = {username}\npassword = {password}\n"
        self.app_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.app_path.with_name(f".{self.app_path.name}.{secrets.token_hex(4)}.part")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                os.fchmod(f.fileno(), 0o600)   # whatever the umask
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.app_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        os.chmod(self.app_path, 0o600)

    def clear(self) -> None:
        """Forget the app's login (the Mixxx fork's is used again, if there is one)."""
        self.app_path.unlink(missing_ok=True)
