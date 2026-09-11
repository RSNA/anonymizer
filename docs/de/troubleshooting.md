# Fehlerbehebung

## Modelle und KI-Funktionen

| Meldung / Symptom | Was versuchen |
| --- | --- |
| Nicht bereit / Download fehlgeschlagen | Zum **Willkommen**-Bildschirm zurück, **KI-Funktionen** öffnen, Herunterladen erneut versuchen, Netzwerk prüfen |
| OpenMP / XGBoost unter macOS | C++-OpenMP einmal installieren: `brew install libomp` (erforderlich für KI-Funktionen / Harmonize-Kontrast) |
| Lizenzfehler | `aca_`-Länge/Format prüfen; online validieren |
| Harmonisieren läuft bereits | Andere Serie beenden oder abbrechen |
| Werkzeug ausgegraut | Passendes CT/MR-Paket installieren |

## Import und Quarantäne

| Symptom | Was versuchen |
| --- | --- |
| Dateien ignoriert | Bereits importiert (gleiche SOP Instance) |
| Quarantäneordner füllen sich | Ordnernamen lesen (Invalid_DICOM, Missing_Attributes, Lookup_Miss, …) |
| Lookup_Miss | [Nachschlagetabelle](05-create-project/) oder Patienten-ID korrigieren |

## Stapel und Speicher

| Symptom | Was versuchen |
| --- | --- |
| Wenig Speicher / gestoppt | Andere Apps schließen; weniger Studien; siehe Speicherwarnungsdialog |
| Alles übersprungen | Bereits verarbeitet — erwartet, außer Sie leeren Status/Cache |
| Keine Serien für Studien | Auswahl hat keine lesbaren DICOM-Serien |

## Headless

Vollständige Anleitung: [Ohne Oberfläche ausführen](10-headless/).

- `--ai-batch-run` braucht **sowohl** `-c` als auch `--ai-batch`
- Feature-Gates scheitern, wenn Modelle auf diesem Rechner nie heruntergeladen wurden
- Leeres `studies` / kein PHI-Index → zuerst in der GUI importieren

## Anzeige

| Symptom | Was versuchen |
| --- | --- |
| Willkommen-Fenster winzig / abgeschnitten (macOS) | Aktuelles V19 nutzen; Tipps zu Tk 9 / uv-Neuinstallation unter [Installation](02-install/) |
| Projektionen scheitern bei Farb-US | Auf aktuelles V19 aktualisieren |
