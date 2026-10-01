# SPDX-License-Identifier: GPL-3.0-or-later
"""Share the log (#71): every rule of what is taken out, against sample logs."""
import io
import unittest
import urllib.error
from unittest import mock

from sunshine_apps_ui import logshare as L

SAMPLE = """\
20:31:02 WARNING Sunshine config: /home/deck/.config/sunshine
20:31:02 WARNING launcher: window started (WebKitGTK 2.54) on living-room-pc
20:31:07 WARNING http://127.0.0.1:47999/?token=abcDEF123_-x
20:31:09 WARNING pad: Sunshine (libvirtualhid) X-Box Series Controller, 17 buttons, 4 axes, X and Y swapped
20:31:09 WARNING host: pad 045e:0b13 v0513 bus 0005: Sunshine (libvirtualhid) X-Box Series Controller, at 7e:a1:02:33:44:55
20:32:14 WARNING scan: steam: 7 found in /mnt/games/SteamLibrary/steamapps
20:32:14 WARNING scan: steam: Satisfactory has no cover in the library cache
20:32:15 WARNING scan: heroic: library not found at /home/deck/.config/heroic
20:33:40 ERROR apply: Sunshine did not answer at https://192.168.1.20:47990/api/apps: connection refused
"""
FACTS = L.Facts(home="/home/deck", user="deck", hostname="living-room-pc.lan",
                games=["Satisfactory", "Portal 2"])


def run(text=SAMPLE, facts=FACTS, remove=()):
    return L.examine(text, facts, remove)


class AlwaysRemoved(unittest.TestCase):
    def test_the_token(self):
        e = run()
        self.assertNotIn("abcDEF123", e.text)
        self.assertIn("?token=[removed]", e.text)
        self.assertEqual(e.found("token").count, 1)

    def test_the_home_folder_is_shown_as_tilde(self):
        e = run()
        self.assertNotIn("/home/deck", e.text)
        self.assertIn("~/.config/sunshine", e.text)
        self.assertEqual(e.found("home").values, ["/home/deck"])

    def test_the_user_name_on_its_own(self):
        e = run("20:00:00 WARNING owner is deck\n")
        self.assertNotIn("deck", e.text)

    def test_a_windows_home_either_way_round(self):
        facts = L.Facts(home="C:\\Users\\Pat", user="Pat")
        e = run("a C:\\Users\\Pat\\AppData\\x b C:/Users/Pat/y\n", facts)
        self.assertNotIn("Pat", e.text)
        self.assertEqual(e.text, "a ~\\AppData\\x b ~/y\n")

    def test_the_machine_name_whole_and_short(self):
        e = run("on living-room-pc and living-room-pc.lan\n")
        self.assertEqual(e.text, "on [machine] and [machine]\n")

    def test_the_moonlight_device(self):
        e = run("client Legion Go S\n", L.Facts(client_name="Legion Go S"))
        self.assertEqual(e.text, "client [device]\n")
        self.assertTrue(e.found("device"))

    def test_a_user_name_where_the_log_says_it_is_one(self):
        e = run("auth user=admin7 ok, username: \"pat\"\n", L.Facts())
        self.assertEqual(e.text, "auth user=[removed] ok, username: [removed]\n")
        self.assertEqual(e.found("sunshine_user").count, 2)

    def test_a_user_name_that_is_a_word_leaves_the_word_alone(self):
        """The Legion test: a Sunshine user named "sunshine" took Sunshine's
        own name out of every line."""
        e = run("host: Sunshine 2026.906, gamepad auto\nconfig: /x/.config/sunshine\n",
                L.Facts(sunshine_user="sunshine"))
        self.assertEqual(e.text, "host: Sunshine 2026.906, gamepad auto\nconfig: /x/.config/sunshine\n")

    def test_the_password_as_itself_but_not_inside_words(self):
        facts = L.Facts(secrets=["sunshine"])
        e = run("sent sunshine to it, pw=sunshine\nSunshine config: /x/.config/sunshine\n", facts)
        self.assertEqual(e.text, "sent [removed] to it, pw=[removed]\n"
                                 "Sunshine config: /x/.config/sunshine\n")

    def test_network_addresses_but_not_loopback(self):
        e = run("a 192.168.1.20 b 127.0.0.1 c fe80::1ff:fe23:4567:890a d ::1 e 0.0.0.0\n")
        self.assertEqual(e.text, "a [address] b 127.0.0.1 c [address] d ::1 e 0.0.0.0\n")
        self.assertEqual(e.found("addresses").count, 2)

    def test_times_are_not_addresses(self):
        e = run("20:31:02 WARNING x\n")
        self.assertEqual(e.text, "20:31:02 WARNING x\n")

    def test_a_controllers_bluetooth_address_is_counted_as_its(self):
        e = run()
        self.assertNotIn("7e:a1:02", e.text)
        f = e.found("addresses")
        self.assertEqual((f.count, f.controller), (2, 1))

    def test_anything_like_a_secret(self):
        e = run("key: 0123456789abcdef0123456789ABCDEF\n"
                "Authorization: Bearer abc.def\nCookie: s=1\n"
                "url?password=hunter2&x=1\nsaw 0123456789abcdef0123456789abcdef\n",
                L.Facts())
        for gone in ("0123456789", "abc.def", "s=1", "hunter2"):
            self.assertNotIn(gone, e.text)
        self.assertIn("&x=1", e.text)

    def test_a_word_ending_in_key_is_not_a_secret(self):
        e = run("monkey: fine\n", L.Facts())
        self.assertEqual(e.text, "monkey: fine\n")


