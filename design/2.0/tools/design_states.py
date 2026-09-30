# SPDX-License-Identifier: GPL-3.0-or-later
"""Serve the real app, on fake state, for design-vs-build comparison (#56).

    python3 design/2.0/tools/design_states.py <scenario> [--port 8766]
        [--streamed] [--pad] [--design-dir DIR]

The real server and the real pages, with the engine replaced by the tests'
FakeEngine (tests/test_server.py) so a page can be put in exactly the state its
board shows. Only three things differ from a real session, all here:

- the token gate is waved through, so a capture tool can open any address;
- --pad marks the page as in controller use, the way the boards are drawn;
- the drive endpoints (/drive, /_target, /_drive.js) let one window be steered
  from page to page without reloading, as the prototype server does.

Scenarios set the engine and the queue; each lists the addresses to capture
with the board file each is compared against.
"""

import argparse
import json
import os
import sys
import tempfile
from unittest import mock
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tests"))

from sunshine_apps_ui import frame, security, server as srv, state  # noqa: E402
import test_server  # noqa: E402

IMG = os.path.join(REPO, "design", "2.0", "img")


def tile(index, name, image, source=None, ident=None, cmd=""):
    return {"index": index, "name": name, "image-path": os.path.join(IMG, image),
            "cmd": cmd, "source": source, "id": ident, "managed": bool(source)}


# The twelve tiles every grid board shows, in the boards' order.
BOARD_APPS = [
    tile(0, "#1 Desktop", "desktop-bazzite.png", "launcher", "desktop"),
    tile(1, "#2 Low Res Desktop", "desktop-lowres-bazzite.png", "launcher", "desktop-lowres"),
    tile(2, "Cyberpunk 2077", "1091500.png", "steam", "1091500", "steam steam://rungameid/1091500"),
    tile(3, "Enshrouded", "1203620.png", "steam", "1203620"),
    tile(4, "NIMRODS", "2086430.png", "steam", "2086430"),
    tile(5, "Portal: Revolution", "601360.png", "steam", "601360"),
    tile(6, "Satisfactory", "satisfactory.png", "heroic", "satisfactory"),
    tile(7, "Zz App Manager", "app-manager.png", "launcher", "apps-ui"),
    tile(8, "Zz Heroic", "heroic.png", "launcher", "heroic"),
    tile(9, "Zz Reboot Host", "reboot-host.png", "launcher", "reboot"),
    tile(10, "Zz Steam", "steam.png", "launcher", "steam"),
    tile(11, "Zz Steam Big Picture", "steam-bigpicture.png", "launcher", "bigpicture"),
]


def board_state(*, without=(), hidden=()):
    """The boards' apps.json: `without` leaves tiles out (a game a scan has
    found is not in the file yet); `hidden` moves them to the hidden list."""
    apps, hide = [], []
    for a in BOARD_APPS:
        if a["name"] in without:
            continue
        (hide if a["name"] in hidden else apps).append(dict(a))
    for i, a in enumerate(apps):
        a["index"] = i
    for a in hide:
        a["index"] = None
    return {
        "schema": 1, "generator": {"name": "bazzite-sunshine-manager", "version": "2.0"},
        "config_dir": "/var/home/user/.config/sunshine",
        "apps_json": "/var/home/user/.config/sunshine/apps.json",
        "apps": apps, "hidden": hide,
    }


def app(name):
    return next(dict(a) for a in BOARD_APPS if a["name"] == name)


# name -> (setup(engine), [(address, board file)])
SCENARIOS = {}


def scenario(name, pages):
    def register(setup):
        SCENARIOS[name] = (setup, pages)
        return setup
    return register


def found_by_scan(name):
    """What a scan queues for a game it found: an adopt, with the entry."""
    a = app(name)
    state.enqueue({"op": "adopt", "name": name, "source": a["source"], "id": a["id"],
                   "from_scan": True, "entry": {"name": name, "image-path": a["image-path"]}})


def edited(name):
    a = app(name)
    state.enqueue({"op": "edit", "name": name, "source": a["source"], "id": a["id"],
                   "fields": {"image-path": a["image-path"]}})


@scenario("grid", [("/", "grid.html")])
def _grid(engine):
    engine.state = board_state(without=["NIMRODS"])
    found_by_scan("NIMRODS")
    edited("Satisfactory")


