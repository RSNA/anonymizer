# Installation und erster Start

**Version 19.0.1** ist die erste offizielle V19-Version. Sie brauchen **Python 3.11 oder 3.12** mit **tkinter**, installiert über **uv**. Python 3.13 wird nicht unterstützt.

## Installation mit uv und tkinter

Sie brauchen drei Dinge: **uv**, eine Python-Umgebung mit **tkinter**, und unter macOS für KI-Funktionen die C++-Bibliothek **libomp**.

### 1. uv installieren

[uv](https://docs.astral.sh/uv/) verwaltet Python, die virtuelle Umgebung und große KI-Pakete.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

Prüfen Sie, dass uv verfügbar ist:

```bash
uv --version
```

### 2. Python mit tkinter und die App installieren

Das Desktop-Fenster braucht **tkinter**. Installieren Sie ein Python mit tkinter, erstellen Sie die venv und installieren Sie **19.0.1**:


| Plattform | tkinter verfügbar machen |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows** | Python 3.11 oder 3.12 von [python.org](https://www.python.org/downloads/) mit **Add to PATH** und **tcl/tk and IDLE** |
| **macOS** | Bevorzugt `uv python install 3.12` (Tk 9.x). Oder Homebrew: `brew install python@3.12 python-tk@3.12` |
| **Linux** | `sudo apt install python3.12 python3.12-tk python3.12-venv` (oder passende 3.11-Pakete) |


```bash
uv python install 3.12
uv venv rsna-anonymizer --python 3.12
source rsna-anonymizer/bin/activate   # Windows: rsna-anonymizer\Scripts\activate

uv pip install rsna-anonymizer       # version 19.0.1
```

### 3. Installation prüfen

```bash
python --version          # 3.11.x or 3.12.x
python -m tkinter         # a small Tk window must open — required for the UI
rsna-anonymizer --version # should report 19.0.1
```

Wenn `python -m tkinter` fehlschlägt, legen Sie die venv mit einem Python neu an, das Tk enthält (Tabelle oben), und installieren Sie erneut.

### 4. Nur macOS — OpenMP für KI-Funktionen

Unter macOS brauchen **KI-Funktionen** (TotalSegmentator / Harmonize-Kontrast und verwandte Werkzeuge) die C++-OpenMP-Bibliothek `**libomp`**. Einmal mit Homebrew installieren, **bevor** Sie diese Modelle laden oder ausführen:

```bash
brew install libomp
```

Ohne `libomp` kann die Harmonize-Kontrastanalyse abstürzen (z. B. Exit 139 oder XGBoost-OpenMP-Fehler). Unter Linux und Windows ist dieser Schritt normalerweise nicht nötig.

### 5. Starten

```bash
rsna-anonymizer
```

## Erster Start

![Willkommen-Bildschirm](shots/macos/Welcome.png)

1. Der **Willkommen**-Bildschirm öffnet sich.
2. Optional, aber empfohlen: auf dem Willkommen-Bildschirm **KI-Funktionen** wählen, um Modelle zu laden / die Face-Lizenz zu akzeptieren (siehe [KI-Funktionen einrichten](../03-ai-features-setup)). Die Einrichtung ist nur vom Willkommen-Bildschirm aus verfügbar — schließen Sie das Projekt, um später dorthin zurückzukehren. Unter macOS zuerst `libomp` installieren (Schritt 4 oben).
3. Über das Menü **Datei** ein Projekt anlegen oder öffnen.

## Upgrade

```bash
source rsna-anonymizer/bin/activate
uv pip install --upgrade rsna-anonymizer
```

Release-Hinweise: [CHANGELOG](https://github.com/RSNA/anonymizer/blob/master/CHANGELOG.md).

## Nächste Schritte

1. [KI-Funktionen einrichten](../03-ai-features-setup/) — vom Willkommen-Bildschirm Modelle laden (optional, aber empfohlen)
2. [Begriffe](../04-words-we-use/), dann [Projekt anlegen](../05-create-project/)
