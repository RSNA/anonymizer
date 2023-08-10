# translate.py: Set the locale and path for .mo translation files
import os
import gettext

domain = "anonymizer"
localedir = os.path.join(os.path.dirname(__file__), "assets", "langpacks")
language_translations = gettext.translation(domain, localedir, fallback=True)
language_translations.install()
_ = language_translations.gettext
