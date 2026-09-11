# RSNA DICOM Anonymizer (V19)

[en](readme.md) · [de](readme.de.md) · [es](readme.es.md) · [fr](readme.fr.md)

[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/rsna-anonymizer.svg)](https://pypi.org/project/rsna-anonymizer/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)

**La version 19.0.7** est la version V19 actuelle sur la branche `master` et sur PyPI. Nécessite **Python 3.11 ou 3.12** avec **tkinter** intégré. Python 3.13 n’est pas pris en charge.

## Installation

Il vous faut trois éléments : **uv**, un environnement Python **3.11/3.12** avec **tkinter**, et (sous macOS, pour AI Features) **libomp**.

### 1. Installer uv

[uv](https://docs.astral.sh/uv/) installe Python, crée le venv et télécharge les grosses dépendances d’IA.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Vérifiez que uv est dans le PATH :

```bash
uv --version
```

### 2. Installer Python avec tkinter, puis l’application

L’interface de bureau a besoin de **tkinter**. Installez un Python qui l’inclut, créez le venv et installez **19.0.7** :

| Plateforme | Assurer la disponibilité de tkinter |
| --- | --- |
| **Windows** | Installez Python 3.11 ou 3.12 depuis [python.org](https://www.python.org/downloads/) avec **Add to PATH** et **tcl/tk and IDLE** |
| **macOS** | Préférez `uv python install 3.12` (Tk 9.x). Ou Homebrew : `brew install python@3.12 python-tk@3.12` |
| **Linux** | `sudo apt install python3.12 python3.12-tk python3.12-venv` (ou les paquets `python3.11` / `python3.11-tk` / `python3.11-venv` correspondants) |

```bash
uv python install 3.12                     # or: 3.11
uv venv rsna-anonymizer --python 3.12      # or: --python 3.11
source rsna-anonymizer/bin/activate        # Windows: rsna-anonymizer\Scripts\activate

uv pip install rsna-anonymizer             # version 19.0.7
```

### 3. Vérifier l’installation

```bash
python --version          # 3.11.x or 3.12.x
python -m tkinter         # a small Tk window must open — required for the UI
rsna-anonymizer --version # should report 19.0.7
```

Si `python -m tkinter` échoue, le Python du venv a été compilé sans Tk : corrigez l’étape plateforme ci-dessus, recréez le venv et réinstallez.

### 4. macOS uniquement — OpenMP pour AI Features

Sous macOS, les **AI Features** qui utilisent TotalSegmentator / l’analyse de contraste Harmonize ont besoin du runtime C++ OpenMP **`libomp`**. Installez-le une fois avec Homebrew avant de télécharger ou d’exécuter ces modèles :

```bash
brew install libomp
```

Sans `libomp`, le contraste Harmonize peut planter (par exemple code de sortie 139 / erreurs OpenMP XGBoost). Face blur et d’autres outils d’IA du même stack peuvent être affectés. Sous Linux et Windows, cette étape n’est en général pas nécessaire.

### 5. Lancer

```bash
rsna-anonymizer
```

Au premier démarrage, utilisez le bouton **AI Features** de l’écran Welcome pour télécharger les modèles et accepter la licence face si besoin.

## Exécution (modes)

```bash
rsna-anonymizer
rsna-anonymizer -c path/to/ProjectModel.json   # headless DICOM receive
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Le lot d’IA sans interface utilise un fichier compagnon [`AiBatchConfig.json`](docs/en/10-headless/AiBatchConfig.example.json) (algorithmes, modes, sélection d’études, résolution CT/MR). Les listes blanches OCR restent sous le répertoire projet `whitelists/`.

## Mise à jour

```bash
source rsna-anonymizer/bin/activate
uv pip install --upgrade rsna-anonymizer
```

Notes de version : [CHANGELOG](CHANGELOG.md).

## Documentation

[Manuel utilisateur clinicien](https://rsna.github.io/anonymizer) (MkDocs Material, anglais). Build local : `uv sync --group docs && uv run mkdocs serve`. Notes mainteneur : [`docs/README.md`](docs/README.md).

## Développement

```bash
git clone https://github.com/RSNA/anonymizer.git
cd anonymizer
git checkout master
uv sync --group dev
uv run pre-commit install
uv run rsna-anonymizer
```

AI Features sous macOS : `brew install libomp` (runtime OpenMP pour contraste Harmonize / TotalSegmentator).

Rechargement à chaud de l’UI : `uv run python src/prototyping/dev_anonymizer.py` (optionnel [watchexec](https://github.com/watchexec/watchexec) ; sinon `watchfiles`).

CLIs expérimentaux sous [`src/prototyping/`](src/prototyping/README.md).

### Linting (Ruff)

Config : `[tool.ruff]` dans `pyproject.toml` (périmètre : `src/anonymizer/`).

```bash
uv run ruff check ./src/anonymizer/
uv run ruff check ./src/anonymizer/ --fix   # safe auto-fixes; not used in CI
uv run pre-commit run ruff-check --all-files
```

### Tests unitaires

La structure reflète le code source : `tests/controller/` → `src/anonymizer/controller/`. Tests prototypage : `src/prototyping/*/tests/`. Voir [tests/README.md](tests/README.md).

```bash
uv run pytest tests/controller/tseg -q
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q
uv run pytest -q                                # full local suite
```

Optionnel : `tests/controller/.env` avec `AWS_USERNAME` / `AWS_PASSWORD` pour les tests d’upload S3. Les marqueurs sont documentés dans `pyproject.toml` et `tests/README.md`.

### Traductions

Langues : `en_US`, `de`, `es`, `fr`. Installez gettext (`brew install gettext`, `choco install gettext` ou `apt install gettext`), puis :

```bash
cd src/anonymizer/assets/locales/
./extract_translations.sh
./update_translations.sh
```

### Architecture logicielle

[Diagramme de classes](class_diagram.md)

### Manuel utilisateur (MkDocs)

```bash
uv sync --group docs
uv run mkdocs serve          # http://127.0.0.1:8000
uv run mkdocs build --strict
```

## Communauté

- [Code de conduite](CODE_OF_CONDUCT.md)
- [Politique de sécurité](SECURITY.md)
- [Licence](LICENSE) (Apache-2.0)
