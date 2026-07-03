import locale

locale.setlocale(locale.LC_ALL, "de_DE.UTF-8")
for key, value in locale.localeconv().items():
    print("%s: %s" % (key, value))
