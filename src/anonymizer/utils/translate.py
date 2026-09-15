"""
translate.py: Application gettext catalog and language selection.

Does not use the Python locale module for UI language. Numerics and dates stay
en_US / DICOM-style for all languages.

Catalog files live under the installed package tree
``anonymizer/assets/locales/<lang>/LC_MESSAGES/messages.mo``. Loading is always
resolved from this package path — never from process CWD — so UI translation
does not depend on platform launch directory or ``os.chdir``.
"""

from __future__ import annotations

import gettext
import logging
import re
from pathlib import Path
from pprint import pformat

# Language name to locale sub-directory name mapping (assets/locales/*)
language_to_code: dict[str, str] = {"English": "en_US", "Deutsch": "de", "Español": "es", "Français": "fr"}
code_to_language: dict[str, str] = {v: k for k, v in language_to_code.items()}

# ``utils/translate.py`` → package root ``anonymizer/``
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_LOCALES_DIR = _PACKAGE_ROOT / "assets" / "locales"

_current_language_code: str | None = None
_current_translations: gettext.NullTranslations | None = None

logger = logging.getLogger(__name__)


def locales_dir() -> Path:
    """Absolute path to packaged gettext locales (platform- and CWD-independent)."""
    return _LOCALES_DIR


def _(msg: str) -> str:
    if not _current_translations:
        raise ValueError("Language not set")
    return _current_translations.gettext(msg)


def set_language_code(lang_code: str):
    """
    Sets the language code for the application.

    Args:
        language_code (str): The language code to set.
    """
    global _current_language_code
    global _current_translations

    if lang_code not in language_to_code.values():
        raise ValueError(f"Invalid language code: {lang_code}")

    localedir = locales_dir()
    logger.info("Setting language code to '%s' (localedir=%s)", lang_code, localedir)

    if not localedir.is_dir():
        raise ValueError(f"Locales directory not found: {localedir}")

    # Latch the language code
    _current_language_code = lang_code

    # Load the compiled MO from the package tree only (no CWD fallback).
    domain = "messages"
    try:
        _current_translations = gettext.translation(
            domain,
            localedir=str(localedir),
            languages=[lang_code],
            fallback=False,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"Language catalog not found: {lang_code} under {localedir}") from exc

    catalog_path = localedir / lang_code / "LC_MESSAGES" / f"{domain}.mo"
    logger.info(
        "Loaded translations from %s:\n%s",
        catalog_path,
        pformat(getattr(_current_translations, "_info", {})),
    )


# Default to US English: en_US
set_language_code("en_US")


def set_language(language: str):
    """
    Sets the language for the application.

    Args:
        language (str): The language to set.
    """
    if language not in language_to_code:
        raise ValueError(f"Invalid language: {language}")

    set_language_code(language_to_code[language])


def get_current_language_code() -> str:
    """
    Returns the language code for the current locale.

    Returns:
        str: The language code for the current locale.
    """
    if not _current_language_code:
        raise ValueError("Language not set")
    return _current_language_code


def get_current_language() -> str:
    """
    Returns the language for the current locale.

    Returns:
        str: The language for the current locale.
    """
    if not _current_language_code:
        raise ValueError("Language not set")
    return code_to_language[_current_language_code]


def insert_spaces_between_cases(input_string):
    """
    Inserts spaces between lowercase and uppercase letters in a string.

    Args:
        input_string (str): The input string to process.

    Returns:
        str: The modified string with spaces inserted between lowercase and uppercase letters.
    """
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", input_string)


def insert_space_after_codes(input_string, codes):
    """
    Inserts a space after each occurrence of the specified codes in the input string.

    Args:
        input_string (str): The input string to process.
        codes (list): A list of codes to search for in the input string.

    Returns:
        str: The modified input string with spaces inserted after the codes.
    """
    # Create a regular expression pattern by joining the codes with a "|" (OR) operator
    pattern = "|".join(re.escape(code) for code in codes)
    return re.sub(rf"({pattern})", r"\1 ", input_string)
