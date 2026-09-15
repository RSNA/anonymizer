/**
 * Swap MkDocs help screenshots to the visitor OS when available.
 *
 * Markdown authors embed shots/macos/*.png (relative to the current language
 * page, e.g. docs/de/06-search/…). On Windows browsers, rewrite only the OS
 * segment to shots/windows/* — language (/de/, /en/, …) is never changed.
 * If the Windows PNG is missing, fall back to that same-language macOS shot
 * (German Windows missing → German macOS, never English).
 *
 * MkDocs emits relative srcs such as ``shots/macos/Welcome.png`` (no leading
 * slash). Match ``shots/macos/`` anywhere in the path — not only ``/shots/macos/``.
 *
 * There is no HTML5 OS API; Client Hints + UA parsing is coarse but enough
 * for Mac vs Windows chrome selection.
 */
(function () {
  var MAC_SEG = "shots/macos/";
  var WIN_SEG = "shots/windows/";

  function docsShotOs() {
    var p = navigator.userAgentData && navigator.userAgentData.platform;
    if (p) {
      if (/Win/i.test(p)) return "windows";
      if (/Mac/i.test(p)) return "macos";
    }
    var ua = navigator.userAgent || "";
    if (/Windows/i.test(ua)) return "windows";
    if (/Mac OS X|Macintosh/i.test(ua)) return "macos";
    return "macos";
  }

  /** Replace shots/<os>/ only; leave language and chapter path untouched. */
  function swapShotOs(src, fromSeg, toSeg) {
    if (!src || src.indexOf(fromSeg) === -1) return null;
    if (src.indexOf(toSeg) !== -1) return null;
    return src.split(fromSeg).join(toSeg);
  }

  function rewriteShots() {
    if (docsShotOs() !== "windows") return;
    var images = document.querySelectorAll('img[src*="shots/macos/"]');
    images.forEach(function (img) {
      var macSrc = img.getAttribute("src");
      var winSrc = swapShotOs(macSrc, MAC_SEG, WIN_SEG);
      if (!winSrc) return;
      // Same-language macOS path for 404 fallback (never default-locale).
      img.setAttribute("data-docs-shot-macos", macSrc);
      img.addEventListener(
        "error",
        function () {
          var fallback = img.getAttribute("data-docs-shot-macos");
          if (fallback && img.getAttribute("src") !== fallback) {
            img.setAttribute("src", fallback);
          }
        },
        { once: true }
      );
      img.setAttribute("src", winSrc);
    });
  }

  function scheduleRewrite() {
    rewriteShots();
    // Material instant navigation replaces page content without a full reload.
    if (typeof document$ !== "undefined" && document$.subscribe) {
      document$.subscribe(rewriteShots);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleRewrite);
  } else {
    scheduleRewrite();
  }
})();
