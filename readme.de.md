# RSNA DICOM Anonymizer (V19)

[en](readme.md) · [de](readme.de.md) · [es](readme.es.md) · [fr](readme.fr.md)

[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/rsna-anonymizer.svg)](https://pypi.org/project/rsna-anonymizer/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)

**Version 19.0.7** ist die aktuelle V19-Version auf dem Branch `master` und auf PyPI. Benötigt **Python 3.11 oder 3.12** mit eingebautem **tkinter**. Python 3.13 wird nicht unterstützt.

## Installation

Sie brauchen drei Dinge: **uv**, eine Python-Umgebung **3.11/3.12** mit **tkinter** und (unter macOS, für AI Features) **libomp**.

### 1. uv installieren

[uv](https://docs.astral.sh/uv/) installiert Python, erstellt die venv und lädt große AI-Abhängigkeiten.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Prüfen Sie, dass uv im PATH liegt:

```bash
uv --version
```

### 2. Python mit tkinter und die App installieren

Die Desktop-Oberfläche braucht **tkinter**. Installieren Sie ein Python mit tkinter, erstellen Sie die venv und installieren Sie **19.0.7**:

| Plattform | tkinter verfügbar machen |
| --- | --- |
| **Windows** | Python 3.11 oder 3.12 von [python.org](https://www.python.org/downloads/) mit **Add to PATH** und **tcl/tk and IDLE** |
| **macOS** | Bevorzugt `uv python install 3.12` (Tk 9.x). Oder Homebrew: `brew install python@3.12 python-tk@3.12` |
| **Linux** | `sudo apt install python3.12 python3.12-tk python3.12-venv` (oder passende `python3.11` / `python3.11-tk` / `python3.11-venv` Pakete) |

```bash
uv python install 3.12                     # or: 3.11
uv venv rsna-anonymizer --python 3.12      # or: --python 3.11
source rsna-anonymizer/bin/activate        # Windows: rsna-anonymizer\Scripts\activate

uv pip install rsna-anonymizer             # version 19.0.7
```

### 3. Installation prüfen

```bash
python --version          # 3.11.x or 3.12.x
python -m tkinter         # a small Tk window must open — required for the UI
rsna-anonymizer --version # should report 19.0.7
```

Wenn `python -m tkinter` fehlschlägt, wurde das Python der venv ohne Tk gebaut: Plattformschritt oben korrigieren, venv neu anlegen und neu installieren.

### 4. Nur macOS — OpenMP für AI Features

Unter macOS brauchen **AI Features**, die TotalSegmentator / Harmonize-Kontrastanalyse nutzen, die C++-OpenMP-Laufzeit **`libomp`**. Einmal mit Homebrew installieren, bevor Sie diese Modelle laden oder ausführen:

```bash
brew install libomp
```

Ohne `libomp` kann die Harmonize-Kontrastanalyse abstürzen (z. B. Exit-Code 139 / XGBoost-OpenMP-Fehler). Face blur und andere AI-Werkzeuge desselben Stacks können betroffen sein. Unter Linux und Windows ist dieser Schritt normalerweise nicht nötig.

### 5. Starten

```bash
rsna-anonymizer
```

Beim ersten Start über den Welcome-Bildschirm die Schaltfläche **AI Features** nutzen, um Modelle herunterzuladen und die Face-Lizenz bei Bedarf zu akzeptieren.

## Ausführen (Modi)

```bash
rsna-anonymizer
rsna-anonymizer -c path/to/ProjectModel.json   # headless DICOM receive
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Headless-AI-Batch nutzt eine Begleitdatei [`AiBatchConfig.json`](docs/en/10-headless/AiBatchConfig.example.json) (Algorithmen, Modi, Studienauswahl, CT/MR-Auflösung). OCR-Whitelists liegen weiterhin unter dem Projektverzeichnis `whitelists/`.

## Upgrade

```bash
source rsna-anonymizer/bin/activate
uv pip install --upgrade rsna-anonymizer
```

Release-Hinweise: [CHANGELOG](CHANGELOG.md).

## Dokumentation

[Klinisches Benutzerhandbuch](https://rsna.github.io/anonymizer) (MkDocs Material, Englisch). Lokal bauen: `uv sync --group docs && uv run mkdocs serve`. Hinweise für Maintainer: [`docs/README.md`](docs/README.md).

## Entwicklung

```bash
git clone https://github.com/RSNA/anonymizer.git
cd anonymizer
git checkout master
uv sync --group dev
uv run pre-commit install
uv run rsna-anonymizer
```

macOS AI Features: `brew install libomp` (OpenMP-Laufzeit für Harmonize-Kontrast / TotalSegmentator).

Hot-Reload der UI: `uv run python src/prototyping/dev_anonymizer.py` (optional [watchexec](https://github.com/watchexec/watchexec); Fallback `watchfiles`).

Experimentelle CLIs unter [`src/prototyping/`](src/prototyping/README.md).

### Linting (Ruff)

Konfiguration: `[tool.ruff]` in `pyproject.toml` (Scope: `src/anonymizer/`).

```bash
uv run ruff check ./src/anonymizer/
uv run ruff check ./src/anonymizer/ --fix   # safe auto-fixes; not used in CI
uv run pre-commit run ruff-check --all-files
```

### Unit-Tests

Struktur spiegelt den Quellcode: `tests/controller/` → `src/anonymizer/controller/`. Prototyping-Tests: `src/prototyping/*/tests/`. Siehe [tests/README.md](tests/README.md).

```bash
uv run pytest tests/controller/tseg -q
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q
uv run pytest -q                                # full local suite
```

Optional: `tests/controller/.env` mit `AWS_USERNAME` / `AWS_PASSWORD` für S3-Upload-Tests. Marker sind in `pyproject.toml` und `tests/README.md` dokumentiert.

### Übersetzungen

Sprachen: `en_US`, `de`, `es`, `fr`. gettext installieren (`brew install gettext`, `choco install gettext` oder `apt install gettext`), dann:

```bash
cd src/anonymizer/assets/locales/
./extract_translations.sh
./update_translations.sh
```

### Softwarearchitektur

[Klassendiagramm](class_diagram.md)

### Benutzerhandbuch (MkDocs)

```bash
uv sync --group docs
uv run mkdocs serve          # http://127.0.0.1:8000
uv run mkdocs build --strict
```

## Community

- [Verhaltenskodex](CODE_OF_CONDUCT.md)
- [Sicherheitsrichtlinie](SECURITY.md)
- [Lizenz](LICENSE) (Apache-2.0)
