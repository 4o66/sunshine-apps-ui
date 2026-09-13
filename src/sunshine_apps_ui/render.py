"""Rendering the plan document as a page.

Server-rendered on purpose: no fetch, no token in JavaScript, and every control
is a real link, which is what makes it navigable by keyboard and by a gamepad
mapped to arrows and Enter.
"""

import html
from typing import Any, Dict, List, Optional

from . import __version__

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
.navbar .ro{margin-left:auto;color:var(--navbar-text-muted);font-size:.82rem;
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
.edit{border-left:3px solid var(--warning)}
.edit .d{width:100%;font-size:.85rem;font-family:var(--mono);color:var(--text-muted);margin-top:.2rem}
.edit .d b{color:var(--text);font-weight:600}

a.btn{display:inline-block;background:var(--primary);color:#fff;text-decoration:none;
border:1px solid var(--primary);border-radius:var(--radius-md);padding:.65rem 1.1rem;
font-weight:500;font-size:.95rem;transition:background 150ms ease}
a.btn:hover{background:var(--primary-hover);border-color:var(--primary-hover)}
a.btn.sec{background:transparent;color:var(--primary)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.actions{display:flex;gap:.6rem;flex-wrap:wrap;margin:0 0 1.25rem}

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
form{display:grid;gap:.4rem;max-width:26rem;margin:.5rem 0 1rem}
form label{font-size:.85rem;color:var(--text-muted);font-weight:500}
form input{background:var(--bg-base);color:var(--text);border:1px solid var(--border);
border-radius:var(--radius-md);padding:.6rem .7rem;font:inherit;font-size:.95rem}
form input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
form button{margin-top:.5rem;background:var(--primary);color:#fff;border:1px solid var(--primary);
border-radius:var(--radius-md);padding:.65rem 1.1rem;font:inherit;font-weight:500;cursor:pointer}
form button:hover{background:var(--primary-hover)}
form button:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.note{color:var(--text-muted);font-size:.85rem;margin-top:1.75rem;
border-top:1px solid var(--border);padding-top:.9rem}
@media(max-width:520px){.wrap{padding:1rem .75rem 3rem}li{flex-direction:column;gap:.15rem}
.navbar .ro{margin-left:0;width:100%}}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


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
        return f'<li class="edit"><span class="name">{name}</span>{sel}{rows}</li>'

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
<form method="post" action="/credentials?token={_e(token)}">
<label for="u">Username</label>
<input id="u" name="username" autocomplete="username" value="{_e(username)}" required autofocus>
<label for="p">Password</label>
<input id="p" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Verify and save</button>
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


def confirm_page(doc: Dict[str, Any], token: str, via_sunshine: bool = False) -> str:
    """The step between wanting to apply and applying.

    Applying reloads Sunshine, which ends any stream in progress. That is not a
    malfunction -- it is how the new list reaches Moonlight -- but it should be
    stated before it happens rather than discovered.
    """
    plan = doc.get("plan", {}) or {}
    totals = doc.get("totals", {}) or {}
    changing = sum(int(totals.get(k, 0)) for k in ("added", "updated", "pruned"))

    if via_sunshine:
        warning = ("<p><b>This will disconnect you.</b> Sunshine has to reload its app "
                   "list, which ends the stream you are watching this through. You will "
                   "return to Moonlight, where the new games should appear in the next "
                   "30 seconds.</p>")
    else:
        warning = ("<p>Sunshine will reload its app list. Any stream in progress will "
                   "disconnect and return to Moonlight, where the new games should "
                   "appear in the next 30 seconds.</p>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Apply changes</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps import</span></div>
<div class="wrap">
<h1>Apply {changing} change{'' if changing == 1 else 's'}?</h1>
<section>{_change_list(plan) or '<p class="why">Nothing would change.</p>'}</section>
<section class="warn">{warning}</section>
<form method="post" action="/apply?token={_e(token)}">
<div class="actions">
<button type="submit">Write and reload</button>
<a class="btn sec" href="/?token={_e(token)}">Cancel</a>
</div>
</form>
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
<title>Sunshine apps</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps import</span><span class="ro">read-only preview</span></div>
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


def error_page(message: str, detail: str = "", token: str = "") -> str:
    q = f"?token={_e(token)}" if token else ""
    extra = f"<pre>{_e(detail)}</pre>" if detail else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sunshine apps</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps import</span></div>
<div class="wrap">
<section class="err"><h2>Could not read a plan</h2>
<p class="why">{_e(message)}</p>{extra}</section>
<div class="actions"><a class="btn sec" href="/{q}">Try again</a></div>
</div></body></html>"""
