# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding candidate cover art for an app, so a person can choose between them.

The importer picks the first artwork that works and stops. Someone choosing
artwork wants the opposite: every option at once, side by side. This module
enumerates candidates instead of choosing one, caches each as a 600x900 PNG
under the config directory, and copies the chosen one into place.

Caching the full image rather than a thumbnail is deliberate. The candidate has
already been fetched by the time it is on screen, so choosing it cannot fail on
a slow CDN or an expired SteamGridDB token -- it is a file copy. It also means
the front end never needs network access of its own: it serves the cache.

Why this lives here and not in the front end: apps.json, the images tree and the
SteamGridDB key are all the importer's, and a second implementation of any of
them is a second thing to keep right.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from . import filemode
from .utils import log

CACHE_DIRNAME = ".candidates"
CACHE_TTL = 7 * 24 * 3600
CHOSEN_DIRNAME = "chosen"

# How many SteamGridDB results to offer. The API returns hundreds for a popular
# game, sorted by community score; past the first dozen they are novelty art.
SGDB_LIMIT = 12

_USER_AGENT = "bazzite-sunshine-manager/2.0"
_SGDB_BASE = "https://www.steamgriddb.com/api/v2"

# Steam's library cache has two layouts. The old one is flat, named
# <appid>_<asset>.jpg. The current one is a directory per appid, with the
# portrait and header a further level down under a content hash:
#
#   librarycache/526870/library_hero.jpg
#   librarycache/526870/8968499686cff.../library_capsule.jpg
#
# A machine that has been through the upgrade has both, so look for both. The
# asset is identified by its filename either way, which is why this is a table
# of names rather than a pair of path templates. "library_capsule" is the
# current name for what used to be "library_600x900" -- the portrait.
_LOCAL_ASSET_LABELS = (
    ("library_600x900", "Portrait"),
    ("library_capsule", "Portrait"),
    ("library_600x900_2x", "Portrait (high resolution)"),
    ("library_hero", "Hero banner"),
    ("library_header", "Header"),
    ("header", "Header"),
    ("logo", "Logo"),
)
_LOCAL_EXTENSIONS = (".jpg", ".png")

_CDN_HOSTS = (
    "https://steamcdn-a.akamaihd.net/steam/apps/{appid}/{asset}",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{asset}",
    "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/{asset}",
)

_CDN_ASSETS = (
    ("library_600x900.jpg", "Portrait"),
    ("library_600x900_2x.jpg", "Portrait (high resolution)"),
    ("library_hero.jpg", "Hero banner"),
    ("header.jpg", "Header"),
)


class ArtworkError(RuntimeError):
    """A candidate could not be found, fetched or stored."""


# --------------------------------------------------------------------------
# Where things live


