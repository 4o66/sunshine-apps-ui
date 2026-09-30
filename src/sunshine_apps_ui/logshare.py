# SPDX-License-Identifier: GPL-3.0-or-later
"""Share the log (#71): what the log holds, taken out before it is sent, and the sending.

The share screen shows "What this log contains" before anything leaves the
machine: one row per kind of thing found, with the value itself where there is
one. Some are always taken out, because nobody reporting a bug needs them sent:

- the session token, which opens this manager without asking;
- anything that looks like a key or a password;
- the home folder (shown as ``~``) and the user name;
- this machine's name, the Moonlight device's name, the Sunshine user name;
- network addresses, and a controller's Bluetooth address.

Three are kept unless their Remove switch is on, because they are often what
the bug is about: controller names, game names, and folders outside the home.

The rules err toward taking out too much. What they cannot see is left alone,
so every rule has a test against a sample log (tests/test_logshare.py).

Sending is dpaste.com's documented API (https://dpaste.com/api/): 7 days,
public to anyone with the link, a User-Agent that names this program, at most
one request a second, and the log cut to its last 900 KB to stay under the
service's 1 MB.
"""
from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

MAX_BYTES = 900 * 1024
DPASTE_URL = "https://dpaste.com/api/v2/"
EXPIRY_DAYS = 7
CUT_NOTE = "[earlier lines cut to stay under the paste service's size limit]"

# The switches, and what each puts in place of what it removes.
OPTIONAL = ("controllers", "games", "folders")

TOKEN = re.compile(r"(token=)[^\s&#\"'<>]+", re.I)
# A header or a parameter whose value is a secret, and a bare 32-hex string
# (a SteamGridDB key). The value runs to the end of the word.
SECRET_FIELD = re.compile(
    r"(\b(?:authorization|cookie|set-cookie|password|passwd|api[_-]?key|key|secret)"
    r"\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|(?:bearer\s+|basic\s+)?[^\s,;&]+)", re.I)
HEX32 = re.compile(r"\b[0-9a-fA-F]{32}\b")
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
# A line about a controller: the Bluetooth address on it is the pad's.
PAD_LINE = re.compile(r"\b(pad|controller|gamepad|joystick|uniq)\b", re.I)
# The pad summary pad.js sends, and the host's list of pads.
# The lines this program writes about pads: the name runs to the first comma
# (a name's own commas are taken out before it is logged; see pad_line).
PAD_NAME = re.compile(r"(?:\bpad: |\bhost: pad [0-9a-f]{4}:[0-9a-f]{4} v[0-9a-f]{4} bus [0-9a-f]{4}: )"
                      r"([^,\n]+),", re.I | re.M)
# A folder: an absolute path that is not a system one, up to the next space.
POSIX_PATH = re.compile(r"/[^\s\"'<>|:,;()]+")
# What may come before a folder: not a word, ~, a URL's // or :, or a
# replacement's closing bracket.
NOT_BEFORE_PATH = re.compile(r"[\w~.:/\]\\]")
WIN_PATH = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>|,;()]*")
SYSTEM_DIRS = ("/usr/", "/etc/", "/proc/", "/sys/", "/dev/", "/tmp/", "/var/", "/bin/",
               "/lib", "/sbin/", "/run/user/", "/app/", "/opt/", "/snap/", "/nix/",
               "/flatpak/", "/api/", "/art", "/_")


@dataclass
class Finding:
    """One row of What this log contains."""
    kind: str
    count: int = 0
    values: List[str] = field(default_factory=list)
    # For addresses: how many were a controller's.
    controller: int = 0

    def add(self, value: Optional[str] = None) -> None:
        self.count += 1
        if value and value not in self.values:
            self.values.append(value)


@dataclass
class Examined:
    """The log as it will be sent, and what was found in it.

    ``pieces`` is the sent text in order, each piece marked as replaced or
    not, so the preview can highlight what changed.
    """
    pieces: List[Tuple[str, bool]]
    findings: Dict[str, Finding]
    cut: bool = False

    @property
    def text(self) -> str:
        return "".join(p for p, _ in self.pieces)

    def found(self, kind: str) -> Optional[Finding]:
        f = self.findings.get(kind)
        return f if f and f.count else None


@dataclass
class Facts:
    """What this machine would give away, looked up once."""
    home: str = ""
    user: str = ""
    hostname: str = ""
    client_name: str = ""
    sunshine_user: str = ""
    games: Sequence[str] = ()


def machine_facts(client_name: str = "", sunshine_user: str = "",
                  games: Iterable[str] = ()) -> Facts:
    import getpass
    import socket
    home = os.path.expanduser("~")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name to hide is not an error
        user = os.path.basename(home)
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = ""
    return Facts(home=home if home not in ("", "/", "~") else "", user=user or "",
                 hostname=hostname or "", client_name=client_name or "",
                 sunshine_user=sunshine_user or "",
                 games=tuple(games))