FLATPAK = "/var/home/user/.var/app/dev.lizardbyte.app.Sunshine/config/sunshine"
NATIVE = "/var/home/user/.config/sunshine"


@scenario("grid-states", [("/", "grid-states.html")])
def _grid_states(engine):
    engine.state = board_state(without=["NIMRODS"], hidden=["Portal: Revolution"])
    a = app("Enshrouded")
    state.enqueue({"op": "hide", "name": "Enshrouded", "source": a["source"], "id": a["id"]})
    found_by_scan("NIMRODS")
    edited("Satisfactory")
    state.enqueue({"op": "add", "fields": {"name": "Hades II"}})
    engine.auth = (False, "The sign-in was refused: 401 Unauthorized.")
    config = {"how": "running", "chosen": NATIVE, "stale": True, "stale_reason": "running",
              "was": FLATPAK, "queued": 0,
              "candidates": [{"path": NATIVE, "apps": 12, "last_used": 0},
                             {"path": FLATPAK, "apps": 3, "last_used": 0}]}
    mock.patch.object(srv.PlanHandler, "_config_panel", lambda self: dict(config)).start()


@scenario("grid-rights", [("/", "grid-rights.html")])
def _grid_rights(engine):
    engine.state = board_state()
    for a in engine.state["apps"][:2]:
        a["image-path"] = a["image-path"].replace("-bazzite.png", "-windows.png")
    engine.state["apps_json"] = "C:\\Program Files\\Sunshine\\config\\apps.json"
    detail = ("This is running without administrator rights, and C:\\Program Files\\Sunshine\\config\\apps.json "
              "belongs to Sunshine's own directory, which only an administrator may write. Sunshine grants those "
              "rights to a tile marked \u201celevated\u201d \u2014 but only when it is running as its service and "
              "the account is an administrator. Started by hand, or from a standard account, it launches this "
              "with your own rights and says so only in its log. Reading, scanning and reloading still work; "
              "nothing can be saved.")
    from sunshine_apps_ui import privilege
    refused = privilege.Privilege(False, False, detail, "Changes cannot be saved")
    mock.patch.object(privilege, "check", lambda conf_dir: refused).start()
    mock.patch.object(privilege, "can_ask_for_elevation", lambda: True).start()


@scenario("grid-restore", [("/", "grid-restore.html")])
def _grid_restore(engine):
    engine.state = board_state()
    state.enqueue({"op": "rollback", "backup": "apps-20260926-211403.json"})
    engine.diff = {"returning": [], "going": [{"name": "NIMRODS", "key": "steam:2086430"}],
                   "changing": [{"name": "Satisfactory", "key": "heroic:satisfactory", "fields": []}],
                   "hidden_now": 0, "hidden_then": 0}


def _unhide(engine, *, edit):
    engine.state = board_state(without=["NIMRODS"], hidden=["Portal: Revolution"])
    found_by_scan("NIMRODS")
    a = app("Portal: Revolution")
    state.enqueue({"op": "restore", "selector": f'{a["source"]}:{a["id"]}', "name": a["name"]})
    edited("Satisfactory")
    if edit:
        edited("Portal: Revolution")


@scenario("grid-unhide", [("/", "grid-unhide.html")])
def _grid_unhide(engine):
    _unhide(engine, edit=False)


@scenario("grid-unhide-edited", [("/", "grid-unhide-edited.html")])
def _grid_unhide_edited(engine):
    _unhide(engine, edit=True)


def edit_state():
    """The boards' apps with the fields the edit boards show."""
    st = board_state()
    for a in st["apps"]:
        a.update({"auto-detach": True, "wait-all": True, "exit-timeout": 5, "working-dir": "", "output": ""})
    return st


@scenario("edit", [("/app?index=2", "edit.html")])
def _edit(engine):
    engine.state = edit_state()


@scenario("edit-custom", [("/app?index=2", "edit-custom.html")])
def _edit_custom(engine):
    engine.state = edit_state()
    engine.state["apps"][2]["exit-timeout"] = 15


@scenario("edit-new", [("/app?new=1", "edit-new.html")])
def _edit_new(engine):
    engine.state = edit_state()


