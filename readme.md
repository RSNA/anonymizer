# RSNA DICOM Anonymizer (V18 stable / V19 dev)
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

Use [uv](https://docs.astral.sh/uv/) for installs. It is much faster than plain `pip` for V19, which pulls large ML dependencies (PyTorch, TotalSegmentator, etc.).

### One-time: install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Restart the terminal if `uv` is not found.

### Create a virtual environment

```bash
uv venv rsna-anonymizer --python 3.12
source rsna-anonymizer/bin/activate    # Windows: rsna-anonymizer\Scripts\activate
```

### Install the package

Stable (V18):

```bash
uv pip install rsna-anonymizer
```

V19 development pre-release (requires `--pre`; does not replace the stable install above):

```bash
uv pip install --pre rsna-anonymizer
```

Pin a specific dev build:

```bash
uv pip install --pre rsna-anonymizer==19.0.0.dev2
```

Verify: `uv pip show rsna-anonymizer` or `rsna-anonymizer --version`. See [CHANGELOG](CHANGELOG.md#1900dev2) for dev release notes.

TotalSegmentator, XGBoost, and related dependencies are included. Enable Harmonize, Face Blur, and Remove Pixel PHI per project in **Settings → Project** (or when creating a new project). Download models and apply the face license from the AI Features panel.
## Execution
`rsna-anonymizer`
### Headless Mode
You need to provide a path to a project configuration to run in headless mode
`rsna-anonymizer -c path/to/ProjectModel.json`
## Upgrading

Activate the virtual environment first (`source rsna-anonymizer/bin/activate`).

Stable:

```bash
uv pip install --upgrade rsna-anonymizer
```

V19 dev pre-release:

```bash
uv pip install --upgrade --pre rsna-anonymizer
```

Pin a specific dev build:

```bash
uv pip install --upgrade --pre rsna-anonymizer==19.0.0.dev2
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
uv run pytest tests/controller/tseg -q                             # may download TS weights
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q              # prototyping only
uv run pytest -q                              # full local suite (controller + view + model)
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
