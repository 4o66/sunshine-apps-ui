# SPDX-License-Identifier: GPL-3.0-or-later
"""Request checks.

Binding to 127.0.0.1 stops remote hosts and nothing else. Two things still
reach a loopback port, and both are handled here:

* Any other process on this machine, running as any user, can connect. So every
  request must carry the token minted at startup.
* A page in the user's browser can be pointed at 127.0.0.1 by a hostname its
  author controls (DNS rebinding), which makes the *browser* issue requests from
  a foreign origin. Binding does nothing about that, so the Host header must
  name loopback exactly, and cross-site requests are refused.
"""

import hmac
import secrets
from typing import Optional, Tuple
from urllib.parse import urlsplit

BIND_HOST = "127.0.0.1"  # Deliberately not configurable. See docs/security.md.

_ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_matches(expected: str, given: Optional[str]) -> bool:
    if not given:
        return False
    return hmac.compare_digest(expected, given)


def host_is_loopback(host_header: Optional[str], port: int) -> bool:
    """True if Host names loopback on our port. Defeats DNS rebinding."""
    if not host_header:
        return False
    host = host_header.strip()
    if host.startswith("["):                      # [::1]:8765
        hostname, _, rest = host.partition("]")
        hostname += "]"
        given_port = rest.lstrip(":")
    else:
        hostname, _, given_port = host.partition(":")
    if hostname not in _ALLOWED_HOSTNAMES:
        return False
    # A missing port would mean 80/443, which is never us.
    return given_port.isdigit() and int(given_port) == port


def origin_is_same(origin: Optional[str], fetch_site: Optional[str], port: int) -> bool:
    """Refuse anything a different site initiated.

    Sec-Fetch-Site is the authority when present. It is set by the browser and a
    page cannot forge it, whereas Origin is legitimately "null" for a
    navigational form post from a page served with Referrer-Policy: no-referrer
    -- which is a policy we set ourselves. Reading that "null" as a foreign
    origin refuses the form the page just rendered.

    Origin is only consulted when Sec-Fetch-Site is absent, which means an
    older browser or a non-browser client.
    """
    if fetch_site is not None:
        return fetch_site in ("same-origin", "none")
    if origin:
        parts = urlsplit(origin)
        hostname = f"[{parts.hostname}]" if parts.hostname and ":" in parts.hostname else parts.hostname
        if hostname not in _ALLOWED_HOSTNAMES or parts.port != port:
            return False
    return True


def is_navigation(headers) -> bool:
    """True for a top-level page load, as opposed to a fetch or subresource."""
    return (headers.get("Sec-Fetch-Mode") == "navigate"
            or headers.get("Sec-Fetch-Dest") == "document")


def check(headers, query_token: Optional[str], expected_token: str, port: int,
          method: str = "GET") -> Tuple[bool, str]:
    """Return (allowed, reason). Reason is for the log, never for the response."""
    if not host_is_loopback(headers.get("Host"), port):
        return False, "bad Host header"

    # The cross-site rule exists to stop another page driving this one. A
    # top-level GET navigation cannot read our response, and someone following
    # the link from a terminal, a chat window or a bookmark legitimately arrives
    # with Sec-Fetch-Site: cross-site -- refusing that just breaks the tool. The
    # token is what authenticates, and it is still required below. Anything that
    # is not a safe navigation must be same-origin.
    safe_navigation = method in ("GET", "HEAD") and is_navigation(headers)
    if not safe_navigation:
        if not origin_is_same(headers.get("Origin"), headers.get("Sec-Fetch-Site"), port):
            return False, "cross-site request"

    supplied = headers.get("X-Auth-Token") or query_token
    if not token_matches(expected_token, supplied):
        return False, "bad or missing token"
    return True, ""
