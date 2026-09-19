// SPDX-License-Identifier: GPL-3.0-or-later
//
// Watches a scan that is running, and leaves when it stops.
//
// This is a served file rather than an inline <script> because the pages here
// are sent with `script-src 'self'`: an inline script is refused by the
// browser, silently, and the first version of this page was exactly that. It
// rendered, showed the first line of the scan, and then never moved -- which
// looks identical to a scan that has hung.
//
// It takes its URLs from data attributes rather than being generated with the
// token baked in, so there is one copy of it and the token is escaped once, by
// the same rule as every other link on the page.
(function () {
  "use strict";
  var box = document.querySelector("[data-scan-status]");
  if (!box) return;
  var statusUrl = box.getAttribute("data-scan-status");
  var doneUrl = box.getAttribute("data-scan-done");
  var latest = document.getElementById("scan-latest");
  var elapsed = document.getElementById("scan-elapsed");

  function tick() {
    fetch(statusUrl, {cache: "no-store"})
      .then(function (response) { return response.json(); })
      .then(function (status) {
        if (latest && status.latest) latest.textContent = status.latest;
        if (elapsed) elapsed.textContent = status.elapsed;
        if (!status.running) {
          window.location.replace(doneUrl);
          return;
        }
        window.setTimeout(tick, 400);
      })
      .catch(function () {
        // A scan busy enough to miss a poll is still a scan. Ask again.
        window.setTimeout(tick, 1000);
      });
  }

  tick();
})();
