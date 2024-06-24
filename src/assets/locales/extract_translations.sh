#!/bin/sh

# Ensure gettext is installed:
# Linux: sudo apt-get install gettext
# Mac: brew install gettext
# Windows: https://mlocati.github.io/articles/gettext-iconv-windows.html or choco install gettext

# Define the source directory and the output .pot file
SRC_DIR="../.."
POT_FILE="messages.pot"

# Find all .py files in the source directory and extract translatable strings
#xgettext_output=$(find $SRC_DIR -name '*.py' | xargs xgettext -v -d messages -o $POT_FILE --from-code UTF-8 -L Python --omit-header --no-wrap --no-location 2>&1)

echo "$xgettext_output"
# To initialise a new language translation file, run the following command:
msginit -l es_ES.UTF8 -o es/LC_MESSAGES/messages.po -i messages.pot --no-translator --no-wrap
#msginit -l es_DE.UTF8 -o de/LC_MESSAGES/messages.po -i messages.pot --no-translator --no-wrap