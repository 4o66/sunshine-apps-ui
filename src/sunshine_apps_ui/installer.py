# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing and removing this, for the current user.

Everything lands under a per-user prefix and nothing needs root. That is
deliberate rather than modest: Bazzite is rpm-ostree, so /usr is read-only and
anything layered there has to survive every rebase. A per-user prefix survives
that, and uninstalling is deleting files rather than unpicking a package. The
same holds for any immutable system, which is most of where Sunshine gets
installed from Flathub.

Windows will not use this. It has no such convention, and the decision recorded
in docs/backlog.md is to install as a normal Windows application instead.
"""

import os
import shutil
import sys
from typing import List, Optional, Tuple

from . import legacy

# What is needed to run. Tests, git history and build files are not.
INSTALLED = ("src", "assets", "scripts", "docs", "README.md", "LICENSE",
             "LICENSE.upstream-MIT", "NOTICE")

COMMAND = "sunshine-apps-ui"


def default_prefix() -> str:
    return os.getenv("PREFIX") or os.path.expanduser("~/.local")


def paths(prefix: Optional[str] = None):
    prefix = prefix or default_prefix()
    return {
        "prefix": prefix,
        "install": os.path.join(prefix, "share", "sunshine-apps-ui"),
        "bin": os.path.join(prefix, "bin"),
        "command": os.path.join(prefix, "bin", COMMAND),
        "state": os.path.join(
            os.getenv("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
            "sunshine-apps-ui"),
    }


def _source_root() -> str:
    """The checkout this is being installed from."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _launcher_script(install_dir: str) -> str:
    """A tiny entry point, so the installed command is a real program.

    It does nothing but put the installed copy on the path and hand over, which
    keeps "what runs" in Python rather than in whatever shell happens to exist.
    """
    return (
        "#!/usr/bin/env python3\n"
        "# SPDX-License-Identifier: GPL-3.0-or-later\n"
        '"""Run the installed copy of sunshine-apps-ui."""\n'
        "import os, sys\n"
        f"sys.path.insert(0, {os.path.join(install_dir, 'src')!r})\n"
        "from sunshine_apps_ui.__main__ import main\n"
        "raise SystemExit(main())\n"
    )


