# Hier beginnen

## Was dieses Programm tut

Der RSNA DICOM Anonymizer ist eine eigenständige Anwendung, die **geschützte Identitätsinformationen** aus medizinischen Bildgebungsstudien entfernt und eine forschungssichere Kopie auf Ihrem Computer speichert.

Sie können Bilder aus einem Ordner oder aus einem klinischen Bildgebungssystem übernehmen, prüfen, optional KI-Werkzeuge anwenden (Entfernung eingebrannten Texts, standardisierte Studien- und Seriennamen, Face blur) und die de-identifizierten Studien dann an ein anderes System oder Cloud-Archiv senden.

## Datenschutzziel

Patientennamen, IDs und andere Kennungen in den Datei-„Etiketten“ (DICOM-Tags) werden ersetzt oder entfernt. Daten werden so verschoben, dass der zeitliche Ablauf innerhalb eines Patienten konsistent bleibt, aber nicht dem Kalenderdatum entspricht. Optionale KI-Werkzeuge können auch Text verbergen, der auf das Bild selbst gezeichnet ist, und Gesichtszüge bei Kopfuntersuchungen unscharf machen — weil diese auch nach bereinigten Etiketten noch identifizieren können.

## Für wen

- Radiologen und Bildgebungsforscher, die Datensätze kuratieren
- Standorte, die Studien an Forschungsarchive übermitteln

## Zwei Arbeitsweisen


| Modus | Am besten geeignet für |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Desktop-Fenster (GUI)** | Projekte anlegen, Bilder prüfen, KI-Werkzeuge, Export |
| **Ohne Fenster (headless)** | Labor/Server: Bilder weiter empfangen oder KI-Stapel über Nacht — siehe [Ohne Oberfläche ausführen](../10-headless/) |


!!! important "Projekt zuerst im Fenster anlegen"
    Der Headless-Modus nutzt ein bereits angelegtes und konfiguriertes Projekt. Beginnen Sie mit [Projekt anlegen](../05-create-project/) und lassen Sie die IT bei Bedarf headless starten.

## Nächste Schritte

1. [Installation und erster Start](../02-install/)
2. [KI-Funktionen einrichten](../03-ai-features-setup/) (vom Willkommen-Bildschirm)
3. [Begriffe](../04-words-we-use/)
4. [Projekt anlegen](../05-create-project/)
