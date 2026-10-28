# Projekt anlegen

Ein **Projekt** hält Einstellungen und anonymisierten Speicher zusammen. Legen Sie es einmal im Desktop-Fenster an, auch wenn ein Server später [ohne Oberfläche](../10-headless/index.md) laufen soll.

Auf dem **Willkommen**-Bildschirm **Datei → Neues Projekt** wählen, dann die **Neuen Projekteinstellungen** **von oben nach unten** durchgehen (gleiche Reihenfolge wie im Dialog).

## Ziel

Ein Projekt mit Standort-Identität, Netzwerkservern, Speicher (Verzeichnis und welche Studien angenommen werden), De-Identifikationsoptionen und Protokollierung — abgestimmt mit der IT.

## 1. Projektidentität

Auf Willkommen **Datei → Neues Projekt** wählen.

![Datei → Neues Projekt auf Willkommen](shots/macos/NewProject_Menu.png)

In den **Neuen Projekteinstellungen**:

- **Projektnamen** setzen (kurz, unter 16 Zeichen).
- **Standort-ID** prüfen — wird automatisch aus der Uhrzeit gebildet (kurze Zahl aus 30-Minuten-Intervallen seit 1970), damit jedes neue Projekt einen eigenen Standortcode erhält; hier nicht editierbar. Mit **JAVA-Indexdatei laden** wird die Standort-ID stattdessen aus dem Index übernommen.
- **UID-Wurzel** prüfen — die feste RSNA-Basis zum Erzeugen neuer anonymisierter DICOM-UIDs. Für einen neuen Standort den Standard belassen. Mit **JAVA-Indexdatei laden** wird die UID-Wurzel aus den anonymisierten Study-UIDs in dieser Datei extrahiert (zusammen mit der Standort-ID), damit Sie denselben Standort fortsetzen.

## 2. Projekteinstellungen

**Neue Projekteinstellungen** ist der Dialog unten. Konfigurieren Sie ihn von oben nach unten; die nummerierten Abschnitte danach folgen diesem Layout.

![Neue Projekteinstellungen](shots/macos/NewProjectSettings.png)

## 3. Netzwerkserver {#3-network-and-modalities}

### Wenn Sie mit der IT sprechen {#when-you-talk-to-it}

Teilen Sie diese Ideen (Details stehen in den Dialogfenstern unten):

- **Lokaler Server** — Adresse, Port und AE Title, mit denen dieser Computer Bilder **empfängt**.
- **DICOM-Bildarchiv (Query/Retrieve-Server)** — das Krankenhausarchiv, in dem Sie suchen und abrufen.
- **Export-Server** oder **AWS** — wohin anonymisierte Studien gesendet werden.
- **Netzwerk-Zeitüberschreitungen** — wie lange auf langsame Archive gewartet wird.

Wenn das Projekt auf einem Laborserver laufen soll, weiter mit [Ohne Oberfläche](../10-headless/index.md).

### Lokaler Server

Adresse, Port und AE Title, mit denen dieser Computer Bilder **empfängt**.

![Lokaler Server](shots/macos/LocalServer.png)

### DICOM-Bildarchiv (Query/Retrieve-Server)

Krankenhausarchiv für Abfrage / Abruf.

![Query Server](shots/macos/QueryServer.png)

Für entfernte Systeme mit **DICOMweb** öffnen Sie den Query-Server-Dialog und aktivieren **DICOMweb**. Tragen Sie **HTTP-Port**, **Pfad** (z. B. `/dicom-web`), optional **Use HTTPS** sowie optional Benutzername/Passwort ein. Abfrage nutzt dann QIDO-RS, Abruf WADO-RS. DIMSE-Port und AE Title bleiben für **Echo** und Dual-Stack-Server. Echo verwendet weiterhin DIMSE.

### Export-Server

DICOM-Ziel beim **Senden** (die Einstellung kann weiterhin Export Server heißen).

