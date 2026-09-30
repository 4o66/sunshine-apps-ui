"""Taking over the three tiles Sunshine ships.

Left alone they sit beside ours: a second desktop tile, different artwork, two
authors on one grid. We claim them where they are untouched, keep what they do,
and never touch one somebody has edited.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sunshine_apps_ui.core.sources.launchers import factory_takeovers
from sunshine_apps_ui.core.reconcile import MARKER, identity, reconcile, tag


def factory():
    """apps.json as Sunshine ships it."""
    return [
        {"name": "Desktop", "image-path": "desktop.png"},
        {"name": "Low Res Desktop", "image-path": "desktop.png",
         "prep-cmd": [{"do": "xrandr --output HDMI-1 --mode 1920x1080",
                       "undo": "xrandr --output HDMI-1 --mode 3840x2160"}]},
        {"name": "Steam Big Picture", "image-path": "steam.png",
         "detached": ["setsid steam steam://open/bigpicture"],
         "prep-cmd": [{"undo": "setsid steam steam://close/bigpicture"}]},
    ]


def ours_desktop():
    return tag({"name": "#1 Desktop", "image-path": "/opt/art/desktop.png"},
               "launcher", "desktop")


def run(existing, desired):
    takeovers, claims = factory_takeovers(existing)
    merged, plan = reconcile(existing, list(desired) + takeovers,
                             claim_by_name=claims)
    return merged, plan, claims


def named(apps, name):
    return [a for a in apps if a.get("name") == name]


def test_three_claims_from_a_fresh_sunshine():
    _, _, claims = run(factory(), [ours_desktop()])
    assert claims == {
        "Desktop": ("launcher", "desktop"),
        "Low Res Desktop": ("launcher", "desktop-lowres"),
        "Steam Big Picture": ("launcher", "steam-bigpicture"),
    }


def test_the_desktop_duplicate_is_gone():
    merged, plan, _ = run(factory(), [ours_desktop()])
    assert not named(merged, "Desktop")
    assert len(named(merged, "#1 Desktop")) == 1
    assert plan["kept_foreign"] == []


def test_what_the_tiles_do_is_preserved():
    merged, _, _ = run(factory(), [ours_desktop()])
    low = named(merged, "#2 Low Res Desktop")[0]
    assert low["prep-cmd"][0]["do"].startswith("xrandr")
    big = named(merged, "Zz Steam Big Picture")[0]
    assert big["detached"] == ["setsid steam steam://open/bigpicture"]
    assert big["prep-cmd"][0]["undo"].endswith("steam://close/bigpicture")


def test_they_become_ours():
    merged, _, _ = run(factory(), [ours_desktop()])
    for name in ("#1 Desktop", "#2 Low Res Desktop", "Zz Steam Big Picture"):
        entry = named(merged, name)[0]
        assert identity(entry)[0] == "launcher"
        assert "assets" in entry["image-path"] or entry["image-path"].startswith("/opt/art")


def test_an_edited_tile_is_left_alone():
    """Different artwork means somebody has been in there. Not ours to take."""
    existing = factory()
    existing[2]["image-path"] = "/home/me/my-steam.png"
    merged, plan, claims = run(existing, [ours_desktop()])
    assert "Steam Big Picture" not in claims
    kept = named(merged, "Steam Big Picture")[0]
    assert kept["image-path"] == "/home/me/my-steam.png"
    assert MARKER not in kept
    assert {"name": "Steam Big Picture"} in plan["kept_foreign"]


def test_a_second_scan_keeps_them_and_changes_nothing():
    merged, _, _ = run(factory(), [ours_desktop()])
    again, plan, claims = run(merged, [ours_desktop()])
    assert claims == {}
    assert [a.get("name") for a in again] == [a.get("name") for a in merged]
    assert plan["missing"] == [] and plan["pruned"] == []
    assert len(plan["unchanged"]) == 3


def test_a_rename_after_the_takeover_is_respected():
    """The ordinary divergence rule applies once a tile is ours."""
    merged, _, _ = run(factory(), [ours_desktop()])
    for app in merged:
        if app["name"] == "Zz Steam Big Picture":
            app["name"] = "Big Picture"
    again, plan, _ = run(merged, [ours_desktop()])
    assert named(again, "Big Picture")
    assert [d["field"] for d in plan["diverged"][0]["fields"]] == ["name"]


def test_we_never_end_up_with_two_desktops():
    """Installed before this existed: both Sunshine's Desktop and our #1."""
    existing = factory() + [dict(ours_desktop())]
    merged, plan, _ = run(existing, [ours_desktop()])
    # The claim is offered but reconcile declines it: we already hold that id.
    assert len(named(merged, "#1 Desktop")) == 1
    assert {"name": "Desktop"} in plan["kept_foreign"]
    assert MARKER not in named(merged, "Desktop")[0]


