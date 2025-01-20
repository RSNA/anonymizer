#!/bin/sh

# Step 1: Update the .pot file, as per extract_translations.sh but with --join-existing
# Define the source directory and the output .pot file
SRC_DIR="../.."
POT_FILE="messages.pot"
# Find all .py files in the source directory and extract translatable strings
find $SRC_DIR -name '*.py' | xargs xgettext -v -d messages -o $POT_FILE --from-code UTF-8 -L Python --omit-header --no-wrap --no-location

# Step 2: Loop through each language directory in the locale directory
for lang_dir in */LC_MESSAGES; do
    # Define the .po and .mo files for the current language
    PO_FILE="$lang_dir/messages.po"
    MO_FILE="$lang_dir/messages.mo"

    # Step 3: Merge the updated .pot file with the existing .po file
    if [ -f "$PO_FILE" ]; then
        msgmerge -U $PO_FILE messages.pot --no-wrap
    fi

    # Step 4: Compile the .po file to a .mo file
    if [ -f "$PO_FILE" ]; then
        msgfmt -cv $PO_FILE -o $MO_FILE
    fi
done
