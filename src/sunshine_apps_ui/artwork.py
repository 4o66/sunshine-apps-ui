"""Serving the artwork that apps.json refers to.

Only paths that actually appear in the current apps.json or its tombstones are
served. The allowlist is rebuilt from the state document on every request, so
this cannot be walked: an arbitrary path is not refused by inspecting it for
"..", it simply is not in the set.
"""

import mimetypes
import os
from typing import Any, Dict, List, Optional, Set

# Relative image-paths (Sunshine's own defaults use them) resolve against the
# directory it ships its assets in.
_ASSET_DIRS = ("/usr/share/sunshine", "/usr/local/share/sunshine")

_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_BYTES = 8 * 1024 * 1024


def resolve(image_path: str) -> str:
    """Absolute path for an image-path as written in apps.json, or ""."""
    if not image_path:
        return ""
    if os.path.isabs(image_path):
        return image_path if os.path.isfile(image_path) else ""
    for base in _ASSET_DIRS:
        candidate = os.path.join(base, image_path)
        if os.path.isfile(candidate):
            return candidate
    return ""


# Artwork the importer caches for the picker: candidates it has fetched, and
# covers already chosen. Both directories hold nothing but images this tool put
# there, and both are read as a list of filenames rather than matched as a path
# prefix, so the allowlist stays an exact set.
_CACHE_DIRS = (os.path.join("images", ".candidates"),
               os.path.join("images", "chosen"))


def _cached_artwork(config_dir: str) -> Set[str]:
    paths = set()
    for relative in _CACHE_DIRS:
        directory = os.path.join(config_dir, relative)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        paths.update(os.path.join(directory, name) for name in names)
    return paths


def allowed_paths(state: Dict[str, Any],
                  pending: Optional[List[Dict[str, Any]]] = None) -> Set[str]:
    """Every image-path the interface may legitimately show.

    That is the current configuration *and* anything queued but not yet applied:
    a game a scan has just staged is in neither apps.json nor its tombstones, so
    leaving the queue out means every newly found tile shows a broken image.
    Artwork being chosen is in neither, either -- a candidate has been fetched
    but nothing refers to it until someone picks it.
    """
    paths = set()
    config_dir = str(state.get("config_dir") or "")
    if config_dir:
        paths |= _cached_artwork(config_dir)
    for group in ("apps", "hidden"):
        for entry in state.get(group) or []:
            if isinstance(entry, dict) and entry.get("image-path"):
                paths.add(str(entry["image-path"]))

    for op in pending or []:
        if not isinstance(op, dict):
            continue
        for source in (op.get("entry"), op.get("fields"), op):
            if isinstance(source, dict) and source.get("image-path"):
                paths.add(str(source["image-path"]))
    return paths


def read(image_path: str, allowed: Set[str]) -> Optional[tuple]:
    """Return (bytes, content_type) if this is a referenced image, else None."""
    if image_path not in allowed:
        return None
    resolved = resolve(image_path)
    if not resolved:
        return None
    content_type, _ = mimetypes.guess_type(resolved)
    if content_type not in _ALLOWED_TYPES:
        return None
    try:
        if os.path.getsize(resolved) > MAX_BYTES:
            return None
        with open(resolved, "rb") as handle:
            return handle.read(), content_type
    except OSError:
        return None
