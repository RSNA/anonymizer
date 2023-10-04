# translate.py: Set the locale and path for .mo translation files
import os
import gettext
import re

domain = "anonymizer"
localedir = os.path.join(os.path.dirname(__file__), "assets", "langpacks")
language_translations = gettext.translation(domain, localedir, fallback=True)
language_translations.install()
_ = language_translations.gettext


def insert_spaces_between_cases(input_string):
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", input_string)


def insert_space_after_codes(input_string, codes):
    # Create a regular expression pattern by joining the codes with a "|" (OR) operator
    pattern = "|".join(re.escape(code) for code in codes)
    return re.sub(rf"({pattern})", r"\1 ", input_string)
