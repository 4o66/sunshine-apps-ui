# SPDX-License-Identifier: GPL-3.0-or-later
"""Talking to Sunshine's own web API so a written apps.json takes effect.

Sunshine re-reads apps.json at startup and in exactly two other places:
saveApp() and deleteApp(), which both call proc::refresh (confighttp.cpp).
There is no file watcher. Writing the file therefore changes nothing visible
until Sunshine restarts -- and restarting drops any stream in progress,
including the one you may be running this from.

Posting one unchanged app back to /api/apps triggers that same refresh without
a restart.

Two consequences of using Sunshine's own write path, both harmless but worth
knowing: saveApp() drops empty "prep-cmd"/"detached" keys from what it stores,
and it sorts the apps array by name. Neither changes what any client displays --
Moonlight sorts the list itself -- but the file on disk is rewritten.
"""

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from . import filemode

from .utils import log

DEFAULT_BASE_URL = "https://127.0.0.1:47990"
CREDENTIALS_FILE = ".bsm-credentials"


class SunshineAPIError(RuntimeError):
    """Sunshine's API could not be reached, authenticated to, or used."""


def load_credentials(conf_dir: str) -> Tuple[str, str]:
    """Credentials from the environment, else a mode-600 file in conf_dir.

    Never from argv: the parent project already leaks --sgdb-key into ps output
    and shell history, and a password is worse.
    """
    user = os.getenv("SUNSHINE_USERNAME", "").strip()
    password = os.getenv("SUNSHINE_PASSWORD", "")
    if user and password:
        return user, password

    path = os.path.join(conf_dir, CREDENTIALS_FILE)
    if not os.path.isfile(path):
        raise SunshineAPIError(
            f"No Sunshine credentials. Set SUNSHINE_USERNAME and SUNSHINE_PASSWORD, "
            f"or write them to {path} as two lines 'username=...' and 'password=...' "
            f"with mode 600."
        )
    private, why = filemode.check_private(path)
    if not private:
        raise SunshineAPIError(why)

    values: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            # The password is taken verbatim apart from the line ending. Trimming
            # it would silently turn a password with a leading or trailing space
            # into a baffling authentication failure. The username is trimmed,
            # since Sunshine compares it case-insensitively anyway.
            values[key] = value if key == "password" else value.strip()
    if not values.get("username") or not values.get("password"):
        raise SunshineAPIError(f"{path} needs both 'username=' and 'password=' lines")
    return values["username"], values["password"]


def _tls_context(conf_dir: str) -> ssl.SSLContext:
    """Verify against Sunshine's own certificate, rather than not verifying.

    The web UI presents the self-signed cert in credentials/cacert.pem. Its
    CN is "Sunshine Gamestream Host", not a hostname, so hostname checking is
    off -- but the certificate itself is still verified, which is what stops
    another local process that grabbed the port from collecting the password.
    """
    cafile = os.path.join(conf_dir, "credentials", "cacert.pem")
    if not os.path.isfile(cafile):
        raise SunshineAPIError(
            f"Cannot verify Sunshine's certificate: {cafile} not found. "
            f"Refusing to send credentials over an unverified connection."
        )
    ctx = ssl.create_default_context(cafile=cafile)
    ctx.check_hostname = False
    return ctx


def verify_credentials(conf_dir: str, user: str, password: str,
                       base_url: str = DEFAULT_BASE_URL) -> None:
    """Raise SunshineAPIError unless Sunshine accepts these credentials."""
    client = SunshineClient.__new__(SunshineClient)
    client.base_url = base_url.rstrip("/")
    client.timeout = 10
    client._ctx = _tls_context(conf_dir)
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    client._auth = f"Basic {token}"
    client.get_apps()


