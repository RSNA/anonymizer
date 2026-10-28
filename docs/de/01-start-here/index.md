# Hier beginnen

## Was dieses Programm tut

Der RSNA DICOM Anonymizer ist eine eigenständige Anwendung, die **geschützte Identitätsinformationen** aus medizinischen Bildgebungsstudien entfernt und eine forschungssichere Kopie auf Ihrem Computer speichert.

Sie können Bilder aus einem Ordner oder aus einem klinischen Bildgebungssystem übernehmen, prüfen, optional KI-Werkzeuge anwenden (eingebrannten Text auf Pixeln, Named-Entity-Bereinigung von Berichtstext, standardisierte Studien- und Seriennamen, Face blur) und die de-identifizierten Studien dann an ein anderes System oder Cloud-Archiv senden.

## Datenschutzziel

Patientennamen, IDs und andere Kennungen in den Datei-„Etiketten“ (DICOM-Tags) werden beim **Import** durch das De-Identifikations-Skript des Projekts ersetzt oder entfernt. Daten werden so verschoben, dass der zeitliche Ablauf innerhalb eines Patienten konsistent bleibt, aber nicht dem Kalenderdatum entspricht.

Dieser Tag-Lauf bereinigt **keinen** Freitext in Structured Reports oder Encapsulated PDFs und löscht keine auf Pixel gezeichneten Namen. Wenn Sie Berichtsobjekte behalten (Clean Structured Content), müssen Sie nach dem Import die **Berichtstext-Prüfung** ausführen: englische Named Entity Recognition (NER) findet Namen, Daten, IDs, Telefonnummern und ähnliche Spannen im Berichtskörper, damit Sie sie leeren oder durch synthetische Werte ersetzen können. Zusätzlich können optionale KI-Werkzeuge eingebrannten Pixeltext verbergen und Gesichter bei Kopfuntersuchungen unscharf machen — weil diese auch nach bereinigten Etiketten noch identifizieren können.

## Standards und Tests

Das Standardskript folgt dem DICOM **Basic Application Confidentiality Profile** ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html)) und den Retain-Optionen, die Sie für das Projekt wählen. Dieses Profil und der öffentliche TCIA-/NCI-**Medical Image De-Identification Benchmark (MIDI-B)** sind an die **HIPAA-Safe-Harbor-ähnliche** Entfernung von Bildgebungs-Kennungen angelehnt (kein Anspruch, das Produkt sei „HIPAA-zertifiziert“). Die Header-De-Identifikation wird mit dem offiziellen MIDI-B-Scorer geprüft (siehe [De-Identifikationsprotokoll](../deidentification-protocol.md)). Die formale Checkliste nach PS 3.15 § E.1.3 steht in der [DICOM-Konformitätserklärung](../dicom-conformance-statement.md). Ihr Datenschutzbeauftragter sollte Optionen und jedes benutzerdefinierte Skript für Ihren Standort trotzdem prüfen — dieses Handbuch ist betriebliche Anleitung, kein Compliance-Zertifikat.

## Für wen

- Radiologen und Bildgebungsforscher, die Datensätze kuratieren
- Standorte, die Studien an Forschungsarchive übermitteln

## Zwei Arbeitsweisen


| Modus | Am besten geeignet für |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Desktop-Fenster (GUI)** | Projekte anlegen, Bilder prüfen, KI-Werkzeuge, Export |
| **Ohne Fenster (headless)** | Labor/Server: Bilder weiter empfangen oder KI-Stapel über Nacht — siehe [Ohne Oberfläche ausführen](../10-headless/index.md) |


!!! important "Projekt zuerst im Fenster anlegen"
    Der Headless-Modus nutzt ein bereits angelegtes und konfiguriertes Projekt. Beginnen Sie mit [Projekt anlegen](../05-create-project/index.md) und lassen Sie die IT bei Bedarf headless starten.

## Nächste Schritte

1. [Installation und erster Start](../02-install/index.md)
2. [KI-Funktionen einrichten](../03-ai-features-setup/index.md) (vom Willkommen-Bildschirm)
3. [Begriffe](../04-words-we-use/index.md)
4. [Projekt anlegen](../05-create-project/index.md)
