/**
 * Swap MkDocs help screenshots to the visitor OS when available.
 *
 * Markdown authors embed shots/macos/*.png. On Windows browsers, rewrite to
 * shots/windows/* and fall back to macOS if the Windows PNG is missing.
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

  function rewriteShots() {
    if (docsShotOs() !== "windows") return;
    var images = document.querySelectorAll('img[src*="shots/macos/"]');
    images.forEach(function (img) {
      var macSrc = img.getAttribute("src");
      if (!macSrc || macSrc.indexOf(MAC_SEG) === -1) return;
      if (macSrc.indexOf(WIN_SEG) !== -1) return;
      var winSrc = macSrc.split(MAC_SEG).join(WIN_SEG);
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
