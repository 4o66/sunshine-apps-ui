# SPDX-License-Identifier: GPL-3.0-or-later
# importers/launchers.py
from __future__ import annotations
import os
import sys
from typing import List, Dict, Any
from pathlib import Path
from ..utils import log, have_cmd, yn
from ..reconcile import tag

# The tiles we draw, by marker id. These ship with the program: until
# 2026-09-19 they were downloaded at scan time from a third party's repository,
# which meant a scan reached out to a stranger for artwork it then wrote into
# somebody's apps.json. The files are in assets/tiles/; docs/tile-art.md says
# how they are made and where each mark came from.
TILE_FILES = {
    "apps-ui": "app-manager.png",
    "steam": "steam.png",
    "heroic": "heroic.png",
    "reboot": "reboot-host.png",
}

# Display names only. The keys are the ownership marker's id and must not
# change: that is what ties an entry in apps.json to the thing that generated
# it, so renaming a key would orphan the existing entry and add a second one
# beside it rather than rename anything.
NAMES = {
    "apps-ui": "Zz App Manager",
    "desktop": "#1 Desktop",
    "steam": "Zz Steam",
    "heroic": "Zz Heroic",
    # "Reboot Host", not "Reboot": on a stream it matters which machine is
    # about to go down, and it is not the one in front of you.
    "reboot": "Zz Reboot Host",
}

def _steam_cmd(home: str) -> tuple[str, str]:
    """Return (cmd, working_dir) for Steam if found, else ('','')."""
    if os.name == "nt":
        import ntpath
        from ..artwork_sources import find_steam_root
        root, _ = find_steam_root(home)
        if root:
            exe = ntpath.join(root, "steam.exe")
            if os.path.isfile(exe):
                return (f'"{exe}"', root)
        return ("", "")

    flatpak_root = f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    if os.path.isdir(flatpak_root):
        return ("flatpak run com.valvesoftware.Steam", flatpak_root)
    if have_cmd("steam"):
        for r in (f"{home}/.local/share/Steam", f"{home}/.steam/steam"):
            if os.path.isdir(r):
                return ("steam", r)
        return ("steam", home)
    return ("", "")

def _heroic_cmd(home: str) -> tuple[str, str]:
    """Return (cmd, working_dir) for Heroic if found, else ('','')."""
    if os.name == "nt":
        import ntpath
        places = [os.environ.get("LOCALAPPDATA", ntpath.join(home, "AppData", "Local")),
                  os.environ.get("ProgramFiles", ""),
                  os.environ.get("ProgramFiles(x86)", "")]
        for base in [p for p in places if p]:
            for tail in (("Programs", "heroic", "Heroic.exe"), ("Heroic", "Heroic.exe")):
                exe = ntpath.join(base, *tail)
                if os.path.isfile(exe):
                    return (f'"{exe}"', ntpath.dirname(exe))
        return ("", "")

    candidates = [
        f"{home}/.var/app/com.heroicgameslauncher.hgl/config/heroic",
        f"{home}/.config/heroic",
    ]
    is_flatpak = any(os.path.isdir(p) and "/.var/app/" in p for p in candidates)
    if is_flatpak:
        return ("flatpak run com.heroicgameslauncher.hgl", home)
    if have_cmd("heroic"):
        return ("heroic", home)
    return ("", "")

def _reboot_cmd() -> str:
    """How this platform is told to restart.

    Not a detail: the tile says "Reboot", and on Windows `systemctl reboot`
    would be an entry that looks right and does nothing.
    """
    if os.name == "nt":
        return "shutdown /r /t 0"
    if sys.platform == "darwin":
        # No sudo: this is the supported way to ask for a restart as the user.
        return 'osascript -e \'tell application "System Events" to restart\''
    return "systemctl reboot"


def _sunshine_is_flatpak(conf_dir: str) -> bool:
    """Is Sunshine itself running from a Flatpak?

    Told by where its configuration lives, which is the same thing config
    discovery uses to find it.
    """
    return "/.var/app/" in conf_dir.replace(os.sep, "/")


