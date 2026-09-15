# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything the interface can ask of apps.json, in one place.

This replaces a CLI contract between two projects. The contract existed to keep
them honest about the boundary; with one project it bought a subprocess per
request and two of everything else. The boundary survives as this module:
nothing outside core writes apps.json, and nothing outside core decides what
"the same app" means.

The shapes returned are the shapes the contract returned, because they were
designed for a front end to render and there was no reason to change them.
"""

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import backups as _backups
from . import run as _run
from .artwork_sources import (ArtworkError, choose_artwork, find_candidates,
                              find_steam_root, load_sgdb_key, save_sgdb_key)
from .mutate import MutateError, apply_ops
from .reconcile import MARKER, SCHEMA_VERSION, backup
from .sunshine_api import (SunshineAPIError, SunshineClient, load_credentials,
                           reload_sunshine, save_credentials, verify_credentials)
from .utils import log, read_json, write_json

VERSION = _run.VERSION
UPSTREAM = _run.UPSTREAM

# Files Sunshine itself writes while running. Their mtime is what distinguishes
# a config directory in use from one an uninstalled Flatpak left behind.
_LIVENESS_FILES = ("sunshine.log", "sunshine_state.json", "sunshine.conf")


class CoreError(RuntimeError):
    """Something could not be read, written, or asked of Sunshine."""


def _candidates(home: str) -> List[str]:
    flatpak_ids = ["dev.lizardbyte.app.Sunshine", "dev.lizardbyte.Sunshine"]
    found = [os.path.join(home, ".var", "app", fid, "config", "sunshine")
             for fid in flatpak_ids]
    found.append(os.path.join(home, ".config", "sunshine"))
    return found


def _last_used(conf_dir: str) -> float:
    newest = 0.0
    for name in _LIVENESS_FILES:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(conf_dir, name)))
        except OSError:
            continue
    return newest


def config_dir(home: Optional[str] = None) -> str:
    """Where Sunshine keeps its configuration.

    SUNSHINE_CONF_DIR overrides everything. Otherwise, when more than one
    candidate exists, the one Sunshine used most recently wins rather than the
    first that happens to exist: an uninstalled Flatpak leaves its whole config
    tree behind, and writing to it silently does nothing.
    """
    override = os.getenv("SUNSHINE_CONF_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(override)))

    home = home or str(Path.home())
    existing = [d for d in _candidates(home) if os.path.isdir(d)]
    if not existing:
        return os.path.join(home, ".config", "sunshine")
    if len(existing) == 1:
        return existing[0]

    ranked = sorted(existing, key=_last_used, reverse=True)
    log("Multiple Sunshine config directories found; choosing the most recently used:")
    for directory in ranked:
        stamp = _last_used(directory)
        when = (time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))
                if stamp else "never used")
        log(f"  {'->' if directory == ranked[0] else '  '} {directory}  ({when})")
    return ranked[0]


def apps_json_path(conf_dir: str) -> str:
    return os.path.join(conf_dir, "apps.json")


def _payload(conf_dir: str) -> Dict[str, Any]:
    payload = read_json(apps_json_path(conf_dir), {})
    if not isinstance(payload, dict):
        payload = {"apps": payload if isinstance(payload, list) else []}
    return payload


# ------------------------------------------------------------------ reading ---


def state(conf_dir: str) -> Dict[str, Any]:
    """What is in apps.json now, as opposed to what would change.

    Entries are reported whole. Reporting a summary meant a front end drawing an
    edit form rendered the fields it omitted as empty, and saving that form
    wrote the empties back.
    """
    payload = _payload(conf_dir)
    apps = payload.get("apps")
    apps = apps if isinstance(apps, list) else []
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    entries = []
    for index, app in enumerate(apps):
        if not isinstance(app, dict):
            continue
        marker = app.get(MARKER) if isinstance(app.get(MARKER), dict) else None
        entry = {k: v for k, v in app.items() if k != MARKER}
        entry.update({
            "index": index,
            "name": app.get("name"),
            "image-path": app.get("image-path") or "",
            "cmd": app.get("cmd") or "",
            "source": marker.get("source") if marker else None,
            "id": marker.get("id") if marker else None,
            "managed": marker is not None,
        })
        entries.append(entry)

    return {
        "schema": SCHEMA_VERSION,
        "generator": {"name": "sunshine-apps-ui", "version": VERSION,
                      "upstream": UPSTREAM},
        "config_dir": conf_dir,
        "apps_json": apps_json_path(conf_dir),
        "apps": entries,
        "hidden": [t for t in (meta.get("removed") or []) if isinstance(t, dict)],
    }


def plan(conf_dir: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a scan would change. Writes nothing."""
    options = dict(opts or {})
    options["BSM_DRY_RUN"] = True
    options["BSM_RELOAD"] = False
    return _run.execute(conf_dir, options)


