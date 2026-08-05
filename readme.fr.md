# RSNA DICOM l'Anonymiseur (V18 stable / V19 dev)
[![en](https://img.shields.io/badge/lang-en-blue.svg)](readme.md)
[![de](https://img.shields.io/badge/lang-de-blue.svg)](readme.de.md)
[![es](https://img.shields.io/badge/lang-es-blue.svg)](readme.es.md)
[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)
## Installation de Python avec tkinter (bibliothèque GUI)
### Windows
1. Téléchargez Python 3.12 depuis [python.org](https://www.python.org/downloads/)
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

Stable (V18) :

```bash
pip install rsna-anonymizer
```

Préversion de développement V19 (nécessite `--pre` ; ne remplace pas l'installation stable ci-dessus) :

```bash
pip install --pre rsna-anonymizer
```

Épingler une version dev précise :

```bash
pip install --pre rsna-anonymizer==19.0.0.dev1
```

Vérifier : `pip show rsna-anonymizer` ou `rsna-anonymizer --version`. Voir [CHANGELOG](CHANGELOG.md#1900dev1).

TotalSegmentator, XGBoost et dépendances associées sont inclus. Activez Harmonize, Face Blur et Remove Pixel PHI par projet dans **Paramètres → Projet**. Téléchargez les modèles et appliquez la licence face depuis le panneau AI Features.
## Exécution
`rsna-anonymizer`
### Mode sans tête
Vous devez fournir un chemin vers une configuration de projet pour fonctionner en mode sans tête
`rsna-anonymizer -c chemin/vers/ProjectModel.json`
## Mise à jour

Stable :

```bash
pip install --upgrade rsna-anonymizer
```

Préversion dev V19 :

```bash
pip install --upgrade --pre rsna-anonymizer
```
## Documentation
[Fichiers d'aide](https://mdevans.github.io/anonymizer/index.html)
