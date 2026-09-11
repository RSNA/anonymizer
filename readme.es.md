# RSNA DICOM Anonymizer (V19)

[en](readme.md) · [de](readme.de.md) · [es](readme.es.md) · [fr](readme.fr.md)

[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/rsna-anonymizer.svg)](https://pypi.org/project/rsna-anonymizer/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)

**La versión 19.0.7** es la versión V19 actual en la rama `master` y en PyPI. Requiere **Python 3.11 o 3.12** con **tkinter** incluido. Python 3.13 no es compatible.

## Instalación

Necesita tres cosas: **uv**, un entorno Python **3.11/3.12** con **tkinter** y (en macOS, para AI Features) **libomp**.

### 1. Instalar uv

[uv](https://docs.astral.sh/uv/) instala Python, crea el venv y descarga dependencias de IA grandes.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Compruebe que uv está en el PATH:

```bash
uv --version
```

### 2. Instalar Python con tkinter y la aplicación

La interfaz de escritorio necesita **tkinter**. Instale un Python que lo incluya, cree el venv e instale **19.0.7**:

| Plataforma | Asegurar tkinter |
| --- | --- |
| **Windows** | Instale Python 3.11 o 3.12 desde [python.org](https://www.python.org/downloads/) con **Add to PATH** y **tcl/tk and IDLE** |
| **macOS** | Prefiera `uv python install 3.12` (Tk 9.x). O Homebrew: `brew install python@3.12 python-tk@3.12` |
| **Linux** | `sudo apt install python3.12 python3.12-tk python3.12-venv` (o los paquetes equivalentes `python3.11` / `python3.11-tk` / `python3.11-venv`) |

```bash
uv python install 3.12                     # or: 3.11
uv venv rsna-anonymizer --python 3.12      # or: --python 3.11
source rsna-anonymizer/bin/activate        # Windows: rsna-anonymizer\Scripts\activate

uv pip install rsna-anonymizer             # version 19.0.7
```

### 3. Verificar la instalación

```bash
python --version          # 3.11.x or 3.12.x
python -m tkinter         # a small Tk window must open — required for the UI
rsna-anonymizer --version # should report 19.0.7
```

Si `python -m tkinter` falla, el Python del venv se compiló sin Tk: corrija el paso de la plataforma, recree el venv y reinstale.

### 4. Solo macOS — OpenMP para AI Features

En macOS, las **AI Features** que usan TotalSegmentator / análisis de contraste Harmonize necesitan el runtime C++ OpenMP **`libomp`**. Instálelo una vez con Homebrew antes de descargar o ejecutar esos modelos:

```bash
brew install libomp
```

Sin `libomp`, el contraste de Harmonize puede fallar (por ejemplo, código de salida 139 / errores OpenMP de XGBoost). Face blur y otras herramientas de IA del mismo stack pueden verse afectadas. En Linux y Windows normalmente no hace falta este paso.

### 5. Ejecutar

```bash
rsna-anonymizer
```

En el primer inicio, use el botón **AI Features** de la pantalla Welcome para descargar modelos y aceptar la licencia de face cuando sea necesario.

## Ejecución (modos)

```bash
rsna-anonymizer
rsna-anonymizer -c path/to/ProjectModel.json   # headless DICOM receive
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

El lote de IA sin interfaz usa un archivo acompañante [`AiBatchConfig.json`](docs/en/10-headless/AiBatchConfig.example.json) (algoritmos, modos, selección de estudios, resolución CT/MR). Las listas blancas OCR siguen en el directorio del proyecto `whitelists/`.

## Actualizar

```bash
source rsna-anonymizer/bin/activate
uv pip install --upgrade rsna-anonymizer
```

Notas de versión: [CHANGELOG](CHANGELOG.md).

## Documentación

[Manual de usuario clínico](https://rsna.github.io/anonymizer) (MkDocs Material, inglés). Compilar en local: `uv sync --group docs && uv run mkdocs serve`. Notas para mantenedores: [`docs/README.md`](docs/README.md).

## Desarrollo

```bash
git clone https://github.com/RSNA/anonymizer.git
cd anonymizer
git checkout master
uv sync --group dev
uv run pre-commit install
uv run rsna-anonymizer
```

AI Features en macOS: `brew install libomp` (runtime OpenMP para contraste Harmonize / TotalSegmentator).

Recarga en caliente de la UI: `uv run python src/prototyping/dev_anonymizer.py` (opcional [watchexec](https://github.com/watchexec/watchexec); alternativa `watchfiles`).

CLIs experimentales en [`src/prototyping/`](src/prototyping/README.md).

### Linting (Ruff)

Configuración: `[tool.ruff]` en `pyproject.toml` (alcance: `src/anonymizer/`).

```bash
uv run ruff check ./src/anonymizer/
uv run ruff check ./src/anonymizer/ --fix   # safe auto-fixes; not used in CI
uv run pre-commit run ruff-check --all-files
```

### Pruebas unitarias

La estructura refleja el código: `tests/controller/` → `src/anonymizer/controller/`. Pruebas de prototipos: `src/prototyping/*/tests/`. Véase [tests/README.md](tests/README.md).

```bash
uv run pytest tests/controller/tseg -q
uv run pytest tests/controller tests/model -q   # CI suite (no view)
uv run pytest src/prototyping -q
uv run pytest -q                                # full local suite
```

Opcional: `tests/controller/.env` con `AWS_USERNAME` / `AWS_PASSWORD` para pruebas de subida a S3. Los marcadores están documentados en `pyproject.toml` y `tests/README.md`.

### Traducciones

Idiomas: `en_US`, `de`, `es`, `fr`. Instale gettext (`brew install gettext`, `choco install gettext` o `apt install gettext`) y luego:

```bash
cd src/anonymizer/assets/locales/
./extract_translations.sh
./update_translations.sh
```

### Arquitectura del software

[Diagrama de clases](class_diagram.md)

### Manual de usuario (MkDocs)

```bash
uv sync --group docs
uv run mkdocs serve          # http://127.0.0.1:8000
uv run mkdocs build --strict
```

## Comunidad

- [Código de conducta](CODE_OF_CONDUCT.md)
- [Política de seguridad](SECURITY.md)
- [Licencia](LICENSE) (Apache-2.0)