class _Editor:
    """Replacements over a text, kept as marked pieces so later rules only
    see what earlier ones left."""

    def __init__(self, text: str) -> None:
        self.pieces: List[Tuple[str, bool]] = [(text, False)]
        # The character before the current match, across pieces.
        self.before = ""

    def sub(self, pattern: "re.Pattern[str]", make) -> None:
        """make(match) -> replacement, or None to leave the match alone."""
        out: List[Tuple[str, bool]] = []
        for piece, done in self.pieces:
            if done:
                out.append((piece, done))
                continue
            at = 0
            for m in pattern.finditer(piece):
                self.before = piece[m.start() - 1] if m.start() else (out[-1][0][-1:] if out else "")
                new = make(m, piece)
                if new is None:
                    continue
                keep, replaced = new if isinstance(new, tuple) else ("", new)
                start = m.start() + len(keep)
                if start > at:
                    out.append((piece[at:start], False))
                out.append((replaced, True))
                at = m.end()
            if at < len(piece):
                out.append((piece[at:], False))
        self.pieces = out

    def literal(self, value: str, replacement: str, finding: Finding,
                word: bool = False, record: Optional[str] = None) -> None:
        if not value:
            return
        body = re.escape(value)
        pattern = re.compile(rf"(?<![\w.-]){body}(?![\w-])" if word else body, re.I)

        def make(m, _piece):
            finding.add(record)
            return replacement
        self.sub(pattern, make)


def _line_of(piece: str, index: int) -> str:
    start = piece.rfind("\n", 0, index) + 1
    end = piece.find("\n", index)
    return piece[start:end if end >= 0 else len(piece)]


def _public_ip(text: str) -> bool:
    try:
        a = ipaddress.ip_address(text)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_unspecified)


def _outside_home(path: str) -> bool:
    if path.startswith(SYSTEM_DIRS) or path in ("/", "//"):
        return False
    # A URL's path, or one component: not a folder anyone owns.
    return path.count("/") >= 2


def examine(text: str, facts: Facts, remove: Iterable[str] = ()) -> Examined:
    """Take out what is never sent, and what the switches say to, from ``text``."""
    remove = set(remove)
    F = {k: Finding(k) for k in ("token", "secrets", "home", "machine", "device",
                                  "sunshine_user", "addresses", "controllers",
                                  "games", "folders")}
    ed = _Editor(text)

    # Always: the token and secrets first, so no later rule sees them.
    ed.sub(TOKEN, lambda m, p: (F["token"].add(), (m.group(1), "[removed]"))[1])
    ed.sub(SECRET_FIELD, lambda m, p: (F["secrets"].add(), (m.group(1), "[removed]"))[1])
    ed.sub(HEX32, lambda m, p: (F["secrets"].add(), "[removed]")[1])
    ed.literal(facts.sunshine_user, "[removed]", F["sunshine_user"], word=True,
               record=facts.sunshine_user)

    # The home folder as ~, both spellings on Windows; then the user name alone.
    homes = {facts.home, os.path.realpath(facts.home) if facts.home else ""}
    if facts.home and "\\" in facts.home:
        homes.add(facts.home.replace("\\", "/"))
    for h in sorted((h for h in homes if h), key=len, reverse=True):
        ed.literal(h.rstrip("/\\"), "~", F["home"], record=facts.home)
    if facts.user and len(facts.user) >= 2:
        ed.literal(facts.user, "[user]", F["home"], word=True)

    # The machine's name, whole and short, and the Moonlight device's.
    for name in sorted({facts.hostname, facts.hostname.split(".")[0]}, key=len, reverse=True):
        if len(name) >= 2 and name.lower() not in ("localhost",):
            ed.literal(name, "[machine]", F["machine"], word=True, record=facts.hostname)
    ed.literal(facts.client_name, "[device]", F["device"], word=True, record=facts.client_name)

    # Addresses: hardware ones (a pad's Bluetooth address, on its own line), then IPs.
    def mac(m, piece):
        F["addresses"].add()
        if PAD_LINE.search(_line_of(piece, m.start())):
            F["addresses"].controller += 1
        return "[address]"
    ed.sub(MAC, mac)
    ed.sub(IPV4, lambda m, p: (F["addresses"].add(), "[address]")[1] if _public_ip(m.group(0)) else None)
    ed.sub(IPV6, lambda m, p: (F["addresses"].add(), "[address]")[1] if _public_ip(m.group(0)) else None)

    # Asked: controller names, game names, folders outside the home. Found
    # either way, so the screen can name them; replaced only when switched on.
    for m in PAD_NAME.finditer(ed_text(ed)):
        name = m.group(1).strip()
        if name and name not in F["controllers"].values:
            F["controllers"].values.append(name)
    for name in sorted(F["controllers"].values, key=len, reverse=True):
        _optional(ed, name, "[controller]", F["controllers"], "controllers" in remove)
    # A name of one or two letters would match all through the log.
    for game in sorted({g.strip() for g in facts.games if len(g.strip()) >= 3}, key=len, reverse=True):
        _optional(ed, game, "[game]", F["games"], "games" in remove, word=True)

    def folder(m, piece):
        path = m.group(0).rstrip(".")
        if m.re is POSIX_PATH and (NOT_BEFORE_PATH.match(ed.before or " ") or not _outside_home(path)):
            return None
        if m.re is WIN_PATH and re.match(r"[A-Za-z]:\\(windows|program|programdata)\b", path, re.I):
            return None
        F["folders"].add(_folder_of(path))
        return "[folder]" if "folders" in remove else None
    ed.sub(POSIX_PATH, folder)
    ed.sub(WIN_PATH, folder)

    ex = Examined(pieces=_merge(ed.pieces), findings=F)
    return _cut(ex)