def _listdir(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _steam_candidates(home: str) -> List[Tuple[str, str]]:
    """(path, kind) for every place Steam keeps its root, most specific first.

    The library *cache* layout inside the root is the same everywhere -- that is
    what makes the artwork sources portable. Only the root differs.
    """
    if os.name == "nt":
        import ntpath
        found = []
        for env in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
            root = os.environ.get(env)
            if root:
                found.append((ntpath.join(root, "Steam"), "native"))
        # A Steam moved to another drive still records where it went.
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                path = str(winreg.QueryValueEx(key, "SteamPath")[0])
                if path:
                    found.insert(0, (ntpath.normpath(path), "native"))
        except OSError:
            pass
        return found

    if sys.platform == "darwin":
        return [(os.path.join(home, "Library", "Application Support", "Steam"), "native")]

    return [(f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam", "flatpak"),
            (f"{home}/.local/share/Steam", "native"),
            (f"{home}/.steam/steam", "native")]


def find_steam_root(home: str) -> Tuple[str, str]:
    """Return (steam root, "flatpak"|"native"), or ("", "") if Steam is absent."""
    for path, kind in _steam_candidates(home):
        if os.path.isdir(path):
            return path, kind
    return "", ""


def cache_dir(conf_dir: str) -> str:
    return os.path.join(conf_dir, "images", CACHE_DIRNAME)


def chosen_dir(conf_dir: str) -> str:
    return os.path.join(conf_dir, "images", CHOSEN_DIRNAME)


def candidate_id(origin: str) -> str:
    """A stable id for a candidate, derived from where it came from.

    The front end hands this back to choose it, so it has to survive a URL and
    mean the same thing on the second request. Hashing the origin also means the
    same art found twice is cached once.
    """
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]


def prune_cache(conf_dir: str, ttl: int = CACHE_TTL) -> int:
    """Drop cached candidates nobody chose. Returns how many were removed."""
    directory = cache_dir(conf_dir)
    if not os.path.isdir(directory):
        return 0
    cutoff = time.time() - ttl
    removed = 0
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


# --------------------------------------------------------------------------
# Fetching


def _http_bytes(url: str, timeout: int, headers: Optional[Dict[str, str]] = None) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT, "Accept": "image/*", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    # Steam answers a missing asset with a tiny placeholder rather than a 404.
    return data if data and len(data) >= 1024 else b""


def _origin_bytes(origin: str, timeout: int) -> bytes:
    if re.match(r"^https?://", origin, re.I):
        return _http_bytes(origin, timeout)
    with open(origin, "rb") as handle:
        return handle.read()


def _store(conf_dir: str, cid: str, data: bytes) -> str:
    """Write *data* into the candidate cache as a 600x900 PNG. Returns its path."""
    directory = cache_dir(conf_dir)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{cid}.png")

    raw = path + ".raw"
    with open(raw, "wb") as handle:
        handle.write(data)
    try:
        from .images import stretch_png_600x900
        ok = stretch_png_600x900(raw, path)
    except Exception as e:  # pillow missing or unusable
        log(f"Artwork: cannot convert {cid}: {e}")
        ok = False
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass
    if not ok:
        raise ArtworkError("Could not read that image")
    return path


def _fetch_candidate(conf_dir: str, candidate: Dict[str, Any], timeout: int) -> Optional[Dict[str, Any]]:
    """Fill in *candidate*'s cached file, or drop it if it cannot be had."""
    origin = candidate["origin"]
    path = os.path.join(cache_dir(conf_dir), f"{candidate['id']}.png")
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        os.utime(path, None)  # it is in use; do not let prune_cache take it
        candidate["path"] = path
        return candidate
    # Steam serves the same bytes from several CDN hosts and any one of them can
    # be having a bad day, so a candidate may name spares. They are the same
    # picture, so they share the primary's id and cache file.
    data = b""
    for attempt in [origin] + list(candidate.get("alternates") or []):
        try:
            data = _origin_bytes(attempt, timeout)
        except Exception as e:
            log(f"Artwork: {attempt} unavailable ({e})")
            continue
        if data:
            break
    if not data:
        return None
    try:
        candidate["path"] = _store(conf_dir, candidate["id"], data)
    except (ArtworkError, OSError) as e:
        log(f"Artwork: {e}")
        return None
    return candidate


# --------------------------------------------------------------------------
# The sources


def _steam_local(steam_root: str, appid: str) -> List[Dict[str, Any]]:
    """Artwork Steam has already downloaded for this machine."""
    if not (steam_root and str(appid).isdigit()):
        return []
    librarycache = os.path.join(steam_root, "appcache", "librarycache")
    if not os.path.isdir(librarycache):
        return []

    # stem -> path, for every file that belongs to this appid under either layout.
    by_stem: Dict[str, str] = {}

    def offer(path: str, stem: str):
        if stem not in by_stem and os.path.isfile(path):
            by_stem[stem] = path

    for entry in _listdir(librarycache):
        stem, extension = os.path.splitext(entry)
        if extension.lower() in _LOCAL_EXTENSIONS and stem.startswith(f"{appid}_"):
            offer(os.path.join(librarycache, entry), stem[len(appid) + 1:])

    per_app = os.path.join(librarycache, str(appid))
    for entry in _listdir(per_app):
        path = os.path.join(per_app, entry)
        stem, extension = os.path.splitext(entry)
        if extension.lower() in _LOCAL_EXTENSIONS:
            offer(path, stem)
            continue
        # The content-hash directories, one asset each.
        for nested in _listdir(path):
            nested_stem, nested_extension = os.path.splitext(nested)
            if nested_extension.lower() in _LOCAL_EXTENSIONS:
                offer(os.path.join(path, nested), nested_stem)

    found, labelled = [], set()
    for stem, label in _LOCAL_ASSET_LABELS:
        # One entry per kind of picture: a machine with both layouts has the
        # portrait twice, and offering it twice is just noise on the page.
        if stem not in by_stem or label in labelled:
            continue
        labelled.add(label)
        origin = by_stem[stem]
        found.append({"id": candidate_id(origin), "source": "steam-local",
                      "label": label, "origin": origin})
    return found


def _steam_cdn(appid: str) -> List[Dict[str, Any]]:
    """Artwork as Valve publishes it today.

    This is the one that matters after a game is rebranded or re-released: the
    local cache and our own images directory both keep whatever was current when
    the game was first seen, and neither ever refreshes.
    """
    if not str(appid).isdigit():
        return []
    found = []
    for asset, label in _CDN_ASSETS:
        # One host per asset. They serve the same bytes; trying all three would
        # triple the requests to offer the same picture three times.
        origin = _CDN_HOSTS[0].format(appid=appid, asset=asset)
        found.append({"id": candidate_id(origin), "source": "steam-cdn",
                      "label": label, "origin": origin,
                      "alternates": [h.format(appid=appid, asset=asset)
                                     for h in _CDN_HOSTS[1:]]})
    return found


def _sgdb_json(path: str, key: str, timeout: int) -> Any:
    url = f"{_SGDB_BASE}{path}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _sgdb(name: str, appid: str, key: str, timeout: int,
          limit: int = SGDB_LIMIT) -> Tuple[List[Dict[str, Any]], str]:
    """Community artwork. Returns (candidates, note explaining any shortfall)."""
    if not key:
        return [], ("SteamGridDB is not configured. Run sunshine-import "
                    "--save-sgdb-key to add a key and community artwork appears here.")

    def grids(endpoint: str) -> List[Dict[str, Any]]:
        try:
            doc = _sgdb_json(endpoint, key, timeout)
        except Exception as e:
            log(f"Artwork: SteamGridDB {endpoint} failed ({e})")
            return []
        data = doc.get("data") if isinstance(doc, dict) else None
        return data if isinstance(data, list) else []

    items: List[Dict[str, Any]] = []
    if str(appid).isdigit():
        items = grids(f"/grids/steam/{appid}?dimensions=600x900")
        if not items:
            items = grids(f"/grids/steam/{appid}")
    if not items and name:
        search = grids(f"/search/autocomplete/{urllib.parse.quote(name)}")
        if search:
            game_id = search[0].get("id")
            if game_id:
                items = (grids(f"/grids/game/{game_id}?dimensions=600x900")
                         or grids(f"/grids/game/{game_id}"))

    if not items:
        return [], "SteamGridDB has no artwork for this one."

    items.sort(key=lambda item: item.get("score") or 0, reverse=True)
    found = []
    for item in items[:limit]:
        origin = item.get("url") or ""
        if not origin:
            continue
        author = ((item.get("author") or {}).get("name")
                  if isinstance(item.get("author"), dict) else "")
        found.append({"id": candidate_id(origin), "source": "sgdb",
                      "label": f"by {author}" if author else "SteamGridDB",
                      "origin": origin})
    return found, ""


