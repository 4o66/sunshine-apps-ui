# SPDX-License-Identifier: GPL-3.0-or-later
"""Host facts for the log, so a controller bug report says what the machine had.

Written at startup, at WARNING so they are there without --verbose: which
window opened, the pads the kernel sees (Linux), and Sunshine's gamepad
setting and version. The page engine's version comes with the first page
request (engine_line). None of it is shown anywhere; it is for the log that
Share the log sends, which takes out a pad's Bluetooth address (logshare).

Everything here is best effort: a fact that cannot be read is left out, never
an error.
"""
from __future__ import annotations

import os
import re
import sys
from typing import List, Optional

DEVICES = "/proc/bus/input/devices"
WINDOW_ENV = "BSM_UI_WINDOW"


def _one_line(value: str, limit: int = 100) -> str:
    value = re.sub(r"[\x00-\x1f\x7f,]+", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()[:limit]


def pads(text: str) -> List[str]:
    """One line per joystick in /proc/bus/input/devices."""
    out = []
    for block in text.split("\n\n"):
        handlers = re.search(r"^H: Handlers=(.*)$", block, re.M)
        if not handlers or not re.search(r"\bjs\d+\b", handlers.group(1)):
            continue
        ids = re.search(r"^I: Bus=(\w+) Vendor=(\w+) Product=(\w+) Version=(\w+)", block, re.M)
        name = re.search(r'^N: Name="(.*)"$', block, re.M)
        uniq = re.search(r"^U: Uniq=(\S*)$", block, re.M)
        line = "host: pad"
        if ids:
            bus, vendor, product, version = (x.lower()[-4:] for x in ids.groups())
            line += f" {vendor}:{product} v{version} bus {bus}"
        line += f": {_one_line(name.group(1) if name else '') or 'no name'}"
        if uniq and uniq.group(1):
            line += f", at {_one_line(uniq.group(1), 40)}"
        out.append(line)
    return out


def sunshine_gamepad(conf_dir: str) -> str:
    """Sunshine's gamepad setting, as sunshine.conf has it; auto when unset."""
    try:
        with open(os.path.join(conf_dir, "sunshine.conf"), encoding="utf-8", errors="replace") as f:
            for raw in f:
                m = re.match(r"\s*gamepad\s*=\s*(\S+)", raw)
                if m:
                    return _one_line(m.group(1), 20)
    except OSError:
        return "unknown"
    return "auto"


def sunshine_version(conf_dir: str) -> str:
    """From the start of sunshine.log, where Sunshine writes it."""
    try:
        with open(os.path.join(conf_dir, "sunshine.log"), encoding="utf-8", errors="replace") as f:
            head = f.read(16384)
    except OSError:
        return ""
    m = re.search(r"Sunshine version:\s*(\S+)", head)
    return _one_line(m.group(1), 40) if m else ""


def host_lines(conf_dir: str, environ: Optional[dict] = None,
               devices: str = DEVICES) -> List[str]:
    environ = os.environ if environ is None else environ
    lines = [f"host: window {_one_line(environ.get(WINDOW_ENV, '') or 'not known', 80)}"]
    if sys.platform.startswith("linux"):
        try:
            with open(devices, encoding="utf-8", errors="replace") as f:
                found = pads(f.read())
        except OSError:
            found = None
        if found is None:
            lines.append("host: pads not readable")
        else:
            lines.extend(found or ["host: no pads"])
    version = sunshine_version(conf_dir)
    lines.append(f"host: Sunshine {version or 'version not known'}, gamepad {sunshine_gamepad(conf_dir)}")
    return lines


def engine_line(user_agent: str) -> str:
    """The page engine and its version, from a request's User-Agent."""
    ua = user_agent or ""
    m = re.search(r"sunshine-apps-ui-window/(\S+)", ua)
    if m:
        return f"host: engine WebKitGTK {_one_line(m.group(1), 20)}"
    m = re.search(r"Edg/(\S+)", ua)
    if m:
        return f"host: engine WebView2 or Edge {_one_line(m.group(1), 20)}"
    m = re.search(r"(Chrome|Firefox)/(\S+)", ua)
    if m:
        return f"host: engine {m.group(1)} {_one_line(m.group(2), 20)}"
    return f"host: engine {_one_line(ua, 120) or 'not known'}"
