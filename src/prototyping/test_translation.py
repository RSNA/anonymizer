import gettext

# Load the compiled MO file
domain = "messages"
localedir = "src/assets/locales"
lang = "es"
lang_translations = gettext.translation(domain, localedir, languages=[lang])
lang_translations.install()

# Example usage:
print(_("RSNA DICOM Anonymizer Version"))
print(_("Config file not found: "))
# Continue printing other translations as needed
