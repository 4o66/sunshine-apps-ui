// SPDX-License-Identifier: GPL-3.0-or-later
// The on-screen keyboard (#62): opened when a text field is chosen with a
// controller. A mouse or keyboard user types into the field itself and never
// sees it.
//
// It is drawn in the page, over its lower half, with the field's text large
// above the keys. What it types goes into the field only on Done; Cancel, or
// B, leaves the field as it was. A field marked data-osk="hex" gets the
// SteamGridDB key's keypad instead, with Full keyboard for a key that looks
// different.
//
// The controller's own buttons, while it is open (pad.js asks handle()):
//   A types the focused key, X deletes, Y is a space, LB and RB move the
//   cursor, Menu is Done, B cancels. Menu acts on a tap, as everywhere.
(function () {
  "use strict";

  var LETTERS = [
    "1234567890-:".split(""),
    "qwertyuiop".split("").concat([["⌫ Delete", "delete", "dim w2"]]),
    "asdfghjkl'".split("").concat([["Done", "done", "go w2"]]),
    [["⇪ Caps", "caps", "dim", "Caps lock"], ["⇧ Shift", "shift", "dim", "Shift, for the next letter"]]
      .concat("zxcvbnm,./".split("")),
    [["&123 Symbols", "symbols", "dim w2"], ["Space", "space", "w6"], ["←", "left", "dim"],
     ["→", "right", "dim"], ["Cancel", "cancel", "dim w2"]]
  ];
  // The same twelve columns and five rows as the letters, so the cursor
  // keeps its place when switching; Caps and Shift are there but off.
  var SYMBOLS = [
    "1234567890-:".split(""),
    "!@#$%^&*()".split("").concat([["⌫ Delete", "delete", "dim w2"]]),
    ["_", "=", "+", ";", "\"", "'", "`", "~", "?", ","].concat([["Done", "done", "go w2"]]),
    [["⇪ Caps", "caps", "dim", "Caps lock", true], ["⇧ Shift", "shift", "dim", "Shift, for the next letter", true]]
      .concat(["\\", "|", "{", "}", "[", "]", "<", ">", ".", "/"]),
    [["abc Letters", "letters", "dim w2"], ["Space", "space", "w6"], ["←", "left", "dim"],
     ["→", "right", "dim"], ["Cancel", "cancel", "dim w2"]]
  ];
  var HEX = [
    "1234567890".split("").concat([["⌫ Delete", "delete", "dim w2"]]),
    "abcdef".split("").concat([["Full keyboard", "full", "dim w3"], ["Done", "done", "go w3"]])
  ];

  var root = null, field = null, text = "", cursor = 0;
  var layout = "letters", caps = false, shift = false;

  function el(tag, cls, content) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (content != null) e.textContent = content;
    return e;
  }

  function labelOf(f) {
    var id = f.getAttribute("id");
    var l = id && document.querySelector('label[for="' + id + '"]');
    return (l && l.textContent.trim()) || f.getAttribute("aria-label") || "Text";
  }

  function glyphHelp(glyph, cls, words) {
    var s = el("span");
    var g = el("span", "glyph " + cls, glyph);
    s.appendChild(g);
    s.appendChild(document.createTextNode(words));
    return s;
  }

  function upper() { return caps || shift; }

  function keyButton(spec) {
    var b;
    if (typeof spec === "string") {
      var ch = (layout === "letters" && upper()) ? spec.toUpperCase() : spec;
      b = el("button", "key", ch);
      b.setAttribute("data-type", ch);
    } else {
      b = el("button", "key" + (spec[2] ? " " + spec[2] : ""), spec[0]);
      b.setAttribute("data-do", spec[1]);
      if (spec[3]) b.setAttribute("aria-label", spec[3]);
      if (spec[4]) b.disabled = true;
      if ((spec[1] === "caps" && caps) || (spec[1] === "shift" && shift)) b.classList.add("on");
    }
    b.type = "button";
    return b;
  }

  function draw(focusSame) {
    var keys = root.querySelector(".keys");
    var was = document.activeElement && keys.contains(document.activeElement)
      ? Array.prototype.indexOf.call(keys.children, document.activeElement) : -1;
    keys.innerHTML = "";
    var rows = layout === "hex" ? HEX : layout === "symbols" ? SYMBOLS : LETTERS;
    rows.forEach(function (row) { row.forEach(function (spec) { keys.appendChild(keyButton(spec)); }); });
    var value = root.querySelector(".value");
    value.textContent = "";
    value.appendChild(document.createTextNode(text.slice(0, cursor)));
    value.appendChild(el("span", "caret"));
    value.appendChild(document.createTextNode(text.slice(cursor)));
    var count = root.querySelector(".count");
    if (count) count.textContent = text.length + " of 32";
    var at = focusSame && was >= 0 ? keys.children[was] : null;
    // Opening starts on Done: typing here is usually a small correction, so A
    // straight away changes nothing and X deletes from the end.
    (at || keys.querySelector('[data-do="done"]')).focus({ preventScroll: true, focusVisible: true });
  }

  function type(ch) {
    text = text.slice(0, cursor) + ch + text.slice(cursor);
    cursor += ch.length;
    if (shift) { shift = false; }
    draw(true);
  }

  function act(what) {
    if (what === "delete") {
      if (cursor > 0) { text = text.slice(0, cursor - 1) + text.slice(cursor); cursor--; }
    } else if (what === "space") { type(" "); return; }
    else if (what === "left") { cursor = Math.max(0, cursor - 1); }
    else if (what === "right") { cursor = Math.min(text.length, cursor + 1); }
    else if (what === "caps") { caps = !caps; shift = false; }
    else if (what === "shift") { shift = !shift; }
    else if (what === "symbols") { layout = "symbols"; }
    else if (what === "letters") { layout = "letters"; }
    else if (what === "full") { layout = "letters"; build(); draw(false); return; }
    else if (what === "done") { close(true); return; }
    else if (what === "cancel") { close(false); return; }
    draw(true);
  }

  function build() {
    if (root) root.remove();
    var veil = document.querySelector(".veil") || document.body.appendChild(el("div", "veil"));
    veil.addEventListener("click", function () { close(false); });
    root = el("div", "osk");
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", layout === "hex" ? "Keyboard for the SteamGridDB key" : "Keyboard");
    var entry = el("div", "entry");
    entry.appendChild(el("label", null, labelOf(field)));
    entry.appendChild(el("div", "value" + (layout === "hex" ? " mono" : "")));
    if (layout === "hex") entry.appendChild(el("span", "muted small count"));
    root.appendChild(entry);
    if (layout === "hex") {
      var p = el("p", "muted small", "SteamGridDB keys are letters a to f and digits. If yours has anything else, " +
        "Full keyboard has every letter.");
      p.style.margin = "0";
      root.appendChild(p);
    }
    root.appendChild(el("div", "keys"));
    var help = el("div", "help");
    help.appendChild(glyphHelp("A", "a", "Type"));
    help.appendChild(glyphHelp("X", "x", "Delete"));
    if (layout !== "hex") help.appendChild(glyphHelp("Y", "y", "Space"));
    help.appendChild(glyphHelp("LB RB", "wide", "Move the cursor"));
    help.appendChild(glyphHelp("☰", "wide", "Done"));
    help.appendChild(glyphHelp("B", "b", "Cancel"));
    root.appendChild(help);
    root.addEventListener("click", function (e) {
      var k = e.target.closest(".key");
      if (!k) return;
      if (k.hasAttribute("data-type")) type(k.getAttribute("data-type"));
      else act(k.getAttribute("data-do"));
    });
    document.body.appendChild(root);
  }

  function open(f) {
    if (!f || f.readOnly || f.disabled) return;
    field = f;
    text = f.value || "";
    cursor = text.length;
    caps = shift = false;
    layout = f.getAttribute("data-osk") === "hex" ? "hex" : "letters";
    build();
    draw(false);
    var kb = document.querySelector(".btn.kb");
    if (kb) kb.style.display = "none";
  }

  function close(keep) {
    if (!root) return;
    var f = field;
    var changed = keep && f.value !== text;
    if (changed) {
      f.value = text;
      f.dispatchEvent(new Event("input", { bubbles: true }));
      f.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // A field that is a search (the artwork picker's) goes on Done.
    if (keep && f.hasAttribute("data-osk-submit") && f.form) { f.form.submit(); return; }
    root.remove();
    root = null;
    var veil = document.querySelector(".veil");
    if (veil) veil.remove();
    field = null;
    f.focus({ preventScroll: true, focusVisible: true });
  }

  // The controller's buttons while it is open. True when the press was used.
  function handle(name) {
    if (!root) return false;
    if (name === "x") act("delete");
    else if (name === "y") { if (layout !== "hex") act("space"); }
    else if (name === "lb") act("left");
    else if (name === "rb") act("right");
    else if (name === "menu") act("done");
    else if (name === "b") act("cancel");
    else return false;
    return true;
  }

  document.addEventListener("pad:type", function (e) { open(e.detail); });
  // A button that types into a field it names, which may be hidden while a
  // controller is in use (the artwork picker's Search by another name).
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-osk-for]");
    if (b) open(document.getElementById(b.getAttribute("data-osk-for")));
  });
  window.OSK = { open: open, handle: handle, isOpen: function () { return !!root; },
                 area: function () { return root; } };
})();
