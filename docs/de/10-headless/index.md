# Ohne Oberfläche ausführen

Nutzen Sie den Headless-Modus auf einem **Labor- oder Server**, wenn Sie das Desktop-Fenster nicht brauchen. Legen Sie das Projekt zuerst in der GUI an und konfigurieren Sie es.

## Ziel

- Weiterhin DICOM in ein bestehendes Projekt empfangen und/oder
- KI-Stapel einmal auf diesem Projekt ausführen, dann beenden, und/oder
- Die **MCP**-Werkzeugschnittstelle bereitstellen, damit ein LLM-Client Projekte, Import, Inventar und Bildgebung steuern kann.

## Empfang und KI-Stapel

### 1. Nur empfangen (DICOM-Listener)

```bash
rsna-anonymizer -c path/to/ProjectModel.json
```

Die App lädt das Projekt und lauscht auf eingehende Bilder mit den lokalen Server-Einstellungen des Projekts.

### 2. KI-Stapel einmal, dann beenden

```bash
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

Sowohl `-c` / `--config` als auch `--ai-batch` sind mit `--ai-batch-run` erforderlich. Kombinieren Sie `-c` **nicht** mit `--mcp`.

## Wofür welche Datei

| Datei | Zweck |
| --- | --- |
| **ProjectModel.json** | Standort, Projektname, Speicherpfad, DICOM-Knoten, Modalitäten, Timeouts — die Projektdefinition. |
| **AiBatchConfig.json** | Welche KI-Werkzeuge laufen, Unschärfe-/OCR-Modi, Studienauswahl (`all` oder eine Liste), optionale CT/MR-Auflösungsüberschreibungen. |

Beispiel KI-Stapel-Konfiguration (herunterladbar: [`AiBatchConfig.example.json`](AiBatchConfig.example.json)):

```json
{
  "algorithms": ["harmonize", "face_blur", "remove_pixel_phi"],
  "blur_mode": "gaussian",
  "pixel_phi_removal_mode": "blackout",
  "use_modality_whitelist": true,
  "include_brain_structures": false,
  "ct_segmentation_mode": "3mm",
  "mr_segmentation_mode": "3mm",
  "studies": "all",
  "skip_already_processed": true
}
```

OCR-Whitelists bleiben unter dem Projektverzeichnis `whitelists/` (wie in der GUI).

## MCP-Server

`-c` und `--mcp` sind **gegenseitig ausschließend**. Projekte nach dem Verbinden mit MCP-Werkzeugen öffnen/anlegen.

Optionalen MCP-Extra einmal installieren (FastMCP-Server):

```bash
uv sync --extra mcp
# oder: pip install 'rsna-anonymizer[mcp]'
```

### HTTP-MCP

```bash
rsna-anonymizer --mcp 127.0.0.1:8000
```

Endpunkt: `http://127.0.0.1:8000/mcp`.

### Stdio-MCP

```bash
rsna-anonymizer --mcp
```

### Client-`mcp.json`

Beispiel: [`mcp.example.json`](mcp.example.json) / [`mcp.stdio.example.json`](mcp.stdio.example.json).

```json
{
  "mcpServers": {
    "rsna-anonymizer": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### Prototype MedGemma-Chat

```bash
# Terminal 1
uv sync --extra mcp
uv run rsna-anonymizer --mcp 127.0.0.1:8000

# Terminal 2
uv sync --extra mcp --group medgemma-chat
uv run python -m prototyping.medgemma_chat \
  --model /path/to/medgemma_hf_weights \
  --mcp-url http://127.0.0.1:8000/mcp
```

Details: `src/prototyping/medgemma_chat/README.md`.

## Voraussetzungen

- Projekt bereits in der GUI angelegt ([Projekt anlegen](../05-create-project/)).
- Modelle und Gesichtslizenz bereits auf **diesem Rechner** eingerichtet ([KI-Funktionen einrichten](../03-ai-features-setup)).
- Genug freier Speicher für die gewählten Algorithmen.

## So sieht es aus, wenn es passt

- Empfangsmodus: Prozess bleibt aktiv; neue Studien erscheinen unter Speicher / Datensatz, wenn Sie die GUI später öffnen.
- Stapelmodus: Protokoll zeigt Phasen und eine Zusammenfassung; Prozess beendet sich nach Fertigstellung (Exit-Code 0 bei Erfolg).

## Häufige Fehler

| Problem | Was prüfen |
| --- | --- |
| `--ai-batch-run` ohne Dateien | Sowohl `-c` als auch `--ai-batch` angeben |
| `-c` mit `--mcp` | Gegenseitig ausschließend |
| Feature-Gate-Fehler | Modelle / Lizenz auf diesem Arbeitsplatz herunterladen |
| Leere Studienliste | Zuerst Daten importieren oder `studies` in AiBatchConfig korrigieren |
| Wenig Speicher | Gleichzeitige Last reduzieren; siehe [Fehlerbehebung](../troubleshooting.md) |
| Client verbindet nicht | `--mcp HOST:PORT` vs. `mcp.json` (`http://HOST:PORT/mcp`); MCP-Extra installiert |
| Veraltete Werkzeuge | MCP neu starten; neuen Chat im Client öffnen |

## Für Kliniker

Headless ersetzt **nicht** die Prüfung einer Stichprobe im Datensatz oder in der Serienansicht. Nutzen Sie die GUI für Ersteinrichtung und Qualitätskontrollen; Headless für Routineempfang oder Nachtstapel.

!!! tip "Gleicher Job wie GUI-Stapel"
    Desktop-Schritte: [Auf vielen Studien ausführen](../08-process/05-run-on-many-studies/). Headless nutzt dieselben KI-Werkzeuge mit einem JSON-Rezept.

## Nächste Schritte

1. [Fehlerbehebung](../troubleshooting.md), wenn etwas fehlschlägt
2. [Tutorials](../tutorials/) für kurze Walkthroughs
3. Zurück zur [Startseite](../) für die vollständige Kapitelliste