@scenario("edit-locked", [("/app?index=7", "edit-locked.html")])
def _edit_locked(engine):
    engine.state = edit_state()
    engine.state["apps"][7].update({"cmd": "/var/home/user/.local/bin/sunshine-apps-ui",
                                    "working-dir": "/var/home/user"})


@scenario("explain", [("/explain?op=hide&index=3", "explain.html")])
def _explain(engine):
    engine.state = edit_state()


def hidden_portal(engine):
    engine.state = edit_state()
    portal = next(a for a in engine.state["apps"] if a["name"] == "Portal: Revolution")
    engine.state["apps"].remove(portal)
    for i, a in enumerate(engine.state["apps"]):
        a["index"] = i
    kept = {k: v for k, v in portal.items() if k not in ("index", "source", "id", "managed")}
    kept["cmd"] = "steam steam://rungameid/601360"
    kept["bsm"] = {"source": "steam", "id": "601360"}
    engine.state["hidden"] = [{"name": portal["name"], "source": "steam", "id": "601360",
                               "image-path": portal["image-path"], "entry": kept}]


@scenario("hidden", [("/app?hidden=steam%3A601360", "hidden.html")])
def _hidden(engine):
    hidden_portal(engine)


@scenario("edit-unhidden", [("/app?hidden=steam%3A601360", "edit-unhidden.html")])
def _edit_unhidden(engine):
    hidden_portal(engine)
    state.enqueue({"op": "restore", "selector": "steam:601360", "name": "Portal: Revolution"})


def osk(address_tail):
    return "/app?index=2&osk=%23name&" + address_tail


@scenario("edit-osk", [(osk("type=%20Ultimate"), "edit-osk.html")])
def _edit_osk(engine):
    engine.state = edit_state()


@scenario("edit-osk-caps", [(osk("type=%20U&press=caps"), "edit-osk-caps.html")])
def _edit_osk_caps(engine):
    engine.state = edit_state()


@scenario("edit-osk-shift", [(osk("type=%20&press=shift"), "edit-osk-shift.html")])
def _edit_osk_shift(engine):
    engine.state = edit_state()


@scenario("edit-osk-symbols", [(osk("type=%3A%20Ultimate&press=symbols"), "edit-osk-symbols.html")])
def _edit_osk_symbols(engine):
    engine.state = edit_state()


# --- artwork (#63, #64, #65) --------------------------------------------------

DESIGN = os.path.join(REPO, "design", "2.0")


def board_sources(board):
    """The pictures a picker board shows, by source, in its order."""
    import re
    html = open(os.path.join(DESIGN, board)).read()
    heads = {"On this machine": "steam-local", "From Steam": "steam-cdn"}
    found = []
    for m in re.finditer(r'<section class="source"><h2>([^<]+?) <span class="n">.*?</section>', html, re.S):
        source = heads[m.group(1).strip()]
        for src in re.findall(r'<img src="img/([^"]+)"', m.group(0)):
            found.append((source, os.path.join(IMG, src)))
    return found


def picker(engine, board, *, key_state="ready"):
    engine.state = edit_state()
    cands = [{"id": f"{i:016x}", "source": source, "label": "Portrait", "path": path, "origin": path}
             for i, (source, path) in enumerate(board_sources(board))]
    engine.candidates = {"ok": True, "candidates": cands, "notes": [],
                         "offer_sgdb": key_state == "none", "sgdb_ready": key_state != "none"}
    if key_state == "refused":
        state.record_sgdb_key("refused")
    # serve() clears drafts as it starts, so run() sets these after it.
    engine.drafts = {"index:2": {"image-path": os.path.join(IMG, "1091500.png")}}


ART = "/artwork?key=index%3A2"


@scenario("artwork", [(ART, "artwork.html")])
def _artwork(engine):
    picker(engine, "artwork.html")


@scenario("artwork-search", [(ART, "artwork-search.html")])
def _artwork_search(engine):
    picker(engine, "artwork-search.html")


@scenario("artwork-nokey", [(ART, "artwork-nokey.html")])
def _artwork_nokey(engine):
    picker(engine, "artwork-nokey.html", key_state="none")


@scenario("artwork-keyrefused", [(ART, "artwork-keyrefused.html")])
def _artwork_keyrefused(engine):
    picker(engine, "artwork-keyrefused.html", key_state="refused")


