# SPDX-License-Identifier: GPL-3.0-or-later
"""A Python of our own, for a Windows machine that has none.

Nobody installs Python to use an app manager. On Linux and macOS there is always
one; on Windows there is not, and "install Python first" is not an instruction to
give someone who wants to see their games on a television.

**What is shipped, and why it is not a frozen executable.** Two artifacts are
fetched and unpacked beside the program: CPython's official *embeddable*
distribution, and the one wheel this depends on. Freezing with PyInstaller was
the other candidate and would produce one file, but it has to be built on
Windows, it turns the program into an opaque blob, and this is GPL software
whose readable source is part of what is being distributed. Unpacking a
published interpreter keeps every line of it inspectable on the machine it runs
on, and needs no build toolchain at all.

**Both artifacts are pinned by SHA-256 and refused if they do not match.** The
interpreter hash is the one python.org publishes in its own SPDX manifest beside
the download, not merely the hash of what arrived here. A download that does not
match is deleted rather than used: this runs elevated, and an interpreter is the
last thing to be relaxed about.

**The `._pth` file is what makes the embeddable distribution usable.** It ships
with `import site` commented out and ignores ``PYTHONPATH`` entirely -- which is
the point of it, and also why simply setting ``PYTHONPATH`` in the launcher does
nothing. The paths this program needs are written into that file instead.
"""

import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from typing import Callable, List, NamedTuple, Optional


class Artifact(NamedTuple):
    name: str
    url: str
    sha256: str
    size: int          # bytes, for the progress line and a cheap sanity check


# CPython 3.12: the version the wheel below is built for. Changing one means
# changing the other, because a binary wheel is tied to the interpreter's ABI.
CPYTHON = Artifact(
    "CPython 3.12.10 (embeddable)",
    "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
    "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3",
    11133606,
)

# Pillow is the only third-party import in the whole program: core/images.py
# needs it to turn artwork into the PNGs Sunshine expects.
PILLOW = Artifact(
    "Pillow 12.3.0 (cp312, win_amd64)",
    "https://files.pythonhosted.org/packages/45/89/da2f7971a317f83d807fdd4065c0af40208e59e692cc43d315a71a0e96d1/"
    "pillow-12.3.0-cp312-cp312-win_amd64.whl",
    "a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09",
    7200000,
)

ARTIFACTS = (CPYTHON, PILLOW)

# What the interpreter is allowed to import from, in order. Relative to the
# directory holding python.exe, which is how CPython reads a ._pth.
PTH_LINES = ("python312.zip", ".", "Lib\\site-packages", "..\\src", "import site")

INTERPRETER_DIRNAME = "python"


class ProvisionError(RuntimeError):
    """The interpreter could not be provided, and nothing was left half-done."""


def interpreter_dir(install_dir: str) -> str:
    return os.path.join(install_dir, INTERPRETER_DIRNAME)


def bundled_python(install_dir: str) -> str:
    """Path to the interpreter we shipped, or "" if there is not one."""
    candidate = os.path.join(interpreter_dir(install_dir), "python.exe")
    return candidate if os.path.isfile(candidate) else ""


def _download(artifact: Artifact, into: str,
              log: Optional[Callable[[str], None]] = None) -> str:
    """Fetch one artifact and prove it is the one we meant to fetch."""
    say = log or (lambda message: None)
    target = os.path.join(into, os.path.basename(artifact.url))
    say(f"Fetching {artifact.name} ({artifact.size // (1024 * 1024)} MB)...")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(artifact.url, timeout=120) as response, \
                open(target, "wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
    except OSError as e:
        raise ProvisionError(f"Could not download {artifact.name}: {e}") from e

    got = digest.hexdigest()
    if got != artifact.sha256:
        # Removed rather than left for someone to find and trust later.
        try:
            os.unlink(target)
        except OSError:
            pass
        raise ProvisionError(
            f"{artifact.name} did not match its published checksum.\n"
            f"  expected {artifact.sha256}\n"
            f"  got      {got}\n"
            f"Nothing was installed. This is either a corrupted download or a "
            f"file that is not what it claims to be; it is not worth running "
            f"either way.")
    return target


def _write_pth(python_dir: str) -> str:
    """Tell the embeddable interpreter where it may import from.

    Without this it imports from nothing but its own zip: ``PYTHONPATH`` is
    ignored by design, so a launcher that sets it accomplishes nothing.
    """
    existing = [name for name in os.listdir(python_dir) if name.endswith("._pth")]
    path = os.path.join(python_dir, existing[0] if existing else "python312._pth")
    with open(path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write("\n".join(PTH_LINES) + "\n")
    return path


def provision(install_dir: str,
              log: Optional[Callable[[str], None]] = None) -> str:
    """Put an interpreter beside the program. Returns the path to python.exe."""
    say = log or (lambda message: None)
    python_dir = interpreter_dir(install_dir)
    workspace = tempfile.mkdtemp(prefix="sunshine-apps-ui-interpreter-")
    try:
        cpython_zip = _download(CPYTHON, workspace, say)
        wheel = _download(PILLOW, workspace, say)

        # Replaced wholesale rather than merged: a half-upgraded interpreter is
        # worse than either version of it.
        if os.path.isdir(python_dir):
            shutil.rmtree(python_dir, ignore_errors=True)
        os.makedirs(python_dir, exist_ok=True)

        with zipfile.ZipFile(cpython_zip) as archive:
            archive.extractall(python_dir)
        packages = os.path.join(python_dir, "Lib", "site-packages")
        os.makedirs(packages, exist_ok=True)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(packages)
        _write_pth(python_dir)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    executable = os.path.join(python_dir, "python.exe")
    if not os.path.isfile(executable):
        raise ProvisionError(
            f"The interpreter did not unpack as expected: no {executable}")
    say(f"Interpreter installed in {python_dir}")
    return executable


def describe() -> List[str]:
    """What would be fetched, for someone who wants to know before it happens."""
    return [f"  {a.name}\n    {a.url}\n    sha256 {a.sha256}" for a in ARTIFACTS]
