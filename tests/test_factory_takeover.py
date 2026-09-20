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