@scenario("artwork-empty", [(ART, "artwork-empty.html")])
def _artwork_empty(engine):
    picker(engine, "artwork-empty.html")
    engine.candidates["candidates"] = []
    engine.candidates["notes"] = ["Nothing to suggest for this app. Browse for a file instead."]


def sgdb(engine, *, page=1, count=30, total=689, status="", note=""):
    import re
    picker(engine, "artwork.html")
    html = open(os.path.join(DESIGN, "artwork-sgdb.html")).read()
    srcs = re.findall(r'<a class="pick"[^>]*><img src="img/([^"]+)"', html)[:count]
    engine.sgdb = {"ok": True, "note": note, "total": total, "page": page, "pages": (total + 29) // 30,
                   "status": status,
                   "candidates": [{"id": f"{i:016x}", "source": "sgdb", "label": "by someone",
                                   "origin": os.path.join(IMG, src)} for i, src in enumerate(srcs)]}
    # A picture of this page is fetched by id; here the "origin" is the file.
    mock.patch.object(srv, "art_sgdb_one", lambda conf_dir, origin: origin).start()


@scenario("artwork-sgdb", [(ART + "&sgdb=1&sgdb_page=1&go=1", "artwork-sgdb.html")])
def _artwork_sgdb(engine):
    sgdb(engine)


@scenario("artwork-sgdb-loading", [(ART + "&sgdb=1", "artwork-sgdb-loading.html")])
def _artwork_sgdb_loading(engine):
    sgdb(engine)
    # The spinner is only on screen until its refresh fires; for a capture,
    # the page is sent without it. (Blocking the fetch instead stalled the
    # window for every capture after this one.)
    real_page = srv.sgdb_artwork_page
    mock.patch.object(srv, "sgdb_artwork_page",
                      lambda *a, **k: real_page(*a, **dict(k, refresh_to=""))).start()


@scenario("artwork-sgdb-unreachable", [(ART + "&sgdb=1&go=1", "artwork-sgdb-unreachable.html")])
def _artwork_sgdb_unreachable(engine):
    sgdb(engine, page=0, count=0, total=0, status="unreachable", note="SteamGridDB did not answer.")


@scenario("artwork-sgdb-empty", [(ART + "&sgdb=1&go=1", "artwork-sgdb-empty.html")])
def _artwork_sgdb_empty(engine):
    sgdb(engine, page=0, count=0, total=0, note="SteamGridDB has no artwork for this one.")


@scenario("browse", [("/browse?key=index%3A2&field=cmd&path=%2Fhome%2Fuser%2FGames", "browse.html")])
def _browse(engine):
    engine.state = edit_state()
    g = "/home/user/Games"
    engine.listing = {"ok": True, "path": g, "parent": "/home/user", "entries":
                      [{"name": n, "path": f"{g}/{n}", "type": "directory"}
                       for n in ("Cyberpunk 2077", "Enshrouded", "Hades II", "Heroic", "NIMRODS", "Satisfactory")]
                      + [{"name": n, "path": f"{g}/{n}", "type": "file"} for n in ("launch-cyberpunk.sh", "README.txt")]}


def covers(engine):
    import re
    engine.state = edit_state()
    html = open(os.path.join(DESIGN, "browse-art.html")).read()
    shown = re.findall(r'<a class="pick"[^>]*><img src="img/([^"]+)" alt=""><span class="fname">([^<]+)</span>', html)
    here = "/home/user/Pictures/covers"
    entries = [{"name": n, "path": f"{here}/{n}", "type": "directory"}
               for n in ("Old covers", "Wallpapers", "Box art", "Fan art", "Heroes", "Logos", "Screenshots", "Steam grid")]
    entries += [{"name": name, "path": os.path.join(IMG, src), "type": "file"} for src, name in shown]
    spare = sorted(os.listdir(os.path.join(IMG, "cand")))[10:]
    entries += [{"name": f"cyberpunk-more-{i:02d}.png", "path": os.path.join(IMG, "cand", spare[i]), "type": "file"}
                for i in range(12)]
    entries.append({"name": "2077-cover.png", "path": os.path.join(IMG, "cand", spare[12]), "type": "file"})
    engine.listing = {"ok": True, "path": here, "parent": "/home/user/Pictures", "entries": entries}


@scenario("browse-art", [("/browse?key=index%3A2&field=image-path&path=%2Fhome%2Fuser%2FPictures%2Fcovers", "browse-art.html")])
def _browse_art(engine):
    covers(engine)


