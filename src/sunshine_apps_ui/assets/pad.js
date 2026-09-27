// SPDX-License-Identifier: GPL-3.0-or-later
// A controller, read through the Gamepad API and turned into focus movement.
//
// Nothing in a web page moves focus when a d-pad is pushed. The window does
// hand the page the pad -- WebKitGTK through libmanette, WebView2 through
// Windows' own input -- but only as numbers to poll, so until this ran a
// controller reached the page and did nothing (#32). Every control here is
// already a link, button or field, so moving focus between them and pressing
// the focused one is the whole job; the pages work unchanged without it.
//
// The standard mapping: 0 is A, 1 is B, 12-15 are the d-pad, axes 0/1 the
// left stick, 2/3 the right.
(function () {
  "use strict";
  if (typeof navigator.getGamepads !== "function") return;

  var FIRST_REPEAT = 400;     // ms held before a direction repeats
  var REPEAT = 130;           // ms between repeats after that
  var DEAD = 0.5;             // stick travel that counts as a push
  var SCROLL = 24;            // px per frame at full right-stick travel
  var FOCUSABLE = "a[href], button:not([disabled]), summary, " +
    "input:not([disabled]):not([type=hidden]), select:not([disabled]), " +
    "textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

  function shown(el) {
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var style = getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  function targets() {
    return Array.prototype.filter.call(
      document.querySelectorAll(FOCUSABLE), shown);
  }

  function put(el) {
    el.focus({ preventScroll: true, focusVisible: true });
    el.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // The nearest control in the direction pushed. Distance along the push
  // counts from the facing edges, so the tile beside this one beats a wider
  // one further on; distance across it counts three times, so moving down a
  // column stays in the column rather than jumping to whatever is closest.
  // Left and right stay in the row: from the last tile, right used to reach
  // Settings, which is further right but at the top of the page.
  function nearest(from, dx, dy, all) {
    var a = from.getBoundingClientRect();
    var best = null, bestScore = Infinity;
    all.forEach(function (el) {
      if (el === from || el.contains(from) || from.contains(el)) return;
      var b = el.getBoundingClientRect();
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
      var score = Math.max(0, along) + across * 3;
      if (score < bestScore) { best = el; bestScore = score; }
    });
    return best;
  }

  function move(dx, dy) {
    var all = targets();
    var here = document.activeElement;
    if (!here || all.indexOf(here) < 0) {
      // Nothing focused yet: start at the first control on screen.
      var first = all.filter(function (el) {
        var r = el.getBoundingClientRect();
        return r.bottom > 0 && r.top < innerHeight;
      })[0] || all[0];
      if (first) put(first);
      return;
    }
    var next = nearest(here, dx, dy, all);
    if (next) put(next);
    else if (dy) scrollBy(0, dy * innerHeight / 2);  // at the end: show what is past it
  }

  function press() {
    var el = document.activeElement;
    if (!el || el === document.body) { move(0, 1); return; }
    var tag = el.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT" ||
        (tag === "INPUT" && !/^(checkbox|radio|submit|button|reset)$/.test(el.type))) {
      return;               // already where typing goes
    }
    el.click();
  }

  function back() {
    var link = document.querySelector("[data-back]");
    if (link && shown(link)) link.click();
    else if (history.length > 1) history.back();
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

  function pressed(pad, i) {
    var b = pad.buttons[i];
    return !!b && (b.pressed || b.value > 0.5);
  }

  function frame(now) {
    requestAnimationFrame(frame);
    // A pad is shared by everything on the machine; only the window in front
    // should act on it.
    if (!document.hasFocus()) { held = {}; return; }
    var pads = navigator.getGamepads();
    var pad = null;
    for (var i = 0; i < pads.length; i++) {
      if (pads[i] && pads[i].connected) { pad = pads[i]; break; }
    }
    if (!pad) return;
    var ax = pad.axes[0] || 0, ay = pad.axes[1] || 0;
    edge("up", pressed(pad, 12) || ay < -DEAD, now, true, function () { move(0, -1); });
    edge("down", pressed(pad, 13) || ay > DEAD, now, true, function () { move(0, 1); });
    edge("left", pressed(pad, 14) || ax < -DEAD, now, true, function () { move(-1, 0); });
    edge("right", pressed(pad, 15) || ax > DEAD, now, true, function () { move(1, 0); });
    edge("a", pressed(pad, 0), now, false, press);
    edge("b", pressed(pad, 1), now, false, back);
    var rx = pad.axes[2] || 0, ry = pad.axes[3] || 0;
    if (Math.abs(rx) > 0.2 || Math.abs(ry) > 0.2) scrollBy(rx * SCROLL, ry * SCROLL);
  }

  // Held on arrival (B pressed on the last page, say) is not a new press.
  requestAnimationFrame(function (now) {
    var pads = navigator.getGamepads();
    for (var i = 0; i < pads.length; i++) {
      var pad = pads[i];
      if (!pad) continue;
      [0, 1, 12, 13, 14, 15].forEach(function (b) {
        if (pressed(pad, b)) held[b === 0 ? "a" : b === 1 ? "b" :
          ["up", "down", "left", "right"][b - 12]] = { since: now, last: now };
      });
    }
    requestAnimationFrame(frame);
  });
})();