def test_nothing_happens_where_there_is_nothing_to_take():
    takeovers, claims = factory_takeovers([{"name": "Cyberpunk 2077"}])
    assert (takeovers, claims) == ([], {})


# --- Through the interface's queue: Rescan stages, Apply writes. #42. ---
#
# The scan above always got this right. The staged path did not: each update
# became an "adopt" that knew only the new entry, and Apply finds an adopt's
# target by marker -- which Sunshine's own tiles do not have. Found on Ubuntu
# 26.04, 2026-09-26: eight apps after Apply, Sunshine's three beside ours.


def staged_and_applied(existing, desired):
    """Rescan then Apply, as the interface does it, on a private queue."""
    import tempfile, shutil
    from unittest import mock
    from sunshine_apps_ui import state
    from sunshine_apps_ui.core.mutate import apply_ops

    home = tempfile.mkdtemp()
    try:
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": home}):
            state.clear_queue()
            _, plan, _ = run(existing, desired)
            state.stage_plan(plan)
            ops = state.queue()
            payload, results = apply_ops({"apps": [dict(a) for a in existing]}, ops)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return payload["apps"], ops, results


def test_the_plan_says_which_tile_a_takeover_replaces():
    _, plan, _ = run(factory(), [ours_desktop()])
    replaced = {u["name"]: u.get("replaces") for u in plan["updated"]}
    assert replaced == {"#1 Desktop": "Desktop",
                        "#2 Low Res Desktop": "Low Res Desktop",
                        "Zz Steam Big Picture": "Steam Big Picture"}


def test_an_update_found_by_marker_replaces_nothing():
    """Only a match by name needs saying; a marker finds its own target."""
    # Ours already, missing a field we now set: an update, found by marker.
    # (A field of ours that differs would be the user's edit, not an update.)
    existing = [tag({"name": "#1 Desktop"}, "launcher", "desktop")]
    _, plan, _ = run(existing, [ours_desktop()])
    assert plan["updated"] and "replaces" not in plan["updated"][0]


def test_rescan_and_apply_leave_one_set_of_tiles():
    apps, _, results = staged_and_applied(factory(), [ours_desktop()])
    names = sorted(a.get("name") for a in apps)
    assert names == ["#1 Desktop", "#2 Low Res Desktop", "Zz Steam Big Picture"], names
    assert all(r.get("ok") for r in results)


def test_and_what_they_do_survives_the_trip():
    apps, _, _ = staged_and_applied(factory(), [ours_desktop()])
    steam = named(apps, "Zz Steam Big Picture")[0]
    assert steam["detached"] == ["setsid steam steam://open/bigpicture"]
    assert identity(steam) == ("launcher", "steam-bigpicture")


def test_a_tile_renamed_since_the_scan_is_not_overwritten():
    """The scan saw Sunshine's Desktop; by Apply the user had made it theirs."""
    import tempfile, shutil
    from unittest import mock
    from sunshine_apps_ui import state
    from sunshine_apps_ui.core.mutate import apply_ops

    home = tempfile.mkdtemp()
    try:
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": home}):
            state.clear_queue()
            _, plan, _ = run(factory(), [ours_desktop()])
            state.stage_plan(plan)
            now = factory()
            now[0]["name"] = "My Desktop"
            payload, _ = apply_ops({"apps": now}, state.queue())
    finally:
        shutil.rmtree(home, ignore_errors=True)
    names = [a.get("name") for a in payload["apps"]]
    assert "My Desktop" in names and "#1 Desktop" in names


def test_a_tile_that_has_gained_a_marker_is_not_taken_by_name():
    from sunshine_apps_ui.core.mutate import apply_ops
    theirs = tag({"name": "Desktop"}, "someone-else", "x")
    op = {"op": "adopt", "entry": ours_desktop(), "replaces": "Desktop"}
    payload, _ = apply_ops({"apps": [theirs]}, [op])
    assert [a.get("name") for a in payload["apps"]] == ["Desktop", "#1 Desktop"]


def test_the_confirmation_says_a_takeover_replaces_sunshines_tile():
    """It printed "adopt #1 Desktop", and nothing said Desktop was going."""
    from sunshine_apps_ui.render import _queued_rows
    html = _queued_rows([
        {"op": "adopt", "name": "#1 Desktop", "replaces": "Desktop", "fields": ["name"]},
        {"op": "adopt", "name": "Zz App Manager"},
        {"op": "adopt", "name": "Portal 2", "fields": ["image-path"]},
    ], [])
    assert "Replace Desktop with #1 Desktop" in html
    assert "Add Zz App Manager" in html
    assert "Update Portal 2" in html
    assert "adopt" not in html


def load_tests(loader, tests, pattern):
    """These are plain functions, which unittest -- what the suite runs -- does
    not collect. Until this, none of them ran at all."""
    import unittest
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite
