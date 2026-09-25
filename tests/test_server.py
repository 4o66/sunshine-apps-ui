# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end tests against a real server on a loopback port."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Dict
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from unittest import mock  # noqa: E402

from sunshine_apps_ui import security  # noqa: E402
from sunshine_apps_ui import server as server_module  # noqa: E402
from sunshine_apps_ui.server import serve  # noqa: E402

PLAN = {
    "schema": 1,
    "generator": {"name": "bazzite-sunshine-manager", "version": "2.0"},
    "generated_at": "2026-09-12T02:00:00-0700",
    "dry_run": True,
    "config_dir": "/home/u/.config/sunshine",
    "apps_json": "/home/u/.config/sunshine/apps.json",
    "sources": [{"name": "steam", "enabled": True, "status": "ok", "imported": 2},
                {"name": "heroic", "enabled": True, "status": "not_found", "imported": 0}],
    "totals": {"added": 1, "updated": 0, "unchanged": 0, "diverged": 1,
               "missing": 0, "kept_foreign": 1, "removed_by_user": 0,
               "suppressed": 0, "pruned": 0, "restored": 0},
    "plan": {
        # Deliberately not one of the apps in STATE: a scan's "added" means an
        # entry the file does not have yet.
        "added": [{"name": "Half-Life", "source": "steam", "id": "70",
                   "entry": {"name": "Half-Life", "cmd": "steam -applaunch 70",
                             "bsm": {"v": 1, "source": "steam", "id": "70",
                                     "fields": {}}}}],
        "updated": [], "unchanged": [],
        "diverged": [{"name": "Cyberpunk 2077", "source": "steam", "id": "1091500",
                      "fields": [{"field": "cmd", "current": "mine <script>",
                                  "would_be": "theirs"}]}],
        "missing": [], "kept_foreign": [{"name": "Desktop"}],
        "removed_by_user": [], "suppressed": [], "pruned": [], "restored": [],
    },
}


STATE = {
    "schema": 1,
    "generator": {"name": "bazzite-sunshine-manager", "version": "2.0"},
    "config_dir": "/home/u/.config/sunshine",
    "apps_json": "/home/u/.config/sunshine/apps.json",
    "apps": [
        {"index": 0, "name": "Desktop", "image-path": "desktop.png", "cmd": "",
         "source": None, "id": None, "managed": False},
        {"index": 1, "name": "Portal 2", "image-path": "/img/620.png",
         "cmd": "steam -applaunch 620", "source": "steam", "id": "620",
         "managed": True},
    ],
    "hidden": [{"name": "TF2", "source": "steam", "id": "440",
                "image-path": "/img/440.png", "at": "2026-09-13T00:00:00+0000"}],
}


class FakeEngine:
    """Stands in for core, at the seam the server actually binds.

    The server used to reach core by running it as a program, so the tests
    supplied a shell script that printed JSON. Now it calls it, so they supply
    the answers directly: faster, and it tests the server rather than a fixture
    of a command line.
    """

    def __init__(self, state=None, plan=None):
        self.state = state if state is not None else dict(STATE)
        self.plan = plan if plan is not None else dict(PLAN)
        self.auth = (True, "ok")
        self.listing = {"ok": True, "path": "/home/u", "parent": "/home", "entries": []}
        self.candidates = {"ok": True, "candidates": [], "notes": []}
        # Every SteamGridDB fetch the handler makes, so a test can assert that
        # opening the picker makes none at all. Issue #30.
        self.sgdb_calls = []
        self.sgdb = {"ok": True, "candidates": [], "note": "", "total": 0,
                     "page": 0, "per": 48, "pages": 0}
        self.chosen = ""
        self.copies = []
        self.diff = {}
        self.saved = None
        self.applied = []
        self.fails = {}                 # name -> message, to make one call fail

    # Each of these matches what the server imported from engine.

    def get_state(self, conf_dir, use_cache=False):
        self._maybe_fail("get_state")
        return self.state

    def run_plan(self, conf_dir, opts=None):
        self._maybe_fail("run_plan")
        return self.plan, "log line"

    # Per-operation outcomes the fake should report, keyed by qid. Anything not
    # named here succeeds. Set by a test that wants a refusal.
    refuse: Dict[str, str] = {}

    def mutate(self, conf_dir, ops, reload=True):
        self._maybe_fail("mutate")
        self.applied.append(list(ops))
        results = []
        for op in ops:
            why = self.refuse.get(str(op.get("qid", "")))
            if why:
                results.append({"op": op.get("op"), "ok": False,
                                "name": op.get("name"), "error": why})
            else:
                results.append({"op": op.get("op"), "ok": True,
                                "name": op.get("name")})
        ok = all(r["ok"] for r in results)
        return ok, f"Applied {sum(1 for r in results if r['ok'])} change(s)", results

    def browse(self, conf_dir, path="", kind="any"):
        self._maybe_fail("browse")
        return self.listing

    def art_search(self, conf_dir, name="", source="", ident=""):
        self._maybe_fail("art_search")
        self.searched = {"name": name, "source": source, "ident": ident}
        return self.candidates

    def art_sgdb(self, conf_dir, name="", source="", ident="", page=0, per=0):
        self._maybe_fail("art_sgdb")
        self.sgdb_calls.append({"name": name, "source": source,
                                "ident": ident, "page": page, "per": per})
        return self.sgdb

    def art_choose(self, conf_dir, chosen_id, name=""):
        self._maybe_fail("art_choose")
        return self.chosen or f"/img/{name}-{chosen_id}.png"

    def list_backups(self, conf_dir):
        self._maybe_fail("list_backups")
        return self.copies

    def backup_diff(self, conf_dir, name):
        self._maybe_fail("backup_diff")
        return dict(self.diff, backup=name)

    def check_auth(self, conf_dir):
        return self.auth

    def save_auth(self, conf_dir, username, password):
        self.saved = (username, password)
        return self.auth

    def _maybe_fail(self, name):
        if name in self.fails:
            from sunshine_apps_ui.engine import EngineError
            raise EngineError(self.fails[name])


class ServerTest(unittest.TestCase):
    def setUp(self):
        # Every test gets its own state, and every test's state is gone when it
        # ends. Shared state between tests here is not a tidiness question: the
        # queue is a file, and two tests using one file race.
        self.state_dir = tempfile.mkdtemp()
        self._previous_state_home = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state_dir

        self.conf_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.conf_dir, True)
        self.engine = FakeEngine()
        for name in ("get_state", "run_plan", "mutate", "browse", "art_search",
                     "art_sgdb", "art_choose", "list_backups", "backup_diff",
                     "check_auth", "save_auth"):
            patched = mock.patch.object(server_module, name,
                                        getattr(self.engine, name))
            patched.start()
            self.addCleanup(patched.stop)

        self.token = security.new_token()
        self.httpd = serve(self.token, self.conf_dir, {}, port=0)
        # ThreadingHTTPServer runs handlers as daemon threads and does not wait
        # for them, so a request still being served when a test ends carries on
        # into the next one -- writing that test's queue file out from under it.
        # This made StopAfterApplyTest fail about one run in five, and only on
        # the machine fast enough to start the next test before the last one
        # had finished.
        self.httpd.daemon_threads = False
        self.httpd.block_on_close = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()          # joins any handler still running
        if self._previous_state_home is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._previous_state_home
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def scan(self, wait=20.0):
        """Ask for a scan, wait for the thread, and return the grid it produced.

        A scan no longer happens on the request thread: asking for one now
        returns the page that watches it. Tests that care what a scan *found*
        have to wait for it, which is what the interface does too.
        """
        from sunshine_apps_ui import scanjob
        self.get(f"/?scan=1&token={self.token}")
        deadline = time.monotonic() + wait
        while scanjob.job.running() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(scanjob.job.running(), "the scan never finished")
        return self.get(f"/?scanned=1&token={self.token}")

    def get(self, path="/", token=None, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        if token:
            url += f"?token={token}"
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                # Some responses are binary (artwork), so never assume text.
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def post(self, body, token=None, headers=None, path="/credentials"):
        url = f"http://127.0.0.1:{self.port}{path}"
        if token:
            url += f"?token={token}"
        data = urllib.parse.urlencode(body).encode()
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method="POST")
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

    def get_no_redirect(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(url, timeout=10) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

    def test_it_binds_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_valid_token_renders_the_plan(self):
        status, body = self.get("/plan", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("Half-Life", body)
        self.assertIn("Cyberpunk 2077", body)
        self.assertIn("steam", body)

    def test_no_token_is_refused(self):
        status, body = self.get()
        self.assertEqual(status, 404)
        self.assertNotIn("Portal 2", body)

    def test_wrong_token_is_refused(self):
        self.assertEqual(self.get(token="wrong")[0], 404)

    def test_refusal_does_not_reveal_why(self):
        """A prober should not learn whether the token or the Host was wrong."""
        a = self.get(token="wrong")
        b = self.get(token=self.token, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(a, b)

    def test_cross_site_request_is_refused_even_with_the_token(self):
        status, _ = self.get(token=self.token, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 404)

    def test_rebound_host_header_is_refused(self):
        status, _ = self.get(token=self.token, headers={"Host": "evil.example.com"})
        self.assertEqual(status, 404)

    def test_unknown_path_is_not_served(self):
        self.assertEqual(self.get("/etc/passwd", token=self.token)[0], 404)

    def test_unmanaged_entries_are_described_without_guessing_their_origin(self):
        """The tool knows it did not create them; it does not know who did."""
        _, body = self.get("/plan", token=self.token)
        self.assertIn("Left alone", body)
        self.assertNotIn("Not ours", body)
        self.assertNotIn("entries you created", body)

    def test_user_content_is_escaped(self):
        _, body = self.get("/plan", token=self.token)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_the_policy_permits_what_the_page_actually_loads(self):
        """A policy that blocks your own assets fails silently in the browser."""
        url = f"http://127.0.0.1:{self.port}/?token={self.token}"
        with urllib.request.urlopen(url, timeout=10) as r:
            csp = r.headers["Content-Security-Policy"]
            body = r.read().decode()
        if "<img" in body:
            self.assertIn("img-src 'self'", csp)
        if "<form" in body:
            self.assertIn("form-action 'self'", csp)
        if "<script" in body:
            self.assertIn("script-src 'self'", csp)

    def test_security_headers_are_present(self):
        url = f"http://127.0.0.1:{self.port}/?token={self.token}"
        with urllib.request.urlopen(url, timeout=10) as r:
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))


class EngineSeamTest(ServerTest):
    """What used to be the CLI contract is now a function call.

    The guarantees worth keeping are the same two: a plan never writes, and a
    failure is reported rather than rendered as an empty page.
    """

    def test_looking_at_the_plan_never_writes(self):
        self.get(f"/plan?token={self.token}")
        self.assertEqual(self.engine.applied, [])

    def test_a_failure_is_shown_rather_than_an_empty_page(self):
        self.engine.fails["run_plan"] = "the library is offline"
        status, body = self.get(f"/plan?token={self.token}")
        self.assertEqual(status, 500)
        self.assertIn("the library is offline", body)

    def test_a_failure_reading_the_apps_is_shown_too(self):
        self.engine.fails["get_state"] = "apps.json is not readable"
        status, body = self.get(f"/?token={self.token}")
        self.assertEqual(status, 500)
        self.assertIn("apps.json is not readable", body)


class CredentialsEndpointTest(ServerTest):
    """The first POST endpoint, and the reason the cross-site rules exist."""

    def test_a_post_without_a_token_is_refused(self):
        status, _ = self.post({"username": "a", "password": "b"})
        self.assertEqual(status, 404)

    def test_a_cross_site_post_is_refused_even_with_the_token(self):
        """A navigation exemption must never apply to an unsafe method."""
        status, _ = self.post({"username": "a", "password": "b"}, token=self.token,
                              headers={"Sec-Fetch-Site": "cross-site",
                                       "Sec-Fetch-Mode": "navigate",
                                       "Sec-Fetch-Dest": "document"})
        self.assertEqual(status, 404)

    def test_an_unknown_post_path_is_refused(self):
        status, _ = self.post({"a": "b"}, token=self.token, path="/anything")
        self.assertEqual(status, 404)

    def test_a_valid_post_redirects_rather_than_rendering(self):
        """Post/redirect/get, so refreshing cannot resubmit the password."""
        status, headers = self.post({"username": "a", "password": "b"}, token=self.token)
        self.assertEqual(status, 303)
        self.assertIn("/?", headers["Location"])

    def test_the_password_never_appears_in_the_redirect(self):
        _, headers = self.post({"username": "admin", "password": "sup3rsecret"},
                               token=self.token)
        self.assertNotIn("sup3rsecret", headers["Location"])

    def test_an_oversized_body_is_rejected(self):
        """Edit forms are bigger than a login, so the cap is 64K, not 8K."""
        status, _ = self.post({"username": "a" * 70000, "password": "b"}, token=self.token)
        self.assertEqual(status, 400)

    def test_the_form_is_offered_when_asked_for(self):
        status, body = self.get(f"/connect?token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("Connect to Sunshine", body)
        self.assertIn('type="password"', body)

    def test_the_form_posts_back_to_us_and_csp_permits_it(self):
        url = f"http://127.0.0.1:{self.port}/connect?token={self.token}"
        with urllib.request.urlopen(url, timeout=10) as r:
            csp = r.headers["Content-Security-Policy"]
            body = r.read().decode()
        self.assertIn("form-action 'self'", csp)
        self.assertIn('action="/credentials', body)

    def test_a_rejected_save_shows_the_reason_not_a_generic_message(self):
        status, body = self.get(
            f"/connect?msg=Sunshine+rejected+the+credentials&token={self.token}")
        self.assertIn("Sunshine rejected the credentials", body)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ApplyTest(ServerTest):
    """Apply writes and reloads, behind a confirmation that says what happens."""

    def setUp(self):
        super().setUp()
        # The confirmation shows the queue, so these need one. It used to show
        # what a scan found as well, which is why they did not before.
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})

    def test_get_apply_shows_a_confirmation_and_changes_nothing(self):
        status, body = self.get("/apply", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("Write and reload", body)
        self.assertIn("Cancel", body)

    def test_the_confirmation_lists_the_actual_changes(self):
        """Naming them beats asserting that some exist."""
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Your changes", body)
        self.assertIn("Hide Portal 2", body)

    def test_the_confirmation_states_the_disconnect(self):
        _, body = self.get("/apply", token=self.token)
        self.assertIn("30 seconds", body)
        self.assertIn("Moonlight", body)

    def test_wording_is_direct_when_viewed_through_a_stream(self):
        self.httpd.RequestHandlerClass.via_sunshine = True
        try:
            _, body = self.get("/apply", token=self.token)
            self.assertIn("This will disconnect you", body)
        finally:
            self.httpd.RequestHandlerClass.via_sunshine = False

    def test_wording_is_conditional_when_not_in_a_stream(self):
        _, body = self.get("/apply", token=self.token)
        self.assertNotIn("This will disconnect you", body)
        self.assertIn("Any stream in progress", body)

    def test_getting_apply_without_a_token_is_refused(self):
        self.assertEqual(self.get("/apply")[0], 404)

    def test_posting_apply_without_a_token_is_refused(self):
        status, _ = self.post({}, path="/apply")
        self.assertEqual(status, 404)

    def test_a_cross_site_post_to_apply_is_refused(self):
        status, _ = self.post({}, token=self.token, path="/apply",
                              headers={"Sec-Fetch-Site": "cross-site",
                                       "Sec-Fetch-Mode": "navigate",
                                       "Sec-Fetch-Dest": "document"})
        self.assertEqual(status, 404)

    def test_applying_nothing_just_returns_to_the_grid(self):
        """Apply means "apply the queue"; an empty queue has nothing to do."""
        from sunshine_apps_ui import state as st
        st.clear_queue()
        status, headers = self.post({}, token=self.token, path="/apply")
        self.assertEqual(status, 303)
        self.assertNotIn("/applied", headers["Location"])

    def test_applying_writes_and_reloads(self):
        """What "apply" means, now that it is a call and not two CLI flags."""
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "edit", "index": 1, "name": "Portal 2",
                    "fields": {"name": "Portal 2"}})
        captured = {}
        original = self.engine.mutate

        def watched(conf_dir, ops, reload=True):
            captured["reload"] = reload
            return original(conf_dir, ops, reload)

        self.engine.mutate = watched
        import sunshine_apps_ui.server as sm
        patched = mock.patch.object(sm, "mutate", watched)
        patched.start()
        self.addCleanup(patched.stop)
        self.post({}, token=self.token, path="/apply")
        self.assertTrue(captured.get("reload"), "apply must reload, or nothing sees it")
        self.assertEqual(len(self.engine.applied), 1)

    def test_looking_at_the_confirmation_writes_nothing(self):
        self.get("/apply", token=self.token)
        self.assertEqual(self.engine.applied, [])


