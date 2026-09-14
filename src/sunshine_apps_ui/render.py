"""Rendering the plan document as a page.

Server-rendered on purpose: no fetch, no token in JavaScript, and every control
is a real link, which is what makes it navigable by keyboard and by a gamepad
mapped to arrows and Enter.
"""

import html
from urllib.parse import quote
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
.navbar .ro{margin-left:0;width:100%}}
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

    Applying reloads Sunshine, which ends any stream in progress. That is not a
    malfunction -- it is how the new list reaches Moonlight -- but it should be
    stated before it happens rather than discovered.
    """
    pending = pending or []
    plan = doc.get("plan", {}) or {}
    totals = doc.get("totals", {}) or {}
    # Both kinds of pending change count: the ones you queued by hand, and the
    # ones a scan found. Counting only the second is what made this read zero.
    changing = len(pending) + sum(int(totals.get(k, 0))
                                  for k in ("added", "updated", "pruned"))

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
<title>Apply changes</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps import</span></div>
<div class="wrap">
<h1>Apply {changing} change{'' if changing == 1 else 's'}?</h1>
<section>{_queued_list(pending)}{_change_list(plan)
  or ('' if pending else '<p class="why">Nothing would change.</p>')}</section>
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
<title>Applied</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps import</span></div>
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


def error_page(message: str, detail: str = "", token: str = "",
               title: str = "Something went wrong") -> str:
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
<section class="err"><h2>{_e(title)}</h2>
<p class="why">{_e(message)}</p>{extra}</section>
<div class="actions"><a class="btn sec" href="/{q}">Try again</a></div>
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
<title>Connect to Sunshine</title><style>{_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps</span></div>
<div class="wrap">
{credentials_form(token, message, username)}
<div class="actions"><a class="btn sec" href="/?token={_e(token)}">Back</a></div>
</div></body></html>"""


def grid_page(state: Dict[str, Any], token: str, *, new_ids: Optional[set] = None,
              scanned: bool = False, auth_ok: bool = True,
              pending: Optional[List[Dict[str, Any]]] = None,
              auth_detail: str = "") -> str:
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

    outstanding = queued
    apply_button = (f'<a class="btn" href="/apply?token={_e(token)}">'
                    f'Apply {outstanding} change{"" if outstanding == 1 else "s"}</a>'
                    if outstanding else "")
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

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sunshine apps</title><style>{_CSS}{_GRID_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps</span></div>
<div class="wrap">
<h1>{len(apps)} application{'' if len(apps) == 1 else 's'}</h1>
<p class="sub"><code>{_e(state.get("apps_json", ""))}</code></p>
{auth_note}
<div class="actions">{apply_button}{discard_button}
<a class="btn{'' if not queued else ' sec'}" href="/?scan=1&token={_e(token)}">Rescan</a></div>
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
_FLAGS = [
    ("elevated", "Run elevated"),
    ("auto-detach", "Auto-detach"),
    ("wait-all", "Wait for all processes"),
    ("exclude-global-prep-cmd", "Skip global prep commands"),
]


def render_fields():
    """The editable text fields, so the server can read the same set back."""
    return list(_FIELDS)


def render_flags():
    """The editable boolean fields."""
    return list(_FLAGS)


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
<title>{_e(name)}</title><style>{_CSS}{_APP_CSS}{_GRID_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps</span></div>
<div class="wrap">
<h1>{_e(name)}</h1>
<div class="preview">{art}<div class="meta">
<b>Hidden.</b> It is not in your app list, and scanning will not bring it back.
Un-hiding lets the next scan find it again.<br>
<span class="sel">{_e(selector_text)}</span></div></div>
{action}
</div></body></html>"""


def app_page(entry: Dict[str, Any], token: str, *, is_new: bool = False,
             queued: int = 0, warning: str = "", qid: str = "",
             queued_op: str = "") -> str:
    """One application, with everything about it editable."""
    name = entry.get("name") or ""
    index = entry.get("index")
    managed = bool(entry.get("managed"))
    image = entry.get("image-path") or ""

    fields = []
    for key, label, _kind, hint in _FIELDS:
        value = entry.get(key)
        value = "" if value is None else str(value)
        fields.append(
            f'<div class="field"><label for="f_{key}">{_e(label)}</label>'
            f'<input id="f_{key}" name="{key}" type="text" value="{_e(value)}">'
            f'<span class="hint">{_e(hint)}</span></div>')
    flags = "".join(
        f'<label class="check"><input type="checkbox" name="{key}"'
        f'{" checked" if entry.get(key) else ""}> {_e(label)}</label>'
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
<title>{_e(name or "New application")}</title>
<style>{_CSS}{_APP_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps</span></div>
<div class="wrap">
<h1>{_e(name or "New application")}</h1>
{preview}{warn}
<form class="edit" method="post" action="/app?token={_e(token)}" data-dirty-guard>
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
<title>{_e(title)}</title><style>{_CSS}{_APP_CSS}</style></head>
<body>
<div class="navbar"><span class="brand">Sunshine</span><span class="sep">/</span>
<span class="where">apps</span></div>
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

