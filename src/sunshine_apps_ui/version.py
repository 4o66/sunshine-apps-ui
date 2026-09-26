# SPDX-License-Identifier: GPL-3.0-or-later
"""What version this is, and which build of it.

Two forms, for two audiences. `version()` is PEP 440, so packaging tools sort
it correctly and a development build sorts *below* the release it is heading
for. `display()` is what a person reads, and leads with the word "dev" so there
is no mistaking a build off the branch for a release.

The build number is the commit count. It costs nothing to maintain, never goes
backward, and answers the only question a build number is ever asked: which
one is newer. In a checkout it is read from git; an installed copy has no git,
so the installer bakes it in.

The count is only unambiguous along a single line of history, and there are now
two: `main` carries releases, `dev` carries development. Those two never hold
different commits at the same depth, because `main` only ever takes what `dev`
already has -- so a build off either is identified by its number alone. A build
off any other branch is not: two issue branches cut from the same commit reach
the same count. Those carry the branch and the commit as well, in the PEP 440
local segment, which sorts them above the `dev` build they branched from and
still below the release it is heading for.
"""

import os
import re
import subprocess
from typing import Optional

#: What the next release will be called.
RELEASE = "1.2.0"

#: "dev" until there is a release to call it. Set to "" to cut one.
CHANNEL = ""

#: Branches whose commit count is unambiguous, so the number stands alone.
INTEGRATION = ("dev", "main")

_cached: Optional[dict] = None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _slug(name: str) -> str:
    """A branch name as a PEP 440 local segment: alphanumerics and periods."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", ".", name).strip(".").lower()
    return cleaned or "branch"


def _from_git() -> Optional[dict]:
    root = _repo_root()
    # A file, not a directory, when the checkout is a worktree -- which is how
    # issue branches get worked on, so testing for a directory reported build 0
    # for every one of them.
    if not os.path.exists(os.path.join(root, ".git")):
        return None
    try:
        count = subprocess.run(["git", "-C", root, "rev-list", "--count", "HEAD"],
                               capture_output=True, text=True, timeout=10)
        commit = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10)
        branch = subprocess.run(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if count.returncode or commit.returncode:
        return None
    # "HEAD" means detached, which is not a branch name. Empty stands for a
    # branch we could not read, and the commit does the identifying instead.
    found = "" if branch.returncode else branch.stdout.strip()
    return {"build": count.stdout.strip() or "0",
            "commit": commit.stdout.strip(),
            "branch": "" if found == "HEAD" else found,
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
            # Absent in anything stamped before branches existed. Missing
            # entirely is not the same as detached: say nothing rather than
            # imply a copy came from somewhere it may well not have.
            "branch": getattr(_build, "BRANCH", None),
            "dirty": bool(getattr(_build, "DIRTY", False))}


def details(refresh: bool = False) -> dict:
    """Build number, commit, branch and whether the tree was clean."""
    global _cached
    if _cached is None or refresh:
        _cached = (_from_git() or _from_baked()
                   or {"build": "0", "commit": "", "branch": None,
                       "dirty": False})
    return dict(_cached)


def _off_integration() -> Optional[dict]:
    """The details, if this build cannot be named by its number alone."""
    found = details()
    branch = found.get("branch")
    if branch is None or branch in INTEGRATION:
        return None
    return found


def _local() -> str:
    """The PEP 440 local segment: which branch, and which commit on it."""
    found = _off_integration()
    if found is None:
        return ""
    parts = [_slug(found["branch"])] if found["branch"] else []
    if found["commit"]:
        parts.append(f"g{found['commit']}")
    return ".".join(parts)


def version() -> str:
    """PEP 440, so a development build sorts below the release it precedes."""
    base = RELEASE if not CHANNEL else f"{RELEASE}.{CHANNEL}{details()['build']}"
    local = _local()
    return f"{base}+{local}" if local else base


def _note(with_commit: bool = False) -> str:
    """" (issue.3)", for a build whose number does not identify it alone."""
    off = _off_integration()
    if off is None:
        return ""
    inside = _slug(off["branch"]) if off["branch"] else "detached"
    if with_commit and off["commit"]:
        inside = f"{inside} {off['commit']}"
    return f" ({inside})"


def _body() -> str:
    """The version and build, without any note about where it came from."""
    found = details()
    if not CHANNEL:
        return RELEASE
    text = f"{CHANNEL} {RELEASE}.{found['build']}"
    return f"{text}+" if found["dirty"] else text


def display() -> str:
    """What a person reads. The channel comes first, so it cannot be missed."""
    # Whatever the number says, this may have come off a branch of its own.
    return _body() + _note()


def long_display() -> str:
    """With the commit, for a bug report."""
    found = details()
    if _note():
        # One parenthesis, not two: the branch and the commit belong together.
        return _body() + _note(with_commit=True)
    return f"{_body()} ({found['commit']})" if found["commit"] else _body()