def ed_text(ed: _Editor) -> str:
    return "".join(p for p, _ in ed.pieces)


def _optional(ed: _Editor, value: str, replacement: str, finding: Finding,
              on: bool, word: bool = False) -> None:
    if on:
        ed.literal(value, replacement, finding, word=word, record=value)
        return
    body = re.escape(value)
    pattern = re.compile(rf"(?<![\w]){body}(?![\w])" if word else body, re.I)
    hits = len(pattern.findall(ed_text(ed)))
    if hits:
        finding.count += hits
        if value not in finding.values:
            finding.values.append(value)


def _folder_of(path: str) -> str:
    """The folder a path is in, three levels deep at most: /mnt/games/SteamLibrary."""
    sep = "\\" if "\\" in path else "/"
    parts = [p for p in path.split(sep) if p]
    if sep == "\\":
        return sep.join(parts[:3])
    return "/" + "/".join(parts[:3])


def _merge(pieces: List[Tuple[str, bool]]) -> List[Tuple[str, bool]]:
    out: List[Tuple[str, bool]] = []
    for piece, done in pieces:
        if not piece:
            continue
        if out and out[-1][1] == done:
            out[-1] = (out[-1][0] + piece, done)
        else:
            out.append((piece, done))
    return out


def _cut(ex: Examined) -> Examined:
    """Keep the last MAX_BYTES, from a line's start, with a note that it was cut."""
    total = sum(len(p.encode("utf-8")) for p, _ in ex.pieces)
    if total <= MAX_BYTES:
        return ex
    budget = MAX_BYTES - len(CUT_NOTE) - 1
    kept: List[Tuple[str, bool]] = []
    for piece, done in reversed(ex.pieces):
        size = len(piece.encode("utf-8"))
        if size <= budget:
            kept.append((piece, done))
            budget -= size
            continue
        tail = piece.encode("utf-8")[-budget:].decode("utf-8", "ignore") if budget > 0 else ""
        kept.append((tail, done))
        break
    kept.reverse()
    text = "".join(p for p, _ in kept)
    drop = text.find("\n") + 1  # start at a whole line
    out: List[Tuple[str, bool]] = [(CUT_NOTE + "\n", False)]
    for piece, done in kept:
        if drop >= len(piece):
            drop -= len(piece)
            continue
        out.append((piece[drop:], done))
        drop = 0
    return Examined(pieces=_merge(out), findings=ex.findings, cut=True)


# ------------------------------------------------------------- sending ---

_last_send = 0.0
_send_lock = threading.Lock()


class SendError(Exception):
    """Why a log could not be sent, in words for the screen."""


def user_agent() -> str:
    from .version import version
    return f"sunshine-apps-ui/{version()} (+https://github.com/4o66/sunshine-apps-ui)"


def send(text: str, timeout: float = 20.0,
         opener=urllib.request.urlopen) -> str:
    """Post ``text`` to dpaste.com and return the paste's address."""
    global _last_send
    body = urllib.parse.urlencode({
        "content": text, "syntax": "text", "expiry_days": str(EXPIRY_DAYS),
        "title": "sunshine-apps-ui log"}).encode("utf-8")
    request = urllib.request.Request(DPASTE_URL, data=body, method="POST", headers={
        "User-Agent": user_agent(),
        "Content-Type": "application/x-www-form-urlencoded"})
    with _send_lock:
        wait = 1.0 - (time.monotonic() - _last_send)
        if wait > 0:
            time.sleep(wait)
        _last_send = time.monotonic()
        try:
            with opener(request, timeout=timeout) as response:
                address = (response.headers.get("Location") or
                           response.read().decode("utf-8", "replace")).strip()
        except urllib.error.HTTPError as e:
            raise SendError(f"dpaste.com refused it ({e.code}).") from e
        except (urllib.error.URLError, OSError) as e:
            raise SendError("dpaste.com could not be reached.") from e
    if not address.startswith("https://dpaste.com/"):
        raise SendError("dpaste.com answered, but not with a link.")
    return address
