// SPDX-License-Identifier: GPL-3.0-or-later
// A controller, read through the Gamepad API: focus movement and the 2.0
// button mapping (#56, #59).
//
// Nothing in a web page moves focus when a d-pad is pushed. The window hands
// the page the pad -- WebKitGTK through libmanette, WebView2 through Windows'
// own input -- only as numbers to poll (#32). Every control is a link, button
// or field, so this moves focus between them and presses them; the pages work
// unchanged without it, with a mouse, keyboard or touch.
//
// The buttons are found by the glyphs the page already shows, so what a
// button says and what it does cannot drift apart: Y presses the control
// showing the Y glyph, X the one showing X, LB and RB the ones showing LB and
// RB, Menu the Settings gear. B presses the control showing B, else the page's
// Back link, else goes back.
//
// Menu acts on a short tap only. Moonlight on a desktop or Android takes Start
// held for 750 ms as its own mouse-mode switch, after which no controller input
// reaches this page at all, so nothing here may ever ask for a hold.
//
// While a controller is in use, <html> carries .pad: the stylesheet then shows
// the glyphs, the focus ring and the Keyboard button. A mouse movement takes it
// away again.
//
// The standard mapping: 0 A, 1 B, 2 X, 3 Y (but see faceX), 4 LB, 5 RB, 9 Menu (Start),
// 12-15 the d-pad; axes 0/1 the left stick, 2/3 the right.
(function () {
  "use strict";
  if (typeof navigator.getGamepads !== "function") return;

  var FIRST_REPEAT = 400;     // ms held before a direction repeats
  var REPEAT = 130;           // ms between repeats after that
  var DEAD = 0.5;             // stick travel that counts as a push
  var SCROLL = 24;            // px per frame at full right-stick travel
  var TAP = 600;              // Menu counts only if let go within this, in ms
  var FOCUSABLE = "a[href], button:not([disabled]), summary, " +
    "input:not([disabled]):not([type=hidden]), select:not([disabled]), " +
    "textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
  var root = document.documentElement;
  // WebKit shows a page its pads only after a button is pressed on that page,
  // so "a controller is in use" is carried across pages for the session;
  // otherwise every page would open without its hints until the next press.
  function remember(on) {
    try { if (on) sessionStorage.setItem("pad", "1"); else sessionStorage.removeItem("pad"); }
    catch (e) { /* private mode: hints come back on the next press */ }
  }
  try { if (sessionStorage.getItem("pad") === "1") root.classList.add("pad"); } catch (e) {}
  function usingPad() { if (!root.classList.contains("pad")) { root.classList.add("pad"); } remember(true); }

  function shown(el) {
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var style = getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  // While the on-screen keyboard is open, only its keys (osk.js).
  function keyboard() {
    return window.OSK && window.OSK.isOpen() ? window.OSK.area() : null;
  }

  function targets() {
    return Array.prototype.filter.call(
      (keyboard() || document).querySelectorAll(FOCUSABLE), shown);
  }

  // The page scrolls between the bars, not the window.
  function scroller() {
    return document.querySelector("main.main") || document.scrollingElement;
  }

  // WebKit selects a text field's whole contents when it is focused from
  // script; a controller only arrives at a field, so it gets a cursor at the
  // start, as the design draws it, and A opens the keyboard on it.
  function put(el) {
    el.focus({ preventScroll: true, focusVisible: true });
    if (el.tagName === "INPUT" && typeof el.setSelectionRange === "function" &&
        /^(text|search|url|password)$/.test(el.type)) {
      try { el.setSelectionRange(0, 0); } catch (e) { /* not every input allows it */ }
    }
    el.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // The nearest control in the direction pushed. Distance along the push
  // counts from the facing edges; distance across it counts three times, so
  // moving down a column stays in the column. Left and right stay in the row.
  // Where a control is on screen, as it is drawn. The exit-timeout choices
  // and the switches are real radios and checkboxes, 1px and hidden inside
  // the box you see; measuring the 1px dot sent up and down to odd places
  // (the Legion test, 2026-09-28).
  function box(el) {
    var shown = el.tagName === "INPUT" && el.closest && el.closest("label.choice, label.switch");
    return (shown || el).getBoundingClientRect();
  }

  function nearest(from, dx, dy, all) {
    var a = box(from);
    var best = null, bestScore = Infinity;
    all.forEach(function (el) {
      if (el === from || el.contains(from) || from.contains(el)) return;
      var b = box(el);
      var along, across;
      if (dx) {
        along = dx > 0 ? b.left - a.right : a.left - b.right;
        if ((b.left + b.right) * dx <= (a.left + a.right) * dx) return;
        across = Math.max(0, Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom));
        if (across > 0) return;
      } else {
        along = dy > 0 ? b.top - a.bottom : a.top - b.bottom;
        if ((b.top + b.bottom) * dy <= (a.top + a.bottom) * dy) return;
        across = Math.max(0, Math.max(a.left, b.left) - Math.min(a.right, b.right));
      }
      // Ties (a row of choices below a field, say) go to the one nearest the
      // middle of where focus is now.
      var off = dx ? Math.abs((a.top + a.bottom) - (b.top + b.bottom)) / 2
                   : Math.abs((a.left + a.right) - (b.left + b.right)) / 2;
      var score = Math.max(0, along) + across * 3 + off * 0.01;
      if (score < bestScore) { best = el; bestScore = score; }
    });
    return best;
  }

  function move(dx, dy) {
    var all = targets();
    var here = document.activeElement;
    if (!here || all.indexOf(here) < 0) {
      var first = all.filter(function (el) {
        var r = el.getBoundingClientRect();
        return r.bottom > 0 && r.top < innerHeight;
      })[0] || all[0];
      if (first) put(first);
      return;
    }
    var next = nearest(here, dx, dy, all);
    if (next) put(next);
    else if (dy) scroller().scrollBy(0, dy * innerHeight / 2);  // at the end: show what is past it
  }

  // The control that shows a glyph, by its letter: ".glyph.y", or a wide one
  // whose text is "LB". Only controls that are shown and not drawn flat.
  function byGlyph(name) {
    var sel = name.length === 1 ? ".glyph." + name : ".glyph.wide";
    var found = null;
    Array.prototype.forEach.call(document.querySelectorAll(sel), function (g) {
      if (found) return;
      if (name.length > 1 && g.textContent.trim().indexOf(name.toUpperCase()) < 0) return;
      var control = g.closest("a[href], button, label");
      if (!control || control.classList.contains("flat") || control.disabled) return;
      if (shown(control)) found = control;
    });
    return found;
  }

  function activate(el) {
    if (!el) return false;
    el.click();
    return true;
  }

  function press() {
    var el = document.activeElement;
    if (!el || el === document.body) { move(0, 1); return; }
    var tag = el.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT" ||
        (tag === "INPUT" && !/^(checkbox|radio|submit|button|reset)$/.test(el.type))) {
      // A text field: the on-screen keyboard's job (osk.js).
      document.dispatchEvent(new CustomEvent("pad:type", { detail: el }));
      return;
    }
    el.click();
  }

  // B cancels the screen you are on: its own B button, else its Back or
  // Cancel link. Never the browser's history, which went wherever you had
  // last been (from the grid, to a tile's edit page). Where there is nothing
  // to cancel, the grid, B does nothing. The Legion test, 2026-09-28.
  function back() {
    if (activate(byGlyph("b"))) return;
    var link = document.querySelector("[data-back]");
    if (link && shown(link)) link.click();
  }

  function menu() {
    var gear = document.querySelector("a.gear");
    if (gear && shown(gear)) gear.click();
  }

  var held = {};            // name -> {since, last}
  function edge(name, down, now, repeats, action) {
    var h = held[name];
    if (!down) { delete held[name]; return; }
    if (!h) { held[name] = { since: now, last: now }; action(); return; }
    if (repeats && now - h.since >= FIRST_REPEAT && now - h.last >= REPEAT) {
      h.last = now;
      action();
    }
  }
  // Menu: remembered on press, acted on at release, and only if short.
  var menuSince = null;

  function pressed(pad, i) {
    var b = pad.buttons[i];
    return !!b && (b.pressed || b.value > 0.5);
  }

  // X and Y, by the letter printed on the button. An Xbox pad on Linux --
  // the kernel's own driver, and the virtual pad Sunshine makes through
  // inputtino -- reports X as BTN_NORTH and Y as BTN_WEST. WebKitGTK maps
  // those by where the kernel says they sit, so X arrives as button 3 and Y
  // as 2, the wrong way round. Measured on bsm-bazzite, 2026-09-27, with a
  // uinput pad sending inputtino's codes. WebView2 reads XInput and gets
  // them right, so this is only for WebKit on Linux.
  var SWAPPED_XY = /Linux/.test(navigator.userAgent) && !/Chrom/.test(navigator.userAgent);
  function faceX(pad) { return SWAPPED_XY && /x-?box|xinput/i.test(pad.id) ? 3 : 2; }
  function faceY(pad) { return SWAPPED_XY && /x-?box|xinput/i.test(pad.id) ? 2 : 3; }

  function frame(now) {
    requestAnimationFrame(frame);
    // A pad is shared by everything on the machine; only the window in front
    // should act on it.
    if (!document.hasFocus()) { held = {}; menuSince = null; return; }
    var pads = navigator.getGamepads();
    var pad = null;
    for (var i = 0; i < pads.length; i++) {
      if (pads[i] && pads[i].connected) { pad = pads[i]; break; }
    }
    if (!pad) return;
    var any = false;
    for (var b = 0; b < pad.buttons.length; b++) if (pressed(pad, b)) { any = true; break; }
    var ax = pad.axes[0] || 0, ay = pad.axes[1] || 0;
    var rx = pad.axes[2] || 0, ry = pad.axes[3] || 0;
    if (any || Math.abs(ax) > DEAD || Math.abs(ay) > DEAD) usingPad();

    edge("up", pressed(pad, 12) || ay < -DEAD, now, true, function () { move(0, -1); });
    edge("down", pressed(pad, 13) || ay > DEAD, now, true, function () { move(0, 1); });
    edge("left", pressed(pad, 14) || ax < -DEAD, now, true, function () { move(-1, 0); });
    edge("right", pressed(pad, 15) || ax > DEAD, now, true, function () { move(1, 0); });
    // The keyboard takes B, X, Y, LB, RB and Menu while it is open; A still
    // presses the focused key. X and the cursor keys repeat when held there.
    function to(name, fallback) {
      return function () { if (!(keyboard() && window.OSK.handle(name))) fallback(); };
    }
    var typing = !!keyboard();
    edge("a", pressed(pad, 0), now, false, press);
    edge("b", pressed(pad, 1), now, false, to("b", back));
    edge("x", pressed(pad, faceX(pad)), now, typing, to("x", function () { activate(byGlyph("x")); }));
    edge("y", pressed(pad, faceY(pad)), now, false, to("y", function () { activate(byGlyph("y")); }));
    edge("lb", pressed(pad, 4), now, typing, to("lb", function () { activate(byGlyph("lb")); }));
    edge("rb", pressed(pad, 5), now, typing, to("rb", function () { activate(byGlyph("rb")); }));

    if (pressed(pad, 9)) {
      if (menuSince === null) menuSince = now;
    } else if (menuSince !== null) {
      if (now - menuSince < TAP) to("menu", menu)();
      menuSince = null;
    }

    if (!typing && (Math.abs(rx) > 0.2 || Math.abs(ry) > 0.2)) scroller().scrollBy(rx * SCROLL, ry * SCROLL);
  }

  // A mouse in use: no controller hints.
  addEventListener("mousemove", function (e) {
    if (e.movementX || e.movementY) { root.classList.remove("pad"); remember(false); }
  });

  // Held on arrival (B pressed on the last page, say) is not a new press.
  requestAnimationFrame(function (now) {
    var pads = navigator.getGamepads();
    var names = { 0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 12: "up", 13: "down", 14: "left", 15: "right" };
    for (var i = 0; i < pads.length; i++) {
      var pad = pads[i];
      if (!pad) continue;
      Object.keys(names).forEach(function (b) {
        if (pressed(pad, +b)) held[names[b]] = { since: now, last: now };
      });
    }
    requestAnimationFrame(frame);
  });
})();
