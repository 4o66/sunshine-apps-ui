# SPDX-License-Identifier: GPL-3.0-or-later
"""Language: which one this machine is in, and what to say in it.

**Strings ship with the program.** They are a few kilobytes -- `locales/en.json`
is under 4 KB -- so there is nothing to download and nothing to go missing.
Adding a language is a file and a pull request, which is the point.

**Artwork does not.** A tile is a picture with words baked into it, and a full
set is a couple of megabytes per language. `assets/tiles/<code>/` holds a set
where somebody has made one; every other language gets `assets/tiles/_wordless/`,
which has no text at all. That is not a consolation prize: with the Pillow we
ship on Windows there is no text shaping, so Arabic renders unjoined and
left-to-right, Hebrew reversed, and Devanagari and Thai with their marks in the
wrong places. A wordless tile is correct in every language. See
`docs/tile-art.md`.

**Falling back is a chain, not a cliff.** `pt-BR` tries `pt-BR`, then `pt`,
then English -- for strings. For artwork it tries the same, then wordless.
"""

import json
import os
from typing import Any, Dict, List, Optional

DEFAULT = "en"
WORDLESS = "_wordless"


def _root() -> str:
    """The installed tree: <root>/locales and <root>/assets live here."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def locales_dir() -> str:
    return os.path.join(_root(), "locales")


def tiles_dir() -> str:
    return os.path.join(_root(), "assets", "tiles")


def _normalise(tag: str) -> str:
    """`en_GB.UTF-8` and `en-gb` are the same language to us: `en-GB`."""
    tag = (tag or "").strip().replace("_", "-")
    tag = tag.split(".")[0].split("@")[0]
    if not tag:
        return ""
    parts = tag.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        out.append(part.upper() if len(part) == 2 else part.title())
    return "-".join(out)


def system_language() -> str:
    """What language this machine is set to, or "" if it will not say.

    The environment first, because on Linux that is the answer and on Windows
    it is how somebody overrides. Then Windows' own setting, which is the only
    reliable source there: `LANG` is usually unset.
    """
    for name in ("SAU_LANGUAGE", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        # Normalise before judging: "C.UTF-8" is the C locale wearing a suffix,
        # and comparing the raw value lets it through as the language "c".
        found = _normalise(os.environ.get(name, "").split(":")[0])
        if found and found.lower() not in ("c", "posix"):
            return found
    if os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, 85):
                return _normalise(buffer.value)
        except Exception:          # noqa: BLE001 - a preference, never a failure
            pass
    try:
        import locale

        found = _normalise((locale.getdefaultlocale() or ("", ""))[0] or "")
    except Exception:              # noqa: BLE001
        return ""
    # The same guard as above: `locale` happily reports the C locale, which is
    # the absence of a language rather than a language.
    return "" if found.lower() in ("c", "posix") else found


def candidates(tag: str = "") -> List[str]:
    """The chain to try: pt-BR, then pt, then English."""
    tag = _normalise(tag) if tag else system_language()
    chain = []
    while tag:
        if tag not in chain:
            chain.append(tag)
        tag = tag.rpartition("-")[0]
    if DEFAULT not in chain:
        chain.append(DEFAULT)
    return chain


def available() -> List[str]:
    """Every catalogue shipped, by code."""
    try:
        return sorted(name[:-5] for name in os.listdir(locales_dir())
                      if name.endswith(".json"))
    except OSError:
        return []


def _read(code: str) -> Dict[str, Any]:
    path = os.path.join(locales_dir(), code + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


_cache: Dict[str, Dict[str, Any]] = {}


def catalogue(tag: str = "") -> Dict[str, Any]:
    """The best catalogue for *tag*, laid over English so nothing is missing.

    A partial translation is the normal state of a translation: whatever it
    does not say is said in English rather than left blank.
    """
    chain = candidates(tag)
    key = ">".join(chain)
    if key in _cache:
        return _cache[key]

    merged: Dict[str, Any] = {}
    for code in reversed(chain):          # English first, then more specific
        data = _read(code)
        for section, values in data.items():
            if section.startswith("_"):
                continue
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(
                    {k: v for k, v in values.items() if not k.startswith("_")})
    _cache[key] = merged
    return merged


def text(path: str, tag: str = "", **fields) -> str:
    """One string, by "section.key". Returns the key itself if it is missing.

    Showing the key is deliberate: a blank label looks like a rendering bug,
    and `ui.rescan` on a button tells whoever sees it exactly what to fix.
    """
    section, _, key = path.partition(".")
    value = (catalogue(tag).get(section) or {}).get(key)
    if not isinstance(value, str):
        return path
    try:
        return value.format(**fields) if fields else value
    except (KeyError, IndexError, ValueError):
        return value


def tile_set(tag: str = "") -> str:
    """The directory of tile artwork to use. Wordless unless we have the words.

    **English is not a fallback here, unlike for strings.** A French machine
    showing English tiles would be worse than one showing wordless tiles: the
    words would be confidently wrong rather than absent. So the chain is the
    requested tag, then its base language, then no words at all.
    """
    base = tiles_dir()
    asked = candidates(tag)
    if DEFAULT not in (_normalise(tag) if tag else system_language() or ""):
        asked = [code for code in asked if code != DEFAULT]
    for code in asked:
        candidate = os.path.join(base, code)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(base, WORDLESS)


def tile(name: str, tag: str = "") -> str:
    """One tile by name, from the best set, falling back to wordless.

    A set does not have to be complete: a translator who has done the four
    common tiles and not every distribution is still useful, and the rest come
    from the wordless set rather than from nowhere.
    """
    chosen = os.path.join(tile_set(tag), name)
    if os.path.isfile(chosen):
        return chosen
    fallback = os.path.join(tiles_dir(), WORDLESS, name)
    return fallback if os.path.isfile(fallback) else ""


def describe() -> str:
    """One line for the installer: which language, and which artwork."""
    language = system_language() or "unknown"
    chosen = os.path.basename(tile_set())
    if chosen == WORDLESS:
        return f"{language} -- no tile artwork for it, using the wordless set"
    return f"{language} -- tile artwork from assets/tiles/{chosen}"
