# Screenshots-Styleguide

Für Autoren, die dieses Handbuch aktualisieren.

## Aufnahme-Regeln

- **Theme:** Hellmodus
- **Sprache:** UI beim Finalisieren des englischen Handbuchs in Englisch (`en_US`) aufnehmen
- **PHI:** nur Test-Fixtures — niemals echte Patientendaten
- **Ablage:** Screenshots liegen unter jedem nummerierten Workflow als `shots/macos/*.png` und `shots/windows/*.png`
- **Katalog:** [`docs/screenshots-manifest.yaml`](../screenshots-manifest.yaml) listet jedes UX-Element und jeden Shot
- **Skalierung / Auflösung:** Aufnahme speichert **logische UI-Punkte** (Retina 2× → 1 PNG-px ≈ 1 App-pt), dann erzwingt `normalize_for_docs` jedes PNG auf **`DOCS_SHOT_MAX_WIDTH`** (960): breite Fenster werden verkleinert, schmale Dialoge letterboxed (kein UI-Upscale). Gleiche Dateibreite ⇒ gleiche MkDocs-Skalierung ⇒ gleicher kleinster UI-Text über Seiten hinweg.
- **Keine Schatten:** macOS-Aufnahmen nutzen `screencapture -o` (Fensterschatten weglassen); restliche weiche Ränder werden vor dem Speichern entfernt. Keine Shots mit Schlagschatten ausliefern.
- **Ecken:** macOS nutzt Window-ID-Capture (`screencapture -l`), sodass PNGs abgerundete Ecken und Alpha behalten; Windows nutzt PrintWindow / BitBlt

## Workflow-Ordner

```
docs/en/02-install/shots/{macos,windows}/
docs/en/03-ai-features-setup/shots/{macos,windows}/
docs/en/05-create-project/shots/{macos,windows}/
docs/en/06-search/shots/{macos,windows}/
docs/en/07-view/shots/{macos,windows}/
docs/en/08-process/02-remove-burned-in-text/shots/{macos,windows}/
docs/en/08-process/03-harmonize-names/shots/{macos,windows}/
docs/en/08-process/04-blur-faces/shots/{macos,windows}/
docs/en/08-process/05-run-on-many-studies/shots/{macos,windows}/
docs/en/09-send/shots/{macos,windows}/
```

Markdown bettet den **macOS**-Pfad ein (Site-JS tauscht für Windows-Besucher auf Windows):

`![…](shots/macos/Welcome.png)`

## Automatisierte Aufnahme

Das Tooling liegt in [`src/docs_help/`](../../src/docs_help/) (nicht im ausgelieferten App-Paket).

**Vom Entwickler verantwortet:** neuesten Code auschecken, Capture auf **macOS** und erneut auf **Windows** ausführen, dann beide PNG-Bäume committen und pushen. Es gibt kein CI-/Cloud-Grab.

Erfordert ein Desktop-Display mit Bildschirmaufnahme-Berechtigung (macOS Screen Recording; Windows Desktop-Zugriff); Orthanc auf `127.0.0.1:4242` (AE `ORTHANC`) für Search/Query-Shots. Wenn Aufnahmen leer sind, Capture-Berechtigung erneut erteilen und mit `--force` neu starten.

```bash
uv run python -m docs_help --language en_US
uv run python -m docs_help --language en_US --force
uv run python -m docs_help --language en_US --force --only Welcome
```

- Schreibt `docs/<lang>/<chapter>/shots/<os>/`, wobei `<os>` `macos` oder `windows` ist (Host-OS; `--platform auto`)
- **Standardmäßig fortsetzen** (`--skip-existing`); mit `--force` oder `--force-shot ID` erneut
- Process-Demos nutzen nur **nicht-synthetische** Fixtures:
  - **8.1** Pixel-PHI entfernen → `davidson_cxr` (schwärzen) + `us_rgb_single_frame` (einblenden + Exclude Area unter mindray)
  - **8.2** Harmonisieren → `CT_Head_With_Contrast` (Serienansicht → abgeschlossene Ergebnisse → Hirn-Prompt → segmentierter mittlerer Schnitt) + `davidson_cxr` / `us_rgb_single_frame` (planare Playbook-Quellen)
  - **8.3** Gesichtsunschärfe → `CT_Head_With_Contrast` (Gaussian)
  - **8.4** Stapel → beide Fixtures im Datensatz ausgewählt
- Soft-Fail bei KI-lastigen Process-Shots, wenn Modelle fehlen
- Hard-Fail bei Orthanc-abhängigen Search-Shots, wenn C-ECHO fehlschlägt
- Fehlt ein Windows-PNG, fällt die veröffentlichte Site auf das macOS-Bild zurück

## Prioritäre Shots (V19)

Willkommen; KI-Funktionen; Projekteinstellungen anlegen (+ Unterdialoge); Dashboard; Suchen; Ansicht (Datensatz + Serien-/Studienbeschreibungsbearbeitung + Projektionen + Serie + Patientensuche-CSV); Verarbeiten (Pixel-PHI entfernen, Harmonisieren, Gesicht, Stapel); Senden (Anfang → Auswahl → Senden → gesendet).
