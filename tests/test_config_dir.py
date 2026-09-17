# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding Sunshine's config directory on each platform.

The Linux rules are already covered by the liveness tests; what is new here is
Windows, where the answer is not under $HOME at all. Sunshine's appdata() there
is the directory holding Sunshine.exe, so apps.json lives under Program Files
and finding it means finding the install.

winreg exists only on Windows, so the registry lookups are exercised by standing
in for it. That is worth saying plainly: these tests prove we read an ImagePath
correctly and prefer the right candidate, not that the keys exist on any
particular machine. The rig in issue #15 is where the latter is checked.
"""

import ntpath
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core import api  # noqa: E402


class FakeWinreg:
    """Just enough of winreg to answer the two lookups, from a dict."""

    HKEY_LOCAL_MACHINE = 1
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x0100
    KEY_WOW64_32KEY = 0x0200

    def __init__(self, services=None, uninstall=None):
        self.services = services or {}      # name -> ImagePath
        self.uninstall = uninstall or {}    # name -> InstallLocation

    class _Key:
        def __init__(self, values, children=()):
            self.values = values
            self.children = list(children)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=0):  # noqa: N802 - winreg's name
        if isinstance(root, self._Key):
            for name, location in self.uninstall.items():
                if name == path:
                    return self._Key({"InstallLocation": location})
            raise OSError("no such key")
        tail = path.rsplit("\\", 1)[-1]
        if path.startswith("SYSTEM"):
            if tail in self.services:
                return self._Key({"ImagePath": self.services[tail]})
            raise OSError("no such service")
        if path.endswith("Uninstall"):
            return self._Key({}, children=list(self.uninstall))
        raise OSError("no such key")

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in key.values:
            raise OSError("no such value")
        return key.values[name], 1

    def QueryInfoKey(self, key):  # noqa: N802
        return (len(key.children), 0, 0)

    def EnumKey(self, key, index):  # noqa: N802
        return key.children[index]


class WindowsDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.real_name = os.name
        self.real_environ = dict(os.environ)

    def tearDown(self):
        os.name = self.real_name
        os.environ.clear()
        os.environ.update(self.real_environ)
        sys.modules.pop("winreg", None)

    def install(self, **kwargs):
        sys.modules["winreg"] = types.SimpleNamespace(
            **{name: getattr(FakeWinreg(**kwargs), name)
               for name in ("OpenKey", "QueryValueEx", "QueryInfoKey", "EnumKey")},
            HKEY_LOCAL_MACHINE=FakeWinreg.HKEY_LOCAL_MACHINE,
            KEY_READ=FakeWinreg.KEY_READ,
            KEY_WOW64_64KEY=FakeWinreg.KEY_WOW64_64KEY,
            KEY_WOW64_32KEY=FakeWinreg.KEY_WOW64_32KEY)

    def test_the_service_image_path_names_the_install(self):
        self.install(services={
            "SunshineService": r'"C:\Program Files\Sunshine\sunshinesvc.exe"'})
        dirs = api._windows_install_dirs()
        self.assertIn(ntpath.normpath(r"C:\Program Files\Sunshine"), dirs)

    def test_an_unquoted_image_path_with_arguments_is_still_a_path(self):
        """ImagePath is a command line, not a path. It has bitten every tool that assumed otherwise."""
        self.install(services={
            "SunshineService": r"C:\Program Files\Sunshine\sunshinesvc.exe --service"})
        dirs = api._windows_install_dirs()
        self.assertIn(ntpath.normpath(r"C:\Program Files\Sunshine"), dirs)
        self.assertFalse(any("--service" in d for d in dirs))

    def test_add_remove_programs_is_asked_when_there_is_no_service(self):
        """The portable zip registers no service, and is a supported way to run it."""
        self.install(uninstall={"Sunshine": r"C:\Tools\Sunshine"})
        dirs = api._windows_install_dirs()
        self.assertIn(ntpath.normpath(r"C:\Tools\Sunshine"), dirs)

    def test_the_default_location_is_the_last_resort(self):
        self.install()
        os.environ["ProgramFiles"] = r"C:\Program Files"
        os.environ.pop("ProgramW6432", None)
        os.environ.pop("ProgramFiles(x86)", None)
        dirs = api._windows_install_dirs()
        self.assertEqual(dirs[-1], ntpath.normpath(r"C:\Program Files\Sunshine"))

    def test_the_service_is_preferred_over_the_default(self):
        """Where Sunshine is actually installed beats where installers usually put it."""
        self.install(services={
            "SunshineService": r'"D:\Games\Sunshine\sunshinesvc.exe"'})
        os.environ["ProgramFiles"] = r"C:\Program Files"
        dirs = api._windows_install_dirs()
        self.assertEqual(dirs[0], ntpath.normpath(r"D:\Games\Sunshine"))

    def test_the_same_install_is_not_listed_twice(self):
        self.install(services={"SunshineService": r'"C:\Program Files\Sunshine\sunshinesvc.exe"'},
                     uninstall={"Sunshine": r"C:\Program Files\Sunshine"})
        os.environ["ProgramFiles"] = r"C:\Program Files"
        dirs = api._windows_install_dirs()
        self.assertEqual(len(dirs), len(set(dirs)))

    def test_candidates_look_beside_the_executable(self):
        """Not AppData. config/ next to Sunshine.exe is what appdata() returns."""
        self.install(services={"SunshineService": r'"C:\Program Files\Sunshine\sunshinesvc.exe"'})
        os.name = "nt"
        try:
            candidates = api._candidates(r"C:\Users\sean")
        finally:
            os.name = self.real_name
        self.assertIn(ntpath.normpath(r"C:\Program Files\Sunshine\config"), candidates)
        self.assertFalse(any("AppData" in c for c in candidates))
        self.assertFalse(any(".config" in c for c in candidates))

    def test_nothing_registered_anywhere_still_returns_the_default(self):
        self.install()
        os.environ["ProgramFiles"] = r"C:\Program Files"
        os.environ.pop("ProgramW6432", None)
        os.environ.pop("ProgramFiles(x86)", None)
        self.assertEqual(api._windows_install_dirs(),
                         [ntpath.normpath(r"C:\Program Files\Sunshine")])


@unittest.skipIf(os.name == "nt", "the POSIX candidate list; Windows has its own")
class PosixCandidatesTest(unittest.TestCase):
    """The existing behaviour, unchanged by the Windows work."""

    def test_flatpak_paths_come_before_the_native_one(self):
        found = api._candidates("/home/sean")
        self.assertTrue(found[0].endswith("dev.lizardbyte.app.Sunshine/config/sunshine"))
        self.assertIn("/home/sean/.config/sunshine", found)

    @unittest.skipUnless(sys.platform == "darwin", "macOS paths")
    def test_macos_adds_the_app_bundle_and_application_support(self):
        found = api._candidates("/Users/sean")
        self.assertIn("/Users/sean/.config/sunshine", found)
        self.assertTrue(any("Sunshine.app" in path for path in found))


if __name__ == "__main__":
    unittest.main()


class ServiceBinaryLocationTest(unittest.TestCase):
    """sunshinesvc.exe is in tools\\, not beside sunshine.exe.

    Measured on the rig: the real installer registers
    "C:\\Program Files\\Sunshine\\tools\\sunshinesvc.exe". Taking its directory
    gives ...\\Sunshine\\tools, so the config directory would be looked for at
    ...\\Sunshine\\tools\\config, which does not exist. The liveness ranking
    happened to recover from it, which is exactly why it needed a test: it was
    wrong and still worked.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.install = os.path.join(self.tmp, "Sunshine")
        self.tools = os.path.join(self.install, "tools")
        os.makedirs(self.tools)
        open(os.path.join(self.install, "sunshine.exe"), "w").close()
        self.real_environ = dict(os.environ)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.clear()
        os.environ.update(self.real_environ)
        sys.modules.pop("winreg", None)

    def test_the_install_is_the_directory_holding_sunshine_exe(self):
        service = os.path.join(self.tools, "sunshinesvc.exe")
        sys.modules["winreg"] = types.SimpleNamespace(
            **{name: getattr(FakeWinreg(services={"SunshineService": f'"{service}"'}), name)
               for name in ("OpenKey", "QueryValueEx", "QueryInfoKey", "EnumKey")},
            HKEY_LOCAL_MACHINE=FakeWinreg.HKEY_LOCAL_MACHINE, KEY_READ=FakeWinreg.KEY_READ,
            KEY_WOW64_64KEY=FakeWinreg.KEY_WOW64_64KEY, KEY_WOW64_32KEY=FakeWinreg.KEY_WOW64_32KEY)
        for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            os.environ.pop(name, None)
        self.assertEqual(api._windows_install_dirs(), [ntpath.normpath(self.install)])

    def test_a_service_beside_sunshine_exe_is_left_alone(self):
        """Do not climb when there is nothing to climb for."""
        service = os.path.join(self.install, "sunshinesvc.exe")
        sys.modules["winreg"] = types.SimpleNamespace(
            **{name: getattr(FakeWinreg(services={"SunshineService": f'"{service}"'}), name)
               for name in ("OpenKey", "QueryValueEx", "QueryInfoKey", "EnumKey")},
            HKEY_LOCAL_MACHINE=FakeWinreg.HKEY_LOCAL_MACHINE, KEY_READ=FakeWinreg.KEY_READ,
            KEY_WOW64_64KEY=FakeWinreg.KEY_WOW64_64KEY, KEY_WOW64_32KEY=FakeWinreg.KEY_WOW64_32KEY)
        for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            os.environ.pop(name, None)
        self.assertEqual(api._windows_install_dirs(), [ntpath.normpath(self.install)])