class Asked(unittest.TestCase):
    def test_kept_by_default_but_named(self):
        e = run()
        self.assertIn("Sunshine (libvirtualhid) X-Box Series Controller", e.text)
        self.assertIn("Satisfactory", e.text)
        self.assertIn("/mnt/games/SteamLibrary", e.text)
        self.assertEqual(e.found("controllers").values,
                         ["Sunshine (libvirtualhid) X-Box Series Controller"])
        self.assertEqual(e.found("games").values, ["Satisfactory"])
        self.assertEqual(e.found("folders").values, ["/mnt/games/SteamLibrary"])

    def test_removed_when_switched_on(self):
        e = run(remove=L.OPTIONAL)
        self.assertIn("pad: [controller], 17 buttons", e.text)
        self.assertIn("steam: [game] has no cover", e.text)
        self.assertIn("7 found in [folder]", e.text)

    def test_each_switch_alone(self):
        e = run(remove=["games"])
        self.assertIn("[game]", e.text)
        self.assertNotIn("[controller]", e.text)
        self.assertNotIn("[folder]", e.text)

    def test_folders_in_the_home_system_ones_and_urls_are_not_asked_about(self):
        e = run("~ /home/deck/x /usr/lib/y /proc/bus/input/devices "
                "http://127.0.0.1:47999/api/apps https://[x]/a/b /run/user/1000/bus\n")
        self.assertIsNone(e.found("folders"))

    def test_a_windows_library_folder(self):
        e = run("steam: D:\\SteamLibrary\\steamapps\\common C:\\Program Files\\x\n",
                L.Facts(), remove=["folders"])
        self.assertEqual(e.text, "steam: [folder] C:\\Program Files\\x\n")

    def test_short_game_names_are_not_used(self):
        e = run("the Go button\n", L.Facts(games=["Go"]))
        self.assertIsNone(e.found("games"))


class Preview(unittest.TestCase):
    def test_pieces_mark_what_was_replaced(self):
        e = run("at /home/deck/x on living-room-pc\n")
        self.assertEqual(e.pieces, [("at ", False), ("~", True), ("/x on ", False),
                                    ("[machine]", True), ("\n", False)])

    def test_nothing_found_is_nothing_listed(self):
        e = run("20:00:00 WARNING nothing here\n", L.Facts())
        self.assertFalse([f for f in e.findings.values() if f.count])


class Cut(unittest.TestCase):
    def test_a_long_log_keeps_its_last_900_kb_from_a_line_start(self):
        line = "20:00:00 WARNING " + "x" * 83 + "\n"   # 101 bytes
        text = "".join(line.replace("x", str(i % 10), 1) for i in range(20000))
        e = run(text, L.Facts())
        self.assertTrue(e.cut)
        sent = e.text.encode("utf-8")
        self.assertLessEqual(len(sent), L.MAX_BYTES)
        self.assertTrue(e.text.startswith(L.CUT_NOTE + "\n20:00:00 "))
        self.assertTrue(e.text.endswith(line.replace("x", "9", 1)))

    def test_a_short_log_is_whole(self):
        self.assertFalse(run().cut)


class Send(unittest.TestCase):
    def setUp(self):
        L._last_send = 0.0

    def fake(self, body=b"https://dpaste.com/ABC123\n", headers=None):
        seen = {}

        class Response(io.BytesIO):
            def __init__(self):
                super().__init__(body)
                self.headers = headers or {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout):
            seen["request"] = request
            return Response()
        return opener, seen

    def test_posts_to_the_api_with_a_user_agent_for_seven_days(self):
        opener, seen = self.fake()
        self.assertEqual(L.send("hello", opener=opener), "https://dpaste.com/ABC123")
        r = seen["request"]
        self.assertEqual(r.full_url, "https://dpaste.com/api/v2/")
        self.assertRegex(r.get_header("User-agent"),
                         r"^sunshine-apps-ui/\S+ \(\+https://github.com/4o66/sunshine-apps-ui\)$")
        self.assertIn(b"expiry_days=7", r.data)
        self.assertIn(b"content=hello", r.data)

    def test_one_request_a_second(self):
        opener, _ = self.fake()
        with mock.patch.object(L.time, "sleep") as sleep:
            L.send("a", opener=opener)
            L.send("b", opener=opener)
        self.assertEqual(sleep.call_count, 1)
        self.assertGreater(sleep.call_args[0][0], 0.5)

    def test_refused_and_unreachable_say_so(self):
        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 429, "slow down", {}, None)

        def unreachable(request, timeout):
            raise urllib.error.URLError("no route")
        with mock.patch.object(L.time, "sleep"):
            with self.assertRaisesRegex(L.SendError, "refused it \\(429\\)"):
                L.send("a", opener=refused)
            with self.assertRaisesRegex(L.SendError, "could not be reached"):
                L.send("a", opener=unreachable)

    def test_an_answer_that_is_not_a_link(self):
        opener, _ = self.fake(body=b"<html>oops</html>")
        with self.assertRaises(L.SendError):
            L.send("a", opener=opener)


if __name__ == "__main__":
    unittest.main()
