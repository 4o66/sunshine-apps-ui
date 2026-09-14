"""End-to-end tests against a real server on a loopback port."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from sunshine_apps_ui import importer, security  # noqa: E402
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


def fake_importer(payload=None, exit_code=0, stderr="log line"):
    """A stand-in that speaks the contract: JSON on stdout, logs on stderr."""
    body = json.dumps(payload if payload is not None else PLAN)
    fd, path = tempfile.mkstemp(suffix=".sh")
    script = (
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *--check-auth*) echo '{\"ok\": true, \"message\": \"ok\"}'; exit 0 ;;\n"
        "  *--state*) cat <<'S'\n" + json.dumps(STATE) + "\nS\n exit 0 ;;\n"
        "  *--save-auth*)  cat >/dev/null; echo '{\"ok\": true, \"message\": \"saved\"}'; exit 0 ;;\n"
        "esac\n"
        f"cat <<'J'\n{body}\nJ\n"
        f"echo '{stderr}' >&2\nexit {exit_code}\n"
    )
    os.write(fd, script.encode())
    os.close(fd)
    os.chmod(path, 0o755)
    return path


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.importer = fake_importer()
        self.token = security.new_token()
        self.httpd = serve(self.token, self.importer, [], port=0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.unlink(self.importer)

    def get(self, path="/", token=None, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        if token:
            url += f"?token={token}"
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

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


class ImporterContractTest(unittest.TestCase):
    def test_unknown_schema_is_rejected_rather_than_guessed(self):
        with self.assertRaises(importer.ImporterError) as cm:
            importer.parse_plan(json.dumps({"schema": 99, "plan": {}}))
        self.assertIn("not supported", str(cm.exception))

    def test_non_json_output_is_rejected(self):
        with self.assertRaises(importer.ImporterError):
            importer.parse_plan("this is a log line, not a plan")

    def test_a_failing_importer_surfaces_its_exit_code(self):
        path = fake_importer(exit_code=3, stderr="boom")
        try:
            with self.assertRaises(importer.ImporterError) as cm:
                importer.run_plan(path)
            self.assertIn("exited 3", str(cm.exception))
        finally:
            os.unlink(path)

    def test_the_importer_is_always_invoked_read_only(self):
        """--dry-run must be non-negotiable; the UI never writes apps.json."""
        fd, path = tempfile.mkstemp(suffix=".sh")
        argdump = path + ".args"
        os.write(fd, f"#!/bin/sh\necho \"$@\" > {argdump}\ncat <<'J'\n{json.dumps(PLAN)}\nJ\n".encode())
        os.close(fd); os.chmod(path, 0o755)
        try:
            importer.run_plan(path, ["--no-heroic"])
            recorded = open(argdump).read().split()
            self.assertIn("--dry-run", recorded)
            self.assertIn("--json", recorded)
            self.assertIn("--no-heroic", recorded)
        finally:
            os.unlink(path); os.path.exists(argdump) and os.unlink(argdump)


if __name__ == "__main__":
    unittest.main()


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

    def test_get_apply_shows_a_confirmation_and_changes_nothing(self):
        status, body = self.get("/apply", token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("Write and reload", body)
        self.assertIn("Cancel", body)

    def test_the_confirmation_lists_the_actual_changes(self):
        """Naming them beats asserting that some exist."""
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Will be added", body)
        self.assertIn("Half-Life", body)

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
        status, headers = self.post({}, token=self.token, path="/apply")
        self.assertEqual(status, 303)
        self.assertNotIn("/applied", headers["Location"])

    def test_the_apply_invocation_is_not_a_dry_run_and_does_reload(self):
        """The two flags that make apply mean 'write and reload'."""
        fd, path = tempfile.mkstemp(suffix=".sh")
        argdump = path + ".args"
        os.write(fd, f"#!/bin/sh\necho \"$@\" > {argdump}\nexit 0\n".encode())
        os.close(fd); os.chmod(path, 0o755)
        try:
            from sunshine_apps_ui.importer import apply_plan
            apply_plan(path, ["--no-heroic"])
            recorded = open(argdump).read().split()
            self.assertIn("--reload", recorded)
            self.assertNotIn("--dry-run", recorded)
            self.assertIn("--no-heroic", recorded)
        finally:
            os.unlink(path); os.path.exists(argdump) and os.unlink(argdump)


class AppliedPageTest(ServerTest):
    def test_success_lands_somewhere_static(self):
        """Re-running the importer here would race the teardown the apply caused."""
        status, headers = self.post({}, token=self.token, path="/apply")
        self.assertEqual(status, 303)
        self.assertTrue(headers["Location"].startswith("/applied?"), headers["Location"])

    def test_the_applied_page_does_not_invoke_the_importer(self):
        fd, path = tempfile.mkstemp(suffix=".sh")
        marker = path + ".ran"
        os.write(fd, f"#!/bin/sh\ntouch {marker}\nexit 1\n".encode())
        os.close(fd); os.chmod(path, 0o755)
        self.httpd.RequestHandlerClass.importer_path = path
        try:
            status, body = self.get(f"/applied?token={self.token}")
            self.assertEqual(status, 200)
            self.assertIn("Applied", body)
            self.assertFalse(os.path.exists(marker), "the importer was invoked")
        finally:
            self.httpd.RequestHandlerClass.importer_path = self.importer
            os.unlink(path)
            os.path.exists(marker) and os.unlink(marker)

    def test_applied_needs_the_token(self):
        self.assertEqual(self.get("/applied")[0], 404)

    def test_a_failed_apply_still_returns_to_the_plan(self):
        """Nothing reloaded, so nothing is tearing down; the plan is safe to render."""
        fd, path = tempfile.mkstemp(suffix=".sh")
        os.write(fd, b"#!/bin/sh\necho boom >&2\nexit 3\n")
        os.close(fd); os.chmod(path, 0o755)
        self.httpd.RequestHandlerClass.importer_path = path
        try:
            status, headers = self.post({}, token=self.token, path="/apply")
            self.assertEqual(status, 303)
            self.assertIn("apply_error", headers["Location"])
        finally:
            self.httpd.RequestHandlerClass.importer_path = self.importer
            os.unlink(path)


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
            _, body = self.get(f"/?scan=1&token={self.token}")
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
            self.get(f"/?scan=1&token={self.token}")
            self.get(f"/?scan=1&token={self.token}")
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
        """The fixture importer also reports one addition, so this totals two."""
        from sunshine_apps_ui import state as st
        _, before = self.get("/apply", token=self.token)
        self.assertIn("Apply 1 change?", before)
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        _, after = self.get("/apply", token=self.token)
        self.assertIn("Apply 2 changes?", after)
        self.assertNotIn("Apply 0 changes?", after)

    def test_the_confirmation_names_them_in_plain_words(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        st.enqueue({"op": "add", "fields": {"name": "My Script"}})
        _, body = self.get("/apply", token=self.token)
        self.assertIn("Your changes", body)
        self.assertIn("Hide Portal 2", body)
        self.assertIn("Add My Script", body)

    def test_nothing_queued_and_nothing_found_still_reads_as_nothing(self):
        import tempfile as tf
        empty = {"schema": 1, "generator": {"name": "x", "version": "1"},
                 "totals": {}, "sources": [], "plan": {"added": []}}
        fd, path = tf.mkstemp(suffix=".sh")
        os.write(fd, f"#!/bin/sh\ncat <<'J'\n{json.dumps(empty)}\nJ\n".encode())
        os.close(fd); os.chmod(path, 0o755)
        self.httpd.RequestHandlerClass.importer_path = path
        try:
            _, body = self.get("/apply", token=self.token)
            self.assertIn("Nothing would change.", body)
            self.assertIn("Apply 0 changes?", body)
        finally:
            self.httpd.RequestHandlerClass.importer_path = self.importer
            os.unlink(path)

    def test_applying_a_queue_does_not_reload_twice(self):
        """One session of changes should cost one disconnect, not one per step."""
        import tempfile as tf
        fd, path = tf.mkstemp(suffix=".sh")
        argdump = path + ".args"
        # Must answer --mutate with JSON, or apply stops at the first step.
        os.write(fd, (f"#!/bin/sh\necho \"$@\" >> {argdump}\n"
                      "case \"$*\" in *--mutate*) cat >/dev/null; "
                      "echo '{\"ok\":true,\"applied\":1,\"results\":[]}';; esac\n"
                      "exit 0\n").encode())
        os.close(fd); os.chmod(path, 0o755)
        self.httpd.RequestHandlerClass.importer_path = path
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "hide", "index": 1, "name": "Portal 2"})
        try:
            self.post({}, token=self.token, path="/apply")
            calls = open(argdump).read().splitlines()
            reloads = [c for c in calls if "--reload" in c]
            self.assertEqual(len(reloads), 1, calls)
            self.assertTrue(any("--mutate" in c for c in calls), calls)
        finally:
            self.httpd.RequestHandlerClass.importer_path = self.importer
            os.unlink(path)
            os.path.exists(argdump) and os.unlink(argdump)


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

    def test_asking_twice_says_it_is_already_queued(self):
        from sunshine_apps_ui import state as st
        st.enqueue({"op": "restore", "selector": "steam:440", "name": "TF2"})
        _, body = self.get(f"/app?hidden=steam%3A440&token={self.token}")
        self.assertIn("Already queued", body)
        self.assertNotIn("Un-hide it", body)

    def test_an_entry_that_is_not_hidden_says_so(self):
        status, body = self.get(f"/app?hidden=steam%3A999&token={self.token}")
        self.assertEqual(status, 404)
        self.assertIn("not hidden", body)
        self.assertNotIn("Could not read a plan", body)

    def test_a_restore_without_a_selector_is_refused(self):
        status, _ = self.post({"op": "restore"}, token=self.token, path="/queue")
        self.assertEqual(status, 400)
