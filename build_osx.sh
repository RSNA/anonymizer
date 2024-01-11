export PYTHONOPTIMIZE=1
pyinstaller --noconfirm --target-arch universal2 --onedir --windowed --add-data "assets:assets" --icon assets/images/rsna_icon.icns -n "Anonymizer" anonymizer.py
