"""Tests for the request checks. Loopback binding is not the only defence."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import security  # noqa: E402


class Headers(dict):
    """http.client.HTTPMessage is case-insensitive; mimic just enough of it."""
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class TestToken(unittest.TestCase):
    def test_tokens_are_unique_and_long(self):
        a, b = security.new_token(), security.new_token()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 32)

    def test_missing_or_wrong_token_is_refused(self):
        for given in (None, "", "wrong"):
            self.assertFalse(security.token_matches("secret", given))
        self.assertTrue(security.token_matches("secret", "secret"))


class TestHostHeader(unittest.TestCase):
    """Rejecting a foreign Host is what stops DNS rebinding."""

    def test_loopback_with_our_port_is_accepted(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
            self.assertTrue(security.host_is_loopback(host, 8765), host)

    def test_a_rebound_hostname_is_refused(self):
        self.assertFalse(security.host_is_loopback("evil.example.com:8765", 8765))

    def test_wrong_port_is_refused(self):
        self.assertFalse(security.host_is_loopback("127.0.0.1:9999", 8765))

    def test_missing_port_is_refused(self):
        self.assertFalse(security.host_is_loopback("127.0.0.1", 8765))

    def test_absent_host_is_refused(self):
        self.assertFalse(security.host_is_loopback(None, 8765))


class TestOrigin(unittest.TestCase):
    def test_same_origin_and_direct_navigation_are_allowed(self):
        self.assertTrue(security.origin_is_same(None, "same-origin", 8765))
        self.assertTrue(security.origin_is_same(None, "none", 8765))
        self.assertTrue(security.origin_is_same(None, None, 8765))

    def test_cross_site_is_refused(self):
        self.assertFalse(security.origin_is_same(None, "cross-site", 8765))
        self.assertFalse(security.origin_is_same(None, "same-site", 8765))

    def test_a_null_origin_with_same_origin_fetch_site_is_allowed(self):
        """Our own Referrer-Policy makes Chrome send Origin: null on form posts.

        Reading that as a foreign origin refused the very form the page had just
        rendered. Sec-Fetch-Site is set by the browser and cannot be forged by a
        page, so it decides when present.
        """
        self.assertTrue(security.origin_is_same("null", "same-origin", 8765))

    def test_a_null_origin_without_fetch_site_is_still_refused(self):
        self.assertFalse(security.origin_is_same("null", None, 8765))

    def test_fetch_site_decides_even_when_origin_disagrees(self):
        self.assertFalse(security.origin_is_same("http://127.0.0.1:8765",
                                                 "cross-site", 8765))

    def test_foreign_origin_header_is_refused(self):
        self.assertFalse(security.origin_is_same("https://evil.example.com", None, 8765))

    def test_loopback_origin_on_another_port_is_refused(self):
        """Another local service must not be able to drive this one."""
        self.assertFalse(security.origin_is_same("http://127.0.0.1:9999", None, 8765))
        self.assertTrue(security.origin_is_same("http://127.0.0.1:8765", None, 8765))


class TestCheck(unittest.TestCase):
    def _headers(self, **over):
        h = Headers({"Host": "127.0.0.1:8765"})
        h.update(over)
        return h

    def test_happy_path(self):
        ok, _ = security.check(self._headers(), "secret", "secret", 8765)
        self.assertTrue(ok)

    def test_token_in_a_header_also_works(self):
        h = self._headers(**{"X-Auth-Token": "secret"})
        ok, _ = security.check(h, None, "secret", 8765)
        self.assertTrue(ok)

    def test_each_failure_is_reported_distinctly(self):
        cases = [
            (self._headers(Host="evil.com:8765"), "secret", "bad Host header"),
            (self._headers(**{"Sec-Fetch-Site": "cross-site"}), "secret", "cross-site request"),
            (self._headers(), "nope", "bad or missing token"),
        ]
        for headers, tok, expected in cases:
            ok, reason = security.check(headers, tok, "secret", 8765)
            self.assertFalse(ok)
            self.assertEqual(reason, expected)

    def test_a_cross_site_top_level_navigation_is_allowed(self):
        """Following the link from a terminal or chat app arrives cross-site.

        Refusing it breaks the only way most people will ever open this page,
        and a cross-site GET cannot read the response anyway. The token is the
        authenticator.
        """
        h = self._headers(**{"Sec-Fetch-Site": "cross-site",
                             "Sec-Fetch-Mode": "navigate",
                             "Sec-Fetch-Dest": "document"})
        ok, reason = security.check(h, "secret", "secret", 8765)
        self.assertTrue(ok, reason)

    def test_a_cross_site_navigation_still_needs_the_token(self):
        h = self._headers(**{"Sec-Fetch-Site": "cross-site",
                             "Sec-Fetch-Mode": "navigate",
                             "Sec-Fetch-Dest": "document"})
        ok, reason = security.check(h, None, "secret", 8765)
        self.assertFalse(ok)
        self.assertEqual(reason, "bad or missing token")

    def test_a_cross_site_fetch_is_still_refused(self):
        """Only navigations get the exemption; a script-driven fetch does not."""
        h = self._headers(**{"Sec-Fetch-Site": "cross-site",
                             "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"})
        ok, reason = security.check(h, "secret", "secret", 8765)
        self.assertFalse(ok)
        self.assertEqual(reason, "cross-site request")

    def test_an_unsafe_method_never_gets_the_navigation_exemption(self):
        """A cross-site form POST is a navigation too, and must not be trusted."""
        h = self._headers(**{"Sec-Fetch-Site": "cross-site",
                             "Sec-Fetch-Mode": "navigate",
                             "Sec-Fetch-Dest": "document"})
        ok, reason = security.check(h, "secret", "secret", 8765, method="POST")
        self.assertFalse(ok)
        self.assertEqual(reason, "cross-site request")

    def test_a_valid_token_does_not_rescue_a_bad_host(self):
        ok, _ = security.check(self._headers(Host="evil.com:8765"), "secret", "secret", 8765)
        self.assertFalse(ok)

    def test_bind_host_is_loopback_and_not_configurable(self):
        self.assertEqual(security.BIND_HOST, "127.0.0.1")
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "src", "sunshine_apps_ui", "__main__.py")).read()
        self.assertNotIn("--host", src)
        self.assertNotIn("--bind", src)


if __name__ == "__main__":
    unittest.main()
