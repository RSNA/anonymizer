/**
 * Swap MkDocs help screenshots to the visitor OS when available.
 *
 * Markdown authors embed shots/macos/*.png. On Windows browsers, rewrite to
 * shots/windows/* and fall back to macOS if the Windows PNG is missing.
 *
 * There is no HTML5 OS API; Client Hints + UA parsing is coarse but enough
 * for Mac vs Windows chrome selection.
 */
(function () {
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
    var images = document.querySelectorAll('img[src*="/shots/macos/"]');
    images.forEach(function (img) {
      var macSrc = img.getAttribute("src");
      if (!macSrc || macSrc.indexOf("/shots/macos/") === -1) return;
      var winSrc = macSrc.replace("/shots/macos/", "/shots/windows/");
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", rewriteShots);
  } else {
    rewriteShots();
  }
})();