![Export-Server](shots/macos/ExportServer.png)

Ist am Export-Server **DICOMweb** aktiv, nutzt Senden STOW-RS statt C-STORE.

### AWS Cognito (optional)

Anmeldedaten für S3-Senden, wenn aktiviert.

![AWS Cognito](shots/macos/AWSCognito.png)

### Netzwerk-Zeitüberschreitungen {#network-timeouts}

Wie lange auf langsame Archive gewartet wird.

![Netzwerk-Zeitüberschreitungen](shots/macos/NetworkTimeouts.png)

## 4. Speicher {#storage-classes}

### Speicherverzeichnis

Wählen Sie das **Speicherverzeichnis**, in dem die anonymisierten Dateien dieses Projekts liegen (standardmäßig folgt es dem Projektnamen unter Dokumente / RSNA Anonymizer).

### Modalitäten / Speicherklassen / Transfersyntaxen

Diese drei Einstellungen bestimmen, welche Studien dieses Projekt bei der Suche in einem entfernten Archiv, beim Netzwerkempfang oder beim Einlesen von Dateien vom Datenträger annimmt.

**Modalitäten** — Untersuchungsarten wie CT, MR oder US. Eine Änderung der Modalitäten füllt die **Speicherklassen** zunächst passend.

![Modalitäten](shots/macos/Modalities.png)

**Speicherklassen** — die DICOM-Objektarten, die der Anonymizer **annimmt** (z. B. CT Image Storage). Die Liste wird **zunächst aus den gewählten Modalitäten** gesetzt, kann danach aber bearbeitet werden (Klassen hinzufügen oder entfernen). Dateien, deren Speicherklasse nicht auf dieser Liste steht, werden nicht in das Projekt anonymisiert — sie landen in Quarantäne.

![Speicherklassen](shots/macos/StorageClasses.png)

**Transfersyntaxen** — wie Pixeldaten beim Empfang oder Speichern kodiert sind:

- **Unkomprimierte** Kodierungen behalten jeden Abtastwert. Dateien sind größer auf dem Datenträger.
- **Komprimierte** Kodierungen (JPEG, JPEG 2000 und ähnliche) verkleinern Dateien; dieselbe Studie braucht weniger Speicherplatz.

Das Projekt behält jede Datei in der Transfersyntax, die sie bereits hat. **Umkodierung** von einer Transfersyntax in eine andere ist derzeit **nicht aktiviert** — wählen Sie die Syntaxen, die Ihre Quellen bereits nutzen (und die Sie auf dem Datenträger behalten wollen).

![Transfersyntaxen](shots/macos/TransferSyntaxes.png)

## 5. De-Identifikationsoptionen {#2-de-identification-options}

Öffnen Sie **De-Identifikationsoptionen**. De-Identifikationsoptionen sind die DICOM-Vertraulichkeitsentscheidungen aus [PS 3.15 Anhang E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) (Basic Profile, Modified Dates, Retain Safe Private und verwandte Optionen). Sie erscheinen unter ihren Standardnamen unter **De-identification Options**.

![De-Identifikationsoptionen](shots/macos/DeidentificationOptions.png)

### Voreinstellungen

| Voreinstellung | Was ausgewählt wird |
| --- | --- |
| **Basic** | Nur Basic Profile |
| **Retain** | Basic Profile + Modified Dates + Patient Characteristics + Retain Safe Private |

Voreinstellungen füllen nur die Kontrollkästchen. Das Projekt speichert die **ausgewählten Optionscodes**, nicht den Namen der Voreinstellung.

### Wie Optionen das Anonymizer-Skript erzeugen

Beim Anlegen (und immer wenn Sie bei einem bestehenden Projekt neue Optionen **Übernehmen**), **kompiliert** die App das Projekt-Anonymizer-Skript:

