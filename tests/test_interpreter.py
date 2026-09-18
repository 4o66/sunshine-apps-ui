# SPDX-License-Identifier: GPL-3.0-or-later
"""Shipping a Python, for a Windows machine that has none.

The download itself is not exercised here -- these tests do not touch the
network. What is exercised is everything that decides whether what arrives is
used: the checksum, what happens when it does not match, and the ``._pth`` file
without which an embeddable interpreter can import nothing.

The checksum is the part worth being strict about. This runs elevated on
Windows, and an interpreter is the last thing to be relaxed about.
"""

import hashlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import interpreter  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DownloadVerificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.real_urlopen = interpreter.urllib.request.urlopen

    def tearDown(self):
        interpreter.urllib.request.urlopen = self.real_urlopen
        shutil.rmtree(self.tmp, ignore_errors=True)

    def serve(self, payload):
        interpreter.urllib.request.urlopen = lambda url, timeout=0: FakeResponse(payload)

    def artifact_for(self, payload):
        return interpreter.Artifact(
            "test", "https://example.invalid/thing.zip",
            hashlib.sha256(payload).hexdigest(), len(payload))

    def test_a_matching_download_is_kept(self):
        payload = b"the real thing"
        self.serve(payload)
        path = interpreter._download(self.artifact_for(payload), self.tmp)
        self.assertEqual(open(path, "rb").read(), payload)

    def test_a_mismatched_download_is_refused(self):
        self.serve(b"something else entirely")
        wrong = self.artifact_for(b"the real thing")
        with self.assertRaises(interpreter.ProvisionError) as caught:
            interpreter._download(wrong, self.tmp)
        message = str(caught.exception)
        self.assertIn("did not match its published checksum", message)
        self.assertIn(wrong.sha256, message)
        self.assertIn("Nothing was installed", message)

    def test_a_mismatched_download_is_deleted_rather_than_left(self):
        """Left on disk it becomes something a later run might trust."""
        self.serve(b"something else entirely")
        with self.assertRaises(interpreter.ProvisionError):
            interpreter._download(self.artifact_for(b"the real thing"), self.tmp)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_failed_fetch_says_which_artifact(self):
        def explode(url, timeout=0):
            raise OSError("no route to host")
        interpreter.urllib.request.urlopen = explode
        with self.assertRaises(interpreter.ProvisionError) as caught:
            interpreter._download(interpreter.CPYTHON, self.tmp)
        self.assertIn("CPython", str(caught.exception))
        self.assertIn("no route to host", str(caught.exception))


class PinnedArtifactsTest(unittest.TestCase):
    def test_both_artifacts_are_pinned_by_sha256(self):
        for artifact in interpreter.ARTIFACTS:
            self.assertRegex(artifact.sha256, r"^[0-9a-f]{64}$")

    def test_they_come_from_where_they_should(self):
        self.assertTrue(interpreter.CPYTHON.url.startswith(
            "https://www.python.org/ftp/python/"))
        self.assertTrue(interpreter.PILLOW.url.startswith(
            "https://files.pythonhosted.org/"))

    def test_the_wheel_matches_the_interpreter_it_will_run_on(self):
        """A binary wheel is tied to the ABI. Bumping one means bumping both."""
        self.assertIn("3.12", interpreter.CPYTHON.url)
        self.assertIn("cp312", interpreter.PILLOW.url)
        self.assertIn("win_amd64", interpreter.PILLOW.url)

    def test_describe_shows_what_would_be_downloaded(self):
        """Somebody about to accept a download should be able to see it first."""
        text = "\n".join(interpreter.describe())
        self.assertIn(interpreter.CPYTHON.url, text)
        self.assertIn(interpreter.PILLOW.sha256, text)


