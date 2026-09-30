// SPDX-License-Identifier: GPL-3.0-or-later
// The edit page's scripting (#61):
//   - Apply stays off until a field actually changes, so it cannot queue a
//     no-op change; off is drawn flat. A new application needs a name first.
//   - Custom's stepper: shown only while Custom is chosen, and its - and +.
//   - The Keyboard button in the bar, shown while a text field has focus,
//     on the edit page and on Settings (the SteamGridDB key, a password field).
(function () {
  "use strict";
  var form = document.querySelector("form[data-dirty-guard]");
  if (form) guard(form);

  function guard(form) {
  var submit = document.querySelector("[data-apply]");

  function inputs() {
    // The form's own fields and those outside it that belong to it.
    return Array.prototype.slice.call(form.elements).filter(function (f) {
      return /^(INPUT|TEXTAREA|SELECT)$/.test(f.tagName) && f.type !== "hidden";
    });
  }
  function value(f) {
    return (f.type === "checkbox" || f.type === "radio") ? String(f.checked) : f.value;
  }
  var fields = inputs();
  var initial = fields.map(value);

  // A form can arrive already changed: a path or a cover chosen in a picker is
  // in the field before this runs, so there is nothing here to compare against.
  // The server says so, because it is the one that merged the two.
  var alreadyChanged = form.getAttribute("data-dirty") === "1";
  var needsName = form.hasAttribute("data-needs-name");
  var nameField = form.querySelector("input[name=name]");

  function changed() {
    if (needsName) return !!(nameField && nameField.value.trim());
    if (alreadyChanged) return true;
    return fields.some(function (f, i) { return value(f) !== initial[i]; });
  }

  function sync() {
    if (!submit) return;
    var ready = changed();
    submit.disabled = !ready;
    submit.classList.toggle("flat", !ready);
    submit.title = ready ? "" : (needsName ? "Give it a name first" : "Change something first");
  }

  // Custom opens the stepper; the presets close it.
  var stepper = form.querySelector(".stepper");
  var custom = stepper && stepper.querySelector("input");
  function syncStepper() {
    if (!stepper) return;
    var on = !!form.querySelector("input[name=exit-timeout][value=custom]:checked");
    stepper.style.display = on ? "" : "none";
  }
  if (stepper) {
    Array.prototype.forEach.call(stepper.querySelectorAll("[data-step]"), function (b) {
      b.addEventListener("click", function () {
        var now = parseInt(custom.value, 10);
        if (isNaN(now)) now = 0;
        custom.value = String(Math.max(0, now + parseInt(b.getAttribute("data-step"), 10)));
        sync();
      });
    });
  }

  fields.forEach(function (f) {
    f.addEventListener("input", sync);
    f.addEventListener("change", function () { syncStepper(); sync(); });
  });
  syncStepper();
  sync();
  }

  // Show password (#70): the eye in the field and X in the bar both turn the
  // password field between hidden and shown.
  Array.prototype.forEach.call(document.querySelectorAll("[data-show-password]"), function (b) {
    b.addEventListener("click", function () {
      var field = document.getElementById(b.getAttribute("data-show-password"));
      if (!field) return;
      var show = field.type === "password";
      field.type = show ? "text" : "password";
      Array.prototype.forEach.call(document.querySelectorAll("[data-show-password]"), function (other) {
        other.setAttribute("aria-pressed", show ? "true" : "false");
        var label = other.querySelector("[data-show-label]");
        if (label) label.textContent = show ? "Hide password" : "Show password";
      });
    });
  });

  // The Keyboard button: A on a text field opens the keyboard, and this says
  // so in the bar. The stylesheet shows it only while a controller is in use.
  var kb = document.querySelector(".btn.kb");
  var typing = null;
  function isText(el) {
    return !!el && el.tagName === "INPUT" && (el.type === "text" || el.type === "password") && !el.readOnly;
  }
  if (kb) {
    document.addEventListener("focusin", function (e) {
      if (e.target === kb) return;
      typing = isText(e.target) ? e.target : null;
      kb.style.display = typing ? "" : "none";
    });
    kb.addEventListener("click", function () {
      if (typing) document.dispatchEvent(new CustomEvent("pad:type", { detail: typing }));
    });
    if (isText(document.activeElement)) { typing = document.activeElement; kb.style.display = ""; }
  }
})();
