# SPDX-License-Identifier: GPL-3.0-or-later
"""What the interface asks of apps.json, and the only thing it asks.

Everything here forwards to core, which owns the file. The interface never
imports core directly: keeping one seam means there is still one place to look
when asking "what can the front end actually do", which is the part of the old
two-project split that was worth keeping.

It used to be a subprocess per request, because core was a separate program.
That bought process isolation nobody needed and cost a fork, an interpreter
start and a JSON round trip on every page.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from .core import api
from .core.artwork_sources import ArtworkError
from .core.mutate import MutateError
from .core.sunshine_api import SunshineAPIError


class EngineError(RuntimeError):
    """Something could not be read, written, or asked of Sunshine."""


def _wrap(call, *args, **kwargs):
    """Turn the failures core raises into the one this layer reports."""
    try:
        return call(*args, **kwargs)
    except (ArtworkError, MutateError, SunshineAPIError, ValueError, OSError) as e:
        raise EngineError(str(e)) from e


def config_dir(home: Optional[str] = None) -> str:
    return api.config_dir(home)


_STATE_CACHE: Dict[str, Any] = {"at": 0.0, "conf_dir": "", "doc": None}
STATE_TTL = 3.0


def get_state(conf_dir: str, use_cache: bool = False) -> Dict[str, Any]:
    """What is in apps.json now.

    A page of tiles asks for this once to render and once per image to check the
    allowlist. Those image requests may share a very short cache; the page
    render itself always reads fresh.
    """
    now = time.monotonic()
    if (use_cache and _STATE_CACHE["doc"] is not None
            and _STATE_CACHE["conf_dir"] == conf_dir
            and now - _STATE_CACHE["at"] < STATE_TTL):
        return _STATE_CACHE["doc"]
    doc = _wrap(api.state, conf_dir)
    _STATE_CACHE.update({"at": now, "conf_dir": conf_dir, "doc": doc})
    return doc


def forget_state() -> None:
    """Drop the cache, after something has changed the file."""
    _STATE_CACHE.update({"at": 0.0, "conf_dir": "", "doc": None})


def run_plan(conf_dir: str, opts: Optional[Dict[str, Any]] = None
             ) -> Tuple[Dict[str, Any], str]:
    """What a scan would change. Writes nothing."""
    return _wrap(api.plan, conf_dir, opts), ""


def mutate(conf_dir: str, ops: List[Dict[str, Any]], *,
           reload: bool = True) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """Apply the queue. Returns (everything worked, message, per-operation results).

    The results are returned rather than dropped because "did it all work" is
    not enough to decide what to do with the queue afterwards. A run where one
    of two operations is refused still wrote the other one, and leaving both
    queued jammed the queue permanently: the applied one goes stale, and every
    later apply then does nothing at all.
    """
    ok, message, results = _wrap(api.mutate, conf_dir, ops, reload)
    forget_state()
    return ok, message, results


def browse(conf_dir: str, path: str = "", kind: str = "any") -> Dict[str, Any]:
    return _wrap(api.browse, conf_dir, path, kind)


def art_search(conf_dir: str, *, name: str = "", source: str = "",
               ident: str = "") -> Dict[str, Any]:
    return _wrap(api.art_search, conf_dir, name, source, ident)


def art_sgdb(conf_dir: str, *, name: str = "", source: str = "",
             ident: str = "", page: int = 0) -> Dict[str, Any]:
    return _wrap(api.art_sgdb, conf_dir, name, source, ident, page)


def art_choose(conf_dir: str, chosen_id: str, name: str = "") -> str:
    return _wrap(api.art_choose, conf_dir, chosen_id, name)


def list_backups(conf_dir: str) -> List[Dict[str, Any]]:
    return _wrap(api.list_backups, conf_dir)


def backup_diff(conf_dir: str, name: str) -> Dict[str, Any]:
    return _wrap(api.backup_diff, conf_dir, name)


def check_auth(conf_dir: str) -> Tuple[bool, str]:
    return api.check_auth(conf_dir)


def save_auth(conf_dir: str, username: str, password: str) -> Tuple[bool, str]:
    return api.save_auth(conf_dir, username, password)
