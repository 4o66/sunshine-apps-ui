"""Serving the artwork that apps.json refers to.

Only paths that actually appear in the current apps.json or its tombstones are
served. The allowlist is rebuilt from the state document on every request, so
this cannot be walked: an arbitrary path is not refused by inspecting it for
"..", it simply is not in the set.
"""

import mimetypes
import os
from typing import Any, Dict, Optional, Set

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


def allowed_paths(state: Dict[str, Any]) -> Set[str]:
    """Every image-path the current configuration refers to."""
    paths = set()
    for group in ("apps", "hidden"):
        for entry in state.get(group) or []:
            if isinstance(entry, dict) and entry.get("image-path"):
                paths.add(str(entry["image-path"]))
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