def scan_and_apply(conf_dir: str, opts: Optional[Dict[str, Any]] = None,
                   reload: bool = True) -> Dict[str, Any]:
    """Scan and write. The opposite of plan()."""
    options = dict(opts or {})
    options["BSM_DRY_RUN"] = False
    options["BSM_RELOAD"] = reload
    return _run.execute(conf_dir, options)


# ------------------------------------------------------------------ writing ---


def mutate(conf_dir: str, ops: List[Dict[str, Any]],
           reload: bool = True) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """Apply queued operations. A copy of the file is taken first, always."""
    if not ops:
        return False, "No operations given", []
    path = apps_json_path(conf_dir)
    payload = _payload(conf_dir)
    updated, results = apply_ops(payload, ops)
    failed = [r for r in results if not r.get("ok")]

    if os.path.exists(path):
        try:
            log(f"Backup saved: {backup(path)}")
        except Exception as e:                       # noqa: BLE001 - reported
            log(f"Warning: failed to back up apps.json: {e}")
    write_json(path, updated)

    applied = len(results) - len(failed)
    log(f"Applied {applied} of {len(results)} change(s) to {path}")
    if reload and not failed:
        try:
            reload_sunshine(conf_dir)
        except SunshineAPIError as e:
            return False, f"Written, but Sunshine did not reload: {e}", results
    if failed:
        return False, "; ".join(str(f.get("error")) for f in failed)[:300], results
    return True, f"Applied {applied} change(s)", results


# ------------------------------------------------------------------- copies ---


def list_backups(conf_dir: str) -> List[Dict[str, Any]]:
    """Kept copies, newest first, sweeping up any earlier layout's."""
    moved = _backups.adopt_legacy(conf_dir)
    if moved:
        log(f"Moved {moved} older copy(s) out of {conf_dir}")
    rescued = _backups.adopt_previous_location()
    if rescued:
        log(f"Moved {rescued} copy(s) out of the install directory")
    return _backups.list_backups()


def backup_diff(conf_dir: str, name: str) -> Dict[str, Any]:
    """What restoring one copy would change. Changes nothing."""
    return _backups.compare(_payload(conf_dir), name)


# ------------------------------------------------------------------ browsing ---


def browse(conf_dir: str, path: str = "", kind: str = "any") -> Dict[str, Any]:
    """List a directory, through Sunshine's own file browser."""
    doc = SunshineClient(conf_dir).browse(path, kind)
    doc["ok"] = True
    return doc


# ------------------------------------------------------------------- artwork ---


def art_search(conf_dir: str, name: str = "", source: str = "",
               ident: str = "", home: Optional[str] = None) -> Dict[str, Any]:
    steam_root, _ = find_steam_root(home or str(Path.home()))
    result = find_candidates(
        conf_dir, name=name, source=source, ident=ident, steam_root=steam_root,
        sgdb_key=load_sgdb_key(conf_dir),
        sgdb_enable=str(os.getenv("SGDB_ENABLE", "1")).strip().lower()
                    not in ("0", "false", "no", "off"),
        timeout=int(os.getenv("SGDB_TIMEOUT", "8") or 8))
    return {"ok": True, **result}


def art_choose(conf_dir: str, chosen_id: str, name: str = "") -> str:
    return choose_artwork(conf_dir, chosen_id, name)


# --------------------------------------------------------------- credentials ---


def check_auth(conf_dir: str) -> Tuple[bool, str]:
    try:
        user, password = load_credentials(conf_dir)
        verify_credentials(conf_dir, user, password)
        return True, f"Sunshine accepted the stored credentials for {user!r}."
    except SunshineAPIError as e:
        return False, str(e)


def save_auth(conf_dir: str, username: str, password: str) -> Tuple[bool, str]:
    try:
        path = save_credentials(conf_dir, username, password)
        return True, f"Verified and saved to {path}"
    except SunshineAPIError as e:
        return False, str(e)


def save_sgdb(conf_dir: str, key: str) -> Tuple[bool, str]:
    try:
        return True, f"Verified and saved to {save_sgdb_key(conf_dir, key)}"
    except ArtworkError as e:
        return False, str(e)
