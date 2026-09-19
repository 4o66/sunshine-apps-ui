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
from .version import display as version_display

# What this is called, in one place. It is not an importer any more -- importing
# is one of the things it does -- and the tile it is launched from says the same.
PRODUCT = "App Manager"


def _version_chip() -> str:
    """Which build this is, in the bar, where a screenshot will catch it."""
    return f'<span class="ver">{_e(version_display())}</span>'


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
:root{
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
@media(prefers-color-scheme:dark){:root{
--primary-hover:#3d8bfd;--accent-hover:#fd9843;
--bg-base:#212529;--bg-subtle:#2c3034;--bg-muted:#383d41;--surface:#2c3034;
--border:#495057;--border-strong:#6c757d;
--text:#f8f9fa;--text-muted:#adb5bd;--text-subtle:#6c757d;
--shadow-sm:0 1px 2px 0 rgba(0,0,0,.3);
--shadow-md:0 4px 6px -1px rgba(0,0,0,.4),0 2px 4px -1px rgba(0,0,0,.3);
}}
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
<form class="creds" method="post" action="/credentials?token={_e(token)}">
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
        verb = _QUEUED_WORDING.get(str(op.get("op")), str(op.get("op")))
        name = op.get("name") or (op.get("fields") or {}).get("name") or "(unnamed)"
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
        action_block = (f'<form method="post" action="/apply?token={_e(token)}">'
                        f'<div class="actions">'
                        f'<button class="btn" type="submit">Write and reload</button>'
                        f'<a class="btn sec" href="/?token={_e(token)}">Cancel</a>'
                        f'</div></form>')
    else:
        # Applying would reload Sunshine, and reloading disconnects. Not worth
        # doing for no change, so do not offer it.
        warn_block = ""
        action_block = (f'<div class="actions">'
                        f'<a class="btn" href="/?token={_e(token)}">Back</a></div>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Apply changes')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Apply {changing} change{'' if changing == 1 else 's'}?</h1>
<section>{_queued_list(pending)
  or '<p class="why">Nothing would change.</p>'}</section>
{warn_block}
{action_block}
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
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Applied')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Applied</h1>
<section class="ok"><p class="why">apps.json was written. {_e(detail)}</p></section>
<div class="actions"><a class="btn sec" href="/?token={_e(token)}">Back to the apps</a></div>
</div></body></html>"""


def page(doc: Dict[str, Any], log: str = "", token: str = "",
         auth_ok: bool = True, auth_message: str = "", show_form: bool = False,
         applied: bool = False, apply_error: str = "") -> str:
    totals = doc.get("totals", {}) or {}
    plan = doc.get("plan", {}) or {}
    q = f"?token={_e(token)}" if token else ""

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
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title()}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}<span class="ro">read-only preview</span></div>
<div class="wrap">
<h1>{_e(summary)}</h1>
<p class="sub"><code>{_e(doc.get("apps_json", ""))}</code></p>
{_sources_bar(doc.get("sources") or [], auth_chip)}
{banner}
{form_block}
<div class="actions"><a class="btn" href="/apply{q}">Apply changes</a>
<a class="btn sec" href="/{q}">Re-scan</a></div>
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
    q = f"?token={_e(token)}" if token else ""
    extra = f"<pre>{_e(detail)}</pre>" if detail else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title()}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<section class="err"><h2>{_e(title)}</h2>
<p class="why">{_e(message)}</p>{extra}</section>
<div class="actions"><a class="btn sec" href="/{q}">Try again</a></div>
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
            f'&token={_e(token)}">See what this would change</a></div>')

    body = ("".join(rows) if rows else
            '<p class="why">No copies yet. One is taken automatically before '
            'anything is written to apps.json.</p>')
    problem = (f'<section class="err"><p class="why">{_e(error)}</p></section>'
               if error else "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Restore a copy')}</title>
<style>{_CSS}{_BACKUPS_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Restore a copy</h1>
<p class="sub">A copy of apps.json is taken before anything is written to it.
The most recent {len(copies)} are kept.</p>
{problem}
<div class="copies">{body}</div>
<p class="why">Choosing one shows what it would change on the grid. Nothing is
written until you apply it, and a copy of the current file is taken first --
so a restore can itself be undone.</p>
<div class="actions"><a class="btn sec" href="/?token={_e(token)}">Back</a></div>
</div></body></html>"""


# ---------------------------------------------------------------- the grid ---

_GRID_CSS = """
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
margin:0 0 1.5rem}
.tile{position:relative;display:block;text-decoration:none;color:inherit;
aspect-ratio:2/3;border-radius:var(--radius-lg);overflow:hidden;
background:var(--bg-subtle);border:2px solid transparent;box-shadow:var(--shadow-sm)}
.tile:hover,.tile:focus-visible{border-color:var(--primary);outline:none}
.tile img{width:100%;height:100%;object-fit:cover;display:block}
.tile .fallback{width:100%;height:100%;display:flex;align-items:center;
justify-content:center;padding:.6rem;text-align:center;font-weight:600;
font-size:.9rem;color:var(--text-muted);background:var(--bg-muted)}
.tile .cap{position:absolute;left:0;right:0;bottom:0;padding:.45rem .55rem;
font-size:.82rem;font-weight:600;color:#fff;
background:linear-gradient(transparent,rgba(0,0,0,.85))}
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
.tile.hidden .mark{position:absolute;inset:0;display:flex;align-items:center;
justify-content:center;transform:rotate(-20deg);font-size:1.1rem;font-weight:800;
letter-spacing:.1em;color:var(--text);opacity:.75;text-transform:uppercase}
.tile.add{border:2px dashed var(--border-strong);background:transparent}
.tile.add .fallback{background:transparent;color:var(--text-muted);font-size:.9rem}
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
    inner = (f'<img src="/art?p={_eq(image)}&token={_e(token)}" alt="">'
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
    target = (f'/app?index={_e(entry.get("index"))}&token={_e(token)}'
              if entry.get("index") is not None
              else f'/app?hidden={_eq(str(entry.get("source")) + ":" + str(entry.get("id")))}'
                   f'&token={_e(token)}')
    return (f'<a class="{classes}" href="{target}">{inner}{flag}{mark}'
            f'<span class="cap">{name}</span></a>')


def connect_page(token: str, message: str = "", username: str = "") -> str:
    """The credentials form on its own page, reachable from the grid."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Connect to Sunshine')}</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
{credentials_form(token, message, username)}
<div class="actions"><a class="btn sec" href="/?token={_e(token)}">Back</a></div>
</div></body></html>"""


def render_elevating(token: str) -> str:
    """Shown while Windows asks whether to allow it.

    The new instance replaces this one as any relaunch does, so this page only
    has to exist for as long as the prompt does.
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title("Administrator")}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<section class="ok"><h2>Windows is asking</h2>
<p class="why">Allow it, and the manager opens again with the rights it needs to
write <code>apps.json</code>. This window closes on its own.</p>
<p class="why">Refusing is a fine answer: everything except saving works
without it.</p></section>
<div class="actions"><a class="btn sec" href="/?token={_e(token)}">Back</a></div>
</div></body></html>"""


def grid_page(state: Dict[str, Any], token: str, *, new_ids: Optional[set] = None,
              scanned: bool = False, auth_ok: bool = True,
              pending: Optional[List[Dict[str, Any]]] = None,
              auth_detail: str = "",
              restore: Optional[Dict[str, Any]] = None,
              rights: Any = None) -> str:
    new_ids = new_ids or set()
    pending = pending or []
    apps = state.get("apps") or []
    hidden = state.get("hidden") or []

    # Which tile each queued operation refers to, matched the way the importer
    # matches them: by position, falling back to an unambiguous name.
    by_ident = {f'{a.get("source")}:{a.get("id")}': i
                for i, a in enumerate(apps) if a.get("source")}
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

    tiles = []
    for position, entry in enumerate(apps):
        kind, scanned_op = marks.get(position, ("", False))
        tiles.append(_tile(entry, token, pending=kind, from_scan=scanned_op))
    for entry in hidden:
        key = f'{entry.get("source")}:{entry.get("id")}'
        coming_back = key in restores
        tiles.append(_tile(entry, token, is_hidden=not coming_back,
                           pending="restore" if coming_back else ""))
    for ghost in ghosts:
        if ghost["op"] == "clone":
            label, tone = "COPY QUEUED", "ghost"
        elif ghost.get("from_scan"):
            label, tone = "NEW", "ghost found"
        else:
            label, tone = "NEW QUEUED", "ghost"
        art = (f'<img src="/art?p={_eq(ghost["image-path"])}&token={_e(token)}" alt="">'
               if ghost.get("image-path") else '<div class="fallback">&nbsp;</div>')
        qid = ghost.get("qid")
        target = (f'/app?queued={_e(qid)}&token={_e(token)}' if qid else "")
        open_tag = (f'<a class="tile {tone}" href="{target}">' if target
                    else f'<span class="tile {tone}">')
        close_tag = "</a>" if target else "</span>"
        tiles.append(f'{open_tag}{art}'
                     f'<span class="flag">{label}</span>'
                     f'<span class="cap">{_e(ghost["name"])}</span>{close_tag}')
    tiles.append(f'<a class="tile add" href="/app?new=1&token={_e(token)}">'
                 f'<div class="fallback">+ Add an application</div></a>')
    queued = len(pending)

    legend = ""
    parts = []
    if queued:
        parts.append('<span><i class="pend">&nbsp;</i> queued, not applied yet</span>')
    if scanned:
        parts.append('<span><i class="new">&nbsp;</i> found by the last scan</span>')
    if hidden:
        parts.append('<span><i class="hid">&nbsp;</i> hidden, will not come back</span>')
    if parts:
        legend = f'<div class="legend">{"".join(parts)}</div>'

    # A queued restore is a whole-file change, so it is said in words above the
    # grid as well as drawn on it -- including the part no tile can show.
    restore_note = ""
    if restore:
        counts = []
        for key, word in (("returning", "would come back"),
                          ("going", "would be removed"),
                          ("changing", "would change")):
            items = restore.get(key) or []
            if not items:
                continue
            if key == "changing":
                # Saying that something changes without saying what leaves you
                # to guess, and the interesting part is usually the rename.
                said = []
                for item in items[:6]:
                    name = _e(str(item.get("name")))
                    becomes = item.get("becomes")
                    detail = _fields_in_words(item.get("fields") or [])
                    if becomes:
                        line = f"{name} &rarr; <b>{_e(str(becomes))}</b>"
                        if detail:
                            line += f" ({detail})"
                    else:
                        line = f"{name}{f' ({detail})' if detail else ''}"
                    said.append(line)
                names = "; ".join(said)
            else:
                names = ", ".join(_e(str(i.get("name"))) for i in items[:6])
            if len(items) > 6:
                names += f" and {len(items) - 6} more"
            counts.append(f"<li><b>{len(items)}</b> {word}: {names}</li>")
        hidden_change = ""
        if restore.get("hidden_now") != restore.get("hidden_then"):
            hidden_change = (f'<li>What you have hidden goes from '
                             f'<b>{restore.get("hidden_now")}</b> to '
                             f'<b>{restore.get("hidden_then")}</b> entries</li>')
        body = "".join(counts) + hidden_change
        if not body:
            body = "<li>Nothing would change. This copy matches what you have now.</li>"
        restore_note = (
            f'<section class="warn"><h2>Restoring the copy from '
            f'{_e(_when(restore.get("backup", "")))}</h2>'
            f'<ul class="why">{body}</ul>'
            f'<p class="why">Nothing has changed yet. A copy of the current file '
            f'is taken before this is applied, so this can be undone the same way.</p>'
            f'<div class="actions">'
            f'<form method="post" action="/unqueue?token={_e(token)}">'
            f'<input type="hidden" name="qid" value="{_e(restore.get("qid", ""))}">'
            f'<button class="btn sec" type="submit">Cancel this restore</button>'
            f'</form></div></section>')

    outstanding = queued
    read_only = bool(rights is not None and not rights.can_write)
    # An Apply that can only fail is worse than no Apply: it loses the queue's
    # meaning and teaches people the tool is broken rather than unprivileged.
    apply_button = (f'<a class="btn" href="/apply?token={_e(token)}">'
                    f'Apply {outstanding} change{"" if outstanding == 1 else "s"}</a>'
                    if outstanding and not read_only else "")
    discard_button = (f'<form method="post" action="/discard?token={_e(token)}" '
                      f'style="display:inline">'
                      f'<button class="btn sec" type="submit">Discard</button></form>'
                      if queued else "")
    # Not every failure is a sign-in failure. Saying so sent me looking at
    # credentials when apps.json held a value Sunshine could not parse.
    if auth_ok:
        auth_note = ""
    elif auth_detail:
        auth_note = (f'<section class="err"><h2>Sunshine is not answering</h2>'
                     f'<p class="why">{_e(auth_detail)}</p>'
                     f'<div class="actions"><a class="btn sec" '
                     f'href="/connect?token={_e(token)}">Check the sign-in</a>'
                     f'</div></section>')
    else:
        auth_note = (f'<div class="bar"><span class="chip">'
                     f'<span class="dot error"></span><b>sunshine</b> needs sign-in</span>'
                     f'<a class="chip" style="text-decoration:none;color:var(--primary)" '
                     f'href="/connect?token={_e(token)}">Connect</a></div>')

    # Said here, once, on the page someone is already looking at -- not at the
    # write, after a dozen changes are queued. See privilege.py.
    rights_note = ""
    if read_only:
        # An offer, where there is one to make. Saying "you cannot do this" and
        # stopping is what made this warn and then do nothing: the change was
        # taken, queued, and left with no way to apply it.
        offer = ""
        try:
            from .privilege import can_ask_for_elevation
            if can_ask_for_elevation():
                offer = (f'<div class="actions">'
                         f'<form method="post" action="/elevate?token={_e(token)}" '
                         f'style="display:inline">'
                         f'<button class="btn" type="submit">Run as administrator</button>'
                         f'</form></div>')
        except Exception:                        # noqa: BLE001 - never break the page
            offer = ""
        queued_note = ""
        if queued:
            queued_note = (f'<p class="why"><b>{queued} change'
                           f'{"" if queued == 1 else "s"} '
                           f'{"is" if queued == 1 else "are"} waiting</b> and cannot '
                           f'be applied until then. Nothing has been lost.</p>')
        rights_note = (f'<section class="err"><h2>{_e(rights.headline or "Changes cannot be saved")}</h2>'
                       f'<p class="why">{_e(rights.detail)}</p>{queued_note}{offer}</section>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title()}</title><style>{_CSS}{_GRID_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>{len(apps)} application{'' if len(apps) == 1 else 's'}</h1>
<p class="sub"><code>{_e(state.get("apps_json", ""))}</code></p>
{rights_note}{auth_note}{restore_note}
<div class="actions">{apply_button}{discard_button}
<a class="btn{'' if not queued else ' sec'}" href="/?scan=1&token={_e(token)}">Rescan</a>
<a class="btn sec" href="/backups?token={_e(token)}">Restore a copy</a></div>
{legend}
<div class="grid">{"".join(tiles)}</div>
</div></body></html>"""


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


