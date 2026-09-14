"""Queued changes and preferences, kept per user outside the config.

Changes are queued rather than written as you make them, so a session of edits
becomes one write and one Sunshine reload -- which matters here, because a
reload ends any stream in progress. Ten edits should cost one disconnect, not
ten.
"""

import json
import os
import tempfile
from typing import Any, Dict, List

QUEUE_FILE = "queue.json"
PREFS_FILE = "prefs.json"

# Operations destructive enough to explain before doing, until told not to.
EXPLAINED = ("hide", "delete")


def state_dir() -> str:
    base = os.getenv("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = os.path.join(base, "sunshine-apps-ui")
    os.makedirs(path, exist_ok=True)
    return path


def _read(name: str, default: Any) -> Any:
    try:
        with open(os.path.join(state_dir(), name), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _write(name: str, value: Any) -> None:
    directory = state_dir()
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
        os.replace(tmp, os.path.join(directory, name))
    except Exception:
        os.path.exists(tmp) and os.unlink(tmp)
        raise


def queue() -> List[Dict[str, Any]]:
    value = _read(QUEUE_FILE, [])
    return value if isinstance(value, list) else []


def enqueue(op: Dict[str, Any]) -> List[Dict[str, Any]]:
    pending = queue()
    pending.append(op)
    _write(QUEUE_FILE, pending)
    return pending


def clear_queue() -> None:
    _write(QUEUE_FILE, [])


def drop(position: int) -> List[Dict[str, Any]]:
    pending = queue()
    if 0 <= position < len(pending):
        pending.pop(position)
        _write(QUEUE_FILE, pending)
    return pending


def stage_plan(plan: Dict[str, Any]) -> int:
    """Turn a scan's findings into queued changes, on the grid where they show.

    Anything already queued for the same entry wins: a scan should not quietly
    undo a decision you have already made and can see.
    """
    pending = queue()
    claimed = set()
    for op in pending:
        source, ident = op.get("source"), op.get("id")
        if source and ident:
            claimed.add(f"{source}:{ident}")
        entry = op.get("entry") or {}
        marker = entry.get("bsm") or {}
        if marker.get("source"):
            claimed.add(f"{marker['source']}:{marker.get('id')}")
        if op.get("name"):
            claimed.add(str(op["name"]))

    added = 0
    for found in plan.get("added") or []:
        key = f"{found.get('source')}:{found.get('id')}"
        if key in claimed or found.get("name") in claimed or not found.get("entry"):
            continue
        pending.append({"op": "adopt", "entry": found["entry"],
                        "name": found.get("name"),
                        "source": found.get("source"), "id": found.get("id"),
                        "from_scan": True})
        claimed.add(key)
        added += 1

    for changed in plan.get("updated") or []:
        key = f"{changed.get('source')}:{changed.get('id')}"
        if key in claimed or not changed.get("entry"):
            continue
        pending.append({"op": "adopt", "entry": changed["entry"],
                        "name": changed.get("name"),
                        "source": changed.get("source"), "id": changed.get("id"),
                        "fields": changed.get("fields"), "from_scan": True})
        claimed.add(key)
        added += 1

    if added:
        _write(QUEUE_FILE, pending)
    return added


def prefs() -> Dict[str, Any]:
    value = _read(PREFS_FILE, {})
    return value if isinstance(value, dict) else {}


def should_explain(op: str) -> bool:
    """Explain by default; only silence for an operation once asked to."""
    if op not in EXPLAINED:
        return False
    return bool(prefs().get(f"explain_{op}", True))


def set_explain(op: str, value: bool) -> None:
    current = prefs()
    current[f"explain_{op}"] = bool(value)
    _write(PREFS_FILE, current)