def install(prefix: Optional[str] = None, *,
            confirm=None) -> Tuple[bool, List[str]]:
    """Copy this into place. Returns (installed, messages)."""
    where = paths(prefix)
    messages = []

    blocking = legacy.destructive_installs()
    if blocking:
        # The original rewrites apps.json from scratch on every run, removing
        # everything it did not generate. It cannot be left beside this, so
        # this is a refusal rather than a warning.
        messages.append("The original bazzite-sunshine-manager is still installed:")
        for found in blocking:
            messages.append(f"  {found['root']}")
            for path in legacy.removal_plan(found):
                messages.append(f"    would remove: {path}")
        messages.append("")
        messages.append(legacy.REWRITES_EVERYTHING)
        messages.append("")
        messages.append(legacy.SUNSHINE_WEB_UI)
        if confirm is None or not confirm(
                "\n".join(messages),
                "Remove it? Only its own files; apps.json is not touched."):
            messages.append("")
            messages.append("Left in place. Do not run it: it will undo what this "
                            "manages. Nothing was installed.")
            return False, messages
        for found in blocking:
            for path in legacy.removal_plan(found):
                messages.append(f"  removed {path}" if _remove(path)
                                else f"  could not remove {path}")

    source = _source_root()
    os.makedirs(where["install"], exist_ok=True)
    os.makedirs(where["bin"], exist_ok=True)

    for item in INSTALLED:
        origin = os.path.join(source, item)
        if not os.path.exists(origin):
            continue
        target = os.path.join(where["install"], item)
        _remove(target)
        if os.path.isdir(origin):
            shutil.copytree(origin, target,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(origin, target)

    # An installed copy has no git to ask, so the answer is written down while
    # the checkout that has one is still to hand. Without this every install
    # would report build 0 and every bug report would be ambiguous.
    stamp_build(os.path.join(where["install"], "src", "sunshine_apps_ui"))

    with open(where["command"], "w", encoding="utf-8") as handle:
        handle.write(_launcher_script(where["install"]))
    os.chmod(where["command"], 0o755)

    messages.append(f"Installed to {where['install']}")
    messages.append(f"Command     {where['command']}")

    messages.extend(_offer_unhide_tile(confirm))

    on_path = [os.path.normpath(p) for p in os.getenv("PATH", "").split(os.pathsep)]
    if os.path.normpath(where["bin"]) not in on_path:
        messages.append("")
        messages.append(f"Note: {where['bin']} is not on your PATH. Sunshine's tile "
                        f"still works -- it runs the command by its full path -- "
                        f"but you cannot type it.")
    return True, messages


def _offer_unhide_tile(confirm=None) -> List[str]:
    """Offer to bring back a tile that was hidden rather than merely deleted.

    A deleted tile comes back on its own: nothing records the deletion, so the
    next scan sees the launcher as new and adds it. A *hidden* one does not --
    hiding writes a tombstone, and a tombstone is an instruction to keep
    skipping it, which --put-the-tile-back-because-i-deleted-it obeys along
    with everything else. So reinstalling to get the tile back quietly achieves
    nothing, and the only clue is a tile that never reappears.

    Asking is the point. The tombstone is a decision the user made, and an
    installer that silently reversed it would be no better than one that
    silently ignored it.
    """
    try:
        from .core import api
    except ImportError:                          # pragma: no cover - defensive
        return []
    try:
        conf_dir = api.config_dir()
        hidden = [t for t in api.state(conf_dir).get("hidden") or []
                  if t.get("source") == "launcher" and t.get("id") == "apps-ui"]
    except Exception:                            # noqa: BLE001 - not worth failing an install
        return []
    if not hidden:
        return []

    name = hidden[0].get("name") or "The manager's own tile"
    question = (f"{name} is hidden, so scanning will keep skipping it. "
                f"Put it back?")
    if confirm is None:
        # Non-interactive: say so rather than decide. Reversing a hide without
        # being asked is exactly what the tombstone exists to prevent.
        return ["", f"Note: {name} is hidden, so it will not come back on its "
                    f"own -- not even with --put-the-tile-back-because-i-deleted-it. "
                    f"Unhide it from the app list, or reinstall where you can "
                    f"answer a prompt."]
    if not confirm("", question):
        return ["", f"Left hidden. {name} stays out of Sunshine until you "
                    f"unhide it."]

    try:
        ok, message, _ = api.mutate(
            conf_dir, [{"op": "restore", "selector": "launcher:apps-ui"}])
    except Exception as e:                       # noqa: BLE001 - reported
        return ["", f"Could not unhide {name}: {e}"]
    if not ok:
        return ["", f"Could not unhide {name}: {message}"]

    # Hiding keeps the whole entry, so restoring puts the tile straight back.
    # Suppressing -- refusing something a scan offered, before it ever existed
    # in the file -- has no entry to put back, so clearing the tombstone only
    # stops it being skipped. Saying "unhid" and leaving no tile would look
    # exactly like the silent failure this was written to remove.
    if _tile_is_present(api, conf_dir):
        return ["", f"Unhid {name}."]
    return ["", f"Unhid {name}, but there was no kept copy of it to put back. "
                f"Run --install --put-the-tile-back-because-i-deleted-it to "
                f"rebuild it; nothing is blocking it now."]


def _tile_is_present(api, conf_dir: str) -> bool:
    try:
        return any(a.get("source") == "launcher" and a.get("id") == "apps-ui"
                   for a in api.state(conf_dir).get("apps") or [])
    except Exception:                            # noqa: BLE001 - defensive
        return True                              # do not invent bad news


def stamp_build(package_dir: str) -> bool:
    """Write down which build this is, for a copy that cannot work it out.

    Refuses to replace a known build number with an unknown one. Installing
    from a source tree that has no git -- an unpacked tarball, say -- would
    otherwise overwrite a number carried in that tarball with 0, which is the
    exact ambiguity this exists to prevent.
    """
    from .version import details

    found = details(refresh=True)
    target = os.path.join(package_dir, "_build.py")
    if found["build"] in ("", "0") and os.path.exists(target):
        return False
    try:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(
                "# SPDX-License-Identifier: GPL-3.0-or-later\n"
                '"""Written when this was packaged or installed. Not in git:\n'
                'it describes one copy, not the source it came from."""\n'
                f"BUILD = {found['build']!r}\n"
                f"COMMIT = {found['commit']!r}\n"
                f"DIRTY = {bool(found['dirty'])!r}\n")
        return True
    except OSError:
        return False              # a missing build number is not worth failing over


def uninstall(prefix: Optional[str] = None, *, keep_state: bool = False,
              keep_tile: bool = False,
              purge_backups: bool = False) -> Tuple[bool, List[str]]:
    """Remove this, tile included. Returns (removed, messages)."""
    where = paths(prefix)
    messages = []

    from .launcher import stop_previous
    stop_previous()

    if not keep_tile:
        # The tile goes first, while the engine is still installed to remove it
        # properly. Deleting our files first would leave a tile pointing at a
        # command that no longer exists.
        removed, note = _remove_tile()
        messages.append(note)
        if not removed:
            messages.append("Leaving the files in place.")
            return False, messages

    _remove(where["command"])
    _remove(where["install"])
    messages.append(f"Removed {where['install']}")

    backups = os.path.join(where["state"], "backups")
    if keep_state:
        messages.append(f"Kept {where['state']}")
    elif purge_backups:
        _remove(where["state"])
        messages.append(f"Removed {where['state']}, kept copies included")
    else:
        # Everything under state except the copies of apps.json, which are
        # copies of your configuration rather than of this program -- and an
        # uninstall is a moment you might want one back.
        for name in _listdir(where["state"]):
            if name != "backups":
                _remove(os.path.join(where["state"], name))
        kept = len(_listdir(backups))
        if kept:
            messages.append(f"Kept {backups} ({kept} copies of apps.json)")
            messages.append("  Remove them with --purge-backups, or by hand.")

    messages.append("Done. Sunshine, and everything in apps.json that was not "
                    "ours, is untouched.")
    return True, messages


def _remove_tile() -> Tuple[bool, str]:
    """Delete this manager's own tile, by its marker rather than its name."""
    try:
        from .core import api
    except ImportError as e:                     # pragma: no cover - defensive
        return False, f"Could not load the engine to remove the tile: {e}"
    try:
        conf_dir = api.config_dir()
        found = [a for a in api.state(conf_dir).get("apps") or []
                 if a.get("source") == "launcher" and a.get("id") == "apps-ui"]
    except Exception as e:                       # noqa: BLE001 - reported
        return False, f"Could not read the app list: {e}"
    if not found:
        return True, "No tile to remove; it is not in apps.json."
    entry = found[0]
    try:
        ok, message, _ = api.mutate(
            conf_dir, [{"op": "delete", "index": entry["index"],
                        "name": entry["name"]}])
    except Exception as e:                       # noqa: BLE001 - reported
        return False, f"Could not remove the tile: {e}"
    return ok, (message if ok else f"Could not remove the tile: {message}")


def _listdir(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _remove(path: str) -> bool:
    try:
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        return True
    except OSError:
        return False
