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
// fit and how big the sheet has to be to hold exactly that many, and goes on
// to the address that fetches them.
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
    // An <img> with no picture yet may not honour its aspect-ratio, so it is
    // given the height a loaded one will have. Then the whole figure -- the
    // border, the gap above the caption, the caption -- is measured as laid
    // out, rather than added up from parts that could be missed.
    var img = sample.querySelector("img");
    var figure = sample.querySelector("figure");
    if (img) img.style.height = (img.getBoundingClientRect().width * TALL) + "px";
    var style = getComputedStyle(sample);
    var found = {
      count: columns.length,
      width: parseFloat(columns[0]) || 0,
      height: figure ? figure.getBoundingClientRect().height : 0,
      gap: parseFloat(style.rowGap) || 0,
      colGap: parseFloat(style.columnGap) || 0
    };
    body.removeChild(sample);
    return found;
  }

  var tile = measure();
  if (!tile.count || tile.width <= 0) return;

  var pad = getComputedStyle(body);
  var height = body.clientHeight -
    (parseFloat(pad.paddingTop) || 0) - (parseFloat(pad.paddingBottom) || 0);
  var width = body.clientWidth -
    (parseFloat(pad.paddingLeft) || 0) - (parseFloat(pad.paddingRight) || 0);
  if (tile.height <= 0 || height <= 0) return;

  // Whole rows only. A row sliced off by the bottom of the sheet is the thing
  // this is here to prevent.
  var rows = Math.floor((height + tile.gap) / (tile.height + tile.gap));
  if (rows < 1) rows = 1;

  var fits = tile.count * rows;
  if (fits < 1) return;

  // Then the sheet is drawn to fit the grid, not the screen. Whole rows leave
  // up to a row's height of empty space at the bottom, and that space is the
  // signal a short last page gives -- so on a full page it said "the end"
  // when it was not. The sheet shrinks by exactly the slack, and every page
  // of the run is drawn at this one size, so the last page's gap still means
  // what it should. A couple of pixels of leeway: a grid a fraction taller
  // than its box grows a scrollbar, which takes a column with it.
  var dialog = body.parentNode;
  var fit = "";
  if (dialog && dialog.offsetWidth && dialog.offsetHeight) {
    var usedH = rows * tile.height + (rows - 1) * tile.gap;
    var usedW = tile.count * tile.width + (tile.count - 1) * tile.colGap;
    var w = Math.ceil(dialog.offsetWidth - Math.max(0, width - usedW)) + 2;
    var h = Math.ceil(dialog.offsetHeight - Math.max(0, height - usedH)) + 2;
    if (w > 0 && h > 0) fit = "&fit=" + w + "x" + h;
  }

  // replace, not assign: the waiting page is a step on the way, and should not
  // be somewhere the Back button lands.
  location.replace(target + "&per=" + fits + fit);
})();