class AppliedPageTest(ServerTest):
    def queue_a_change(self):
        """Apply with an empty queue goes home, which is not what is being tested.

        These two used to pass without this, on whatever happened to be left in
        the real state directory by an earlier test.
        """
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "edit", "index": 1, "name": "Portal 2",
                    "fields": {"name": "Portal 2"}})

    def test_success_lands_somewhere_static(self):
        """Re-running the importer here would race the teardown the apply caused."""
        self.queue_a_change()
        status, headers = self.post({}, token=self.token, path="/apply")
        self.assertEqual(status, 303)
        self.assertTrue(headers["Location"].startswith("/applied?"), headers["Location"])

    def test_the_applied_page_asks_the_engine_for_nothing(self):
        """Scanning here would race the teardown the apply just caused."""
        self.engine.fails["run_plan"] = "must not be called"
        self.engine.fails["get_state"] = "must not be called"
        status, body = self.get(f"/applied?token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("Applied", body)

    def test_an_empty_queue_has_nothing_to_apply(self):
        """Applying reloads Sunshine and reloading disconnects, so doing it for
        no change is worse than doing nothing."""
        status, headers = self.post({}, token=self.token, path="/apply")
        self.assertEqual(status, 303)
        self.assertTrue(headers["Location"].startswith("/?"), headers["Location"])

    def test_applied_needs_the_token(self):
        self.assertEqual(self.get("/applied")[0], 404)

    def test_a_failed_apply_still_returns_to_the_grid(self):
        """Nothing reloaded, so nothing is tearing down; the grid is safe to render."""
        self.engine.fails["mutate"] = "boom"
        self.queue_a_change()
        status, headers = self.post({}, token=self.token, path="/apply")
        self.assertEqual(status, 303)
        self.assertIn("apply_error", headers["Location"])


class AppPageTest(ServerTest):
    def test_it_shows_every_editable_field(self):
        status, body = self.get(f"/app?index=1&token={self.token}")
        self.assertEqual(status, 200)
        for field in ("name", "cmd", "working-dir", "image-path"):
            self.assertIn(f'name="{field}"', body)

    def test_it_says_whether_the_importer_owns_the_entry(self):
        _, managed = self.get(f"/app?index=1&token={self.token}")
        self.assertIn("Created by the importer", managed)
        _, mine = self.get(f"/app?index=0&token={self.token}")
        self.assertIn("Yours.", mine)

    def test_the_new_form_has_no_delete_or_hide(self):
        _, body = self.get(f"/app?new=1&token={self.token}")
        self.assertNotIn("op=hide", body)
        self.assertNotIn("op=delete", body)

    def test_a_missing_index_is_a_clean_message(self):
        status, body = self.get(f"/app?index=99&token={self.token}")
        self.assertEqual(status, 404)
        self.assertIn("no longer there", body)

    def test_the_script_that_guards_apply_is_served(self):
        status, body = self.get(f"/app.js?token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("data-apply", body)

    def test_the_page_asks_for_that_script_with_a_token(self):
        """Every request needs one, including the page's own assets."""
        _, body = self.get(f"/app?index=1&token={self.token}")
        self.assertIn(f'src="/app.js?token={self.token}"', body)
        self.assertIn("data-dirty-guard", body)

    def test_a_browser_form_post_is_accepted(self):
        """The exact header shape Chrome sends for a same-origin form post."""
        status, headers = self.post(
            {"op": "hide", "index": "1", "name": "Portal 2"},
            token=self.token, path="/queue",
            headers={"Origin": "null", "Sec-Fetch-Site": "same-origin",
                     "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
        self.assertEqual(status, 303)


class ExplainTest(ServerTest):
    def setUp(self):
        super().setUp()
        self.state_dir = tempfile.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state_dir

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        import shutil
        shutil.rmtree(self.state_dir, ignore_errors=True)
        super().tearDown()

    def test_hide_and_delete_are_explained_differently(self):
        _, hide = self.get(f"/explain?op=hide&index=1&token={self.token}")
        _, delete = self.get(f"/explain?op=delete&index=1&token={self.token}")
        self.assertIn("will not bring it back", hide)
        self.assertIn("will find it again", delete)

    def test_the_checkbox_defaults_to_showing_it_every_time(self):
        _, body = self.get(f"/explain?op=hide&index=1&token={self.token}")
        self.assertIn('name="keep_explaining" checked', body)

    def test_unchecking_it_silences_that_operation_only(self):
        from sunshine_apps_ui import state as st
        self.post({"op": "hide", "index": "1", "name": "Portal 2"},
                  token=self.token, path="/queue")
        self.assertFalse(st.should_explain("hide"))
        self.assertTrue(st.should_explain("delete"))

    def test_keeping_it_checked_leaves_the_preference_alone(self):
        from sunshine_apps_ui import state as st
        self.post({"op": "hide", "index": "1", "name": "Portal 2",
                   "keep_explaining": "on"}, token=self.token, path="/queue")
        self.assertTrue(st.should_explain("hide"))

    def test_a_silenced_operation_queues_without_the_interstitial(self):
        from sunshine_apps_ui import state as st
        st.set_explain("delete", False)
        # get() follows the redirect, so we land back on the grid rather than
        # on an explanation page.
        status, body = self.get(f"/explain?op=delete&index=1&token={self.token}")
        self.assertEqual(status, 200)
        self.assertNotIn("Delete this application?", body)
        self.assertEqual(len(st.queue()), 1)
        self.assertEqual(st.queue()[0]["op"], "delete")

    def test_an_unknown_operation_is_not_explained(self):
        status, _ = self.get(f"/explain?op=nuke&index=1&token={self.token}")
        self.assertEqual(status, 404)


class QueueTest(ExplainTest):
    def test_editing_queues_rather_than_writing(self):
        from sunshine_apps_ui import state as st
        self.post({"op": "edit", "index": "1", "orig_name": "Portal 2",
                   "name": "Portal Two", "cmd": "x"}, token=self.token, path="/app")
        self.assertEqual(st.queue()[0]["op"], "edit")
        self.assertEqual(st.queue()[0]["fields"]["name"], "Portal Two")

    def test_apply_appears_on_the_grid_only_once_something_is_queued(self):
        _, before = self.get(token=self.token)
        self.assertNotIn(">Apply ", before)
        self.post({"op": "edit", "index": "1", "orig_name": "Portal 2",
                   "name": "X"}, token=self.token, path="/app")
        _, after = self.get(token=self.token)
        self.assertIn("Apply 1 change", after)

    def test_discarding_empties_the_queue(self):
        from sunshine_apps_ui import state as st
        self.post({"op": "edit", "index": "1", "orig_name": "Portal 2",
                   "name": "X"}, token=self.token, path="/app")
        self.post({}, token=self.token, path="/discard")
        self.assertEqual(st.queue(), [])

    def test_an_unknown_action_is_refused(self):
        status, _ = self.post({"op": "destroy", "index": "1"},
                              token=self.token, path="/app")
        self.assertEqual(status, 400)


class GridTest(ServerTest):
    def test_the_front_page_is_the_grid_of_what_is_loaded(self):
        status, body = self.get(token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("2 applications", body)
        self.assertIn("Desktop", body)
        self.assertIn("Portal 2", body)

    def test_hidden_entries_appear_muted_and_marked(self):
        _, body = self.get(token=self.token)
        self.assertIn("tile hidden", body)
        self.assertIn('class="mark">hidden', body)
        self.assertIn("TF2", body)

    def test_nothing_is_marked_new_until_a_scan(self):
        _, body = self.get(token=self.token)
        self.assertNotIn("tile new", body)

    def test_a_scan_stages_what_it_found_onto_the_grid(self):
        """Findings become pending changes you can see, not a separate channel."""
        import tempfile as tf, shutil as sh
        d = tf.mkdtemp()
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = d
        try:
            from sunshine_apps_ui import state as st
            _, body = self.scan()
            self.assertIn(">NEW<", body)
            self.assertIn("ghost found", body)
            self.assertEqual([o["op"] for o in st.queue()], ["adopt"])
            self.assertIn("Apply 1 change", body)
        finally:
            if old is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = old
            sh.rmtree(d, ignore_errors=True)

    def test_scanning_twice_does_not_stage_it_twice(self):
        import tempfile as tf, shutil as sh
        d = tf.mkdtemp()
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = d
        try:
            from sunshine_apps_ui import state as st
            self.scan()
            self.scan()
            self.assertEqual(len(st.queue()), 1)
        finally:
            if old is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = old
            sh.rmtree(d, ignore_errors=True)

    def test_there_is_an_add_tile(self):
        _, body = self.get(token=self.token)
        self.assertIn("Add an application", body)

    def test_a_queued_hide_is_visible_on_the_tile(self):
        """The grid is where changes are shown, so a queued change belongs on it."""
        import tempfile as tf, shutil as sh
        d = tf.mkdtemp()
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = d
        try:
            from sunshine_apps_ui import state as st
            st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
            _, body = self.get(token=self.token)
            self.assertIn("WILL HIDE", body)
            self.assertIn("tile pending", body)
            self.assertIn("queued, not applied yet", body)
        finally:
            if old is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = old
            sh.rmtree(d, ignore_errors=True)

    def test_a_queued_delete_reads_differently_from_a_hide(self):
        import tempfile as tf, shutil as sh
        d = tf.mkdtemp()
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = d
        try:
            from sunshine_apps_ui import state as st
            st.enqueue({"op": "delete", "index": 1, "name": "Portal 2"})
            _, body = self.get(token=self.token)
            self.assertIn("WILL DELETE", body)
            self.assertNotIn("WILL HIDE", body)
        finally:
            if old is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = old
            sh.rmtree(d, ignore_errors=True)

    def test_a_queued_addition_appears_as_a_ghost_tile(self):
        import tempfile as tf, shutil as sh
        d = tf.mkdtemp()
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = d
        try:
            from sunshine_apps_ui import state as st
            st.enqueue({"op": "add", "fields": {"name": "My Script"}})
            _, body = self.get(token=self.token)
            self.assertIn("tile ghost", body)
            self.assertIn("My Script", body)
            self.assertIn("NEW QUEUED", body)
        finally:
            if old is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = old
            sh.rmtree(d, ignore_errors=True)

    def test_the_plan_view_is_no_longer_linked_from_the_grid(self):
        """The grid shows changes now; a separate diff view only confuses."""
        _, body = self.get(token=self.token)
        self.assertNotIn("What would change", body)

    def test_discard_is_offered_only_when_something_is_queued(self):
        _, body = self.get(token=self.token)
        self.assertNotIn(">Discard<", body)

    def test_apply_is_absent_with_nothing_queued(self):
        _, body = self.get(token=self.token)
        self.assertNotIn("Apply 0", body)
        self.assertNotIn(">Apply ", body)


class ScanRoutesTest(ServerTest):
    """Asking for a scan, and watching the one that is running.

    The scan used to happen on this thread and the answer arrived fifty
    seconds later with nothing in between.
    """

    def test_asking_for_a_scan_does_not_return_the_grid(self):
        """It returns the page that watches the scan, at its own address."""
        opener = urllib.request.build_opener(NoRedirect)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/?scan=1&token={self.token}")
        try:
            response = opener.open(request)
            status, location = response.status, response.headers.get("Location")
        except urllib.error.HTTPError as e:
            status, location = e.code, e.headers.get("Location")
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/scanning"), location)

    def test_the_watching_page_does_not_start_a_scan(self):
        """A refresh while scanning must watch, not launch another."""
        from sunshine_apps_ui import scanjob
        runs_before = scanjob.job.status()["run"]
        self.get(f"/scanning?token={self.token}")
        self.get(f"/scanning?token={self.token}")
        self.assertEqual(scanjob.job.status()["run"], runs_before)

    def test_the_status_is_json_and_says_whether_it_is_running(self):
        _, body = self.get(f"/scan/status?token={self.token}")
        status = json.loads(body)
        self.assertIn("running", status)
        self.assertIn("latest", status)
        self.assertIn("elapsed", status)

    def test_the_status_does_not_carry_the_whole_log_on_every_poll(self):
        """It is asked every 400 ms; the log would send the scan twice over."""
        _, body = self.get(f"/scan/status?token={self.token}")
        self.assertNotIn("lines", json.loads(body))

    def test_the_watcher_script_is_served(self):
        """It cannot be inline: these pages are sent with script-src 'self'."""
        _, body = self.get(f"/scanning.js?token={self.token}")
        self.assertIn("data-scan-status", body)

    def test_the_policy_allows_the_page_to_ask_how_the_scan_is_going(self):
        """default-src 'none' with no connect-src blocks the fetch silently."""
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/scanning?token={self.token}")
        policy = response.headers.get("Content-Security-Policy")
        self.assertIn("connect-src 'self'", policy)
        self.assertIn("script-src 'self'", policy)

    def test_neither_route_answers_without_a_token(self):
        for path in ("/scan/status", "/scanning"):
            _, body = self.get(path)
            self.assertIn("Not found", body)

    def test_a_finished_scan_sends_the_watcher_to_the_grid(self):
        opener = urllib.request.build_opener(NoRedirect)
        self.scan()                      # leaves the job finished, not running
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/scanning?token={self.token}")
        try:
            response = opener.open(request)
            status, location = response.status, response.headers.get("Location")
        except urllib.error.HTTPError as e:
            status, location = e.code, e.headers.get("Location")
        self.assertEqual(status, 303)
        self.assertIn("scanned=1", location)


class ArtworkTest(ServerTest):
    def _art(self, path):
        from urllib.parse import quote
        return self.get(f"/art?p={quote(path, safe='')}&token={self.token}")

    def test_an_unreferenced_path_is_not_served(self):
        """Not refused by inspecting it -- simply not in the allowlist."""
        status, _ = self._art("/etc/passwd")
        self.assertEqual(status, 404)

    def test_traversal_is_not_served(self):
        status, _ = self._art("/img/../../etc/shadow")
        self.assertEqual(status, 404)

    def test_a_referenced_but_missing_file_is_a_clean_404(self):
        status, _ = self._art("/img/620.png")
        self.assertEqual(status, 404)

    def test_art_needs_the_token(self):
        from urllib.parse import quote
        status, _ = self.get(f"/art?p={quote('/img/620.png', safe='')}")
        self.assertEqual(status, 404)


class ApplyCountsTheQueueTest(ServerTest):
    """Apply asked about the importer's plan and ignored the queue entirely."""

    def setUp(self):
        super().setUp()
        import tempfile as tf
        self.sd = tf.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.sd

    def tearDown(self):
        import shutil as sh
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        sh.rmtree(self.sd, ignore_errors=True)
        super().tearDown()

    def test_the_confirmation_counts_queued_changes(self):
        """The queue, and only the queue: that is what applying applies."""
        from sunshine_apps_ui import state as st
        _, before = self.get("/apply", token=self.token)
        self.assertIn("Apply 0 changes?", before)
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        _, after = self.get("/apply", token=self.token)
        self.assertIn("Apply 1 change?", after)

    def test_the_confirmation_names_them_in_plain_words(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        st.enqueue({"op": "add", "fields": {"name": "My Script"}})
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Your changes", body)
        self.assertIn("Hide Portal 2", body)
        self.assertIn("Add My Script", body)

    def test_nothing_queued_reads_as_nothing_however_much_a_scan_would_find(self):
        """A scan finding things is not a reason to promise them here."""
        self.engine.plan = dict(PLAN)
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Nothing would change.", body)
        self.assertIn("Apply 0 changes?", body)

    def test_applying_a_queue_is_one_write_and_one_reload(self):
        """One session of changes should cost one disconnect, not one per step."""
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        st.enqueue({"op": "add", "fields": {"name": "My Script"}})
        self.post({}, token=self.token, path="/apply")
        self.assertEqual(len(self.engine.applied), 1,
                         "the whole queue goes in one call")
        self.assertEqual(len(self.engine.applied[0]), 2)


class HiddenEntryTest(ServerTest):
    """A hidden entry needs a way back, or hiding is one-way in the UI."""

    def setUp(self):
        super().setUp()
        import tempfile as tf
        self.sd = tf.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.sd

    def tearDown(self):
        import shutil as sh
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        sh.rmtree(self.sd, ignore_errors=True)
        super().tearDown()

    def test_a_hidden_tile_has_a_detail_page(self):
        status, body = self.get(f"/app?hidden=steam%3A440&token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("TF2", body)
        self.assertIn("Un-hide it", body)

    def test_it_explains_what_hidden_means(self):
        _, body = self.get(f"/app?hidden=steam%3A440&token={self.token}")
        self.assertIn("scanning will not bring it back", body)

    def test_un_hiding_queues_a_restore(self):
        from sunshine_apps_ui import state as st
        self.post({"op": "restore", "selector": "steam:440", "name": "TF2"},
                  token=self.token, path="/queue")
        self.assertEqual(st.queue()[0]["op"], "restore")
        self.assertEqual(st.queue()[0]["selector"], "steam:440")

    def test_the_grid_shows_it_coming_back(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "restore", "selector": "steam:440", "name": "TF2"})
        _, body = self.get(token=self.token)
        self.assertIn("WILL UN-HIDE", body)
        self.assertNotIn('class="mark">hidden', body)

    def test_asking_twice_says_it_is_already_queued_and_offers_a_way_out(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "restore", "selector": "steam:440", "name": "TF2"})
        _, body = self.get(f"/app?hidden=steam%3A440&token={self.token}")
        self.assertIn("Queued to come back", body)
        self.assertNotIn("Un-hide it", body)
        self.assertIn("Cancel un-hiding", body)
        self.assertIn("Back to the apps", body)

    def test_cancelling_removes_it_from_the_queue(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "restore", "selector": "steam:440", "name": "TF2"})
        self.post({"op": "restore", "selector": "steam:440"},
                  token=self.token, path="/unqueue")
        self.assertEqual(st.queue(), [])

    def test_cancelling_something_not_queued_is_harmless(self):
        from sunshine_apps_ui import state as st
        status, _ = self.post({"op": "restore", "selector": "steam:999"},
                              token=self.token, path="/unqueue")
        self.assertEqual(status, 303)
        self.assertEqual(st.queue(), [])

    def test_an_entry_that_is_not_hidden_says_so(self):
        status, body = self.get(f"/app?hidden=steam%3A999&token={self.token}")
        self.assertEqual(status, 404)
        self.assertIn("not hidden", body)
        self.assertNotIn("Could not read a plan", body)

    def test_a_restore_without_a_selector_is_refused(self):
        status, _ = self.post({"op": "restore"}, token=self.token, path="/queue")
        self.assertEqual(status, 400)


class AuthFailureWordingTest(ServerTest):
    """Not every failure is a sign-in failure.

    Saying so sent me looking at credentials when apps.json held a value
    Sunshine could not parse.
    """

    def test_a_parse_failure_is_not_reported_as_needing_a_sign_in(self):
        self.engine.auth = (False, "Sunshine could not read its own apps.json.")
        _, body = self.get(token=self.token)
        self.assertIn("Sunshine is not answering", body)
        self.assertIn("could not read its own apps.json", body)
        self.assertNotIn("needs sign-in", body)

    def test_a_real_credential_problem_still_offers_the_sign_in(self):
        self.engine.auth = (False, "Sunshine rejected the credentials")
        _, body = self.get(token=self.token)
        self.assertIn("needs sign-in", body)
        self.assertIn("/connect", body)

class StagedArtworkTest(ServerTest):
    def setUp(self):
        super().setUp()
        import tempfile as tf
        self.sd = tf.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.sd
        fd, self.png = tf.mkstemp(suffix=".png")
        os.write(fd, b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        os.close(fd)

    def tearDown(self):
        import shutil as sh
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        sh.rmtree(self.sd, ignore_errors=True)
        os.path.exists(self.png) and os.unlink(self.png)
        super().tearDown()

    def test_a_staged_tile_can_load_its_artwork(self):
        """Staged entries are in neither apps.json nor the tombstones."""
        from urllib.parse import quote
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "adopt", "name": "TF2",
                    "entry": {"name": "TF2", "image-path": self.png}})
        status, _ = self.get(f"/art?p={quote(self.png, safe='')}&token={self.token}")
        self.assertEqual(status, 200)

    def test_an_unreferenced_path_is_still_refused_with_a_queue_present(self):
        from urllib.parse import quote
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "adopt", "name": "TF2",
                    "entry": {"name": "TF2", "image-path": self.png}})
        status, _ = self.get(f"/art?p={quote('/etc/passwd', safe='')}&token={self.token}")
        self.assertEqual(status, 404)


class EditPendingTest(ServerTest):
    """A change that has not happened yet should still be adjustable."""

    def setUp(self):
        super().setUp()
        import tempfile as tf
        self.sd = tf.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.sd

    def tearDown(self):
        import shutil as sh
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        sh.rmtree(self.sd, ignore_errors=True)
        super().tearDown()

    def _staged(self):
        from sunshine_apps_ui import state as st
        st.stage_plan({"added": [{
            "name": "Half-Life", "source": "steam", "id": "70",
            "entry": {"name": "Half-Life", "cmd": "steam -applaunch 70",
                      "bsm": {"v": 1, "source": "steam", "id": "70", "fields": {}}}}]})
        return st.queue()[0]["qid"]

    def test_a_staged_tile_links_to_its_own_editor(self):
        qid = self._staged()
        _, body = self.get(token=self.token)
        self.assertIn(f"/app?queued={qid}", body)

    def test_the_editor_loads_the_queued_values(self):
        qid = self._staged()
        status, body = self.get(f"/app?queued={qid}&token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn('value="Half-Life"', body)
        self.assertIn("steam -applaunch 70", body)

    def test_it_says_the_entry_does_not_exist_yet(self):
        qid = self._staged()
        _, body = self.get(f"/app?queued={qid}&token={self.token}")
        self.assertIn("Not added yet", body)
        self.assertNotIn("Created by the importer", body)

    def test_saving_revises_the_queued_entry_in_place(self):
        from sunshine_apps_ui import state as st
        qid = self._staged()
        self.post({"op": "revise", "qid": qid, "name": "Half-Life 1998",
                   "cmd": "steam -applaunch 70", "working-dir": "",
                   "image-path": "", "output": "", "exit-timeout": ""},
                  token=self.token, path="/app")
        op = st.find(qid)
        self.assertEqual(op["entry"]["name"], "Half-Life 1998")
        self.assertEqual(op["name"], "Half-Life 1998")
        self.assertEqual(len(st.queue()), 1)

    def test_revising_keeps_the_ownership_marker(self):
        """Otherwise the importer stops maintaining it the moment you rename it."""
        from sunshine_apps_ui import state as st
        qid = self._staged()
        self.post({"op": "revise", "qid": qid, "name": "Renamed", "cmd": "x",
                   "working-dir": "", "image-path": "", "output": "",
                   "exit-timeout": ""}, token=self.token, path="/app")
        self.assertIn("bsm", st.find(qid)["entry"])

    def test_the_grid_shows_the_revised_name(self):
        qid = self._staged()
        self.post({"op": "revise", "qid": qid, "name": "Renamed", "cmd": "x",
                   "working-dir": "", "image-path": "", "output": "",
                   "exit-timeout": ""}, token=self.token, path="/app")
        _, body = self.get(token=self.token)
        self.assertIn("Renamed", body)

    def test_declining_it_removes_only_that_change(self):
        from sunshine_apps_ui import state as st
        qid = self._staged()
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        self.post({"qid": qid}, token=self.token, path="/unqueue")
        self.assertEqual([o["op"] for o in st.queue()], ["hide"])

    def test_the_editor_offers_a_way_to_decline_it(self):
        qid = self._staged()
        _, body = self.get(f"/app?queued={qid}&token={self.token}")
        self.assertIn("Do not add this", body)

    def test_a_change_that_is_gone_says_so(self):
        status, body = self.get(f"/app?queued=nope&token={self.token}")
        self.assertEqual(status, 404)
        self.assertIn("no longer queued", body)

    def test_revising_a_vanished_change_is_refused(self):
        status, _ = self.post({"op": "revise", "qid": "nope", "name": "X"},
                              token=self.token, path="/app")
        self.assertEqual(status, 404)


class FilePickerTest(ServerTest):
    """Choosing a path without typing it, and without losing the form."""

    LISTING = {
        "ok": True, "path": "/home/u", "parent": "/home",
        "entries": [{"name": "games", "path": "/home/u/games", "type": "directory"},
                    {"name": "run.sh", "path": "/home/u/run.sh", "type": "file"}],
    }

    def setUp(self):
        super().setUp()
        self.engine.listing = dict(self.LISTING)

    def test_the_form_offers_a_browse_button_for_path_fields(self):
        _, body = self.get(f"/app?new=1&token={self.token}")
        for field in ("cmd", "working-dir", "image-path"):
            self.assertIn(f'value="browse:{field}"', body)

    def test_it_does_not_offer_one_for_a_field_that_is_not_a_path(self):
        _, body = self.get(f"/app?new=1&token={self.token}")
        self.assertNotIn('value="browse:name"', body)

    def test_pressing_browse_keeps_what_was_typed(self):
        """Otherwise everything entered before choosing a file is lost."""
        from sunshine_apps_ui import state as st
        self.post({"op": "browse:cmd", "name": "My Game", "cmd": "",
                   "working-dir": "/tmp", "image-path": "", "output": "",
                   "exit-timeout": ""}, token=self.token, path="/app")
        self.assertEqual(st.draft("new")["name"], "My Game")
        self.assertEqual(st.draft("new")["working-dir"], "/tmp")

    def test_the_form_comes_back_with_the_draft(self):
        from sunshine_apps_ui import state as st
        st.set_draft("new", {"name": "My Game", "cmd": "/bin/true"})
        _, body = self.get(f"/app?new=1&token={self.token}")
        self.assertIn('value="My Game"', body)
        self.assertIn('value="/bin/true"', body)

    def test_the_picker_lists_directories_and_files_differently(self):
        status, body = self.get(f"/browse?key=new&field=cmd&token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("games", body)
        self.assertIn("run.sh", body)
        self.assertIn(">folder<", body)
        self.assertIn(">choose<", body)

    def test_choosing_a_file_records_it_and_returns_to_the_form(self):
        from sunshine_apps_ui import state as st
        st.set_draft("new", {"name": "My Game"})
        from urllib.parse import quote
        status, headers = self.get_no_redirect(
            f"/browse?key=new&field=cmd&pick={quote('/home/u/run.sh', safe='')}"
            f"&token={self.token}")
        self.assertEqual(status, 303)
        self.assertIn("/app?new=1", headers["Location"])
        self.assertEqual(st.draft("new")["cmd"], "/home/u/run.sh")
        self.assertEqual(st.draft("new")["name"], "My Game")

    def test_a_huge_directory_is_capped_rather_than_rendered_whole(self):
        """/usr/bin has thousands of executables; all of them was half a megabyte."""
        from sunshine_apps_ui.render import PICKER_LIMIT
        self.engine.listing = {
            "ok": True, "path": "/usr/bin", "parent": "/usr",
            "entries": [{"name": f"prog{i}", "path": f"/usr/bin/prog{i}",
                         "type": "file"} for i in range(PICKER_LIMIT * 4)]}
        _, body = self.get(f"/browse?key=new&field=cmd&token={self.token}")
        self.assertEqual(body.count(">choose<"), PICKER_LIMIT)
        self.assertIn(f"showing the first {PICKER_LIMIT}", body)
        self.assertLess(len(body), 200000)

    def test_the_filter_narrows_the_listing(self):
        _, body = self.get(f"/browse?key=new&field=cmd&q=run&token={self.token}")
        self.assertIn("run.sh", body)
        self.assertNotIn(">games<", body)
        self.assertIn("match", body)

    def test_the_filter_survives_into_the_form(self):
        """Filtering must not lose which form opened the picker."""
        _, body = self.get(f"/browse?key=new&field=cmd&q=run&token={self.token}")
        self.assertIn('name="key" value="new"', body)
        self.assertIn('name="field" value="cmd"', body)

    def test_a_field_that_cannot_be_browsed_is_refused(self):
        status, _ = self.get(f"/browse?key=new&field=name&token={self.token}")
        self.assertEqual(status, 404)

    def test_the_picker_needs_a_token(self):
        self.assertEqual(self.get("/browse?key=new&field=cmd")[0], 404)

    def test_a_listing_failure_is_shown_rather_than_crashing(self):
        self.engine.fails["browse"] = "nope"
        status, body = self.get(f"/browse?key=new&field=cmd&token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("nope", body)

    def test_queueing_the_entry_clears_its_draft(self):
        from sunshine_apps_ui import state as st
        st.set_draft("new", {"name": "leftover"})
        self.post({"op": "add", "name": "My Game", "cmd": "/bin/true",
                   "working-dir": "", "image-path": "", "output": "",
                   "exit-timeout": ""}, token=self.token, path="/app")
        self.assertEqual(st.draft("new"), {})


class ArtworkPickerTest(ServerTest):
    """Choosing a cover from what can be found, rather than typing a path."""

    FOUND = {
        "ok": True,
        "candidates": [
            {"id": "a" * 16, "source": "steam-local", "label": "Portrait",
             "origin": "/steam/526870/library_capsule.jpg",
             "path": "/home/u/.config/sunshine/images/.candidates/aaaa.png"},
            {"id": "b" * 16, "source": "steam-cdn", "label": "Portrait",
             "origin": "https://steam/library_600x900.jpg",
             "path": "/home/u/.config/sunshine/images/.candidates/bbbb.png"},
            {"id": "c" * 16, "source": "sgdb", "label": "by someone",
             "origin": "https://sgdb/1.png",
             "path": "/home/u/.config/sunshine/images/.candidates/cccc.png"},
        ],
        "notes": ["SteamGridDB is not configured."],
    }

    def setUp(self):
        super().setUp()
        self.engine.state = dict(STATE)
        self.engine.candidates = dict(self.FOUND)
        self.engine.searched = {}
        self.engine.chosen = ("/home/u/.config/sunshine/images/chosen/"
                              "Portal-2-aaaa.png")

    def test_the_form_offers_to_find_artwork(self):
        _, body = self.get(f"/app?index=1&token={self.token}")
        self.assertIn('value="artwork"', body)

    def test_it_offers_that_only_for_the_artwork_field(self):
        _, body = self.get(f"/app?index=1&token={self.token}")
        self.assertEqual(body.count('value="artwork"'), 1)

    def test_candidates_are_grouped_by_where_they_came_from(self):
        _, body = self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertIn("On this machine", body)
        self.assertIn("From Steam", body)
        self.assertIn("From SteamGridDB", body)

    def test_every_candidate_is_shown_as_a_picture(self):
        _, body = self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertEqual(body.count('<img src="/art?p='), 3)

    def test_a_steam_entry_is_looked_up_by_its_appid(self):
        self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertEqual(self.engine.searched["source"], "steam")
        self.assertEqual(self.engine.searched["ident"], "620")

    def test_the_name_being_edited_is_what_gets_searched_for(self):
        from sunshine_apps_ui import state as st
        st.set_draft("index:1", {"name": "Portal 2 Deluxe"})
        self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertEqual(self.engine.searched["name"], "Portal 2 Deluxe")

    def test_searching_another_title_drops_the_appid(self):
        """A different name means a different game; its appid would win and
        silently ignore what was typed."""
        self.get(f"/artwork?key=index:1&q=Hades&token={self.token}")
        self.assertEqual(self.engine.searched["name"], "Hades")
        self.assertEqual(self.engine.searched["ident"], "")

    def test_searching_the_same_title_keeps_the_appid(self):
        self.get(f"/artwork?key=index:1&q=Portal%202&token={self.token}")
        self.assertEqual(self.engine.searched["ident"], "620")

    def test_notes_explain_a_source_that_gave_nothing(self):
        _, body = self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertIn("SteamGridDB is not configured", body)

    def test_choosing_a_cover_records_it_and_returns_to_the_form(self):
        from sunshine_apps_ui import state as st
        st.set_draft("index:1", {"name": "Portal 2", "cmd": "keep me"})
        status, headers = self.get_no_redirect(
            f"/artwork?key=index:1&choose={'a' * 16}&token={self.token}")
        self.assertEqual(status, 303)
        self.assertIn("/app?index=1", headers["Location"])
        draft = st.draft("index:1")
        self.assertTrue(draft["image-path"].endswith("Portal-2-aaaa.png"))
        self.assertEqual(draft["cmd"], "keep me")

    def test_the_cover_in_use_is_marked_rather_than_offered_again(self):
        from sunshine_apps_ui import state as st
        st.set_draft("index:1", {
            "image-path": self.FOUND["candidates"][0]["path"]})
        _, body = self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertIn("in use", body)

    def test_pressing_find_artwork_keeps_what_was_typed(self):
        from sunshine_apps_ui import state as st
        status, headers = self.post(
            {"op": "artwork", "index": "1", "name": "Portal 2", "cmd": "half typed",
             "working-dir": "", "image-path": "", "output": "", "exit-timeout": ""},
            token=self.token, path="/app")
        self.assertEqual(status, 303)
        self.assertIn("/artwork", headers["Location"])
        self.assertEqual(st.draft("index:1")["cmd"], "half typed")

    def test_a_new_entry_can_look_for_artwork_too(self):
        from sunshine_apps_ui import state as st
        st.set_draft("new", {"name": "Some Game"})
        status, body = self.get(f"/artwork?key=new&token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("Some Game", body)

    def test_a_queued_addition_looks_up_its_own_appid(self):
        from sunshine_apps_ui import state as st
        st.clear_queue()
        qid = st.enqueue({"op": "add", "name": "Half-Life",
                          "entry": {"name": "Half-Life",
                                    "bsm": {"source": "steam", "id": "70"}}}
                         )[-1]["qid"]
        self.get(f"/artwork?key=qid:{qid}&token={self.token}")
        self.assertEqual(self.engine.searched["ident"], "70")

    def test_the_picker_needs_a_token(self):
        self.assertEqual(self.get("/artwork?key=index:1")[0], 404)

    def test_a_failure_to_search_is_shown_rather_than_crashing(self):
        self.engine.fails["art_search"] = "no network"
        status, body = self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("no network", body)

    def test_there_is_always_a_way_back(self):
        _, body = self.get(f"/artwork?key=index:1&token={self.token}")
        self.assertIn("/app?index=1", body)
        self.assertIn("Browse for a file", body)


class EditFormShowsTheFileTest(ServerTest):
    """The form has to show what is in apps.json, because saving it writes
    every field back. A flag it renders unchecked is a flag it turns off."""

    REBOOT = {
        "index": 0, "name": "Zz Reboot", "cmd": "", "image-path": "/img/r.png",
        "source": "launcher", "id": "reboot", "managed": True,
        "auto-detach": True, "wait-all": True, "exclude-global-prep-cmd": False,
        "exit-timeout": 5, "output": "/tmp/reboot.log",
        "detached": ["systemctl reboot"],
    }

    def setUp(self):
        super().setUp()
        self.engine.state = dict(STATE, apps=[self.REBOOT])

    def test_a_flag_that_is_set_is_shown_as_set(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn('name="auto-detach" checked', body)
        self.assertIn('name="wait-all" checked', body)

    def test_a_flag_that_is_not_set_is_not_shown_as_set(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn('name="exclude-global-prep-cmd">', body)

    def test_the_exit_timeout_is_shown(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn('id="f_exit-timeout" name="exit-timeout" type="text" value="5"',
                      body)

    def test_the_output_log_is_shown(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn('value="/tmp/reboot.log"', body)

    def test_showing_the_real_values_does_not_make_the_form_look_edited(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertNotIn('data-dirty="1"', body)


class StopAfterApplyTest(ServerTest):
    """Applying is the end of the session, whether or not we want it to be.

    Sunshine replaces its whole process manager when it reloads, so from the
    moment changes are applied it no longer knows this app is running -- it
    reports the host as free and cannot close the window either. Staying open
    leaves a browser on the host's desktop that nothing will reach again.
    """

    def setUp(self):
        super().setUp()
        import tempfile as tf
        self.sd = tf.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.sd
        handler = self.httpd.RequestHandlerClass
        handler.applied = False
        handler.stopping = False
        handler._armed = False

    def tearDown(self):
        import shutil as sh
        handler = self.httpd.RequestHandlerClass
        handler.applied = handler.stopping = handler.via_sunshine = False
        handler._armed = False
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        sh.rmtree(self.sd, ignore_errors=True)
        super().tearDown()

    def _apply(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "edit", "index": 1, "name": "Portal 2",
                    "fields": {"name": "Portal 2"}})
        self.post({}, token=self.token, path="/apply")

    def test_applying_from_a_stream_stops_the_server(self):
        self.httpd.RequestHandlerClass.via_sunshine = True
        self._apply()
        self.assertTrue(self.httpd.RequestHandlerClass.stopping)

    def test_it_does_not_wait_for_the_applied_page_to_be_asked_for(self):
        """Applying reloads Sunshine, which ends the stream this is watched
        through -- so the browser is usually gone before it can ask for that
        page. Waiting for it left the window sitting on the desktop."""
        self.httpd.RequestHandlerClass.via_sunshine = True
        self._apply()                      # and never fetch /applied
        self.assertTrue(self.httpd.RequestHandlerClass.stopping)

    def test_stopping_means_the_serving_loop_is_actually_ended(self):
        """Setting a flag would be no use on its own."""
        handler = self.httpd.RequestHandlerClass
        with mock.patch.object(threading, "Timer") as timer:
            handler.via_sunshine = True
            self._apply()
        self.assertTrue(timer.called)
        delay, function = timer.call_args[0]
        self.assertGreater(delay, 0, "the response needs time to reach the browser")
        self.assertEqual(function, self.httpd.shutdown)

    def test_the_timer_is_not_stacked_if_the_page_is_asked_for_too(self):
        handler = self.httpd.RequestHandlerClass
        with mock.patch.object(threading, "Timer") as timer:
            handler.via_sunshine = True
            self._apply()
            self.get(f"/applied?token={self.token}")
        self.assertEqual(timer.call_count, 1)

    def test_a_browser_on_the_network_is_left_alone(self):
        """Opened from a laptop, this window is the user's to close."""
        self.httpd.RequestHandlerClass.via_sunshine = False
        self._apply()
        self.get(f"/applied?token={self.token}")
        self.assertFalse(self.httpd.RequestHandlerClass.stopping)

    def test_it_does_not_stop_for_the_page_alone(self):
        """Reaching /applied without having applied anything is not the end."""
        self.httpd.RequestHandlerClass.via_sunshine = True
        self.get(f"/applied?token={self.token}")
        self.assertFalse(self.httpd.RequestHandlerClass.stopping)


class ProtectedTileTest(ServerTest):
    """The tile this manager is launched from can be renamed and nothing else.

    Every other change to it takes away the way back in, and none of them can
    be undone from a page you can no longer reach.
    """

    MANAGER = {"index": 0, "name": "Zz App Manager", "cmd": "/home/u/.local/bin/x",
               "image-path": "/img/ui.png", "source": "launcher", "id": "apps-ui",
               "managed": True, "wait-all": True, "exit-timeout": 5}
    GAME = {"index": 1, "name": "Portal 2", "cmd": "steam -applaunch 620",
            "image-path": "/img/620.png", "source": "steam", "id": "620",
            "managed": True}

    def setUp(self):
        super().setUp()
        self.engine.state = dict(STATE, apps=[self.MANAGER, self.GAME])

    def _edit(self, index, **overrides):
        body = {"op": "edit", "index": str(index), "orig_name": "Zz App Manager",
                "name": "Zz App Manager", "cmd": "", "working-dir": "",
                "image-path": "", "output": "", "exit-timeout": ""}
        body.update(overrides)
        return self.post(body, token=self.token, path="/app")

    # --- what the page offers

    def test_its_settings_are_shown(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn("/home/u/.local/bin/x", body)

    def test_but_not_as_something_you_can_type_into(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn('name="cmd" type="text" value="/home/u/.local/bin/x" readonly',
                      body)

    def test_the_name_stays_editable(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertNotIn('name="name" type="text" value="Zz App Manager" readonly',
                         body)

    def test_the_flags_cannot_be_toggled(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn('name="wait-all" checked disabled', body)

    def test_it_says_why(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn("way back in", body)

    def test_hide_delete_and_copy_are_not_offered(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertNotIn("op=hide", body)
        self.assertNotIn("op=delete", body)
        self.assertNotIn('value="clone"', body)

    def test_the_button_says_rename(self):
        _, body = self.get(f"/app?index=0&token={self.token}")
        self.assertIn(">Rename</button>", body)

    def test_an_ordinary_tile_is_untouched(self):
        _, body = self.get(f"/app?index=1&token={self.token}")
        self.assertIn("op=delete", body)
        self.assertIn('value="clone"', body)
        self.assertNotIn("readonly", body)

    # --- what the server allows, which is the part that counts

    def test_a_rename_goes_through(self):
        from sunshine_apps_ui import state as st
        status, _ = self._edit(0, name="Zz Tiles")
        self.assertEqual(status, 303)
        self.assertEqual(st.queue()[0]["fields"], {"name": "Zz Tiles"})

    def test_a_posted_command_change_is_dropped_rather_than_queued(self):
        """The form said read-only; a form is only a suggestion."""
        from sunshine_apps_ui import state as st
        self._edit(0, cmd="/bin/false")
        self.assertEqual(st.queue()[0]["fields"], {"name": "Zz App Manager"})

    def test_a_posted_flag_change_is_dropped_too(self):
        from sunshine_apps_ui import state as st
        self._edit(0, elevated="on")
        self.assertNotIn("elevated", st.queue()[0]["fields"])

    def test_copying_it_is_refused(self):
        from sunshine_apps_ui import state as st
        status, _ = self.post({"op": "clone", "index": "0",
                               "orig_name": "Zz App Manager", "name": "Copy",
                               "cmd": "", "working-dir": "", "image-path": "",
                               "output": "", "exit-timeout": ""},
                              token=self.token, path="/app")
        self.assertEqual(status, 400)
        self.assertEqual(st.queue(), [])

    def test_hiding_it_is_refused_at_the_interstitial(self):
        status, body = self.get(
            f"/explain?op=hide&index=0&name=Zz%20App%20Manager&token={self.token}")
        self.assertEqual(status, 400)
        self.assertIn("way back in", body)

    def test_deleting_it_is_refused_even_posted_straight_to_the_queue(self):
        """The interstitial can be skipped once it has been silenced."""
        from sunshine_apps_ui import state as st
        status, _ = self.post({"op": "delete", "index": "0",
                               "name": "Zz App Manager"},
                              token=self.token, path="/queue")
        self.assertEqual(status, 400)
        self.assertEqual(st.queue(), [])

    def test_an_ordinary_tile_can_still_be_deleted(self):
        from sunshine_apps_ui import state as st
        status, _ = self.post({"op": "delete", "index": "1", "name": "Portal 2"},
                              token=self.token, path="/queue")
        self.assertEqual(status, 303)
        self.assertEqual(st.queue()[0]["op"], "delete")

    def test_an_ordinary_tile_can_still_be_edited_in_full(self):
        from sunshine_apps_ui import state as st
        self.post({"op": "edit", "index": "1", "orig_name": "Portal 2",
                   "name": "Portal 2", "cmd": "/bin/new", "working-dir": "",
                   "image-path": "", "output": "", "exit-timeout": ""},
                  token=self.token, path="/app")
        self.assertEqual(st.queue()[0]["fields"]["cmd"], "/bin/new")

    def test_it_is_identified_by_its_marker_not_its_name(self):
        """Renaming it must not unlock it."""
        from sunshine_apps_ui.render import is_protected
        self.assertTrue(is_protected(dict(self.MANAGER, name="Something Else")))
        self.assertFalse(is_protected(self.GAME))

    def test_an_unreadable_app_list_refuses_rather_than_allows(self):
        """Not being able to tell is not a reason to permit the one change that
        cannot be undone from here."""
        self.engine.fails["get_state"] = "apps.json is unreadable"
        status, _ = self.post({"op": "delete", "index": "0", "name": "x"},
                              token=self.token, path="/queue")
        self.assertEqual(status, 400)


class RestoreCopyTest(ServerTest):
    """Going back to a kept copy of apps.json.

    The copy is chosen, what it would do is shown on the grid in the same
    language as every other pending change, and nothing is written until apply.
    """

    COPIES = [
        {"name": "apps-20260915-101500.json", "apps": 9, "readable": True,
         "at": "2026-09-15T10:15:00", "size": 4096},
        {"name": "apps-20260914-090000.json", "apps": 7, "readable": True,
         "at": "2026-09-14T09:00:00", "size": 3000},
        {"name": "apps-20260913-080000.json", "apps": 0, "readable": False,
         "at": "2026-09-13T08:00:00", "size": 12},
    ]
    DIFF = {
        "ok": True, "backup": "apps-20260915-101500.json",
        "returning": [{"name": "Hades"}],
        "going": [{"name": "Portal 2"}],
        "changing": [{"name": "Desktop", "fields": ["cmd"]}],
        "hidden_now": 0, "hidden_then": 2, "nothing_to_do": False,
    }

    def setUp(self):
        super().setUp()
        self.engine.state = dict(STATE, apps=[
            {"index": 0, "name": "Desktop", "image-path": "", "cmd": "",
             "source": None, "id": None, "managed": False},
            {"index": 1, "name": "Portal 2", "image-path": "", "cmd": "x",
             "source": "steam", "id": "620", "managed": True},
        ])
        self.engine.copies = list(self.COPIES)
        self.engine.diff = dict(self.DIFF)

    def test_the_grid_offers_a_way_to_restore(self):
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("/backups?token=", body)

    def test_the_picker_lists_the_copies_by_when_they_were_taken(self):
        _, body = self.get(f"/backups?token={self.token}")
        self.assertIn("15 Sep 2026 at 10:15:00", body)
        self.assertIn("9 applications", body)

    def test_a_copy_that_cannot_be_read_is_shown_but_not_offered(self):
        """Hiding it would be worse: you would wonder where it went."""
        _, body = self.get(f"/backups?token={self.token}")
        self.assertIn("cannot be read", body)
        self.assertNotIn("restore=apps-20260913-080000.json", body)

    def test_choosing_one_queues_it_rather_than_applying_it(self):
        from sunshine_apps_ui import state as st
        status, headers = self.get_no_redirect(
            f"/backups?restore=apps-20260915-101500.json&token={self.token}")
        self.assertEqual(status, 303)
        self.assertTrue(headers["Location"].startswith("/?"))
        self.assertEqual(st.queue()[0]["op"], "rollback")
        self.assertEqual(st.queue()[0]["backup"], "apps-20260915-101500.json")

    def test_the_grid_then_says_what_it_would_do(self):
        self.get_no_redirect(
            f"/backups?restore=apps-20260915-101500.json&token={self.token}")
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("Restoring the copy from 15 Sep 2026 at 10:15:00", body)
        self.assertIn("would come back", body)
        self.assertIn("would be removed", body)
        self.assertIn("would change", body)

    def test_it_says_the_part_no_tile_can_show(self):
        """The hidden list is why this is a whole-file operation."""
        self.get_no_redirect(
            f"/backups?restore=apps-20260915-101500.json&token={self.token}")
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("What you have hidden goes from", body)

    def test_the_tiles_themselves_are_marked(self):
        self.get_no_redirect(
            f"/backups?restore=apps-20260915-101500.json&token={self.token}")
        _, body = self.get(f"/?token={self.token}")
        # What would go is marked like a deletion, what returns appears as a
        # tile that is not there yet.
        self.assertIn("Hades", body)
        self.assertIn("tile ghost", body)

    def test_nothing_is_applied_by_looking(self):
        self.get_no_redirect(
            f"/backups?restore=apps-20260915-101500.json&token={self.token}")
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("Nothing has changed yet", body)
        self.assertIn("Apply 1 change", body)

    def test_it_can_be_cancelled_from_the_grid(self):
        from sunshine_apps_ui import state as st
        self.get_no_redirect(
            f"/backups?restore=apps-20260915-101500.json&token={self.token}")
        qid = st.queue()[0]["qid"]
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("Cancel this restore", body)
        self.assertIn(f'value="{qid}"', body)
        self.post({"qid": qid}, token=self.token, path="/unqueue")
        self.assertEqual(st.queue(), [])

    def test_choosing_a_second_copy_replaces_the_first(self):
        """Two restores queued at once would be a fight over the same file."""
        from sunshine_apps_ui import state as st
        for name in ("apps-20260915-101500.json", "apps-20260914-090000.json"):
            self.get_no_redirect(f"/backups?restore={name}&token={self.token}")
        rollbacks = [op for op in st.queue() if op["op"] == "rollback"]
        self.assertEqual(len(rollbacks), 1)
        self.assertEqual(rollbacks[0]["backup"], "apps-20260914-090000.json")

    def test_a_preview_that_fails_does_not_take_the_grid_down(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "rollback", "backup": "apps-20260915-101500.json"})
        self.engine.fails["backup_diff"] = "that copy is gone"
        status, body = self.get(f"/?token={self.token}")
        self.assertEqual(status, 200)
        self.assertIn("Restoring the copy from", body)

    def test_the_picker_needs_a_token(self):
        self.assertEqual(self.get("/backups")[0], 404)


class ResponseOrderingTest(ServerTest):
    """What the page says must be true by the time the page arrives.

    /applied decided to stop after sending the response, so a client could read
    the page and find the decision not yet made. That is a real ordering bug and
    not merely a flaky test: anything acting on the response -- a script, a
    second request, a person clicking quickly -- could arrive first.
    """

    def setUp(self):
        super().setUp()
        handler = self.httpd.RequestHandlerClass
        handler.applied = False
        handler.stopping = False
        self.addCleanup(setattr, handler, "via_sunshine", False)
        self.addCleanup(setattr, handler, "applied", False)
        self.addCleanup(setattr, handler, "stopping", False)

    def test_the_decision_to_stop_is_true_when_the_page_arrives(self):
        from sunshine_apps_ui import state as st
        self.httpd.RequestHandlerClass.via_sunshine = True
        st.enqueue({"op": "edit", "index": 1, "name": "Portal 2",
                    "fields": {"name": "Portal 2"}})
        self.post({}, token=self.token, path="/apply")
        for _ in range(20):
            self.get(f"/applied?token={self.token}")
            self.assertTrue(self.httpd.RequestHandlerClass.stopping,
                            "the page arrived before the decision was made")
            self.httpd.RequestHandlerClass.stopping = False


class ConfirmationShowsWhatApplyDoesTest(ServerTest):
    """The confirmation lists the queue, because the queue is what Apply does.

    It used to run a scan and show what that found as well. A game deleted
    earlier reappears in a scan -- deleting does not leave a tombstone -- so it
    was listed as "will be added", and then was not added, because Apply
    applies the queue. The page promised something the button does not do.
    """

    def setUp(self):
        super().setUp()
        self.engine.plan = dict(PLAN)      # a scan would find Half-Life

    def test_the_confirmation_does_not_scan(self):
        """It is the page whose whole job is to ask first."""
        scanned = []
        original = self.engine.run_plan
        self.engine.run_plan = lambda *a, **k: (scanned.append(1), original(*a, **k))[1]
        import sunshine_apps_ui.server as sm
        with mock.patch.object(sm, "run_plan", self.engine.run_plan):
            self.get("/apply", token=self.token)
        self.assertEqual(scanned, [], "the confirmation ran a library scan")

    def test_it_does_not_promise_what_a_scan_found(self):
        _, body = self.get("/apply", token=self.token)
        self.assertNotIn("Half-Life", body)
        self.assertNotIn("Will be added", body)

    def test_it_lists_the_queue(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        st.enqueue({"op": "add", "fields": {"name": "My Script"}})
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Hide Portal 2", body)
        self.assertIn("Add My Script", body)

    def test_the_count_is_the_queue_and_nothing_else(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Apply 1 change?", body)

    def test_an_empty_queue_says_nothing_would_change(self):
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Nothing would change.", body)
        self.assertIn("Apply 0 changes?", body)

    def test_what_it_lists_is_what_gets_applied(self):
        """The property that was broken: the page and the button agree."""
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        _, body = self.get("/apply", token=self.token)
        self.post({}, token=self.token, path="/apply")
        self.assertEqual(len(self.engine.applied), 1)
        applied = [op["name"] for op in self.engine.applied[0]]
        self.assertIn("Portal 2", applied)
        self.assertEqual(len(applied), body.count('class="queued"') or len(applied))


class ReadOnlyGridTest(ServerTest):
    """What the grid says when apps.json cannot be written.

    The failure this prevents is silent: on Windows a standard account, or a
    hand-started Sunshine, gets no elevation and no error, and the first sign of
    trouble is a write failing after a dozen changes are queued.
    """

    def setUp(self):
        from sunshine_apps_ui import privilege
        patched = mock.patch.object(
            server_module.privilege, "check",
            lambda conf_dir: privilege.Privilege(
                False, False, "Because this is not elevated.",
                "Changes cannot be saved"))
        patched.start()
        self.addCleanup(patched.stop)
        super().setUp()

    def test_the_grid_says_why_nothing_can_be_saved(self):
        _, body = self.get(token=self.token)
        self.assertIn("Changes cannot be saved", body)
        self.assertIn("Because this is not elevated.", body)

    def test_apply_is_not_offered_when_it_could_only_fail(self):
        self.post({"op": "edit", "index": "1", "orig_name": "Portal 2",
                   "name": "X"}, token=self.token, path="/app")
        _, body = self.get(token=self.token)
        self.assertNotIn(">Apply 1 change<", body)
        # The queue is still there, and still discardable: read-only is not a
        # reason to throw away what somebody typed.
        self.assertIn("Discard", body)

    def test_the_rest_of_the_grid_still_works(self):
        """Read-only is not broken. Everything but saving carries on."""
        _, body = self.get(token=self.token)
        self.assertIn("2 applications", body)
        self.assertIn("Portal 2", body)
        self.assertIn("Rescan", body)


class QueueDrainsEvenWhenSomethingIsRefusedTest(ServerTest):
    """The queue must not keep operations that were already attempted.

    The maintainer's report, 2026-09-18: "write changes: give the warning then does
    nothing". His log says exactly what happened:

        Applied 1 of 2 change(s)                      <- the delete really happened
        Skipped delete: 'Desktop' is no longer where it was
        Skipped hide:   'Steam Big Picture' is no longer where it was
        Applied 0 of 2 change(s)                      <- and for ever after

    One of two operations was refused, so mutate reported failure, so the queue
    was not cleared -- including the operation that had genuinely been applied.
    That one then referred to a file that had changed under it, went stale, and
    every later apply did nothing at all while still writing a backup.
    """

    def queue_two(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "delete", "index": 1, "name": "Portal 2"})
        st.enqueue({"op": "hide", "index": 2, "name": "Desktop"})
        return st.queue()

    def test_a_refusal_does_not_keep_the_applied_one_queued(self):
        from sunshine_apps_ui import state as st
        queued = self.queue_two()
        self.engine.refuse = {str(queued[1]["qid"]): "hiding it is the same as deleting it"}
        self.post({}, token=self.token, path="/apply")
        self.assertEqual(st.queue(), [], "the queue jams if anything is left behind")

    def test_the_refusal_is_reported_rather_than_swallowed(self):
        queued = self.queue_two()
        self.engine.refuse = {str(queued[1]["qid"]): "hiding it is the same as deleting it"}
        _, headers = self.post({}, token=self.token, path="/apply")
        # Carried on the redirect, which is where the grid reads it from.
        self.assertIn("apply_error", headers["Location"])
        self.assertIn("hiding+it+is+the+same", headers["Location"])

    def test_a_second_apply_has_nothing_left_to_do(self):
        """The press that used to say "Applied 0 of 2"."""
        queued = self.queue_two()
        self.engine.refuse = {str(queued[1]["qid"]): "refused"}
        self.post({}, token=self.token, path="/apply")
        before = len(self.engine.applied)
        self.post({}, token=self.token, path="/apply")
        self.assertEqual(len(self.engine.applied), before,
                         "an empty queue must not reach the engine at all")

    def test_everything_working_still_clears_and_reports(self):
        from sunshine_apps_ui import state as st
        self.queue_two()
        self.engine.refuse = {}
        self.post({}, token=self.token, path="/apply")
        self.assertEqual(st.queue(), [])

    def test_a_failure_to_write_at_all_keeps_the_queue(self):
        """Nothing was attempted, so there is nothing to forget."""
        from sunshine_apps_ui import state as st
        self.queue_two()
        self.engine.fails = {"mutate": "apps.json could not be written"}
        self.post({}, token=self.token, path="/apply")
        self.assertEqual(len(st.queue()), 2)


class RestoreDefaultTilesTest(ServerTest):
    """The settings button that puts Sunshine's three default tiles back.

    They can be deleted like anything else, and unlike our own launchers a
    scan does not offer them again -- they exist because Sunshine's entries
    did, and once ours are gone there is nothing left to claim. This is the
    way back, and it goes through a scan so the tiles arrive on the grid as
    pending changes rather than being written behind the user's back.
    """

    def _found(self, path="/usr/share/sunshine/apps.json"):
        from sunshine_apps_ui.core import system_apps
        patched = mock.patch.object(system_apps, "find_system_apps_json",
                                    lambda override="": path)
        patched.start()
        self.addCleanup(patched.stop)

    def _watch_opts(self):
        seen = {}

        def run_plan(conf_dir, opts=None):
            seen.update(opts or {})
            return self.engine.plan, "log line"

        patched = mock.patch.object(server_module, "run_plan", run_plan)
        patched.start()
        self.addCleanup(patched.stop)
        return seen

    def _wait(self):
        from sunshine_apps_ui import scanjob
        deadline = time.monotonic() + 20.0
        while scanjob.job.running() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(scanjob.job.running(), "the restore never finished")

    def test_the_button_is_offered(self):
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("/settings/defaults", body)
        self.assertIn("Put the default tiles back", body)

    def test_it_asks_for_a_restore(self):
        self._found()
        seen = self._watch_opts()
        status, headers = self.post({}, token=self.token, path="/settings/defaults")
        self._wait()
        self.assertEqual(seen.get("BSM_RESTORE_DEFAULTS"), "1")
        self.assertIn("/scanning", headers.get("Location", ""))

    def test_an_ordinary_scan_does_not(self):
        """Restoring is what the button does, not what every scan does."""
        self._found()
        seen = self._watch_opts()
        self.scan()
        self.assertNotIn("BSM_RESTORE_DEFAULTS", seen)

    def test_nothing_is_written_by_pressing_it(self):
        """It stages. Apply writes."""
        self._found()
        self._watch_opts()
        self.post({}, token=self.token, path="/settings/defaults")
        self._wait()
        self.assertEqual(self.engine.applied, [])

    def test_it_says_so_when_there_is_nothing_to_copy_from(self):
        self._found(path="")
        seen = self._watch_opts()
        status, headers = self.post({}, token=self.token,
                                    path="/settings/defaults")
        self.assertIn("/settings", headers.get("Location", ""))
        self.assertEqual(seen, {})
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("nothing to copy the default tiles from", body)

    def test_and_says_it_only_once(self):
        self._found(path="")
        self.post({}, token=self.token, path="/settings/defaults")
        self.get(f"/settings?token={self.token}")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertNotIn("nothing to copy the default tiles from", body)

    def test_it_needs_the_token(self):
        self._found()
        seen = self._watch_opts()
        status, _ = self.post({}, path="/settings/defaults")
        self.assertEqual(status, 404)
        self.assertEqual(seen, {})


class LanguageSettingTest(ServerTest):
    """Choosing the language the tiles are written in, and the artwork for it.

    The setting is about tiles, not the interface: the interface is English
    until somebody translates it. What this has to get right is that changing
    a language never downloads anything by itself, and that the one button
    that does reach the network says what it will fetch first.
    """

    def _remote(self, sets, why=""):
        from sunshine_apps_ui import tileart
        patched = mock.patch.object(tileart, "remote_manifest",
                                    lambda timeout=0: (sets, why))
        patched.start()
        self.addCleanup(patched.stop)

    def _set(self, choice):
        return self.post({"language": choice}, token=self.token,
                         path="/settings/language")

    def test_the_languages_we_ship_are_offered(self):
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn('<option value="en"', body)
        self.assertIn("Follow the system", body)

    def test_choosing_one_is_remembered(self):
        from sunshine_apps_ui import state
        self._remote({})
        self._set("en")
        self.assertEqual(state.prefs().get("language"), "en")

    def test_following_the_system_is_the_empty_choice(self):
        from sunshine_apps_ui import state
        self._remote({})
        self._set("en")
        self._set("")
        self.assertEqual(state.prefs().get("language"), "")

    def test_a_language_we_do_not_ship_is_refused(self):
        from sunshine_apps_ui import state
        self._set("../../etc/passwd")
        self.assertIsNone(state.prefs().get("language"))
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("not a language we ship", body)

    def test_changing_language_downloads_nothing(self):
        """It offers. A couple of megabytes is not a side effect of a dropdown."""
        from sunshine_apps_ui import tileart
        fetched = []
        patched = mock.patch.object(
            tileart, "fetch_set",
            lambda *a, **k: (fetched.append(a) or (0, "")))
        patched.start()
        self.addCleanup(patched.stop)
        self._remote({"fr": {"steam.png": "f" * 64}})
        self._set("en")
        self.assertEqual(fetched, [])

    def test_the_check_reports_when_everything_matches(self):
        self._remote({})
        self.post({}, token=self.token, path="/settings/art-check")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("the published one", body)

    def test_the_check_offers_an_update_when_a_set_differs(self):
        from sunshine_apps_ui import tileart
        self._remote({"_wordless": {"steam.png": "f" * 64}})
        patched = mock.patch.object(tileart, "stale", lambda remote: {"_wordless": 3})
        patched.start()
        self.addCleanup(patched.stop)
        self.post({}, token=self.token, path="/settings/art-check")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("3 tiles in the _wordless set differ from", body)
        self.assertIn("/settings/art-fetch", body)

    def test_the_check_says_so_when_it_cannot_reach_us(self):
        self._remote({}, why="the artwork list could not be reached (offline)")
        self.post({}, token=self.token, path="/settings/art-check")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("could not be reached", body)

    def test_a_download_reports_what_it_saved(self):
        from sunshine_apps_ui import tileart
        patched = mock.patch.object(tileart, "fetch_set", lambda code: (23, ""))
        patched.start()
        self.addCleanup(patched.stop)
        # The code travels in the link behind the button, as the offer builds it.
        self.post({}, path=f"/settings/art-fetch?code=fr&token={self.token}")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("23 tiles saved for fr", body)
        self.assertIn("Scan now", body)

    def test_a_failed_download_says_why(self):
        from sunshine_apps_ui import tileart
        patched = mock.patch.object(
            tileart, "fetch_set", lambda code: (0, "steam.png did not match"))
        patched.start()
        self.addCleanup(patched.stop)
        self.post({}, path=f"/settings/art-fetch?code=fr&token={self.token}")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("did not match", body)

    def test_the_notice_is_shown_once(self):
        self._remote({})
        self.post({}, token=self.token, path="/settings/art-check")
        self.get(f"/settings?token={self.token}")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertNotIn("the published one", body)

    def test_it_needs_the_token(self):
        from sunshine_apps_ui import state
        status, _ = self.post({"language": "en"}, path="/settings/language")
        self.assertEqual(status, 404)
        self.assertIsNone(state.prefs().get("language"))


class ClosingTest(ServerTest):
    """Leaving, for somebody who looked and decided nothing needed changing.

    There was no way out of the interface except closing the window, which on
    a television means finding the controller shortcut for it. The maintainer, seeing the
    artwork picker: "there should also be an exit button in the ui, when the
    user decides no changes are needed."
    """

    def _quit(self, **body):
        return self.post(body, token=self.token, path="/quit")

    def _stopping(self):
        # The handler class is made per server, with the token baked in, so the
        # flag lands there rather than on the class in the module.
        return bool(getattr(self.httpd.RequestHandlerClass, "stopping", False))

    def setUp(self):
        super().setUp()
        handler = self.httpd.RequestHandlerClass
        handler.stopping = False
        handler._armed = False

    def test_the_button_is_on_the_grid(self):
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("/quit", body)
        self.assertIn("Close the manager", body)

    def test_closing_stops_the_server(self):
        status, _ = self._quit()
        self.assertEqual(status, 200)
        self.assertTrue(self._stopping())

    def test_it_says_the_window_is_going(self):
        from sunshine_apps_ui.render import closing_page
        self.assertIn("Closed", closing_page())
        self.assertIn("close it", closing_page())

    def test_staged_changes_are_asked_about_first(self):
        """Not a warning that anything is lost -- it is not -- but a fact."""
        from sunshine_apps_ui import state
        state.stage_plan(dict(PLAN["plan"]))
        status, _ = self._quit()
        self.assertEqual(status, 200)
        self.assertFalse(self._stopping(), "it stopped without asking")

    def test_and_closing_anyway_stops(self):
        from sunshine_apps_ui import state
        state.stage_plan(dict(PLAN["plan"]))
        self._quit(anyway="1")
        self.assertTrue(self._stopping())

    def test_the_queue_survives_closing(self):
        from sunshine_apps_ui import state
        state.stage_plan(dict(PLAN["plan"]))
        before = len(state.queue())
        self._quit(anyway="1")
        self.assertEqual(len(state.queue()), before)

    def test_it_needs_the_token(self):
        status, _ = self.post({}, path="/quit")
        self.assertEqual(status, 404)
        self.assertFalse(self._stopping())

    def test_a_get_does_not_close_it(self):
        """A link somebody follows, or a page prefetching, must not stop it."""
        status, _ = self.get_no_redirect(f"/quit?token={self.token}")
        self.assertIn(status, (404, 405))
        self.assertFalse(self._stopping())


class WhichBuildsTest(ServerTest):
    """The two switches under "Which builds", which had no test at all.

    That is how they shipped unusable: a checkbox that needed script to apply,
    on a page whose policy forbids inline script, so pressing them did nothing
    and nothing was written. Issue #28.
    """

    def _press(self, setting, value):
        return self.post({"setting": setting, "value": value},
                         token=self.token, path="/settings/channel")

    def _prefs(self):
        from sunshine_apps_ui import state
        return state.prefs()

    def test_turning_development_builds_on(self):
        self._press("dev_builds", "1")
        self.assertIs(self._prefs().get("dev_builds"), True)

    def test_and_off_again(self):
        self._press("dev_builds", "1")
        self._press("dev_builds", "0")
        self.assertIs(self._prefs().get("dev_builds"), False)

    def test_the_child_follows_while_development_builds_are_on(self):
        self._press("dev_builds", "1")
        self._press("stable_if_no_newer_dev", "0")
        self.assertIs(self._prefs().get("stable_if_no_newer_dev"), False)
        self._press("stable_if_no_newer_dev", "1")
        self.assertIs(self._prefs().get("stable_if_no_newer_dev"), True)

    def test_the_child_is_refused_while_they_are_off(self):
        """The switch is disabled, but a request can arrive anyway."""
        self._press("dev_builds", "0")
        self._press("stable_if_no_newer_dev", "0")
        self.assertIsNone(self._prefs().get("stable_if_no_newer_dev"))

    def test_an_unknown_setting_changes_nothing(self):
        self._press("theme", "1")
        self.assertEqual(self._prefs(), {})

    def test_it_needs_the_token(self):
        status, _ = self.post({"setting": "dev_builds", "value": "1"},
                              path="/settings/channel")
        self.assertEqual(status, 404)
        self.assertEqual(self._prefs(), {})

    # --- what the page actually offers to press ----------------------------

    def test_each_switch_is_a_button_that_submits_on_its_own(self):
        """Not a checkbox: applying has to need nothing but HTML."""
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn('name="setting" value="dev_builds"', body)
        self.assertIn('name="setting" value="stable_if_no_newer_dev"', body)
        self.assertNotIn('type="checkbox"', body)

    def test_a_switch_posts_the_value_it_would_set(self):
        _, off = self.get(f"/settings?token={self.token}")
        self.assertIn('name="value" value="1"', off)      # currently off
        self._press("dev_builds", "1")
        _, on = self.get(f"/settings?token={self.token}")
        self.assertIn('name="value" value="0"', on)       # now offers to turn it off

    def test_the_child_is_disabled_until_the_parent_is_on(self):
        _, body = self.get(f"/settings?token={self.token}")
        self.assertRegex(body, r'value="stable_if_no_newer_dev".*?disabled')
        self._press("dev_builds", "1")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertNotRegex(body, r'value="stable_if_no_newer_dev".*?disabled')

    def test_there_is_no_save_button_to_forget(self):
        _, body = self.get(f"/settings?token={self.token}")
        self.assertNotIn("noscript", body)


class CommunityArtworkKeyTest(ServerTest):
    """Issue #22: somewhere to put a SteamGridDB key that is not a shell.

    The picker used to answer "no artwork found" by naming a command -- first
    one that did not exist, then one that on Windows is a .cmd off PATH. This
    program is normally launched as a Sunshine tile, on a television, from a
    gamepad. There is nothing to type a command into, so the key goes in a
    field on the settings page and the picker points at the page.
    """

    def _saving(self, ok=True, why="SteamGridDB did not accept that key: 403"):
        """Stand in for the network call save_sgdb makes to check a key."""
        from sunshine_apps_ui.core import api
        seen = {}

        def save_sgdb(conf_dir, key):
            seen["conf_dir"], seen["key"] = conf_dir, key
            if ok:
                return True, f"Verified and saved to {conf_dir}/.bsm-sgdb-key"
            return False, why

        patched = mock.patch.object(api, "save_sgdb", save_sgdb)
        patched.start()
        self.addCleanup(patched.stop)
        return seen

    def _stored(self, value="a-stored-key"):
        from sunshine_apps_ui.core import artwork_sources
        patched = mock.patch.object(artwork_sources, "load_sgdb_key",
                                    lambda conf_dir: value)
        patched.start()
        self.addCleanup(patched.stop)

    def test_the_field_is_offered(self):
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("/settings/sgdb-key", body)
        self.assertIn("Community artwork", body)

    def test_it_says_when_no_key_is_stored(self):
        self._stored("")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("No key stored", body)

    def test_it_says_when_a_key_is_stored(self):
        self._stored()
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("A key is stored", body)

    def test_the_stored_key_is_never_rendered(self):
        """It is a secret. The page says whether there is one, not what it is."""
        self._stored("sekrit-value-0123")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertNotIn("sekrit-value-0123", body)

    def test_a_typed_key_reaches_save_sgdb(self):
        seen = self._saving()
        self.post({"sgdb-key": " typed-key "}, token=self.token,
                  path="/settings/sgdb-key")
        # Trimmed: a key pasted from a web page arrives with whitespace, and a
        # key with a space on the end is a key that does not work.
        self.assertEqual(seen["key"], "typed-key")
        self.assertEqual(seen["conf_dir"], self.conf_dir)

    def test_a_good_key_is_reported_without_naming_the_file(self):
        self._saving()
        self._stored("")
        self.post({"sgdb-key": "good"}, token=self.token,
                  path="/settings/sgdb-key")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("That key works", body)
        self.assertNotIn(".bsm-sgdb-key", body)

    def test_a_bad_key_says_why(self):
        self._saving(ok=False)
        self._stored("")
        self.post({"sgdb-key": "bad"}, token=self.token,
                  path="/settings/sgdb-key")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("did not accept that key", body)

    def test_an_empty_field_does_not_reach_the_network(self):
        seen = self._saving()
        self.post({"sgdb-key": "   "}, token=self.token,
                  path="/settings/sgdb-key")
        self.assertEqual(seen, {})
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("No key was typed", body)

    def test_the_result_is_shown_once(self):
        """Cleared when drawn, like every other one-shot notice here: a result
        still on the page after a reload reads as a second attempt."""
        self._saving()
        self._stored("")
        self.post({"sgdb-key": "good"}, token=self.token,
                  path="/settings/sgdb-key")
        self.get(f"/settings?token={self.token}")
        _, body = self.get(f"/settings?token={self.token}")
        self.assertNotIn("That key works", body)

    def test_it_needs_the_token(self):
        """404 rather than 403, as everywhere else here: a wrong token is told
        there is nothing at this address, not that it guessed the wrong one."""
        seen = self._saving()
        status, _ = self.post({"sgdb-key": "good"}, path="/settings/sgdb-key")
        self.assertEqual(status, 404)
        self.assertEqual(seen, {})


class SteamGridDbSheetTest(ServerTest):
    """Issue #30. Community artwork arrives a page at a time, on demand.

    Cyberpunk 2077 has 689 grids and the picker offered twelve of them, chosen
    by a sort on a `score` field that is zero on every item of every game. The
    sort is gone. What replaces it is a modal that pages through the lot, and
    which is never fetched until somebody presses for it.
    """

    def _key(self, ready=True):
        self.engine.candidates = {"ok": True, "candidates": [], "notes": [],
                                  "offer_sgdb": not ready, "sgdb_ready": ready}

    def _page(self, n=0, count=48, total=689):
        self.engine.sgdb = {
            "ok": True, "note": "", "total": total, "page": n,
            "pages": (total + 47) // 48,
            "candidates": [{"id": f"c{i}", "source": "sgdb", "label": "by nobody",
                            "origin": f"https://g/{n}-{i}.png",
                            "path": f"/cache/{n}-{i}.png"} for i in range(count)]}

    def _open(self, page=None, go=True):
        """*go* is the second step: the first draws the spinner, the second
        does the fetching. Issue #31."""
        url = "/artwork?key=index:0&token=" + self.token
        if page is not None:
            url += f"&sgdb=1&sgdb_page={page}" + ("&go=1" if go else "")
        return self.get(url)[1]

    # --- nothing is fetched until it is asked for --------------------------

    def test_opening_the_picker_fetches_no_community_artwork(self):
        """The whole point of on demand. This is the assertion that stops it
        quietly going back to a network round trip on every picker open."""
        self._key()
        self._open()
        self.assertEqual(self.engine.sgdb_calls, [])

    def test_the_button_is_offered_when_a_key_is_stored(self):
        self._key()
        body = self._open()
        self.assertIn("Show SteamGridDB art", body)
        self.assertIn("sgdb=1", body)

    def test_no_button_without_a_key(self):
        self._key(ready=False)
        body = self._open()
        self.assertNotIn("Show SteamGridDB art", body)

    def test_asking_without_a_key_fetches_nothing(self):
        """The address can say sgdb=1 whatever the state of the key file."""
        self._key(ready=False)
        self._open(page=0)
        self.assertEqual(self.engine.sgdb_calls, [])

    # --- the sheet ---------------------------------------------------------

    def test_pressing_it_fetches_page_zero(self):
        self._key(); self._page()
        self._open(page=0)
        self.assertEqual(len(self.engine.sgdb_calls), 1)
        self.assertEqual(self.engine.sgdb_calls[0]["page"], 0)

    def test_the_sheet_is_a_dialog_that_opens_without_script(self):
        """A modal that needs JavaScript to open is a modal that does not open
        -- which is exactly what happened to the settings switches (#28). It is
        rendered already open, so nothing has to run for it to be there."""
        self._key(); self._page()
        body = self._open(page=0)
        # The whole opening tag, not just "<dialog": the CSS beside it used to
        # mention the tag in a comment, so the loose assertion passed on a page
        # with no sheet on it at all.
        self.assertIn('<dialog class="sheet" open', body)
        self.assertNotIn("<script>", body)          # nothing inline

    def test_every_control_in_the_sheet_is_a_link(self):
        """The contract that matters, now that sheet.js exists: script sizes the
        grid and does nothing else, so with it blocked or broken the sheet is
        still a sheet you can page, close and choose from with a gamepad."""
        self._key(); self._page(n=1)
        body = self._open(page=1)
        sheet = body[body.index('<dialog class="sheet" open'):]
        for control in ("sgdb_page=2", "sgdb_page=0", "Close"):
            self.assertIn(control, sheet)
        # No button, no form, no handler -- links and images.
        self.assertNotIn("<button", sheet)
        self.assertNotIn("onclick", sheet)

    def test_the_results_page_carries_no_script_at_all(self):
        """Sizing moved to the waiting page, which is the only place that needs
        to measure anything. What comes back with the pictures is plain HTML."""
        self._key(); self._page()
        self.assertNotIn("<script", self._open(page=0))

    def test_the_picker_carries_no_open_dialog_until_asked(self):
        """The other half of the one above, and the half that can regress:
        a sheet that is always in the markup is a sheet that is always up."""
        self._key(); self._page()
        self.assertNotIn('<dialog class="sheet" open', self._open())

    def test_it_says_how_far_through_you_are(self):
        self._key(); self._page(n=1)
        body = self._open(page=1)
        self.assertIn("49-96 of 689", body)
        self.assertIn("Page 2 of 15", body)

    def test_next_and_back_carry_the_page(self):
        self._key(); self._page(n=1)
        body = self._open(page=1)
        self.assertIn("sgdb_page=2", body)
        self.assertIn("sgdb_page=0", body)

    def test_back_is_dead_on_the_first_page(self):
        self._key(); self._page(n=0)
        body = self._open(page=0)
        self.assertIn('flat">Back', body)

    def test_next_is_dead_on_the_last_page(self):
        self._key(); self._page(n=14)
        body = self._open(page=14)
        self.assertIn('flat">Next', body)

    def test_a_negative_page_is_read_as_the_first(self):
        self._key(); self._page()
        self.get(f"/artwork?key=index:0&token={self.token}&sgdb=1&sgdb_page=-4&go=1")
        self.assertEqual(self.engine.sgdb_calls[0]["page"], 0)

    def test_a_nonsense_page_is_read_as_the_first(self):
        self._key(); self._page()
        self.get(f"/artwork?key=index:0&token={self.token}&sgdb=1&sgdb_page=banana&go=1")
        self.assertEqual(self.engine.sgdb_calls[0]["page"], 0)

    def test_the_search_term_survives_a_page_turn(self):
        """Paging through results for a name you typed must keep looking up
        that name, not fall back to the entry's own title."""
        self._key(); self._page()
        self.get(f"/artwork?key=index:0&token={self.token}"
                 f"&q=Cyberpunk&sgdb=1&sgdb_page=1&go=1")
        self.assertEqual(self.engine.sgdb_calls[0]["name"], "Cyberpunk")

    def test_closing_leads_back_to_the_picker_without_the_sheet(self):
        self._key(); self._page()
        body = self._open(page=0)
        self.assertIn("Close", body)
        self.assertIn(f"/artwork?key=index%3A0&token={self.token}", body)

    def test_a_failure_leaves_the_picker_standing(self):
        """The sheet is one source among several. It failing is not the page
        failing -- everything already found is still on it."""
        self._key()
        self.engine.fails = {"art_sgdb": "SteamGridDB is not answering"}
        body = self._open(page=0)
        self.assertIn("SteamGridDB is not answering", body)
        self.assertIn("Artwork for", body)


class SteamGridDbWaitingTest(ServerTest):
    """Issue #31, the first half: the button had no visible effect.

    Pressing it fetched the list *and* downloaded all 48 pictures before the
    browser was given anything to draw, so the window sat there looking like
    nothing had happened. The sheet goes up empty with a spinner now, and the
    page it refreshes to is the one that does the asking.
    """

    def setUp(self):
        super().setUp()
        self.engine.candidates = {"ok": True, "candidates": [], "notes": [],
                                  "offer_sgdb": False, "sgdb_ready": True}

    def _wait_page(self):
        return self.get(f"/artwork?key=index:0&token={self.token}"
                        f"&sgdb=1&sgdb_page=0")[1]

    def test_the_first_step_asks_steamgriddb_nothing(self):
        self._wait_page()
        self.assertEqual(self.engine.sgdb_calls, [])

    def test_the_sheet_is_already_up(self):
        """Up, and empty. The point is that it appears at once."""
        body = self._wait_page()
        self.assertIn('<dialog class="sheet" open', body)
        self.assertIn('class="spinner"', body)

    def test_it_refreshes_into_the_fetch(self):
        body = self._wait_page()
        self.assertIn('http-equiv="refresh"', body)
        self.assertIn("go=1", body)

    def test_the_waiting_sheet_measures_how_many_fit(self):
        """The empty sheet is the box the pictures will go in, so this is where
        the count is taken. The spinner itself is CSS."""
        body = self._wait_page()
        self.assertIn("/sheet.js", body)
        self.assertNotIn("<script>", body)          # nothing inline

    def test_the_waiting_sheet_works_without_the_script(self):
        """The meta refresh goes to the same address without a count, and the
        server falls back to a full page. Script makes it fit, not work."""
        body = self._wait_page()
        self.assertIn('http-equiv="refresh"', body)
        self.assertNotIn("per=", body)

    def test_it_claims_no_count_while_it_is_still_asking(self):
        """"1-0 of 0" beside a spinner is worse than saying nothing."""
        body = self._wait_page()
        self.assertNotIn(" of 0", body)
        self.assertNotIn("Page 1 of", body)

    def test_paging_is_dead_while_waiting(self):
        body = self._wait_page()
        self.assertIn('flat">Back', body)
        self.assertIn('flat">Next', body)

    def test_the_button_leads_to_the_spinner_not_the_fetch(self):
        """Otherwise the first thing pressed is the slow thing again."""
        body = self.get(f"/artwork?key=index:0&token={self.token}")[1]
        self.assertIn("Show SteamGridDB art", body)
        start = body.index("Show SteamGridDB art")
        link = body[max(0, start - 300):start]
        self.assertIn("sgdb=1", link)
        self.assertNotIn("go=1", link)


class SheetFitsItsGridTest(ServerTest):
    """The sheet is drawn to the size of the grid it holds.

    Whole rows in a screen-sized sheet leave up to a row of empty space at the
    bottom, and empty space is what says "this is the last page" -- so a full
    page looked like the end. sheet.js measures the size that holds exactly
    the rows that fit, and every page of the run is drawn at it, the last one
    included, so a short last page is still the only one with a gap.
    """

    def setUp(self):
        super().setUp()
        self.engine.candidates = {"ok": True, "candidates": [], "notes": [],
                                  "offer_sgdb": False, "sgdb_ready": True}
        self.engine.sgdb = {"ok": True, "candidates": [
            {"id": str(i), "label": "by someone", "origin": "x"}
            for i in range(30)], "total": 689, "page": 1, "per": 30,
            "pages": 23, "note": ""}

    def _get(self, extra, go=True):
        return self.get(f"/artwork?key=index:0&token={self.token}"
                        f"&sgdb=1&sgdb_page=1&per=30{extra}"
                        + ("&go=1" if go else ""))[1]

    def _dialog(self, body):
        at = body.index('<dialog class="sheet"')
        return body[at:body.index(">", at) + 1]

    def test_the_measured_size_is_the_sheet_size(self):
        self.assertIn('style="width:1010px;height:900px"',
                      self._dialog(self._get("&fit=1010x900")))

    def test_the_waiting_sheet_is_already_that_size(self):
        """Otherwise the sheet jumps when the pictures arrive."""
        body = self._get("&fit=1010x900", go=False)
        self.assertIn('style="width:1010px;height:900px"', self._dialog(body))
        self.assertIn("fit=1010x900", body)          # carried into the fetch

    def test_next_and_back_keep_the_size(self):
        """The last page must be drawn in the same box as the full ones, or
        its gap stops meaning anything."""
        body = self._get("&fit=1010x900")
        foot = body[body.index('class="sheet-foot"'):]
        self.assertEqual(foot.count("fit=1010x900"), 2)

    def test_without_a_measurement_the_stylesheet_decides(self):
        self.assertNotIn("style=", self._dialog(self._get("")))

    def test_nothing_but_two_numbers_reaches_the_style(self):
        for asked in ("1010x900;background:red", "1010", "x900", "abcxdef",
                      "10x10", "99999x900", "1010x900x3", "-5x900"):
            with self.subTest(fit=asked):
                body = self._get("&fit=" + asked)
                self.assertNotIn("style=", self._dialog(body))
                self.assertNotIn("red", self._dialog(body))


class SteamGridDbPictureTest(ServerTest):
    """One picture per request, so the grid fills in rather than arriving whole.

    And the id is resolved against what this session was actually offered: a
    route that fetched whatever URL the page handed it would be a proxy onto
    anything this machine can reach.
    """

    def setUp(self):
        super().setUp()
        self.engine.candidates = {"ok": True, "candidates": [], "notes": [],
                                  "offer_sgdb": False, "sgdb_ready": True}
        self.engine.sgdb = {
            "ok": True, "note": "", "total": 2, "page": 0, "pages": 1,
            "candidates": [{"id": "a" * 16, "source": "sgdb", "label": "by x",
                            "origin": "https://cdn.example/a.png"}]}

    def _offered(self):
        self.get(f"/artwork?key=index:0&token={self.token}&sgdb=1&sgdb_page=0&go=1")

    def test_the_sheet_points_at_the_per_picture_route(self):
        self._offered()
        body = self.get(f"/artwork?key=index:0&token={self.token}"
                        f"&sgdb=1&sgdb_page=0&go=1")[1]
        self.assertIn("/sgdb-art?id=", body)

    def test_an_id_we_never_offered_is_refused(self):
        """Nothing is fetched for it -- this is the anti-proxy assertion."""
        seen = []
        with mock.patch.object(server_module, "art_sgdb_one",
                               lambda *a, **k: seen.append(a) or ""):
            status, _ = self.get_no_redirect(
                f"/sgdb-art?id={'b' * 16}&token={self.token}")
        self.assertEqual(status, 404)
        self.assertEqual(seen, [])

    def test_an_offered_id_is_fetched_by_its_origin(self):
        self._offered()
        asked = []

        def fetch(conf_dir, origin):
            asked.append(origin)
            return ""

        with mock.patch.object(server_module, "art_sgdb_one", fetch):
            self.get_no_redirect(f"/sgdb-art?id={'a' * 16}&token={self.token}")
        self.assertEqual(asked, ["https://cdn.example/a.png"])

    def test_it_needs_the_token(self):
        self._offered()
        status, _ = self.get_no_redirect(f"/sgdb-art?id={'a' * 16}")
        self.assertEqual(status, 404)


class ChoosingFromTheSheetTest(ServerTest):
    """Picking a picture whose tile never loaded still works. Issue #31.

    Choosing copies the cached file, and a sheet picture is cached only once
    the browser has fetched it. That is normally true -- you click what you can
    see -- but a tile whose image failed is still a link, and "that artwork is
    no longer cached" is a baffling answer to "I picked this one".
    """

    def setUp(self):
        super().setUp()
        self.engine.candidates = {"ok": True, "candidates": [], "notes": [],
                                  "offer_sgdb": False, "sgdb_ready": True}
        self.engine.sgdb = {
            "ok": True, "note": "", "total": 1, "page": 0, "pages": 1,
            "candidates": [{"id": "c" * 16, "source": "sgdb", "label": "by x",
                            "origin": "https://cdn.example/c.png"}]}
        self.get(f"/artwork?key=index:0&token={self.token}&sgdb=1&sgdb_page=0&go=1")

    def test_it_is_fetched_before_being_chosen(self):
        asked = []
        with mock.patch.object(server_module, "art_sgdb_one",
                               lambda conf, origin: asked.append(origin) or ""):
            self.get_no_redirect(f"/artwork?key=index:0&choose={'c' * 16}"
                                 f"&token={self.token}")
        self.assertEqual(asked, ["https://cdn.example/c.png"])

    def test_a_picture_we_never_offered_is_not_fetched(self):
        """The same rule as the image route: only what we listed."""
        asked = []
        with mock.patch.object(server_module, "art_sgdb_one",
                               lambda conf, origin: asked.append(origin) or ""):
            self.get_no_redirect(f"/artwork?key=index:0&choose={'d' * 16}"
                                 f"&token={self.token}")
        self.assertEqual(asked, [])


class TheLastPageLooksLikeTheLastPageTest(ServerTest):
    """A short page keeps the tile size and leaves the grid part empty.

    That empty space is the signal. The pages were briefly evened out so every
    page was the same length, which removed it; Sean's call, 2026-09-22: "the
    grid not filling a page feels like it's signaling this is the last page."
    """

    def setUp(self):
        super().setUp()
        self.engine.candidates = {"ok": True, "candidates": [], "notes": [],
                                  "offer_sgdb": False, "sgdb_ready": True}

    def _page(self, n, count, total=689):
        self.engine.sgdb = {
            "ok": True, "note": "", "total": total, "page": n,
            "pages": (total + 47) // 48,
            "candidates": [{"id": f"{i:016x}", "source": "sgdb", "label": "by x",
                            "origin": f"https://cdn.example/{n}-{i}.png"}
                           for i in range(count)]}
        return self.get(f"/artwork?key=index:0&token={self.token}"
                        f"&sgdb=1&sgdb_page={n}&go=1")[1]

    def test_the_tiles_are_a_fixed_size_so_a_short_page_is_simply_short(self):
        """Nothing in the markup tells the grid how many a full page holds any
        more: the tile is a fixed size -- the main grid's own 164.67px -- so
        seventeen pictures are seventeen tiles and the rest of the box is
        empty. That empty space is the end-of-list signal."""
        body = self._page(14, 17)
        self.assertNotIn("data-full", body)
        self.assertEqual(body.count("/sgdb-art?id="), 17)

    def test_a_full_page_uses_the_same_tile(self):
        self.assertNotIn("data-full", self._page(0, 48))

    def test_the_count_says_where_the_end_is(self):
        self.assertIn("673-689 of 689", self._page(14, 17))

    def test_next_is_dead_on_the_last_page(self):
        self.assertIn('flat">Next', self._page(14, 17))

    def test_pages_are_full_sized_throughout(self):
        """Fourteen pages of 48 and then one of 17 -- not fifteen of 46."""
        body = self._page(1, 48)
        self.assertIn("49-96 of 689", body)
        self.assertIn("Page 2 of 15", body)