# --------------------------------------------------------------------------
# The entry points


def find_candidates(conf_dir: str, *, name: str = "", source: str = "",
                    ident: str = "", steam_root: str = "", sgdb_key: str = "",
                    sgdb_enable: bool = True, timeout: int = 8,
                    workers: int = 8) -> Dict[str, Any]:
    """Every piece of artwork on offer for one app, each cached and ready.

    *source* and *ident* are the ownership marker's: a "steam" entry carries its
    appid, which unlocks both Valve's CDN and SteamGridDB's Steam lookup. An
    entry without one is searched for by name.
    """
    prune_cache(conf_dir)

    appid = str(ident or "") if source == "steam" else ""
    notes: List[str] = []

    wanted: List[Dict[str, Any]] = []
    wanted += _steam_local(steam_root, appid)
    wanted += _steam_cdn(appid)
    if sgdb_enable:
        sgdb_found, note = _sgdb(name, appid, sgdb_key, timeout)
        wanted += sgdb_found
        if note:
            notes.append(note)

    if not wanted:
        return {"candidates": [], "notes": notes or [
            "Nothing to suggest for this app. Browse for a file instead."]}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        fetched = list(pool.map(
            lambda c: _fetch_candidate(conf_dir, c, timeout), wanted))

    # Order follows `wanted`, which is the order a person wants to see: what is
    # already on this machine, then what Valve has now, then community art.
    candidates = [c for c in fetched if c]
    if not candidates and not notes:
        notes.append("None of the artwork sources answered. Check the network, "
                     "or browse for a file.")
    return {"candidates": candidates, "notes": notes}


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "art").strip()).strip("-")
    return (cleaned or "art")[:64]


