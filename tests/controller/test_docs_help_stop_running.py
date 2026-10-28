"""Unit tests for docs_help Anonymizer process matching (no live kills)."""

from docs_help.stop_running import cmdline_looks_like_anonymizer_gui, owner_looks_like_anonymizer_app


def test_cmdline_matches_gui_entrypoints() -> None:
    assert cmdline_looks_like_anonymizer_gui("python -m anonymizer")
    assert cmdline_looks_like_anonymizer_gui("/venv/bin/rsna-anonymizer")
    assert cmdline_looks_like_anonymizer_gui("Anonymizer")
    assert cmdline_looks_like_anonymizer_gui(
        "/Users/me/CODE/anonymizer/.venv/bin/python -m anonymizer.anonymizer"
    )


def test_cmdline_excludes_docs_help_and_tests() -> None:
    assert not cmdline_looks_like_anonymizer_gui("python -m docs_help --language en_US")
    assert not cmdline_looks_like_anonymizer_gui("uv run python -m docs_help -v")
    assert not cmdline_looks_like_anonymizer_gui("pytest tests/controller/test_anonymizer.py")
    assert not cmdline_looks_like_anonymizer_gui("python -m pytest anonymizer")


def test_owner_matches_anonymizer_app_names() -> None:
    assert owner_looks_like_anonymizer_app("Anonymizer")
    assert owner_looks_like_anonymizer_app("rsna-anonymizer")
    assert owner_looks_like_anonymizer_app("RSNA DICOM Anonymizer")
    assert owner_looks_like_anonymizer_app("anonymizer.exe")


def test_owner_rejects_browsers_even_when_tab_title_matches() -> None:
    """Safari/Chrome must not be killed when a tab title contains the product name."""
    assert not owner_looks_like_anonymizer_app("Safari")
    assert not owner_looks_like_anonymizer_app("Google Chrome")
    assert not owner_looks_like_anonymizer_app("Firefox")
    assert not owner_looks_like_anonymizer_app("Microsoft Edge")
    assert not owner_looks_like_anonymizer_app("chrome.exe")
    assert not owner_looks_like_anonymizer_app("")
