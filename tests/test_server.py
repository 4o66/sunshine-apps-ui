"""End-to-end tests against a real server on a loopback port."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
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
        "added": [{"name": "Portal 2", "source": "steam", "id": "620"}],
        "updated": [], "unchanged": [],
        "diverged": [{"name": "Cyberpunk 2077", "source": "steam", "id": "1091500",
                      "fields": [{"field": "cmd", "current": "mine <script>",
                                  "would_be": "theirs"}]}],
        "missing": [], "kept_foreign": [{"name": "Desktop"}],
        "removed_by_user": [], "suppressed": [], "pruned": [], "restored": [],
    },
}


def fake_importer(payload=None, exit_code=0, stderr="log line"):
    """A stand-in that speaks the contract: JSON on stdout, logs on stderr."""
    body = json.dumps(payload if payload is not None else PLAN)
    fd, path = tempfile.mkstemp(suffix=".sh")
    os.write(fd, f"#!/bin/sh\ncat <<'J'\n{body}\nJ\necho '{stderr}' >&2\nexit {exit_code}\n".encode())
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

    def test_it_binds_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_valid_token_renders_the_plan(self):
        status, body = self.get(token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("Portal 2", body)
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

    def test_user_content_is_escaped(self):
        _, body = self.get(token=self.token)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

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
