# SPDX-License-Identifier: GPL-3.0-or-later
"""Request checks.

Binding to 127.0.0.1 stops remote hosts and nothing else. Two things still
reach a loopback port, and both are handled here:

* Any other process on this machine, running as any user, can connect. So every
  request must carry the token minted at startup -- in the address it is first
  opened at, and after that in a cookie, so it never appears in a link. A link
  shows its address on hover, and that put the token on screen, in the stream
  and in every screenshot of it (issue #55).
* A page in the user's browser can be pointed at 127.0.0.1 by a hostname its
  author controls (DNS rebinding), which makes the *browser* issue requests from
  a foreign origin. Binding does nothing about that, so the Host header must
  name loopback exactly, and cross-site requests are refused.
"""

import hmac
import secrets
from http.cookies import CookieError, SimpleCookie
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


def cookie_name(port: int) -> str:
    """Named for the port, because a cookie is not.

    A browser keeps one jar per host, not per host and port, so two sessions
    side by side -- or one left from yesterday -- would otherwise overwrite
    each other's cookie.
    """
    return f"sau-session-{int(port)}"


def session_cookie(token: str, port: int) -> str:
    """The Set-Cookie value that carries the token from here on.

    HttpOnly so no script can read it, and Strict so no other site's request
    carries it. No expiry: it ends with the browser session, and the token
    ends with ours before that.
    """
    return f"{cookie_name(port)}={token}; Path=/; HttpOnly; SameSite=Strict"


def cookie_token(cookie_header: Optional[str], port: int) -> Optional[str]:
    """This session's token from a Cookie header, or None."""
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except CookieError:
        return None
    morsel = jar.get(cookie_name(port))
    return morsel.value if morsel is not None else None


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
          method: str = "GET", cookie: Optional[str] = None) -> Tuple[bool, str]:
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
    if token_matches(expected_token, supplied):
        return True, ""
    # The cookie only ever from our own pages, even for a navigation: that is
    # what makes it safe to have one at all. A browser already withholds a
    # Strict cookie from another site's request; this does not rely on it.
    if token_matches(expected_token, cookie):
        if origin_is_same(headers.get("Origin"), headers.get("Sec-Fetch-Site"), port):
            return True, ""
        return False, "session cookie on a request from another site"
    return False, "bad or missing token"
