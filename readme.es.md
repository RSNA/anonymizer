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

Estable (V18):

```bash
pip install rsna-anonymizer
```

Versión preliminar de desarrollo V19 (requiere `--pre`; no reemplaza la instalación estable anterior):

```bash
pip install --pre rsna-anonymizer
```

Fijar una versión dev concreta:

```bash
pip install --pre rsna-anonymizer==19.0.0.dev2
```

Verificar: `pip show rsna-anonymizer` o `rsna-anonymizer --version`. Ver [CHANGELOG](CHANGELOG.md#1900dev2).

TotalSegmentator, XGBoost y dependencias relacionadas están incluidos. Active Harmonize, Face Blur y Remove Pixel PHI por proyecto en **Configuración → Proyecto**. Descargue modelos y aplique la licencia face desde el panel AI Features.
## Ejecución
`rsna-anonymizer`
###Modo sin cabeza
Necesita proporcionar una ruta a una configuración de proyecto para ejecutar en modo sin cabeza
`rsna-anonymizer -c ruta/a/ProjectModel.json`
## Actualización

Estable:

```bash
pip install --upgrade rsna-anonymizer
```

V19 dev preliminar:

```bash
pip install --upgrade --pre rsna-anonymizer
```
## Documentación
[Archivos de ayuda](https://mdevans.github.io/anonymizer/index.html)
