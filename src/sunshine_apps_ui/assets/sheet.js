// SPDX-License-Identifier: GPL-3.0-or-later
//
// How many SteamGridDB pictures fit on this screen.
//
// The tiles are a fixed size -- the same `minmax(150px,1fr)` at 2:3 that the
// main grid and the artwork picker use, because a picture being chosen should
// be the size of the thing it is being chosen for. So what adapts to the
// screen is the number of them, not their size, and that number is something
// only the browser can know.
//
// This runs on the waiting page: the sheet is already up with a spinner in it,
// nothing has been asked of SteamGridDB yet, and the empty body is exactly the
// box the pictures will go in. It measures that box, works out how many tiles
// fit, and goes on to the address that fetches them.
//
// **Without it the page still works.** The waiting page carries a
// `<meta http-equiv="refresh">` to the same address without a count, and the
// server falls back to a full page; the body scrolls if that is more than the
// screen holds. This is the difference between a page that fits and one that
// scrolls, not between working and not -- which is the line issue #28 drew.
(function () {
  "use strict";

  var body = document.querySelector(".sheet-body");
  var onward = document.querySelector('meta[http-equiv="refresh"]');
  if (!body || !onward) return;

  // "0;url=..." -- the address the no-script path would go to anyway.
  var target = String(onward.getAttribute("content") || "");
  var at = target.toLowerCase().indexOf("url=");
  if (at === -1) return;
  target = target.slice(at + 4).trim();
  if (!target || target.charAt(0) !== "/") return;   // ours, and only ours
  if (/[?&]per=/.test(target)) return;               // already counted

  var TALL = 3 / 2;   // a cover's height as a multiple of its width

  // A real tile, laid out by the real stylesheet, rather than numbers copied
  // out of it. Hidden from sight and from anything reading the page aloud; it
  // exists for one measurement and is taken out again.
  function measure() {
    var sample = document.createElement("div");
    sample.className = "arts";
    sample.setAttribute("aria-hidden", "true");
    sample.style.cssText = "position:absolute;visibility:hidden;" +
      "left:-9999px;top:0;width:" + body.clientWidth + "px";
    sample.innerHTML =
      '<figure><a href="#"><img alt=""></a>' +
      "<figcaption><b>by someone</b>choose</figcaption></figure>";
    body.appendChild(sample);

    var columns = getComputedStyle(sample).gridTemplateColumns
      .split(" ").filter(function (n) { return n; });
    var caption = sample.querySelector("figcaption");
    var found = {
      count: columns.length,
      width: parseFloat(columns[0]) || 0,
      caption: caption ? caption.getBoundingClientRect().height : 0,
      gap: parseFloat(getComputedStyle(sample).rowGap) || 0
    };
    body.removeChild(sample);
    return found;
  }

  var tile = measure();
  if (!tile.count || tile.width <= 0) return;

  var pad = getComputedStyle(body);
  var height = body.clientHeight -
    (parseFloat(pad.paddingTop) || 0) - (parseFloat(pad.paddingBottom) || 0);
  var tileHeight = tile.width * TALL + tile.caption;
  if (tileHeight <= 0 || height <= 0) return;

  // Whole rows only. A row sliced off by the bottom of the sheet is the thing
  // this is here to prevent.
  var rows = Math.floor((height + tile.gap) / (tileHeight + tile.gap));
  if (rows < 1) rows = 1;

  var fits = tile.count * rows;
  if (fits < 1) return;

  // replace, not assign: the waiting page is a step on the way, and should not
  // be somewhere the Back button lands.
  location.replace(target + "&per=" + fits);
})();
