"""Open the published clinician user manual in the system browser.

Primary docs: https://rsna.github.io/anonymizer/
Offline fallback: local MkDocs ``site/`` build next to the repo/workdir when present.
"""

from __future__ import annotations

import logging
import webbrowser
from pathlib import Path

from anonymizer.utils.translate import _, get_current_language_code

logger = logging.getLogger(__name__)

DOCS_BASE_URL = "https://rsna.github.io/anonymizer"

# Menu label (gettext msgid) → docs page slug (no trailing slash).
HELP_TOPICS: tuple[tuple[str, str], ...] = (
    ("Start here", "01-start-here"),
    ("Install and first launch", "02-install"),
    ("Create a project", "04-create-project"),
    ("Search", "05-search"),
    ("View", "06-view"),
    ("Process", "07-process"),
    ("Send", "08-send"),
    ("AI Features setup", "07-process/01-ai-features-setup"),
    ("Remove burned-in text", "07-process/02-remove-burned-in-text"),
    ("Harmonize names", "07-process/03-harmonize-names"),
    ("Blur faces", "07-process/04-blur-faces"),
    ("Run on many studies", "07-process/05-run-on-many-studies"),
    ("Run without the window", "09-headless"),
    ("Troubleshooting", "troubleshooting"),
    ("Tutorials", "tutorials/"),
    ("License", "license"),
)


def docs_language_prefix() -> str:
    """Return URL language segment for mkdocs-static-i18n (empty for default English)."""
    code = (get_current_language_code() or "en_US").replace("-", "_")
    if code.lower().startswith("en"):
        return ""
    if code in {"de", "es", "fr"}:
        return code
    # en_US, etc.
    short = code.split("_", 1)[0].lower()
    if short == "en":
        return ""
    if short in {"de", "es", "fr"}:
        return short
    return ""


def help_page_url(slug: str, *, base_url: str = DOCS_BASE_URL) -> str:
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
        # Best-effort: open language subpath if present beside index.
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


def help_menu_topics() -> tuple[tuple[str, str], ...]:
    """Translated labels with page slugs for the Help menu."""
    return tuple((_(label), slug) for label, slug in HELP_TOPICS)
