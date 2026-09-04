"""Open the published clinician user manual in the system browser.

Primary docs: https://rsna.github.io/anonymizer/
Offline fallback: local MkDocs ``site/`` build next to the repo/workdir when present.
"""

from __future__ import annotations

import logging
import webbrowser
from pathlib import Path

from anonymizer.utils.translate import get_current_language_code

logger = logging.getLogger(__name__)

DOCS_BASE_URL = "https://rsna.github.io/anonymizer"
# Video walkthroughs (Help → Tutorials). Update when a dedicated playlist exists.
TUTORIALS_YOUTUBE_URL = "https://www.youtube.com/@RSNA"


def docs_language_prefix() -> str:
    """Return URL language segment for non-default locales (empty for English at site root)."""
    code = (get_current_language_code() or "en_US").replace("-", "_")
    if code.lower().startswith("en"):
        return ""
    if code in {"de", "es", "fr"}:
        return code
    short = code.split("_", 1)[0].lower()
    if short == "en":
        return ""
    if short in {"de", "es", "fr"}:
        return short
    return ""


def help_page_url(slug: str = "", *, base_url: str = DOCS_BASE_URL) -> str:
    slug = slug.strip("/")
    lang = docs_language_prefix()
    parts = [base_url.rstrip("/")]
    if lang:
        parts.append(lang)
    if slug:
        parts.append(slug)
    return "/".join(parts) + "/"


def local_site_index() -> Path | None:
    """Return ``site/index.html`` if a local MkDocs build is available."""
    candidates = [
        Path.cwd() / "site" / "index.html",
        Path(__file__).resolve().parents[4] / "site" / "index.html",  # repo root from src/anonymizer/view/common
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def open_help_page(slug: str = "") -> bool:
    """Open a help page in the default browser. Returns True if something was opened."""
    url = help_page_url(slug)
    try:
        if webbrowser.open(url):
            logger.info("Opened help URL: %s", url)
            return True
    except Exception:
        logger.exception("Failed to open help URL %s", url)

    local = local_site_index()
    if local is not None:
        local_url = local.resolve().as_uri()
        lang = docs_language_prefix()
        if slug:
            candidate = local.parent / lang / slug / "index.html" if lang else local.parent / slug / "index.html"
            if not candidate.is_file() and lang:
                candidate = local.parent / slug / "index.html"
            if candidate.is_file():
                local_url = candidate.resolve().as_uri()
        try:
            if webbrowser.open(local_url):
                logger.info("Opened local help: %s", local_url)
                return True
        except Exception:
            logger.exception("Failed to open local help %s", local_url)

    logger.warning("Could not open help for slug=%r", slug)
    return False


def open_tutorials_channel() -> bool:
    """Open the tutorials YouTube channel in the default browser."""
    try:
        if webbrowser.open(TUTORIALS_YOUTUBE_URL):
            logger.info("Opened tutorials URL: %s", TUTORIALS_YOUTUBE_URL)
            return True
    except Exception:
        logger.exception("Failed to open tutorials URL %s", TUTORIALS_YOUTUBE_URL)
    return False


def locale_html_dir() -> Path:
    """Return ``assets/locales/<lang>/html`` for the active UI language."""
    code = get_current_language_code() or "en_US"
    cwd_candidate = Path("assets/locales") / code / "html"
    if cwd_candidate.is_dir():
        return cwd_candidate
    packaged = Path(__file__).resolve().parents[2] / "assets" / "locales" / code / "html"
    return packaged


def license_html_path() -> Path | None:
    """Return the in-app license HTML for the current locale, if present."""
    candidates = [locale_html_dir()]
    en_fallback = Path("assets/locales/en_US/html")
    if not en_fallback.is_dir():
        en_fallback = Path(__file__).resolve().parents[2] / "assets" / "locales" / "en_US" / "html"
    if en_fallback not in candidates:
        candidates.append(en_fallback)

    for html_dir in candidates:
        if not html_dir.is_dir():
            continue
        for pattern in ("*license*.html", "*licence*.html", "*lizenz*.html", "*licencia*.html"):
            matches = sorted(html_dir.glob(pattern))
            if matches:
                return matches[0]
    return None


def help_menu_topics() -> tuple[tuple[str, str], ...]:
    """Deprecated: Help menu no longer lists every manual chapter."""
    return ()
