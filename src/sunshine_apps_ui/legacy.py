# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the older importer this project grew out of, and saying what it does.

There is exactly one thing the two cannot share, and it is not a directory or a
command name -- those are ours to choose. It is Sunshine's apps.json, which we
also share with Sunshine itself, so not sharing it is not an option.

The original rewrites that file from scratch on every run. Its own source says
so::

    # Fresh write: "env" then "apps" (then meta for visibility)
    payload = {"env": env_block, "apps": apps, "meta": {...}}
    write_json(apps_json, payload)

Everything outside its own generated list goes: Sunshine's default entries,
anything added by hand, the managed list, and every tombstone. So this is not an
install-time question that can be asked once and forgotten -- the tool can be
run any day afterwards, which is why it is checked for at install *and* on every
scan.
"""

import os
import shutil
from typing import Any, Dict, List, Optional

# Where the original installs itself, from its own init.sh:
#     DEST="$HOME/.config/sunshine/helper"
#     ln -sfn "$DEST/sunshine-import.sh" "${HOME}/.local/bin/sunshine-import"
_HELPER_DIR = ".config/sunshine/helper"
_COMMANDS = (".local/bin/sunshine-import", ".local/bin/bsm-test-import")

# What tells the two apart. The fork that became this project added the
# reconciler; the original has no such file and never did.
_FORK_ONLY = ("common/reconcile.py", "common/mutate.py")

REWRITES_EVERYTHING = (
    "It rewrites apps.json from scratch every time it runs. That removes "
    "anything it did not generate itself -- Sunshine's own default entries, "
    "anything you added by hand, every record of what you have hidden or "
    "deleted -- and there is no way to tell afterwards that they were ever "
    "there."
)

# Checked against Sunshine's source rather than assumed, because the obvious
# guess is wrong and a warning that cries wolf teaches people to ignore it.
SUNSHINE_WEB_UI = (
    "Sunshine's own web UI is safe to use alongside this. It reads each app "
    "whole, copies it, and writes the whole file back, so nothing of ours is "
    "lost. One thing to know: deleting an app there is not recorded as a "
    "deletion, so the next scan finds it again and offers to put it back."
)


def _is_fork(root: str) -> bool:
    return any(os.path.isfile(os.path.join(root, f)) for f in _FORK_ONLY)


def _root_of(command: str) -> str:
    """The install directory a command launcher belongs to."""
    return os.path.dirname(os.path.realpath(command))


def find_installs(home: Optional[str] = None,
                  search_path: bool = True) -> List[Dict[str, Any]]:
    """Every copy of the older importer that can be found, newest style first.

    Each result says where it is, how it is launched, and whether it is the
    fork this project absorbed or the original it came from -- because only one
    of those two will destroy your file.
    """
    home = home or os.path.expanduser("~")
    found: List[Dict[str, Any]] = []
    seen = set()

    def record(root: str, command: str):
        root = os.path.realpath(root)
        if root in seen or not os.path.isdir(root):
            return
        seen.add(root)
        found.append({
            "root": root,
            "command": command,
            "kind": "fork" if _is_fork(root) else "original",
            "destructive": not _is_fork(root),
        })

    helper = os.path.join(home, _HELPER_DIR)
    if os.path.isdir(helper):
        record(helper, os.path.join(helper, "sunshine-import.sh"))

    candidates = [os.path.join(home, c) for c in _COMMANDS]
    if search_path:
        on_path = shutil.which("sunshine-import")
        if on_path:
            candidates.append(on_path)
    for command in candidates:
        if os.path.exists(command):
            record(_root_of(command), command)

    return found


def destructive_installs(home: Optional[str] = None,
                         search_path: bool = True) -> List[Dict[str, Any]]:
    """Only the ones that would rewrite apps.json wholesale."""
    return [i for i in find_installs(home, search_path) if i["destructive"]]


def removal_plan(install: Dict[str, Any],
                 home: Optional[str] = None) -> List[str]:
    """What removing this install would delete, so it can be shown before doing it.

    Only ever its own files. apps.json is never on this list: it is Sunshine's,
    not the importer's, and removing a tool is not a reason to touch your apps.
    """
    home = home or os.path.expanduser("~")
    paths = [install["root"]]
    for command in _COMMANDS:
        path = os.path.join(home, command)
        if os.path.islink(path) and _root_of(path) == install["root"]:
            paths.append(path)
    return paths
