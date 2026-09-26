# SPDX-License-Identifier: GPL-3.0-or-later
"""The local HTTP server.

It renders what is in apps.json, queues changes to it, and applies them through
the importer's --mutate contract. It never writes apps.json itself: the rules
about ownership markers, tombstones and Sunshine's own defaults live beside the
reconciler, and one implementation of them is enough.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlsplit

from . import __version__, security
from . import artwork, privilege, state
from .engine import (EngineError, art_choose, art_search, art_sgdb,
                     art_sgdb_one, backup_diff, browse,
                     check_auth, choose_config, config_choice, forget_state,
                     get_state, list_backups, mutate, run_plan,
                     save_auth)
from . import scanjob, updates
from .render import _sheet_url as render_sheet_url
from .render import (LOCK_NOTE, app_page, applied_page, artwork_page,
                     closing_page, leaving_with_changes_page,
                     render_elevating,
                     backups_page, confirm_page, connect_page, error_page,
                     explain_page, grid_page, hidden_page, is_protected, page,
                     picker_page, render_browsable, render_fields, render_flags,
                     report_page, scanning_page, settings_page)

log = logging.getLogger("sunshine-apps-ui")

# How long to keep serving after applying, when this is being watched through a
# stream. The reload has already ended that stream, so this is only enough for
# the redirect to land if it somehow survived.
STOP_AFTER_APPLY = 3.0


class PlanHandler(BaseHTTPRequestHandler):
    server_version = f"sunshine-apps-ui/{__version__}"
    sys_version = ""                      # do not advertise the Python version

    # Set when an apply succeeds, so the page after it knows there is nothing
    # left to stay open for.
    applied: bool = False
    stopping: bool = False
    _armed: bool = False

    # Set by serve().
    token: str = ""
    conf_dir: str = ""
    # How conf_dir was arrived at, as config_choice() reports it, so the page
    # can say which tree it picked when the pick was a judgment. Issue #19.
    config: Dict[str, Any] = {"how": "only", "candidates": [], "stale": False}
    # Where to look for config trees; None is the user's home. For tests.
    config_home: Optional[str] = None
    importer_opts: Dict[str, Any] = {}
    port: int = 0
    via_sunshine: bool = False
    # Whether apps.json can be written. Assumed writable so that a handler
    # constructed without serve() -- every test that builds one directly --
    # behaves as it always did.
    rights: privilege.Privilege = privilege.Privilege(True, None, "", "")

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
        # connect-src is for the scanning page, which asks this server how the
        # scan is getting on. Without it default-src 'none' blocks the fetch
        # and the page sits at "0.0s elapsed" looking exactly like a hang.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
                         "script-src 'self'; connect-src 'self'; form-action 'self'; "
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

        if parts.path == "/art":
            wanted = (query.get("p") or [""])[0]
            try:
                current = get_state(self.conf_dir, use_cache=True)
            except EngineError:
                self._send(404, error_page("Not found.", token=self.token))
                return
            found = artwork.read(wanted,
                                 artwork.allowed_paths(current, state.queue()))
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

        if parts.path == "/sgdb-art":
            # One picture, fetched when the browser asks for it rather than all
            # 48 before the page is allowed to exist. Issue #31.
            asked = (query.get("id") or [""])[0]
            origin = _SGDB_SEEN.get(self.token, {}).get(asked, "")
            if not origin:
                # Not something we offered this session: a stale page after a
                # restart, or somebody guessing.
                self._send(404, error_page("Not found.", token=self.token))
                return
            try:
                path = art_sgdb_one(self.conf_dir, origin)
            except EngineError:
                path = ""
            body = b""
            if path:
                try:
                    with open(path, "rb") as handle:
                        body = handle.read()
                except OSError:
                    body = b""
            if not body:
                self._send(404, error_page("Not found.", token=self.token))
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return

        if parts.path == "/settings":
            answer = _LAST_CHECK.pop(self.token, None)
            self._send(200, settings_page(self.token, prefs=state.prefs(),
                                          answer=answer,
                                          notice=_NOTICE.pop(self.token, ""),
                                          language=_language_panel(self.token),
                                          via_sunshine=self.via_sunshine,
                                          sgdb=self._sgdb_panel(),
                                          config=self._config_panel()))
            return

        if parts.path == "/report":
            self._send(200, report_page(self.token, self.via_sunshine,
                                        _describe_platform()))
            return

        if parts.path == "/scan/status":
            # Only what the page shows: the whole log would make a poll
            # every 400 ms carry the scan twice over.
            status = scanjob.job.status()
            self._send(200, json.dumps({
                "running": status["running"], "elapsed": status["elapsed"],
                "latest": status["latest"], "error": status["error"],
                "staged": status["staged"], "run": status["run"]}),
                "application/json; charset=utf-8")
            return

        if parts.path == "/scanning":
            status = scanjob.job.status()
            if not status["running"] and status["ran"]:
                # It finished while the page was being asked for. Nothing to
                # watch; go where the result is.
                self._redirect("/", scanned="1")
                return
            self._send(200, scanning_page(self.token, status))
            return

        if "scan" in query and parts.path in ("/", "/index.html"):
            # A scan stages what it found onto the grid as pending changes,
            # rather than holding them aside to be applied by a second,
            # invisible route. Everything that will happen is now one list.
            #
            # It runs on a thread and this returns at once: the page that
            # watches it is the indicator the maintainer asked for after pressing Rescan
            # and seeing nothing move for fifty seconds.
            conf_dir, opts = self.conf_dir, self.importer_opts

            def work() -> int:
                doc, _ = run_plan(conf_dir, opts)
                staged = state.stage_plan(doc.get("plan", {}) or {})
                log.info("scan staged %d change(s)", staged)
                return staged

            if not scanjob.job.start(work, on_error=lambda why:
                                     log.warning("scan failed: %s", why)):
                log.info("a scan was already running; watching that one")
            self._redirect("/scanning")
            return

        if parts.path in ("/", "/index.html"):
            try:
                current = get_state(self.conf_dir)
            except EngineError as e:
                self._send(500, error_page("Could not read the app list.",
                                           str(e), token=self.token))
                return
            # "scanned" is a scan that has finished -- the flag the scanning
            # page comes back with. "scan" is a request to run one, and that
            # no longer happens on this thread: it took the best part of a
            # minute and returned nothing at all until it was over.
            scanned = "scanned" in query
            auth_ok, auth_message = self._auth_state()
            # A credential problem is one thing; Sunshine failing for another
            # reason is a different thing and should not send you to a login.
            detail = "" if (auth_ok or "credential" in auth_message.lower()
                            or "No Sunshine credentials" in auth_message) else auth_message
            queued = state.queue()
            # A queued restore is a change to the whole file, so what it would
            # do has to be worked out rather than read off the operation.
            restore = None
            rollback = next((op for op in queued
                             if op.get("op") == "rollback"), None)
            if rollback:
                try:
                    restore = backup_diff(self.conf_dir,
                                          str(rollback.get("backup", "")))
                    restore["qid"] = rollback.get("qid", "")
                except EngineError as e:
                    log.warning("could not preview the restore: %s", e)
                    restore = {"backup": str(rollback.get("backup", "")),
                               "qid": rollback.get("qid", ""),
                               "returning": [], "going": [], "changing": [],
                               "unreadable": str(e)}
            self._send(200, grid_page(current, self.token, scanned=scanned,
                                      auth_ok=auth_ok, pending=queued,
                                      auth_detail=detail, restore=restore,
                                      rights=self.rights,
                                      config=self._config_panel()))
            return

        if parts.path == "/scanning.js":
            self._send_asset("scanning.js", "text/javascript; charset=utf-8")
            return

        if parts.path == "/sheet.js":
            self._send_asset("sheet.js", "text/javascript; charset=utf-8")
            return

        if parts.path == "/app.js":
            self._send_asset("app.js", "text/javascript; charset=utf-8")
            return

        if parts.path == "/app":
            if "new" in query:
                entry, dirty = self._with_draft({}, "new")
                self._send(200, app_page(entry, self.token, is_new=True,
                                         draft_key="new", dirty=dirty))
                return
            if "queued" in query:
                qid = (query.get("queued") or [""])[0]
                op = state.find(qid)
                if op is None:
                    self._send(404, error_page("That change is no longer queued.",
                                               token=self.token,
                                               title="Nothing to show"))
                    return
                # Show whichever payload this kind of operation carries.
                entry = dict(op.get("entry") or op.get("fields") or {})
                entry.setdefault("name", op.get("name") or "")
                marker = (op.get("entry") or {}).get("bsm") or {}
                entry["managed"] = bool(marker)
                entry["source"], entry["id"] = marker.get("source"), marker.get("id")
                entry, dirty = self._with_draft(entry, f"qid:{qid}")
                self._send(200, app_page(entry, self.token, qid=qid,
                                         queued_op=str(op.get("op", "")),
                                         draft_key=f"qid:{qid}", dirty=dirty))
                return

            if "hidden" in query:
                wanted = (query.get("hidden") or [""])[0]
                try:
                    current = get_state(self.conf_dir, use_cache=True)
                except EngineError as e:
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
            entry = dict(entry)
            entry, dirty = self._with_draft(entry, f"index:{entry.get('index')}")
            self._send(200, app_page(entry, self.token, dirty=dirty,
                                     draft_key=f"index:{entry.get('index')}"))
            return

        if parts.path == "/explain":
            op = (query.get("op") or [""])[0]
            if op not in state.EXPLAINED:
                self._send(404, error_page("Not found.", token=self.token))
                return
            if self._protects((query.get("index") or [""])[0]):
                self._refuse_locked()
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

        if parts.path == "/browse":
            key = (query.get("key") or [""])[0]
            field = (query.get("field") or [""])[0]
            browsable = render_browsable()
            if field not in browsable:
                self._send(404, error_page("Nothing to choose here.",
                                           token=self.token, title="Nothing to show"))
                return

            picked = (query.get("pick") or [""])[0]
            if picked:
                values = dict(state.draft(key))
                values[field] = picked
                state.set_draft(key, values)
                self._redirect_raw(self._form_target(key))
                return

            label = next(l for k, l, _t, _h in render_fields() if k == field)
            where = (query.get("path") or [""])[0] or os.path.expanduser("~")
            error = ""
            try:
                listing = browse(self.conf_dir, where, browsable[field])
            except EngineError as e:
                error, listing = str(e), {"path": where, "parent": "", "entries": []}
            self._send(200, picker_page(listing, self.token, key=key, field=field,
                                        label=label, error=error,
                                        filter_text=(query.get("q") or [""])[0]))
            return

        if parts.path == "/backups":
            chosen = (query.get("restore") or [""])[0]
            if chosen:
                # Queued, not applied. The grid then shows what it would do,
                # and it can be cancelled from there like anything else.
                state.drop_matching(op="rollback")
                state.enqueue({"op": "rollback", "backup": chosen,
                               "name": f"the copy from {chosen}"})
                self._redirect("/")
                return
            error, copies = "", []
            try:
                copies = list_backups(self.conf_dir)
            except EngineError as e:
                error = str(e)
            self._send(200, backups_page(copies, self.token, error=error))
            return

        if parts.path == "/artwork":
            key = (query.get("key") or [""])[0]
            name, source, ident = self._art_subject(key)

            chosen = (query.get("choose") or [""])[0]
            if chosen:
                # Choosing copies the cached file, and a picture from the sheet
                # is only cached once the browser has asked for it. Normally it
                # has -- you are clicking something you can see. But an image
                # that failed to load leaves a tile you can still click, and
                # "that artwork is no longer cached" is a baffling answer to
                # "I picked this one". Fetch it and carry on. Issue #31.
                origin = _SGDB_SEEN.get(self.token, {}).get(chosen, "")
                if origin:
                    try:
                        art_sgdb_one(self.conf_dir, origin)
                    except EngineError:
                        pass
                try:
                    picked = art_choose(self.conf_dir, chosen, name)
                except EngineError as e:
                    self._send(500, error_page("Could not save that artwork.",
                                               str(e), token=self.token))
                    return
                values = dict(state.draft(key))
                values["image-path"] = picked
                state.set_draft(key, values)
                self._redirect_raw(self._form_target(key))
                return

            # Searching for a different title means a different game, so the
            # ownership marker no longer applies: look it up by that name alone.
            searched = (query.get("q") or [""])[0] or name
            if searched != name:
                source = ident = ""
            error, doc = "", {"candidates": [], "notes": [],
                              "offer_sgdb": False, "sgdb_ready": False}
            try:
                doc = art_search(self.conf_dir, name=searched,
                                 source=source, ident=ident)
            except EngineError as e:
                error = str(e)

            # The SteamGridDB sheet, only when the address asks for it. This is
            # the one fetch on this page that reaches a third party, so it
            # happens because somebody pressed for it and not before. Issue #30.
            sheet, refresh_to = None, ""
            if (query.get("sgdb") or [""])[0] == "1" and doc.get("sgdb_ready"):
                asked = (query.get("sgdb_page") or ["0"])[0]
                try:
                    wanted = max(0, int(asked))
                except ValueError:
                    wanted = 0
                try:
                    per = max(0, int((query.get("per") or ["0"])[0]))
                except ValueError:
                    per = 0
                fit = _sheet_fit((query.get("fit") or [""])[0])
                if (query.get("go") or [""])[0] != "1":
                    # The sheet, empty, with a spinner in it -- drawn at once,
                    # before anything is asked of SteamGridDB. The refresh in
                    # its head leads to the address that does the asking, so
                    # the wait happens on screen instead of behind a button
                    # that looked like it had not been pressed. Issue #31.
                    sheet = {"loading": True, "candidates": [], "note": "",
                             "total": 0, "page": wanted, "pages": 0,
                             "per": per, "fit": fit}
                    refresh_to = render_sheet_url(key, self.token, searched,
                                                  wanted, go=True, per=per,
                                                  fit=fit)
                else:
                    try:
                        sheet = art_sgdb(self.conf_dir, name=searched,
                                         source=source, ident=ident,
                                         page=wanted, per=per)
                    except EngineError as e:
                        sheet = {"candidates": [], "note": str(e), "total": 0,
                                 "page": wanted, "pages": 0}
                    sheet["fit"] = fit
                    self._remember_sgdb(sheet.get("candidates") or [])

            self._send(200, artwork_page(
                doc.get("candidates") or [], self.token, key=key,
                label=name or "this app",
                current=str(state.draft(key).get("image-path") or ""),
                notes=doc.get("notes") or [], searched=searched, error=error,
                offer_sgdb=bool(doc.get("offer_sgdb")),
                sgdb_ready=bool(doc.get("sgdb_ready")), sheet=sheet,
                refresh_to=refresh_to))
            return

        if parts.path == "/connect":
            auth_ok, auth_message = self._auth_state()
            posted = (query.get("msg") or [""])[0]
            self._send(200, connect_page(self.token, posted or ("" if auth_ok else auth_message)))
            return

        if parts.path == "/applied":
            # Decided before the response goes out, armed after. The client can
            # be reading the page while this thread is still here, so anything
            # that happens after _send is not yet true when the page arrives.
            #
            # Usually already armed by the apply itself; this covers the case
            # where the stream survived long enough to ask for this page.
            stopping = bool(self.applied and self.via_sunshine)
            if stopping:
                type(self).stopping = True
            self._send(200, applied_page(self.token, self.via_sunshine))
            # Applying reloads Sunshine, and that reload has already ended the
            # stream this page was being watched through -- Sunshine replaces
            # its whole process manager on refresh, so it no longer knows this
            # app is running and cannot close it either. Nobody can reach this
            # page any more, and the browser showing it would sit on the host's
            # desktop until something else swept it up. So stop, and let the
            # launcher take the window down with us.
            if stopping:
                self._stop_soon()
            return

        if parts.path == "/apply":
            # No scan here. Applying applies the queue, so the confirmation
            # shows the queue; running a library scan to decorate it promised
            # changes that would not happen and took seconds to say so.
            self._send(200, confirm_page({}, self.token, self.via_sunshine,
                                         pending=state.queue()))
            return

        if parts.path != "/plan":
            self._send(404, error_page("Not found.", token=self.token))
            return

        try:
            doc, importer_log = run_plan(self.conf_dir, self.importer_opts)
        except EngineError as e:
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
            current = get_state(self.conf_dir, use_cache=True)
        except EngineError:
            return None
        for app in current.get("apps") or []:
            if app.get("index") == index:
                return app
        return None

    @staticmethod
    def _with_draft(entry: Dict[str, Any], key: str):
        """Overlay a saved form onto an entry, and say whether it changed it.

        Apply is disabled until something changes, and the page cannot tell:
        a value chosen in a picker is already in the form by the time the
        browser sees it, so comparing the form against itself finds nothing.
        The server knows, because it is the one merging the two.
        """
        values = state.draft(key)
        differs = False
        for field, value in values.items():
            before = entry.get(field)
            if isinstance(value, bool):
                differs = differs or bool(before) != value
            else:
                differs = differs or str("" if before is None else before) != str(value)
        entry.update(values)
        return entry, differs

    def _protects(self, index) -> bool:
        """Is *index* the tile this manager is launched from?

        Looked up in apps.json rather than trusted from the form: the page can
        say a field is read-only, but a form is only a suggestion. This is the
        check that decides.
        """
        if index in (None, ""):
            return False
        try:
            current = get_state(self.conf_dir, use_cache=True)
        except EngineError:
            # Refuse rather than allow: not being able to tell is not a reason
            # to permit the one change that cannot be undone from here.
            return True
        for app in current.get("apps") or []:
            if str(app.get("index")) == str(index):
                return is_protected(app)
        return False

    def _refuse_locked(self) -> None:
        self._send(400, error_page("That cannot be changed.", LOCK_NOTE,
                                   token=self.token, title="Not allowed"))

    def _art_subject(self, key: str):
        """(name, source, ident) for whichever form the artwork picker opened from.

        The name comes from the draft rather than from apps.json, so renaming an
        entry and then looking for artwork searches for the new name. The marker
        is what turns a search into a lookup: with an appid there is no guessing.
        """
        values = state.draft(key)
        name = str(values.get("name") or "")
        source = ident = ""
        if key.startswith("qid:"):
            op = state.find(key[4:]) or {}
            name = name or str(op.get("name") or "")
            marker = (op.get("entry") or {}).get("bsm") or {}
            source, ident = str(marker.get("source") or ""), str(marker.get("id") or "")
        elif key.startswith("index:"):
            try:
                current = get_state(self.conf_dir, use_cache=True)
            except EngineError:
                current = {}
            for app in current.get("apps") or []:
                if str(app.get("index")) == key[6:]:
                    name = name or str(app.get("name") or "")
                    source = str(app.get("source") or "")
                    ident = str(app.get("id") or "")
                    break
        return name, source, ident

    def _form_target(self, key: str) -> str:
        if key == "new":
            return f"/app?new=1&token={self.token}"
        if key.startswith("qid:"):
            return f"/app?queued={key[4:]}&token={self.token}"
        if key.startswith("index:"):
            return f"/app?index={key[6:]}&token={self.token}"
        return f"/?token={self.token}"

    def _stop_soon(self, delay: float = 0.5) -> None:
        """Stop serving, once this response has had time to reach the browser.

        From a timer thread, because shutdown() waits for the serving loop to
        finish and this is running inside it.
        """
        if self._armed:
            return                      # already stopping; do not stack timers
        type(self).stopping = True
        type(self)._armed = True
        threading.Timer(delay, self.server.shutdown).start()

    def _redirect_raw(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _redirect(self, location: str, **params) -> None:
        # Named "location", not "path": "path" is also a query parameter the
        # picker needs to pass, and the collision crashed the handler.
        params.setdefault("token", self.token)
        self.send_response(303)
        self.send_header("Location", location + "?" + urlencode(params))
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
            return check_auth(self.conf_dir)
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

        if parts.path == "/quit":
            # Leaving is a change to the world -- the program stops -- so it is
            # a POST with a token behind it, like everything else here that
            # does something rather than shows something.
            fields = self._form()
            queued = state.queue()
            if queued and "anyway" not in fields:
                self._send(200, leaving_with_changes_page(self.token, len(queued)))
                return
            self._send(200, closing_page(self.via_sunshine))
            # The launcher watches the server as well as the window, and takes
            # the window down when we go. So stopping here is the whole of it:
            # there is nothing to ask the window to do.
            self._stop_soon()
            return

        if parts.path == "/config-dir":
            fields = self._form()
            wanted = (fields.get("path") or [""])[0]
            why = self._switch_config(wanted)
            if why:
                _CONFIG_NOTICE[self.token] = why
            back = (fields.get("back") or [""])[0]
            self._redirect("/settings" if back == "settings" else "/")
            return

        if parts.path.startswith("/settings/"):
            fields = self._form()
            what = parts.path.split("/", 2)[2]

            if what == "theme":
                choice = (fields.get("theme") or ["system"])[0]
                if choice in ("system", "light", "dark"):
                    state.set_pref("theme", choice)
            elif what == "channel":
                # One switch per press, naming itself and the value it wants.
                # It was a checkbox whose absence meant "off", which needed
                # script to submit at all -- and the script was blocked by our
                # own policy, so nothing here could be changed. Issue #28.
                setting = (fields.get("setting") or [""])[0]
                wanted = (fields.get("value") or [""])[0] == "1"
                if setting == "dev_builds":
                    state.set_pref("dev_builds", wanted)
                elif setting == "stable_if_no_newer_dev":
                    # Only meaningful while development builds are on, and the
                    # switch is disabled otherwise -- but a request can arrive
                    # regardless, so it is refused here rather than assumed.
                    if state.prefs().get("dev_builds"):
                        state.set_pref("stable_if_no_newer_dev", wanted)
            elif what == "language":
                from . import i18n

                choice = (fields.get("language") or [""])[0].strip()
                codes = {item["code"] for item in i18n.languages()}
                if choice and choice not in codes:
                    _NOTICE[self.token] = "That is not a language we ship."
                else:
                    state.set_pref("language", choice)
                    i18n._cache.clear()
                    _offer_artwork(self.token, choice)
            elif what == "art-check":
                _check_artwork(self.token)
            elif what == "art-fetch":
                # The offer is a button, so what to fetch travels in the link
                # behind it rather than in a field nobody typed.
                asked = (fields.get("code") or [""])[0].strip()
                if not asked:
                    asked = (parse_qs(parts.query).get("code")
                             or [""])[0].strip()
                _fetch_artwork(self.token, asked)
            elif what == "defaults":
                # A scan with restore turned on, so the tiles arrive on the
                # grid as pending changes the same way everything else does.
                # Nothing is written until Apply, and the takeover makes the
                # restored entries ours on the way past.
                from .core.system_apps import find_system_apps_json
                conf_dir, opts = self.conf_dir, dict(self.importer_opts)
                if not find_system_apps_json(
                        str(opts.get("SYSTEM_APPS_JSON", "")).strip()):
                    _NOTICE[self.token] = (
                        "Sunshine's own apps.json is not where we look for it, "
                        "so there is nothing to copy the default tiles from.")
                else:
                    opts["BSM_RESTORE_DEFAULTS"] = "1"

                    def work() -> int:
                        doc, _ = run_plan(conf_dir, opts)
                        staged = state.stage_plan(doc.get("plan", {}) or {})
                        log.info("restore defaults staged %d change(s)", staged)
                        return staged

                    if not scanjob.job.start(work, on_error=lambda why:
                                             log.warning("restore failed: %s", why)):
                        log.info("a scan was already running; watching that one")
                    self._redirect("/scanning")
                    return
            elif what == "sgdb-key":
                # Checked against the API before it is stored, and stored mode
                # 600 -- both inside save_sgdb, which is the same path the
                # command line uses. A key that does not work is worse than
                # none: it looks, weeks later, like SteamGridDB having nothing
                # for anything.
                typed = (fields.get("sgdb-key") or [""])[0].strip()
                if not typed:
                    _SGDB[self.token] = {"state": "unreachable",
                                         "message": "No key was typed."}
                else:
                    from .core import api

                    ok, why = api.save_sgdb(self.conf_dir, typed)
                    _SGDB[self.token] = {
                        "state": "available" if ok else "unreachable",
                        # save_sgdb reports the path it wrote, which is not
                        # what someone at a television wants to read.
                        "message": ("That key works, and is saved. Community "
                                    "artwork appears in the picker from now "
                                    "on.") if ok else why}
            elif what == "check":
                prefs = state.prefs()
                _LAST_CHECK[self.token] = updates.check(
                    dev=bool(prefs.get("dev_builds", False)),
                    stable_if_no_newer_dev=bool(
                        prefs.get("stable_if_no_newer_dev", True)))
            else:
                self._send(404, error_page("Not found.", token=self.token))
                return
            self._redirect("/settings")
            return

        if parts.path == "/app":
            fields = self._form()
            op = (fields.get("op") or [""])[0]

            if op in ("artwork",) or op.startswith("browse:"):
                field = "image-path" if op == "artwork" else op.split(":", 1)[1]
                if field not in render_browsable():
                    self._send(400, error_page("Nothing to choose there.",
                                               token=self.token))
                    return
                # Whichever picker this is, the half-typed form goes into a
                # draft first: leaving the page must not discard the edits that
                # were the reason for opening a picker in the first place.
                values = {k: (fields.get(k) or [""])[0]
                          for k, _l, _t, _h in render_fields()}
                for k, _label in render_flags():
                    values[k] = k in fields
                qid = (fields.get("qid") or [""])[0]
                index = (fields.get("index") or [""])[0]
                key = (f"qid:{qid}" if qid
                       else f"index:{index}" if index != "" else "new")
                state.set_draft(key, values)
                if op == "artwork":
                    self._redirect("/artwork", key=key)
                    return
                self._redirect("/browse", key=key, field=field,
                               path=values.get(field) or "")
                return

            if op == "revise":
                qid = (fields.get("qid") or [""])[0]
                existing = state.find(qid)
                if existing is None:
                    self._send(404, error_page("That change is no longer queued.",
                                               token=self.token,
                                               title="Nothing to show"))
                    return
                values = {key: (fields.get(key) or [""])[0]
                          for key, _l, _k, _h in render_fields()}
                for key, _label in render_flags():
                    values[key] = key in fields
                # Revise the payload this operation actually carries, so the
                # ownership marker on an adopted entry survives being edited.
                if isinstance(existing.get("entry"), dict):
                    revised = dict(existing["entry"])
                    revised.update(values)
                    state.update(qid, {"entry": revised,
                                       "name": values.get("name") or existing.get("name")})
                else:
                    state.update(qid, {"fields": values,
                                       "name": values.get("name") or existing.get("name")})
                state.clear_draft(f"qid:{qid}")
                self._redirect("/")
                return

            if op not in ("add", "edit", "clone"):
                self._send(400, error_page("Unknown action.", token=self.token))
                return
            values = {key: (fields.get(key) or [""])[0]
                      for key, _l, _k, _h in render_fields()}
            for key, _label in render_flags():
                values[key] = key in fields

            posted_index = (fields.get("index") or [""])[0]
            if op != "add" and self._protects(posted_index):
                if op == "clone":
                    # A copy would be made from a form whose fields are not
                    # editable, so it could only ever be a duplicate or a
                    # broken one.
                    self._refuse_locked()
                    return
                # Rename and nothing else. The importer updates exactly the
                # fields it is given, so sending only this one is the guard.
                values = {"name": values.get("name", "")}

            entry = {"op": op, "fields": values}
            key_for_form = "new"
            if op != "add":
                try:
                    entry["index"] = int((fields.get("index") or ["-1"])[0])
                except ValueError:
                    entry["index"] = -1
                entry["name"] = (fields.get("orig_name") or [""])[0]
                key_for_form = f"index:{entry['index']}"
            state.enqueue(entry)
            state.clear_draft(key_for_form)
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
            if self._protects((fields.get("index") or [""])[0]):
                self._refuse_locked()
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
            qid = (fields.get("qid") or [""])[0]
            if qid:
                if not state.drop_qid(qid):
                    log.info("nothing matched to un-queue: qid=%r", qid)
                self._redirect("/")
                return
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

        if parts.path == "/elevate":
            # Asking Windows for the rights this was not given. The new
            # instance ends this one on its way up, the way every relaunch
            # does, so there is nothing to tear down here.
            from . import winbrowser
            if privilege.can_ask_for_elevation() and winbrowser.relaunch_elevated():
                self._send(200, render_elevating(self.token))
            else:
                # Refusing the prompt is an answer, not a failure.
                self._redirect("/")
            return

        if parts.path == "/apply":
            pending = state.queue()
            if not pending:
                self._redirect("/")
                return
            try:
                ok, message, results = mutate(self.conf_dir, pending, reload=True)
            except EngineError as e:
                # Nothing was attempted, so the queue is still worth keeping.
                ok, message, results = False, str(e), []

            # Everything that was attempted leaves the queue, whether or not it
            # worked. Keeping a refused operation sounds kinder and is not: the
            # file was written either way, so a queued operation that referred
            # to the old contents is now stale, and re-applying it does nothing
            # for ever. That is the jam the maintainer hit -- "Applied 0 of 2" on every
            # press, after the first press had really applied one of them.
            refused = []
            for op, result in zip(pending, results):
                state.drop_qid(str(op.get("qid", "")))
                if not result.get("ok"):
                    refused.append(f'{result.get("name") or result.get("op")}: '
                                   f'{result.get("error")}')
            if refused:
                self._redirect("/", apply_error="; ".join(refused)[:300])
                return
            if ok:
                type(self).applied = True
                self._redirect("/applied")
                if self.via_sunshine:
                    # Arm the stop here rather than when /applied is fetched.
                    # Applying reloads Sunshine, which ends the stream this is
                    # being watched through -- so the browser is usually gone
                    # before it can ask for that page, and waiting for it meant
                    # the window was still sitting there on the desktop
                    # afterwards. Long enough for the redirect to land if the
                    # stream did survive.
                    self._stop_soon(delay=STOP_AFTER_APPLY)
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
            ok, message = save_auth(self.conf_dir, username, password)
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

    def _remember_sgdb(self, candidates: List[Dict[str, Any]]) -> None:
        """Note the pictures this sheet offered, so their ids can be resolved."""
        seen = _SGDB_SEEN.setdefault(self.token, {})
        for candidate in candidates:
            found = str(candidate.get("id") or "")
            origin = str(candidate.get("origin") or "")
            if found and origin:
                seen[found] = origin
        # Bounded: a long session paging through a big game would otherwise
        # keep every url it ever showed.
        while len(seen) > _SGDB_SEEN_MAX:
            seen.pop(next(iter(seen)))

    def _config_panel(self) -> Dict[str, Any]:
        """What the pages need to say which config tree this is, and offer others."""
        panel = dict(self.config)
        panel["chosen"] = self.conf_dir
        panel["notice"] = _CONFIG_NOTICE.pop(self.token, "")
        panel["queued"] = len(state.queue())
        candidates = []
        for candidate in panel.get("candidates") or []:
            item = dict(candidate)
            item["apps"] = _count_apps(item.get("path", ""))
            candidates.append(item)
        panel["candidates"] = candidates
        return panel

    def _switch_config(self, wanted: str) -> str:
        """Use another config tree from now on. Returns why not, or "".

        Only a tree config_choice() itself found can be chosen: the path comes
        from a form, and a server that writes apps.json wherever it is told is
        one that can be told to write anywhere.
        """
        how = self.config.get("how")
        if how == "override":
            return ("SUNSHINE_CONF_DIR names the config directory, so it cannot "
                    "be changed from here.")
        if how == "argument":
            return ("--conf-dir names the config directory, so it cannot be "
                    "changed from here.")
        fresh = config_choice(self.config_home)
        if wanted not in [c["path"] for c in fresh.get("candidates") or []]:
            return "That is not one of the Sunshine config directories found here."
        if scanjob.job.running():
            return "A scan is running. Switch once it has finished."
        queued = len(state.queue())
        if queued and wanted != self.conf_dir:
            # Queued changes were worked out against this tree's apps.json.
            # Carried to another they would address the wrong entries by
            # position -- the same silent wrong-file failure, one step later.
            return (f"{queued} change{'' if queued == 1 else 's'} "
                    f"{'is' if queued == 1 else 'are'} waiting to be applied "
                    f"to this one. Apply or discard "
                    f"{'it' if queued == 1 else 'them'} first.")
        choose_config(wanted)
        handler = type(self)
        if wanted != handler.conf_dir:
            log.warning("config directory switched: %s -> %s",
                        handler.conf_dir, wanted)
        handler.conf_dir = wanted
        handler.rights = privilege.check(wanted)
        handler.config = config_choice(self.config_home)
        forget_state()
        state.clear_drafts()
        return ""

    def _sgdb_panel(self) -> Dict[str, Any]:
        """What the community-artwork section knows: whether a key is stored,
        and the outcome of the last attempt to store one.

        Never the key. `load_sgdb_key` also honours SGDB_API_KEY, so a key in
        the environment counts as stored -- typing one here would be ignored in
        favour of it, and saying "no key stored" beside working artwork is the
        kind of small lie that costs an afternoon.
        """
        from .core.artwork_sources import load_sgdb_key

        panel: Dict[str, Any] = dict(_SGDB.pop(self.token, {}))
        try:
            panel["have"] = bool(load_sgdb_key(self.conf_dir))
        except OSError:
            panel["have"] = False
        return panel


# The result of the last check, waiting for the redirect that shows it. Keyed
# by token so a second session cannot read the first one's answer.
_LAST_CHECK: Dict[str, Any] = {}
# Something to say on the settings page after a button that did not work.
_NOTICE: Dict[str, str] = {}
# Why a switch of config directory was refused, for whichever page it came from.
_CONFIG_NOTICE: Dict[str, str] = {}
# What the language section should say next time it is drawn: the result of a
# check, or an offer to download a set. One per token, cleared when shown.
_ART: Dict[str, Dict[str, Any]] = {}
# The outcome of saving a SteamGridDB key, waiting for the redirect that shows
# it. Never the key itself -- only whether it was accepted, and why not.
_SGDB: Dict[str, Dict[str, Any]] = {}
# Which SteamGridDB pictures this session has actually been offered: id ->
# origin, per token. The image route resolves an id through this and never
# takes a URL from the page -- a server that fetches whatever address it is
# handed is a server that can be aimed at anything it can reach, including
# whatever else is listening on this machine. Issue #31.
_SGDB_SEEN: Dict[str, Dict[str, str]] = {}
# Two pages' worth, so paging back does not orphan the pictures behind you.
_SGDB_SEEN_MAX = 2 * 48


def _sheet_fit(asked: str) -> str:
    """The sheet's size as sheet.js measured it, "WxH" in pixels, or "".

    It goes back out inside a style attribute, so it is rebuilt from two
    integers rather than passed through, and anything implausible is dropped:
    the sheet then falls back to its stylesheet size, which is only less snug.
    """
    w, sep, h = asked.partition("x")
    if not sep or not w.isdigit() or not h.isdigit():
        return ""
    w_px, h_px = int(w), int(h)
    if not (200 <= w_px <= 8000 and 200 <= h_px <= 8000):
        return ""
    return f"{w_px}x{h_px}"


def _tile_language() -> str:
    """Which set the tiles are actually coming from, as a sentence."""
    from . import i18n

    folder = os.path.basename(i18n.tile_set())
    if folder == i18n.WORDLESS:
        return "Showing tiles with no words, which are right in every language."
    for item in i18n.languages():
        if item["code"] == folder:
            return f"Showing {item['name_in_english']} tiles."
    return f"Showing {folder} tiles."


def _language_panel(token: str) -> Dict[str, Any]:
    from . import i18n

    system = i18n.system_language()
    suffix = f" ({system})" if system else ""
    return {"languages": i18n.languages(), "system_suffix": suffix,
            "showing": _tile_language(), "art": _ART.pop(token, None)}


def _offer_artwork(token: str, code: str) -> None:
    """After a language change: is there artwork for it, and is it here?

    Nothing is downloaded by changing the language. The set is a couple of
    megabytes and the person asked to change a language, not to start a
    download; so this offers, and the offer names the language.
    """
    from . import i18n, tileart

    wanted = code or i18n.system_language()
    if not wanted or tileart.have_set(wanted):
        return                              # already covered, or no opinion
    remote, why = tileart.remote_manifest()
    if why:
        _ART[token] = {"state": "unreachable",
                       "message": f"Wordless tiles are being used. {why}."}
        return
    for candidate in i18n.candidates(wanted):
        if candidate in remote and candidate != i18n.DEFAULT:
            _ART[token] = {
                "state": "available",
                "message": (f"Tiles are published for {candidate}. "
                            f"Until they are here, the wordless set is used."),
                "action": f"/settings/art-fetch?token={token}&code={candidate}",
                "label": f"Download the {candidate} tiles"}
            return
    _ART[token] = {"state": "none",
                   "message": (f"Nobody has made tiles for {wanted} yet, so the "
                               f"wordless set is used. Adding a language is a "
                               f"file and a pull request; the link above says "
                               f"how.")}


def _check_artwork(token: str) -> None:
    from . import tileart

    remote, why = tileart.remote_manifest()
    if why:
        _ART[token] = {"state": "unreachable", "message": why.capitalize() + "."}
        return
    behind = tileart.stale(remote)
    if not behind:
        _ART[token] = {"state": "none",
                       "message": "The tile artwork here is the published one."}
        return
    code, count = sorted(behind.items())[0]
    rest = (f" ({len(behind) - 1} other set also differs)" if len(behind) == 2
            else f" ({len(behind) - 1} other sets also differ)"
            if len(behind) > 2 else "")
    _ART[token] = {
        "state": "available",
        "message": (f"{count} tile{'s' if count != 1 else ''} in the {code} "
                    f"set {'differ' if count != 1 else 'differs'} from the "
                    f"published artwork{rest}."),
        "action": f"/settings/art-fetch?token={token}&code={code}",
        "label": f"Update the {code} tiles"}


def _fetch_artwork(token: str, code: str) -> None:
    from . import tileart

    written, why = tileart.fetch_set(code)
    if why:
        _ART[token] = {"state": "unreachable", "message": why.capitalize() + "."}
        return
    _ART[token] = {
        "state": "available",
        "message": (f"{written} tiles saved for {code}. They go onto the grid "
                    f"on the next scan, where you can see the change before "
                    f"anything is written."),
        "action": f"/?scan=1&token={token}",
        "method": "get",
        "label": "Scan now"}


def _count_apps(conf_dir: str) -> Optional[int]:
    """How many entries a tree's apps.json holds, or None if it cannot be read.

    The single most telling fact when choosing between two trees: the live one
    is usually the one with your games in it.
    """
    try:
        with open(os.path.join(conf_dir, "apps.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    apps = payload.get("apps") if isinstance(payload, dict) else payload
    return len(apps) if isinstance(apps, list) else None


def _describe_platform() -> str:
    """Enough for a bug report, and nothing that identifies the machine."""
    import platform

    system = platform.system() or "unknown"
    release = platform.release() or ""
    return f"{system} {release}".strip()


def serve(token: str, conf_dir: str,
           importer_opts: Optional[Dict[str, Any]] = None,
           port: int = 0, choice: Optional[Dict[str, Any]] = None,
           config_home: Optional[str] = None) -> ThreadingHTTPServer:
    """Bind and return a server. The address is always loopback, by design."""
    # Asked once, here, rather than at the first write. See privilege.py.
    rights = privilege.check(conf_dir)
    # Read-only is a warning even without --verbose: it is the one startup fact
    # that changes what the program can do for you.
    (log.info if rights.can_write else log.warning)(
        "%s", privilege.startup_line(rights, conf_dir))
    handler = type("BoundPlanHandler", (PlanHandler,), {
        "token": token,
        "conf_dir": conf_dir,
        "config": dict(choice or {"how": "only", "candidates": [], "stale": False}),
        "config_home": config_home,
        "rights": rights,
        "importer_opts": dict(importer_opts or {}),
        # Set by our launcher, which only ever runs inside a streamed session.
        "via_sunshine": os.getenv("BSM_UI_VIA_SUNSHINE", "") == "1",
    })
    # The queue is deliberately kept between runs; drafts are not. They belong
    # to a form that is no longer open, and a stale one silently overrides the
    # file it was drafted against.
    state.clear_drafts()
    httpd = ThreadingHTTPServer((security.BIND_HOST, port), handler)
    handler.port = httpd.server_address[1]    # resolve port 0 to what we actually got
    return httpd
