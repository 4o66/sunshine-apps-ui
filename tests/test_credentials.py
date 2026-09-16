# SPDX-License-Identifier: GPL-3.0-or-later
"""Asking for a secret without it reaching argv, ps, or shell history.

These were shell scripts using `read -rs`. What they guaranteed is what is
tested here: nothing is echoed, nothing becomes an argument, and nothing is
written until the value has been checked.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import credentials  # noqa: E402


class SunshineCredentialsTest(unittest.TestCase):
    def _capture(self, secrets, username="admin"):
        answers = iter(secrets)
        return credentials.capture_sunshine_credentials(
            "/conf", ask=lambda prompt: next(answers),
            ask_visible=lambda prompt: username)

    def test_a_good_pair_is_verified_then_stored(self):
        with mock.patch("sunshine_apps_ui.core.api.save_auth",
                        return_value=(True, "Verified and saved")) as saved:
            ok, message = self._capture(["hunter2", "hunter2"])
        self.assertTrue(ok)
        saved.assert_called_once_with("/conf", "admin", "hunter2")

    def test_a_mistyped_confirmation_writes_nothing(self):
        with mock.patch("sunshine_apps_ui.core.api.save_auth") as saved:
            ok, message = self._capture(["hunter2", "hunter3"])
        self.assertFalse(ok)
        self.assertFalse(saved.called)
        self.assertIn("do not match", message)

    def test_an_empty_password_writes_nothing(self):
        with mock.patch("sunshine_apps_ui.core.api.save_auth") as saved:
            ok, message = self._capture(["", ""])
        self.assertFalse(ok)
        self.assertFalse(saved.called)

    def test_an_empty_username_writes_nothing(self):
        with mock.patch("sunshine_apps_ui.core.api.save_auth") as saved:
            ok, _ = self._capture(["hunter2", "hunter2"], username="")
        self.assertFalse(ok)
        self.assertFalse(saved.called)

    def test_a_rejected_pair_says_nothing_was_written(self):
        with mock.patch("sunshine_apps_ui.core.api.save_auth",
                        return_value=(False, "Sunshine rejected the credentials")):
            ok, message = self._capture(["hunter2", "hunter2"])
        self.assertFalse(ok)
        self.assertIn("Nothing was written", message)

    def test_it_is_verified_before_it_is_written(self):
        """A typo should fail here, not silently later when Sunshine stops
        answering and it looks like something else."""
        import inspect
        from sunshine_apps_ui.core import sunshine_api
        self.assertIn("verify_credentials",
                      inspect.getsource(sunshine_api.save_credentials))


class SgdbKeyTest(unittest.TestCase):
    def test_a_good_key_is_checked_then_stored(self):
        with mock.patch("sunshine_apps_ui.core.api.save_sgdb",
                        return_value=(True, "Verified and saved")) as saved:
            ok, _ = credentials.capture_sgdb_key("/conf", ask=lambda p: " abc123 ")
        self.assertTrue(ok)
        saved.assert_called_once_with("/conf", "abc123")

    def test_no_key_writes_nothing(self):
        with mock.patch("sunshine_apps_ui.core.api.save_sgdb") as saved:
            ok, message = credentials.capture_sgdb_key("/conf", ask=lambda p: "  ")
        self.assertFalse(ok)
        self.assertFalse(saved.called)
        self.assertIn("nothing written", message)

    def test_a_key_the_api_refuses_is_not_stored(self):
        with mock.patch("sunshine_apps_ui.core.api.save_sgdb",
                        return_value=(False, "SteamGridDB did not accept that key")):
            ok, message = credentials.capture_sgdb_key("/conf", ask=lambda p: "nope")
        self.assertFalse(ok)
        self.assertIn("Nothing was written", message)


class NotOnTheCommandLineTest(unittest.TestCase):
    """The reason these exist at all.

    The project this grew out of took --sgdb-key as an argument, which puts it
    in ps output and in shell history.
    """

    def test_the_prompt_does_not_echo(self):
        import inspect
        self.assertIn("getpass", inspect.getsource(credentials._ask))

    def test_no_flag_takes_a_secret_as_a_value(self):
        from sunshine_apps_ui import __main__ as entry
        import inspect
        source = inspect.getsource(entry)
        for flag in ('"--sgdb-key"', '"--password"', '"--api-key"'):
            self.assertNotIn(flag, source)

    def test_the_key_is_read_from_the_terminal_rather_than_argv(self):
        from sunshine_apps_ui import __main__ as entry
        import inspect
        source = inspect.getsource(entry)
        self.assertIn("--save-sgdb-key", source)
        self.assertIn("--save-credentials", source)


if __name__ == "__main__":
    unittest.main()
