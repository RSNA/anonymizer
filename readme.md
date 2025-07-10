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
1. Setup python environment (>3.10) which includes Tkinter, recommend using pyenv with MacOS & Linux
2. Ensure python is installed with Tkinter: `python -m tkinter`, a small GUI window should open
3. Install poetry: `pip install poetry`
4. Set virtual environment within project: `poetry config virtualenvs.in-project true`
4. Clone repository
5. Setup virtual environment and install all dependencies listed in pyproject.toml: `poetry install --with dev`
### Unit Testing 
#### For model and controller with coverage
```
1. Create tests/controller/.env file with your AWS_USERNAME and AWS_PASSWORD
2. poetry run pytest
```
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
