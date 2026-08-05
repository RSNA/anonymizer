# RSNA DICOM Anonymisierer (V18 stabil / V19 dev)
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

Verwenden Sie [uv](https://docs.astral.sh/uv/) für Installationen. Es ist deutlich schneller als reines `pip`, besonders für V19 mit großen ML-Abhängigkeiten (PyTorch, TotalSegmentator usw.).

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

Stabil (V18):

```bash
uv pip install rsna-anonymizer
```

V19 Entwicklungs-Vorabversion (erfordert `--pre`; ersetzt nicht die stabile Installation oben):

```bash
uv pip install --pre rsna-anonymizer
```

Bestimmte Dev-Version festlegen:

```bash
uv pip install --pre rsna-anonymizer==19.0.0.dev3
```

Prüfen: `uv pip show rsna-anonymizer` oder `rsna-anonymizer --version`. Siehe [CHANGELOG](CHANGELOG.md#1900dev3).

TotalSegmentator, XGBoost und zugehörige Abhängigkeiten sind enthalten. Harmonize, Face Blur und Remove Pixel PHI pro Projekt unter **Einstellungen → Projekt** aktivieren. Modelle und Face-Lizenz im AI-Features-Panel herunterladen bzw. hinterlegen.
## Ausführung
`rsna-anonymizer`
### Headless-Modus
Sie müssen einen Pfad zu einer Projektkonfiguration angeben, um im Headless-Modus zu laufen
`rsna-anonymizer -c pfad/zu/ProjectModel.json`
## Aktualisierung

Zuerst die virtuelle Umgebung aktivieren (`source rsna-anonymizer/bin/activate`).

Stabil:

```bash
uv pip install --upgrade rsna-anonymizer
```

V19 Dev-Vorabversion:

```bash
uv pip install --upgrade --pre rsna-anonymizer
```

Bestimmte Dev-Version festlegen:

```bash
uv pip install --upgrade --pre rsna-anonymizer==19.0.0.dev3
```
## Dokumentation
[Hilfedateien](https://mdevans.github.io/anonymizer/index.html)
