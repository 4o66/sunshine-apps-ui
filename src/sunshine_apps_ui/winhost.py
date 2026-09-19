# SPDX-License-Identifier: GPL-3.0-or-later
"""A window of our own on Windows, instead of driving a browser.

**What this is.** ``host/AppWindow.cs`` is a WinForms window with a WebView2
control in it, compiled on the machine it will run on by the ``csc.exe`` that
is part of Windows. This module finds that compiler, fetches the three
assemblies the control needs, builds the window, and proves it runs before
letting anything depend on it.

**Why, in numbers.** Measured on the rig on 2026-09-18, in the interactive
session, against the real server, timed from process creation:

=====================  ==================  ==============
host                   window on screen    app rendered
=====================  ==================  ==============
this, frameless        0.36 s              1.48 s
this, framed           0.41 s              2.00 s
pywebview + WebView2   1.94 s              3.35 s
a browser              --                  ~3.6 s
=====================  ==================  ==============

and, with no WebView2 runtime available, this fails in 0.36 s with an error a
caller can act on, where pywebview put a blank window on screen and hung until
it was killed at 40 seconds.

**Why it is compiled here rather than shipped built.** Everything else about
this program is readable on the machine it runs on, which is the argument
``interpreter.py`` makes for unpacking a published CPython rather than freezing
one. A binary we built elsewhere would be the one part nobody could check. The
compiler needed is already present on every Windows install -- there is no
toolchain to fetch and nothing to install -- so the source can ship instead.

**The browser is still there.** Nothing here is required. No compiler, no
runtime, a build that fails, a machine that is not Windows: in every case
``find_browsers`` simply does not offer this window and the browser path runs
exactly as it did. That is why every failure below returns a reason rather than
raising into the launcher.
"""

import os
import shutil
import subprocess
import tempfile
import zipfile
from typing import Callable, List, Optional

from .interpreter import Artifact, ProvisionError, _download

HOST_DIRNAME = "host"
EXE_NAME = "AppWindow.exe"
SOURCE_NAME = "AppWindow.cs"

# The WebView2 SDK. Only three files out of nine megabytes are kept: the two
# managed assemblies the control is, and the native loader that finds the
# runtime. Pinned and checked exactly as the interpreter's artifacts are.
WEBVIEW2 = Artifact(
    "Microsoft.Web.WebView2 1.0.4191.47 (SDK)",
    "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/"
    "1.0.4191.47/microsoft.web.webview2.1.0.4191.47.nupkg",
    "f492bbf547d0da329553b6727435b677579b1e9f91cc9e4a1ad029366d5f23d0",
    9259926,
)

# member in the package -> what it is called beside the executable. The x64
# loader, so the build is /platform:x64 and not "whatever this Python is".
ASSEMBLIES = {
    "lib/net462/Microsoft.Web.WebView2.Core.dll": "Microsoft.Web.WebView2.Core.dll",
    "lib/net462/Microsoft.Web.WebView2.WinForms.dll": "Microsoft.Web.WebView2.WinForms.dll",
    "runtimes/win-x64/native/WebView2Loader.dll": "WebView2Loader.dll",
}

REFERENCES = ("Microsoft.Web.WebView2.Core.dll",
              "Microsoft.Web.WebView2.WinForms.dll")

# Where Windows keeps its own C# compiler. 64-bit first, to match /platform:x64
# and the loader above; the 32-bit one produces the same assembly and is only a
# fallback for an install that somehow lacks the other.
COMPILERS = (
    r"Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    r"Microsoft.NET\Framework\v4.0.30319\csc.exe",
)

