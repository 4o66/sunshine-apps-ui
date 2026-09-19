# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys, re, json, tempfile, shutil, time

def _stderr_is_a_terminal() -> bool:
    """Whether to colour the output, asked without assuming there is any.

    Started by pythonw.exe a process has no stderr at all -- sys.stderr is
    None, not a closed file -- and this line ran at import time, so the whole
    program died with AttributeError before main() was reached. The Start menu
    shortcut did nothing at all and left nothing to say why.
    """
    stream = getattr(sys, "stderr", None)
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, ValueError):
        return False


is_tty = _stderr_is_a_terminal() or (os.getenv("FORCE_COLOR","0")=="1")
Y = "\033[33m" if is_tty else ""
R = "\033[0m"  if is_tty else ""

def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    stream = getattr(sys, "stderr", None) or getattr(sys, "stdout", None)
    if stream is None:
        return          # nowhere to say it; not a reason to fail
    print(f"[{ts}] {msg}", file=stream)

def yn(s: str) -> str:
    return f"{Y}{s}{R}"

def have_cmd(name: str) -> bool:
    return shutil.which(name) is not None

def slugify(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_").lower() or "unnamed"

def ensure_obj_with_apps(data):
    if isinstance(data, list): return {"apps": data}
    if isinstance(data, dict):
        data["apps"] = list(data.get("apps") or []); return data
    return {"apps": []}

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)
