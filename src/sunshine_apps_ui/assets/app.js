// SPDX-License-Identifier: GPL-3.0-or-later
// The one thing on these pages that needs scripting: Apply stays disabled
// until a field actually changes, so it cannot queue a no-op change.
(function () {
  "use strict";
  var form = document.querySelector("form[data-dirty-guard]");
  if (!form) return;
  var submit = form.querySelector("[data-apply]");
  if (!submit) return;

  var fields = Array.prototype.slice.call(
    form.querySelectorAll("input, textarea, select")
  );
  var initial = fields.map(function (f) {
    return f.type === "checkbox" ? String(f.checked) : f.value;
  });

  // A form can arrive already changed: a path or a cover chosen in a picker is
  // in the field before this runs, so there is nothing here to compare against.
  // The server says so, because it is the one that merged the two.
  var alreadyChanged = form.getAttribute("data-dirty") === "1";

  function changed() {
    if (alreadyChanged) return true;
    return fields.some(function (f, i) {
      var now = f.type === "checkbox" ? String(f.checked) : f.value;
      return now !== initial[i];
    });
  }

  function sync() {
    var dirty = changed();
    submit.disabled = !dirty;
    submit.title = dirty ? "" : "Change something first";
  }

  fields.forEach(function (f) {
    f.addEventListener("input", sync);
    f.addEventListener("change", sync);
  });
  sync();
})();