def save_credentials(conf_dir: str, user: str, password: str) -> str:
    """Verify first, then write mode-600. Returns the path written."""
    if not user or not password:
        raise SunshineAPIError("Both a username and a password are required")
    if "\n" in password or "\r" in password or "\n" in user or "\r" in user:
        # The file is one key=value per line, so a newline could not be read back.
        raise SunshineAPIError("A username or password containing a newline cannot be stored")
    verify_credentials(conf_dir, user, password)
    path = os.path.join(conf_dir, CREDENTIALS_FILE)
    # Create with restrictive permissions from the outset rather than widening
    # then narrowing, which would leave a readable window.
    filemode.write_private(path, f"username={user}\npassword={password}\n")
    return path


class SunshineClient:
    def __init__(self, conf_dir: str, base_url: str = DEFAULT_BASE_URL,
                 timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._ctx = _tls_context(conf_dir)
        user, password = load_credentials(conf_dir)
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        self._auth = f"Basic {token}"

    def _request(self, method: str, path: str,
                 body: Optional[Dict[str, Any]] = None) -> Any:
        data = None
        headers = {"Authorization": self._auth, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        # Deliberately no Origin or Referer. validate_csrf_token() treats a
        # request carrying neither as non-browser, and so not a CSRF risk, which
        # is exactly what this is.
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SunshineAPIError("Sunshine rejected the credentials") from e
            if e.code == 400:
                raise SunshineAPIError(
                    "Sunshine could not read its own apps.json. A field may hold "
                    "a value of the wrong type, such as a non-numeric exit-timeout."
                ) from e
            if e.code == 403:
                raise SunshineAPIError(
                    "Sunshine refused the request. Its origin_web_ui_allowed "
                    "setting may not permit connections from here."
                ) from e
            raise SunshineAPIError(f"{method} {path} failed: HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise SunshineAPIError(f"Could not reach {self.base_url}: {e.reason}") from e
        except ssl.SSLError as e:
            raise SunshineAPIError(f"TLS verification failed: {e}") from e

        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as e:
            raise SunshineAPIError(f"{method} {path} did not return JSON: {e}") from e

    def get_apps(self) -> Dict[str, Any]:
        doc = self._request("GET", "/api/apps")
        if not isinstance(doc, dict) or not isinstance(doc.get("apps"), list):
            raise SunshineAPIError("/api/apps did not return an apps list")
        return doc

    def browse(self, path: str = "", kind: str = "any") -> Dict[str, Any]:
        """List a directory through Sunshine, which already has this endpoint.

        Going through Sunshine rather than reading the filesystem ourselves
        means one implementation of what counts as an executable, and nothing
        new that can read arbitrary paths.
        """
        query = urllib.parse.urlencode({"path": path or "", "type": kind or "any"})
        doc = self._request("GET", f"/api/browse?{query}")
        if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
            raise SunshineAPIError("/api/browse did not return a listing")
        return doc

    def reload(self) -> str:
        """Make Sunshine re-read apps.json. Returns the app used to do it.

        The GET is not optional. /api/apps addresses apps by their position in
        the array and they have no stable id, so an index read before our own
        write -- or before anything else touched the file -- can point at a
        different app by the time we post. Always re-read immediately first.
        """
        apps = self.get_apps()["apps"]
        if not apps:
            raise SunshineAPIError(
                "Sunshine reports no apps, so there is nothing to re-save. "
                "Restart Sunshine to load the file."
            )
        index = 0
        body = dict(apps[index])
        name = str(body.get("name", "?"))
        body["index"] = index
        self._request("POST", "/api/apps", body)
        return name


def reload_sunshine(conf_dir: str, base_url: str = DEFAULT_BASE_URL) -> bool:
    """Best-effort hot reload. Returns True on success, logs and returns False otherwise."""
    try:
        client = SunshineClient(conf_dir, base_url)
        name = client.reload()
        log(f"Sunshine reloaded apps.json (via a no-op save of {name!r}); no restart needed.")
        return True
    except SunshineAPIError as e:
        log(f"Could not reload Sunshine: {e}")
        log("apps.json was written but Sunshine has not re-read it. "
            "Restart Sunshine, or pass --restart, to pick it up.")
        return False
