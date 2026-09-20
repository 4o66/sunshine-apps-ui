# SPDX-License-Identifier: GPL-3.0-or-later
"""Sunshine's own default apps: locating them, seeding from them, restoring them.

Sunshine ships an apps.json containing the entries a fresh install starts with
(Desktop, Low Res Desktop, Steam Big Picture). This module implements the
INCLUDE_SYSTEM_APPS and SYSTEM_APPS_JSON settings, which config/README.md has
always documented but nothing read.

These entries are never modified by this tool: they carry no ownership marker,
so the reconciler treats them as foreign and passes them through. What this adds
is putting them back -- on a fresh config, or on request after they were deleted
by an older version of this tool that rewrote apps.json wholesale.
"""

import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .utils import log, read_json

# Where the defaults live, per install type. The Flatpak keeps them inside the
# runtime rather than /usr/share, so looking only at the native path finds
# nothing on a Flatpak-only system.
_SYSTEM_APPS_CANDIDATES = (
    "/usr/share/sunshine/apps.json",
    "/usr/local/share/sunshine/apps.json",
    "/var/lib/flatpak/app/dev.lizardbyte.app.Sunshine/current/active/files/share/sunshine/apps.json",
    "~/.local/share/flatpak/app/dev.lizardbyte.app.Sunshine/current/active/files/share/sunshine/apps.json",
    "/var/lib/flatpak/app/dev.lizardbyte.Sunshine/current/active/files/share/sunshine/apps.json",
    "~/.local/share/flatpak/app/dev.lizardbyte.Sunshine/current/active/files/share/sunshine/apps.json",
)


def _platform_candidates() -> List[str]:
    """The places that are not a fixed path, because they follow the install.

    On Windows the shipped copy sits beside the executable, in the install
    directory -- `assets\\apps.json` next to `config\\apps.json`, which is the
    live one. There is no fixed path for it: Sunshine can be installed
    anywhere, so the install has to be found first, the same way the live
    config is found. Measured on the rig 2026-09-19, where this returned
    nothing and the defaults were reported missing while sitting in
    `C:\\Program Files\\Sunshine\\assets\\apps.json`.

    On macOS the app bundle carries its own, under Resources.
    """
    import sys

    found: List[str] = []
    if os.name == "nt":
        import ntpath

        from .api import _windows_install_dirs

        for directory in _windows_install_dirs():
            found.append(ntpath.join(directory, "assets", "apps.json"))
    elif sys.platform == "darwin":
        found.append("/Applications/Sunshine.app/Contents/Resources/assets/apps.json")
    return found


def find_system_apps_json(override: str = "") -> str:
    """Path to Sunshine's shipped apps.json, or "" if it cannot be found."""
    if override:
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(override)))
        return path if os.path.isfile(path) else ""
    for candidate in list(_SYSTEM_APPS_CANDIDATES) + _platform_candidates():
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return ""


def load_system_apps(path: str) -> List[Dict[str, Any]]:
    if not path:
        return []
    data = read_json(path, {})
    apps = data.get("apps") if isinstance(data, dict) else data
    return [a for a in apps if isinstance(a, dict) and a.get("name")] if isinstance(apps, list) else []


def system_app_names(apps: List[Dict[str, Any]]) -> set:
    return {a.get("name") for a in apps if a.get("name")}


def restore_missing(existing: List[Dict[str, Any]],
                    system_apps: List[Dict[str, Any]],
                    also_present: Optional[Set[str]] = None,
                    ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Prepend any default entry that is absent from *existing*, by name.

    Matching is by name only. An entry you renamed or rewrote is yours, and a
    default of the same name that you edited is left exactly as you have it --
    only wholly absent ones come back.

    *also_present* names defaults that are here under another name, because we
    took them over and renamed them. Without it "Low Res Desktop" looks absent
    the moment it becomes "#2 Low Res Desktop", and restoring it would add a
    second copy of a tile that is already on the grid.
    """
    present = {a.get("name") for a in existing if isinstance(a, dict)}
    present |= set(also_present or ())
    missing = [a for a in system_apps if a.get("name") not in present]
    if not missing:
        return existing, []
    return list(missing) + list(existing), [a.get("name") for a in missing]
