# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the UI, print its URL, and stop when you close it."""

import argparse
import logging
import os
import sys
import webbrowser

from . import __version__, security
from .engine import EngineError, config_dir
from .server import serve


def _scan(conf_dir: str, options, *, dry_run: bool, reload: bool) -> int:
    """Run a scan from the command line, for scripts and for the installer.

    The interface is the usual way in, but putting a tile back or refreshing a
    library should not require opening a browser.
    """
    from .core import api
    doc = (api.plan(conf_dir, options) if dry_run
           else api.scan_and_apply(conf_dir, options, reload=reload))
    totals = {k: v for k, v in (doc.get("totals") or {}).items() if v}
    print(("Would change: " if dry_run else "Changed: ")
          + (", ".join(f"{k} {v}" for k, v in sorted(totals.items()))
             or "nothing"), file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sunshine-apps-ui",
        description="Manage the applications Sunshine offers.",
        epilog="The listener always binds 127.0.0.1. There is no option to change that.",
    )
    parser.add_argument("--port", type=int, default=47999,
                        help="port to listen on (default: 47999; 0 picks a free one)")
    parser.add_argument("--conf-dir", default="",
                        help="Sunshine's config directory "
                             "(default: found automatically)")
    parser.add_argument("--serve", action="store_true",
                        help="run the interface and print its URL, without "
                             "opening a window (the bare command opens one)")
    parser.add_argument("--open", action="store_true", help="open a browser at the URL")
    parser.add_argument("--scan", action="store_true",
                        help="scan for applications and write apps.json, without "
                             "starting the interface")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --scan, report what would change and write nothing")
    parser.add_argument("--no-reload", action="store_true",
                        help="with --scan, do not ask Sunshine to re-read the file")
    parser.add_argument("--install", action="store_true",
                        help="install this for the current user")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove this, and its tile, for the current user")
    parser.add_argument("--prefix", default="",
                        help="with --install or --uninstall, where to put it "
                             "(default: ~/.local)")
    parser.add_argument("--keep-state", action="store_true",
                        help="with --uninstall, keep the queue and preferences")
    parser.add_argument("--keep-tile", action="store_true",
                        help="with --uninstall, leave apps.json alone")
    parser.add_argument("--purge-backups", action="store_true",
                        help="with --uninstall, also delete the kept copies of "
                             "apps.json. They are kept by default.")
    parser.add_argument("--put-the-tile-back-because-i-deleted-it",
                        dest="restore_tile", action="store_true",
                        help="with --install, rebuild the launcher tiles so the "
                             "manager's own tile comes back")
    parser.add_argument("--stamp-build", action="store_true",
                        help="write this checkout's build number into the source "
                             "tree, so a copy made from it can still report which "
                             "build it is")
    parser.add_argument("--save-credentials", action="store_true",
                        help="read Sunshine's web UI login from the terminal, "
                             "verify it, and store it mode 600")
    parser.add_argument("--save-sgdb-key", action="store_true",
                        help="read a SteamGridDB key on stdin, check it against "
                             "the API, and store it mode 600. Never as an "
                             "argument: argv is visible in ps and in history")
    parser.add_argument("--browser-helper", default="",
                        help="internal: hold the browser at medium integrity, so "
                             "an elevated launcher never hands it those rights")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("importer_args", nargs="*",
                        help="scan options as NAME=VALUE, e.g. -- IMPORT_HEROIC=0")
    # No arguments at all means "open the interface as a window", which is what
    # Sunshine's tile runs. Anything else is the program being used directly.
    raw = sys.argv[1:] if argv is None else list(argv)
    if not raw:
        from .launcher import launch
        return launch()

    args = parser.parse_args(argv)

    if args.browser_helper:
        # Started by the launcher through the shell, so that this process is
        # unelevated. It owns the job the browser lives in and stays for as
        # long as the window should. See winbrowser.
        from .winbrowser import helper_main
        return helper_main(args.browser_helper)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
    )

    conf_dir = args.conf_dir or config_dir()
    # Installing is the one thing that can sensibly happen before Sunshine has
    # ever run: there is nothing to manage yet, and refusing would mean telling
    # people to install in a particular order for no reason.
    needs_config = not (args.install or args.uninstall)
    if needs_config and not os.path.isdir(conf_dir):
        print(f"error: no Sunshine config directory at {conf_dir}", file=sys.stderr)
        return 2

    options = {}
    for pair in args.importer_args:
        name, _, value = pair.partition("=")
        if not _:
            print(f"error: scan options are NAME=VALUE, not {pair!r}", file=sys.stderr)
            return 2
        options[name] = value

    if args.stamp_build:
        from .installer import stamp_build
        from .version import display
        where = os.path.dirname(os.path.abspath(__file__))
        if stamp_build(where):
            print(f"Stamped {display()} into {where}", file=sys.stderr)
            return 0
        print("Nothing to stamp: no git here, and no build number already "
              "written down.", file=sys.stderr)
        return 1

    if args.install or args.uninstall:
        from .installer import install, uninstall
        prefix = args.prefix or None
        if args.install:
            def confirm(text: str, question: str) -> bool:
                if text:
                    print(text, file=sys.stderr)
                answer = input(f"{question} [y/N] ").strip().lower()
                return answer in ("y", "yes")

            # No terminal, no questions. Passing the callback anyway would make
            # input() raise halfway through an install; passing None lets each
            # question say what it would have asked, which is the useful half
            # of a prompt nobody is there to answer.
            ok, messages = install(
                prefix, confirm=confirm if sys.stdin.isatty() else None)
        else:
            ok, messages = uninstall(prefix, keep_state=args.keep_state,
                                     keep_tile=args.keep_tile,
                                     purge_backups=args.purge_backups)
        for line in messages:
            print(line, file=sys.stderr)
        if ok and args.install and args.restore_tile:
            # Only the launcher entries. The library importers are off so that
            # putting one tile back does not turn into a full scan and a pile
            # of unrelated changes.
            print("\nRebuilding the launcher tiles...", file=sys.stderr)
            return _scan(conf_dir, {"IMPORT_STEAM": "0", "IMPORT_HEROIC": "0"},
                         dry_run=False, reload=True)
        return 0 if ok else 1

    if args.save_credentials:
        from .credentials import main as capture
        return capture("sunshine", conf_dir)

    if args.save_sgdb_key:
        from .core import api
        ok, message = api.save_sgdb(conf_dir, sys.stdin.readline())
        print(message, file=sys.stderr)
        return 0 if ok else 1

    if args.scan:
        return _scan(conf_dir, options, dry_run=args.dry_run,
                     reload=not args.no_reload)

    token = security.new_token()
    try:
        httpd = serve(token, conf_dir, options, args.port)
    except OSError as e:
        print(f"error: could not bind {security.BIND_HOST}:{args.port}: {e}", file=sys.stderr)
        return 2

    port = httpd.server_address[1]
    url = f"http://{security.BIND_HOST}:{port}/?token={token}"

    print(f"Sunshine config: {conf_dir}", file=sys.stderr)
    print(f"\n  {url}\n", file=sys.stderr)
    print("This URL contains a one-time token for this session. Anyone who has it, and\n"
          "can reach this machine's loopback, can read your app list. Ctrl-C to stop.",
          file=sys.stderr)

    if args.open:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