def picker_page(listing: Dict[str, Any], token: str, *, key: str, field: str,
                label: str, error: str = "", filter_text: str = "") -> str:
    """Choose a path, through Sunshine's own directory listing."""
    here = str(listing.get("path") or "")
    parent = str(listing.get("parent") or "")
    entries = [e for e in (listing.get("entries") or []) if isinstance(e, dict)]

    total = len(entries)
    needle = filter_text.strip().lower()
    if needle:
        entries = [e for e in entries if needle in str(e.get("name", "")).lower()]
    matched = len(entries)
    entries = entries[:PICKER_LIMIT]

    def link(path: str, name: str, is_dir: bool) -> str:
        what = "go" if is_dir else "pick"
        return (f'<a class="{"dir" if is_dir else "file"}" '
                f'href="/browse?key={_eq(key)}&field={_eq(field)}'
                f'&{"path" if is_dir else "pick"}={_eq(path)}&token={_e(token)}">'
                f'<span class="k">{"folder" if is_dir else "choose"}</span>'
                f'<span>{_e(name)}</span></a>')

    rows = []
    if parent and parent != here:
        rows.append(link(parent, "..", True))
    for item in entries:
        if not isinstance(item, dict):
            continue
        rows.append(link(str(item.get("path") or ""), str(item.get("name") or ""),
                         item.get("type") == "directory"))

    body = ("".join(rows) if rows
            else '<p class="why">Nothing here to choose.</p>')
    problem = f'<section class="err"><p class="why">{_e(error)}</p></section>' if error else ""

    shown = len(entries)
    if needle:
        counted = f"{matched} of {total} match &ldquo;{_e(filter_text)}&rdquo;"
    else:
        counted = f"{total} item{'' if total == 1 else 's'}"
    if matched > shown:
        counted += f", showing the first {shown}"

    search = (f'<form class="filter" method="get" action="/browse">'
              f'<input type="hidden" name="key" value="{_e(key)}">'
              f'<input type="hidden" name="field" value="{_e(field)}">'
              f'<input type="hidden" name="path" value="{_e(here)}">'
              f'<input type="hidden" name="token" value="{_e(token)}">'
              f'<input type="text" name="q" value="{_e(filter_text)}" '
              f'placeholder="Filter by name" aria-label="Filter by name">'
              f'<button class="btn sec" type="submit">Filter</button></form>'
              f'<p class="crumb">{counted}</p>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Choose ' + _e(label))}</title>