- Ausgangspunkt ist das mitgelieferte `default-anonymizer.script`.
- **Options-Overlays** für jede gewählte Vertraulichkeitsoption (welche Tags behalten, entfernt oder umgewandelt werden).
- Ergebnis als projekt-private `{site_id}-anonymizer.script` neben `ProjectModel.json`.

Das Projekt verwendet **nur dieses Skript** für die Tag-Anonymisierung (nicht NER/OCR). Vollständige Regelsprache und Stempel-Tags stehen im [De-Identifikationsprotokoll](../deidentification-protocol.md). Prüfer mit der Checkliste PS 3.15 § E.1.3 nutzen die [DICOM-Konformitätserklärung](../dicom-conformance-statement.md).

!!! warning "Optionen nach dem Anlegen ändern"
    Beim Anwenden anderer Optionen fragt die App zur Bestätigung. **Übernehmen** **kompiliert** neu aus dem mitgelieferten Standard plus Overlays — **benutzerdefinierte Skriptbearbeitungen gehen verloren**. Bereits im Projekt gespeicherte Dateien werden nicht erneut verarbeitet.

### Bereinigungsoptionen und Modalitäten

Bereinigungsoptionen (Clean Pixel Data, Clean Structured Content, Clean Descriptors, Clean Recognizable Visual Features) lassen sich nur wählen, wenn die zugehörige KI-Funktion installiert ist — Sie werden zum Modell-Download aufgefordert. Die Auswahl von Clean Structured Content oder Clean Descriptors aktiviert SR/PDF-Modalitäten; neu aktivierte SR- oder PDF-Modalitäten schalten Clean Structured Content ein, wenn es aus war.

Pixel-, Berichts- und Gesichtsreinigung nutzen weiterhin die optionalen [Verarbeiten](../08-process/index.md)-Werkzeuge, wenn solche Objekte vorliegen. Siehe [De-Identifikationsprotokoll](../deidentification-protocol.md#pixel-and-face-options-in-the-dicom-profile).

Die meisten Standorte bearbeiten das kompilierte Skript nie von Hand. Erweiterte Tag-Regeln, Datumsstrategien und Patienten-Nachschlagetabellen: [Anonymizer-Skript (erweitert)](anonymizer-script.md).

## 6. Protokollierung


Anonymizer- / Netzwerkprotokollierung erhöhen, wenn Sie mit der IT Fehler beheben.

![Protokollierungsstufen](shots/macos/LoggingLevels.png)

## Projekt anlegen

Wenn die Einstellungen vollständig sind, wählen Sie **Projekt anlegen**. Das kompilierte Anonymizer-Skript liegt neben `ProjectModel.json` als `{site_id}-anonymizer.script`. Das **Dashboard** öffnet sich.

![Dashboard](shots/macos/Dashboard.png)

## Nach dem Anlegen

| Aktion | So |
| --- | --- |
| Schließen | **Datei → Projekt schließen** oder Fenster schließen |
| Einstellungen klonen | **Datei → Projekt klonen** in einen neuen Speicherordner (keine Bilder werden kopiert). Halten Sie die UID-Wurzel projektübergreifend eindeutig. |

## So sieht es aus, wenn es passt

- Das Dashboard zeigt Projektname und Standort-ID.
- Das Speicherverzeichnis existiert und ist beschreibbar.
- De-Identifikationsoptionen passen zu Ihrem Datenschutzplan; `{site_id}-anonymizer.script` liegt neben `ProjectModel.json`.
- Netzwerk- und Modalitätsdialoge entsprechen dem, was die IT für diesen Standort erwartet.

## Wenn es fehlschlägt

- Speicherpfad nicht beschreibbar → anderen Ordner wählen.
- Name zu lang → Projektnamen kürzen.
- Warnung beim Klonen zur UID-Wurzel → pro Projekt eine eindeutige Wurzel verwenden, um ID-Kollisionen zu vermeiden.

## Nächste Schritte

Weiter mit [Suchen](../06-search/index.md).
