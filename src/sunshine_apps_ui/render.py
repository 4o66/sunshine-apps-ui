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
    ("kept_foreign", "Not ours", "Sunshine's defaults and entries you created. Never touched."),
]

STATUS_NOTE = {
    "ok": "scanned",
    "not_found": "not installed here",
    "disabled": "turned off",
    "error": "failed",
}

_CSS = """
:root{color-scheme:light dark;--bg:#f6f7f9;--fg:#16181d;--muted:#5b6170;--card:#fff;
--line:#dfe2e8;--accent:#2f6bd8;--warnbg:#fff5e0;--danger:#a12d2d;--ok:#1f7a48}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8eaef;--muted:#9aa1b1;
--card:#1c1f25;--line:#2c313a;--accent:#7aa6f5;--warnbg:#33270f;
--danger:#f0908c;--ok:#6ed39b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 20px;font-size:.95rem}
.sub code{font-size:.9em}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
padding:7px 14px;font-size:.9rem;display:flex;gap:8px;align-items:center}
.dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.dot.ok{background:var(--ok)}.dot.not_found,.dot.disabled{background:var(--muted)}
.dot.error{background:var(--danger)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin:0 0 16px}
section h2{font-size:1.05rem;margin:0;display:flex;align-items:baseline;gap:10px}
section h2 .n{color:var(--muted);font-weight:400;font-size:.9rem}
section p.why{color:var(--muted);margin:4px 0 12px;font-size:.9rem}
ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}
li{border:1px solid var(--line);border-radius:8px;padding:10px 12px;
display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
li .name{font-weight:600}
li .sel{color:var(--muted);font-size:.85rem;font-family:ui-monospace,monospace}
li .fields{color:var(--muted);font-size:.85rem}
.edit{background:var(--warnbg);border-color:transparent}
.edit .d{width:100%;font-size:.88rem;font-family:ui-monospace,monospace;color:var(--muted)}
.edit .d b{color:var(--fg);font-weight:600}
a.btn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
border-radius:8px;padding:12px 20px;font-weight:600;font-size:1rem}
a.btn.sec{background:transparent;color:var(--accent);border:1px solid var(--accent)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}
details{margin-top:22px}summary{cursor:pointer;color:var(--muted)}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:12px;overflow:auto;font-size:.82rem;line-height:1.5;max-height:50vh}
.err{border-left:4px solid var(--danger);padding-left:14px}
.note{color:var(--muted);font-size:.85rem;margin-top:26px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:520px){.wrap{padding:16px 12px 48px}li{flex-direction:column;gap:2px}}
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


def _sources_bar(sources: List[Dict[str, Any]]) -> str:
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
    return f'<div class="bar">{"".join(chips)}</div>'


def page(doc: Dict[str, Any], log: str = "", token: str = "") -> str:
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

    log_block = ""
    if log.strip():
        log_block = (f'<details><summary>Importer log</summary>'
                     f'<pre>{_e(log.strip())}</pre></details>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sunshine apps</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>Sunshine apps</h1>
<p class="sub">{_e(summary)} &middot; <code>{_e(doc.get("apps_json", ""))}</code></p>
{_sources_bar(doc.get("sources") or [])}
<div class="actions"><a class="btn" href="/{q}">Re-scan</a></div>
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
<body><div class="wrap">
<h1>Sunshine apps</h1>
<section class="err"><h2>Could not read a plan</h2>
<p class="why">{_e(message)}</p>{extra}</section>
<div class="actions"><a class="btn sec" href="/{q}">Try again</a></div>
</div></body></html>"""
