# RSNA DICOM Anonymizer V18.0
[![de](https://img.shields.io/badge/lang-de-blue.svg)](readme.de.md)
[![es](https://img.shields.io/badge/lang-es-blue.svg)](readme.es.md)
[![fr](https://img.shields.io/badge/lang-fr-blue.svg)](readme.fr.md)
[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)

## Install Python with tkinter (GUI library)
### Windows
1. Download Python 3.12 from [python.org](https://www.python.org/downloads/) (pytorch does not currently support 3.13)
2. Run installer
   - Select "Add python.exe to PATH"
   - Enable "tcl/tk and IDLE"
### macOS
1. Install Homebrew if not present: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)'
2. Install Python 3.12 with Tcl/Tk:
```
brew install python@3.12
brew install tcl-tk
```
### Linux (Ubuntu/Debian)
1. Install the required packages:
```
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-tk
```
## Verify Installation
```
python --version
python -m tkinter
```
If python + tkinter has been installed successfully a small GUI window should open
## Install rsna-anonymizer package from PyPI
`pip install rsna-anonymizer`
## Execution
`rsna-anonymizer`
### Headless Mode
You need to provide a path to a project configuration to run in headless mode
`rsna-anonymizer -c path/to/ProjectModel.json`
## Upgrading
`pip install --upgrade rsna-anonymizer`
## Documentation
[Help files](https://rsna.github.io/anonymizer)
## Development
### Setup
1. Setup python environment (3.12) which includes Tkinter, recommend using pyenv with MacOS & Linux
2. Ensure python is installed with Tkinter: `python -m tkinter`, a small GUI window should open
3. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
4. Clone repository
5. Create virtual environment and install dependencies: `uv sync --group dev`
6. Optional — TotalSegmentator anatomy analysis for Harmonize: `uv sync --extra tseg --group dev`
7. Enable Git pre-commit hooks (Ruff lint, same rules as CI): `uv run pre-commit install`

Hooks run on every `git commit`, including commits from the VS Code / Cursor Source Control UI. To skip once: `git commit --no-verify`.

### Linting (Ruff)
Configuration: `[tool.ruff]` in `pyproject.toml` (scope: `src/anonymizer/`).

```bash
uv run ruff check ./src/anonymizer/
uv run ruff check ./src/anonymizer/ --fix   # safe auto-fixes only; not run in CI
uv run pre-commit run ruff-check --all-files
```

CI runs `ruff check` without `--fix`. Pre-commit uses the same check on staged Python files under `src/anonymizer/`.

### Unit Testing

Test layout mirrors source: `tests/controller/` → `src/anonymizer/controller/`, prototyping tests live under `src/prototyping/*/tests/`. See [tests/README.md](tests/README.md).

```bash
uv sync --extra tseg --group dev
uv run pytest tests/controller/tseg -q
uv run pytest src/prototyping -q              # local only; excluded from CI
uv run pytest -q                              # CI suite with coverage (see pyproject.toml)
```

Optional: create `tests/controller/.env` with `AWS_USERNAME` and `AWS_PASSWORD` for S3 upload tests.

Markers (`tseg_integration`, `dicom_integration`, `rsna_local_data`) are documented in `pyproject.toml` and `tests/README.md`.
### Translations
Languages for 17.3: `en_US, de, es, fr`
#### Ensure gettext is installed:
1. Windows: [Install instructions](https://mlocati.github.io/articles/gettext-iconv-windows.html) or `choco install gettext`
2. Mac OSX: `brew install gettext`
3. Linux: `sudo apt-get install gettext`
#### Extracting messages from source files:
cd src/anonymizer/assets/locales/
./extract_translations.sh
#### Updating translations:
cd src/anonymizer/assets/locales/
./update_translations.sh
### Software Architecture
Full class diagram on github [here](class_diagram.md)
