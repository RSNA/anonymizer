# RSNA DICOM l'Anonymiseur V17
[![en](https://img.shields.io/badge/lang-en-blue.svg)](readme.md)
[![de](https://img.shields.io/badge/lang-de-blue.svg)](readme.de.md)
[![es](https://img.shields.io/badge/lang-es-blue.svg)](readme.es.md)
[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)
## Installation de Python avec tkinter (bibliothèque GUI)
### Windows
1. Téléchargez Python 3.12+ depuis [python.org](https://www.python.org/downloads/)
2. Exécutez l'installateur
    - Sélectionnez "Add python.exe to PATH"
    - Activez "tcl/tk and IDLE"
### macOS
1. Installez Homebrew si absent : `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
2. Installez Python 3.12 avec Tcl/Tk :
```
brew install python@3.12
brew install tcl-tk
```
### Linux (Ubuntu/Debian)
1. Installez les paquets requis :
```
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-tk
```
## Vérification de l'installation
```
python --version
python -m tkinter
```
Si python + tkinter sont installés correctement, une petite fenêtre GUI devrait s'ouvrir
## Installation du paquet rsna-anonymizer depuis PyPI
`pip install rsna-anonymizer`
## Exécution
`rsna-anonymizer`
## Mise à jour
`pip install --upgrade rsna-anonymizer`
## Documentation
[Fichiers d'aide](https://mdevans.github.io/anonymizer/index.html)