@scenario("browse-art-filter", [("/browse?key=index%3A2&field=image-path&path=%2Fhome%2Fuser%2FPictures%2Fcovers&filter=1",
                                 "browse-art-filter.html")])
def _browse_art_filter(engine):
    covers(engine)


# --- settings (#66) --------------------------------------------------------------

def settings_base(engine):
    """Streamed from the Legion, as every settings board is drawn."""
    engine.state = edit_state()
    os.environ["BSM_UI_VIA_SUNSHINE"] = "1"
    os.environ["SUNSHINE_CLIENT_NAME"] = "Legion Go S"


@scenario("settings", [("/settings?section=appearance", "settings.html")])
def _settings(engine):
    settings_base(engine)


@scenario("settings-language", [("/settings?section=language", "settings-language.html")])
def _settings_language(engine):
    settings_base(engine)


@scenario("settings-art", [("/settings?section=art", "settings-art.html")])
def _settings_art(engine):
    settings_base(engine)


@scenario("settings-art-osk", [("/settings?section=art&osk=%23sgdb-key&type=3f9a0c7e41b2", "settings-art-osk.html")])
def _settings_art_osk(engine):
    settings_base(engine)


@scenario("settings-art-refused", [("/settings?section=art", "settings-art-refused.html")])
def _settings_art_refused(engine):
    settings_base(engine)
    state.set_pref("sgdb_key_state", {"state": "refused", "at": "2026-09-27"})


@scenario("settings-sunshine", [("/settings?section=sunshine", "settings-sunshine.html")])
def _settings_sunshine(engine):
    import time
    settings_base(engine)
    stamp = lambda text: time.mktime(time.strptime(text, "%Y-%m-%d %H:%M"))
    config = {"how": "newest", "chosen": NATIVE, "queued": 0,
              "candidates": [{"path": NATIVE, "apps": 12, "last_used": stamp("2026-09-27 16:13")},
                             {"path": FLATPAK, "apps": 1, "last_used": stamp("2026-09-26 07:38")}]}
    mock.patch.object(srv.PlanHandler, "_config_panel", lambda self: dict(config)).start()


@scenario("settings-defaults", [("/settings?section=defaults", "settings-defaults.html")])
def _settings_defaults(engine):
    settings_base(engine)
    engine.state["apps"] = [a for a in engine.state["apps"] if a["name"] != "Zz Steam Big Picture"]
    from sunshine_apps_ui.core import system_apps
    shipped = [{"name": "Desktop"}, {"name": "Low Res Desktop"}, {"name": "Steam Big Picture"}]
    mock.patch.object(system_apps, "find_system_apps_json", lambda override="": "/usr/share/sunshine/apps.json").start()
    mock.patch.object(system_apps, "load_system_apps", lambda path: shipped).start()


class _Always(dict):
    """A check's answer that every capture of the page sees, not just the first."""
    def __init__(self, value):
        super().__init__()
        self.value = value

    def pop(self, *a, **k):
        return self.value


@scenario("settings-updates", [("/settings?section=updates", "settings-updates.html")])
def _settings_updates(engine):
    from sunshine_apps_ui import updates
    settings_base(engine)
    release = updates.Release(updates.Version(2, 0, 1, None), "https://github.com/4o66/sunshine-apps-ui/releases", {})
    answer = updates.Answer("available", "2.0.1 is available.", release)
    mock.patch.object(srv, "_LAST_CHECK", _Always(answer)).start()
    mock.patch.object(updates, "running", lambda: updates.Version(2, 0, 0, None)).start()


# --- flow screens (#67, #68, #69, #70) ------------------------------------------

def streamed(engine):
    engine.state = board_state(without=["NIMRODS"])
    os.environ["BSM_UI_VIA_SUNSHINE"] = "1"
    os.environ["SUNSHINE_CLIENT_NAME"] = "Legion Go S"


def two_changes():
    edited("Satisfactory")
    found_by_scan("NIMRODS")


@scenario("confirm", [("/apply", "confirm.html")])
def _confirm(engine):
    streamed(engine)
    two_changes()


@scenario("applied", [("/applied", "applied.html")])
def _applied(engine):
    streamed(engine)


