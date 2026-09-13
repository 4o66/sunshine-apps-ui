"""Running the importer and reading its plan document.

The only supported interface between the two projects is the CLI contract:
`sunshine-import --dry-run --json` writes a versioned document to stdout and its
logging to stderr. We never import the importer's Python -- it is not a package,
and it claims the top-level names `common` and `importers`.
"""

import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import SUPPORTED_SCHEMA

# Where the importer usually ends up, in preference order.
_CANDIDATES = (
    "~/.local/bin/sunshine-import",
    "~/.config/sunshine/helper/sunshine-import.sh",
)


class ImporterError(RuntimeError):
    """The importer could not be run, or did not return a usable plan."""


def find_importer(override: str = "") -> str:
    if override:
        path = os.path.abspath(os.path.expanduser(override))
        if not os.path.isfile(path):
            raise ImporterError(f"No importer at {path}")
        return path
    found = shutil.which("sunshine-import")
    if found:
        return found
    for candidate in _CANDIDATES:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    raise ImporterError(
        "Could not find sunshine-import. Put it on PATH or pass --importer PATH."
    )


def parse_plan(stdout: str) -> Dict[str, Any]:
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ImporterError(f"Importer did not return JSON: {e}") from e
    if not isinstance(doc, dict):
        raise ImporterError("Importer returned JSON that is not an object")
    schema = doc.get("schema")
    if schema != SUPPORTED_SCHEMA:
        raise ImporterError(
            f"Plan schema {schema!r} is not supported (this build understands "
            f"{SUPPORTED_SCHEMA}). Update sunshine-apps-ui."
        )
    return doc


def check_auth(importer: str, timeout: int = 30) -> Tuple[bool, str]:
    """Are stored Sunshine credentials present and accepted?"""
    proc = subprocess.run([importer, "--check-auth", "--json"],
                          capture_output=True, text=True, timeout=timeout)
    try:
        doc = json.loads(proc.stdout)
        return bool(doc.get("ok")), str(doc.get("message", ""))
    except json.JSONDecodeError:
        tail = (proc.stderr or "").strip().splitlines()
        return False, tail[-1] if tail else "Could not check credentials"


def save_auth(importer: str, username: str, password: str,
              timeout: int = 30) -> Tuple[bool, str]:
    """Hand credentials to the importer on stdin, which verifies then stores them.

    stdin, never argv: arguments are visible in ps and land in shell history.
    The value is not logged here and is not retained after this call.
    """
    proc = subprocess.run([importer, "--save-auth", "--json"],
                          input=f"{username}\n{password}\n",
                          capture_output=True, text=True, timeout=timeout)
    try:
        doc = json.loads(proc.stdout)
        return bool(doc.get("ok")), str(doc.get("message", ""))
    except json.JSONDecodeError:
        tail = (proc.stderr or "").strip().splitlines()
        return False, tail[-1] if tail else "Could not save credentials"


def run_plan(importer: str, extra_args: Optional[List[str]] = None,
             timeout: int = 180) -> Tuple[Dict[str, Any], str]:
    """Run the importer read-only and return (plan document, its log output)."""
    cmd = [importer, "--dry-run", "--json", *(extra_args or [])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise ImporterError(f"Could not execute {importer}: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise ImporterError(
            f"Importer did not finish within {timeout}s. It resolves cover art over "
            f"the network, so a first run can be slow."
        ) from e

    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
        raise ImporterError(f"Importer exited {proc.returncode}:\n{tail}")

    return parse_plan(proc.stdout), proc.stderr or ""
