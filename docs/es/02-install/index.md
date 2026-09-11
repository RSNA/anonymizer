# Instalación y primer inicio

**La versión 19.0.1** es la primera versión oficial de V19. Necesita **Python 3.11 o 3.12** con **tkinter**, instalado mediante **uv**. Python 3.13 no es compatible.

## Instalar con uv y tkinter

Necesita tres cosas: **uv**, un entorno Python con **tkinter** y, en macOS, para Funciones de IA, la biblioteca C++ **libomp**.

### 1. Instalar uv

[uv](https://docs.astral.sh/uv/) gestiona Python, el entorno virtual y los paquetes grandes de IA.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Compruebe que uv está disponible:

```bash
uv --version
```

### 2. Instalar Python con tkinter y la aplicación

La ventana de escritorio necesita **tkinter**. Instale un Python que lo incluya, cree el venv e instale **19.0.1**:


| Plataforma | Asegurar tkinter |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows** | Instale Python 3.11 o 3.12 desde [python.org](https://www.python.org/downloads/) con **Add to PATH** y **tcl/tk and IDLE** |
| **macOS** | Prefiera `uv python install 3.12` (Tk 9.x). O Homebrew: `brew install python@3.12 python-tk@3.12` |
| **Linux** | `sudo apt install python3.12 python3.12-tk python3.12-venv` (o paquetes 3.11 equivalentes) |


```bash
uv python install 3.12
uv venv rsna-anonymizer --python 3.12
source rsna-anonymizer/bin/activate   # Windows: rsna-anonymizer\Scripts\activate

uv pip install rsna-anonymizer       # version 19.0.1
```

### 3. Verificar la instalación

```bash
python --version          # 3.11.x or 3.12.x
python -m tkinter         # a small Tk window must open — required for the UI
rsna-anonymizer --version # should report 19.0.1
```

Si `python -m tkinter` falla, recree el venv con un Python que incluya Tk (tabla anterior) y reinstale.

### 4. Solo macOS — OpenMP para Funciones de IA

En macOS, las **Funciones de IA** (TotalSegmentator / contraste Harmonize y herramientas relacionadas) necesitan la biblioteca C++ OpenMP `**libomp`**. Instálela una vez con Homebrew **antes** de descargar o ejecutar esos modelos:

```bash
brew install libomp
```

Sin `libomp`, el contraste de Harmonize puede fallar (por ejemplo, salida 139 o errores OpenMP de XGBoost). En Linux y Windows normalmente no hace falta este paso.

### 5. Ejecutar

```bash
rsna-anonymizer
```

## Primer inicio

![Pantalla Bienvenido](shots/macos/Welcome.png)

1. Se abre la pantalla **Bienvenido**.
2. Opcional pero recomendado: pulse **Funciones de IA** en Bienvenido para descargar modelos / aceptar la licencia de face (véase [Configuración de Funciones de IA](../03-ai-features-setup)). La configuración solo está disponible desde Bienvenido — cierre el proyecto para volver más tarde. En macOS, instale primero `libomp` (paso 4 arriba).
3. Cree o abra un proyecto desde el menú **Archivo**.

## Actualizar

```bash
source rsna-anonymizer/bin/activate
uv pip install --upgrade rsna-anonymizer
```

Notas de versión: [CHANGELOG](https://github.com/RSNA/anonymizer/blob/master/CHANGELOG.md).

## Siguientes pasos

1. [Configuración de Funciones de IA](../03-ai-features-setup/) — desde Bienvenido, descargar modelos (opcional pero recomendado)
2. [Palabras que usamos](../04-words-we-use/), luego [Crear un proyecto](../05-create-project/)