@scenario("scanning", [("/scanning", "scanning.html")])
def _scanning(engine):
    from sunshine_apps_ui import scanjob
    streamed(engine)
    running = {"running": True, "ran": True, "latest": "Steam: 7 found. Now looking in Heroic.", "elapsed": 4.2, "error": ""}
    mock.patch.object(scanjob.job, "status", lambda *a, **k: dict(running)).start()
    mock.patch.object(scanjob.job, "running", lambda *a, **k: True).start()


@scenario("backups", [("/backups", "backups.html")])
def _backups(engine):
    streamed(engine)
    engine.copies = [{"name": f"apps-{stamp}.json", "apps": n, "readable": True}
                     for stamp, n in (("20260927-005946", 12), ("20260926-211403", 11), ("20260926-092837", 11),
                                      ("20260922-163710", 9), ("20260919-180255", 7))]


@scenario("connect", [("/connect?set=u%3Dsunshine%3Bp%3Dhunter2hunter2", "connect.html")])
def _connect(engine):
    streamed(engine)
    engine.auth = (True, "ok")


@scenario("leaving", [("/_page/leaving", "leaving.html")])
def _leaving(engine):
    streamed(engine)


@scenario("closing", [("/_page/closing", "closing.html")])
def _closing(engine):
    streamed(engine)


@scenario("error", [("/_page/error", "error.html")])
def _error(engine):
    streamed(engine)


@scenario("elevate", [("/_page/elevate", "elevate.html")])
def _elevate(engine):
    streamed(engine)


# Report a bug and Share the log, with the log and machine the Share board shows.
SHARE_LOG = """\
20:31:02 WARNING Sunshine config: /home/deck/.config/sunshine
20:31:02 WARNING launcher: window started (WebKitGTK 2.54) on living-room-pc
20:31:07 WARNING http://127.0.0.1:47999/?token=Zq81XbVn0pLr
20:31:09 WARNING pad: Sunshine (libvirtualhid) X-Box Series Controller, 17 buttons, 4 axes, X and Y swapped
20:31:09 WARNING host: pad 045e:0b13 v0513 bus 0005: Sunshine (libvirtualhid) X-Box Series Controller, at 7e:a1:02:33:44:55
20:32:14 WARNING scan: steam: 7 found in /mnt/games/SteamLibrary
20:32:14 WARNING scan: steam: Satisfactory has no cover in the library cache
20:32:15 WARNING scan: heroic: library not found at /home/deck/.config/heroic
20:33:40 ERROR apply: Sunshine did not answer at https://192.168.1.20:47990: connection refused
"""
SHARE_LOG += "".join(f"20:34:0{i} WARNING backups: kept /home/deck/.config/sunshine/backups/apps-{i}.json\n"
                     for i in range(10))
SHARE_LOG += "20:35:00 WARNING scan: heroic: /home/deck/Games/Heroic, /home/deck/Games/Heroic/Prefixes\n"
SHARE_LOG += "20:35:01 WARNING host: living-room-pc.local at 192.168.1.44, and living-room-pc\n"
SHARE_LOG += "20:35:02 WARNING scan: steam: found Hades, Celeste, Balatro, Hollow Knight, Portal 2, Stardew Valley\n"
SHARE_GAMES = ["Satisfactory", "Hades", "Celeste", "Balatro", "Hollow Knight", "Portal 2", "Stardew Valley"]


def reporting(engine):
    streamed(engine)
    from sunshine_apps_ui import logshare
    mock.patch.object(srv, "_describe_platform", lambda *a, **k: "Bazzite 44 · KDE Plasma · Wayland").start()
    mock.patch.object(srv, "_read_log", lambda: SHARE_LOG).start()
    mock.patch.object(logshare, "machine_facts", lambda **k: logshare.Facts(
        home="/home/deck", user="deck", hostname="living-room-pc", games=SHARE_GAMES)).start()
    srv._PAD_LOGGED["name"] = "Sunshine (libvirtualhid) X-Box Series Controller"


@scenario("report", [("/report", "report.html")])
def _report(engine):
    reporting(engine)


@scenario("report-share", [("/report/share", "report-share.html")])
def _report_share(engine):
    reporting(engine)


@scenario("report-shared", [("/_page/shared", "report-shared.html")])
def _report_shared(engine):
    reporting(engine)


@scenario("controller-test-start", [("/report/controller", "controller-test-start.html")])
def _pad_start(engine):
    reporting(engine)


