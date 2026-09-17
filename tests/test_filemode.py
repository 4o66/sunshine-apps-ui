# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeping the two secrets files to their owner.

The POSIX behaviour is the behaviour that already existed, and is tested for
real. The Windows behaviour cannot be tested from macOS -- there is no DACL to
read -- so what is tested here is that the decision is made from SIDs rather
than names, and that an unreadable ACL is treated as a failure rather than as
permission. The real check runs on the rig.

Worth stating the bug this replaces: on Windows `st_mode & 0o077` is always
zero, so the old guard reported "private" about a password file that inherited
Program Files' ACL and was readable by every authenticated account.
"""

import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core import filemode  # noqa: E402


class PosixModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "secret")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_a_written_secret_is_private_immediately(self):
        filemode.write_private(self.path, "password=hunter2\n")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        private, why = filemode.check_private(self.path)
        self.assertTrue(private)
        self.assertEqual(why, "")

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads anything")
    def test_a_readable_secret_is_refused_and_the_fix_is_named(self):
        filemode.write_private(self.path, "password=hunter2\n")
        os.chmod(self.path, 0o644)
        private, why = filemode.check_private(self.path)
        self.assertFalse(private)
        self.assertIn("chmod 600", why)
        self.assertIn(self.path, why)

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_the_content_survives_the_locking_down(self):
        filemode.write_private(self.path, "username=sean\npassword=hunter2\n")
        self.assertEqual(open(self.path).read(), "username=sean\npassword=hunter2\n")


class WindowsAclTest(unittest.TestCase):
    """What the Windows path decides, with the ACL lookup stood in for."""

    def setUp(self):
        self.real_name = os.name
        self.real_sid = filemode.current_user_sid
        self.real_dacl = filemode.dacl_sids
        self.real_owner = filemode.owner_sid
        os.name = "nt"
        filemode.current_user_sid = lambda: "S-1-5-21-1-2-3-1000"
        filemode.owner_sid = lambda path: "S-1-5-21-1-2-3-1000"

    def tearDown(self):
        os.name = self.real_name
        filemode.current_user_sid = self.real_sid
        filemode.dacl_sids = self.real_dacl
        filemode.owner_sid = self.real_owner

    def test_owner_system_and_administrators_are_allowed(self):
        filemode.dacl_sids = lambda path: [
            "S-1-5-21-1-2-3-1000", filemode.SYSTEM_SID, filemode.ADMINISTRATORS_SID]
        private, why = filemode.check_private("C:\\x\\credentials")
        self.assertTrue(private, why)

    def test_an_inherited_everyone_entry_is_a_leak(self):
        """The real case: a file created under Program Files inherits its ACL."""
        filemode.dacl_sids = lambda path: [
            "S-1-5-21-1-2-3-1000", filemode.SYSTEM_SID, "S-1-5-11"]  # Authenticated Users
        private, why = filemode.check_private("C:\\x\\credentials")
        self.assertFalse(private)
        self.assertIn("S-1-5-11", why)
        # The message has to carry the fix, since there is no chmod to suggest.
        self.assertIn("icacls", why)
        self.assertIn("/inheritance:r", why)

    def test_a_missing_dacl_is_not_treated_as_safe(self):
        filemode.dacl_sids = lambda path: ["<none>"]
        private, _ = filemode.check_private("C:\\x\\credentials")
        self.assertFalse(private)

    def test_an_unreadable_acl_is_refused_rather_than_assumed(self):
        def explode(path):
            raise OSError("could not read the permissions of C:\\x (error 5)")
        filemode.dacl_sids = explode
        private, why = filemode.check_private("C:\\x\\credentials")
        self.assertFalse(private)
        self.assertIn("cannot confirm", why)

    def test_owner_rights_entries_are_not_a_leak(self):
        """S-1-3-4 is "whoever owns this", which Windows puts on files in your own
        directories. It is the owner, not a second principal -- and it cost a real
        false positive on the rig before it was allowed for."""
        filemode.dacl_sids = lambda path: [
            filemode.OWNER_RIGHTS_SID, filemode.CREATOR_OWNER_SID, filemode.SYSTEM_SID]
        private, why = filemode.check_private("C:\\x\\credentials")
        self.assertTrue(private, why)

    def test_a_file_owned_by_somebody_else_is_not_private(self):
        """Allowing OWNER RIGHTS is only sound while the owner is us."""
        filemode.owner_sid = lambda path: "S-1-5-21-9-9-9-1001"
        filemode.dacl_sids = lambda path: [filemode.OWNER_RIGHTS_SID]
        private, why = filemode.check_private("C:\\x\\credentials")
        self.assertFalse(private)
        self.assertIn("owned by", why)

    def test_the_decision_is_made_from_sids_not_names(self):
        """Names are localised; "Administrators" is not what a German install calls it."""
        filemode.dacl_sids = lambda path: [filemode.ADMINISTRATORS_SID]
        self.assertTrue(filemode.check_private("C:\\x\\credentials")[0])
        self.assertEqual(filemode.ADMINISTRATORS_SID, "S-1-5-32-544")
        self.assertEqual(filemode.SYSTEM_SID, "S-1-5-18")



class PrivateLogTest(unittest.TestCase):
    """The server's log carries the session token, so it is not a public file.

    The token is the whole of the authentication for a server that can rewrite
    apps.json. It used to be written to /tmp/sunshine-apps-ui.log with whatever
    the umask gave it -- a fixed name, in a directory every local user can write
    and read. That is the exact threat the token exists to answer.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "server.log")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "POSIX modes; Windows is checked by ACL")
    def test_the_log_is_created_unreadable_by_others(self):
        with filemode.open_private(self.path) as handle:
            handle.write("http://127.0.0.1:1/?token=secret\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_a_symlink_left_there_first_is_refused_not_followed(self):
        """Otherwise a fixed path in a shared directory is a way to make an
        elevated launcher overwrite a file of somebody else's choosing."""
        target = os.path.join(self.tmp, "victim")
        with open(target, "w") as handle:
            handle.write("important")
        os.symlink(target, self.path)
        with self.assertRaises(OSError):
            filemode.open_private(self.path)
        self.assertEqual(open(target).read(), "important")

    def test_it_writes_what_it_was_given(self):
        with filemode.open_private(self.path) as handle:
            handle.write("hello\n")
        self.assertEqual(open(self.path).read(), "hello\n")


class LogLocationTest(unittest.TestCase):
    def test_the_log_lives_in_our_state_directory_not_a_shared_temp(self):
        from sunshine_apps_ui import launcher, places
        previous = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
        try:
            path = launcher.log_path()
            self.assertTrue(path.startswith(places.state_dir()), path)
            self.assertNotIn("/tmp/", path)
        finally:
            import shutil
            shutil.rmtree(os.environ["XDG_STATE_HOME"], ignore_errors=True)
            if previous is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = previous

if __name__ == "__main__":
    unittest.main()
