# SPDX-License-Identifier: GPL-3.0-or-later
"""Applying manual changes to apps.json.

The front end queues operations and sends them here rather than writing
apps.json itself. Two writers to a file carrying ownership markers, a managed
list and tombstones would eventually disagree; this keeps one implementation of
those rules, next to the reconciler that defines them.

Operations are positional because Sunshine's own apps have no stable id, so each
one carries the name it expects to find and is refused if the file has moved
underneath it.
"""

import copy
import time
from typing import Any, Dict, List, Tuple

from .backups import load as load_backup
from .reconcile import MARKER, identity, selector
from .utils import log

# Keys the front end may set. Anything else is ignored rather than written
# through, so a malformed request cannot inject arbitrary structure.
EDITABLE = (
    "name", "cmd", "working-dir", "image-path", "output",
    "detached", "prep-cmd", "elevated", "auto-detach", "wait-all",
    "exit-timeout", "exclude-global-prep-cmd",
)


class MutateError(ValueError):
    """An operation could not be applied to the file as it stands."""


def _find(apps: List[Dict[str, Any]], op: Dict[str, Any]) -> int:
    """Locate the entry an operation refers to, or raise."""
    index = op.get("index")
    expected = op.get("name")
    if isinstance(index, int) and 0 <= index < len(apps):
        if expected is None or apps[index].get("name") == expected:
            return index
    # The file moved under us. Fall back to an unambiguous name match.
    if expected is not None:
        matches = [i for i, a in enumerate(apps) if a.get("name") == expected]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise MutateError(f"{expected!r} matches more than one entry; reopen the list")
    raise MutateError(f"{expected or index!r} is no longer where it was; reopen the list")


# Sunshine reads these with a type in mind. getApps() runs std::stoi over the
# integer ones and throws if the value is a string it cannot parse, which makes
# its whole configuration API answer 400 -- so an empty box in a form must not
# reach the file as "".
_INTEGER_FIELDS = ("exit-timeout",)
_BOOLEAN_FIELDS = ("elevated", "auto-detach", "wait-all", "exclude-global-prep-cmd")


def _coerce(key: str, value: Any) -> Any:
    if key in _BOOLEAN_FIELDS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if key in _INTEGER_FIELDS:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return None          # drop it rather than write an unparseable ""
        try:
            return int(text)
        except ValueError:
            raise MutateError(f"{key} must be a whole number, not {text!r}")
    return value


def _clean(fields: Any) -> Dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    cleaned = {}
    for key, value in fields.items():
        if key not in EDITABLE:
            continue
        coerced = _coerce(key, value)
        if coerced is None and key in _INTEGER_FIELDS:
            continue
        cleaned[key] = coerced
    return cleaned


