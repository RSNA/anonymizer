#!/bin/sh

# Ensure gettext is installed:
# Linux: sudo apt-get install gettext
# Mac: brew install gettext
# Windows: https://mlocati.github.io/articles/gettext-iconv-windows.html or choco install gettext

# Define the source directory and the output .pot file
SRC_DIR="../.."
POT_FILE="messages.pot"

# Find all .py files in the source directory and extract translatable strings
find $SRC_DIR -name '*.py' | xargs xgettext -v -d messages -o $POT_FILE --from-code UTF-8 -L Python --omit-header --no-wrap --no-location

# To initialise a new language translation file, run the following command:
msginit -l en_US -o en_US/LC_MESSAGES/messages.po -i messages.pot --no-translator --no-wrap
#msginit -l es -o es/LC_MESSAGES/messages.po -i messages.pot --no-translator --no-wrap
#msginit -l de -o de/LC_MESSAGES/messages.po -i messages.pot --no-translator --no-wrap
#msginit -l fr -o de/LC_MESSAGES/messages.po -i messages.pot --no-translator --no-wrap