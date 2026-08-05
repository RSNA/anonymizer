# RSNA DICOM Anonimizador (V19)
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
2. Instala Python 3.12, Tcl/Tk y OpenMP (OpenMP necesario para el análisis de contraste Harmonize en macOS):
```
brew install python@3.12
brew install tcl-tk
brew install libomp
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
## Instalar rsna-anonymizer desde PyPI

V19 está en PyPI como versión preliminar (`--pre`). Use [uv](https://docs.astral.sh/uv/) — mucho más rápido que `pip` para dependencias ML grandes (PyTorch, TotalSegmentator, etc.).

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

```bash
uv pip install --pre rsna-anonymizer
```

Verificar: `uv pip show rsna-anonymizer` o `rsna-anonymizer --version`. Ver [CHANGELOG](CHANGELOG.md).

TotalSegmentator, XGBoost y dependencias relacionadas están incluidos. Active AI Features por proyecto en **Configuración → Proyecto**. Descargue modelos y acepte la licencia face desde **AI Features** en la pantalla de bienvenida.
## Ejecución
`rsna-anonymizer`
###Modo sin cabeza
Necesita proporcionar una ruta a una configuración de proyecto para ejecutar en modo sin cabeza
`rsna-anonymizer -c ruta/a/ProjectModel.json`
## Actualización

Active primero el entorno virtual (`source rsna-anonymizer/bin/activate`).

```bash
uv pip install --upgrade --pre rsna-anonymizer
```
## Documentación
[Archivos de ayuda](https://mdevans.github.io/anonymizer/index.html)
