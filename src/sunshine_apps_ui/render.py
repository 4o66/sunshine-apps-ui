# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering the plan document as a page.

Server-rendered on purpose: no fetch, no token in JavaScript, and every control
is a real link, which is what makes it navigable by keyboard and by a gamepad
mapped to arrows and Enter.
"""

import html
from urllib.parse import quote
from typing import Any, Dict, List, Optional

from . import __version__
from .core.artwork_sources import SGDB_PAGE
from . import frame
from .version import display as version_display

# What this is called, in one place. It is not an importer any more -- importing
# is one of the things it does -- and the tile it is launched from says the same.
PRODUCT = "App Manager"


def _version_chip() -> str:
    """Which build this is, in the bar, where a screenshot will catch it."""
    return f'<span class="ver">{_e(version_display())}</span>'


def theme() -> str:
    """light, dark, or system -- what the person chose, system unless asked.

    Read here rather than passed through fifteen page functions: it is one
    small file, read once per page, and a page that renders in the wrong
    colors because a caller forgot an argument is a worse trade.
    """
    try:
        from . import state

        chosen = str(state.prefs().get("theme", "system")).lower()
    except Exception:              # noqa: BLE001 - colors, never a failure
        return "system"
    return chosen if chosen in ("light", "dark", "system") else "system"


def _html(theme_name: Optional[str] = None) -> str:
    """The opening <html>, carrying the choice for the CSS to act on."""
    chosen = theme_name if theme_name is not None else theme()
    if chosen in ("light", "dark"):
        return f'<html lang="en" data-theme="{chosen}">'
    return '<html lang="en">'


def _title(part: str = "") -> str:
    """A window title that says what program this is, then which page.

    It runs as its own window, so this is what the title bar and the task
    switcher show. The program comes first because that is what someone is
    looking for there.
    """
    name = f"{PRODUCT} {version_display()}"
    return f"{name} \u2014 {part}" if part else name


# What each bucket means to someone looking at their own app list, in the order
# a person cares about: things that need a decision first.
BUCKETS = [
    ("diverged", "Your edits kept", "These are managed entries you changed by hand. "
                                    "The importer left them alone."),
    ("removed_by_user", "You deleted these", "They will not be recreated."),
    ("suppressed", "Skipped", "Found in your library, but you removed them before."),
    ("added", "Would be added", "Discovered and not in apps.json yet."),
    ("updated", "Would be updated", "Fields the importer owns have changed."),
    ("pruned", "Would be removed", "No longer in a library that scanned cleanly."),
    ("missing", "No longer found", "Imported before, not discovered now. Left in place."),
    ("unchanged", "Unchanged", "Nothing to do."),
    # Say only what is actually known: the importer did not create these, so it
    # does not change them. Claiming they are Sunshine's defaults or the user's
    # own is a guess -- an entry may equally have been added by another tool or
    # by someone at the keyboard.
    ("kept_foreign", "Left alone", "Entries the importer does not manage. "
                                   "It never changes them."),
]

STATUS_NOTE = {
    "ok": "scanned",
    "not_found": "not installed here",
    "disabled": "turned off",
    "error": "failed",
}

_CSS = """
/* Design tokens lifted from Sunshine's own sunshine.css so this reads as part
   of the same tool: Bootstrap 5 palette, amber navbar, matching radii. */
/* color-scheme is what the engine draws its own controls by. Without it
   WebKitGTK paints a <select> from the GTK theme: on Ubuntu with the app set
   to Dark, a light box under this page's light text, unreadable. #44. */
:root{
color-scheme:light;
--primary:#0d6efd;--primary-hover:#0b5ed7;--accent:#fd7e14;
--success:#198754;--danger:#dc3545;--warning:#ffc107;--info:#0dcaf0;
--bg-base:#fff;--bg-subtle:#f8f9fa;--bg-muted:#e9ecef;--surface:#fff;
--border:#dee2e6;--border-strong:#adb5bd;
--text:#212529;--text-muted:#6c757d;--text-subtle:#adb5bd;
--navbar-bg:linear-gradient(135deg,#ffc400 0%,#ff9d00 100%);
--navbar-text:#594400;--navbar-text-muted:#7f6100;
--radius-sm:.375rem;--radius-md:.5rem;--radius-lg:.75rem;
--shadow-sm:0 1px 2px 0 rgba(0,0,0,.05);
--shadow-md:0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -1px rgba(0,0,0,.06);
--mono:'SF Mono','Monaco','Inconsolata','Fira Code','Courier New',monospace;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
color-scheme:dark;
--primary-hover:#3d8bfd;--accent-hover:#fd9843;
--bg-base:#212529;--bg-subtle:#2c3034;--bg-muted:#383d41;--surface:#2c3034;
--border:#495057;--border-strong:#6c757d;
--text:#f8f9fa;--text-muted:#adb5bd;--text-subtle:#6c757d;
--shadow-sm:0 1px 2px 0 rgba(0,0,0,.3);
--shadow-md:0 4px 6px -1px rgba(0,0,0,.4),0 2px 4px -1px rgba(0,0,0,.3);
}}
:root[data-theme="dark"]{
color-scheme:dark;
--primary-hover:#3d8bfd;--accent-hover:#fd9843;
--bg-base:#212529;--bg-subtle:#2c3034;--bg-muted:#383d41;--surface:#2c3034;
--border:#495057;--border-strong:#6c757d;
--text:#f8f9fa;--text-muted:#adb5bd;--text-subtle:#6c757d;
--shadow-sm:0 1px 2px 0 rgba(0,0,0,.3);
--shadow-md:0 4px 6px -1px rgba(0,0,0,.4),0 2px 4px -1px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg-base);color:var(--text);
font:1rem/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}

.navbar{background:var(--navbar-bg);box-shadow:var(--shadow-md);padding:.6rem 1rem;
display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap}
.navbar .brand{color:var(--navbar-text);font-weight:700;font-size:1.3rem;letter-spacing:-.01em}
.navbar .sep{color:var(--navbar-text-muted)}
.navbar .where{color:var(--navbar-text-muted);font-weight:500}
.navbar .ver{margin-left:auto;color:var(--navbar-text-muted);font-size:.78rem;
font-family:var(--mono);letter-spacing:.01em}
.navbar .ro{margin-left:.6rem;color:var(--navbar-text-muted);font-size:.82rem;
border:1px solid var(--navbar-text-muted);border-radius:999px;padding:2px 10px}
/* The same slate the tiles are painted on, so it reads as part of the set and
   not as a scratch on the amber bar. It was a thin outlined pill before and
   The maintainer could not find it. */
