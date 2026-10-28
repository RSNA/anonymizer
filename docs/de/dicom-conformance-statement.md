# DICOM-Konformitätserklärung

Diese Seite ist die Antwort des Produkts auf die [DICOM-PS-3.15-§-E.1.3-Konformitätsanforderungen](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/sect_E.1.3.html) für Anwendungen, die das **Basic Application Level Confidentiality Profile** beanspruchen.

Sie richtet sich an Datenschutzbeauftragte und Prüfer. Der betriebliche Alltag steht im [De-Identifikationsprotokoll](deidentification-protocol.md) und unter [Projekt anlegen](05-create-project/index.md#2-de-identification-options).

!!! note "Umfang dieses Anspruchs"
    Konformität bedeutet hier: der **Importpfad** setzt das Basic Profile (und gewählte Optionen aus Anhang E) um, indem das Projekt-Anonymizer-Skript auf DICOM-Attribute angewendet wird. Optionale Pixel-, Berichts-, Deskriptor- und Gesichtsreinigung laufen **nach** dem Import, wenn diese Optionen und KI-Funktionen aktiviert sind. Diese Erklärung ist keine Rechtsberatung und keine HIPAA-Produktzertifizierung — siehe [HIPAA Safe Harbor und MIDI-B](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b).

## Beanspruchte Profile und Optionen

| Punkt | Anspruch |
| --- | --- |
| Profil | **Basic Application Level Confidentiality Profile** (CID-7050-Code 113100) |
| Attributkatalog | [PS 3.15 Table E.1-1](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) — gepackter Extrakt `e1_1_retain_tags.json` steuert Retain-Option-Overlays beim Kompilieren |
| Methodenstempel | `(0012,0062) Patient Identity Removed = YES`; `(0012,0063) Deidentification Method = RSNA DICOM ANONYMIZER`; gewählte Optionscodes in `(0012,0064) Deidentification Method Code Sequence` |
| Maßgebliche Projektregeln | Kompiliertes `{site_id}-anonymizer.script` neben `ProjectModel.json` (aus gepacktem `default-anonymizer.script` plus Option-Overlays oder importiertem Custom-Skript) |

## E.1.3-Checkliste

### Welche Attribute werden während des Schutzes entfernt

Unter dem **Basic Profile** beim Import (gepacktes Standardskript, sofern keine Retain-Option oder Custom-Bearbeitung sie behält):

- **Alle Private Tags** (außer bei **Retain Safe Private** — dann wird jedes private Element über die TCIA-Private-Tag-Wissensbasis aufgelöst; unbekannte Slots werden entfernt).
- **Curve- und Overlay-Gruppen**.
- Attribute, die Table E.1-1 unter Basic zum Entfernen oder Leeren vorsieht und die das Projektskript mit `@remove()`, `@empty()` oder gleichwertig umsetzt (Geburtsdatum, Arztnamen, Institutionsidentität, Geräteidentität, Patientenmerkmale und viele klinische Workflow-Kennungen).
- **Encrypted Attributes** und verwandte Verschlüsselungs-Tags (`Encrypted Attributes Sequence`, `Encrypted Content`, `Encrypted Content Transfer Syntax UID` und verwandte Signatur-/Verschlüsselungselemente der Gruppe 0400) — **entfernt**, nicht befüllt.
- Digitale Signatur-UIDs und verwandte Signaturelemente — **entfernt**.

Die **vollständige** Entfernen/Behalten/Transformieren-Liste eines Projekts ist das kompilierte Anonymizer-Skript (Anonymizer Script Editor). Retain-Optionen ändern Overlays wie unter [De-Identifikationsoptionen](05-create-project/index.md#2-de-identification-options). Custom-Skriptedits überschreiben das Compile für diese Tags, bis Optionen erneut akzeptiert werden (dann Neu-Compile vom gepackten Default und **Verlust** der Custom-Edits).

### Welche Attribute durch Dummy-Werte ersetzt werden und wie diese erzeugt werden

| Attributklasse | Erzeugung der Ersatzwerte |
| --- | --- |
| **Patient Name / Patient ID** | Standort-ID plus fortlaufende Patientennummer, die für dieselbe Person **in diesem Projekt** gleich bleibt (Lookup in der privaten Projektdatenbank). |
| **Accession Number** | Deterministischer Hash aus Projekt-Mixer (`site_id` / `uid_root`) plus Original-Accession. |
| **DICOM-UIDs** (Study, Series, SOP Instance, Frame of Reference und andere Skriptregeln mit `@uid`) | Projektpräfix (`uid_root` + Site-ID) + gekürzte MD5 der Original-UID — gleiches Original → gleicher Ersatz **innerhalb des Projekts**. |
| **Daten / DateTimes** (Datumsdelta-Operanden) | Pro-Patient- oder Trial-Strategie: Standard `@hashdate`; oder `@lookup`, `@incrementdate`, `@rebasedate` wenn konfiguriert. Tageszeit typischerweise unverändert. Siehe [Daten](deidentification-protocol.md#daten). |
| **Patient Age** | Auf Fünfjahresband gerundet (`@round`), auch bei **Retain Patient Characteristics**. |
| **Andere Basic-Leerungen** | `@empty()` oder feste Literale laut Skript. |

Details und Sicherheitshinweise: [Deterministische Ersetzungen](deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

**Retain UIDs** behält Original-UIDs statt `@uid`. **Full Dates** behält Original-Kalenderdaten statt Verschiebung.

### Encrypted Attributes Data Sets (Re-Identifikation)

**Nicht unterstützt.** Der Anonymizer legt Originale **nicht** in ein Encrypted Attributes Data Set zur späteren Re-Identifikation und wählt **keine** Verschlüsselungsschlüssel dafür.

- Das Standardskript **entfernt** Encrypted Attributes Sequence / Encrypted Content / verwandte Gruppe-0400-Tags, falls vorhanden.
- Die maßgebliche Original↔Anonym-Map liegt in der **privaten Projektdatenbank** (nicht in freigegebenen DICOM-Objekten) — diese Datenbank darf nicht in Export-/Send-Pakete.

### Umfang der referenziellen Integrität der Ersatzwerte

| Umfang | Verhalten |
| --- | --- |
| **Innerhalb eines Projekts** | Gleiche Original-Patient-ID, Accession oder UID → gleicher anonymisierter Wert für jede SOP Instance in diesem Projekt (stabile Verknüpfung über Studien, Serien und Instanzen). |
| **Frame of Reference und verwandte UIDs** | Skript-`@uid`-Regeln konsistent remapped, wenn Retain UIDs aus ist. Manche RT-/Referenzsequenzen werden unter Basic entfernt statt remapped — siehe Projektskript. |
| **Erneute Verarbeitung derselben Studie** | Re-Import in dasselbe Projekt nutzt gespeicherte PHI/UID-Zuordnungen bei passenden Originalen. Neu-Compile der Optionen schreibt bereits gespeicherte Dateien **nicht** um. |
| **Über Projekte hinweg** | **Nicht** garantiert. |
| **Über Standorte nur mit freigegebenem DICOM** | Ersatz-UIDs/Accessions sind **geheimnislose** Konstruktionen; siehe Deterministik-Hinweise. |

### Welche Attribute und Werte während des Schutzes eingefügt werden

Bei erfolgreichem Import-Schutz stellt das Produkt mindestens sicher:

| Tag | Wert / Verhalten |
| --- | --- |
| `(0012,0062) Patient Identity Removed` | `YES` (per `@always()` erzeugt, falls fehlend) |
| `(0012,0063) Deidentification Method` | `RSNA DICOM ANONYMIZER` |
| `(0012,0064) Deidentification Method Code Sequence` | Ein DCM-Item pro **ausgeführtem** Optionscode (Import-Optionen beim Import; Clean-/Gesichtsoptionen bei späteren Tasks) |
| `(0028,0303) Longitudinal Temporal Information Modified` | `MODIFIED` bei Datumsdelta-Strategie |
| `(0012,0052)` / `(0012,0053)` (Rebase-Pfad) | Offset From Event und Event Type `REGISTRATION` bei `@rebasedate` / Registrierungs-Rebase |

Skript-`@always()…` kann fehlende Nicht-Sequenz-Elemente mit festem Literal **anlegen**.

### Transfer Syntaxes für Encrypted Attributes Data Set

**Nicht zutreffend.** Es werden keine Encrypted Attributes Data Sets erzeugt.

### Welche Optionen unterstützt werden

| Option (CID 7050) | Unterstützt? | Wann |
| --- | --- | --- |
| Basic Application Confidentiality Profile (113100) | **Ja** (immer) | Import |
| Clean Pixel Data (113101) | **Ja** | Nach Import — Embedded PHI (Modelle nötig) |
| Clean Recognizable Visual Features (113102) | **Ja** | Nach Import — Gesichter unscharf (Modelle nötig) |
| Clean Graphics (113103) | **Nur wählbar** | Nur Absicht — siehe Hinweis unten |
| Clean Structured Content (113104) | **Ja** | Nach Import — Report Text Review / AI Batch (Modelle nötig) |
| Clean Descriptors (113105) | **Ja** | Nach Import — Metadaten-Text (Modelle nötig) |
| Retain Longitudinal Temporal Information Full Dates (113106) | **Ja** | Import (exklusiv zu Modified Dates) |
| Retain Longitudinal Temporal Information Modified Dates (113107) | **Ja** | Import (Retain-Preset) |
| Retain Patient Characteristics (113108) | **Ja** | Import |
| Retain Device Identity (113109) | **Ja** | Import |
| Retain UIDs (113110) | **Ja** | Import |
| Retain Safe Private (113111) | **Ja** | Import (TCIA-KB) |
| Retain Institution Identity (113112) | **Ja** | Import |

Presets und UI: [Projekt anlegen — De-Identifikationsoptionen](05-create-project/index.md#2-de-identification-options). Bedeutungen: [De-Identifikationsprotokoll](deidentification-protocol.md).

### Warum Clean Graphics nicht ausgeführt wird {#why-clean-graphics-is-not-executed}

Die DICOM-Option **Clean Graphics** zielt auf **nicht-textuelle** eingebrannte Grafiken in Pixeln (Logos, Lineale, Dekoration) jenseits gewöhnlicher Curve-/Overlay-Gruppen. Unter dem Basic Profile entfernt dieses Produkt Curve- und Overlay-Gruppen bereits beim Import. Verbleibende nicht-textuelle eingebrannte Grafiken sind in modernen klinischen Forschungsarchiven unüblich (die meiste verbleibende Pixel-PHI ist **Text**, behandelt durch Clean Pixel Data / Embedded PHI). Ein eigener Detektor/Scrubber für diesen Legacy-Randfall wurde nicht priorisiert; die Auswahl von Clean Graphics speichert nur die Projektabsicht und startet **keinen** Verarbeitungs-Task und stempelt **nicht**.

### Zusätzliche Einschränkungen

- **Kein Encrypted-Attributes- / Public-Key-Re-Identifikationspfad** — keine Schlüsselgrößen oder Cipher Suites.
- **Clean\*-Optionen** brauchen installierte KI-Funktionen.
- **Custom-CTP-Skripte** können importiert werden; unbekannte Operanden werden abgelehnt; Datumsregeln müssen Study Date entsprechen.
- **Erneutes Akzeptieren von Optionen** kompiliert neu und **verwirft** Custom-Skriptedits; bereits importierte Instanzen werden nicht neu anonymisiert.
- **MIDI-B**-Scores sind Nachweis für Header-Prüfung, kein Ersatz für die institutionelle Feststellung ([Protokoll](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b)).

!!! note "Für Compliance-Prüfung"
    Lassen Sie Ihren Datenschutzbeauftragten diese Erklärung zusammen mit den [De-Identifikationsoptionen](05-create-project/index.md#2-de-identification-options), dem kompilierten Skript und etwaigen [benutzerdefinierten Skriptbearbeitungen](05-create-project/anonymizer-script.md#4-custom-script-edits) prüfen. Dieses Handbuch ist betriebliche und Normen-Dokumentation, keine Rechtsberatung.
