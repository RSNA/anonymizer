# translate.py: Set the locale and path for .mo translation files
import os
import gettext
import re
import os
import locale

# Set environment var: LANG for testing
# os.environ["LANG"] = "es"

language_code = locale.getlocale()[0]

if not language_code:
    language_code = "en_US"

language_code = "de"

# Load the compiled MO file
domain = "messages"
localedir = "src/assets/locales"
lang_translations = gettext.translation(domain, localedir, languages=[language_code], fallback=True)
lang_translations.install()
_ = lang_translations.gettext


def get_language_code():
    """
    Returns the language code for the current locale.

    Returns:
        str: The language code for the current locale.
    """
    return language_code


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
