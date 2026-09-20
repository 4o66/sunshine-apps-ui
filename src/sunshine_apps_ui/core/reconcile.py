# SPDX-License-Identifier: GPL-3.0-or-later
"""Three-way reconcile of generated apps into an existing apps.json.

The importer used to rewrite apps.json from scratch on every run, which deleted
anything the user had added through Sunshine's web UI, including the defaults
Sunshine ships with. This module merges instead, by tracking which entries and
which individual fields the importer owns.

Ownership is recorded inline, in a "bsm" key on each generated app. That is safe
because Sunshine round-trips unknown keys: confighttp.cpp parses apps.json into a
generic JSON DOM, replaces only the element being edited, and re-dumps the whole
tree, and the web UI deep-clones an app before editing it. Entries we did not
create are never touched.
"""

import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .utils import log

MARKER = "bsm"
MARKER_VERSION = 1

# Sunshine's saveApp() erases these keys when their value is empty, so an absent
# key and an empty one are the same state and must hash identically. Without
# this, one save in the web UI makes every entry look user-edited.
_EMPTY_EQUIV = ("prep-cmd", "detached")

Identity = Tuple[str, str]


def _normalized(key: str, value: Any) -> Any:
    if key in _EMPTY_EQUIV and not value:
        return None
    return value


