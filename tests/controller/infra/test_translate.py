import pytest

from pathlib import Path

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


def test_ai_features_strings_translate_in_german() -> None:
    import gettext

    localedir = Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "assets" / "locales"
    translations = gettext.translation("messages", localedir=str(localedir), languages=["de"])
    assert translations.gettext("AI Features") == "KI-Funktionen"
    assert translations.gettext("Harmonize") == "Harmonisieren"
    assert translations.gettext("Slice Thickness") == "Schichtdicke"
    assert translations.gettext("Installed (1.5 mm).") == "Installiert (1,5 mm)."
    assert translations.gettext("Installed (0.5 x 0.5 x 1 mm).") == "Installiert (0,5 x 0,5 x 1 mm)."
    assert translations.gettext("Installed: 1.5 mm.") == "Installiert: 1,5 mm."
    assert translations.gettext("Use modality whitelist") == "Modalitäts-Freigabeliste verwenden"
    assert translations.gettext("Strict") == "Strikt"
    assert translations.gettext("WHITELIST") == "Freigabeliste"
    assert translations.gettext("Harmonized") == "Harmonisiert"
    assert translations.gettext("Face blur") == "Gesichtsunschärfe"
    assert translations.gettext("Pixel PHI") == "Pixel-PHI"
    assert translations.gettext("View Dataset") == "Datensatz anzeigen"
    assert translations.gettext("No") == "Nein"
    assert translations.gettext("Yes") == "Ja"
    assert translations.gettext("Value") == "Wert"
    assert translations.gettext("Evidence") == "Nachweis"
    assert translations.gettext("Source") == "Quelle"
    assert translations.gettext("Chest") == "Thorax"
    assert translations.gettext("Without contrast") == "Ohne Kontrast"
    assert translations.gettext("MIN") == "MIN"
    assert translations.gettext("MEAN") == "MITTEL"
    assert translations.gettext("MAX") == "MAX"
    assert translations.gettext("SLICE") == "SCHICHT"
