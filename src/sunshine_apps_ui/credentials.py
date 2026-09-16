# SPDX-License-Identifier: GPL-3.0-or-later
"""Asking for a secret, without it reaching argv, ps, or shell history.

Both of these were shell scripts. They are here for the same reason the
launcher is: the next platform has no bash, and one description of a careful
thing is better than two that drift.

Nothing here is ever passed as an argument. That is the whole point: argv is
visible in ps and lands in shell history, which is how the project this grew
out of leaked its SteamGridDB key.
"""

import getpass
import sys
from typing import Callable, Optional, Tuple

from .core import api

Ask = Callable[[str], str]


def _ask(prompt: str) -> str:
    return getpass.getpass(prompt)


def capture_sunshine_credentials(conf_dir: str, *, ask: Optional[Ask] = None,
                                 ask_visible: Optional[Callable[[str], str]] = None
                                 ) -> Tuple[bool, str]:
    """Prompt for Sunshine's web UI login, verify it, store it mode 600.

    Verified before it is written, so a typo fails here rather than silently
    later, when it looks like Sunshine has stopped answering.
    """
    ask = ask or _ask
    ask_visible = ask_visible or input
    username = ask_visible("Sunshine web UI username: ").strip()
    password = ask("Sunshine web UI password: ")
    again = ask("Confirm password: ")

    if password != again:
        return False, "Passwords do not match; nothing written."
    if not username or not password:
        return False, "Username and password are both required; nothing written."
    ok, message = api.save_auth(conf_dir, username, password)
    del password, again
    return ok, message if ok else f"{message} Nothing was written."


def capture_sgdb_key(conf_dir: str, *, ask: Optional[Ask] = None) -> Tuple[bool, str]:
    """Prompt for a SteamGridDB key, check it against the API, store it mode 600.

    Get one from https://www.steamgriddb.com/profile/preferences/api -- it is
    free, and it is what makes community artwork available for games Steam has
    no cover for. Checking it here means a bad paste fails now rather than
    looking, weeks later, like SteamGridDB having nothing for anything.
    """
    ask = ask or _ask
    key = ask("SteamGridDB API key: ").strip()
    if not key:
        return False, "No key given; nothing written."
    ok, message = api.save_sgdb(conf_dir, key)
    del key
    return ok, message if ok else f"{message} Nothing was written."


def main(which: str, conf_dir: str) -> int:
    capture = (capture_sunshine_credentials if which == "sunshine"
               else capture_sgdb_key)
    ok, message = capture(conf_dir)
    print(message, file=sys.stderr)
    if ok:
        print("Nothing was echoed and no value appears in your shell history.",
              file=sys.stderr)
    return 0 if ok else 1
