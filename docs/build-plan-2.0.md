# sunshine-apps-ui 2.0: the build plan

## Context

The 2.0 interface is designed and approved (#56): every page, the full flow of 41 screens, and a WebView2 check on Windows. The design canvas is https://claude.ai/artifact/GAQVBgymuL8XEzryyXBoUP. The prototypes and `app.css` are in `design/2.0` on branch `redesign-2.0`. This plan turns the approved design into the real app.

**The rule for the whole build:** the build matches the boards. Where it can't, work stops and I bring you the difference. Nothing counts as too minor to raise.

**Decided for this plan (2026-09-27):**
- **Install update comes after 2.0.** In 2.0, Updates keeps Check for updates and What changed. The drawn Install button becomes its own issue.
- **Share the log is in 2.0, through dpaste.com.** It uses the documented API (https://dpaste.com/api/), sends a User-Agent that names the app, and follows the terms (https://dpaste.com/terms/).
- **Before a log is posted, you are told what's in it** (next section).

## What a log holds, and what the share screen does about it

From the code: `server.log` is in the state folder, overwritten at each launch, at WARNING level unless `--verbose`. The scan's lines end up in it too.

| In the log | Where it comes from | Handling |
|---|---|---|
| The session token (the full URL with `?token=`) | `__main__.py:240` | **Always removed.** It grants access to the manager. Not something to ask about. |
| Home folder and username | config dir, backup paths, Heroic paths, config candidates | **Replaced with `~`, and you're told.** The screen names the folder: "Your home folder, /home/…, appears 14 times. It is shown as ~." |
| Machine name (hostname) | if it appears in Sunshine or scan lines | Replaced, and named on the screen the same way |
| Local IP and MAC addresses | Sunshine URLs, errors | Replaced; the screen says how many were found |
| Moonlight device name (`SUNSHINE_CLIENT_NAME`) | only if logged | Replaced, and named |
| Sunshine username | only if ever logged (it shouldn't be) | Replaced; its presence would be a bug to fix |
| Anything that looks like a secret: a 32-hex key, `Authorization`/`Cookie` headers, `password=`, `key=` | defensive; none expected | **Always removed**, never offered |
| Game names in your library | scan lines | **Asked**: "The log names 7 games from your library." with a Remove game names switch, **off** by default, since the names are often what a bug is about |
| Paths outside the home folder (e.g. `/mnt/games/…`) | Heroic and Steam library folders | **Asked**: listed, with Remove these paths, off by default |

**The share screen (the drawn board is redrawn first, see phase 7):**
- **"What this log contains":** one row per kind found, showing the real value it replaces (such as the home folder) and whether it's removed or kept, with a switch where it's your choice.
- **The full log as it will be sent,** with every replacement highlighted.
- **dpaste.com, public link, 7 days, can't be recalled.** Back is the default button; Send is the only way anything leaves.

**Sanitizer rules:**
- Every rule has tests against sample logs.
- The rules err toward removing too much.
- The log is cut to its last 900 KB to stay under dpaste's 1 MB limit.
- The limit of one request per second is kept.
- The User-Agent is `sunshine-apps-ui/<version> (+https://github.com/4o66/sunshine-apps-ui)`.

## How every phase runs

1. **Worktree:** from `origin/redesign-2.0`, into `/tmp/<phase>`. `dev` is merged forward at the start of each phase.
2. **Build the phase.**
3. **Tests:** the full suite. Tests that pin old markup are updated in the same commit; the structural ones in `test_navigation.py` stay as they are.
4. **Render the real app, not the prototype.** A dev script, `scripts/design-states`, starts the real server on fake engine state, the way `tests/test_server.py` does (`FakeEngine` plus the same `mock.patch.object` names). It serves each board's state at a fixed address. `dbatch2` captures it in WebKitGTK at four sizes and both themes on bsm-bazzite, and `wbatch` captures it in WebView2 on bsm-win11.
5. **Design-vs-build page on the canvas:** each approved board shown beside its build frame, plus a pixel-difference score.
6. **Any difference stops the phase.** It gets fixed, or it goes to you with both pictures. The phase is done only when every pair matches, or you've ruled on the difference.
7. **Commit and push:** one commit per phase, explicit paths, no personal names or home paths in anything staged, pushed to `redesign-2.0`, then the issues are updated.
8. **Moonlight check with you:** on the Legion Go S, after phases 2, 4 and 8.

## Phases

**0. Foundations.**
- **Shell:** one page-shell helper in `render.py` replaces the 18 hand-written shells. It takes `title`, `main` and `bar` and writes the doctype, `_html()`, the title bar, the scrolling main and the action bar, with the gear and, on the grid, the bug.
- **Stylesheet:** `app.css` becomes the single stylesheet. It is served inline, as today, and every `_*_CSS` block goes.
- **Couch or desk:** the `couch` or `desk` class comes from `via_sunshine`.
- **Per-device text size:** `SUNSHINE_CLIENT_NAME` is read in `serve()`. It is already in the server's environment through `launcher.server_environment()`. The size is saved as `set_pref("text_size", {client: size})` in `state.py`.
- **Controller script:** `pad.js` is rewritten as the approved mapping:
  - A chooses, B goes back, X is the second action, Y the main one.
  - Menu opens Settings, and acts on a tap, never a hold.
  - LB and RB turn pages; the right stick scrolls.
  - It sets `.pad` on `<html>` while a controller is in use, so the glyphs, rings and Keyboard button show.
  - It keeps today's spatial movement, row lock, repeat and focus checks. `with_pad` stays.
- **Tools:** the `scripts/design-states` harness, and the canvas's design-vs-build board type.
- **Check:** the foundations and states boards match.

**1. Grid:**
- All four grid boards: notices, flags with status-colored name strips, the action bar.
- The un-hide grid states.

**2. Edit:**
- Edit, new, locked, and custom timeout, including Custom's stepper.
- The Keyboard button in the bar.
- Hide explanation, the hidden app, and un-hide → edit → grid, with stacked flags.

**3. On-screen keyboard:**
- The QWERTY keyboard with Caps, Shift and symbols.
- The hex keypad for the SteamGridDB key.
- Mouse and keyboard users type straight into the field.

**4. Artwork:**
- The picker, with In use under the picture.
- The SteamGridDB page instead of the sheet: 30 per page, LB and RB, Pulling artwork. It retires `sheet.js` and `_sgdb_sheet`.
- The file browser's letter jumps.
- The no-key, refused-key and unreachable states. This includes **#78**: telling 401/403 apart from no results and from unreachable, in `core/artwork_sources.py`, and recording the key's last known state.

**5. Settings:**
- Two panes, the language choices, Text size, and default tiles listing what would come back (from `restore_missing`, with no scan).
- Updates with Which builds.
- The Install button is left out, per the decision above; its board gets a note.

**6. Flow screens:** confirm, applied, scanning, restore a copy, connect (with show password), closing, errors, and asking for elevated access.

**7. Report and Share the log:**
- **Redraw first:** the share board gets the "What this log contains" section and needs your approval before it's built.
- **Then build:** the sanitizer as its own module with tests, the preview, dpaste.com upload through the API, and the QR code.

**8. Windows:** **#79**, `core.Settings.IsStatusBarEnabled = false` in `AppWindow.cs`'s `Initialized()`. Also on `dev` for 1.x. Then a WebView2 design-vs-build pass over every page.

**9. Finish:**
- README screenshots in `docs/images/`, and the README's controller note (2.0 has full support).
- `docs/design.md`'s stale lines.
- Close #32, #56, #57–#79.
- Release 2.0 by `docs/releasing.md`.

## Verification

- **Each phase:** the suite passes, every design-vs-build pair matches or has your ruling, and the WebView2 frames are checked in phases 4 and 8.
- **Controller runs:** the virtual pad on bsm-bazzite (`vpadd.py`), a scripted focus walk per screen, and the real Legion over Moonlight after phases 2, 4 and 8.
- **Share the log:** the sanitizer is tested against captured real logs (home, hostname, IPs, token), and one real upload goes to dpaste.com with your approval before release.
- **Before release:** a full re-render of every board beside the build.
