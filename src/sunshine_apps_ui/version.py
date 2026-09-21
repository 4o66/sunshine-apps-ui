# SPDX-License-Identifier: GPL-3.0-or-later
"""What version this is, and which build of it.

Two forms, for two audiences. `version()` is PEP 440, so packaging tools sort
it correctly and a development build sorts *below* the release it is heading
for. `display()` is what a person reads, and leads with the word "dev" so there
is no mistaking a build off the branch for a release.

The build number is the commit count. It costs nothing to maintain, never goes
backwards, and answers the only question a build number is ever asked: which
one is newer. In a checkout it is read from git; an installed copy has no git,
so the installer bakes it in.
"""

import os
import subprocess
from typing import Optional

#: What the next release will be called.
RELEASE = "1.1.0"

#: "dev" until there is a release to call it. Set to "" to cut one.
CHANNEL = ""

_cached: Optional[dict] = None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _from_git() -> Optional[dict]:
    root = _repo_root()
    if not os.path.isdir(os.path.join(root, ".git")):
        return None
    try:
        count = subprocess.run(["git", "-C", root, "rev-list", "--count", "HEAD"],
                               capture_output=True, text=True, timeout=10)
        commit = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if count.returncode or commit.returncode:
        return None
    return {"build": count.stdout.strip() or "0",
            "commit": commit.stdout.strip(),
            # A build with uncommitted changes is not the commit it claims to
            # be, and saying so has saved more time than it has ever cost.
            "dirty": bool(dirty.stdout.strip())}


def _from_baked() -> Optional[dict]:
    try:
        from . import _build                      # written at install time
    except ImportError:
        return None
    return {"build": getattr(_build, "BUILD", "0"),
            "commit": getattr(_build, "COMMIT", ""),
            "dirty": bool(getattr(_build, "DIRTY", False))}


def details(refresh: bool = False) -> dict:
    """Build number, commit and whether the tree was clean."""
    global _cached
    if _cached is None or refresh:
        _cached = (_from_git() or _from_baked()
                   or {"build": "0", "commit": "", "dirty": False})
    return dict(_cached)


def version() -> str:
    """PEP 440, so a development build sorts below the release it precedes."""
    if not CHANNEL:
        return RELEASE
    return f"{RELEASE}.{CHANNEL}{details()['build']}"


def display() -> str:
    """What a person reads. The channel comes first, so it cannot be missed."""
    found = details()
    if not CHANNEL:
        return RELEASE
    text = f"{CHANNEL} {RELEASE}.{found['build']}"
    return f"{text}+" if found["dirty"] else text


def long_display() -> str:
    """With the commit, for a bug report."""
    found = details()
    return f"{display()} ({found['commit']})" if found["commit"] else display()
