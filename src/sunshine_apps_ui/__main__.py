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
    parser.add_argument("--open", action="store_true", help="open a browser at the URL")
    parser.add_argument("--scan", action="store_true",
                        help="scan for applications and write apps.json, without "
                             "starting the interface")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --scan, report what would change and write nothing")
    parser.add_argument("--no-reload", action="store_true",
                        help="with --scan, do not ask Sunshine to re-read the file")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("importer_args", nargs="*",
                        help="scan options as NAME=VALUE, e.g. -- IMPORT_HEROIC=0")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
    )

    conf_dir = args.conf_dir or config_dir()
    if not os.path.isdir(conf_dir):
        print(f"error: no Sunshine config directory at {conf_dir}", file=sys.stderr)
        return 2

    options = {}
    for pair in args.importer_args:
        name, _, value = pair.partition("=")
        if not _:
            print(f"error: scan options are NAME=VALUE, not {pair!r}", file=sys.stderr)
            return 2
        options[name] = value

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
