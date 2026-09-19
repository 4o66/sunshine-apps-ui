# SPDX-License-Identifier: GPL-3.0-or-later
"""Is there a newer one, and which one counts as newer.

**What this does not do yet.** It does not install anything. Installing needs a
package to install, and there is not one -- see `docs/packaging.md`. What is
here is the half that can be built and tested now: ask where the releases are,
work out whether any of them is newer than what is running, and say so.

**Two channels.** A release (`1.2.0`) and a development build (`1.2.0.dev314`,
which is a *pre*-release of 1.2.0 and sorts below it). Someone on the
development channel who has 1.2.0.dev314 and is offered 1.2.0 should be moved
up to it, because the release is the same code without the "dev" -- that is the
"upgrade to the standard release if there is no newer dev build" option, and it
is on by default for exactly that reason.

**The repository is private**, so an anonymous request for its releases gets a
404 (checked 2026-09-19). Until releases are published somewhere a stranger can
read, this will honestly report that it cannot see any -- which is why the URL
is a setting rather than a constant.
"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, NamedTuple, Optional, Tuple

RELEASES_URL = "https://api.github.com/repos/4o66/sunshine-apps-ui/releases"

TIMEOUT = 15

# v1.2.0 / v1.2.0.dev314 / 1.2.0 -- the shapes docs/releasing.md produces.
TAG = re.compile(r"\Av?(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?\Z")


class Version(NamedTuple):
    """A version that can be compared with another. Sorts the way tags sort."""

    major: int
    minor: int
    patch: int
    dev: Optional[int]        # None for a release, which outranks any dev of it

    @property
    def is_dev(self) -> bool:
        return self.dev is not None

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}.dev{self.dev}" if self.is_dev else base

    def _key(self) -> Tuple[int, int, int, int, int]:
        # A release sorts above every dev build of the same number: (1,2,0) is
        # newer than (1,2,0).dev314, which is what .devN means.
        return (self.major, self.minor, self.patch,
                0 if self.is_dev else 1, self.dev or 0)

    def newer_than(self, other: "Version") -> bool:
        return self._key() > other._key()


def parse(text: str) -> Optional[Version]:
    match = TAG.match((text or "").strip())
    if not match:
        return None
    major, minor, patch, dev = match.groups()
    return Version(int(major), int(minor), int(patch),
                   int(dev) if dev is not None else None)


def running() -> Optional[Version]:
    """What is installed here, as a Version."""
    from . import version

    build = version.version() if hasattr(version, "version") else ""
    found = parse(build)
    if found:
        return found
    # version.display() is for people ("dev 0.1.0.79+"); dig the number out.
    text = re.sub(r"[^0-9.]", "", str(build or ""))
    return parse(text)


class Release(NamedTuple):
    version: Version
    url: str                  # where a human goes to read about it
    assets: Dict[str, str]    # filename -> download URL


def _fetch(url: str) -> List[dict]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "sunshine-apps-ui"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def releases(url: str = "") -> List[Release]:
    """Every release we can see, newest first. Raises OSError if we cannot look."""
    found = []
    for entry in _fetch(url or os.environ.get("SAU_RELEASES_URL") or RELEASES_URL):
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        number = parse(str(entry.get("tag_name", "")))
        if number is None:
            continue
        assets = {str(a.get("name")): str(a.get("browser_download_url"))
                  for a in (entry.get("assets") or [])
                  if isinstance(a, dict) and a.get("name")}
        found.append(Release(number, str(entry.get("html_url", "")), assets))
    return sorted(found, key=lambda r: r.version._key(), reverse=True)


def pick(available: List[Release], current: Version, *, dev: bool,
         stable_if_no_newer_dev: bool = True) -> Optional[Release]:
    """Which release to offer, or None when there is nothing better.

    On the stable channel only releases count. On the development channel the
    newest development build counts -- and, unless told otherwise, so does a
    release that is newer than it, because a release is where a dev build was
    heading.
    """
    stable = [r for r in available if not r.version.is_dev]
    newest_stable = stable[0] if stable else None

    if not dev:
        best = newest_stable
    else:
        best = available[0] if available else None
        if best is not None and best.version.is_dev and not stable_if_no_newer_dev:
            pass                       # keep the dev build; asked not to leave it
        elif (stable_if_no_newer_dev and newest_stable is not None
                and (best is None or newest_stable.version.newer_than(best.version))):
            best = newest_stable

    if best is None or not best.version.newer_than(current):
        return None
    return best


class Answer(NamedTuple):
    """What the settings page shows after a check."""

    state: str                # "current" | "available" | "unreachable"
    message: str
    release: Optional[Release] = None


def check(*, dev: bool, stable_if_no_newer_dev: bool = True,
          url: str = "") -> Answer:
    """Look, and say what was found in words a person can act on."""
    current = running()
    if current is None:
        return Answer("unreachable",
                      "This build does not say which version it is, so there is "
                      "nothing to compare against.")
    try:
        available = releases(url)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return Answer("unreachable",
                          "No releases are published where this can see them. "
                          "The repository is private; there is nothing to check "
                          "against yet.")
        return Answer("unreachable", f"The release list could not be read ({e}).")
    except (OSError, ValueError) as e:
        return Answer("unreachable",
                      f"Could not reach the release list ({e}). This machine may "
                      f"be offline, which is a perfectly good state to be in.")

    best = pick(available, current, dev=dev,
                stable_if_no_newer_dev=stable_if_no_newer_dev)
    if best is None:
        channel = "development builds" if dev else "releases"
        return Answer("current",
                      f"{current} is the newest there is, on {channel}.")
    kind = "development build" if best.version.is_dev else "release"
    return Answer("available",
                  f"{best.version} is available -- a {kind}. This is {current}.",
                  best)