@scenario("controller-test", [("/report/controller?padtest=22%3Brup%3Dbutton%3A7%3Bleft%3D5", "controller-test.html")])
def _pad_running(engine):
    reporting(engine)


@scenario("controller-test-done", [("/_page/controller-done", "controller-test-done.html")])
def _pad_done(engine):
    reporting(engine)


def flow_page(handler, name):
    """Pages that only follow a POST or a failure, rendered for a capture."""
    from sunshine_apps_ui import render
    if name == "leaving":
        return render.leaving_with_changes_page(handler.token, 2)
    if name == "closing":
        return render.closing_page(True)
    if name == "elevate":
        return render.render_elevating(handler.token)
    if name == "shared":
        return render.shared_page("https://dpaste.com/7QXGJ4K2M")
    if name == "controller-done":
        results = {p: "ok" for p in render.PAD_TEST_ORDER}
        results.update(rup="button:7", rdown="missed")
        return render.controller_test_page("Sunshine (libvirtualhid) X-Box Series Controller", results)
    if name == "error":
        return render.error_page("Sunshine did not answer at https://localhost:47990. It may still be starting.")
    return None


# What the address asks for, for a capture: ?theme=, ?scale=couch|desk (couch
# is streamed and in controller use, as the boards are drawn) and ?focus=, the
# control the board shows focused ("text:Keep this one", or a CSS selector).
LOOK = {"theme": None, "scale": None}

DRIVE_JS = r"""(function(){
var me=location.pathname+location.search;
var q=new URLSearchParams(location.search), f=q.get("focus"), osk=q.get("osk"), typed=q.get("type")||"", press=q.get("press")||"";
(q.get("set")||"").split(";").filter(Boolean).forEach(function(pair){var i=pair.indexOf("=");
 var el=document.getElementById(pair.slice(0,i));if(el)el.value=pair.slice(i+1);});
function find(spec,within){var el=null;within=within||document;
 if(spec.indexOf("text:")===0){var t=spec.slice(5);
  Array.prototype.forEach.call(within.querySelectorAll("a,button"),function(c){if(!el&&c.textContent.trim()===t)el=c;});}
 else el=within.querySelector(spec);
 return el;}
function put(){
 if(osk&&window.OSK){var field=document.querySelector(osk);field.focus();window.OSK.open(field);
  var k=window.OSK.area();
  typed.split("").forEach(function(ch){
   if(ch===" "){k.querySelector('[data-do=space]').click();return;}
   if(ch!==ch.toLowerCase()){k.querySelector('[data-do=shift]').click();}
   var key=k.querySelector('[data-type="'+ch.replace(/"/g,'\\"')+'"]');if(key)key.click();});
  press.split(",").filter(Boolean).forEach(function(d){k.querySelector('[data-do="'+d+'"]').click();});}
 if(!f)return;var el=find(f,osk&&window.OSK?window.OSK.area():document);
 if(el){el.focus({preventScroll:true,focusVisible:true});
  if(el.tagName==="INPUT"&&el.type==="text"){try{el.setSelectionRange(0,0)}catch(e){}}}}
var pt=q.get("padtest");
function padtest(){if(!pt||!window.PADTEST)return;var bits=pt.split(";"),at=+bits[0],left=8,res={};
 var order=["a","b","x","y","lb","rb","lt","rt","view","menu","l3","r3","dup","ddown","dleft","dright","lup","ldown","lleft","lright","rup","rdown","rleft","rright"];
 order.slice(0,at-1).forEach(function(k){res[k]={kind:"ok"};});
 bits.slice(1).forEach(function(b){var i=b.indexOf("="),k=b.slice(0,i),v=b.slice(i+1);
  if(k==="left"){left=+v;return;}var j=v.indexOf(":");res[k]=j<0?{kind:v}:{kind:v.slice(0,j),value:v.slice(j+1)};});
 window.PADTEST.show(at,res,left);}
addEventListener("DOMContentLoaded",padtest);
if(document.readyState==="complete")put();else addEventListener("DOMContentLoaded",put);
setInterval(function(){fetch('/_target',{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){
t=t.trim();if(t&&t!==me){location.replace(t)}}).catch(function(){})},300)})();"""


