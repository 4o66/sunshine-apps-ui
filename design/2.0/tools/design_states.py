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
from urllib.parse import urlsplit

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


def board_state():
    return {
        "schema": 1, "generator": {"name": "bazzite-sunshine-manager", "version": "2.0"},
        "config_dir": "/var/home/user/.config/sunshine",
        "apps_json": "/var/home/user/.config/sunshine/apps.json",
        "apps": [dict(a) for a in BOARD_APPS], "hidden": [],
    }


# name -> (setup(engine), [(address, board file)])
SCENARIOS = {}


def scenario(name, pages):
    def register(setup):
        SCENARIOS[name] = (setup, pages)
        return setup
    return register


@scenario("grid", [("/", "grid.html")])
def _grid(engine):
    engine.state = board_state()
    state.enqueue({"op": "edit", "index": 6, "name": "Satisfactory",
                   "fields": {"image-path": os.path.join(IMG, "satisfactory.png")}})
    state.enqueue({"op": "add", "name": "NIMRODS", "source": "steam", "id": "2086430"})


def run(name, port, streamed, pad):
    setup, pages = SCENARIOS[name]
    tmp = tempfile.mkdtemp(prefix="design-states-")
    os.environ["XDG_STATE_HOME"] = tmp
    os.environ["BSM_UI_VIA_SUNSHINE"] = "1" if streamed else "0"
    engine = test_server.FakeEngine()
    for fn in ("get_state", "run_plan", "mutate", "browse", "art_search", "art_sgdb",
               "art_choose", "list_backups", "backup_diff", "check_auth", "save_auth"):
        mock.patch.object(srv, fn, getattr(engine, fn)).start()
    mock.patch.object(security, "check", lambda *a, **k: (True, "")).start()
    mock.patch.object(security, "token_matches", lambda *a, **k: False).start()
    if pad:
        real_open = frame.html_open
        mock.patch.object(frame, "html_open",
                          lambda t=None: real_open(t).replace('class="', 'class="pad ', 1)).start()
    setup(engine)

    target_file = os.path.join(tmp, ".target")
    served_file = os.path.join(tmp, ".served")
    real_get = srv.PlanHandler.do_GET

    def do_get(self):
        path = urlsplit(self.path).path
        if path in ("/_target", "/_drive.js", "/drive"):
            if path == "/_drive.js":
                body = (b"(function(){var me=location.pathname+location.search;setInterval(function(){"
                        b"fetch('/_target',{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){"
                        b"t=t.trim();if(t&&t!==me){location.replace(t)}}).catch(function(){})},300)})();")
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
        with open(served_file, "w") as handle:
            handle.write(self.path)
        return real_get(self)

    mock.patch.object(srv.PlanHandler, "do_GET", do_get).start()
    real_pad = srv.with_pad
    mock.patch.object(srv, "with_pad", lambda page: real_pad(page).replace(
        "</head>", '<script src="/_drive.js" defer></script></head>', 1)).start()

    httpd = srv.serve("design-states", tempfile.mkdtemp(), {}, port=port)
    print(json.dumps({"scenario": name, "port": httpd.server_address[1], "state": tmp,
                      "pages": pages}), flush=True)
    httpd.serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scenario", choices=sorted(SCENARIOS) + ["list"])
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--streamed", action="store_true")
    p.add_argument("--pad", action="store_true")
    a = p.parse_args()
    if a.scenario == "list":
        for name, (_, pages) in sorted(SCENARIOS.items()):
            print(name, " ".join(board for _, board in pages))
        return
    run(a.scenario, a.port, a.streamed, a.pad)


if __name__ == "__main__":
    main()