<style>{_CSS}{_APP_CSS}{_PICKER_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Choose {_e(label)}</h1>
{problem}
<p class="crumb">{_e(here or "/")}</p>
{search}
<div class="listing">{body}</div>
<div class="actions">
<a class="btn sec" href="{_e(_form_url(key, token))}">Cancel</a></div>
</div></body></html>"""


def _form_url(key: str, token: str) -> str:
    """Where a form lives, so the picker can go back to the one that opened it."""
    if key == "new":
        return f"/app?new=1&token={_e(token)}"
    if key.startswith("qid:"):
        return f"/app?queued={_e(key[4:])}&token={_e(token)}"
    if key.startswith("index:"):
        return f"/app?index={_e(key[6:])}&token={_e(token)}"
    return f"/?token={_e(token)}"


def hidden_page(entry: Dict[str, Any], token: str, queued: bool = False) -> str:
    """A hidden entry, and the way back.

    Hidden entries are not in apps.json at all -- they are tombstones -- so they
    have none of the fields the edit screen shows. What they have is a way to
    stop being hidden.
    """
    name = entry.get("name") or "(unnamed)"
    image = entry.get("image-path") or ""
    art = (f'<img src="/art?p={_eq(image)}&token={_e(token)}" alt="">'
           if image else "")
    selector_text = f'{entry.get("source")}:{entry.get("id")}'

    if queued:
        # Every page needs a way out, and a queued change needs a way to undo
        # the queueing -- otherwise the only route back is the browser button.
        action = (f'<p class="why">Queued to come back. Apply on the grid to make '
                  f'it so, then its settings can be edited like any other app.</p>'
                  f'<form method="post" action="/unqueue?token={_e(token)}">'
                  f'<input type="hidden" name="op" value="restore">'
                  f'<input type="hidden" name="selector" value="{_e(selector_text)}">'
                  f'<div class="actions">'
                  f'<button class="btn sec" type="submit">Cancel un-hiding</button>'
                  f'<a class="btn" href="/?token={_e(token)}">Back to the apps</a>'
                  f'</div></form>')
    else:
        action = (f'<form method="post" action="/queue?token={_e(token)}">'
                  f'<input type="hidden" name="op" value="restore">'
                  f'<input type="hidden" name="selector" value="{_e(selector_text)}">'
                  f'<input type="hidden" name="name" value="{_e(name)}">'
                  f'<div class="actions">'
                  f'<button class="btn" type="submit">Un-hide it</button>'
                  f'<a class="btn sec" href="/?token={_e(token)}">Back</a></div></form>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title(_e(name))}</title><style>{_CSS}{_APP_CSS}{_GRID_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>{_e(name)}</h1>
<div class="preview">{art}<div class="meta">
<b>Hidden.</b> It is not in your app list, and scanning will not bring it back.
Un-hiding lets the next scan find it again.<br>
<span class="sel">{_e(selector_text)}</span></div></div>
{action}
</div></body></html>"""



_ARTWORK_CSS = """
.arts{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
gap:1rem;margin:0 0 1.5rem}
.arts figure{margin:0;display:flex;flex-direction:column;gap:.4rem}
.arts a{display:block;border:2px solid var(--border);border-radius:var(--radius-md);
overflow:hidden;background:var(--bg-subtle);text-decoration:none}
.arts a:hover,.arts a:focus-visible{border-color:var(--primary);outline:none}
.arts img{display:block;width:100%;aspect-ratio:2/3;object-fit:cover}
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
"""

# Where each candidate came from, said the way it matters to someone choosing:
# not the name of an API, but why this picture might be the right one.
_ART_SOURCES = [
    ("steam-local", "On this machine",
     "What Steam has already downloaded for its own library. Usually the "
     "current art, because Steam keeps it up to date."),
    ("steam-cdn", "From Steam",
     "What Valve publishes today. Sometimes older than the copy above: these "
     "addresses are not always refreshed when a game's art changes."),
    ("sgdb", "From SteamGridDB",
     "Made by other people and voted on, best first. Where to look when a game "
     "has no cover of its own."),
]


def artwork_page(candidates: List[Dict[str, Any]], token: str, *, key: str,
                 label: str, current: str = "", notes: Optional[List[str]] = None,
                 searched: str = "", error: str = "") -> str:
    """Choose cover art from everything that could be found for one app."""
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        by_source.setdefault(str(candidate.get("source")), []).append(candidate)

    def tile(candidate: Dict[str, Any]) -> str:
        path = str(candidate.get("path") or "")
        is_current = bool(current) and path == current
        return (f'<figure class="{"current" if is_current else ""}">'
                f'<a href="/artwork?key={_eq(key)}&choose={_eq(str(candidate.get("id")))}'
                f'&q={_eq(searched)}&token={_e(token)}">'
                f'<img src="/art?p={_eq(path)}&token={_e(token)}" alt=""></a>'
                f'<figcaption><b>{_e(str(candidate.get("label") or ""))}</b>'
                f'{"in use" if is_current else "choose"}</figcaption></figure>')

    sections = []
    for source, heading, why in _ART_SOURCES:
        found = by_source.get(source) or []
        if not found:
            continue
        sections.append(
            f'<h2>{_e(heading)}</h2><p class="why">{_e(why)}</p>'
            f'<div class="arts">{"".join(tile(c) for c in found)}</div>')

    if not sections:
        sections.append('<p class="why">Nothing was found for this one. '
                        'Try a different name, or browse for a file.</p>')

    note_items = "".join(f"<li>{_e(n)}</li>" for n in (notes or []))
    note_list = f'<ul class="notes">{note_items}</ul>' if note_items else ""
    problem = (f'<section class="err"><p class="why">{_e(error)}</p></section>'
               if error else "")

    # Searching by a different name is the way out of a title that does not
    # match what SteamGridDB calls it -- an edition, a subtitle, a re-release.
    find = (f'<form class="find" method="get" action="/artwork">'
            f'<input type="hidden" name="key" value="{_e(key)}">'
            f'<input type="hidden" name="token" value="{_e(token)}">'
            f'<input type="text" name="q" value="{_e(searched)}" '
            f'placeholder="Search by another name" aria-label="Search by another name">'
            f'<button class="btn sec" type="submit">Search</button></form>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title('Artwork for ' + _e(label))}</title>
<style>{_CSS}{_APP_CSS}{_ARTWORK_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>Artwork for {_e(label)}</h1>
{problem}{note_list}{find}
{"".join(sections)}
<div class="actions">
<a class="btn sec" href="{_e(_form_url(key, token))}">Back</a>
<a class="btn sec" href="/browse?key={_eq(key)}&field=image-path&token={_e(token)}">
Browse for a file</a></div>
</div></body></html>"""


def app_page(entry: Dict[str, Any], token: str, *, is_new: bool = False,
             queued: int = 0, warning: str = "", qid: str = "",
             queued_op: str = "", draft_key: str = "",
             dirty: bool = False) -> str:
    """One application, with everything about it editable.

    Everything except the tile this manager is launched from, which can only be
    renamed -- see LOCK_NOTE.
    """
    name = entry.get("name") or ""
    index = entry.get("index")
    managed = bool(entry.get("managed"))
    image = entry.get("image-path") or ""
    locked = is_protected(entry) and not is_new and not qid

    fields = []
    for key, label, _kind, hint in _FIELDS:
        value = entry.get(key)
        value = "" if value is None else str(value)
        if locked and key != "name":
            # Shown, so it can be read, but not editable. "readonly" rather than
            # "disabled" on purpose: a disabled field is not submitted at all,
            # and this form writes every field back.
            fields.append(
                f'<div class="field"><label for="f_{key}">{_e(label)}</label>'
                f'<input id="f_{key}" name="{key}" type="text" value="{_e(value)}" '
                f'readonly tabindex="-1">'
                f'<span class="hint">{_e(hint)}</span></div>')
            continue
        browse = ""
        if key in _BROWSABLE:
            browse = (f'<button class="btn sec browse" type="submit" '
                      f'name="op" value="browse:{key}" formnovalidate>Browse</button>')
        if key == "image-path":
            # Typing a path is the fallback here, not the main way: almost
            # nobody knows where a cover lives, but everybody knows one when
            # they see it.
            browse = (f'<button class="btn sec browse" type="submit" '
                      f'name="op" value="artwork" formnovalidate>Find artwork'
                      f'</button>') + browse
        fields.append(
            f'<div class="field"><label for="f_{key}">{_e(label)}</label>'
            f'<div class="withbtn">'
            f'<input id="f_{key}" name="{key}" type="text" value="{_e(value)}">'
            f'{browse}</div>'
            f'<span class="hint">{_e(hint)}</span></div>')
    flags = "".join(
        f'<label class="check"><input type="checkbox" name="{key}"'
        f'{" checked" if entry.get(key) else ""}'
        f'{" disabled" if locked else ""}> {_e(label)}</label>'
        for key, label in _FLAGS)

    preview = ""
    if not is_new or qid:
        art = (f'<img src="/art?p={_eq(image)}&token={_e(token)}" alt="">'
               if image else "")
        if qid:
            origin = ('<b>Not added yet.</b> This is queued, so these are the values '
                      'it will be written with. Apply on the grid to create it.')
        elif managed:
            origin = (f'Created by the importer (<code>{_e(entry.get("source"))}:'
                      f'{_e(entry.get("id"))}</code>). Fields you change here are kept '
                      f'and it stops updating them.')
        else:
            origin = "Yours. The importer never changes it."
        preview = (f'<div class="preview">{art}<div class="meta">{origin}</div></div>')

    warn = (f'<section class="warn"><p>{_e(warning)}</p></section>' if warning else "")
    if locked:
        warn = f'<section class="warn"><p>{_e(LOCK_NOTE)}</p></section>' + warn

    if qid:
        hidden_id = f'<input type="hidden" name="qid" value="{_e(qid)}">'
    elif not is_new:
        hidden_id = (f'<input type="hidden" name="index" value="{_e(index)}">'
                     f'<input type="hidden" name="orig_name" value="{_e(name)}">')
    else:
        hidden_id = ""

    if qid:
        # A change that has not happened yet: saving revises it in place, and
        # the only destructive option is to drop it from the queue.
        actions = (f'<button class="btn" data-apply type="submit" name="op" '
                   f'value="revise">Save changes</button>'
                   f'<a class="btn sec" href="/?token={_e(token)}">Back</a>')
        extra = (f'<div class="actions danger">'
                 f'<form method="post" action="/unqueue?token={_e(token)}">'
                 f'<input type="hidden" name="qid" value="{_e(qid)}">'
                 f'<button class="btn" type="submit">'
                 f'{"Do not add this" if queued_op in ("adopt", "add") else "Cancel this change"}'
                 f'</button></form></div>')
    elif is_new:
        actions = (f'<button class="btn" data-apply type="submit" name="op" value="add">'
                   f'Add to the queue</button>'
                   f'<a class="btn sec" href="/?token={_e(token)}">Cancel</a>')
        extra = ""
    elif locked:
        # Rename and leave. Every other way out of this page changes something
        # that would cost you the way back in.
        actions = (f'<button class="btn" data-apply type="submit" name="op" value="edit">'
                   f'Rename</button>'
                   f'<a class="btn sec" href="/?token={_e(token)}">Back</a>')
        extra = ""
    else:
        actions = (f'<button class="btn" data-apply type="submit" name="op" value="edit">'
                   f'Apply</button>'
                   f'<button class="btn sec" type="submit" name="op" value="clone">'
                   f'Save as a copy</button>'
                   f'<a class="btn sec" href="/?token={_e(token)}">Back</a>')
        extra = (f'<div class="actions danger">'
                 f'<a class="btn" href="/explain?op=hide&index={_e(index)}'
                 f'&name={_eq(name)}&token={_e(token)}">Hide</a>'
                 f'<a class="btn" href="/explain?op=delete&index={_e(index)}'
                 f'&name={_eq(name)}&token={_e(token)}">Delete</a></div>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title(_e(name or "New application"))}</title>
<style>{_CSS}{_APP_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>{_e(name or "New application")}</h1>
{preview}{warn}
<form class="edit" method="post" action="/app?token={_e(token)}" data-dirty-guard{' data-dirty="1"' if dirty else ''}>
{hidden_id}
{"".join(fields)}
<div class="row">{flags}</div>
<div class="actions">{actions}</div>
</form>
{extra}
</div>
<script src="/app.js?token={_e(token)}"></script>
</body></html>"""


_EXPLAIN = {
    "hide": ("Hide this application?",
             "It is removed from the list and recorded as hidden, so scanning "
             "again will not bring it back. Use this for a game you own but "
             "never want to see here.",
             "Hide it"),
    "delete": ("Delete this application?",
               "It is removed from the list, and nothing is recorded. The next "
               "scan will find it again and add it back. Use this to start over "
               "with an entry, not to get rid of one for good.",
               "Delete it"),
}


def explain_page(op: str, entry: Dict[str, Any], token: str) -> str:
    title, body, button = _EXPLAIN[op]
    name = entry.get("name") or ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_title(_e(title))}</title><style>{_CSS}{_APP_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">app manager</span>{_version_chip()}</div>
<div class="wrap">
<h1>{_e(title)}</h1>
<section><p class="why"><b>{_e(name)}</b> &mdash; {_e(body)}</p></section>
<form method="post" action="/queue?token={_e(token)}">
<input type="hidden" name="op" value="{_e(op)}">
<input type="hidden" name="index" value="{_e(entry.get('index'))}">
<input type="hidden" name="name" value="{_e(name)}">
<label class="check" style="margin:.5rem 0 1rem">
<input type="checkbox" name="keep_explaining" checked> Show this explanation every time</label>
<div class="actions danger">
<button class="btn" type="submit">{_e(button)}</button>
<a class="btn sec" style="border-color:var(--primary);color:var(--primary)"
   href="/app?index={_e(entry.get('index'))}&token={_e(token)}">Cancel</a></div>
</form>
</div></body></html>"""

