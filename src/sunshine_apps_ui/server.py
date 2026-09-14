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
from . import artwork, state
from .importer import (ImporterError, check_auth, get_state, mutate,
                       run_plan, save_auth)
from .render import (app_page, applied_page, confirm_page, connect_page,
                     error_page, explain_page, grid_page, hidden_page,
                     page, render_fields, render_flags)

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
        self.send_header("Referrer-Policy", "same-origin")
        # img-src is needed for the tile artwork, which /art serves from this
        # same origin. Without it default-src 'none' blocks every tile and the
        # browser never even issues the request.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
                         "script-src 'self'; form-action 'self'; frame-ancestors 'none'; "
                         "base-uri 'none'")
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

        if parts.path == "/art":
            wanted = (query.get("p") or [""])[0]
            try:
                current = get_state(self.importer_path, use_cache=True)
            except ImporterError:
                self._send(404, error_page("Not found.", token=self.token))
                return
            found = artwork.read(wanted, artwork.allowed_paths(current))
            if not found:
                log.warning("artwork not served: %r", wanted)
                self._send(404, error_page("Not found.", token=self.token))
                return
            body, content_type = found
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return

        if parts.path in ("/", "/index.html"):
            try:
                current = get_state(self.importer_path)
            except ImporterError as e:
                self._send(500, error_page("Could not read the app list.",
                                           str(e), token=self.token))
                return
            scanned = "scan" in query
            if scanned:
                # A scan stages what it found onto the grid as pending changes,
                # rather than holding them aside to be applied by a second,
                # invisible route. Everything that will happen is now one list.
                try:
                    doc, _ = run_plan(self.importer_path, self.importer_args)
                    staged = state.stage_plan(doc.get("plan", {}) or {})
                    log.info("scan staged %d change(s)", staged)
                except ImporterError as e:
                    log.warning("scan failed: %s", e)
            auth_ok, auth_message = self._auth_state()
            # A credential problem is one thing; Sunshine failing for another
            # reason is a different thing and should not send you to a login.
            detail = "" if (auth_ok or "credential" in auth_message.lower()
                            or "No Sunshine credentials" in auth_message) else auth_message
            self._send(200, grid_page(current, self.token, scanned=scanned,
                                      auth_ok=auth_ok, pending=state.queue(),
                                      auth_detail=detail))
            return

        if parts.path == "/app.js":
            self._send_asset("app.js", "text/javascript; charset=utf-8")
            return

        if parts.path == "/app":
            if "new" in query:
                self._send(200, app_page({}, self.token, is_new=True))
                return
            if "hidden" in query:
                wanted = (query.get("hidden") or [""])[0]
                try:
                    current = get_state(self.importer_path, use_cache=True)
                except ImporterError as e:
                    self._send(500, error_page("Could not read the app list.",
                                               str(e), token=self.token))
                    return
                entry = next(
                    (h for h in (current.get("hidden") or [])
                     if f'{h.get("source")}:{h.get("id")}' == wanted), None)
                if entry is None:
                    self._send(404, error_page("That entry is not hidden.",
                                               token=self.token,
                                               title="Nothing to show"))
                    return
                already = any(op.get("op") == "restore"
                              and op.get("selector") == wanted
                              for op in state.queue())
                self._send(200, hidden_page(entry, self.token, queued=already))
                return
            entry = self._entry(query)
            if entry is None:
                self._send(404, error_page("That application is no longer there.",
                                           token=self.token,
                                           title="Nothing to show"))
                return
            self._send(200, app_page(entry, self.token))
            return

        if parts.path == "/explain":
            op = (query.get("op") or [""])[0]
            if op not in state.EXPLAINED:
                self._send(404, error_page("Not found.", token=self.token))
                return
            entry = self._entry(query)
            if entry is None:
                self._send(404, error_page("That application is no longer there.",
                                           token=self.token))
                return
            if not state.should_explain(op):
                # Silenced previously: queue it without the interstitial.
                self._queue_and_return(op, entry)
                return
            self._send(200, explain_page(op, entry, self.token))
            return

        if parts.path == "/connect":
            auth_ok, auth_message = self._auth_state()
            posted = (query.get("msg") or [""])[0]
            self._send(200, connect_page(self.token, posted or ("" if auth_ok else auth_message)))
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
            self._send(200, confirm_page(doc, self.token, self.via_sunshine,
                                         pending=state.queue()))
            return

        if parts.path != "/plan":
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

    def _send_asset(self, name: str, content_type: str) -> None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send(404, error_page("Not found.", token=self.token))
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _entry(self, query):
        """The app a request refers to, read fresh from the importer."""
        try:
            index = int((query.get("index") or ["-1"])[0])
        except ValueError:
            return None
        try:
            current = get_state(self.importer_path, use_cache=True)
        except ImporterError:
            return None
        for app in current.get("apps") or []:
            if app.get("index") == index:
                return app
        return None

    def _redirect(self, path: str, **params) -> None:
        params.setdefault("token", self.token)
        self.send_response(303)
        self.send_header("Location", path + "?" + urlencode(params))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _queue_and_return(self, op: str, entry) -> None:
        state.enqueue({"op": op, "index": entry.get("index"),
                       "name": entry.get("name")})
        self._redirect("/")

    def _form(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > 64 * 1024:
            return None
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        return parse_qs(body, keep_blank_values=True)

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
            log.warning("refused POST %s: %s (Host=%r Origin=%r Sec-Fetch-Site=%r)",
                        parts.path, reason, self.headers.get("Host"),
                        self.headers.get("Origin"),
                        self.headers.get("Sec-Fetch-Site"))
            self._send(404, error_page("Not found."))
            return

        if parts.path == "/app":
            fields = self._form()
            op = (fields.get("op") or [""])[0]
            if op not in ("add", "edit", "clone"):
                self._send(400, error_page("Unknown action.", token=self.token))
                return
            values = {key: (fields.get(key) or [""])[0]
                      for key, _l, _k, _h in render_fields()}
            for key, _label in render_flags():
                values[key] = key in fields
            entry = {"op": op, "fields": values}
            if op != "add":
                try:
                    entry["index"] = int((fields.get("index") or ["-1"])[0])
                except ValueError:
                    entry["index"] = -1
                entry["name"] = (fields.get("orig_name") or [""])[0]
            state.enqueue(entry)
            self._redirect("/")
            return

        if parts.path == "/queue":
            fields = self._form()
            op = (fields.get("op") or [""])[0]
            if op == "restore":
                selector = (fields.get("selector") or [""])[0]
                if not selector:
                    self._send(400, error_page("Nothing to un-hide.", token=self.token))
                    return
                state.enqueue({"op": "restore", "selector": selector,
                               "name": (fields.get("name") or [""])[0]})
                self._redirect("/")
                return
            if op not in state.EXPLAINED:
                self._send(400, error_page("Unknown action.", token=self.token))
                return
            if "keep_explaining" not in fields:
                state.set_explain(op, False)
            try:
                index = int((fields.get("index") or ["-1"])[0])
            except ValueError:
                index = -1
            state.enqueue({"op": op, "index": index,
                           "name": (fields.get("name") or [""])[0]})
            self._redirect("/")
            return

        if parts.path == "/unqueue":
            fields = self._form()
            op = (fields.get("op") or [""])[0]
            criteria = {"op": op}
            for key in ("selector", "name"):
                value = (fields.get(key) or [""])[0]
                if value:
                    criteria[key] = value
            if not op or not state.drop_matching(**criteria):
                log.info("nothing matched to un-queue: %r", criteria)
            self._redirect("/")
            return

        if parts.path == "/discard":
            state.clear_queue()
            self._redirect("/")
            return

        if parts.path == "/apply":
            pending = state.queue()
            if not pending:
                self._redirect("/")
                return
            try:
                ok, message = mutate(self.importer_path, pending, reload=True)
            except ImporterError as e:
                ok, message = False, str(e)
            if ok:
                state.clear_queue()
                self._redirect("/applied")
            else:
                self._redirect("/", apply_error=message[:300])
            return

        if parts.path != "/credentials":
            self._send(404, error_page("Not found.", token=self.token))
            return

        fields = self._form()
        if fields is None:
            self._send(400, error_page("Nothing to save.", token=self.token))
            return
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
            params["msg"] = message[:300]
        self.send_response(303)
        self.send_header("Location", ("/?" if ok else "/connect?") + urlencode(params))
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
