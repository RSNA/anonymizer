# RSNA DICOM Anonymizer (V19)
[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)

**Version 19.0.6** is the current V19 release on the `master` branch and PyPI. Requires **Python 3.11 or 3.12** with **tkinter** built in. Python 3.13 is not supported.

## Install

You need three things: **uv**, a Python **3.11/3.12** environment that includes **tkinter**, and (on macOS, for AI Features) **libomp**.

### 1. Install uv

[uv](https://docs.astral.sh/uv/) installs Python, creates the venv, and pulls large AI dependencies.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Confirm uv is on your PATH:

```bash
uv --version
```

### 2. Install Python with tkinter, then the app

The desktop UI needs **tkinter**. Install a Python that ships with it, then create the venv and install **19.0.6**:

| Platform | Ensure tkinter is available |
| --- | --- |
| **Windows** | Install Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/) with **Add to PATH** and **tcl/tk and IDLE** checked |
| **macOS** | Prefer `uv python install 3.12` (Tk 9.x). Or Homebrew: `brew install python@3.12 python-tk@3.12` |
| **Linux** | `sudo apt install python3.12 python3.12-tk python3.12-venv` (or the matching `python3.11` / `python3.11-tk` / `python3.11-venv` packages) |

```bash
uv python install 3.12                     # or: 3.11
uv venv rsna-anonymizer --python 3.12      # or: --python 3.11
source rsna-anonymizer/bin/activate        # Windows: rsna-anonymizer\Scripts\activate

uv pip install rsna-anonymizer             # version 19.0.6
```

### 3. Verify the install

```bash
python --version          # 3.11.x or 3.12.x
python -m tkinter         # a small Tk window must open — required for the UI
rsna-anonymizer --version # should report 19.0.6
```

If `python -m tkinter` fails, the venv’s Python was built without Tk: fix the platform step above, recreate the venv, and reinstall.

### 4. macOS only — OpenMP for AI Features

On macOS, **AI Features** that use TotalSegmentator / Harmonize contrast analysis need the C++ OpenMP runtime **`libomp`**. Install it once with Homebrew before you download or run those models:

```bash
brew install libomp
```

Without `libomp`, Harmonize contrast can crash (for example exit code 139 / XGBoost OpenMP errors). Face blur and other AI tools that depend on the same stack can be affected. Linux and Windows normally do not need this step.

### 5. Run

```bash
rsna-anonymizer
```

On first launch, use the Welcome screen **AI Features** button to download models and accept the face license when needed.

## Run (modes)

```bash
rsna-anonymizer
rsna-anonymizer -c path/to/ProjectModel.json   # headless DICOM receive
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Headless AI batch uses a companion [`AiBatchConfig.json`](docs/en/10-headless/AiBatchConfig.example.json) (algorithms, modes, study selection, CT/MR resolution). OCR whitelists remain under the project `whitelists/` directory.

## Upgrade

```bash
source rsna-anonymizer/bin/activate
uv pip install --upgrade rsna-anonymizer
```

See [CHANGELOG](CHANGELOG.md) for release notes.

## Documentation

[Clinician user manual](https://rsna.github.io/anonymizer) (MkDocs Material, English). Build locally: `uv sync --group docs && uv run mkdocs serve`. Maintainer notes: [`docs/README.md`](docs/README.md).

## Development

```bash
git clone https://github.com/RSNA/anonymizer.git
cd anonymizer
git checkout V19          # for V19 work
uv sync --group dev
uv run pre-commit install
uv run rsna-anonymizer
```

macOS AI Features: `brew install libomp` (OpenMP runtime for Harmonize contrast / TotalSegmentator).

Hot-reload UI work: `uv run python src/prototyping/dev_anonymizer.py` (optional [watchexec](https://github.com/watchexec/watchexec); falls back to `watchfiles`).

Experimental CLIs live under [`src/prototyping/`](src/prototyping/README.md).

### Linting (Ruff)

Config: `[tool.ruff]` in `pyproject.toml` (scope: `src/anonymizer/`).

```bash
uv run ruff check ./src/anonymizer/
uv run ruff check ./src/anonymizer/ --fix   # safe auto-fixes; not used in CI
uv run pre-commit run ruff-check --all-files
```

### Unit testing

Layout mirrors source: `tests/controller/` → `src/anonymizer/controller/`. Prototyping tests: `src/prototyping/*/tests/`. See [tests/README.md](tests/README.md).

```bash
uv run pytest tests/controller/tseg -q
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q
uv run pytest -q                                # full local suite
```

Optional: `tests/controller/.env` with `AWS_USERNAME` / `AWS_PASSWORD` for S3 upload tests. Markers are documented in `pyproject.toml` and `tests/README.md`.

### Translations

Languages: `en_US`, `de`, `es`, `fr`. Install gettext (`brew install gettext`, `choco install gettext`, or `apt install gettext`), then:

```bash
cd src/anonymizer/assets/locales/
./extract_translations.sh
./update_translations.sh
```

### Software architecture

[Class diagram](class_diagram.md)

### User manual (MkDocs)

```bash
uv sync --group docs
uv run mkdocs serve          # http://127.0.0.1:8000
uv run mkdocs build --strict
```
