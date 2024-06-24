# translate.py: Set the locale and path for .mo translation files
import os
import gettext
import re

# localedir = os.path.join(os.path.dirname(__file__), "assets", "locale")
# language_translations = gettext.translation("messages", localedir, fallback=True)
# language_translations.install()
# _ = language_translations.gettext

# Load the compiled MO file
domain = "messages"
localedir = "src/assets/locales"
lang = "de"
lang_translations = gettext.translation(domain, localedir, languages=[lang])
lang_translations.install()
_ = lang_translations.gettext


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