def choose_artwork(conf_dir: str, chosen_id: str, name: str = "") -> str:
    """Copy a cached candidate into the images tree. Returns its image-path.

    The destination is ours to decide -- the front end sends an id, never a
    path, so there is nothing to sanitise. It lands beside the generated art but
    in its own directory, because a rescan regenerates the generated files and
    must not overwrite something chosen by hand.
    """
    if not re.fullmatch(r"[0-9a-f]{16}", chosen_id or ""):
        raise ArtworkError("That is not a candidate id.")
    cached = os.path.join(cache_dir(conf_dir), f"{chosen_id}.png")
    if not os.path.isfile(cached):
        raise ArtworkError("That artwork is no longer cached. Search again.")

    destination_dir = chosen_dir(conf_dir)
    os.makedirs(destination_dir, exist_ok=True)
    destination = os.path.join(destination_dir, f"{_slug(name)}-{chosen_id}.png")
    shutil.copyfile(cached, destination)
    os.utime(cached, None)
    return destination


# --------------------------------------------------------------------------
# The SteamGridDB key

SGDB_KEY_FILE = ".bsm-sgdb-key"


def load_sgdb_key(conf_dir: str) -> str:
    """The key from the environment, else a mode-600 file, else "".

    The parent project takes it as --sgdb-key, which puts it in ps output and
    shell history. Storing it means the front end never has to ask, and nothing
    has to carry it around.
    """
    from_env = os.getenv("SGDB_API_KEY", "").strip()
    if from_env:
        return from_env
    path = os.path.join(conf_dir, SGDB_KEY_FILE)
    if not os.path.isfile(path):
        return ""
    private, why = filemode.check_private(path)
    if not private:
        log(f"Ignoring {path}: {why}")
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def save_sgdb_key(conf_dir: str, key: str) -> str:
    """Check the key works, then write it mode-600. Returns the path written."""
    key = (key or "").strip()
    if not key:
        raise ArtworkError("No key given")
    try:
        # Half-Life 2. Any real appid does; this one is not going anywhere.
        _sgdb_json("/grids/steam/220?limit=1", key, 10)
    except Exception as e:
        raise ArtworkError(f"SteamGridDB did not accept that key: {e}") from e
    path = os.path.join(conf_dir, SGDB_KEY_FILE)
    filemode.write_private(path, key + "\n")
    return path