class PthFileTest(unittest.TestCase):
    """The file that makes an embeddable interpreter able to import anything."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_lists_our_source_and_site_packages(self):
        interpreter._write_pth(self.tmp)
        written = open(os.path.join(self.tmp, "python312._pth")).read()
        self.assertIn("..\\src", written)
        self.assertIn("Lib\\site-packages", written)

    def test_it_turns_site_back_on(self):
        """It ships commented out, and Pillow is not importable without it."""
        interpreter._write_pth(self.tmp)
        self.assertIn("import site",
                      open(os.path.join(self.tmp, "python312._pth")).read())

    def test_it_replaces_the_one_the_distribution_ships(self):
        shipped = os.path.join(self.tmp, "python312._pth")
        with open(shipped, "w") as handle:
            handle.write("python312.zip\n.\n#import site\n")
        interpreter._write_pth(self.tmp)
        written = open(shipped).read()
        self.assertNotIn("#import site", written)
        self.assertEqual(len([n for n in os.listdir(self.tmp) if n.endswith("._pth")]), 1)


class ProvisionTest(unittest.TestCase):
    """Unpacking, with the two downloads stood in for by zips built here."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.install = os.path.join(self.tmp, "install")
        os.makedirs(self.install)
        self.real_download = interpreter._download

        def fake_download(artifact, into, log=None):
            path = os.path.join(into, os.path.basename(artifact.url))
            with zipfile.ZipFile(path, "w") as archive:
                if artifact is interpreter.CPYTHON:
                    archive.writestr("python.exe", "not really")
                    archive.writestr("python312._pth", "python312.zip\n.\n#import site\n")
                else:
                    archive.writestr("PIL/__init__.py", "# pillow")
            return path

        interpreter._download = fake_download
        # The unpacked python.exe here is a text file, so it cannot be run.
        # Whether a real one runs is tested on the rig; these are about what
        # ends up where.
        self.real_works = interpreter.works
        interpreter.works = lambda executable: os.path.isfile(executable)

    def tearDown(self):
        interpreter._download = self.real_download
        interpreter.works = self.real_works
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_puts_an_interpreter_beside_the_program(self):
        executable = interpreter.provision(self.install)
        self.assertTrue(os.path.isfile(executable))
        self.assertEqual(interpreter.bundled_python(self.install), executable)

    def test_the_wheel_lands_where_it_can_be_imported(self):
        interpreter.provision(self.install)
        self.assertTrue(os.path.isfile(os.path.join(
            interpreter.interpreter_dir(self.install),
            "Lib", "site-packages", "PIL", "__init__.py")))

    def test_reprovisioning_replaces_rather_than_merges(self):
        """Half of one version and half of another is worse than either."""
        interpreter.provision(self.install)
        stray = os.path.join(interpreter.interpreter_dir(self.install), "stray.pyd")
        open(stray, "w").close()
        interpreter.provision(self.install)
        self.assertFalse(os.path.exists(stray))

    def test_nothing_is_left_behind_in_temp(self):
        before = len(os.listdir(tempfile.gettempdir()))
        interpreter.provision(self.install)
        self.assertLessEqual(len(os.listdir(tempfile.gettempdir())), before)

    def test_no_bundled_python_before_one_is_provisioned(self):
        self.assertEqual(interpreter.bundled_python(self.install), "")


class InstallerIntegrationTest(unittest.TestCase):
    """How --install decides whether to fetch one."""

    def setUp(self):
        from sunshine_apps_ui import installer
        self.installer = installer
        self.real_name = os.name
        self.tmp = tempfile.mkdtemp()
        self.where = {"install": self.tmp}
        os.name = "nt"
        self.real_provision = interpreter.provision
        self.provisioned = []
        interpreter.provision = lambda install_dir, log=None: (
            self.provisioned.append(install_dir) or os.path.join(install_dir, "python", "python.exe"))

    def tearDown(self):
        os.name = self.real_name
        interpreter.provision = self.real_provision
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_asked_for_explicitly_it_is_installed(self):
        self.installer._provide_interpreter(self.where, True)
        self.assertEqual(self.provisioned, [self.tmp])

    def test_declined_explicitly_it_is_not(self):
        messages = self.installer._provide_interpreter(self.where, False)
        self.assertEqual(self.provisioned, [])
        self.assertTrue(any("Python is on PATH" in m for m in messages))

    def test_with_no_terminal_it_says_so_rather_than_downloading(self):
        """A silent download onto somebody's machine is not a default."""
        messages = self.installer._provide_interpreter(self.where, None, confirm=None)
        self.assertEqual(self.provisioned, [])
        self.assertTrue(any("--with-interpreter" in m for m in messages))

    def test_asked_and_agreed_it_is_installed(self):
        self.installer._provide_interpreter(
            self.where, None, confirm=lambda detail, question: True)
        self.assertEqual(self.provisioned, [self.tmp])

    def test_the_question_shows_what_would_be_downloaded(self):
        seen = {}
        self.installer._provide_interpreter(
            self.where, None,
            confirm=lambda detail, question: seen.update(detail=detail) or False)
        self.assertIn(interpreter.CPYTHON.url, seen["detail"])
        self.assertIn("sha256", seen["detail"])

    def test_a_failure_does_not_fail_the_install(self):
        def explode(install_dir, log=None):
            raise interpreter.ProvisionError("the checksum did not match")
        interpreter.provision = explode
        messages = self.installer._provide_interpreter(self.where, True)
        self.assertTrue(any("checksum did not match" in m for m in messages))
        self.assertTrue(any("Everything else is in place" in m for m in messages))

    def test_none_of_this_happens_off_windows(self):
        os.name = self.real_name
        if os.name == "nt":
            self.skipTest("this asserts the POSIX no-op")
        self.assertEqual(self.installer._provide_interpreter(self.where, True), [])



