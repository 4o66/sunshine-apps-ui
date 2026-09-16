# SPDX-License-Identifier: GPL-3.0-or-later
"""Copies of apps.json, kept so a bad run can be undone.

A copy is taken immediately before every write, which is the only moment that
reliably precedes a mistake. Ten are kept, named for when they were taken.

They live in our own data directory rather than beside apps.json. Sunshine's
config directory is Sunshine's, a drawer full of apps.json.bak-* is noise in it,
and anything we leave there is something a future Sunshine could reasonably
decide to tidy up.

Restoring is not done from here. A copy is a file; putting one back is a change
to apps.json like any other, so it goes through the same path -- previewed on
the grid, applied only when asked, and preceded by a copy of its own. Undoing a
restore is therefore just another restore.
"""

import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

KEEP = 10
_STAMP = "%Y%m%d-%H%M%S"
_PREFIX = "apps-"
_SUFFIX = ".json"

# What the older layout looked like, so it can be swept up and put where it
# belongs rather than left behind in Sunshine's directory.
_LEGACY_PREFIX = "apps.json.bak-"


def backup_dir(create: bool = False) -> str:
    """Where copies are kept. Override with BSM_BACKUP_DIR.

    Under state, not share, and that is not arbitrary. Share is where the
    program is installed, so anything kept there is inside the directory an
    install replaces and an uninstall deletes -- which is the moment you most
    want the copies to still exist. I proved that by deleting ten of them with
    an rsync --delete onto the install directory.
    """
    override = os.getenv("BSM_BACKUP_DIR", "").strip()
    if override:
        directory = os.path.abspath(os.path.expanduser(override))
    else:
        base = os.getenv("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        directory = os.path.join(base, "sunshine-apps-ui", "backups")
    if create:
        os.makedirs(directory, exist_ok=True)
    return directory


def _previous_dir() -> str:
    """Where copies used to be kept, so any still there can be rescued."""
    base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "sunshine-apps-ui", "backups")


def adopt_previous_location(keep: int = KEEP) -> int:
    """Move copies out of the install directory they used to sit in."""
    source = _previous_dir()
    destination = backup_dir()
    if os.path.realpath(source) == os.path.realpath(destination):
        return 0
    try:
        names = sorted(n for n in os.listdir(source) if is_backup(n))
    except OSError:
        return 0
    if not names:
        return 0
    os.makedirs(destination, exist_ok=True)
    moved = 0
    for name in names:
        target = os.path.join(destination, name)
        try:
            if os.path.exists(target):
                os.remove(os.path.join(source, name))
            else:
                shutil.move(os.path.join(source, name), target)
                moved += 1
        except OSError:
            continue
    if moved:
        prune(keep)
    return moved


def _name(when: Optional[float] = None) -> str:
    return _PREFIX + time.strftime(_STAMP, time.localtime(when)) + _SUFFIX


def is_backup(name: str) -> bool:
    """Is this one of ours? Used instead of trusting a name from a request."""
    return (name.startswith(_PREFIX) and name.endswith(_SUFFIX)
            and "/" not in name and "\\" not in name
            and len(name) == len(_PREFIX) + 15 + len(_SUFFIX))


def capture(apps_json: str, keep: int = KEEP) -> str:
    """Copy apps.json aside. Returns the copy's path, or "" if there was none.

    Called before writing, never after: a copy taken afterwards records the
    mistake rather than what preceded it.
    """
    if not os.path.isfile(apps_json):
        return ""
    directory = backup_dir(create=True)
    destination = os.path.join(directory, _name())
    # A second write inside the same second would otherwise overwrite the copy
    # taken by the first, which is the one worth keeping.
    if os.path.exists(destination):
        return destination
    shutil.copy2(apps_json, destination)
    prune(keep)
    return destination


def prune(keep: int = KEEP) -> int:
    """Drop all but the newest *keep* copies. Returns how many were removed."""
    directory = backup_dir()
    try:
        names = sorted(n for n in os.listdir(directory) if is_backup(n))
    except OSError:
        return 0
    removed = 0
    for name in names[:-keep] if keep > 0 else names:
        try:
            os.remove(os.path.join(directory, name))
            removed += 1
        except OSError:
            continue
    return removed