def field_hash(key: str, value: Any) -> str:
    """Hash a normalized field *value*, never its serialized form.

    Sunshine re-dumps apps.json with keys sorted and 4-space indent, and getApps()
    coerces legacy string booleans to real booleans, so hashing text would report
    spurious edits.
    """
    blob = json.dumps(_normalized(key, value), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def tag(app: Dict[str, Any], source: str, ident: Any) -> Dict[str, Any]:
    """Return *app* with an ownership marker recording every field we set."""
    tagged = {k: v for k, v in app.items() if k != MARKER}
    tagged[MARKER] = {
        "v": MARKER_VERSION,
        "source": source,
        "id": str(ident),
        "fields": {k: field_hash(k, v) for k, v in tagged.items()},
    }
    return tagged


def identity(app: Dict[str, Any]) -> Optional[Identity]:
    m = app.get(MARKER)
    if isinstance(m, dict) and m.get("source") and m.get("id") is not None:
        return (str(m["source"]), str(m["id"]))
    return None


def _recorded_hashes(app: Dict[str, Any]) -> Dict[str, str]:
    m = app.get(MARKER)
    if isinstance(m, dict) and isinstance(m.get("fields"), dict):
        return m["fields"]
    return {}


def _forced(ident: Identity, refresh: Optional[Sequence[str]]) -> bool:
    if not refresh:
        return False
    if "all" in refresh:
        return True
    return f"{ident[0]}:{ident[1]}" in refresh


def _merge(cur: Dict[str, Any], want: Dict[str, Any], ident: Identity,
           forced: bool) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
    recorded = _recorded_hashes(cur)
    merged = {k: v for k, v in cur.items() if k != MARKER}
    marker_fields: Dict[str, str] = {}
    changed: List[str] = []
    diverged: List[Dict[str, Any]] = []

    for key, new_value in want.items():
        if key == MARKER:
            continue
        cur_value = cur.get(key)
        cur_h = field_hash(key, cur_value)
        new_h = field_hash(key, new_value)
        was = recorded.get(key)
        # The user owns this field if it no longer matches what we last wrote.
        user_owned = was is not None and cur_h != was

        if user_owned and not forced:
            if new_h == cur_h:
                marker_fields[key] = new_h       # converged; ours again
            else:
                diverged.append({"field": key, "current": cur_value, "would_be": new_value})
                marker_fields[key] = was         # keep flagging it every run
            continue

        if cur_h != new_h:
            merged[key] = new_value
            changed.append(key)
        marker_fields[key] = new_h

    merged[MARKER] = {
        "v": MARKER_VERSION,
        "source": ident[0],
        "id": ident[1],
        "fields": marker_fields,
    }
    return merged, changed, diverged


def selector(ident: Identity) -> str:
    return f"{ident[0]}:{ident[1]}"


def _selected(ident: Identity, selectors: Optional[Sequence[str]]) -> bool:
    if not selectors:
        return False
    return "all" in selectors or selector(ident) in selectors


def reconcile(existing: List[Dict[str, Any]], desired: List[Dict[str, Any]],
              adopt_by_name: bool = False,
              former_names: Optional[Dict[str, Identity]] = None,
              refresh: Optional[Sequence[str]] = None,
              previously_managed: Optional[Sequence[str]] = None,
              tombstones: Optional[List[Dict[str, Any]]] = None,
              prunable_sources: Optional[Sequence[str]] = None,
              restore_removed: Optional[Sequence[str]] = None,
              ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Merge *desired* generated apps into the *existing* app list.

    Returns (apps, plan). Entries without one of our markers are passed through
    untouched. Generated entries no longer present in *desired* are reported as
    "missing" but kept: removing them is a separate, opt-in behaviour.
    """
    plan: Dict[str, Any] = {
        "added": [], "updated": [], "unchanged": [],
        "diverged": [], "missing": [], "kept_foreign": [],
        "removed_by_user": [], "suppressed": [], "pruned": [], "restored": [],
    }

    was_managed = set(previously_managed or ())
    prunable = set(prunable_sources or ())
    graves: Dict[str, Dict[str, Any]] = {
        f"{t.get('source')}:{t.get('id')}": dict(t)
        for t in (tombstones or []) if isinstance(t, dict)
    }
    for key in list(graves):
        src, _, gid = key.partition(":")
        if _selected((src, gid), restore_removed):
            plan["restored"].append(graves.pop(key))

    by_id: Dict[Identity, Dict[str, Any]] = {}
    for app in desired:
        ident = identity(app)
        if ident is None:
            raise ValueError(f"desired app {app.get('name')!r} has no ownership marker")
        by_id[ident] = app

    name_to_id = {a.get("name"): i for i, a in by_id.items()}
    # Names we used to write. An entry from before ownership markers existed is
    # claimed by its name, so renaming a generated tile would disown every copy
    # already out there and add a second one beside it. "Zz Reboot" became
    # "Zz Reboot Host" on 2026-09-19; this is what keeps the old one ours.
    for was, ident in (former_names or {}).items():
        name_to_id.setdefault(was, ident)
    out: List[Dict[str, Any]] = []
    claimed = set()

    for cur in existing:
        if not isinstance(cur, dict):
            out.append(cur)
            continue
        ident = identity(cur)
        if ident is None and adopt_by_name:
            ident = name_to_id.get(cur.get("name"))

        if ident is None:
            plan["kept_foreign"].append({"name": cur.get("name")})
            out.append(cur)
            continue
        if ident not in by_id:
            entry = {"name": cur.get("name"), "source": ident[0], "id": ident[1]}
            if ident[0] in prunable:
                plan["pruned"].append(entry)
                continue
            plan["missing"].append(entry)
            out.append(cur)
            continue
        if ident in claimed:
            # A second entry claiming the same id is what Sunshine's web UI
            # produces when you duplicate an app: it deep-clones the marker too.
            # That copy is the user's, so hand it over rather than deleting it --
            # dropping an entry someone deliberately made is never the right call.
            adopted = {k: v for k, v in cur.items() if k != MARKER}
            out.append(adopted)
            plan["kept_foreign"].append({"name": adopted.get("name"), "adopted_copy": True})
            continue

        claimed.add(ident)
        merged, changed, diverged = _merge(cur, by_id[ident], ident, _forced(ident, refresh))
        out.append(merged)
        if diverged:
            plan["diverged"].append({"name": merged.get("name"), "source": ident[0],
                                     "id": ident[1], "fields": diverged})
        if changed:
            plan["updated"].append({"name": merged.get("name"), "source": ident[0],
                                    "id": ident[1], "fields": changed,
                                    "values": {k: merged.get(k) for k in changed},
                                    "entry": dict(merged)})
        elif not diverged:
            plan["unchanged"].append({"name": merged.get("name"), "source": ident[0],
                                      "id": ident[1]})

    for ident, app in by_id.items():
        if ident in claimed:
            continue
        key = selector(ident)
        entry = {"name": app.get("name"), "source": ident[0], "id": ident[1]}

        if key in graves:
            plan["suppressed"].append(entry)
            continue

        if key in was_managed:
            # We wrote this last run and it is no longer here, so the user
            # deleted it. Record that rather than quietly recreating it.
            grave = dict(entry)
            grave["at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            # Keep the artwork so a hidden entry can still be shown as one,
            # rather than as a blank tile with a name under it.
            if app.get("image-path"):
                grave["image-path"] = app["image-path"]
            graves[key] = grave
            plan["removed_by_user"].append(grave)
            continue

        out.append(dict(app))
        # Carry the whole entry, marker included. A front end that stages this
        # for the user to approve has to write back exactly what the importer
        # would have written, or the next scan finds it missing and re-adds it.
        plan["added"].append(dict(entry, entry=dict(app)))

    plan["tombstones"] = sorted(graves.values(),
                                key=lambda t: (str(t.get("source")), str(t.get("id"))))
    plan["managed"] = sorted(selector(identity(a)) for a in out
                             if isinstance(a, dict) and identity(a) is not None)
    return out, plan


def log_plan(plan: Dict[str, Any]) -> None:
    log(f"Reconcile: {len(plan['added'])} added, {len(plan['updated'])} updated, "
        f"{len(plan['unchanged'])} unchanged, {len(plan['diverged'])} edited by you, "
        f"{len(plan['missing'])} no longer found, {len(plan.get('pruned', []))} removed, "
        f"{len(plan.get('suppressed', []))} suppressed, {len(plan['kept_foreign'])} not ours")
    for entry in plan["diverged"]:
        fields = ", ".join(f["field"] for f in entry["fields"])
        log(f"  kept your edits to {entry['name']!r} ({fields}); "
            f"use --refresh-edited {entry['source']}:{entry['id']} to overwrite")
    for entry in plan["missing"]:
        log(f"  {entry['name']!r} was imported before but is not installed now; left in place")
    for entry in plan.get("pruned", []):
        log(f"  removed {entry['name']!r}: no longer installed")
    for entry in plan.get("removed_by_user", []):
        log(f"  {entry['name']!r} was deleted by you and will not be recreated "
            f"(--restore-removed {entry['source']}:{entry['id']} to undo)")
    for entry in plan.get("suppressed", []):
        log(f"  skipping {entry['name']!r}: you removed it previously")
    for entry in plan.get("restored", []):
        log(f"  restoring {entry.get('name')!r}: removal undone")


SCHEMA_VERSION = 1


def plan_document(plan: Dict[str, Any], *, config_dir: str, apps_json: str,
                  sources: List[Dict[str, Any]], dry_run: bool,
                  generator_version: str, fork: str = "",
                  upstream: str = "") -> Dict[str, Any]:
    """Serialize a reconcile *plan* as the versioned document other tools consume.

    Consumers should reject a schema version they do not know rather than guess.
    """
    return {
        "schema": SCHEMA_VERSION,
        # Which fork, and which upstream it was built on. A plan document is
        # what gets pasted into a bug report, and "bazzite-sunshine-manager 2.0"
        # on its own does not say whose.
        "generator": {"name": "bazzite-sunshine-manager",
                      "version": generator_version,
                      **({"fork": fork} if fork else {}),
                      **({"upstream": upstream} if upstream else {})},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dry_run": dry_run,
        "config_dir": config_dir,
        "apps_json": apps_json,
        "sources": sources,
        "totals": {key: len(plan.get(key, ())) for key in
                   ("added", "updated", "unchanged", "diverged", "missing",
                    "kept_foreign", "removed_by_user", "suppressed", "pruned", "restored")},
        "plan": plan,
    }


def backup(path: str, keep: int = 10) -> str:
    """Copy apps.json aside before writing it. Returns the copy's path.

    Kept as a thin wrapper because every caller writes apps.json and every one
    of them should take a copy first; where those copies live is backups' to
    decide, and it stopped being "next to the original" once there was a way to
    restore one.
    """
    from .backups import capture
    return capture(path, keep)