def _host(cmd: str, sandboxed: bool) -> str:
    """Run *cmd* on the host, even when Sunshine is sandboxed.

    A Flatpak sees its own filesystem, so a command naming a path outside it --
    which is every command we generate -- simply is not there. Upstream says
    the same: "the Flatpak of Sunshine requires commands to be prefixed with
    flatpak-spawn --host".
    """
    if not cmd or not sandboxed or cmd.startswith("flatpak-spawn "):
        return cmd
    return f"flatpak-spawn --host {cmd}"


def _apps_ui(home: str) -> tuple[str, str]:
    """Return (cmd, poster) for the companion UI if installed, else ('', '').

    Detected by the launcher being on disk, the same way Steam and Heroic are
    detected by their directories. Nothing is imported from it.
    """
    if os.name == "nt":
        # Windows keeps a program in one directory and has no bin/ convention,
        # so the installed command is a .cmd inside the install itself. Asked of
        # the installer rather than rebuilt here, so the two cannot disagree.
        from ...installer import paths, windowless_command
        where = paths()
        poster = os.path.join(where["install"], "assets", "poster.png")
        if os.path.isfile(where["command"]):
            # pythonw where there is one: a tile that opens a console window
            # beside the interface is two windows where a person expects one,
            # and on a television the console is simply in the way.
            return (windowless_command(where),
                    poster if os.path.isfile(poster) else "")
        return ("", "")

    # os.path.join, not an f-string: on Windows a hand-built "/" path produces
    # C:\Users\sean/.local/bin/... which is a real path Windows will open and a
    # string nothing else here will match.
    poster = os.path.join(home, ".local", "share", "sunshine-apps-ui",
                          "assets", "poster.png")
    poster = poster if os.path.isfile(poster) else ""
    local = os.path.join(home, ".local", "bin", "sunshine-apps-ui")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return (local, poster)
    if have_cmd("sunshine-apps-ui"):
        return ("sunshine-apps-ui", poster)
    return ("", "")


def _common_fields() -> Dict[str, Any]:
    return {
        "exclude-global-prep-cmd": False,
        "exit-timeout": 5,
        "output": "",
        "wait-all": True,
    }

# Names these tiles used to have. Keyed by the old name, valued by the marker
# id it belongs to, so an entry written before markers existed is still
# recognised as ours after a rename rather than being duplicated.
FORMER_NAMES = {
    "Zz Reboot": "reboot",
}


def _desktop_tile_name() -> str:
    """Which desktop tile this machine gets: its own platform, or its distro.

    The Desktop tile says which machine you are connecting to. On Linux that
    is the distribution -- from a set we ship, where we have one -- and
    otherwise the platform. docs/tile-art.md has the whole lookup.
    """
    if os.name == "nt":
        return "desktop-windows.png"
    if sys.platform == "darwin":
        return "desktop-macos.png"
    ident = ""
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            fields = dict(
                line.rstrip("\n").split("=", 1) for line in handle
                if "=" in line and not line.startswith("#"))
        ident = fields.get("ID", "").strip('"').lower()
    except OSError:
        ident = ""
    from ... import i18n

    if ident and i18n.tile("desktop-%s.png" % ident):
        return "desktop-%s.png" % ident
    return "desktop-linux.png"          # Tux, which is right anywhere


def _ensure_posters(images_dir: str) -> Dict[str, str]:
    """Where each launcher tile's artwork is. Nothing is downloaded.

    The files ship with the program; this returns the path to the one that
    suits this machine and this language, which is the wordless set unless
    somebody has drawn a worded one -- see docs/i18n.md.
    """
    from ... import i18n

    paths: Dict[str, str] = {}
    for key, filename in TILE_FILES.items():
        found = i18n.tile(filename)
        if not found:
            log(f"Warning: no tile artwork for {key} ({filename})")
        paths[key] = found
    paths["desktop"] = i18n.tile(_desktop_tile_name())
    return paths