def apply_ops(payload: Dict[str, Any],
              ops: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Apply *ops* to a parsed apps.json. Returns (payload, per-op results)."""
    payload = copy.deepcopy(payload)
    apps = payload.get("apps")
    if not isinstance(apps, list):
        apps = []
    payload["apps"] = apps
    meta = payload.setdefault("meta", {})
    managed = meta.get("managed") if isinstance(meta.get("managed"), list) else []
    removed = meta.get("removed") if isinstance(meta.get("removed"), list) else []

    results = []
    for op in ops:
        kind = str(op.get("op", ""))
        try:
            if kind == "adopt":
                # An entry the importer discovered, written exactly as it would
                # have written it: ownership marker intact, registered as
                # managed, so a later scan recognises it instead of duplicating.
                entry = op.get("entry")
                if not isinstance(entry, dict) or not entry.get("name"):
                    raise MutateError("Nothing to adopt")
                # Coerce here too. This was safe only while adopt entries came
                # straight from the importer; once a front end can edit one
                # before it is applied, form strings reach this path and an
                # exit-timeout of "" makes Sunshine's whole API answer 400.
                entry = dict(entry)
                for field, value in list(entry.items()):
                    if field in _INTEGER_FIELDS or field in _BOOLEAN_FIELDS:
                        coerced = _coerce(field, value)
                        if coerced is None:
                            del entry[field]
                        else:
                            entry[field] = coerced
                ident = identity(entry)
                if ident is None:
                    raise MutateError(f"{entry.get('name')!r} has no ownership marker")
                key = selector(ident)
                existing = next((i for i, a in enumerate(apps)
                                 if identity(a) == ident), None)
                if existing is None:
                    apps.append(dict(entry))
                else:
                    apps[existing] = dict(entry)
                if key not in managed:
                    managed.append(key)
                removed = [t for t in removed
                           if f"{t.get('source')}:{t.get('id')}" != key]
                results.append({"op": kind, "ok": True, "name": entry["name"]})

            elif kind == "rollback":
                # Put a kept copy back, whole. Not expressible as per-entry
                # edits: what makes a copy worth keeping is that it also holds
                # the managed list and the tombstones, and those are the part
                # you cannot reconstruct by looking at the apps.
                #
                # Distinct from "restore", which un-hides one entry. This
                # replaces the file.
                name = str(op.get("backup", ""))
                try:
                    restored = load_backup(name)
                except ValueError as e:
                    # MutateError is a ValueError, but not the other way round,
                    # so this would otherwise escape the per-op handler and take
                    # the whole batch down with it.
                    raise MutateError(str(e)) from e
                apps = restored.get("apps")
                apps = apps if isinstance(apps, list) else []
                payload = copy.deepcopy(restored)
                payload["apps"] = apps
                meta = payload.setdefault("meta", {})
                managed = meta.get("managed") if isinstance(meta.get("managed"), list) else []
                removed = meta.get("removed") if isinstance(meta.get("removed"), list) else []
                results.append({"op": kind, "ok": True, "name": name,
                                "apps": len(apps)})

            elif kind == "suppress":
                # Refusing something a scan offered, before it ever exists in
                # the file. hide cannot do this: there is no entry to remove.
                source, ident_id = str(op.get("source", "")), str(op.get("id", ""))
                if not source or not ident_id:
                    raise MutateError("Nothing to suppress")
                key = f"{source}:{ident_id}"
                if any(f"{t.get('source')}:{t.get('id')}" == key for t in removed):
                    raise MutateError(f"{op.get('name') or key} is already hidden")
                grave = {"name": op.get("name"), "source": source, "id": ident_id,
                         "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                if op.get("image-path"):
                    grave["image-path"] = op["image-path"]
                removed.append(grave)
                results.append({"op": kind, "ok": True, "name": op.get("name")})

            elif kind == "add":
                entry = _clean(op.get("fields"))
                if not entry.get("name"):
                    raise MutateError("A new application needs a name")
                apps.append(entry)
                results.append({"op": kind, "ok": True, "name": entry["name"]})

            elif kind == "edit":
                i = _find(apps, op)
                apps[i].update(_clean(op.get("fields")))
                results.append({"op": kind, "ok": True, "name": apps[i].get("name")})

            elif kind == "clone":
                i = _find(apps, op)
                entry = {k: v for k, v in copy.deepcopy(apps[i]).items() if k != MARKER}
                entry.update(_clean(op.get("fields")))
                if not entry.get("name"):
                    raise MutateError("A copy needs a name")
                # Unmarked on purpose: a copy is the user's, not the importer's,
                # so the importer will never touch or reclaim it.
                apps.insert(i + 1, entry)
                results.append({"op": kind, "ok": True, "name": entry["name"]})

            elif kind in ("delete", "hide"):
                i = _find(apps, op)
                entry = apps.pop(i)
                ident = identity(entry)
                if ident:
                    key = selector(ident)
                    managed = [m for m in managed if m != key]
                    if kind == "hide":
                        grave = {"name": entry.get("name"), "source": ident[0],
                                 "id": ident[1],
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                 # Keep the whole entry so un-hiding can put it
                                 # back directly, rather than clearing the
                                 # tombstone and waiting for a scan to notice.
                                 "entry": copy.deepcopy(entry)}
                        if entry.get("image-path"):
                            grave["image-path"] = entry["image-path"]
                        removed = [t for t in removed
                                   if f"{t.get('source')}:{t.get('id')}" != key]
                        removed.append(grave)
                elif kind == "hide":
                    # Nothing generated it, so nothing would bring it back and
                    # there is nothing to record against.
                    raise MutateError(
                        f"{entry.get('name')!r} was not created by the importer, "
                        f"so hiding it is the same as deleting it")
                results.append({"op": kind, "ok": True, "name": entry.get("name")})

            elif kind == "restore":
                key = str(op.get("selector", ""))
                grave = next((t for t in removed
                              if f"{t.get('source')}:{t.get('id')}" == key), None)
                if grave is None:
                    raise MutateError(f"{key} is not hidden")
                removed = [t for t in removed if t is not grave]
                restored = grave.get("entry")
                if isinstance(restored, dict) and restored.get("name"):
                    if not any(identity(a) == identity(restored) for a in apps):
                        apps.append(copy.deepcopy(restored))
                    if key not in managed and identity(restored):
                        managed.append(key)
                results.append({"op": kind, "ok": True,
                                "name": grave.get("name") or key})

            else:
                raise MutateError(f"Unknown operation {kind!r}")

        except MutateError as e:
            log(f"Skipped {kind}: {e}")
            results.append({"op": kind, "ok": False, "error": str(e),
                            "name": op.get("name")})

    meta["managed"] = managed
    meta["removed"] = removed
    return payload, results
