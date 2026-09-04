"""Tests for clinician user-manual help URL helpers."""

from __future__ import annotations

from anonymizer.utils.translate import set_language_code
from anonymizer.view.common.help_docs import (
    DOCS_BASE_URL,
    docs_language_prefix,
    help_page_url,
)


def test_help_page_url_english_default() -> None:
    set_language_code("en_US")
    assert docs_language_prefix() == ""
    assert help_page_url("start-here") == f"{DOCS_BASE_URL}/start-here/"
    assert help_page_url("") == f"{DOCS_BASE_URL}/"


def test_help_page_url_german_prefix() -> None:
    set_language_code("de")
    assert docs_language_prefix() == "de"
    assert help_page_url("headless") == f"{DOCS_BASE_URL}/de/headless/"