def import_launchers(home: str, conf_dir: str, images_dir: str, settings: Dict[str, Any],
                     report: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    Create generic launchers (Desktop, Steam-if-installed, Heroic-if-installed, Reboot).

    Toggle with IMPORT_LAUNCHERS (default: on).
    """
    if report is None:
        report = {}
    enabled = str(settings.get("IMPORT_LAUNCHERS", "1")).strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        log("Launchers importer disabled.")
        report["status"] = "disabled"
        return []
    # These entries are synthesised, not discovered, so the scan cannot fail.
    report["status"] = "ok"

    posters = _ensure_posters(images_dir)
    apps: List[Dict[str, Any]] = []
    # Every command below names a path on the host. If Sunshine is sandboxed,
    # none of them exist from where it is looking.
    sandboxed = _sunshine_is_flatpak(conf_dir)
    if sandboxed:
        log("Sunshine is running from a Flatpak; commands will run on the host.")

    # 1) Desktop
    apps.append(tag({
        "name": NAMES["desktop"],
        "cmd": "",
        "working-dir": home,
        "image-path": posters["desktop"],
        "detached": False,
        "elevated": False,
        "exit-on-close": True,
        **_common_fields(),
    }, "launcher", "desktop"))
    log(f"Added {yn(NAMES['desktop'])} launcher")

    # 2) Steam (only if installed)
    steam_cmd, steam_wd = _steam_cmd(home)
    if steam_cmd:
        apps.append(tag({
            "name": NAMES["steam"],
            "cmd": _host(steam_cmd, sandboxed),
            "working-dir": steam_wd or home,
            "image-path": posters["steam"],
            "detached": False,
            "elevated": False,
            "exit-on-close": True,
            **_common_fields(),
        }, "launcher", "steam"))
        log(f"Added {yn(NAMES['steam'])} launcher")
    else:
        log("Steam not detected; skipping Steam launcher")

    # 3) Heroic (only if installed)
    heroic_cmd, heroic_wd = _heroic_cmd(home)
    if heroic_cmd:
        apps.append(tag({
            "name": NAMES["heroic"],
            "cmd": _host(heroic_cmd, sandboxed),
            "working-dir": heroic_wd or home,
            "image-path": posters["heroic"],
            "detached": False,
            "elevated": False,
            "exit-on-close": True,
            **_common_fields(),
        }, "launcher", "heroic"))
        log(f"Added {yn(NAMES['heroic'])} launcher")
    else:
        log("Heroic not detected; skipping Heroic launcher")

    # 4) The companion UI, if it is installed
    ui_cmd, ui_poster = _apps_ui(home)
    ui_poster = posters.get("apps-ui") or ui_poster
    if ui_cmd:
        apps.append(tag({
            "name": NAMES["apps-ui"],
            "cmd": _host(ui_cmd, sandboxed),
            "working-dir": home,
            "image-path": ui_poster,
            "detached": False,
            # On Windows this flag is the whole mechanism. apps.json lives in
            # Sunshine's own directory under Program Files, so only an elevated
            # process can write it -- and Sunshine grants that to an entry
            # marked "elevated" with no UAC prompt, because it is already
            # running as SYSTEM. Without it the manager opens read-only and can
            # do nothing but look, which is what privilege.check reports.
            #
            # Not on Linux or macOS, where the config directory is the user's
            # own and asking for root would be asking for rights we do not need.
            "elevated": os.name == "nt",
            "exit-on-close": True,
            **_common_fields(),
        }, "launcher", "apps-ui"))
        log(f"Added {yn(NAMES['apps-ui'])} launcher")
    else:
        log("sunshine-apps-ui not detected; skipping its launcher")

    # 5) Reboot
    apps.append(tag({
        "name": NAMES["reboot"],
        "auto-detach": True,
        "cmd": [],
        "detached": [_host(_reboot_cmd(), sandboxed)],
        "image-path": posters["reboot"],
        **_common_fields(),
    }, "launcher", "reboot"))
    log(f"Added {yn(NAMES['reboot'])} launcher")

    return apps
