# SPDX-License-Identifier: GPL-3.0-or-later
"""Tile artwork that is not in the box: fetching a language's set, and
noticing when the set you have is no longer the set we publish.

**Why anything is fetched at all.** Strings ship with the program because they
are kilobytes. A set of tiles is a couple of megabytes per language, and there
is no sense in every install carrying forty languages it will never show. So
the box holds English and the wordless set -- one of which is always right --
and any other language is fetched when somebody asks for it.

**Only from this project.** The artwork comes from this repository and nothing
else. There is no third-party art service here, on purpose: artwork is the one
thing on a tile a user cannot check, and a picture from a stranger is a picture
nobody reviewed.

**What the hashes are and are not.** `assets/tiles/manifest.json` carries a
sha256 per file, and every download is checked against it. That catches a
truncated file, a proxy that rewrote something, a half-finished publish. It is
not a signature: the manifest comes from the same place as the files, so it
proves the download matches what that server said, not who the server is.
HTTPS and a pinned host are what stand behind that, and they are stated here
rather than implied.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import i18n

# The published tree. A tag rather than a branch would pin the artwork to a
# release, which is wrong here: a language somebody adds should reach people
# who already have the program, not wait for the next release of it.
BASE_URL = "https://raw.githubusercontent.com/4o66/sunshine-apps-ui/main/assets/tiles"
MANIFEST_URL = BASE_URL + "/manifest.json"
TIMEOUT = 20

# A set is a directory of PNGs and nothing else. Everything in a manifest is
# treated as hostile until it has been through this: a name with a slash or a
# "*.py" in it would otherwise write wherever it liked when it was saved.
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_FILES_PER_SET = 200


def _safe_name(name: str) -> bool:
    return (isinstance(name, str) and name.endswith(".png")
            and name == os.path.basename(name) and not name.startswith(".")
            and "/" not in name and "\\" not in name and len(name) <= 120)


def _safe_set(code: str) -> bool:
    if not isinstance(code, str) or not code or len(code) > 40:
        return False
    if code == i18n.WORDLESS:
        return True
    return code == i18n._normalise(code) and code.replace("-", "").isalnum()


def clean(manifest: Any) -> Dict[str, Dict[str, str]]:
    """Everything in a manifest we are willing to act on, and nothing else."""
    sets: Dict[str, Dict[str, str]] = {}
    if not isinstance(manifest, dict):
        return sets
    for code, files in (manifest.get("sets") or {}).items():
        if not _safe_set(code) or not isinstance(files, dict):
            continue
        good = {name: digest for name, digest in files.items()
                if _safe_name(name) and isinstance(digest, str)
                and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)}
        if good and len(good) <= MAX_FILES_PER_SET:
            sets[code] = good
    return sets


def local_manifest() -> Dict[str, Dict[str, str]]:
    path = os.path.join(i18n.tiles_dir(), "manifest.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return clean(json.load(handle))
    except (OSError, ValueError):
        return {}


def _get(url: str, timeout: int = TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "sunshine-apps-ui"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_FILE_BYTES + 1)


def remote_manifest(timeout: int = TIMEOUT) -> Tuple[Dict[str, Dict[str, str]], str]:
    """(sets, why it failed). An empty dict with no reason means nothing published."""
    try:
        raw = _get(MANIFEST_URL, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Not an error to explain in HTTP terms: it is what an install
            # older than the published index sees, and what anybody sees
            # before the first set is published.
            return {}, "no artwork index has been published yet"
        return {}, f"the artwork list answered {e.code}"
    except Exception as e:                       # noqa: BLE001 - offline is normal
        return {}, f"the artwork list could not be reached ({e})"
    try:
        return clean(json.loads(raw.decode("utf-8"))), ""
    except ValueError:
        return {}, "the artwork list was not readable"


def installed_sets() -> List[str]:
    """Every set on this machine, wordless included."""
    try:
        return sorted(name for name in os.listdir(i18n.tiles_dir())
                      if os.path.isdir(os.path.join(i18n.tiles_dir(), name))
                      and name != "_template")
    except OSError:
        return []


def have_set(code: str) -> bool:
    """Is there a worded set for this language on this machine?

    Asked of the language, not the directory, so `pt-BR` counts as covered by
    a `pt` set -- which is what the tile lookup will actually use.
    """
    if not code:
        return False
    here = set(installed_sets())
    return any(candidate in here for candidate in i18n.candidates(code)
               if candidate != i18n.DEFAULT or code.startswith(i18n.DEFAULT))


def _digest(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


def stale(remote: Dict[str, Dict[str, str]]) -> Dict[str, int]:
    """How many files differ, per set we actually have. Only sets we have.

    A language we have never asked for is not "out of date", it is somebody
    else's language, and offering to download all of them is how an update
    check turns into a hundred megabytes.
    """
    out: Dict[str, int] = {}
    for code in installed_sets():
        published = remote.get(code)
        if not published:
            continue
        folder = os.path.join(i18n.tiles_dir(), code)
        differing = sum(1 for name, digest in published.items()
                        if _digest(os.path.join(folder, name)) != digest)
        if differing:
            out[code] = differing
    return out


def fetch_set(code: str, remote: Optional[Dict[str, Dict[str, str]]] = None,
              timeout: int = TIMEOUT) -> Tuple[int, str]:
    """Download one set into assets/tiles/<code>. Returns (files written, error).

    **Every file is checked before it is kept**, and a file that does not match
    the manifest is dropped rather than written. A half-downloaded set is worse
    than none: the tile lookup falls back per file, so a partial set produces a
    grid that is half one language and half wordless, which looks like a bug in
    the program rather than an interrupted download.
    """
    if not _safe_set(code):
        return 0, "that is not a language code"
    if remote is None:
        remote, why = remote_manifest(timeout)
        if why:
            return 0, why
    files = remote.get(code)
    if not files:
        return 0, f"there is no {code} artwork published yet"

    staged: Dict[str, bytes] = {}
    for name, digest in sorted(files.items()):
        try:
            body = _get(f"{BASE_URL}/{code}/{name}", timeout)
        except Exception as e:                   # noqa: BLE001
            return 0, f"{name} could not be downloaded ({e})"
        if len(body) > MAX_FILE_BYTES:
            return 0, f"{name} is larger than a tile should be"
        if hashlib.sha256(body).hexdigest() != digest:
            return 0, f"{name} did not match the artwork list"
        staged[name] = body

    folder = os.path.join(i18n.tiles_dir(), code)
    try:
        os.makedirs(folder, exist_ok=True)
        for name, body in staged.items():
            # Written beside the target and moved, so a tile is never half a
            # file on disk while Sunshine is reading it.
            temporary = os.path.join(folder, name + ".part")
            with open(temporary, "wb") as handle:
                handle.write(body)
            os.replace(temporary, os.path.join(folder, name))
    except OSError as e:
        return 0, f"the artwork could not be saved ({e})"
    return len(staged), ""
