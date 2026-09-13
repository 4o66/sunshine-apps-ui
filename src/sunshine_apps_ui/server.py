"""The local HTTP server.

Read-only: it runs the importer with --dry-run and shows the resulting plan.
Nothing here writes to apps.json.
"""

import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlsplit

from . import __version__, security
from .importer import (ImporterError, apply_plan, check_auth, run_plan,
                       save_auth)
from .render import applied_page, confirm_page, error_page, page

log = logging.getLogger("sunshine-apps-ui")


class PlanHandler(BaseHTTPRequestHandler):
    server_version = f"sunshine-apps-ui/{__version__}"
    sys_version = ""                      # do not advertise the Python version

    # Set by serve().
    token: str = ""
    importer_path: str = ""
    importer_args: List[str] = []
    port: int = 0
    via_sunshine: bool = False

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        # Nothing here should ever be embedded, cached, or sniffed.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - http.server's interface
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        supplied = (query.get("token") or [None])[0]

        allowed, reason = security.check(self.headers, supplied, self.token,
                                         self.port, self.command)
        if not allowed:
            # Deliberately uninformative to the caller; the reason goes to our log.
            log.warning("refused %s: %s", parts.path, reason)
            self._send(404, error_page("Not found."))
            return

        if parts.path == "/applied":
            self._send(200, applied_page(self.token, self.via_sunshine))
            return

        if parts.path == "/apply":
            try:
                doc, _ = run_plan(self.importer_path, self.importer_args)
            except ImporterError as e:
                self._send(500, error_page("Could not work out what would change.",
                                           str(e), token=self.token))
                return
            self._send(200, confirm_page(doc, self.token, self.via_sunshine))
            return

        if parts.path not in ("/", "/index.html"):
            self._send(404, error_page("Not found.", token=self.token))
            return

        try:
            doc, importer_log = run_plan(self.importer_path, self.importer_args)
        except ImporterError as e:
            log.error("plan failed: %s", e)
            self._send(500, error_page("The importer could not produce a plan.",
                                       str(e), token=self.token))
            return

        auth_ok, auth_message = self._auth_state()
        # A message carried back from a rejected save is the more useful one.
        posted_message = (query.get("msg") or [""])[0]
        if posted_message:
            auth_ok, auth_message = False, posted_message
        # Offer the form when Sunshine will not let us in, or when asked for.
        show_form = (not auth_ok) or ("connect" in query)
        self._send(200, page(doc, importer_log, self.token,
                             auth_ok=auth_ok, auth_message=auth_message,
                             show_form=show_form,
                             applied="applied" in query,
                             apply_error=(query.get("apply_error") or [""])[0]))

    do_HEAD = do_GET

    def _auth_state(self):
        try:
            return check_auth(self.importer_path)
        except Exception as e:                       # noqa: BLE001 - shown, not raised
            log.warning("credential check failed: %s", e)
            return False, "Could not check the stored credentials."

    def do_POST(self) -> None:  # noqa: N802 - http.server's interface
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        supplied = (query.get("token") or [None])[0]

        # An unsafe method never gets the cross-site navigation exemption, so a
        # form posted from anywhere but this page is refused here.
        allowed, reason = security.check(self.headers, supplied, self.token,
                                         self.port, self.command)
        if not allowed:
            log.warning("refused POST %s: %s", parts.path, reason)
            self._send(404, error_page("Not found."))
            return

        if parts.path == "/apply":
            try:
                ok, importer_log = apply_plan(self.importer_path, self.importer_args)
            except ImporterError as e:
                ok, importer_log = False, str(e)
            log.info("apply: %s", "ok" if ok else "failed")
            params = {"token": self.token}
            if ok:
                # Somewhere static: re-running the importer here would race the
                # session teardown that this very apply just triggered.
                target = "/applied?"
            else:
                target = "/?"
                tail = importer_log.strip().splitlines()
                params["apply_error"] = (tail[-1] if tail else "Apply failed")[:300]
            self.send_response(303)
            self.send_header("Location", target + urlencode(params))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if parts.path != "/credentials":
            self._send(404, error_page("Not found.", token=self.token))
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 8192:
            self._send(400, error_page("Nothing to save.", token=self.token))
            return
        body = self.rfile.read(length).decode("utf-8", "replace")
        fields = parse_qs(body, keep_blank_values=True)
        username = (fields.get("username") or [""])[0]
        password = (fields.get("password") or [""])[0]

        try:
            ok, message = save_auth(self.importer_path, username, password)
        except Exception as e:                       # noqa: BLE001 - shown, not raised
            ok, message = False, str(e)
        # The password is not logged, not echoed back, and not kept.
        del password
        log.info("credential save: %s", "accepted" if ok else "rejected")

        # Redirect after posting so a refresh cannot resubmit the form.
        params = {"token": self.token}
        if not ok:
            params["connect"] = "1"
            params["msg"] = message[:300]
        self.send_response(303)
        self.send_header("Location", "/?" + urlencode(params))
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve(token: str, importer_path: str, importer_args: Optional[List[str]] = None,
          port: int = 0) -> ThreadingHTTPServer:
    """Bind and return a server. The address is always loopback, by design."""
    handler = type("BoundPlanHandler", (PlanHandler,), {
        "token": token,
        "importer_path": importer_path,
        "importer_args": list(importer_args or []),
        # Set by our launcher, which only ever runs inside a streamed session.
        "via_sunshine": os.getenv("BSM_UI_VIA_SUNSHINE", "") == "1",
    })
    httpd = ThreadingHTTPServer((security.BIND_HOST, port), handler)
    handler.port = httpd.server_address[1]    # resolve port 0 to what we actually got
    return httpd
