# SPDX-License-Identifier: GPL-3.0-or-later
"""The host facts and controller summary written to the log for bug reports."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from sunshine_apps_ui import diagnostics as D
from sunshine_apps_ui import logshare
from sunshine_apps_ui.server import pad_line

# The Legion Go S's pad over Moonlight, as the Bazzite box listed it, beside a
# keyboard that must be left out. The Bluetooth address is made up.
DEVICES = """\
I: Bus=0005 Vendor=045e Product=0b13 Version=0513
N: Name="Sunshine (libvirtualhid) X-Box Series Controller"
P: Phys=
S: Sysfs=/devices/virtual/misc/uhid/0005:045E:0B13.0007/input/input42
U: Uniq=7e:a1:02:33:44:55
H: Handlers=event12 js0
B: EV=1b

I: Bus=0003 Vendor=046d Product=c52b Version=0111
N: Name="Logitech USB Receiver"
U: Uniq=
H: Handlers=sysrq kbd event3 leds
"""


class Pads(unittest.TestCase):
    def test_joysticks_only_with_ids_name_and_address(self):
        self.assertEqual(D.pads(DEVICES), [
            "host: pad 045e:0b13 v0513 bus 0005: Sunshine (libvirtualhid) X-Box Series Controller, "
            "at 7e:a1:02:33:44:55"])

    def test_a_name_cannot_break_the_line(self):
        text = DEVICES.replace("Sunshine (libvirtualhid) X-Box Series Controller", "Evil\\npad, one")
        self.assertIn(": Evil\\npad one, at", D.pads(text)[0])

    def test_the_share_screen_names_it_and_removes_its_address(self):
        e = logshare.examine("\n".join(D.pads(DEVICES)) + "\n", logshare.Facts())
        self.assertNotIn("7e:a1", e.text)
        self.assertEqual(e.found("addresses").controller, 1)
        self.assertEqual(e.found("controllers").values,
                         ["Sunshine (libvirtualhid) X-Box Series Controller"])


class Host(unittest.TestCase):
    def setUp(self):
        self.conf = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.conf, True)
        self.devices = os.path.join(self.conf, "devices")
        with open(self.devices, "w") as f:
            f.write(DEVICES)

    def write(self, name, text):
        with open(os.path.join(self.conf, name), "w") as f:
            f.write(text)

    def test_window_pads_and_sunshine(self):
        self.write("sunshine.conf", "# gamepad = ds4\ngamepad = x360\n")
        self.write("sunshine.log", "[2026-09-29] Info: Sunshine version: v2026.906.1\n")
        with mock.patch.object(D.sys, "platform", "linux"):
            lines = D.host_lines(self.conf, {D.WINDOW_ENV: "our own window"}, self.devices)
        self.assertEqual(lines[0], "host: window our own window")
        self.assertTrue(lines[1].startswith("host: pad 045e:0b13"))
        self.assertEqual(lines[-1], "host: Sunshine v2026.906.1, gamepad x360")

    def test_what_cannot_be_read_is_said_plainly(self):
        with mock.patch.object(D.sys, "platform", "linux"):
            lines = D.host_lines(self.conf, {}, os.path.join(self.conf, "none"))
        self.assertEqual(lines, ["host: window not known", "host: pads not readable",
                                 "host: Sunshine version not known, gamepad unknown"])

    def test_no_pads_and_no_gamepad_line(self):
        self.write("sunshine.conf", "port = 47989\n")
        with open(self.devices, "w") as f:
            f.write(DEVICES.split("\n\n")[1])
        with mock.patch.object(D.sys, "platform", "linux"):
            lines = D.host_lines(self.conf, {}, self.devices)
        self.assertIn("host: no pads", lines)
        self.assertTrue(lines[-1].endswith("gamepad auto"))

    def test_not_linux_has_no_pad_lines(self):
        with mock.patch.object(D.sys, "platform", "win32"):
            lines = D.host_lines(self.conf, {}, self.devices)
        self.assertFalse([l for l in lines if "pad" in l.split(",")[0]])


class Engine(unittest.TestCase):
    def test_each_engine(self):
        self.assertEqual(D.engine_line("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 "
                                       "(KHTML, like Gecko) Version/18.0 Safari/605.1.15 "
                                       "sunshine-apps-ui-window/2.50.1"),
                         "host: engine WebKitGTK 2.50.1")
        self.assertEqual(D.engine_line("Mozilla/5.0 (Windows NT 10.0) Chrome/141.0.0.0 "
                                       "Safari/537.36 Edg/141.0.3537.71"),
                         "host: engine WebView2 or Edge 141.0.3537.71")
        self.assertEqual(D.engine_line("Mozilla/5.0 Firefox/143.0"), "host: engine Firefox 143.0")
        self.assertEqual(D.engine_line(""), "host: engine not known")


class PadLine(unittest.TestCase):
    def test_the_legion_pad(self):
        self.assertEqual(pad_line({
            "name": ["Sunshine (libvirtualhid) X-Box Series Controller"], "buttons": ["17"],
            "axes": ["4"], "mapping": ["standard"], "resting": ["2=-1.00"],
            "rules": ["X and Y swapped; triggers read from axis 2 and button 6; right stick off"]}),
            "pad: Sunshine (libvirtualhid) X-Box Series Controller, 17 buttons, 4 axes, "
            "mapping standard, resting 2=-1.00, X and Y swapped; triggers read from axis 2 "
            "and button 6; right stick off")

    def test_what_a_device_sends_cannot_break_the_log(self):
        line = pad_line({"name": ["x\n20:00:00 ERROR fake, " + "y" * 300],
                         "buttons": ["lots"], "resting": ["<b>"]})
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("pad: x 20:00:00 ERROR fake " ))
        self.assertIn("? buttons", line)
        self.assertNotIn("<b>", line)
        self.assertLess(len(line), 300)

    def test_no_name_no_line(self):
        self.assertEqual(pad_line({}), "")


class RunningOn(unittest.TestCase):
    def setUp(self):
        fd, self.release = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.remove, self.release)
        with open(self.release, "w") as f:
            f.write('NAME="Bazzite"\nVERSION="44.20260925.0 (Kinoite)"\nVERSION_ID=44\n')

    def run_on(self, system, environ, **kw):
        from sunshine_apps_ui import server
        with mock.patch("platform.system", return_value=system), \
                mock.patch("platform.release", return_value=kw.get("release", "")), \
                mock.patch("platform.version", return_value=kw.get("version", "")):
            return server._describe_platform(environ, self.release)

    def test_as_the_board_draws_it(self):
        self.assertEqual(self.run_on("Linux", {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}),
                         "Bazzite 44 · KDE Plasma · Wayland")

    def test_the_display_server_from_its_socket(self):
        self.assertEqual(self.run_on("Linux", {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "DISPLAY": ":0"}),
                         "Bazzite 44 · GNOME · X11")
        self.assertEqual(self.run_on("Linux", {}), "Bazzite 44")

    def test_windows_11_says_so(self):
        self.assertEqual(self.run_on("Windows", {}, release="10", version="10.0.26100"),
                         "Windows 11 (build 26100)")
        self.assertEqual(self.run_on("Windows", {}, release="10", version="10.0.19045"),
                         "Windows 10 (build 19045)")


if __name__ == "__main__":
    unittest.main()