# Where the runtime records itself. Per-machine first, then per-user: both are
# real installs, and a machine can have only the second.
RUNTIME_KEY = (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
               r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")
RUNTIME_KEY_NATIVE = (r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
                      r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")


def install_root() -> str:
    """The directory the program was installed into.

    This module lives at ``<root>/src/sunshine_apps_ui/winhost.py``, in an
    install and in a checkout alike.
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def host_dir(install_dir: str) -> str:
    return os.path.join(install_dir, HOST_DIRNAME)


def host_exe(install_dir: str) -> str:
    """The window we built, or "" if there is not one."""
    candidate = os.path.join(host_dir(install_dir), EXE_NAME)
    return candidate if os.path.isfile(candidate) else ""


def source_path() -> str:
    """The C# we ship. Shipped, not generated: it is meant to be read."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        HOST_DIRNAME, SOURCE_NAME)


def compiler() -> str:
    """The C# compiler that is part of Windows, or "" on a machine without it."""
    if os.name != "nt":
        return ""
    windows = os.environ.get("SystemRoot") or r"C:\Windows"
    for relative in COMPILERS:
        candidate = os.path.join(windows, relative)
        if os.path.isfile(candidate):
            return candidate
    return ""


def runtime_version() -> str:
    """The WebView2 runtime's version, or "" if there is none.

    Asked before a window is opened rather than after: a machine without the
    runtime should get the browser, not a window that appears and disappears.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key in (RUNTIME_KEY, RUNTIME_KEY_NATIVE):
            try:
                with winreg.OpenKey(root, key) as handle:
                    version = str(winreg.QueryValueEx(handle, "pv")[0]).strip()
                    if version and version != "0.0.0.0":
                        return version
            except OSError:
                continue
    return ""


def works(executable: str) -> bool:
    """Does that window run, with a runtime it can actually use?

    ``--check`` opens nothing. It asks the loader for the runtime's version,
    which means the answer covers the whole chain in one question: the
    executable starts, both assemblies load, the native loader is beside them,
    and there is a runtime for it to find.
    """
    if not executable or not os.path.isfile(executable):
        return False
    try:
        result = subprocess.run(
            [executable, "--check"], capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def is_current(install_dir: str) -> bool:
    """Is the window here built, working, and built from the source we ship?

    The source is copied in beside the executable at build time precisely so
    this question can be asked. Without it every install would re-download nine
    megabytes and rebuild something identical; with it, only a changed window
    is rebuilt.
    """
    exe = host_exe(install_dir)
    if not exe:
        return False
    built_from = os.path.join(host_dir(install_dir), SOURCE_NAME)
    try:
        with open(built_from, "rb") as a, open(source_path(), "rb") as b:
            if a.read() != b.read():
                return False
    except OSError:
        return False
    return works(exe)


def available(install_dir: Optional[str] = None) -> bool:
    """Is there a window here we can open, right now?

    Deliberately cheap -- this is asked on every launch. It does not run the
    executable: ``works()`` is for the install, where being sure is worth a
    process, and here the cost would be paid by the person waiting for a window.
    """
    if os.name != "nt":
        return False
    root = install_dir if install_dir is not None else install_root()
    return bool(host_exe(root)) and bool(runtime_version())


def _extract(archive_path: str, into: str) -> None:
    """Take the three files we need out of the package, and nothing else."""
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        missing = [member for member in ASSEMBLIES if member not in names]
        if missing:
            raise ProvisionError(
                "The WebView2 package does not contain %s. It is not the "
                "package this expects; nothing was installed."
                % ", ".join(missing))
        for member, local in ASSEMBLIES.items():
            with archive.open(member) as source, \
                    open(os.path.join(into, local), "wb") as handle:
                shutil.copyfileobj(source, handle)


def compile_command(csc: str, source: str, output: str, where: str) -> List[str]:
    """What is run to build the window.

    ``/platform:x64`` because the native loader beside it is the x64 one, and a
    32-bit process would not load it.
    """
    command = [csc, "/nologo", "/target:winexe", "/platform:x64",
               "/out:" + output]
    command += ["/reference:" + os.path.join(where, name) for name in REFERENCES]
    command.append(source)
    return command


def build(install_dir: Optional[str] = None,
          log: Optional[Callable[[str], None]] = None) -> str:
    """Build the window beside the program. Returns the path to the executable.

    Built in a directory of its own and moved into place only once it has been
    run and answered -- the same shape as ``interpreter.provision``, and for the
    same reason: replacing something that works with something that does not,
    while reporting success, is the failure that costs an afternoon.
    """
    say = log or (lambda line: None)
    root = install_dir if install_dir is not None else install_root()

    csc = compiler()
    if not csc:
        raise ProvisionError(
            "No C# compiler was found. It is normally part of Windows, at "
            r"%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe.")

    source = source_path()
    if not os.path.isfile(source):
        raise ProvisionError("The window's source (%s) is not here." % source)

    target = host_dir(root)
    staging = target + ".new"
    previous = target + ".old"
    workspace = tempfile.mkdtemp(prefix="sunshine-apps-ui-host-")
    try:
        package = _download(WEBVIEW2, workspace, say)
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)
        _extract(package, staging)
        shutil.copyfile(source, os.path.join(staging, SOURCE_NAME))

        say("Building the window with %s..." % os.path.basename(csc))
        candidate = os.path.join(staging, EXE_NAME)
        result = subprocess.run(
            compile_command(csc, os.path.join(staging, SOURCE_NAME),
                            candidate, staging),
            capture_output=True, cwd=staging,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 or not os.path.isfile(candidate):
            detail = (result.stdout or b"").decode("utf-8", "replace").strip()
            raise ProvisionError(
                "The window would not compile:\n%s" % (detail or "no output"))

        if not works(candidate):
            raise ProvisionError(
                "The window compiled but will not run here. Nothing has been "
                "replaced; this machine will use a browser, as it did before.")

        shutil.rmtree(previous, ignore_errors=True)
        if os.path.isdir(target):
            try:
                os.rename(target, previous)
            except OSError as e:
                raise ProvisionError(
                    "The window already here could not be moved aside (%s). "
                    "Close the manager and try again; nothing has been "
                    "changed." % e) from e
        os.rename(staging, target)
        shutil.rmtree(previous, ignore_errors=True)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)

    say("Window built in %s" % target)
    return os.path.join(target, EXE_NAME)


def describe() -> List[str]:
    """What building it would fetch, for someone who wants to know first."""
    return ["  %s\n    %s\n    sha256 %s"
            % (WEBVIEW2.name, WEBVIEW2.url, WEBVIEW2.sha256)]