class BootstrapScriptTest(unittest.TestCase):
    """The one part that cannot be Python: installing where there is no Python.

    It carries a copy of the interpreter's URL and hash, because it runs before
    anything of ours can be imported. Two copies of one constant is how they
    drift, so this checks they agree.
    """

    def setUp(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(here, "scripts", "install.ps1")
        self.text = open(self.path, encoding="utf-8").read()

    def test_it_exists_and_is_powershell(self):
        self.assertTrue(os.path.isfile(self.path))
        self.assertIn("param(", self.text)

    def test_its_pinned_hash_matches_the_one_the_program_uses(self):
        self.assertIn(interpreter.CPYTHON.sha256, self.text)

    def test_its_pinned_url_matches_too(self):
        self.assertIn(interpreter.CPYTHON.url, self.text)

    def test_it_refuses_a_download_that_does_not_match(self):
        self.assertIn("did not match its published checksum", self.text)
        self.assertIn("Nothing was installed", self.text)

    def test_it_uses_a_python_that_is_already_there(self):
        """Downloading one onto a machine that has three is rude."""
        self.assertIn("Find-Python", self.text)

    def test_it_is_not_fooled_by_the_store_stub(self):
        """`where python` answers with a stub that only opens the Microsoft Store."""
        self.assertIn("Store", self.text)

    def test_it_asks_the_installer_for_an_interpreter_by_default(self):
        self.assertIn("--with-interpreter", self.text)
        self.assertIn("--without-interpreter", self.text)


class PillowIsNotNeededToInstallTest(unittest.TestCase):
    """Installing must not require the thing the install is about to fetch.

    Every module reaches core.images eventually -- the importers import it, the
    engine imports them -- so a top-level `from PIL import Image` made Pillow a
    requirement of *starting*. On a Windows machine with a freshly bootstrapped
    interpreter that is a deadlock: the installer cannot run far enough to
    install the Pillow it needs in order to run. Found on the rig, on a machine
    with no Python at all.
    """

    def test_the_program_imports_without_pillow(self):
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # A child with PIL made unimportable, which is the machine in question.
        code = (
            "import sys\n"
            "class Blocked:\n"
            "    def find_module(self, name, path=None):\n"
            "        if name == 'PIL' or name.startswith('PIL.'):\n"
            "            raise ImportError('no PIL here')\n"
            "        return None\n"
            "sys.meta_path.insert(0, Blocked())\n"
            "import sunshine_apps_ui.__main__\n"
            "import sunshine_apps_ui.installer\n"
            "from sunshine_apps_ui.core import api, run\n"
            "print('imported fine')\n"
        )
        environment = dict(os.environ, PYTHONPATH=os.path.join(here, "src"))
        result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, env=environment)
        self.assertIn("imported fine", result.stdout, result.stderr)

    def test_asking_for_pillow_when_it_is_missing_says_what_to_do(self):
        from sunshine_apps_ui.core import images
        real = images.__dict__.get("_image")
        try:
            import builtins
            real_import = builtins.__import__

            def blocked(name, *args, **kwargs):
                if name == "PIL":
                    raise ImportError("no PIL here")
                return real_import(name, *args, **kwargs)

            builtins.__import__ = blocked
            with self.assertRaises(ImportError) as caught:
                images._image()
            self.assertIn("--with-interpreter", str(caught.exception))
            self.assertIn("pip install pillow", str(caught.exception))
        finally:
            builtins.__import__ = real_import

