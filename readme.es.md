# RSNA DICOM Anonimizador (V18 estable / V19 dev)
[![en](https://img.shields.io/badge/lang-en-blue.svg)](readme.md)
[![de](https://img.shields.io/badge/lang-de-blue.svg)](readme.de.md)
[![fr](https://img.shields.io/badge/lang-fr-blue.svg)](readme.fr.md)
[![Tests](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml/badge.svg)](https://github.com/RSNA/anonymizer/actions/workflows/tests.yaml)

## Instalar Python con tkinter (biblioteca GUI)
### Windows
1. Descarga Python 3.12 desde [python.org](https://www.python.org/downloads/)
2. Ejecuta el instalador
    - Selecciona "Add python.exe to PATH"
    - Habilita "tcl/tk and IDLE"
### macOS
1. Instala Homebrew si no está presente: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)'
2. Instala Python 3.12 con Tcl/Tk:
```
brew install python@3.12
brew install tcl-tk
```
### Linux (Ubuntu/Debian)
1. Instala los paquetes requeridos:
```
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12 python3.12-tk
```
## Verificar Instalación
```
python --version
python -m tkinter
```
Si python + tkinter se han instalado correctamente, se abrirá una pequeña ventana GUI
## Instalar el paquete rsna-anonymizer desde PyPI

Use [uv](https://docs.astral.sh/uv/) para las instalaciones. Es mucho más rápido que `pip` solo, sobre todo para V19, que descarga dependencias ML grandes (PyTorch, TotalSegmentator, etc.).

### Una vez: instalar uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Reinicie la terminal si no encuentra `uv`.

### Crear un entorno virtual

```bash
uv venv rsna-anonymizer --python 3.12
source rsna-anonymizer/bin/activate    # Windows: rsna-anonymizer\Scripts\activate
```

### Instalar el paquete

Estable (V18):

```bash
uv pip install rsna-anonymizer
```

Versión preliminar de desarrollo V19 (requiere `--pre`; no reemplaza la instalación estable anterior):

```bash
uv pip install --pre rsna-anonymizer
```

Fijar una versión dev concreta:

```bash
uv pip install --pre rsna-anonymizer==19.0.0.dev3
```

Verificar: `uv pip show rsna-anonymizer` o `rsna-anonymizer --version`. Ver [CHANGELOG](CHANGELOG.md#1900dev3).

TotalSegmentator, XGBoost y dependencias relacionadas están incluidos. Active Harmonize, Face Blur y Remove Pixel PHI por proyecto en **Configuración → Proyecto**. Descargue modelos y aplique la licencia face desde el panel AI Features.
## Ejecución
`rsna-anonymizer`
###Modo sin cabeza
Necesita proporcionar una ruta a una configuración de proyecto para ejecutar en modo sin cabeza
`rsna-anonymizer -c ruta/a/ProjectModel.json`
## Actualización

Active primero el entorno virtual (`source rsna-anonymizer/bin/activate`).

Estable:

```bash
uv pip install --upgrade rsna-anonymizer
```

V19 dev preliminar:

```bash
uv pip install --upgrade --pre rsna-anonymizer
```

Fijar una versión dev concreta:

```bash
uv pip install --upgrade --pre rsna-anonymizer==19.0.0.dev3
```
## Documentación
[Archivos de ayuda](https://mdevans.github.io/anonymizer/index.html)
