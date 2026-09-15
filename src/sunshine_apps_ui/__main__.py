# SPDX-License-Identifier: GPL-3.0-or-later
"""Start the UI, print its URL, and stop when you close it."""

import argparse
import logging
import sys
import webbrowser

from . import __version__, security
from .importer import ImporterError, find_importer
from .server import serve


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sunshine-apps-ui",
        description="Local web UI showing what bazzite-sunshine-manager would change.",
        epilog="The listener always binds 127.0.0.1. There is no option to change that.",
    )
    parser.add_argument("--port", type=int, default=47999,
                        help="port to listen on (default: 47999; 0 picks a free one)")
    parser.add_argument("--importer", default="",
                        help="path to sunshine-import (default: found on PATH)")
    parser.add_argument("--open", action="store_true", help="open a browser at the URL")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("importer_args", nargs="*",
                        help="extra arguments passed through to the importer, "
                             "e.g. -- --no-heroic")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
    )

    try:
        importer = find_importer(args.importer)
    except ImporterError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    token = security.new_token()
    try:
        httpd = serve(token, importer, args.importer_args, args.port)
    except OSError as e:
        print(f"error: could not bind {security.BIND_HOST}:{args.port}: {e}", file=sys.stderr)
        return 2

    port = httpd.server_address[1]
    url = f"http://{security.BIND_HOST}:{port}/?token={token}"

    print(f"Using importer: {importer}", file=sys.stderr)
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
