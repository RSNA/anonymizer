# translate.py: Set the path for .mo translation files and language code for the html help system
# Do not use python locale module, manage language settings within the application
# Numerics and Dates are based on en_US / DICOM std for all languages
import gettext
import re
import logging
from pprint import pformat

# Language name to locale sub-directory name mapping (assets/locales/*)
language_to_code = {"English": "en_US", "Deutsch": "de", "Español": "es", "Français": "fr"}
code_to_language = {v: k for k, v in language_to_code.items()}

_current_language_code: str = None
_current_translations = None

logger = logging.getLogger(__name__)


def _(msg: str) -> str:
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

    logger.info(f"Setting language code to '{lang_code}'")

    # Latch the language code
    _current_language_code = lang_code

    # Load the compiled MO file
    domain = "messages"
    localedir = "assets/locales"
    # Load the compiled MO file
    _current_translations = gettext.translation(domain, localedir, languages=[lang_code], fallback=True)
    logger.info(f"_current_translations:\n{pformat(_current_translations._info)}")


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


def get_current_language_code():
    """
    Returns the language code for the current locale.

    Returns:
        str: The language code for the current locale.
    """
    return _current_language_code


def get_current_language():
    """
    Returns the language for the current locale.

    Returns:
        str: The language for the current locale.
    """
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
