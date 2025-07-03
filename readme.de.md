# RSNA DICOM Anonymisierer V18.0
[![en](https://img.shields.io/badge/lang-en-blue.svg)](readme.md)
[![es](https://img.shields.io/badge/lang-es-blue.svg)](readme.es.md)
[![fr](https://img.shields.io/badge/lang-fr-blue.svg)](readme.fr.md)
[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)
## Python mit tkinter (GUI-Bibliothek) installieren
### Windows
1. Laden Sie Python 3.12 von [python.org](https://www.python.org/downloads/) herunter
2. Führen Sie das Installationsprogramm aus
    - Wählen Sie "Add python.exe to PATH"
    - Aktivieren Sie "tcl/tk und IDLE"
### macOS
1. Installieren Sie Homebrew, falls nicht vorhanden: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)`
2. Installieren Sie Python 3.12 mit Tcl/Tk:
```
brew install python@3.12
brew install tcl-tk
```
### Linux (Ubuntu/Debian)
1. Installieren Sie die erforderlichen Pakete:
```
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-tk
```
## Installation überprüfen
```
python --version
python -m tkinter
```
Wenn Python + tkinter erfolgreich installiert wurde, sollte ein kleines GUI-Fenster geöffnet werden
## rsna-anonymizer Paket von PyPI installieren
`pip install rsna-anonymizer`
## Ausführung
`rsna-anonymizer`
### Headless-Modus
Sie müssen einen Pfad zu einer Projektkonfiguration angeben, um im Headless-Modus zu laufen
`rsna-anonymizer -c pfad/zu/ProjectModel.json`
## Aktualisierung
`pip install --upgrade rsna-anonymizer`
## Dokumentation
[Hilfedateien](https://mdevans.github.io/anonymizer/index.html)
