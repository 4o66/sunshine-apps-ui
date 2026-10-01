// SPDX-License-Identifier: GPL-3.0-or-later
// The controller test (phase 7), started from Report a bug. Approved
// 2026-09-30 as drawn on the Test the controller boards.
//
// It asks for each of 24 inputs in turn, drawn on a controller: blue is the
// one to press, green arrived as expected, red was missed or arrived as
// something else. "As expected" means as pad.js reads it (window.PAD), since
// that is what the manager acts on; what arrived instead is said by what
// pad.js calls it, or else the raw button or axis number.
//
// A starts the test and is its first input. Each input has 8 seconds, shown
// by the bar running out. pad.js stands still on this page (PAD.paused) and
// this reads the pad: before the start B is Back and Menu is Settings; while
// it runs every button counts, so holding A for 2 seconds starts over and
// holding B stops. At the end the results are posted, which logs them and
// shows the result page.
// pad.js comes after this in the page, so this starts once both have run.
document.addEventListener("DOMContentLoaded", function () {
  "use strict";
  var main = document.querySelector("[data-padtest]");
  if (!main || !window.PAD || typeof navigator.getGamepads !== "function") return;

  // The buttons, the d-pad, then each stick: its press and its four ways
  // before the next one (asked for after the Legion test, 2026-09-30).
  var ORDER = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "view", "menu",
    "dup", "ddown", "dleft", "dright", "l3", "lup", "ldown", "lleft", "lright",
    "r3", "rup", "rdown", "rleft", "rright"];
  var NAMES = { a: "A", b: "B", x: "X", y: "Y", lb: "LB", rb: "RB", lt: "LT", rt: "RT",
    view: "View", menu: "Menu", l3: "Left stick, pressed", r3: "Right stick, pressed",
    dup: "D-pad up", ddown: "D-pad down", dleft: "D-pad left", dright: "D-pad right",
    lup: "Left stick up", ldown: "Left stick down", lleft: "Left stick left", lright: "Left stick right",
    rup: "Right stick up", rdown: "Right stick down", rleft: "Right stick left", rright: "Right stick right" };
  // What to do, and the word on the blue key: "Push the right stick" "down".
  function asking(part) {
    var dir = { up: "up", down: "down", left: "left", right: "right" };
    var m = /^(d|l|r)(up|down|left|right)$/.exec(part);
    if (m) return [m[1] === "d" ? "Press the d-pad" : "Push the " + (m[1] === "l" ? "left" : "right") + " stick", dir[m[2]]];
    if (part === "l3") return ["Press the left stick", "in"];
    if (part === "r3") return ["Press the right stick", "in"];
    return [part === "lt" || part === "rt" ? "Pull" : "Press", NAMES[part]];
  }
  var WAIT = 8000, HOLD = 2000, SETTLE = 150;

  // This page reads the pad itself, from the start: A here starts the test
  // rather than pressing the focused button.
  window.PAD.paused = true;
  var step = -1, results = {}, since = 0, armed = false, releasedAt = 0, waitingSince = 0;
  var prevL = {}, prevButtons = [], prevAxes = [], base = null;
  var holdA = null, holdB = null, frozen = null;

  function said(part, r) {
    if (r.kind === "missed") return "did not arrive at all";
    if (r.kind === "other") return "arrived as " + NAMES[r.value];
    var what = /^[lr](up|down|left|right)$/.test(part) ? "the stick" : /^d/.test(part) ? "the d-pad"
      : part === "lt" || part === "rt" ? "the trigger" : "";
    var kind = r.kind === "button" ? "a button" : "an axis";
    return what ? "arrived as " + kind + " (" + r.value + "), not " + what
                : "arrived as " + (r.kind === "button" ? "a different button" : "an axis") + " (" + r.value + ")";
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function paint(now) {
    Array.prototype.forEach.call(main.querySelectorAll("[data-part]"), function (p) {
      var part = p.getAttribute("data-part"), r = results[part];
      p.classList.remove("want", "ok", "bad");
      if (r) p.classList.add(r.kind === "ok" ? "ok" : "bad");
      else if (ORDER[step < 0 ? 0 : step] === part) p.classList.add("want");
    });
    document.documentElement.classList.toggle("testing", step >= 0);
    Array.prototype.forEach.call(document.querySelectorAll("[data-when]"), function (b) {
      b.hidden = b.getAttribute("data-when") !== (step >= 0 ? "running" : "start");
    });
    if (step < 0) return;
    var ask = main.querySelector(".ask");
    var part = ORDER[step], words = asking(part);
    var left = Math.max(0, WAIT - (armed ? now - since : 0));
    ask.textContent = "";
    ask.appendChild(el("span", "n", (step + 1) + " of " + ORDER.length));
    var b = el("b", null, words[0] + " ");
    b.appendChild(el("span", "big", words[1]));
    ask.appendChild(b);
    var timer = el("div", "timer");
    timer.setAttribute("role", "progressbar");
    timer.setAttribute("aria-label", "Time left");
    timer.setAttribute("aria-valuemin", "0");
    timer.setAttribute("aria-valuemax", String(WAIT / 1000));
    timer.setAttribute("aria-valuenow", String(Math.ceil(left / 1000)));
    var fill = el("span");
    fill.style.width = (100 * left / WAIT) + "%";
    timer.appendChild(fill);
    ask.appendChild(timer);
    var secs = Math.ceil(left / 1000);
    ask.appendChild(el("span", "muted small", secs + (secs === 1 ? " second" : " seconds") +
      " left, then it is marked missed."));
    var wrong = ORDER.filter(function (p) { return results[p] && results[p].kind !== "ok"; });
    if (wrong.length) {
      var h = el("h2", null, "Not as expected so far");
      h.style.cssText = "margin:1.2rem 0 .4rem;font-size:1.05rem";
      ask.appendChild(h);
      wrong.forEach(function (p) {
        var line = el("p", null, NAMES[p] + " " + said(p, results[p]) + ".");
        line.style.margin = "0";
        ask.appendChild(line);
      });
    }
    ask.appendChild(legend.cloneNode(true));
  }
  var legend = main.querySelector(".legend");

  function record(r) {
    results[ORDER[step]] = r;
    step++;
    armed = false;
    waitingSince = performance.now();
    if (step >= ORDER.length) finish();
  }

  function start(pad) {
    results = {};
    step = 0;
    base = pad.axes.slice();
    record({ kind: "ok" });           // A started it, and A is the first one
  }

  function reset() {
    step = -1; results = {}; armed = false;
    holdA = holdB = null;
  }

  function finish() {
    var form = document.getElementById("padtest-results");
    ORDER.forEach(function (p) {
      var r = results[p] || { kind: "missed" };
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "r_" + p;
      input.value = r.kind === "ok" || r.kind === "missed" ? r.kind : r.kind + ":" + r.value;
      form.appendChild(input);
    });
    form.submit();
  }

  function pad() {
    var pads = navigator.getGamepads();
    for (var i = 0; i < pads.length; i++) if (pads[i] && pads[i].connected) return pads[i];
    return null;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (frozen) return;
    var p = pad();
    if (!p) { paint(now); return; }
    var name = document.querySelector("[data-pad-name]");
    if (name && !name.textContent) name.textContent = p.id;
    var nameField = document.querySelector("#padtest-results input[name=name]");
    if (nameField) nameField.value = p.id;
    var L = window.PAD.logical(p);
    var buttons = p.buttons.map(function (b, i) { return window.PAD.pressed(p, i); });

    if (step < 0) {
      if (L.a && !prevL.a) start(p);
      // Before it starts, B is Back and Menu is Settings, as everywhere.
      else if (L.b && !prevL.b) { var back = document.querySelector("[data-back]"); if (back) back.click(); }
      else if (!L.menu && prevL.menu) { var gear = document.querySelector("a.gear"); if (gear) gear.click(); }
    } else if (step < ORDER.length) {
      // Held: A starts over, B stops. A press is still a press first.
      holdA = L.a ? (holdA === null ? now : holdA) : null;
      holdB = L.b ? (holdB === null ? now : holdB) : null;
      if (holdA !== null && now - holdA >= HOLD) { reset(); prevL = L; paint(now); return; }
      if (holdB !== null && now - holdB >= HOLD) {
        reset();
        var stop = document.querySelector("[data-stop]");
        if (stop) location.href = stop.getAttribute("href");
        return;
      }
      if (!armed) {
        // Everything let go first, so the last press is not taken for this
        // one. An axis that rests somewhere odd does not hold it up.
        var any = Object.keys(L).some(function (k) { return L[k]; }) || buttons.some(Boolean);
        if (any) releasedAt = now;
        if ((!any && now - releasedAt >= SETTLE) || now - waitingSince > 3000) { armed = true; since = now; }
      } else {
        var want = ORDER[step];
        var fresh = ORDER.filter(function (k) { return L[k] && !prevL[k]; });
        var rawButton = -1, rawAxis = null;
        buttons.forEach(function (on, i) { if (on && !prevButtons[i] && rawButton < 0) rawButton = i; });
        p.axes.forEach(function (v, i) {
          var off = Math.abs(v - (base[i] || 0)) > 0.5, was = Math.abs((prevAxes[i] || 0) - (base[i] || 0)) > 0.5;
          if (off && !was && rawAxis === null) rawAxis = i + (v > (base[i] || 0) ? "+" : "-");
        });
        if (fresh.length) record(fresh.indexOf(want) >= 0 ? { kind: "ok" } : { kind: "other", value: fresh[0] });
        else if (rawButton >= 0) record({ kind: "button", value: rawButton });
        else if (rawAxis !== null) record({ kind: "axis", value: rawAxis });
        else if (now - since >= WAIT) record({ kind: "missed" });
      }
    }
    prevL = L;
    prevButtons = buttons;
    prevAxes = p.axes.slice();
    paint(now);
  }

  // A mouse: Start over is a button, Stop a link.
  var again = document.querySelector("[data-start-over]");
  if (again) again.addEventListener("click", function () { reset(); paint(performance.now()); });

  // For the design harness only: show a state as a board draws it, held still.
  // step (1-based), then part=result pairs, and the seconds left.
  window.PADTEST = {
    show: function (at, given, secondsLeft) {
      frozen = true;
      step = at - 1;
      results = given || {};
      armed = true;
      since = performance.now() - (WAIT - secondsLeft * 1000);
      var now = performance.now();
      paint(now);
    }
  };

  paint(performance.now());
  requestAnimationFrame(frame);
});
