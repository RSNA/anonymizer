pyinstaller --noconfirm --onedir --windowed --add-data "/Users/michaelevans/.local/share/virtualenvs/dicom_scrub-ifLrTesE/lib/python3.11/site-packages/customtkinter:customtkinter/" --add-data "assets:assets" --icon assets/rsna_icon.icns -n "DICOM Anonymizer" dicom_scrub.py