.navbar .gear{margin-left:.9rem;color:#f1f3f5;text-decoration:none;
font-size:.85rem;font-weight:600;letter-spacing:.01em;
background:linear-gradient(135deg,#3a4149 0%,#23282d 100%);
border:1px solid rgba(0,0,0,.35);border-radius:999px;padding:5px 15px;
box-shadow:0 1px 3px rgba(0,0,0,.3);white-space:nowrap}
.navbar .gear:hover{background:linear-gradient(135deg,#474f59 0%,#2c3238 100%)}

.wrap{max-width:1100px;margin:0 auto;padding:1.5rem 1rem 4rem}
h1{font-size:1.35rem;margin:0 0 .25rem}
.sub{color:var(--text-muted);margin:0 0 1.25rem;font-size:.95rem}
.sub code{font-family:var(--mono);font-size:.85em}

.bar{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.25rem}
.chip{background:var(--bg-subtle);border:1px solid var(--border);border-radius:999px;
padding:.4rem .85rem;font-size:.875rem;display:flex;gap:.5rem;align-items:center}
.dot{width:.55rem;height:.55rem;border-radius:50%;flex:0 0 auto}
.dot.ok{background:var(--success)}
.dot.not_found,.dot.disabled{background:var(--text-subtle)}
.dot.error{background:var(--danger)}

section{background:var(--surface);border:1px solid var(--border);
border-radius:var(--radius-lg);box-shadow:var(--shadow-sm);padding:1.25rem 1.4rem;margin:0 0 1rem}
section h2{font-size:1.05rem;margin:0;display:flex;align-items:center;gap:.6rem}
section h2 .n{background:var(--bg-muted);color:var(--text);border-radius:999px;
padding:.1rem .6rem;font-size:.8rem;font-weight:600}
section p.why{color:var(--text-muted);margin:.35rem 0 .9rem;font-size:.9rem}

ul{list-style:none;margin:0;padding:0;display:grid;gap:.4rem}
li{background:var(--bg-subtle);border:1px solid var(--border);border-radius:var(--radius-md);
padding:.6rem .8rem;display:flex;flex-wrap:wrap;gap:.2rem .75rem;align-items:baseline}
li .name{font-weight:600}
li .sel{color:var(--text-muted);font-size:.82rem;font-family:var(--mono)}
li .fields{color:var(--text-muted);font-size:.85rem}
.diverged{border-left:3px solid var(--warning)}
.diverged .d{width:100%;font-size:.85rem;font-family:var(--mono);color:var(--text-muted);margin-top:.2rem}
.diverged .d b{color:var(--text);font-weight:600}

.btn{display:inline-block;background:var(--primary);color:#fff;text-decoration:none;
border:1px solid var(--primary);border-radius:var(--radius-md);padding:.65rem 1.1rem;
font-family:inherit;font-size:.95rem;line-height:1.5;font-weight:500;cursor:pointer;
transition:background 150ms ease}
.btn:hover{background:var(--primary-hover);border-color:var(--primary-hover)}
.btn.sec{background:transparent;color:var(--primary)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.actions{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin:0 0 1.25rem}

details{margin-top:1.5rem}
summary{cursor:pointer;color:var(--text-muted)}
pre{background:var(--bg-subtle);border:1px solid var(--border);border-radius:var(--radius-md);
padding:.8rem;overflow:auto;font-family:var(--mono);font-size:.8rem;line-height:1.5;max-height:50vh}
.err{border-left:3px solid var(--danger)}
.warn{border-left:3px solid var(--warning)}
.ok{border-left:3px solid var(--success)}
.warn p{margin:0;font-size:.95rem}
h3.ch{font-size:.95rem;margin:.2rem 0 .5rem;display:flex;align-items:center;gap:.5rem}
h3.ch .n{background:var(--bg-muted);border-radius:999px;padding:.1rem .6rem;
font-size:.8rem;font-weight:600}
section h3.ch + ul{margin-bottom:1rem}
form.creds{display:grid;gap:.4rem;max-width:26rem;margin:.5rem 0 1rem}
form.creds label{font-size:.85rem;color:var(--text-muted);font-weight:500}
form.creds input{background:var(--bg-base);color:var(--text);border:1px solid var(--border);
border-radius:var(--radius-md);padding:.6rem .7rem;font:inherit;font-size:.95rem}
form.creds input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
form.creds .btn{margin-top:.5rem;justify-self:start}
button:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.note{color:var(--text-muted);font-size:.85rem;margin-top:1.75rem;
border-top:1px solid var(--border);padding-top:.9rem}
@media(max-width:520px){.wrap{padding:1rem .75rem 3rem}li{flex-direction:column;gap:.15rem}
.navbar .ver{margin-left:0}}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _eq(value: Any) -> str:
    """Escape for use inside a URL query value, then for HTML."""
    return _e(quote(str(value or ""), safe=""))


def _entry_li(bucket: str, entry: Dict[str, Any]) -> str:
    name = _e(entry.get("name") or "(unnamed)")
    sel = ""
    if entry.get("source") and entry.get("id") is not None:
        sel = f'<span class="sel">{_e(entry["source"])}:{_e(entry["id"])}</span>'

    if bucket == "diverged":
        rows = "".join(
            f'<span class="d"><b>{_e(f.get("field"))}</b> yours: {_e(f.get("current"))}'
            f' &nbsp;|&nbsp; importer: {_e(f.get("would_be"))}</span>'
            for f in entry.get("fields", []) if isinstance(f, dict)
        )
        return f'<li class="diverged"><span class="name">{name}</span>{sel}{rows}</li>'

    extra = ""
    if bucket == "updated" and entry.get("fields"):
        extra = f'<span class="fields">{_e(", ".join(map(str, entry["fields"])))}</span>'
    return f'<li><span class="name">{name}</span>{sel}{extra}</li>'


def _sources_bar(sources: List[Dict[str, Any]], extra: str = "") -> str:
    chips = []
    for src in sources:
        status = str(src.get("status", "?"))
        note = STATUS_NOTE.get(status, status)
        count = src.get("imported", 0)
        detail = f"{count} found" if status == "ok" else note
        chips.append(
            f'<span class="chip"><span class="dot {_e(status)}"></span>'
            f'<b>{_e(src.get("name"))}</b> {_e(detail)}</span>'
        )
    return f'<div class="bar">{"".join(chips)}{extra}</div>'


def credentials_form(token: str, message: str = "", username: str = "") -> str:
    """Shown on first use and whenever Sunshine rejects what we have.

    Applying changes needs Sunshine's own API, which needs its web UI login.
    Asking here beats making someone run a shell script.
    """
    note = (f'<p class="why" style="color:var(--danger)">{_e(message)}</p>'
            if message else
            '<p class="why">Applying changes asks Sunshine to reload, which needs '
            'the login you use for its web interface at port 47990.</p>')
    return f"""<section><h2>Connect to Sunshine</h2>{note}
<form class="creds" method="post" action="/credentials">
<label for="u">Username</label>
<input id="u" name="username" autocomplete="username" value="{_e(username)}" required autofocus>
<label for="p">Password</label>
<input id="p" name="password" type="password" autocomplete="current-password" required>
<button class="btn" type="submit">Verify and save</button>
</form>
<p class="why">Checked against Sunshine before it is stored, so a typo fails here
rather than later. Saved to the config directory, readable only by you.</p>
</section>"""


def _change_list(plan: Dict[str, Any]) -> str:
    """Spell out what will actually change, rather than asserting that something will."""
    blocks = []
    for key, title in (("added", "Will be added"), ("updated", "Will be updated"),
                       ("pruned", "Will be removed")):
        entries = plan.get(key) or []
        if not entries:
            continue
        items = "".join(f'<li><span class="name">{_e(e.get("name"))}</span></li>'
                        for e in entries if isinstance(e, dict))
        blocks.append(f'<h3 class="ch">{_e(title)} <span class="n">{len(entries)}</span></h3>'
                      f'<ul>{items}</ul>')
    return "".join(blocks)


_QUEUED_WORDING = {
    "hide": "Hide", "delete": "Delete", "edit": "Edit",
    "clone": "Copy", "add": "Add", "restore": "Un-hide",
}


def _queued_list(pending: List[Dict[str, Any]]) -> str:
    if not pending:
        return ""
    items = []
    for op in pending:
        if op.get("op") == "adopt":
            # What a scan found, in words: it was printing "adopt", the
            # queue's own name for it. A takeover says what it replaces, or
            # nothing on this page mentions Sunshine's tile going. #42.
            name = op.get("name") or "(unnamed)"
            if op.get("replaces"):
                text = f"Replace {op['replaces']} with {name}"
            else:
                text = f"{'Update' if op.get('fields') else 'Add'} {name}"
            items.append(f'<li><span class="name">{_e(text)}</span></li>')
            continue
        if op.get("op") == "rollback":
            # It said "rollback the copy from apps-20260927-005946.json": the
            # queue's word and a file name, where the page that chose it had
            # said "27 Sep 2026 at 00:59:46".
            text = f"Restore the copy from {_when(str(op.get('backup') or ''))}"
            items.append(f'<li><span class="name">{_e(text)}</span></li>')
            continue
        verb = _QUEUED_WORDING.get(str(op.get("op")), str(op.get("op")))
        name = op.get("name") or (op.get("fields") or {}).get("name") or "(unnamed)"
        renamed = (op.get("fields") or {}).get("name") if op.get("op") == "edit" else None
        if renamed and renamed != name:
            # "Edit Team Fortress 2" did not say it would be called something
            # else afterwards, which is the one change you would look for.
            items.append(f'<li><span class="name">'
                         f'{_e(f"Rename {name} to {renamed}")}</span></li>')
            continue
        items.append(f'<li><span class="name">{_e(verb)} {_e(name)}</span></li>')
    return (f'<h3 class="ch">Your changes <span class="n">{len(pending)}</span></h3>'
            f'<ul>{"".join(items)}</ul>')


def confirm_page(doc: Dict[str, Any], token: str, via_sunshine: bool = False,
                 pending: Optional[List[Dict[str, Any]]] = None) -> str:
    """The step between wanting to apply and applying.

    It lists the queue and nothing else, because the queue is exactly what
    applying does. It used to run a scan and show what that found as well,
    which was wrong twice over: it promised changes Apply does not make -- a
    game deleted earlier reappears in a scan and was listed as "will be added",
    then was not added -- and it ran a library scan nobody asked for, on the
    page whose whole job is to ask first.

    Applying reloads Sunshine, which ends any stream in progress. That is not a
    malfunction -- it is how the new list reaches Moonlight -- but it should be
    stated before it happens rather than discovered.
    """
    pending = pending or []
    changing = len(pending)

    if via_sunshine:
        warning = ("<p><b>This will disconnect you.</b> Sunshine has to reload its app "
                   "list, which ends the stream you are watching this through. You will "
                   "return to Moonlight, where the new games should appear in the next "
                   "30 seconds.</p>")
    else:
        warning = ("<p>Sunshine will reload its app list. Any stream in progress will "
                   "disconnect and return to Moonlight, where the new games should "
                   "appear in the next 30 seconds.</p>")

    if changing:
        warn_block = f'<section class="warn">{warning}</section>'
        action_block = (f'<form method="post" action="/apply">'
                        f'<div class="actions">'
                        f'<button class="btn" type="submit">Write and reload</button>'
                        f'<a class="btn sec" href="/">Cancel</a>'
                        f'</div></form>')
    else:
        # Applying would reload Sunshine, and reloading disconnects. Not worth
        # doing for no change, so do not offer it.
        warn_block = ""
        action_block = (f'<div class="actions">'
                        f'<a class="btn" href="/" data-back>Back</a></div>')

    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Apply changes')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Apply {changing} change{'' if changing == 1 else 's'}?</h1>
<section>{_queued_list(pending)
  or '<p class="why">Nothing would change.</p>'}</section>
{warn_block}
{action_block}
</div></body></html>"""


def closing_page(via_sunshine: bool = False) -> str:
    """The last page, shown while the server is on its way down.

    There is a page at all because the window takes a moment to go, and a
    frame of "this site cannot be reached" as the server stops looks like a
    crash rather than like leaving.
    """
    # Which kind of window this is showing in is not something the server
    # knows: it starts before the launcher has decided, and a browser may have
    # been the fallback. So say what is true of both rather than guess.
    if via_sunshine:
        detail = ("Sunshine will end this stream and you will be back in "
                  "Moonlight in a moment.")
    else:
        detail = ("Its own window closes itself. A browser tab stays until you "
                  "close it -- we cannot close a window we did not open.")
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Closing')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
<section class="ok"><h2>Closed</h2><p class="why">{_e(detail)}</p></section>
</div></body></html>"""


def leaving_with_changes_page(token: str, queued: int) -> str:
    """Asked before closing while something is staged, and only then.

    The queue is a file and outlives the program, so nothing is lost by
    leaving -- but "I pressed close and my changes vanished" is what somebody
    would reasonably assume, so say what actually happens instead.
    """
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Close?')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Close without applying?</h1>
<p class="sub">{queued} change{'' if queued == 1 else 's'} {'is' if queued == 1
else 'are'} staged and {'has' if queued == 1 else 'have'} not been written to
Sunshine.</p>
<section><p class="why">Nothing is lost by closing: what you have staged is
still here the next time you open the manager. Applying is what writes it to
Sunshine.</p></section>
<div class="actions">
<a class="btn" href="/">Back to the apps</a>
<form method="post" action="/quit" class="inline">
<input type="hidden" name="anyway" value="1">
<button class="btn sec" type="submit">Close anyway</button></form>
</div>
</div></body></html>"""


def applied_page(token: str, via_sunshine: bool = False) -> str:
    """Shown straight after a successful apply.

    Deliberately static. Redirecting to the plan would re-run the importer, and
    a reload ends the stream, so Sunshine terminates our process group while
    that subprocess is running -- which surfaced as "could not read a plan"
    exactly when the apply had in fact succeeded.
    """
    if via_sunshine:
        detail = ("This stream is ending so Sunshine can reload. You will return to "
                  "Moonlight, where the new games should appear in the next 30 seconds.")
    else:
        detail = ("Sunshine reloaded its app list. Any stream in progress has "
                  "disconnected and will show the new games within 30 seconds.")
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Applied')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Applied</h1>
<section class="ok"><p class="why">apps.json was written. {_e(detail)}</p></section>
<div class="actions"><a class="btn sec" href="/">Back to the apps</a></div>
</div></body></html>"""


def page(doc: Dict[str, Any], log: str = "", token: str = "",
         auth_ok: bool = True, auth_message: str = "", show_form: bool = False,
         applied: bool = False, apply_error: str = "") -> str:
    totals = doc.get("totals", {}) or {}
    plan = doc.get("plan", {}) or {}

    sections = []
    for key, title, why in BUCKETS:
        entries = plan.get(key) or []
        if not entries:
            continue
        items = "".join(_entry_li(key, e) for e in entries if isinstance(e, dict))
        sections.append(
            f'<section><h2>{_e(title)} <span class="n">{len(entries)}</span></h2>'
            f'<p class="why">{_e(why)}</p><ul>{items}</ul></section>'
        )
    if not sections:
        sections.append('<section><h2>Nothing to report</h2>'
                        '<p class="why">No apps were discovered and none are recorded.</p></section>')

    changing = sum(int(totals.get(k, 0)) for k in ("added", "updated", "pruned"))
    summary = (f"{changing} change{'' if changing == 1 else 's'} pending"
               if changing else "Up to date — nothing would change")

    banner = ""
    if apply_error:
        banner = (f'<section class="err"><h2>Apply failed</h2>'
                  f'<p class="why">{_e(apply_error)}</p></section>')
    elif applied:
        banner = ('<section class="ok"><h2>Applied</h2><p class="why">'
                  'apps.json was written and Sunshine reloaded it. If you were '
                  'streaming, Moonlight should show the new games in the next '
                  '30 seconds.</p></section>')

    auth_chip = (f'<span class="chip"><span class="dot {"ok" if auth_ok else "error"}"></span>'
                 f'<b>sunshine</b> {"connected" if auth_ok else "needs sign-in"}</span>')

    form_block = credentials_form(token, auth_message if not auth_ok else "") if show_form else ""

    log_block = ""
    if log.strip():
        log_block = (f'<details><summary>Importer log</summary>'
                     f'<pre>{_e(log.strip())}</pre></details>')

    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title()}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}<span class="ro">read-only preview</span></div>
<div class="wrap">
<h1>{_e(summary)}</h1>
<p class="sub"><code>{_e(doc.get("apps_json", ""))}</code></p>
{_sources_bar(doc.get("sources") or [], auth_chip)}
{banner}
{form_block}
<div class="actions"><a class="btn" href="/apply">Apply changes</a>
<a class="btn sec" href="/">Re-scan</a></div>
{"".join(sections)}
{log_block}
<p class="note">Read-only preview. Nothing has been written to apps.json.
Generated {_e(doc.get("generated_at", ""))} by
{_e((doc.get("generator") or {}).get("name", ""))}
{_e((doc.get("generator") or {}).get("version", ""))},
shown by sunshine-apps-ui {_e(__version__)}.</p>
</div></body></html>"""


def error_page(message: str, detail: str = "", token: str = "",
               title: str = "Something went wrong") -> str:
    extra = f"<pre>{_e(detail)}</pre>" if detail else ""
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title()}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
<section class="err"><h2>{_e(title)}</h2>
<p class="why">{_e(message)}</p>{extra}</section>
<div class="actions"><a class="btn sec" href="/">Try again</a></div>
</div></body></html>"""


# Field names as they read on screen. "image-path" is what apps.json calls it;
# nobody thinks of a cover that way.
_FIELD_WORDS = {
    "name": "name", "cmd": "command", "working-dir": "working directory",
    "image-path": "artwork", "output": "output log",
    "exit-timeout": "exit timeout", "elevated": "run elevated",
    "auto-detach": "auto-detach", "wait-all": "wait for all processes",
    "exclude-global-prep-cmd": "global prep commands",
    "detached": "detached commands", "prep-cmd": "prep commands",
}


def _fields_in_words(fields: List[str]) -> str:
    """Which fields differ, said plainly, with the rename spelled out separately."""
    words = [_FIELD_WORDS.get(f, f) for f in fields if f != "name"]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def _when(backup_name: str) -> str:
    """A kept copy's name, said the way a person would say it."""
    import time
    stamp = backup_name[len("apps-"):-len(".json")] if backup_name else ""
    try:
        return time.strftime("%d %b %Y at %H:%M:%S",
                             time.strptime(stamp, "%Y%m%d-%H%M%S"))
    except ValueError:
        return backup_name or "an earlier copy"


_BACKUPS_CSS = """
.copies{display:grid;gap:.5rem;margin:0 0 1.5rem}
.copy{display:flex;align-items:center;gap:1rem;background:var(--bg-subtle);
border:1px solid var(--border);border-radius:var(--radius-md);padding:.7rem .9rem}
.copy .when{font-weight:600}
.copy .what{color:var(--text-muted);font-size:.9rem;flex:1}
.copy.broken{opacity:.6}
.copy.broken .what{color:var(--danger)}
"""


def backups_page(copies: List[Dict[str, Any]], token: str,
                 error: str = "") -> str:
    """Pick a kept copy of apps.json to go back to."""
    rows = []
    for copy in copies:
        when = _when(str(copy.get("name", "")))
        if not copy.get("readable"):
            rows.append(f'<div class="copy broken"><span class="when">{_e(when)}</span>'
                        f'<span class="what">This copy cannot be read, so it cannot '
                        f'be restored.</span></div>')
            continue
        count = copy.get("apps", 0)
        rows.append(
            f'<div class="copy"><span class="when">{_e(when)}</span>'
            f'<span class="what">{count} application{"" if count == 1 else "s"}</span>'
            f'<a class="btn sec" href="/backups?restore={_eq(str(copy.get("name")))}'
            f'">See what this would change</a></div>')

    body = ("".join(rows) if rows else
            '<p class="why">No copies yet. One is taken automatically before '
            'anything is written to apps.json.</p>')
    problem = (f'<section class="err"><p class="why">{_e(error)}</p></section>'
               if error else "")

    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Restore a copy')}</title>
<style>{_CSS}{_BACKUPS_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Restore a copy</h1>
<p class="sub">A copy of apps.json is taken before anything is written to it.
The most recent {len(copies)} are kept.</p>
{problem}
<div class="copies">{body}</div>
<p class="why">Choosing one shows what it would change on the grid. Nothing is
written until you apply it, and a copy of the current file is taken first --
so a restore can itself be undone.</p>
<div class="actions"><a class="btn sec" href="/" data-back>Back</a></div>
</div></body></html>"""


# ---------------------------------------------------------------- the grid ---

_GRID_CSS = """
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
margin:0 0 1.5rem}
.tile{position:relative;display:block;text-decoration:none;color:inherit;
border-radius:var(--radius-lg);overflow:hidden;
background:var(--bg-subtle);border:2px solid transparent;box-shadow:var(--shadow-sm)}
.tile:hover,.tile:focus-visible{border-color:var(--primary);outline:none}
/* The picture is the tile's own 2:3; the name goes under it, not over it.
   Over it, on a scrim, it covered the words our worded tiles carry at the
   bottom -- "APP MANAGER" and "BIG PICTURE" all but hidden on the one page
   that is meant to show what Moonlight will. Issue #47. */
.tile img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block}
.tile .fallback{width:100%;aspect-ratio:2/3;display:flex;align-items:center;
justify-content:center;padding:.6rem;text-align:center;font-weight:600;
font-size:.9rem;color:var(--text-muted);background:var(--bg-muted)}
.tile .cap{display:block;padding:.45rem .55rem .5rem;
font-size:.82rem;font-weight:600;color:var(--text);line-height:1.25;
overflow-wrap:anywhere}
.tile.new{border-color:var(--success)}
.tile.pending{border-color:var(--warning)}
.tile.pending .flag{background:var(--warning);color:#1a1a1a}
.tile.willgo img,.tile.willgo .fallback{filter:grayscale(1);opacity:.4}
.tile.ghost{border:2px dashed var(--warning);background:transparent}
.tile.ghost .fallback{background:transparent;color:var(--text-muted)}
.tile.ghost .flag{background:var(--warning);color:#1a1a1a}
.tile.ghost.found{border-color:var(--success);border-style:solid}
.tile.ghost.found .flag{background:var(--success);color:#fff}
.tile .flag{position:absolute;top:.4rem;left:.4rem;z-index:1;background:var(--success);
color:#fff;font-size:.68rem;font-weight:700;letter-spacing:.04em;
padding:.15rem .45rem;border-radius:999px}
.tile.hidden img,.tile.hidden .fallback{filter:grayscale(1);opacity:.32}
.tile.hidden{border-style:dashed;border-color:var(--border-strong)}
.tile.hidden .mark{position:absolute;top:0;left:0;right:0;aspect-ratio:2/3;display:flex;align-items:center;
justify-content:center;transform:rotate(-20deg);font-size:1.1rem;font-weight:800;
letter-spacing:.1em;color:var(--text);opacity:.75;text-transform:uppercase}
.tile.add{border:2px dashed var(--border-strong);background:transparent}
/* It has no name under it, so it fills the row instead of stopping short. */
.tile.add .fallback{background:transparent;color:var(--text-muted);font-size:.9rem;
aspect-ratio:auto;height:100%;min-height:100%}
.tile.add:hover{border-color:var(--primary)}
.legend{display:flex;gap:1rem;flex-wrap:wrap;color:var(--text-muted);
font-size:.85rem;margin:0 0 1rem}
.legend i{font-style:normal;border-radius:3px;padding:0 .35rem;border:2px solid}
.legend i.new{border-color:var(--success)}
.legend i.hid{border-color:var(--border-strong);border-style:dashed}
.legend i.pend{border-color:var(--warning)}
"""


# What a queued operation does to the tile it refers to.
_PENDING = {
    "hide": ("WILL HIDE", True),
    "delete": ("WILL DELETE", True),
    "edit": ("EDITED", False),
    "clone": ("COPY QUEUED", False),
    "adopt": ("UPDATED", False),
    "suppress": ("WILL HIDE", True),
    "restore": ("WILL UN-HIDE", False),
}


def _tile(entry: Dict[str, Any], token: str, *, is_new: bool = False,
          is_hidden: bool = False, pending: str = "",
          from_scan: bool = False) -> str:
    name = _e(entry.get("name") or "(unnamed)")
    image = entry.get("image-path") or ""
    inner = (f'<img src="/art?p={_eq(image)}" alt="">'
             if image else f'<div class="fallback">{name}</div>')

    label, greyed = _PENDING.get(pending, ("", False))
    # A change a scan proposed reads as green, the way a newly found game should;
    # one you made by hand reads as amber. Both are queued, both are on the grid.
    tone = " new" if (is_new or (label and from_scan)) else (" pending" if label else "")
    classes = ("tile" + tone + (" hidden" if is_hidden else "")
               + (" willgo" if greyed else ""))
    flag = (f'<span class="flag">{_e(label)}</span>' if label
            else ('<span class="flag">NEW</span>' if is_new else ""))
    mark = '<span class="mark">hidden</span>' if is_hidden else ""
    target = (f'/app?index={_e(entry.get("index"))}'
              if entry.get("index") is not None
              else f'/app?hidden={_eq(str(entry.get("source")) + ":" + str(entry.get("id")))}'
                   f'')
    return (f'<a class="{classes}" href="{target}">{inner}{flag}{mark}'
            f'<span class="cap">{name}</span></a>')


def connect_page(token: str, message: str = "", username: str = "") -> str:
    """The credentials form on its own page, reachable from the grid."""
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Connect to Sunshine')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
{credentials_form(token, message, username)}
<div class="actions"><a class="btn sec" href="/" data-back>Back</a></div>
</div></body></html>"""


def render_elevating(token: str) -> str:
    """Shown while Windows asks whether to allow it.

    The new instance replaces this one as any relaunch does, so this page only
    has to exist for as long as the prompt does.
    """
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title("Administrator")}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<section class="ok"><h2>Windows is asking</h2>
<p class="why">Allow it, and the manager opens again with the rights it needs to
write <code>apps.json</code>. This window closes on its own.</p>
<p class="why">Refusing is a fine answer: everything except saving works
without it.</p></section>
<div class="actions"><a class="btn sec" href="/" data-back>Back</a></div>
</div></body></html>"""


# Where bugs go. One place, so the link on the page and the code in the QR
# cannot drift apart -- they are both this string.
ISSUES_URL = "https://github.com/4o66/sunshine-apps-ui/issues"
# Where a SteamGridDB key is actually issued. Deep link rather than the front
# page: the page it lands on is the one with the key on it, so the instructions
# beside it only have to cover getting signed in.
SGDB_KEY_URL = "https://www.steamgriddb.com/profile/preferences/api"
# Documentation lives in the repository and not in an install: a release
# archive carries no docs/ directory, so naming a local path in the interface
# would send somebody looking for a file that is not on their machine.
DOCS_URL = "https://github.com/4o66/sunshine-apps-ui/blob/main/docs"


def _version_label() -> str:
    from . import version

    try:
        return version.display()
    except Exception:              # noqa: BLE001 - a label, never a failure
        return version.RELEASE


# A QR code is always dark-on-white, whatever the theme: a reader points a
# camera at it, and an inverted one does not scan.
_QR_CSS = """
.qr{background:#fff;padding:12px;border-radius:var(--radius-md);
display:inline-block;line-height:0;margin:.25rem 0 .9rem}
.qr svg{display:block;width:min(46vw,260px);height:auto}
"""

SETTINGS_CSS = """
.setting{border-bottom:1px solid var(--border);padding:1rem 0}
.setting:last-child{border-bottom:0}
.setting h3{margin:0 0 .2rem;font-size:1rem}
.setting .why{margin:0 0 .7rem}
.choices{display:flex;gap:.5rem;flex-wrap:wrap}
.choices button{background:var(--bg-subtle);color:var(--text);
border:1px solid var(--border);border-radius:var(--radius-md);
padding:.5rem 1rem;font:inherit;font-size:.9rem;cursor:pointer}
.choices button.on{background:var(--primary);border-color:var(--primary);color:#fff}
.toggle{margin:.4rem 0}
.toggle.nested{margin-left:1.7rem}
.toggle.off{opacity:.5}
/* A whole switch is one button, so the label and the explanation are part of
   what you press -- which matters most with a gamepad, where hitting a 17px
   box is the difference between working and not. */
button.switch{display:flex;align-items:flex-start;gap:.6rem;width:100%;
text-align:left;background:none;border:0;padding:.25rem;margin:0;
font:inherit;color:inherit;cursor:pointer;border-radius:var(--radius-md)}
button.switch:hover:not(:disabled){background:var(--bg-subtle)}
button.switch:disabled{cursor:default}
button.switch:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
button.switch .box{flex:0 0 auto;width:1.05rem;height:1.05rem;margin-top:.2rem;
border:1px solid var(--border-strong);border-radius:4px;background:var(--bg-base);
display:flex;align-items:center;justify-content:center;
font-size:.75rem;line-height:1;color:#fff}
button.switch .box.on{background:var(--primary);border-color:var(--primary)}
button.switch .body{flex:1}
button.switch .lab{display:block;font-weight:500}
button.switch .why{display:block;margin:.1rem 0 0;font-size:.85rem;
color:var(--text-muted)}
.setting form.pick{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
.result{margin:.8rem 0 0;padding:.7rem .9rem;border-radius:var(--radius-md);
background:var(--bg-subtle);border:1px solid var(--border);font-size:.9rem}
.result.available{border-left:3px solid var(--success)}
.result.unreachable{border-left:3px solid var(--warning)}
.setting select{background:var(--bg-subtle);color:var(--text);
border:1px solid var(--border);border-radius:var(--radius-md);
padding:.5rem .7rem;font:inherit;font-size:.9rem;max-width:100%}
.setting select:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.setting input[type=password]{background:var(--bg-subtle);color:var(--text);
border:1px solid var(--border);border-radius:var(--radius-md);
padding:.5rem .7rem;font:inherit;font-size:.9rem;min-width:16rem;max-width:100%}
.setting input[type=password]:focus-visible{outline:3px solid var(--accent);
outline-offset:2px}
/* A link inside explanatory text was the same small muted gray as the text
   around it, underlined in the browser default -- legible on a desk, not from
   a sofa. */
.setting .why a{color:var(--primary);font-weight:600;text-decoration:underline;
text-underline-offset:2px}
.setting .why a:hover{color:var(--primary-hover,var(--primary))}
.setting form + .why{margin:.5rem 0 .7rem}
"""


# ------------------------------------------------------ which config tree ---

CONFIG_CSS = """
ul.trees{margin:.2rem 0 .9rem}
ul.trees li{align-items:center}
ul.trees li .body{flex:1 1 18rem;display:grid;gap:.1rem}
ul.trees li .sel{word-break:break-all}
ul.trees li form{margin:0}
ul.trees li .chip{padding:.25rem .7rem}
ul.trees .btn:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
ul.trees .btn:disabled{opacity:.5;cursor:default}
"""


def _tree_kind(path: str) -> str:
    """What sort of install a config tree belongs to, from where the tree is.

    The tree's location is reliable where a unit name is not: a Flatpak can
    only write under ~/.var/app/<id>, whereas the native RPM's systemd unit is
    named app-dev.lizardbyte.app.Sunshine.service and looks exactly like a
    Flatpak's. Issue #19.
    """
    parts = path.replace("\\", "/").split("/")
    if ".var" in parts:
        at = parts.index(".var")
        if len(parts) > at + 2 and parts[at + 1] == "app":
            return f"Flatpak ({parts[at + 2]})"
    if "Sunshine.app" in parts:
        return "The macOS app"
    if path.replace("\\", "/").rstrip("/").endswith("/.config/sunshine"):
        return "Installed from a package"
    # Windows keeps config\ beside Sunshine.exe, so two installs differ only by
    # where they are -- and "Installed beside Sunshine" twice, which is what
    # the Windows rig showed, told nobody anything. Name the folder.
    folder = path.replace("\\", "/").rstrip("/")
    if folder.lower().endswith("/config"):
        install = path.rstrip("\\/")[:-len("config")].rstrip("\\/")
        if install:
            return f"Installed in {install}"
    return "Installed beside Sunshine"


def _last_used_text(stamp: float) -> str:
    if not stamp:
        return "never used"
    import time
    return "last used " + time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def _config_trees(config: Dict[str, Any], token: str, back: str) -> str:
    """Every tree found, the one in use marked, a button on each of the rest."""
    chosen = str(config.get("chosen") or "")
    queued = int(config.get("queued") or 0)
    offer_keep = config.get("how") in ("newest", "tie")
    rows = []
    for candidate in config.get("candidates") or []:
        path = str(candidate.get("path") or "")
        apps = candidate.get("apps")
        count = ("apps.json unreadable" if apps is None else
                 f"{apps} app{'' if apps == 1 else 's'}")
        facts = f"{_last_used_text(float(candidate.get('last_used') or 0))} &middot; {count}"

        def form(label: str, disabled: bool = False) -> str:
            return (f'<form method="post" action="/config-dir">'
                    f'<input type="hidden" name="path" value="{_e(path)}">'
                    f'<input type="hidden" name="back" value="{_e(back)}">'
                    f'<button class="btn sec" type="submit"'
                    f'{" disabled" if disabled else ""}>{label}</button></form>')

        if path == chosen:
            action = '<span class="chip"><span class="dot ok"></span>In use</span>'
            if offer_keep:
                action += form("Keep this one")
        else:
            action = form("Use this one", disabled=bool(queued))
        rows.append(f'<li><span class="body"><span class="name">{_e(_tree_kind(path))}</span>'
                    f'<span class="sel">{_e(path)}</span>'
                    f'<span class="fields">{facts}</span></span>{action}</li>')
    listing = f'<ul class="trees">{"".join(rows)}</ul>' if rows else ""
    if queued and len(rows) > 1:
        listing += (f'<p class="why">{queued} change{"" if queued == 1 else "s"} '
                    f'{"is" if queued == 1 else "are"} waiting to be applied to '
                    f'the one in use, so switching waits until '
                    f'{"it is" if queued == 1 else "they are"} applied or discarded.</p>')
    notice = str(config.get("notice") or "")
    if notice:
        listing += f'<div class="result unreachable">{_e(notice)}</div>'
    return listing


def config_banner(config: Optional[Dict[str, Any]], token: str) -> str:
    """Said on the grid when the config tree in use was a judgment, not a fact.

    The grid is where it matters: a scan written to the wrong tree reports
    success and changes nothing, and until #19 the only record of the choice
    was a log line on a console nobody at a television sees.
    """
    config = config or {}
    how = config.get("how")
    candidates = config.get("candidates") or []
    if config.get("missing"):
        # The worst case, and the one #19 was found in: the install Sunshine
        # will run has not made its config yet, and what is here was left by
        # one that is gone. Everything done on this page would change nothing.
        missing = _e(str(config["missing"]))
        chosen = _e(str(config.get("chosen") or ""))
        return (f'<section class="err"><h2>This is not the Sunshine that runs</h2>'
                f'<p class="why">Sunshine is set up to use <code>{missing}</code>, '
                f'which does not exist yet &mdash; Sunshine creates it the first '
                f'time it starts. What is shown here is <code>{chosen}</code>, left '
                f'by another install, and changes to it will do nothing. Start '
                f'Sunshine once, then open this again.</p></section>')
    if (how not in ("newest", "tie") and not config.get("stale")) or len(candidates) < 2:
        # Nothing to ask, but a refused switch still has to say why.
        notice = str(config.get("notice") or "")
        return f'<section class="warn"><p>{_e(notice)}</p></section>' if notice else ""
    chosen = _e(str(config.get("chosen") or ""))
    if config.get("stale"):
        was = _e(str(config.get("was") or ""))
        title = "The config you chose earlier has been set aside"
        if config.get("stale_reason") == "running":
            why = (f"You chose <code>{was}</code>, but Sunshine is running from "
                   f"<code>{chosen}</code>, so that is the one showing.")
        elif how == "service":
            why = (f"You chose <code>{was}</code>, but another Sunshine config has "
                   f"been used since, so this is showing <code>{chosen}</code>, "
                   f"the one Sunshine's service starts. Choose again if that is "
                   f"wrong.")
        else:
            why = (f"You chose <code>{was}</code>, but another Sunshine config has "
                   f"been used since, so this is showing <code>{chosen}</code>, "
                   f"the one used most recently. Choose again if that is wrong.")
        cls = "warn"
    elif how == "tie":
        never = all(not c.get("last_used") for c in candidates[:2])
        reason = ("none of them has been used yet" if never else
                  "two were last used at the same moment")
        title = "Which Sunshine is this machine running?"
        why = (f"There is more than one Sunshine config here and nothing tells them "
               f"apart: {reason}. This is showing <code>{chosen}</code>, which is a "
               f"guess. If the tiles below are not the ones you see in Moonlight, "
               f"use the other one.")
        cls = "warn"
    else:
        title = "More than one Sunshine config here"
        others = ("The other is" if len(candidates) == 2 else "The others are")
        why = (f"This is showing the one Sunshine used most recently. {others} "
               f"usually left behind by an install that has since been removed, and "
               f"changes written there do nothing. Keep this one and you will not "
               f"be asked again.")
        cls = ""
    return (f'<section class="{cls}"><h2>{title}</h2><p class="why">{why}</p>'
            f'{_config_trees(config, token, back="")}</section>')


def config_setting(config: Optional[Dict[str, Any]], token: str) -> str:
    """The Settings section: which tree is in use, always, and the others."""
    config = config or {}
    how = config.get("how")
    chosen = _e(str(config.get("chosen") or ""))
    candidates = config.get("candidates") or []
    if how == "override":
        body = (f'<p class="why">Set by <code>SUNSHINE_CONF_DIR</code>: '
                f'<code>{chosen}</code>. Unset it to choose here.</p>')
    elif how == "argument":
        body = (f'<p class="why">Set by <code>--conf-dir</code>: '
                f'<code>{chosen}</code>.</p>')
    elif not candidates:
        body = (f'<p class="why">No Sunshine config was found, so this uses the '
                f'usual place: <code>{chosen}</code>.</p>')
    elif len(candidates) == 1:
        body = ('<p class="why">This machine has one, so there is nothing to '
                'choose.</p>' + _config_trees(config, token, back="settings"))
    else:
        reason = {
            "running": "Sunshine is running from the one in use, so that one is "
                       "certainly live.",
            "service": "Sunshine is not running; the one in use is the one its "
                       "service starts.",
            "preferred": "The one in use is the one you chose.",
        }.get(str(how), "The one Sunshine used most recently is normally the live "
                        "one; the app counts are the quickest way to tell.")
        body = (f'<p class="why">More than one install of Sunshine has left a '
                f'config here. {reason}</p>'
                + _config_trees(config, token, back="settings"))
    return f'<div class="setting"><h3>Which Sunshine</h3>{body}</div>'



SETTINGS_SECTIONS = [("appearance", "Appearance"), ("language", "Language"), ("art", "Community artwork"),
                     ("sunshine", "Which Sunshine"), ("defaults", "Default tiles"), ("updates", "Updates")]


def _choice(name: str, value: str, label: str, chosen: bool) -> str:
    return (f'<button class="choice{" here" if chosen else ""}" name="{_e(name)}" value="{_e(value)}">'
            f'<b>{_e(label)}</b></button>')


def settings_page(token: str, *, prefs: Dict[str, Any],
                  answer: Optional[Any] = None,
                  notice: str = "",
                  language: Optional[Dict[str, Any]] = None,
                  via_sunshine: bool = False,
                  sgdb: Optional[Dict[str, Any]] = None,
                  config: Optional[Dict[str, Any]] = None,
                  section: str = "appearance",
                  device: str = "",
                  text_size: str = "standard",
                  defaults: Optional[Dict[str, Any]] = None,
                  current_version: str = "") -> str:
    """Everything that is a preference rather than a change to the app list (#66).

    Kept off the grid deliberately -- the maintainer's instruction, 2026-09-19, "set apart
    from the grid". Two panes: the sections on the left, one section on the
    right, each at its own address so B and the browser both come back to it.
    """
    section = section if section in dict(SETTINGS_SECTIONS) else "appearance"
    here = ' class="here"'
    nav = "\n".join(f'<a href="/settings?section={key}"{here if key == section else ""}>{_e(label)}</a>'
                    for key, label in SETTINGS_SECTIONS)
    said = notice2("warn", "", _e(notice)) + "\n" if notice else ""

    if section == "appearance":
        chosen = str(prefs.get("theme", "system")).lower()
        themes = "\n".join(_choice("theme", k, l, chosen == k)
                           for k, l in (("system", "Follow the system"), ("light", "Light"), ("dark", "Dark")))
        sizes = "\n".join(_choice("size", k, l, text_size == k)
                          for k, l in (("smaller", "Smaller"), ("standard", "Standard"), ("larger", "Larger")))
        which = f"<b>{_e(device)}</b>" if device else "this machine"
        pane = (f'<h2>Appearance</h2>\n<p>Following the system is the default. On a television, where there is no '
                f'system to follow, pick the one that suits the room.</p>\n'
                f'<form class="choices" method="post" action="/settings/theme">\n{themes}\n</form>\n'
                f'<h2 style="margin-top:.8rem">Text size</h2>\n'
                f'<p>Remembered for each device you stream to. This one is {which}.</p>\n'
                f'<form class="choices" method="post" action="/settings/size">\n{sizes}\n</form>')
    elif section == "language":
        info = language or {}
        picked = str(prefs.get("language", "") or "")
        options = [_choice("language", "", "Follow the system" + str(info.get("system_suffix", "")), not picked)]
        for item in info.get("languages", []):
            code = str(item.get("code", ""))
            label = item.get("name", code)
            if item.get("name_in_english") and item["name_in_english"] != label:
                label = f'{label} ({item["name_in_english"]})'
            options.append(_choice("language", code, label, picked == code))
        extra = ""
        art = info.get("art") or {}
        if art.get("message"):
            if art.get("action") and art.get("method") == "get":
                button = f'<a class="btn" href="{_e(art["action"])}">{_e(art.get("label", "Go"))}</a>'
            elif art.get("action"):
                button = (f'<form method="post" action="{_e(art["action"])}"><button class="btn" type="submit">'
                          f'{_e(art.get("label", "Download"))}</button></form>')
            else:
                button = ""
            extra += notice2("", "", _e(art["message"]), button) + "\n"
        queued = info.get("queued")
        if queued:
            extra += notice2("", "", f'{queued} of your {"tile" if queued == 1 else "tiles"} will change to match. '
                             f'Nothing is written until you apply it.',
                             f'<a class="btn" href="/apply">Apply {queued} change{"" if queued == 1 else "s"}</a>') + "\n"
        elif queued == 0:
            extra += notice2("", "", "Your tiles already match; there is nothing to apply.") + "\n"
        pane = (f'<h2>Language</h2>\n<p>Which language the words on the tiles are in. The interface itself is '
                f'English for now; the strings are ready to be translated and a language is a file and a pull '
                f'request &mdash; <a href="{_e(DOCS_URL)}/i18n.md" style="color:var(--primary)" target="_blank" '
                f'rel="noopener noreferrer">how to add one</a>.</p>\n'
                f'<form class="choices" method="post" action="/settings/language">\n' + "\n".join(options) + '\n</form>\n'
                f'<p>{_e(info.get("showing", ""))}</p>\n'
                f'<form method="post" action="/settings/art-check"><button class="btn sec" type="submit">Check for '
                f'new tile artwork</button></form>\n'
                f'<p>Looks only at the sets on this machine &mdash; the wordless tiles and any language you have asked '
                f'for &mdash; and never downloads the others.</p>\n{extra}')
    elif section == "art":
        from . import qr
        panel = sgdb or {}
        told = ""
        known = panel.get("key_state") or {}
        if known.get("state") == "refused":
            told = notice2("warn", f'The saved key was refused on {_e(_day(str(known.get("at") or "")))}',
                           "SteamGridDB no longer accepts it. Open the key page on your phone with the code below, "
                           "copy the key shown there, and save it here.") + "\n"
        if panel.get("message"):
            told += notice2("" if panel.get("state") == "available" else "warn", "", _e(panel["message"])) + "\n"
        pane = (f'<h2>Community artwork</h2>\n<p>SteamGridDB is a community library of game artwork, and the place '
                f'to look when a game has no cover of its own &mdash; which is most often a GOG or Epic game, since '
                f'Steam ships its own. It is optional, and everything else here works without it. With a key, the '
                f'artwork picker grows a <b>Show SteamGridDB art</b> button &mdash; nothing is fetched from them '
                f'until you press it.</p>\n{told}'
                f'<div style="display:flex;gap:2rem;align-items:center">\n'
                f'<div class="qr">{qr.svg(SGDB_KEY_URL)}</div>\n'
                f'<form style="display:flex;flex-direction:column;gap:1rem;flex:1" method="post" action="/settings/sgdb-key">\n'
                f'<input type="password" id="sgdb-key" name="sgdb-key" placeholder="API key" aria-label="SteamGridDB API key" '
                f'autocomplete="off" spellcheck="false" data-osk="hex" data-osk-label="Key">\n'
                f'<div><button class="btn sec" type="submit">Save the key</button></div>\n</form>\n</div>')
    elif section == "sunshine":
        pane = "<h2>Which Sunshine</h2>\n" + _which_sunshine(config or {})
    elif section == "defaults":
        pane = _default_tiles_pane(defaults or {})
    else:
        pane = _updates_pane(prefs, answer, current_version)

    main = (f'<main class="main">\n<div class="head"><h1>Settings</h1><span class="sub">None of this touches your '
            f'app list.</span></div>\n<div class="panes">\n<nav class="nav" aria-label="Settings">\n{nav}\n</nav>\n'
            f'<div class="pane">\n{said}{pane}\n</div>\n</div>\n</main>')
    bar = ['<a class="btn sec" href="/" data-back><span class="glyph b">B</span>Back to the apps</a>',
           '<span class="grow"></span>']
    if section in ("art",):
        bar.append(keyboard_button())
    page_html = frame.page("Settings", main, "\n".join(bar), settings_here=True)
    return page_html.replace("</body>", '<script src="/app.js"></script>\n</body>', 1) if section == "art" else page_html


def _day(stamp: str) -> str:
    """"2026-09-27" as "27 Sep 2026"."""
    import time
    try:
        return time.strftime("%-d %b %Y", time.strptime(stamp[:10], "%Y-%m-%d"))
    except ValueError:
        return stamp


def _which_sunshine(config: Dict[str, Any]) -> str:
    """Every config tree found: the one in use marked, a button on each of the rest."""
    how = config.get("how")
    chosen = str(config.get("chosen") or "")
    candidates = config.get("candidates") or []
    if how == "override":
        return (f'<p>Set by <code>SUNSHINE_CONF_DIR</code>: <code>{_e(chosen)}</code>. '
                f'Unset it to choose here.</p>')
    if how == "argument":
        return f'<p>Set by <code>--conf-dir</code>: <code>{_e(chosen)}</code>.</p>'
    if not candidates:
        return (f'<p>No Sunshine config was found, so this uses the usual place: <code>{_e(chosen)}</code>.</p>')
    queued = int(config.get("queued") or 0)
    rows = []
    for c in candidates:
        path = str(c.get("path") or "")
        apps = c.get("apps")
        count = "apps.json unreadable" if apps is None else f"{apps} app{'' if apps == 1 else 's'}"
        facts = f"{_last_used_text(float(c.get('last_used') or 0))} · {count}"
        if path == chosen:
            side = '<span class="what" style="background:var(--success);color:#fff">In use</span>'
        else:
            side = (f'<form method="post" action="/config-dir"><input type="hidden" name="path" value="{_e(path)}">'
                    f'<input type="hidden" name="back" value="settings"><button class="btn sec" type="submit"'
                    f'{" disabled" if queued else ""}>Use this one</button></form>')
        rows.append(f'<div class="item"><span class="grow"><span class="name">{_e(_tree_kind(path))}</span>'
                    f'<span class="meta"><code>{_e(path)}</code></span><span class="meta">{facts}</span></span>{side}</div>')
    out = '<div class="list">\n' + "\n".join(rows) + '\n</div>'
    if queued and len(rows) > 1:
        out += (f'\n<p>{queued} change{"" if queued == 1 else "s"} {"is" if queued == 1 else "are"} waiting to be '
                f'applied to the one in use, so switching waits until {"it is" if queued == 1 else "they are"} '
                f'applied or discarded.</p>')
    if config.get("notice"):
        out += "\n" + notice2("warn", "", _e(str(config["notice"])))
    return out


def _default_tiles_pane(defaults: Dict[str, Any]) -> str:
    """What putting the default tiles back would do, before it is pressed (#66)."""
    rows, adding = [], 0
    for item in defaults.get("tiles") or []:
        if item.get("have"):
            meta = f'You have it, as {_e(item["have"])}. Left as it is.'
            flag = ""
        else:
            adding += 1
            meta = f'Deleted. It would come back, as {_e(item.get("becomes") or item["name"])}.'
            flag = '<span class="what">WOULD ADD</span>'
        rows.append(f'<div class="item"><span class="grow"><span class="name">{_e(item["name"])}</span>'
                    f'<span class="meta">{meta}</span></span>{flag}</div>')
    intro = ("<h2>The default tiles</h2>\n<p>Sunshine ships a Desktop, a low resolution Desktop and Steam Big "
             "Picture, and this puts back any of them you have deleted &mdash; in our artwork and doing exactly what "
             "Sunshine's did. Nothing you still have is touched, and nothing is written until you press Apply.</p>\n")
    if defaults.get("unavailable"):
        return intro + notice2("warn", "", _e(defaults["unavailable"]))
    listing = '<div class="list">\n' + "\n".join(rows) + '\n</div>\n'
    if adding:
        tiles = f'{adding} tile{"" if adding == 1 else "s"}'
        return (intro + listing + f'<p>Pressing it queues <b>{tiles}</b> to add. Nothing is written to Sunshine '
                f'until you apply.</p>\n<form method="post" action="/settings/defaults"><button class="btn" '
                f'type="submit">Put {tiles} back</button></form>')
    return intro + listing + "<p>All of them are here; there is nothing to put back.</p>"


def _updates_pane(prefs: Dict[str, Any], answer: Any, current_version: str) -> str:
    """Check for updates, and which builds (#66). Installing waits for after 2.0."""
    found = ""
    if answer is not None:
        if answer.state == "available" and answer.release is not None:
            ver = str(getattr(answer.release, "version", "") or "")
            found = notice2("", f"{_e(ver)} is available" if ver else _e(answer.message),
                            f"You have {_e(current_version)}." if current_version else "",
                            f'<a class="btn sec" href="{_e(answer.release.url)}" target="_blank" '
                            f'rel="noopener noreferrer">What changed</a>') + "\n"
        else:
            found = notice2("warn" if answer.state == "unreachable" else "", "", _e(answer.message)) + "\n"
    dev = bool(prefs.get("dev_builds", False))
    fall_back = bool(prefs.get("stable_if_no_newer_dev", True))

    def switch(setting: str, on: bool, label: str, why: str, enabled: bool = True) -> str:
        cls = "switch" + (" on" if on else "") + ("" if enabled else " flat")
        return (f'<form method="post" action="/settings/channel"><input type="hidden" name="setting" value="{setting}">\n'
                f'<button class="{cls}" type="submit" name="value" value="{"0" if on else "1"}" role="switch" '
                f'aria-checked="{"true" if on else "false"}"{"" if enabled else " disabled"}><span class="knob"></span>'
                f'<span class="t"><b>{label}</b><span>{why}</span></span></button></form>')
    return ('<h2>Updates</h2>\n<p>Checked only when you ask. Nothing is downloaded or installed without you saying '
            f'so.</p>\n{found}<form method="post" action="/settings/check"><button class="btn sec" type="submit">'
            'Check for updates</button></form>\n<h2 style="margin-top:.8rem">Which builds</h2>\n'
            + switch("dev_builds", dev, "Offer development builds",
                     "Newer, and sometimes broken. Off means only finished releases.") + "\n"
            + switch("stable_if_no_newer_dev", fall_back, "Move to the finished release when it is newer",
                     "A release is where a development build was heading, so this leaves you on the finished one "
                     "rather than stranded on an older preview. Only applies while development builds are on.",
                     enabled=dev))


def report_page(token: str, via_sunshine: bool = False,
                platform: str = "") -> str:
    """Where to report a bug, in the two ways this is ever looked at.

    **On a television, through Moonlight, there is no way to get a URL out.**
    No keyboard, no address bar, nothing to copy into. So the address is a QR
    code: the phone already in your hand is the way off the screen.

    **At the machine there is a pointer**, so the first thing is a link, and
    following it opens the real browser rather than taking this window there --
    our own window hands anything that is not ours to the desktop, and a
    browser gets ``target="_blank"``. Either way the manager stays where it is.

    Both are always on the page: the detection only decides which comes first,
    so being wrong about it costs nothing.
    """
    from . import qr

    code = f'<div class="qr">{qr.svg(ISSUES_URL)}</div>'
    address = f'<p class="why"><code>{_e(ISSUES_URL)}</code></p>'
    link = (f'<div class="actions"><a class="btn" href="{_e(ISSUES_URL)}" '
            f'target="_blank" rel="noopener noreferrer">'
            f'Open the issues page</a></div>')

    if via_sunshine:
        first = (f'<section class="ok"><h2>Scan this with your phone</h2>'
                 f'<p class="why">Carry on wherever suits you. Scan this and '
                 f'the issues page opens on your phone, which has a keyboard '
                 f'and can paste a log -- neither of which a television has.'
                 f'</p>{code}{address}</section>'
                 f'<section><h2>Or, at the machine itself</h2>{link}</section>')
    else:
        first = (f'<section class="ok"><h2>Report a bug</h2>'
                 f'<p class="why">This opens the issues page in your usual '
                 f'browser. The manager stays open behind it.</p>'
                 f'{link}{address}</section>'
                 f'<section><h2>Or scan it with your phone</h2>{code}</section>')

    # What to put in the report. Asking someone at a television to go and find
    # a version string is asking them not to bother.
    opened = ("through Sunshine, on a stream" if via_sunshine
              else "at the machine")
    facts = (f'<section><h2>Worth mentioning in the report</h2><ul>'
             f'<li><span class="name">Version</span>'
             f'<span class="sel">{_e(_version_label())}</span></li>'
             f'<li><span class="name">Running on</span>'
             f'<span class="sel">{_e(platform or "unknown")}</span></li>'
             f'<li><span class="name">Opened</span>'
             f'<span class="sel">{opened}</span></li>'
             f'</ul></section>')

    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title("Report a bug")}</title><style>{_CSS}{_QR_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">
{first}
{facts}
<div class="actions"><a class="btn sec" href="/">Back to the apps</a></div>
</div></body></html>"""


def scanning_page(token: str, status: Dict[str, Any]) -> str:
    """Shown while a scan runs, which on a real library is the best part of a minute.

    It says what the scan is doing, taken from the lines the importers already
    write, because "please wait" for fifty seconds is indistinguishable from
    nothing happening -- which is exactly how it was read.

    The watcher is ``/scanning.js``, not an inline script: these pages are sent
    with ``script-src 'self'`` and an inline one is refused without a word. The
    first version of this page was inline, and it showed the scan's first line
    and then sat at "0.0s elapsed" for ever -- indistinguishable from a hang,
    which is the very thing the page exists to rule out.

    The page is its own URL rather than ``/?scan``, so a refresh watches the
    scan instead of starting another.
    """
    # Built here, not in the script, so the script holds no addresses.
    done = "/?scanned=1"
    poll = "/scan/status"
    latest = status.get("latest") or "Starting..."
    error = status.get("error") or ""
    if error:
        body = (f"""<section class="err"><h2>The scan stopped</h2>
<p class="why">{_e(error)}</p></section>""")
    else:
        body = f"""<section class="ok"><h2>Scanning your libraries</h2>
<div class="scanning" data-scan-status="{_e(poll)}" data-scan-done="{_e(done)}">
<div class="ring" aria-hidden="true"></div>
<div><p class="why" id="scan-latest">{_e(latest)}</p>
<p class="why dim"><span id="scan-elapsed">{_e(status.get('elapsed', 0))}</span>s
elapsed. Steam is quick; Heroic reads its whole library and takes the longest.</p>
</div></div></section>"""
    return f"""<!doctype html>
{_html()}<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title("Scanning")}</title><style>{_CSS}
.scanning{{display:flex;gap:1rem;align-items:center}}
.ring{{width:34px;height:34px;flex:0 0 34px;border-radius:50%;
border:3px solid rgba(128,128,128,.25);border-top-color:#ffc400;
animation:spin 900ms linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.dim{{opacity:.7;font-size:.9rem}}
</style>
<noscript><meta http-equiv="refresh" content="2"></noscript>
<script src="/scanning.js" defer></script>
</head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">App Manager</span>{_version_chip()}</div>
<div class="wrap">{body}
<div class="actions"><a class="btn sec" href="/">Stop watching</a></div>
</div></body></html>"""


def grid_page(state: Dict[str, Any], token: str, *, new_ids: Optional[set] = None,
              scanned: bool = False, auth_ok: bool = True,
              pending: Optional[List[Dict[str, Any]]] = None,
              auth_detail: str = "",
              restore: Optional[Dict[str, Any]] = None,
              rights: Any = None,
              config: Optional[Dict[str, Any]] = None) -> str:
    new_ids = new_ids or set()
    pending = pending or []
    apps = state.get("apps") or []
    hidden = state.get("hidden") or []

    # Which tile each queued operation refers to, matched the way the importer
    # matches them: by position, falling back to an unambiguous name.
    by_ident = {f'{a.get("source")}:{a.get("id")}': i
                for i, a in enumerate(apps) if a.get("source")}
    hidden_keys = {f'{h.get("source")}:{h.get("id")}' for h in hidden if h.get("source")}
    marks: Dict[int, tuple] = {}
    ghosts: List[Dict[str, Any]] = []
    restores: set = set()
    for op in pending:
        kind = str(op.get("op", ""))
        scanned_op = bool(op.get("from_scan"))

        if kind == "restore":
            restores.add(str(op.get("selector", "")))
            continue

        if kind == "rollback":
            # Not a change to one tile, so it cannot be marked on one. What it
            # would do is worked out by the importer and drawn below, in the
            # same marks and ghosts every other pending change uses.
            continue

        if kind in ("add", "clone"):
            fields = op.get("fields") or {}
            ghosts.append({"name": fields.get("name") or "(unnamed)",
                           "op": kind, "from_scan": False, "qid": op.get("qid"),
                           "image-path": fields.get("image-path") or ""})
            continue

        index = None
        key = f'{op.get("source")}:{op.get("id")}'
        if kind in ("edit", "adopt") and key in hidden_keys:
            # An edit to a hidden entry is drawn on its own tile, below.
            continue
        if key in by_ident:
            index = by_ident[key]
        else:
            candidate = op.get("index")
            if isinstance(candidate, int) and 0 <= candidate < len(apps):
                index = candidate
            else:
                names = [i for i, a in enumerate(apps)
                         if a.get("name") == op.get("name")]
                index = names[0] if len(names) == 1 else None

        if index is None:
            # Nothing on the grid yet: a game a scan just found.
            entry = op.get("entry") or {}
            ghosts.append({"name": op.get("name") or "(unnamed)", "op": kind,
                           "from_scan": scanned_op, "qid": op.get("qid"),
                           "image-path": entry.get("image-path") or ""})
        else:
            marks[index] = (kind, scanned_op)

    # A queued restore, translated into the grid's own language: what would go
    # is marked like a deletion, what would change like an edit, and what would
    # come back appears as a tile that is not there yet.
    if restore:
        by_name, by_key = {}, {}
        for position, entry in enumerate(apps):
            by_name.setdefault(entry.get("name"), position)
            if entry.get("source"):
                by_key.setdefault(f'{entry.get("source")}:{entry.get("id")}', position)

        def find(item) -> Optional[int]:
            """The tile an item refers to: by marker first, name second.

            By marker because that is how the two versions of the file were
            matched, and it survives a rename -- which is the case where
            matching on the name is guaranteed to fail.
            """
            position = by_key.get(str(item.get("key") or ""))
            if position is None:
                position = by_name.get(item.get("name"))
            return position

        for item in restore.get("going") or []:
            position = find(item)
            if position is not None:
                marks.setdefault(position, ("delete", False))
        for item in restore.get("changing") or []:
            position = find(item)
            if position is not None:
                marks.setdefault(position, ("edit", False))
        for item in restore.get("returning") or []:
            ghosts.append({"name": item.get("name") or "(unnamed)", "op": "add",
                           "from_scan": False, "qid": None, "image-path": ""})

    # 2.0 (#60): a tile carries its status twice, as a flag on the picture
    # and as the color of its name strip; a tile can carry more than one.
    edits_by_key: Dict[str, List[str]] = {}
    for op in pending:
        if str(op.get("op", "")) in ("edit", "adopt") and op.get("source"):
            edits_by_key.setdefault(f'{op.get("source")}:{op.get("id")}', []).append(str(op.get("op")))

    # Sunshine keeps apps.json sorted by name, so a hidden tile and a game a
    # scan found are drawn where they would be; what was added by hand, or
    # copied, waits at the end, beside Add, where it was asked for.
    tiles = []
    for position, entry in enumerate(apps):
        kind, scanned_op = marks.get(position, ("", False))
        tiles.append((entry.get("name") or "", tile2(entry, pending=[kind] if kind else [], from_scan=scanned_op)))
    placed = []
    for entry in hidden:
        key = f'{entry.get("source")}:{entry.get("id")}'
        if key in restores:
            placed.append((entry.get("name") or "", tile2(entry, pending=["restore"] + edits_by_key.get(key, []))))
        else:
            placed.append((entry.get("name") or "", tile2(entry, is_hidden=True)))
    at_end = []
    for ghost in ghosts:
        if ghost.get("from_scan") and ghost["op"] != "clone":
            placed.append((ghost["name"], ghost2(ghost)))
        else:
            at_end.append(ghost2(ghost))
    for name, markup in placed:
        where = next((i for i, (other, _) in enumerate(tiles) if other.casefold() > name.casefold()), len(tiles))
        tiles.insert(where, (name, markup))
    tiles = [markup for _, markup in tiles] + at_end
    tiles.append('<a class="tile add" href="/app?new=1"><span class="plus">+</span>Add an application</a>')
    queued = len(pending)

    notices = [n for n in (config_notice2(config), rights_notice2(rights, queued),
                           auth_notice2(auth_ok, auth_detail), restore_notice2(restore)) if n]

    read_only = bool(rights is not None and not rights.can_write)
    bar = ['<form method="post" action="/quit"><button class="btn sec" type="submit">Close the manager</button></form>',
           '<span class="grow"></span>',
           '<a class="btn sec" href="/backups">Restore a copy</a>',
           '<a class="btn sec" href="/?scan=1"><span class="glyph x">X</span>Rescan</a>']
    # An Apply that can only fail is worse than no Apply; and with nothing
    # queued there is nothing to apply or discard.
    if queued:
        # Read-only is not a reason to throw away what somebody typed.
        bar.append('<form method="post" action="/discard"><button class="btn sec" type="submit">Discard</button></form>')
    if queued and not read_only:
        bar.append(f'<a class="btn" href="/apply"><span class="glyph y">Y</span>'
                   f'{_e(apply_label(queued, restore))}</a>')
    # What apps.json holds now, then what is queued to appear on top of it.
    count = len(apps)
    waiting = len(ghosts) + sum(1 for h in hidden if f'{h.get("source")}:{h.get("id")}' in restores)
    heading = f'{count} application{"" if count == 1 else "s"}' + (f", {waiting} waiting" if waiting else "")
    main = (f'<main class="main">\n<div class="head"><h1>{heading}</h1>'
            f'<span class="sub"><code>{_e(state.get("apps_json", ""))}</code></span></div>\n'
            + "".join(n + "\n" for n in notices)
            + '<div class="grid">\n' + "\n".join(tiles) + '\n</div>\n</main>')
    from . import frame
    return frame.page("", main, "\n".join(bar), with_bug=True)


# ------------------------------------------------------------- 2.0 grid bits ---

WARN_SVG = ('<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<path d="M12 3 2 21h20z"/><path d="M12 10v5M12 18v.5"/></svg>')


def notice2(kind: str, title: str, text_html: str, actions_html: str = "") -> str:
    """A full-width notice above the page's content, with its own buttons."""
    cls = "notice" + (f" {kind}" if kind else "")
    icon = WARN_SVG if kind in ("warn", "err") else ""
    head = f"<b>{title}</b>" if title else ""
    return (f'<div class="{cls}">{icon}<div class="text">{head}<span>{text_html}</span></div>'
            f'{actions_html}</div>')


def apply_label(queued: int, restore: Optional[Dict[str, Any]] = None) -> str:
    return f'Apply {queued} change{"" if queued == 1 else "s"}'


def tile2(entry: Dict[str, Any], *, pending: Optional[List[str]] = None,
          is_hidden: bool = False, from_scan: bool = False) -> str:
    """One application on the 2.0 grid."""
    pending = [p for p in (pending or []) if p]
    name = _e(entry.get("name") or "(unnamed)")
    image = entry.get("image-path") or ""
    pic = (f'<img class="pic" src="/art?p={_eq(image)}" alt="">' if image
           else f'<span class="fallback">{name}</span>')
    labels = [_PENDING[p][0] for p in pending if p in _PENDING]
    greyed = any(_PENDING[p][1] for p in pending if p in _PENDING)
    if is_hidden:
        labels, tone = ["HIDDEN"], " hidden"
    elif labels:
        tone = " new" if from_scan else " pending"
    else:
        tone = ""
    classes = "tile" + tone + (" willgo" if greyed else "")
    if len(labels) > 1:
        flags = '<span class="flags">' + "".join(f'<span class="flag">{_e(l)}</span>' for l in labels) + "</span>"
    elif labels:
        flags = f'<span class="flag">{_e(labels[0])}</span>'
    else:
        flags = ""
    if entry.get("index") is not None and not is_hidden and "restore" not in pending:
        target = f'/app?index={_e(entry.get("index"))}'
    else:
        target = f'/app?hidden={_eq(str(entry.get("source")) + ":" + str(entry.get("id")))}'
    return f'<a class="{classes}" href="{target}">{flags}{pic}<span class="cap">{name}</span></a>'


def ghost2(ghost: Dict[str, Any]) -> str:
    """A tile that is not in apps.json yet: found by a scan, or added by hand."""
    name = _e(ghost["name"])
    image = ghost.get("image-path") or ""
    qid = ghost.get("qid")
    if ghost["op"] == "clone":
        label, classes = "COPY QUEUED", "tile ghost"
    elif ghost.get("from_scan"):
        label, classes = "NEW", "tile new"
    else:
        label, classes = "NEW QUEUED", "tile ghost"
    pic = (f'<img class="pic" src="/art?p={_eq(image)}" alt="">' if image
           else f'<span class="fallback">{name}</span>')
    inner = f'<span class="flag">{label}</span>{pic}<span class="cap">{name}</span>'
    if qid:
        return f'<a class="{classes}" href="/app?queued={_e(qid)}">{inner}</a>'
    return f'<span class="{classes}">{inner}</span>'


def config_notice2(config: Optional[Dict[str, Any]]) -> str:
    """config_banner's facts, as a 2.0 notice."""
    config = config or {}
    how = config.get("how")
    candidates = config.get("candidates") or []
    chosen_raw = str(config.get("chosen") or "")
    chosen = _e(chosen_raw)
    if config.get("missing"):
        missing = _e(str(config["missing"]))
        return notice2("err", "This is not the Sunshine that runs",
                       f'Sunshine is set up to use <code>{missing}</code>, which does not exist yet &mdash; '
                       f'Sunshine creates it the first time it starts. What is shown here is <code>{chosen}</code>, '
                       f'left by another install, and changes to it will do nothing. Start Sunshine once, then '
                       f'open this again.')
    if (how not in ("newest", "tie") and not config.get("stale")) or len(candidates) < 2:
        notice = str(config.get("notice") or "")
        return notice2("warn", "", _e(notice)) if notice else ""

    def form(path: str, label: str, disabled: bool = False) -> str:
        return (f'<form method="post" action="/config-dir"><input type="hidden" name="path" value="{_e(path)}">'
                f'<input type="hidden" name="back" value=""><button class="btn sec" type="submit"'
                f'{" disabled" if disabled else ""}>{label}</button></form>')

    count_queued = int(config.get("queued") or 0)
    queued = bool(count_queued)
    others = [str(c.get("path") or "") for c in candidates if str(c.get("path") or "") != chosen_raw]
    # What 1.x listed under the question, kept as sentences: which trees there
    # are and what each holds, why switching is held, and why it was refused.
    trees = []
    for c in candidates:
        apps = c.get("apps")
        count = ("apps.json unreadable" if apps is None else f"{apps} app{'' if apps == 1 else 's'}")
        trees.append(f'<code>{_e(str(c.get("path") or ""))}</code>, '
                     f'{_last_used_text(float(c.get("last_used") or 0))}, {count}')
    after = ""
    if count_queued:
        after += (f' {count_queued} change{"" if count_queued == 1 else "s"} '
                  f'{"is" if count_queued == 1 else "are"} waiting to be applied to the one in use, so switching '
                  f'waits until {"it is" if count_queued == 1 else "they are"} applied or discarded.')
    if config.get("notice"):
        after += f' <b>{_e(str(config["notice"]))}</b>'
    if config.get("stale"):
        was_raw = str(config.get("was") or "")
        was = _e(was_raw)
        title = "The config you chose earlier has been set aside"
        if config.get("stale_reason") == "running":
            why = (f"You chose <code>{was}</code>, but Sunshine is running from "
                   f"<code>{chosen}</code>, so that is the one showing.")
        elif how == "service":
            why = (f"You chose <code>{was}</code>, but another Sunshine config has been used since, so this is "
                   f"showing <code>{chosen}</code>, the one Sunshine's service starts. Choose again if that is wrong.")
        else:
            why = (f"You chose <code>{was}</code>, but another Sunshine config has been used since, so this is "
                   f"showing <code>{chosen}</code>, the one used most recently. Choose again if that is wrong.")
        other = was_raw if was_raw in others else (others[0] if others else "")
        actions = (form(other, "Use this one", disabled=queued) if other else "") + form(chosen_raw, "Keep this one")
        return notice2("warn", title, why + after, actions)
    if how == "tie":
        never = all(not c.get("last_used") for c in candidates[:2])
        reason = ("none of them has been used yet" if never else "two were last used at the same moment")
        why = (f"There is more than one Sunshine config here and nothing tells them apart: {reason}. This is "
               f"showing <code>{chosen}</code>, which is a guess. If the tiles below are not the ones you see in "
               f"Moonlight, use the other one. Found: " + "; ".join(trees) + ".")
        actions = (form(others[0], "Use this one", disabled=queued) if others else "") + form(chosen_raw, "Keep this one")
        return notice2("warn", "Which Sunshine is this machine running?", why + after, actions)
    why = ("This is showing the one Sunshine used most recently. "
           + ("The other is" if len(candidates) == 2 else "The others are")
           + " usually left behind by an install that has since been removed, and changes written there do "
             "nothing. Keep this one and you will not be asked again. Found: " + "; ".join(trees) + ".")
    actions = "".join(form(o, "Use this one", disabled=queued) for o in others) + form(chosen_raw, "Keep this one")
    return notice2("", "More than one Sunshine config here", why + after, actions)


def rights_notice2(rights: Any, queued: int) -> str:
    if rights is None or rights.can_write:
        return ""
    offer = ""
    try:
        from .privilege import can_ask_for_elevation
        if can_ask_for_elevation():
            offer = ('<form method="post" action="/elevate"><button class="btn" type="submit">'
                     'Run as administrator</button></form>')
    except Exception:                                # noqa: BLE001 - never break the page
        offer = ""
    text = _e(rights.detail)
    if queued:
        text += (f' <b>{queued} change{"" if queued == 1 else "s"} {"is" if queued == 1 else "are"} waiting</b> '
                 f'and cannot be applied until then. Nothing has been lost.')
    return notice2("err", _e(rights.headline or "Changes cannot be saved"), text, offer)


def auth_notice2(auth_ok: bool, auth_detail: str) -> str:
    if auth_ok:
        return ""
    button = '<a class="btn sec" href="/connect">Check the sign-in</a>'
    if auth_detail:
        return notice2("err", "Sunshine is not answering", _e(auth_detail), button)
    return notice2("err", "Sunshine needs sign-in", "", '<a class="btn sec" href="/connect">Connect</a>')


def restore_notice2(restore: Optional[Dict[str, Any]]) -> str:
    if not restore:
        return ""
    counts = []
    for key, word in (("returning", "would come back"), ("going", "would be removed"), ("changing", "would change")):
        items = restore.get(key) or []
        if not items:
            continue
        if key == "changing":
            said = []
            for item in items[:6]:
                name = _e(str(item.get("name")))
                becomes = item.get("becomes")
                detail = _fields_in_words(item.get("fields") or [])
                if becomes:
                    said.append(f"{name} &rarr; <b>{_e(str(becomes))}</b>" + (f" ({detail})" if detail else ""))
                else:
                    said.append(name + (f" ({detail})" if detail else ""))
            names = "; ".join(said)
        else:
            names = ", ".join(_e(str(i.get("name"))) for i in items[:6])
        if len(items) > 6:
            names += f" and {len(items) - 6} more"
        counts.append(f"<b>{len(items)}</b> {word}: {names}")
    if restore.get("hidden_now") != restore.get("hidden_then"):
        counts.append(f'What you have hidden goes from <b>{restore.get("hidden_now")}</b> to '
                      f'<b>{restore.get("hidden_then")}</b> entries')
    body = " \u00b7 ".join(counts) or "Nothing would change. This copy matches what you have now."
    body += ('</span><span style="display:block;margin-top:.2rem">Nothing has changed yet. A copy of the current '
             'file is taken before this is applied, so this can be undone the same way.')
    cancel = (f'<form method="post" action="/unqueue"><input type="hidden" name="qid" '
              f'value="{_e(restore.get("qid", ""))}"><button class="btn sec" type="submit">Cancel this restore'
              f'</button></form>')
    return notice2("warn", f'Restoring the copy from {_e(_when(restore.get("backup", "")))}', body, cancel)


# ------------------------------------------------------- app detail / edit ---

_APP_CSS = """
.edit{display:grid;gap:.9rem;max-width:44rem}
.field{display:grid;gap:.3rem}
.field label{font-size:.85rem;color:var(--text-muted);font-weight:500}
.field .hint{font-size:.8rem;color:var(--text-subtle)}
.field input[type=text]{background:var(--bg-base);color:var(--text);
border:1px solid var(--border);border-radius:var(--radius-md);
padding:.55rem .7rem;font:inherit;font-size:.95rem;width:100%}
.field input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.withbtn{display:flex;gap:.4rem;align-items:stretch}
.withbtn input{flex:1}
.withbtn .browse{white-space:nowrap;padding:.55rem .9rem}
.row{display:flex;gap:1.2rem;flex-wrap:wrap}
.check{display:flex;gap:.5rem;align-items:center;font-size:.9rem}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.preview{display:flex;gap:1rem;align-items:flex-start;margin:0 0 1.25rem}
.preview img{width:120px;aspect-ratio:2/3;object-fit:cover;
border-radius:var(--radius-md);border:1px solid var(--border)}
.preview .meta{font-size:.9rem;color:var(--text-muted)}
.preview .meta b{color:var(--text)}
.danger .btn{border-color:var(--danger);color:var(--danger);background:transparent}
.danger .btn:hover{background:var(--danger);color:#fff}
"""

# Every field Sunshine reads that is worth editing by hand, with what it means.
_FIELDS = [
    ("name", "Name", "text", "Shown in Moonlight."),
    ("cmd", "Command", "text", "Run when the app is launched. Leave empty for a desktop session."),
    ("working-dir", "Working directory", "text", "Where the command runs."),
    ("image-path", "Artwork", "text", "Path to a PNG. 600x900 matches the other tiles."),
    ("output", "Output log", "text", "File to capture the command's output. Usually empty."),
    ("exit-timeout", "Exit timeout", "text", "Seconds to wait for a clean exit before forcing it."),
]
# The tile that launches this interface, by its ownership marker rather than by
# its name -- renaming it is the one change that is allowed, so the name cannot
# be what identifies it.
PROTECTED = ("launcher", "apps-ui")

LOCK_NOTE = ("This is the tile you launch this manager from. Changing how it "
             "runs would take away the way back in: a command that no longer "
             "works, or a tile that is hidden, cannot be fixed from here, only "
             "from a terminal. Its settings are shown but cannot be edited, and "
             "it cannot be hidden, copied or deleted. Renaming it is safe, so "
             "that is allowed. To remove it, run the uninstall script.")


def is_protected(entry: Dict[str, Any]) -> bool:
    """Is this the manager's own tile?"""
    return (str(entry.get("source") or ""),
            str(entry.get("id") or "")) == PROTECTED


# Fields that name something on disk, so a picker is worth offering.
_BROWSABLE = {"cmd": "executable", "working-dir": "directory", "image-path": "any"}

_FLAGS = [
    ("elevated", "Run elevated"),
    ("auto-detach", "Auto-detach"),
    ("wait-all", "Wait for all processes"),
    ("exclude-global-prep-cmd", "Skip global prep commands"),
]


def render_fields():
    """The editable text fields, so the server can read the same set back."""
    return list(_FIELDS)


def render_browsable():
    """Which fields name something on disk, and what kind."""
    return dict(_BROWSABLE)


def render_flags():
    """The editable boolean fields."""
    return list(_FLAGS)


_PICKER_CSS = """
.crumb{color:var(--text-muted);font-family:var(--mono);font-size:.85rem;
margin:0 0 .75rem;word-break:break-all}
.listing{display:grid;gap:.3rem;max-height:60vh;overflow:auto;margin:0 0 1rem}
.listing a{display:flex;gap:.6rem;align-items:center;text-decoration:none;
color:inherit;background:var(--bg-subtle);border:1px solid var(--border);
border-radius:var(--radius-md);padding:.5rem .7rem;font-size:.92rem}
.listing a:hover,.listing a:focus-visible{border-color:var(--primary);outline:none}
.listing .k{color:var(--text-subtle);font-size:.78rem;min-width:4.5rem}
.listing a.dir .k{color:var(--accent)}
.filter{display:flex;gap:.4rem;margin:0 0 .6rem}
.filter input[type=text]{flex:1;background:var(--bg-base);color:var(--text);
border:1px solid var(--border);border-radius:var(--radius-md);
padding:.5rem .7rem;font:inherit;font-size:.92rem}
.filter input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
"""


# A directory like /usr/bin holds thousands of executables. Rendering them all
# produced a half-megabyte page, which is slow everywhere and hopeless on a
# television, so the list is capped and a filter offered instead.
PICKER_LIMIT = 250


FOLDER_SVG = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7a2 2 0 '
              '0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>')
UP_SVG = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
          '<path d="M12 19V5M5 12l7-7 7 7"/></svg>')
FILE_SVG = ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3H7a2 '
            '2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>')
PICTURES_PER_PAGE = 10         # five across, two rows (#65)
PICTURE_TYPES = (".png",)      # what Sunshine takes for a tile


def starts_with(name: str) -> str:
    """The filter key a name falls under: a letter, a digit, or "sym"."""
    first = (name or " ")[0]
    if first.isascii() and first.isalpha():
        return first.upper()
    if first.isascii() and first.isdigit():
        return first
    return "sym"


def _filter_popup(heading: str, url, chosen: str, present: set) -> str:
    """Show ... starting with, over the page: All, A to Z, Symbols, then the
    digits on their own row (#65). A key with nothing behind it is dimmed."""
    def key(value: str, label: str, wide: bool = False) -> str:
        cls = [c for c in ("wide" if wide else "", "on" if value == chosen else "",
                           "none" if value and value not in present else "") if c]
        klass = f' class="{" ".join(cls)}"' if cls else ""
        return f'<a href="{_e(url(starts=value))}"{klass}>{_e(label)}</a>'
    keys = [key("", "All", True)] + [key(c, c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    keys += [key("sym", "Symbols", True)] + [key(d, d) for d in "0123456789"]
    return (f'<div class="veil"></div>\n<div class="popup" role="dialog" aria-label="{_e(heading)}">\n'
            f'<h2>{_e(heading)}</h2>\n<nav class="letters">' + "".join(keys) + '</nav>\n'
            '<p class="muted small" style="margin:0">'
            + ('Dimmed: no picture here starts with it. Hidden files, starting with a dot, are never listed.'
               if "pictures" in heading else "Dimmed: nothing here starts with it.")
            + '</p>\n</div>')


def picker_page(listing: Dict[str, Any], token: str, *, key: str, field: str,
                label: str, error: str = "", starts: str = "", filter_open: bool = False,
                page: int = 0) -> str:
    """Choose a path, through Sunshine's own directory listing (#65).

    Folders say "folder" and files "file": Sunshine's listing has names, paths
    and types, and nothing is read here that it did not list. The filter
    narrows what is shown to names starting with one letter, digit, or
    anything else. For artwork, folders sit on the left and the pictures on
    the right as thumbnails, a page at a time.
    """
    here = str(listing.get("path") or "")
    parent = str(listing.get("parent") or "")
    entries = [e for e in (listing.get("entries") or []) if isinstance(e, dict)]
    artwork = field == "image-path"

    def url(**changes: Any) -> str:
        args = {"key": key, "field": field, "path": here, "starts": starts, "page": ""}
        args.update(changes)
        return "/browse?" + "&".join(f"{k}={_eq(str(v))}" for k, v in args.items() if v not in (None, ""))

    def pick_url(path: str) -> str:
        return f"/browse?key={_eq(key)}&field={_eq(field)}&pick={_eq(path)}"

    def item(href: str, icon: str, name: str, meta: str) -> str:
        return (f'<a class="item" href="{_e(href)}">{icon}<span class="grow"><span class="name">{_e(name)}</span>'
                f'<span class="meta">{_e(meta)}</span></span></a>')

    folders = [e for e in entries if e.get("type") == "directory"]
    files = [e for e in entries if e.get("type") != "directory"]
    if artwork:
        folders = [e for e in folders if not str(e.get("name", "")).startswith(".")]
        files = [e for e in files if not str(e.get("name", "")).startswith(".")
                 and str(e.get("name", "")).lower().endswith(PICTURE_TYPES)]
    up = item(url(path=parent, starts="", page=""), UP_SVG, "..", parent) if parent and parent != here else ""
    problem = notice2("err", "", _e(error)) + "\n" if error else ""
    word = "pictures" if artwork else "names"
    chosen_label = "All" if not starts else ("Symbols" if starts == "sym" else starts)
    filter_button = (f'<a class="btn sec filter" href="{_e(url(filter=1))}"'
                     + ('' if artwork else ' style="width:auto;margin:0 0 1.1rem;gap:2rem"')
                     + f'><span>Show {word} starting with</span><b>{_e(chosen_label)}</b></a>')
    close = (f'<a class="btn sec" href="{_e(_form_url(key, token) if not artwork else "/artwork?key=" + _eq(key))}" '
             f'data-back><span class="glyph b">B</span>Cancel</a>')

    if not artwork:
        present = {starts_with(str(e.get("name", ""))) for e in entries}
        shown = [e for e in entries if not starts or starts_with(str(e.get("name", ""))) == starts]
        rows = [up] if up else []
        for e in shown[:PICKER_LIMIT]:
            is_dir = e.get("type") == "directory"
            href = url(path=str(e.get("path") or ""), starts="", page="") if is_dir else pick_url(str(e.get("path") or ""))
            rows.append(item(href, FOLDER_SVG if is_dir else FILE_SVG, str(e.get("name") or ""),
                             "folder" if is_dir else "file"))
        total = len(entries)
        counted = f"{total} item{'' if total == 1 else 's'}"
        if starts:
            counted = f"{len(shown)} of {total} items"
        if len(shown) > PICKER_LIMIT:
            counted += f", showing the first {PICKER_LIMIT}"
        body = ("<div class=\"list\">\n" + "\n".join(rows) + "\n</div>") if rows else \
            '<div class="center"><p>Nothing here to choose.</p></div>'
        main = (f'<main class="main">\n<div class="head"><h1>Choose {_e(label)}</h1>'
                f'<span class="sub"><code>{_e(here or "/")}</code> · {counted}</span></div>\n'
                f'{problem}{filter_button}\n{body}\n</main>')
        bar = [close, '<span class="grow"></span>']
    else:
        present = {starts_with(str(e.get("name", ""))) for e in files}
        pictures = [e for e in files if not starts or starts_with(str(e.get("name", ""))) == starts]
        pages = max(1, (len(pictures) + PICTURES_PER_PAGE - 1) // PICTURES_PER_PAGE)
        page = min(max(0, page), pages - 1)
        on_page = pictures[page * PICTURES_PER_PAGE:(page + 1) * PICTURES_PER_PAGE]
        folder_rows = ([up] if up else []) + [item(url(path=str(e.get("path") or ""), starts="", page=""),
                                                   FOLDER_SVG, str(e.get("name") or ""), "folder") for e in folders]
        picks = "\n".join(
            f'<a class="pick" href="{_e(pick_url(str(e.get("path") or "")))}"><img src="/art?p={_eq(str(e.get("path") or ""))}" '
            f'alt=""><span class="fname">{_e(str(e.get("name") or ""))}</span></a>' for e in on_page)
        if pictures:
            first = page * PICTURES_PER_PAGE + 1
            shelf = (f'<div class="shelf"><h2>Pictures {first}-{first + len(on_page) - 1} of {len(pictures)}</h2>'
                     f'<div class="pages">\n{picks}\n</div></div>')
        else:
            shelf = '<div class="shelf"><h2>Pictures</h2><p class="muted">No pictures here.</p></div>'
        nf, npx = len(folders), len(files)
        counted = f"{nf} folder{'' if nf == 1 else 's'}, {npx} picture{'' if npx == 1 else 's'}"
        main = (f'<main class="main">\n<div class="head"><h1>Choose {_e(label)}</h1>'
                f'<span class="sub"><code>{_e(here or "/")}</code> · {counted}</span></div>\n{problem}'
                f'<div class="split">\n<div class="side">\n<div><h2>Folders</h2><div class="list">\n'
                + "\n".join(folder_rows) + f'\n</div></div>\n{filter_button}\n</div>\n{shelf}\n</div>\n</main>')
        flat_back = '<span class="btn sec flat"><span class="glyph wide">LB</span>Back</span>'
        flat_next = '<span class="btn sec flat"><span class="glyph wide">RB</span>Next</span>'
        prev = (f'<a class="btn sec" href="{_e(url(page=page - 1))}"><span class="glyph wide">LB</span>Back</a>'
                if page > 0 else flat_back)
        nxt = (f'<a class="btn sec" href="{_e(url(page=page + 1))}"><span class="glyph wide">RB</span>Next</a>'
               if page + 1 < pages else flat_next)
        bar = [close, '<span class="grow"></span>', prev, f'<span class="say">Page {page + 1} of {pages}</span>', nxt]

    if filter_open:
        main = main.replace("\n</main>", "\n</main>", 1)
        popup = _filter_popup(f"Show {word} starting with", url, starts, present)
        bar = [f'<a class="btn sec" href="{_e(url())}" data-back><span class="glyph b">B</span>Close</a>',
               '<span class="grow"></span>']
        html_page = frame.page("Choose " + label, main, "\n".join(bar))
        return html_page.replace("</body>", popup + "\n</body>", 1)
    return frame.page("Choose " + label, main, "\n".join(bar))


def _form_url(key: str, token: str) -> str:
    """Where a form lives, so the picker can go back to the one that opened it."""
    if key == "new":
        return f"/app?new=1"
    if key.startswith("qid:"):
        return f"/app?queued={_e(key[4:])}"
    if key.startswith("index:"):
        return f"/app?index={_e(key[6:])}"
    return f"/"


def hidden_page(entry: Dict[str, Any], token: str, queued: bool = False) -> str:
    """A hidden entry, and the way back (#75).

    Hidden entries are not in apps.json at all -- they are tombstones. One
    hidden since the whole entry was kept goes straight to its edit page when
    un-hidden; this page, queued, is for one hidden before that, which has no
    fields to show until a scan finds it again.
    """
    name = entry.get("name") or "(unnamed)"
    image = entry.get("image-path") or ""
    selector_text = f'{entry.get("source")}:{entry.get("id")}'
    art = (f'<img src="/art?p={_eq(image)}" alt="" style="width:10rem;aspect-ratio:2/3;object-fit:cover;'
           f'border-radius:var(--radius-lg);filter:grayscale(1);opacity:.45">' if image else "")
    ids = (f'<input type="hidden" name="op" value="restore">'
           f'<input type="hidden" name="selector" value="{_e(selector_text)}">')
    if queued:
        said = ('<p><b>Queued to come back.</b> Apply on the grid to make it so, then its settings can be '
                'edited like any other app.</p>')
        form = ""
        bar = ['<a class="btn sec" href="/" data-back><span class="glyph b">B</span>Back</a>',
               f'<form method="post" action="/unqueue">{ids}'
               f'<button class="btn danger" type="submit">Cancel un-hiding</button></form>',
               '<span class="grow"></span>']
    else:
        said = ('<p><b>Hidden.</b> It is not in your app list, and scanning will not bring it back. '
                'Un-hiding lets the next scan find it again.</p>')
        form = (f'<form id="unhide" method="post" action="/queue">{ids}'
                f'<input type="hidden" name="name" value="{_e(name)}"></form>\n')
        bar = ['<a class="btn sec" href="/" data-back><span class="glyph b">B</span>Back</a>',
               '<span class="grow"></span>',
               '<button class="btn" type="submit" form="unhide"><span class="glyph y">Y</span>Un-hide it</button>']
    main = (f'<main class="main">\n<div class="head"><h1>{_e(name)}</h1></div>\n'
            f'<div style="display:flex;gap:2rem;align-items:flex-start">\n{art}\n'
            f'<div style="display:flex;flex-direction:column;gap:.8rem;max-width:44rem">\n{said}\n'
            f'<p class="muted mono small">{_e(selector_text)}</p>\n</div>\n</div>\n{form}</main>')
    return frame.page(name, main, "\n".join(bar))

_ARTWORK_CSS = """
form.inline{display:inline}
.arts{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
gap:1rem;margin:0 0 1.5rem}
.arts figure{margin:0;display:flex;flex-direction:column;gap:.4rem}
.arts a{display:block;border:2px solid var(--border);border-radius:var(--radius-md);
overflow:hidden;background:var(--bg-subtle);text-decoration:none}
.arts a:hover,.arts a:focus-visible{border-color:var(--primary);outline:none}
/* The box is Steam's portrait shape, because most of what lands here is a
   Steam portrait and a ragged grid is hard to compare across. The picture
   inside it is not cropped to fit: ours are 600x800 rather than 600x900, and
   `cover` was cutting the top and bottom off the very tiles this page exists
   to let you choose between. */
.arts img{display:block;width:100%;aspect-ratio:2/3;object-fit:contain;
background:var(--bg-muted)}
.arts figcaption{font-size:.8rem;color:var(--text-muted);text-align:center;
line-height:1.3}
.arts figcaption b{display:block;color:var(--text);font-size:.85rem}
.arts .current a{border-color:var(--accent)}
.arts .current figcaption b{color:var(--accent)}
.notes{margin:0 0 1.25rem;padding:0;list-style:none}
.notes li{font-size:.9rem;color:var(--text-muted);margin:.25rem 0}
.find{display:flex;gap:.4rem;margin:0 0 1.25rem}
.find input[type=text]{flex:1;background:var(--bg-base);color:var(--text);
border:1px solid var(--border);border-radius:var(--radius-md);
padding:.5rem .7rem;font:inherit}
.find input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}

/* The SteamGridDB sheet. A real modal, with no script anywhere: the page is
   served with `script-src 'self'` and the switches taught us what happens when
   something here needs JavaScript to work at all (issue #28). So the server
   renders the dialog already open when the address says the sheet is up, and
   every control in it -- forward, back, close, choose -- is a link. A
   gamepad can reach all of them, which a JS-driven overlay cannot promise. */
/* A *definite* height, not max-height. The body below is a flex child that
   scrolls, and a scrolling child needs a parent whose height is known --
   with `height:auto` capped by `max-height`, WebKitGTK (which is the window
   this actually runs in) left the body at its zero flex basis and the whole
   grid became a 40px strip. Chrome inflated it and looked fine, which is how
   it shipped. */
/* The height cap only bites on a display taller than about 1490px -- at 1080p
   94vh is 1015 and wins. It was 1100, which made the sheet *smaller* on a 4K
   screen than on a 1080p one: fewer rows fit, so the pictures came out at 140
   where 1080p managed 164. */
dialog.sheet{position:fixed;inset:0;width:min(1500px,94vw);height:min(94vh,1400px);
max-width:100vw;max-height:100vh;margin:auto;padding:0;border:1px solid var(--border-strong);
border-radius:var(--radius-lg,12px);background:var(--bg-base);color:var(--text);
box-shadow:0 24px 60px rgba(0,0,0,.45);overflow:hidden;
display:flex;flex-direction:column;z-index:20}
dialog.sheet::backdrop{background:rgba(0,0,0,.6)}
/* ::backdrop only paints for a dialog opened by script. This one is open in
   the markup, so it gets a backdrop of its own. */
.sheet-veil{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:10}
/* The bars must not shrink, or a long grid squeezes them instead of scrolling. */
.sheet-head,.sheet-foot{flex:0 0 auto}
.sheet-head{display:flex;align-items:baseline;gap:.75rem;flex-wrap:wrap;
padding:1rem 1.25rem;border-bottom:1px solid var(--border);
background:var(--bg-subtle)}
.sheet-head h2{margin:0;font-size:1.05rem}
.sheet-head .count{font-size:.85rem;color:var(--text-muted)}
.sheet-head .shut{margin-left:auto}
/* `flex:1 1 auto` and not `flex:1`: the shorthand means basis 0%, which makes
   the body contribute no height of its own. `min-height:0` is what lets a flex
   child shrink below its content so `overflow-y` has something to do. */
/* The sheet's tiles are the interface's tiles. `.arts` above already says
   what that is -- `minmax(150px,1fr)` at 2:3, the same rule the main grid and
   the picker use -- so the sheet adds nothing about size and inherits it.
   It used to size them to fill the screen, which made them about two thirds
   the size of every other tile in the program. The maintainer, 2026-09-22: "make ALL of
   them match the size of the tiles on the main page."
   What fills the screen instead is the *number* of them: the browser measures
   how many fit and the server sends that many. So a full page still fills the
   box exactly and a short last page still leaves it visibly empty -- at the
   same tile size either way. */
.sheet-body{padding:1rem;flex:1 1 auto;min-height:0;
/* Never hidden. If the measurement is wrong, or script is off and the fallback
   page size is too big for this screen, the extra has to be reachable rather
   than clipped away. */
overflow-y:auto}
/* The tile is the *same width* as one on the main grid, not merely laid out
   by the same rule. `minmax(150px,1fr)` stretches to whatever box it is in,
   and the sheet's box is much wider than the page's 1100px wrap -- so the same
   rule would still have produced a different size. This is the main grid's
   arithmetic written out: its wrap is 1100px with 1rem of padding each side
   and 1rem gaps, which at its full width is six columns of
   (1100 - 32 - 5*16) / 6. Change either and this wants changing with it.
   Columns are then however many of those fit, centered in the sheet. */
.sheet-body .arts{margin:0;align-content:start;justify-content:center;
grid-template-columns:repeat(auto-fill,164.67px)}
/* One line of name, always. The sheet is cut to fit a measured row height,
   and a name long enough to wrap would make its row taller than that --
   the grid would overflow by a line and a scrollbar would take a column. */
.sheet-body .arts figcaption b{white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}


.sheet-foot{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;
padding:.9rem 1.25rem;border-top:1px solid var(--border);
background:var(--bg-subtle)}
.sheet-foot .where{font-size:.85rem;color:var(--text-muted);margin-left:auto}
.btn.flat{opacity:.45;pointer-events:none}
/* Waiting, with no script to animate it. The sheet is put up empty the moment
   the button is pressed and refreshes into the real results, so the wait
   happens somewhere visible instead of behind a button that looked dead.
   Issue #31. */
.sheet-wait{display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:1rem;height:100%;min-height:14rem;
color:var(--text-muted)}
.spinner{width:2.75rem;height:2.75rem;border-radius:50%;
border:4px solid var(--border);border-top-color:var(--primary);
animation:spin 900ms linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
/* Someone who has asked for less movement gets a bar that breathes instead of
   a thing that whirls. It still says "working", which is the whole job. */
@media (prefers-reduced-motion:reduce){
  .spinner{animation:none;border-top-color:var(--border);
  opacity:.6}
}
/* On a short window the bars were taking 154px of a 513px sheet -- a third of
   it, to say "From SteamGridDB" and hold two buttons. They keep their size on
   anything tall enough to spare it. */
@media (max-height:800px){
  .sheet-head{padding:.55rem .9rem}
  .sheet-foot{padding:.5rem .9rem}
  .sheet-head h2{font-size:.95rem}
  .sheet-body{padding:.8rem}
}
@media (max-width:560px){
  dialog.sheet{width:100vw;height:100vh;border-radius:0;border:0}
}
"""

# Where each candidate came from, said the way it matters to someone choosing:
# not the name of an API, but why this picture might be the right one.
_ART_SOURCES = [
    ("ours", "The tiles this program ships",
     "Both versions of this tile: the one with words on it, in the language "
     "you have chosen, and the one with none. A wordless tile is right in "
     "every language, which is why it is the one a machine gets when nobody "
     "has drawn its language yet."),
    ("steam-local", "On this machine",
     "What Steam has already downloaded for its own library. Usually the "
     "current art, because Steam keeps it up to date."),
    ("steam-cdn", "From Steam",
     "What Valve publishes today. Sometimes older than the copy above: these "
     "addresses are not always refreshed when a game's art changes."),
    ("sgdb", "From SteamGridDB",
     "Made by other people, in SteamGridDB's own order. Where to look when a game "
     "has no cover of its own."),
]



WARN_BTN_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
                'stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 21h20z"/><path d="M12 10v5M12 18v.5"/></svg>')
SGDB_PER = 30          # a page of the SteamGridDB page: three rows of ten (#64)
SGDB_SETTINGS = "/settings?section=art"


def _artwork_url(key: str, **extra: Any) -> str:
    query = "&".join(f"{k}={_eq(str(v))}" for k, v in [("key", key)] + list(extra.items()) if v not in (None, ""))
    return "/artwork?" + query


def artwork_page(candidates: List[Dict[str, Any]], token: str, *, key: str,
                 label: str, current: str = "", notes: Optional[List[str]] = None,
                 searched: str = "", error: str = "",
                 offer_sgdb: bool = False, sgdb_ready: bool = False,
                 key_refused: bool = False) -> str:
    """Choose cover art from everything that could be found for one app (#63).

    One row per source, never scrolling sideways. SteamGridDB is not here: it
    is its own page, reached by Y, and nothing is asked of it until then.
    """
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        by_source.setdefault(str(candidate.get("source")), []).append(candidate)

    def pick(candidate: Dict[str, Any]) -> str:
        path = str(candidate.get("path") or "")
        # A candidate from a network is used from the cached copy, so that is
        # what the entry points at. One of ours is used from where it already
        # lies, so the entry points at the origin instead.
        origin = str(candidate.get("origin") or "")
        is_current = bool(current) and current in (path, origin)
        href = _artwork_url(key, choose=str(candidate.get("id")), q=searched)
        return (f'<a class="pick{" current" if is_current else ""}" href="{_e(href)}">'
                f'<img src="/art?p={_eq(path)}" alt="">'
                + ('<span class="under">In use</span>' if is_current else "") + '</a>')

    sections = []
    for source, heading, why in _ART_SOURCES:
        found = by_source.get(source) or []
        if not found or source == "sgdb":
            continue
        sections.append(
            f'<section class="source"><h2>{_e(heading)} <span class="n">{len(found)}</span></h2>\n'
            f'<p class="muted small" style="margin:-.4rem 0 .7rem">{_e(why)}</p>\n'
            f'<div class="row">\n' + "\n".join(pick(c) for c in found) + '\n</div></section>')

    notices = ""
    if error:
        notices += notice2("err", "", _e(error)) + "\n"
    if key_refused:
        notices += notice2("warn", "SteamGridDB refused the saved key",
                           "It worked when it was saved, but SteamGridDB no longer accepts it. It may have been "
                           "changed or removed on your SteamGridDB account. The pictures below are unaffected.") + "\n"

    if sections:
        body = "\n".join(sections)
    else:
        # None of the sources answered is a different thing from nothing to
        # suggest, and 1.x said so; everything else gets the one sentence.
        said = next((n for n in (notes or []) if n.startswith("None of the artwork sources answered")),
                    "Nothing was found for this one. Try a different name, or browse for a file.")
        body = f'<div class="center"><p>{_e(said)}</p></div>'

    # With a mouse or keyboard, the field; with a controller, X and the
    # on-screen keyboard (osk.js opens it on the same field).
    find = (f'<form class="find" method="get" action="/artwork">'
            f'<input type="hidden" name="key" value="{_e(key)}">'
            f'<input type="text" id="q" name="q" value="{_e(searched or label)}" aria-label="Search by another name" data-osk-submit>'
            f'<button class="btn sec" type="submit">Search</button></form>')

    if key_refused:
        y = (f'<a class="btn warn" href="{SGDB_SETTINGS}"><span class="glyph y">Y</span>{WARN_BTN_SVG}'
             f'<span>Update the SteamGridDB key</span></a>')
    elif offer_sgdb:
        y = (f'<a class="btn warn" href="{SGDB_SETTINGS}"><span class="glyph y">Y</span>{WARN_BTN_SVG}'
             f'<span>Set up SteamGridDB</span></a>')
    elif sgdb_ready:
        y = (f'<a class="btn" href="{_e(_artwork_url(key, q=searched, sgdb=1))}">'
             f'<span class="glyph y">Y</span>Show SteamGridDB art</a>')
    else:
        y = ""
    bar = [f'<a class="btn sec" href="{_e(_form_url(key, token))}" data-back><span class="glyph b">B</span>Back</a>',
           f'<a class="btn sec" href="/browse?key={_eq(key)}&field=image-path">Browse for a file</a>',
           '<span class="grow"></span>',
           '<button class="btn sec padonly" type="button" data-osk-for="q"><span class="glyph x">X</span>'
           'Search by another name</button>']
    if y:
        bar.append(y)
    main = (f'<main class="main">\n<div class="head"><h1>Artwork for {_e(label)}</h1></div>\n{find}\n'
            f'{notices}{body}\n</main>')
    return frame.page("Artwork for " + label, main, "\n".join(bar))


def sgdb_artwork_page(result: Optional[Dict[str, Any]], token: str, *, key: str, searched: str,
                      label: str, current: str = "", refresh_to: str = "") -> str:
    """SteamGridDB's pictures, a page at a time (#64). It replaces 1.x's sheet.

    Drawn first with nothing in it and a spinner (result None), and the
    refresh in its head leads to the address that does the asking, so the
    wait happens on screen with no script. Then one of: the pictures, 30 to a
    page; SteamGridDB not answering, with Try again; or nothing for this one.
    A refused key never gets here: it goes back to the picker, which says so.
    """
    back = _artwork_url(key, q=searched)
    close = f'<a class="btn sec" href="{_e(back)}" data-back><span class="glyph b">B</span>Close</a>'
    flat_back = '<span class="btn sec flat"><span class="glyph wide">LB</span>Back</span>'
    flat_next = '<span class="btn sec flat"><span class="glyph wide">RB</span>Next</span>'
    head = '<div class="head"><h1>From SteamGridDB</h1>{}</div>'
    if result is None:
        main = ('<main class="main">\n' + head.format("") + '\n'
                '<div class="center"><div class="ring" aria-hidden="true"></div><p>Pulling artwork</p></div>\n</main>')
        bar = [close, '<span class="grow"></span>', flat_back, flat_next]
    elif result.get("status") == "unreachable":
        again = _artwork_url(key, q=searched, sgdb=1, sgdb_page=result.get("page") or "")
        main = ('<main class="main">\n' + head.format("") + '\n'
                '<div class="center"><svg style="width:3.4rem;height:3.4rem;color:var(--warning)" viewBox="0 0 24 24" '
                'fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3 2 21h20z"/><path d="M12 10v5M12 18v.5"/>'
                '</svg><h1>SteamGridDB did not answer</h1><p>It may be down, or this machine may be offline. '
                'Your key is fine.</p></div>\n</main>')
        bar = [close, '<span class="grow"></span>',
               f'<a class="btn" href="{_e(again)}"><span class="glyph y">Y</span>Try again</a>', flat_back, flat_next]
    elif not result.get("candidates"):
        said = str(result.get("note") or "SteamGridDB has no artwork for this one.")
        main = ('<main class="main">\n' + head.format("") + f'\n<div class="center"><p>{_e(said)}</p></div>\n</main>')
        page = int(result.get("page") or 0)
        prev = (f'<a class="btn sec" href="{_e(_artwork_url(key, q=searched, sgdb=1, sgdb_page=page - 1))}">'
                f'<span class="glyph wide">LB</span>Back</a>' if page > 0 else flat_back)
        bar = [close, '<span class="grow"></span>', prev, flat_next]
    else:
        page = int(result.get("page") or 0)
        pages = int(result.get("pages") or 1)
        total = int(result.get("total") or 0)
        found = result.get("candidates") or []
        first = page * SGDB_PER + 1
        last = first + len(found) - 1
        sub = f'<span class="sub">{first}-{last} of {total}</span>' if total else ""
        picks = "\n".join(
            f'<a class="pick" href="{_e(_artwork_url(key, choose=str(c.get("id")), q=searched))}">'
            f'<img src="/sgdb-art?id={_eq(str(c.get("id")))}" alt=""></a>' for c in found)
        main = ('<main class="main">\n' + head.format(sub) + '\n'
                '<p class="muted small" style="margin:-.6rem 0 1rem">Made by other people, in SteamGridDB\'s own order. '
                'Where to look when a game has no cover of its own.</p>\n'
                f'<div class="pages">\n{picks}\n</div>\n</main>')
        prev = (f'<a class="btn sec" href="{_e(_artwork_url(key, q=searched, sgdb=1, sgdb_page=page - 1))}">'
                f'<span class="glyph wide">LB</span>Back</a>' if page > 0 else flat_back)
        nxt = (f'<a class="btn sec" href="{_e(_artwork_url(key, q=searched, sgdb=1, sgdb_page=page + 1))}">'
               f'<span class="glyph wide">RB</span>Next</a>' if page + 1 < pages else flat_next)
        bar = [close, '<span class="grow"></span>', prev, f'<span class="say">Page {page + 1} of {max(pages, 1)}</span>', nxt]
    page_html = frame.page("From SteamGridDB", main, "\n".join(bar))
    if refresh_to:
        page_html = page_html.replace("</title>", f'</title>\n<meta http-equiv="refresh" content="0;url={_e(refresh_to)}">', 1)
    return page_html


KB_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
          'stroke-linejoin="round" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2"/>'
          '<path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M18 13h.01M9 13h6M7 16h10"/></svg>')

# Exit timeout, as the values real apps use (#61). 0 is Sunshine's "end it at
# once"; anything else already in the file shows as Custom and is kept.
EXIT_PRESETS = [(0, "Immediately"), (5, "5 seconds"), (10, "10 seconds"), (30, "30 seconds"), (60, "1 minute")]
EXIT_DEFAULT = 5
EXIT_HINT = "Seconds to wait for a clean exit before forcing it. Immediately ends it at once."

# Where each field sits on the 2.0 edit page, top to bottom. The artwork path
# is not among them: Find artwork, under the picture, is how it is chosen.
_EDIT_ORDER = ["name", "cmd", "working-dir", "exit-timeout", "flags", "output"]


def exit_timeout_value(fields: Dict[str, List[str]]) -> str:
    """The posted exit timeout: a preset, or Custom's own number."""
    chosen = (fields.get("exit-timeout") or [""])[0]
    if chosen == "custom":
        return (fields.get("exit-timeout-custom") or [""])[0].strip()
    return chosen


def keyboard_button() -> str:
    """Shown by app.js while a text field has focus, with a controller."""
    return (f'<button class="btn sec kb" type="button" style="display:none"><span class="glyph a">A</span>'
            f'{KB_SVG}<span>Keyboard</span></button>')


def _exit_timeout_field(value: Any, locked: bool) -> str:
    try:
        seconds = int(str(value).strip()) if str(value if value is not None else "").strip() else EXIT_DEFAULT
    except ValueError:
        seconds = EXIT_DEFAULT
    presets = [v for v, _ in EXIT_PRESETS]
    custom = seconds not in presets
    off = " disabled" if locked else ""
    choices = "".join(
        f'<label class="choice"><input type="radio"{off} name="exit-timeout" value="{v}"'
        f'{" checked" if (v == seconds and not custom) else ""}><b>{_e(label)}</b></label>'
        for v, label in EXIT_PRESETS)
    choices += (f'<label class="choice"><input type="radio"{off} name="exit-timeout" value="custom"'
                f'{" checked" if custom else ""}><b>Custom</b></label>')
    shown = "" if custom else ' style="display:none"'
    stepper = (f'<div class="stepper"{shown}>'
               f'<button class="btn sec" type="button" aria-label="One second less" data-step="-1">−</button>'
               f'<input type="text" inputmode="numeric" name="exit-timeout-custom" value="{seconds}" '
               f'aria-label="Seconds"{" readonly" if locked else ""}><span>seconds</span>'
               f'<button class="btn sec" type="button" aria-label="One second more" data-step="1">+</button></div>')
    return (f'<div class="field"><label>Exit timeout</label>\n<div class="choices three tight">\n'
            + choices.replace("</label><label", "</label>\n<label") + '\n</div>\n'
            + stepper + '<span></span>\n'
            f'<span class="hint">{_e(EXIT_HINT)}</span></div>')


def app_page(entry: Dict[str, Any], token: str, *, is_new: bool = False,
             queued: int = 0, warning: str = "", qid: str = "",
             queued_op: str = "", draft_key: str = "",
             dirty: bool = False, unhidden: str = "") -> str:
    """One application, with everything about it editable (#61).

    Everything except the tile this manager is launched from, which can only be
    renamed -- see LOCK_NOTE. `unhidden` is the selector of a hidden entry that
    is queued to come back: its page opens as if nothing were edited, and
    Cancel un-hiding takes the place of Hide and Delete.
    """
    name = entry.get("name") or ""
    index = entry.get("index")
    managed = bool(entry.get("managed"))
    image = entry.get("image-path") or ""
    locked = is_protected(entry) and not is_new and not qid and not unhidden
    hints = {key: hint for key, _l, _k, hint in _FIELDS}
    labels = {key: label for key, label, _k, _h in _FIELDS}
    ids = {"name": "name", "cmd": "cmd", "working-dir": "dir", "output": "log"}

    def text_field(key: str) -> str:
        value = entry.get(key)
        value = "" if value is None else str(value)
        if key in _BROWSABLE:
            button = ('<span class="btn sec flat">Browse</span>' if locked else
                      f'<button class="btn sec" type="submit" name="op" value="browse:{key}" '
                      f'formnovalidate>Browse</button>')
        else:
            button = "<span></span>"
        # "readonly" rather than "disabled": a disabled field is not submitted
        # at all, and this form writes every field back.
        ro = " readonly" if (locked and key != "name") else ""
        return (f'<div class="field"><label for="{ids[key]}">{_e(labels[key])}</label>'
                f'<input id="{ids[key]}" name="{key}" type="text" value="{_e(value)}"{ro}>{button}\n'
                f'<span class="hint">{_e(hints[key])}</span></div>')

    flags = "\n".join(
        f'<label class="switch"><input type="checkbox" name="{key}"'
        f'{" checked" if entry.get(key) else ""}{" disabled" if locked else ""}>'
        f'<span class="knob"></span><span class="t"><b>{_e(label)}</b></span></label>'
        for key, label in _FLAGS)
    rows = []
    for key in _EDIT_ORDER:
        if key == "exit-timeout":
            rows.append(_exit_timeout_field(entry.get("exit-timeout"), locked))
        elif key == "flags":
            rows.append(f'\n<div class="switches">\n{flags}\n</div>')
        else:
            rows.append(text_field(key))

    if is_new and not qid:
        heading, sub = "New application", ""
    elif unhidden:
        heading, sub = name, "Coming back when you apply. You can change it now, or leave it as it was."
    elif locked:
        heading, sub = name, ""
    elif qid:
        heading = name or "New application"
        sub = ('<b>Not added yet.</b> This is queued, so these are the values it will be written with. '
               'Apply on the grid to create it.')
    elif managed:
        heading = name
        sub = (f'Created by the importer (<code>{_e(entry.get("source"))}:{_e(entry.get("id"))}</code>). '
               f'Fields you change here are kept and it stops updating them.')
    else:
        heading, sub = name, "Yours. The importer never changes it."
    head = (f'<div class="head"><h1>{_e(heading)}</h1>'
            + (f'<span class="sub">{sub}</span>' if sub else "") + '</div>')

    notices = ""
    if locked:
        notices += notice2("warn", "", _e(LOCK_NOTE)) + "\n"
    if warning:
        notices += notice2("warn", "", _e(warning)) + "\n"

    if image:
        picture = f'<img src="/art?p={_eq(image)}" alt="">'
    else:
        picture = ('<div class="fallback" style="aspect-ratio:2/3;display:flex;align-items:center;'
                   'justify-content:center;border-radius:var(--radius-lg);background:var(--bg-muted);'
                   'color:var(--text-muted);font-weight:650"></div>')
    find = ('<span class="btn sec flat">Find artwork</span>' if locked else
            '<button class="btn sec" type="submit" name="op" value="artwork" formnovalidate>Find artwork</button>')

    if qid:
        hidden_id = f'<input type="hidden" name="qid" value="{_e(qid)}">'
    elif unhidden:
        hidden_id = (f'<input type="hidden" name="selector" value="{_e(unhidden)}">'
                     f'<input type="hidden" name="orig_name" value="{_e(name)}">')
    elif not is_new:
        hidden_id = (f'<input type="hidden" name="index" value="{_e(index)}">'
                     f'<input type="hidden" name="orig_name" value="{_e(name)}">')
    else:
        hidden_id = ""
    hidden_id += f'<input type="hidden" name="image-path" value="{_e(image)}">'

    def main_button(label: str, op: str) -> str:
        # Off until something changes (app.js), drawn flat when off.
        return (f'<button class="btn flat" type="submit" form="edit" name="op" value="{op}" data-apply disabled>'
                f'<span class="glyph y">Y</span>{_e(label)}</button>')

    def unqueue(label: str, fields: str) -> str:
        return (f'<form method="post" action="/unqueue">{fields}'
                f'<button class="btn danger" type="submit">{_e(label)}</button></form>')

    back = '<a class="btn sec" href="/" data-back><span class="glyph b">B</span>{}</a>'
    kb = keyboard_button()
    if qid:
        bar = [back.format("Back"),
               unqueue("Do not add this" if queued_op in ("adopt", "add") else "Cancel this change",
                       f'<input type="hidden" name="qid" value="{_e(qid)}">'),
               '<span class="grow"></span>', kb, main_button("Save changes", "revise")]
    elif is_new:
        bar = [back.format("Cancel"), '<span class="grow"></span>', kb, main_button("Add to the queue", "add")]
    elif unhidden:
        bar = [back.format("Back"),
               unqueue("Cancel un-hiding", f'<input type="hidden" name="op" value="restore">'
                                           f'<input type="hidden" name="selector" value="{_e(unhidden)}">'),
               '<span class="grow"></span>', kb, main_button("Apply", "edit")]
    elif locked:
        # Rename and leave. Every other way out of this page changes something
        # that would cost you the way back in.
        bar = [back.format("Back"), '<span class="grow"></span>', kb, main_button("Rename", "edit")]
    else:
        bar = [back.format("Back"),
               f'<a class="btn danger" href="/explain?op=hide&index={_e(index)}&name={_eq(name)}">Hide</a>',
               f'<a class="btn danger" href="/explain?op=delete&index={_e(index)}&name={_eq(name)}">Delete</a>',
               '<span class="grow"></span>', kb,
               '<button class="btn sec" type="submit" form="edit" name="op" value="clone">Save as a copy</button>',
               main_button("Apply", "edit")]

    marks = (' data-dirty="1"' if dirty else "") + (" data-needs-name" if is_new and not qid else "")
    main = (f'<main class="main">\n{head}\n{notices}'
            f'<form class="form" id="edit" method="post" action="/app" data-dirty-guard'
            f'{marks}>\n'
            f'{hidden_id}\n<div class="cover">\n{picture}\n{find}\n</div>\n'
            f'<div class="fields">\n' + "\n".join(rows) + '\n</div>\n</form>\n</main>')
    page = frame.page(name or "New application", main, "\n".join(bar))
    return page.replace("</body>", '<script src="/app.js"></script>\n</body>', 1)


_EXPLAIN = {
    "hide": ("Hide {name}?",
             "It disappears from the list in Moonlight. Here it stays on the grid, faded and "
             "marked HIDDEN, so you can un-hide it later. Scanning again will not bring it back. "
             "Use this for a game you own but never want to see in Moonlight.",
             "Hide it"),
    "delete": ("Delete {name}?",
               "It is removed from the list, and nothing is recorded. The next "
               "scan will find it again and add it back. Use this to start over "
               "with an entry, not to get rid of one for good.",
               "Delete it"),
}


def explain_page(op: str, entry: Dict[str, Any], token: str) -> str:
    """Before a hide or a delete: what it does, once, until told not to (#74)."""
    title, body, button = _EXPLAIN[op]
    name = entry.get("name") or ""
    title = title.format(name=name)
    image = entry.get("image-path") or ""
    art = (f'<img src="/art?p={_eq(image)}" alt="" style="width:10rem;aspect-ratio:2/3;object-fit:cover;'
           f'border-radius:var(--radius-lg)">' if image else "")
    main = (f'<main class="main">\n<div class="head"><h1>{_e(title)}</h1></div>\n'
            f'<div style="display:flex;gap:2rem;align-items:flex-start">\n{art}\n'
            f'<div style="display:flex;flex-direction:column;gap:1.2rem;max-width:44rem">\n'
            f'<p>{_e(body)}</p>\n'
            f'<label class="switch" style="max-width:30rem"><input type="checkbox" form="explain" '
            f'name="keep_explaining" checked><span class="knob"></span><span class="t"><b>Show this explanation every '
            f'time</b></span></label>\n</div>\n</div>\n'
            f'<form id="explain" method="post" action="/queue">'
            f'<input type="hidden" name="op" value="{_e(op)}">'
            f'<input type="hidden" name="index" value="{_e(entry.get("index"))}">'
            f'<input type="hidden" name="name" value="{_e(name)}"></form>\n</main>')
    bar = [f'<a class="btn sec" href="/app?index={_e(entry.get("index"))}" data-back>'
           f'<span class="glyph b">B</span>Cancel</a>',
           '<span class="grow"></span>',
           f'<button class="btn danger" type="submit" form="explain"><span class="glyph y">Y</span>'
           f'{_e(button)}</button>']
    return frame.page(title, main, "\n".join(bar))