class ProvisionSafetyTest(unittest.TestCase):
    """What happens to the interpreter that is already there.

    Found on the rig: re-provisioning while a leftover server was still running
    from the old interpreter deleted everything it could (the zip, Lib, the
    ._pth), failed to overwrite the executable still in use, and left something
    that could not start at all -- while reporting that the install had
    succeeded.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.install = os.path.join(self.tmp, "install")
        self.python_dir = os.path.join(self.install, "python")
        os.makedirs(self.python_dir)
        # An interpreter that is already here and works.
        with open(os.path.join(self.python_dir, "python.exe"), "w") as handle:
            handle.write("the one that already works")

        self.real_download = interpreter._download
        self.real_works = interpreter.works

        def fake_download(artifact, into, log=None):
            path = os.path.join(into, os.path.basename(artifact.url))
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("python.exe", "the new one")
            return path

        interpreter._download = fake_download

    def tearDown(self):
        interpreter._download = self.real_download
        interpreter.works = self.real_works

    def test_a_new_one_that_does_not_run_is_not_swapped_in(self):
        interpreter.works = lambda executable: False
        with self.assertRaises(interpreter.ProvisionError) as caught:
            interpreter.provision(self.install)
        self.assertIn("does not run", str(caught.exception))
        # The one that was here is still here, and still itself.
        self.assertEqual(open(os.path.join(self.python_dir, "python.exe")).read(),
                         "the one that already works")

    def test_a_failed_attempt_leaves_no_half_built_directory(self):
        interpreter.works = lambda executable: False
        with self.assertRaises(interpreter.ProvisionError):
            interpreter.provision(self.install)
        self.assertFalse(os.path.exists(self.python_dir + ".new"))

    def test_a_working_new_one_replaces_the_old(self):
        interpreter.works = lambda executable: True
        interpreter.provision(self.install)
        self.assertEqual(open(os.path.join(self.python_dir, "python.exe")).read(),
                         "the new one")

    def test_a_download_that_fails_leaves_the_old_one_alone(self):
        def explode(artifact, into, log=None):
            raise interpreter.ProvisionError("no route to host")
        interpreter._download = explode
        with self.assertRaises(interpreter.ProvisionError):
            interpreter.provision(self.install)
        self.assertEqual(open(os.path.join(self.python_dir, "python.exe")).read(),
                         "the one that already works")


class InstallerLeavesWorkingInterpretersAloneTest(unittest.TestCase):
    """Replacing means deleting, and deleting one that is in use breaks it."""

    def setUp(self):
        from sunshine_apps_ui import installer
        self.installer = installer
        self.real_name = os.name
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "python"))
        open(os.path.join(self.tmp, "python", "python.exe"), "w").close()
        self.where = {"install": self.tmp}
        os.name = "nt"
        self.provisioned = []
        self.real_provision = interpreter.provision
        self.real_works = interpreter.works
        interpreter.provision = lambda install_dir, log=None: (
            self.provisioned.append(install_dir) or "python.exe")

    def tearDown(self):
        os.name = self.real_name
        interpreter.provision = self.real_provision
        interpreter.works = self.real_works

    def test_a_working_one_is_left_alone_even_when_asked_for(self):
        interpreter.works = lambda executable: True
        messages = self.installer._provide_interpreter(self.where, True)
        self.assertEqual(self.provisioned, [])
        self.assertTrue(any("leaving it alone" in m for m in messages))

    def test_a_broken_one_is_replaced_and_said_so(self):
        interpreter.works = lambda executable: False
        messages = self.installer._provide_interpreter(self.where, True)
        self.assertEqual(self.provisioned, [self.tmp])
        self.assertTrue(any("does not run" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
