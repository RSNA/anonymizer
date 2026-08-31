# RSNA DICOM Anonymizer (V19)
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
1. Install Homebrew if not present: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
2. Install Python **3.12** (not Homebrew's default `python3`, which may be 3.14), tkinter, and OpenMP (required for Harmonize contrast analysis on macOS):

```bash
brew install python@3.12 python-tk@3.12 libomp
```

Homebrew's `python@3.12` does not include tkinter by itself — use **`python-tk@3.12`**.

### Linux (Ubuntu/Debian)
1. Install the required packages:
```
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-tk python3.12-venv
```
## Verify Installation
Use **Python 3.12** explicitly (`python3.12`, not `python3`):

```bash
python3.12 --version
python3.12 -m tkinter
python3.12 -c "import tkinter as tk; print('Tk', tk.TkVersion)"
```

If python + tkinter has been installed successfully a small GUI window should open. On macOS, **Tk should be 9.0** for correct UI rendering with CustomTkinter 6.

## Install rsna-anonymizer from PyPI

V19 is on PyPI as a pre-release (`--pre`). Use [uv](https://docs.astral.sh/uv/) — much faster than plain `pip` for large ML dependencies (PyTorch, TotalSegmentator, etc.).

### One-time: install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Restart the terminal if `uv` is not found.

On macOS, update uv and install its managed Python 3.12 with Tcl/Tk 9 (recommended when Homebrew Python is broken or unavailable):

```bash
uv self update
uv python install --reinstall 3.12
```

### Create a virtual environment

```bash
uv venv rsna-anonymizer --python 3.12
source rsna-anonymizer/bin/activate    # Windows: rsna-anonymizer\Scripts\activate
```

Verify **inside the activated venv** (must be Python 3.12.x and Tk 9.0 on macOS):

```bash
python --version
python -c "import tkinter as tk; print('Tk', tk.TkVersion)"
```

If `uv venv --python 3.12` gives Tk 8.6, run `uv python install --reinstall 3.12` and recreate the venv. If Homebrew Python works, you can use `python3.12 -m venv rsna-anonymizer` and `python -m pip install --pre rsna-anonymizer` instead of `uv venv`.

### Install the package

```bash
uv pip install --pre rsna-anonymizer
```

Verify: `uv pip show rsna-anonymizer` or `rsna-anonymizer --version`. See [CHANGELOG](CHANGELOG.md) for release notes.

TotalSegmentator, XGBoost, and related dependencies are included. Download models and accept the face license from **Help → AI Features** or the **AI Features** button on the Welcome screen.
## Execution
`rsna-anonymizer`
### Headless Mode
You need to provide a path to a project configuration to run in headless mode
`rsna-anonymizer -c path/to/ProjectModel.json`
## Upgrading

Activate the virtual environment first (`source rsna-anonymizer/bin/activate`).

```bash
uv pip install --upgrade --pre rsna-anonymizer
```
## Documentation
[Help files](https://rsna.github.io/anonymizer)
## Development
### Setup
1. Setup python environment (3.12) which includes Tkinter, recommend using pyenv with MacOS & Linux
2. Ensure python is installed with Tkinter: `python -m tkinter`, a small GUI window should open
3. Install [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
4. Clone repository (for V19 work, checkout branch `V19` before syncing)
5. Create virtual environment and install dependencies: `uv sync --group dev`
6. macOS Harmonize contrast: `brew install libomp` when using XGBoost/TotalSegmentator contrast
7. Enable Git pre-commit hooks (Ruff lint, same rules as CI): `uv run pre-commit install`

For hot-reload during UI work: `uv run python scripts/dev_anonymizer.py` (requires [watchexec](https://github.com/watchexec/watchexec)).

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
uv sync --group dev
uv run pytest tests/controller/tseg -q                             # mocked unit tests (CI-safe)
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q              # prototyping only
uv run pytest -q                              # full local suite (controller + view + model)
```

Optional: create `tests/controller/.env` with `AWS_USERNAME` and `AWS_PASSWORD` for S3 upload tests.

Markers (`tseg_integration` is prototyping-only, plus `dicom_integration`, `rsna_local_data`) are documented in `pyproject.toml` and `tests/README.md`.
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
