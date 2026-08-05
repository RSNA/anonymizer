# RSNA DICOM Anonymisierer (V19)
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
2. Python 3.12, Tcl/Tk und OpenMP installieren (OpenMP für Harmonize-Kontrastanalyse unter macOS erforderlich):
```
brew install python@3.12
brew install tcl-tk
brew install libomp
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
## rsna-anonymizer von PyPI installieren

V19 ist auf PyPI als Vorabversion verfügbar (`--pre`). Verwenden Sie [uv](https://docs.astral.sh/uv/) — deutlich schneller als reines `pip` bei großen ML-Abhängigkeiten (PyTorch, TotalSegmentator usw.).

### Einmalig: uv installieren

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Terminal neu starten, falls `uv` nicht gefunden wird.

### Virtuelle Umgebung anlegen

```bash
uv venv rsna-anonymizer --python 3.12
source rsna-anonymizer/bin/activate    # Windows: rsna-anonymizer\Scripts\activate
```

### Paket installieren

```bash
uv pip install --pre rsna-anonymizer
```

Prüfen: `uv pip show rsna-anonymizer` oder `rsna-anonymizer --version`. Siehe [CHANGELOG](CHANGELOG.md).

TotalSegmentator, XGBoost und zugehörige Abhängigkeiten sind enthalten. AI Features pro Projekt unter **Einstellungen → Projekt** aktivieren. Modelle und Face-Lizenz über **AI Features** auf dem Willkommensbildschirm herunterladen bzw. hinterlegen.
## Ausführung
`rsna-anonymizer`
### Headless-Modus
Sie müssen einen Pfad zu einer Projektkonfiguration angeben, um im Headless-Modus zu laufen
`rsna-anonymizer -c pfad/zu/ProjectModel.json`
## Aktualisierung

Zuerst die virtuelle Umgebung aktivieren (`source rsna-anonymizer/bin/activate`).

```bash
uv pip install --upgrade --pre rsna-anonymizer
```
## Dokumentation
[Hilfedateien](https://mdevans.github.io/anonymizer/index.html)
