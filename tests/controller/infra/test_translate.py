from pathlib import Path

import pytest

from anonymizer.utils.translate import (
    _current_translations,
    get_current_language,
    get_current_language_code,
    insert_space_after_codes,
    insert_spaces_between_cases,
    set_language,
    set_language_code,
)


def test_set_language_code_valid_code():
    """Test setting language code with a valid code."""
    set_language_code("en_US")
    assert get_current_language_code() == "en_US"


def test_locales_dir_is_install_relative(monkeypatch):
    """Locales resolve under assets/locales after chdir to the install dir."""
    from anonymizer.utils.translate import _, locales_dir, set_language_code

    install_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(install_dir)
    assert locales_dir() == Path("assets/locales")
    assert locales_dir().is_dir()
    set_language_code("de")
    assert _("Welcome") == "Willkommen"
    assert _("Select File → New Project to start.").startswith("Wählen")


def test_set_language_code_invalid_code():
    """Test setting language code with an invalid code."""
    with pytest.raises(ValueError) as excinfo:
        set_language_code("invalid_code")
    assert "Invalid language code" in str(excinfo.value)


def test_set_language_valid_language():
    """Test setting language with a valid language."""
    set_language("English")
    assert get_current_language() == "English"


def test_set_language_invalid_language():
    """Test setting language with an invalid language."""
    with pytest.raises(ValueError) as excinfo:
        set_language("invalid_language")
    assert "Invalid language" in str(excinfo.value)


def test_get_current_language_code_set():
    """Test getting current language code when language is set."""
    set_language_code("fr")
    assert get_current_language_code() == "fr"


def test_get_current_language_set():
    """Test getting current language when language is set."""
    set_language("Español")
    assert get_current_language() == "Español"


def test_insert_spaces_between_cases():
    """Test inserting spaces between lowercase and uppercase letters."""
    assert insert_spaces_between_cases("helloWorld") == "hello World"


def test_insert_space_after_codes():
    """Test inserting spaces after codes in a string."""
    codes = ["HTTP", "URL"]
    assert insert_space_after_codes("This is a HTTP URL", codes) == "This is a HTTP  URL "


def test_translation_after_set_language_code():
    """Test if _current_translations is set after set_language_code."""
    set_language_code("de")
    assert _current_translations is not None


