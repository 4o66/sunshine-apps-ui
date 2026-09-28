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


# What the address asks for, for a capture: ?theme=, ?scale=couch|desk (couch
# is streamed and in controller use, as the boards are drawn) and ?focus=, the
# control the board shows focused ("text:Keep this one", or a CSS selector).
LOOK = {"theme": None, "scale": None}

DRIVE_JS = r"""(function(){
var me=location.pathname+location.search;
var q=new URLSearchParams(location.search), f=q.get("focus"), osk=q.get("osk"), typed=q.get("type")||"", press=q.get("press")||"";
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
        real_get(self)
        with open(served_file, "w") as handle:
            handle.write(self.path)

    mock.patch.object(srv.PlanHandler, "do_GET", do_get).start()
    real_pad = srv.with_pad
    mock.patch.object(srv, "with_pad", lambda page: real_pad(page).replace(
        "</head>", '<script src="/_drive.js" defer></script></head>', 1)).start()

    httpd = srv.serve("design-states", tempfile.mkdtemp(), {}, port=port)
    for draft_key, values in (getattr(engine, "drafts", None) or {}).items():
        state.set_draft(draft_key, values)
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
