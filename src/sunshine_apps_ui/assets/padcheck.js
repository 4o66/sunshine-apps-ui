// SPDX-License-Identifier: GPL-3.0-or-later
// The controller check in Settings (approved 2026-10-02): press anything and
// see what arrives. Nothing is asked for and nothing is recorded; Report a
// bug has the test that goes into the log (padtest.js).
//
// Check the controller (A on it, or a click) starts it. While it runs pad.js
// stands still (PAD.paused), so every button is shown rather than used:
// pressed lights blue on the drawing, the triggers fill as far as they are
// pulled, and each stick's dot sits where the stick is. Holding Y for 2
// seconds ends it; a mouse can click End.
// pad.js comes after this in the page, so this starts once both have run.
document.addEventListener("DOMContentLoaded", function () {
  "use strict";
  var live = document.querySelector("[data-padcheck]");
  if (!live || !window.PAD || typeof navigator.getGamepads !== "function") return;

  // The triggers are shown by how far they fill, not as pressed.
  var NAMES = { a: "A", b: "B", x: "X", y: "Y", lb: "LB", rb: "RB",
    view: "View", menu: "Menu", l3: "Left stick, pressed", r3: "Right stick, pressed",
    dup: "D-pad up", ddown: "D-pad down", dleft: "D-pad left", dright: "D-pad right" };
  var HOLD = 2000, REACH = 30;   // ms to hold Y; how far a dot moves in the drawing
  var running = false, holdY = null;

  function show(on) {
    running = on;
    window.PAD.paused = on;
    holdY = null;
    document.documentElement.classList.toggle("testing", on);
    Array.prototype.forEach.call(document.querySelectorAll("[data-when]"), function (el) {
      el.hidden = el.getAttribute("data-when") !== (on ? "running" : "start");
    });
    var start = document.querySelector("[data-padcheck-start]");
    if (!on && start) start.focus({ preventScroll: true, focusVisible: true });
  }

  function signed(v) {
    return (v < 0 ? "−" : "") + Math.abs(v).toFixed(2);
  }

  function setText(sel, text) {
    var el = live.querySelector(sel);
    if (el && el.textContent !== text) el.textContent = text;
  }

  function paint(p) {
    var L = window.PAD.logical(p), v = window.PAD.analog(p);
    Array.prototype.forEach.call(live.querySelectorAll("[data-part]"), function (el) {
      var part = el.getAttribute("data-part");
      el.classList.toggle("on", !!L[part] && part !== "lt" && part !== "rt");
    });
    [["lt", v.lt], ["rt", v.rt]].forEach(function (t) {
      var amount = Math.max(0, Math.min(1, t[1]));
      var pull = live.querySelector('[data-pull="' + t[0] + '"]');
      if (pull) pull.setAttribute("width", String(110 * amount));
      var meter = live.querySelector('[data-meter="' + t[0] + '"]');
      if (meter) meter.style.width = (100 * amount) + "%";
      setText('[data-value="' + t[0] + '"]', amount.toFixed(2));
    });
    [["l", v.lx, v.ly, 220, 210], ["r", v.rx, v.ry, 490, 300]].forEach(function (s) {
      var knob = live.querySelector('[data-knob="' + s[0] + '"]');
      if (knob) {
        knob.setAttribute("cx", String(s[3] + s[1] * REACH));
        knob.setAttribute("cy", String(s[4] + s[2] * REACH));
      }
      setText('[data-stick="' + s[0] + '"]', "x " + signed(s[1]) + "  y " + signed(s[2]));
    });
    var names = Object.keys(NAMES).filter(function (k) { return L[k]; }).map(function (k) { return NAMES[k]; });
    var raw = [];
    for (var i = 0; i < p.buttons.length; i++) if (window.PAD.pressed(p, i)) raw.push(i);
    setText("[data-pressed]", names.length ? names.join(", ") : " ");
    setText("[data-raw]", raw.length ? (raw.length === 1 ? "button " : "buttons ") + raw.join(", ") : "");
    return L;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    var pads = navigator.getGamepads(), p = null;
    for (var i = 0; i < pads.length; i++) if (pads[i] && pads[i].connected) { p = pads[i]; break; }
    if (!p) return;
    Array.prototype.forEach.call(document.querySelectorAll("[data-pad-name]"), function (el) {
      if (el.textContent !== p.id) el.textContent = p.id;
    });
    if (!running) return;
    var L = paint(p);
    holdY = L.y ? (holdY === null ? now : holdY) : null;
    if (holdY !== null && now - holdY >= HOLD) show(false);
  }

  var start = document.querySelector("[data-padcheck-start]");
  if (start) start.addEventListener("click", function () { show(true); });
  var end = document.querySelector("[data-padcheck-end]");
  if (end) end.addEventListener("click", function () { show(false); });

  // For the design harness only: show the check as the board draws it.
  window.PADCHECK = {
    show: function (state) {
      show(true);
      paint({ id: state.id, axes: state.axes, buttons: state.buttons.map(function (v) {
        return { pressed: v > 0.5, value: v };
      }) });
    }
  };
  requestAnimationFrame(frame);
});