def _describe(directory: str, name: str) -> Dict[str, Any]:
    path = os.path.join(directory, name)
    stamp = name[len(_PREFIX):-len(_SUFFIX)]
    entry: Dict[str, Any] = {"name": name, "path": path, "stamp": stamp}
    try:
        entry["size"] = os.path.getsize(path)
        entry["at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.strptime(stamp, _STAMP))
    except (OSError, ValueError):
        entry["size"], entry["at"] = 0, ""
    # How many apps it holds, so a picker can say what it is rather than only
    # when it was. A copy that will not parse says so instead of being offered
    # as if it were usable.
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        apps = payload.get("apps") if isinstance(payload, dict) else payload
        entry["apps"] = len(apps) if isinstance(apps, list) else 0
        entry["readable"] = True
    except (OSError, json.JSONDecodeError):
        entry["apps"], entry["readable"] = 0, False
    return entry


def list_backups() -> List[Dict[str, Any]]:
    """Every kept copy, newest first."""
    directory = backup_dir()
    try:
        names = sorted((n for n in os.listdir(directory) if is_backup(n)),
                       reverse=True)
    except OSError:
        return []
    return [_describe(directory, n) for n in names]


def load(name: str) -> Dict[str, Any]:
    """Read one copy. Raises ValueError if it is not one of ours or not usable."""
    if not is_backup(name):
        raise ValueError("That is not one of the kept copies.")
    path = os.path.join(backup_dir(), name)
    if not os.path.isfile(path):
        raise ValueError("That copy is no longer there.")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"That copy cannot be read: {e}") from e
    if not isinstance(payload, dict):
        payload = {"apps": payload if isinstance(payload, list) else []}
    return payload


def adopt_legacy(conf_dir: str, keep: int = KEEP) -> int:
    """Move copies made by the old layout out of Sunshine's directory.

    Older versions wrote apps.json.bak-* next to apps.json. They are still
    perfectly good copies, so they are moved rather than discarded -- and
    Sunshine's directory stops accumulating our files.
    """
    moved = 0
    try:
        names = sorted(n for n in os.listdir(conf_dir)
                       if n.startswith(_LEGACY_PREFIX))
    except OSError:
        return 0
    directory = backup_dir(create=True) if names else backup_dir()
    for name in names:
        stamp = name[len(_LEGACY_PREFIX):]
        destination = os.path.join(directory, _PREFIX + stamp + _SUFFIX)
        try:
            if not os.path.exists(destination):
                shutil.move(os.path.join(conf_dir, name), destination)
                moved += 1
            else:
                os.remove(os.path.join(conf_dir, name))
        except OSError:
            continue
    if moved:
        prune(keep)
    return moved


def _key(entry: Dict[str, Any]) -> str:
    """How an app is matched across two versions of the file.

    By ownership marker when there is one, because that survives a rename;
    by name otherwise, because that is all an entry Sunshine or a person
    created has.
    """
    from .reconcile import identity
    ident = identity(entry) if isinstance(entry, dict) else None
    if ident:
        return f"{ident[0]}:{ident[1]}"
    return "name:" + str(entry.get("name", "")) if isinstance(entry, dict) else ""


def _fields(entry: Dict[str, Any]) -> Dict[str, Any]:
    from .reconcile import MARKER
    return {k: v for k, v in entry.items() if k != MARKER}


def compare(current: Dict[str, Any], name: str) -> Dict[str, Any]:
    """What restoring copy *name* would do to *current*.

    Worked out here rather than by a front end: deciding whether two entries
    are the same app is the reconciler's rule, and there should be one of it.
    """
    copy_payload = load(name)

    def index(payload):
        apps = payload.get("apps")
        apps = apps if isinstance(apps, list) else []
        return {_key(a): a for a in apps if isinstance(a, dict)}

    now, then = index(current), index(copy_payload)

    returning = [then[k] for k in then if k not in now]
    going = [now[k] for k in now if k not in then]
    changing = []
    for k in then:
        if k in now and _fields(then[k]) != _fields(now[k]):
            fields = sorted(set(_fields(then[k])) | set(_fields(now[k])))
            differing = [f for f in fields
                         if _fields(now[k]).get(f) != _fields(then[k]).get(f)]
            changing.append({
                # The name it has now, so a front end can find the tile. Naming
                # it by what it would become makes it unfindable in exactly the
                # case where the name is the thing that changes.
                "name": now[k].get("name"),
                "becomes": (then[k].get("name")
                            if then[k].get("name") != now[k].get("name") else None),
                # How the two entries were matched, which survives a rename
                # where a name does not.
                "key": k,
                "fields": differing,
            })

    def meta_list(payload, key):
        meta = payload.get("meta")
        value = meta.get(key) if isinstance(meta, dict) else None
        return value if isinstance(value, list) else []

    return {
        "backup": name,
        "returning": [{"name": a.get("name")} for a in returning],
        "going": [{"name": a.get("name")} for a in going],
        "changing": changing,
        # The part no per-entry view can show, and the reason this is a
        # whole-file operation.
        "hidden_now": len(meta_list(current, "removed")),
        "hidden_then": len(meta_list(copy_payload, "removed")),
        "nothing_to_do": not (returning or going or changing)
                         and meta_list(current, "removed") == meta_list(copy_payload, "removed"),
    }