def run(name, port, streamed, pad, drive_dir=None):
    setup, pages = SCENARIOS[name]
    tmp = tempfile.mkdtemp(prefix="design-states-")
    os.environ["XDG_STATE_HOME"] = tmp
    os.environ["BSM_UI_VIA_SUNSHINE"] = "1" if streamed else "0"
    engine = test_server.FakeEngine()
    for fn in ("get_state", "run_plan", "mutate", "browse", "art_search", "art_sgdb",
               "art_choose", "list_backups", "backup_diff", "check_auth", "save_auth"):
        mock.patch.object(srv, fn, getattr(engine, fn)).start()
    mock.patch.object(security, "check", lambda *a, **k: (True, "")).start()
    # The boards' pictures live in design/2.0/img, where the real app's
    # candidates would be in the config's own cache; let the image route show
    # them. Nothing outside that folder is added.
    from sunshine_apps_ui import artwork as art_mod
    real_allowed = art_mod.allowed_paths
    mock.patch.object(art_mod, "allowed_paths", lambda *a, **k: real_allowed(*a, **k) | {
        os.path.join(root, f) for root, _, files in os.walk(IMG) for f in files}).start()
    mock.patch.object(security, "token_matches", lambda *a, **k: False).start()
    real_open = frame.html_open

    def html_open(theme_name=None):
        if LOOK["theme"]:
            theme_name = LOOK["theme"]
        if LOOK["scale"]:
            frame.set_context(streamed=LOOK["scale"] == "couch")
        opened = real_open(theme_name)
        if pad or LOOK["scale"] == "couch":
            opened = opened.replace('class="', 'class="pad ', 1)
        return opened

    mock.patch.object(frame, "html_open", html_open).start()
    setup(engine)

    drive_dir = drive_dir or tmp
    target_file = os.path.join(drive_dir, ".target")
    served_file = os.path.join(drive_dir, ".served")
    real_get = srv.PlanHandler.do_GET

    def do_get(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path in ("/_target", "/_drive.js", "/drive"):
            if path == "/_drive.js":
                body = DRIVE_JS.encode()
                kind = "text/javascript"
            else:
                try:
                    body = open(target_file, "rb").read().strip()
                except OSError:
                    body = pages[0][0].encode()
                kind = "text/plain"
                if path == "/drive":
                    self.send_response(303); self.send_header("Location", body.decode()); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body); return
        query = parse_qs(parts.query)
        LOOK["theme"] = (query.get("theme") or [None])[0]
        LOOK["scale"] = (query.get("scale") or [None])[0]
        if path.startswith("/_page/"):
            body = flow_page(self, path[len("/_page/"):])
            if body is not None:
                self._send(200, body)
                with open(served_file, "w") as handle:
                    handle.write(self.path)
                return
        real_get(self)
        # Pages only: a window that fetches the scripts again with each page
        # (WebView2 does) would otherwise leave "/pad.js" as the last served.
        if not path.endswith((".js", ".css")) and not path.startswith(("/art", "/scan/status", "/_")):
            with open(served_file, "w") as handle:
                handle.write(self.path)

    mock.patch.object(srv.PlanHandler, "do_GET", do_get).start()
    real_pad = srv.with_pad
    mock.patch.object(srv, "with_pad", lambda page: real_pad(page).replace(
        "</head>", '<script src="/_drive.js" defer></script></head>', 1)).start()

    httpd = srv.serve("design-states", tempfile.mkdtemp(), {}, port=port)
    for draft_key, values in (getattr(engine, "drafts", None) or {}).items():
        state.set_draft(draft_key, values)
    # No console under pythonw.exe (Windows, so no window covers the app).
    if sys.stdout is not None:
        print(json.dumps({"scenario": name, "port": httpd.server_address[1], "state": tmp,
                          "pages": pages}), flush=True)
    httpd.serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scenario", choices=sorted(SCENARIOS) + ["list"])
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--streamed", action="store_true")
    p.add_argument("--pad", action="store_true")
    p.add_argument("--drive-dir", help="where .target and .served live (default: the state folder)")
    a = p.parse_args()
    if a.scenario == "list":
        for name, (_, pages) in sorted(SCENARIOS.items()):
            for address, board in pages:
                print(name, board, address)
        return
    run(a.scenario, a.port, a.streamed, a.pad, a.drive_dir)


if __name__ == "__main__":
    main()
