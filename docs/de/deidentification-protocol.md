# De-Identifizierungsprotokoll

Diese Seite fasst in einfacher Sprache zusammen, wie der Anonymizer dem DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)) folgt. Die formale Antwort nach § E.1.3 für Prüfer ist die [DICOM-Konformitätserklärung](dicom-conformance-statement.md).

## HIPAA Safe Harbor und MIDI-B {#hipaa-safe-harbor-and-midi-b}

US-Standorte fragen oft nach **HIPAA Safe Harbor**. Das ist eine **De-Identifikationsmethode** unter der Privacy Rule (genannte Kennungskategorien entfernen, ohne tatsächliches Wissen um Re-Identifikation)—keine Produktzertifizierung durch HHS. Der Anonymizer beansprucht **nicht**, als Software „HIPAA-zertifiziert“ oder „Safe-Harbor-konform“ zu sein.

Was wir *doch* beanspruchen:

- Der Standard-Importpfad setzt die DICOM-PS-3.15-Vertraulichkeitsoptionen um (Basic Profile und die von Ihnen gewählten Retain-Optionen).
- Diese Optionen und der öffentliche **MIDI-B**-Antwortschlüssel / offizielle Scorer in den Tests sind auf **Safe-Harbor-ähnliche** Entfernung von Bildgebungs-Kennungen plus TCIA-artige Forschungs-Metadatenpraxis ausgelegt.
- Die Standard-**Datumsverschiebung** erhält longitudinale Abstände (Modified Dates). Das ist **nicht** dasselbe wie die Safe-Harbor-Regel „nur Jahr“. Standorte, die nur Jahr (oder Expert Determination) brauchen, müssen die Richtlinie mit dem Datenschutzbeauftragten festlegen.
- Pixel-Text, Berichtstext und Gesichter brauchen weiterhin die optionalen KI- / Report-Text-Review-Schritte, wenn solche Objekte vorliegen.

Nutzen Sie MIDI-B-Scores und dieses Protokoll als **Nachweis für die Prüfung**, nicht als Ersatz für die institutionelle Feststellung.

## Was entfernt oder ersetzt wird

- Patientenname und ID werden zu projektspezifischen anonymisierten Werten (Standort-ID + fortlaufende Patientennummer). Dieselbe Person behält dieselbe anonymisierte ID über Studien im Projekt.
- UIDs werden durch deterministische, projektbezogene Werte ersetzt, damit Verknüpfungen zwischen Bildern konsistent bleiben. Diese Hashes sind **geheimnislos** (stabile Projektverknüpfung, keine schlüsselbasierte Pseudonymisierung) — siehe [Deterministische Ersetzungen](#deterministic-replacements-uids-dates-accessions).
- Viele klinische Workflow- und Private Tags werden entfernt.
- Die Datei vermerkt, dass die Patientenidentität entfernt wurde, und nennt den RSNA DICOM Anonymizer als Methode.

## Daten

Daten werden pro Patient verschoben (hash-basierter Versatz), sodass **Reihenfolge und Abstände** der Studien eines Patienten aussagekräftig bleiben, Kalenderdaten aber nicht die Originale sind. Tageszeiten bleiben typischerweise unverändert.

## Was behalten werden kann (Teiloptionen)

Beispiele für behaltenen klinischen Kontext (je nach Skript- / Profiloptionen):

- Studien- und Serienbeschreibungen (Seriennamen können Sie später mit Harmonisieren standardisieren)
- Geschlecht, Alter, Größe, Gewicht und ähnliche Merkmale, wenn konfiguriert
- Hersteller / Modell, wenn konfiguriert

## Deterministische Ersetzungen (UIDs, Daten, Accessions) {#deterministic-replacements-uids-dates-accessions}

Diese Transformationen sind **absichtlich** und **geheimnislos**. Ihre Aufgabe ist **stabile Verknüpfung innerhalb eines Projekts** (und eine passende Zeile in den PHI-/UID-Tabellen des Projekts) — keine schlüsselbasierte Unverkettbarkeit gegenüber jemandem, der bereits einen Kandidaten für den Originalwert kennt.

| Wert | Ableitung | Bedeutung |
| --- | --- | --- |
| **DICOM-UIDs** | Projektpräfix (`uid_root` + Site-ID) + gekürztes MD5 der Original-UID | Gleiches Original → gleiche Anon-UID. Wer ein Original **raten** kann, kann den Ersatz berechnen und vergleichen. Eine Anon-UID lässt sich aus der anonymisierten Datei allein nicht sinnvoll zum unbekannten Original **umkehren**. |
| **Daten (`@hashdate`)** | Tagesversatz aus MD5 der Patienten-ID (mod ~10 Jahre) | Gleicher Patient → gleicher Versatz; Intervalle zwischen den Studien dieses Patienten bleiben aussagekräftig. |
| **Accession-Nummer** | SHA-256 eines **Projekt-Mixers** (`site_id` / `uid_root`) plus Original-Accession | Unterschiedliche Projekte erzeugen unterschiedliche Hashes für dieselbe Accession (nützlich). Der Mixer ist **kein** Geheimschlüssel: Site-ID und UID-Root erscheinen in freigegebenen anonymisierten UIDs, sodass jemand mit freigegebenen Daten ihn neu aufbauen und geratene Accessions prüfen kann. |

**Nicht beansprucht:** kryptografische Resistenz gegen Online-Verifikation, wenn der Angreifer bereits eine plausible Original-UID, Patienten-ID oder Accession hat. Das ist bei öffentlichen, deterministischen Konstruktionen erwartet und unter offenen DICOM-De-Identifiern üblich.

**Doch beansprucht:** Originale stehen nicht in den freigegebenen DICOM-Daten; die maßgebliche Zuordnung liegt in der privaten Projektdatenbank — halten Sie diese Datenbank aus Export-/Sende-Paketen heraus.

## Pixel- und Gesichtsoptionen im DICOM-Profil {#pixel-and-face-options-in-the-dicom-profile}

Die klassischen Profiloptionen „clean pixel data“ und „clean recognizable visual features“ werden **nicht** allein als automatische DICOM-Profilbits beansprucht. In V19 nutzen Sie stattdessen optionale KI-Funktionen:

- [Eingebrannten Text entfernen](08-process/02-remove-burned-in-text/index.md)
- [Gesichter unscharf machen](08-process/04-blur-faces/index.md)

## Structured Reports und Overlays

Curve-/Overlay-Gruppen werden entfernt. Ob Structured-Report-Objekte akzeptiert werden, steuern die Speicherklassen-Einstellungen des Projekts.

!!! note "Für Compliance-Prüfung"
    Lassen Sie Ihren Datenschutzbeauftragten die [De-Identifikationsoptionen](05-create-project/index.md#2-de-identification-options) und etwaige [benutzerdefinierte Skriptbearbeitungen](05-create-project/anonymizer-script.md#4-custom-script-edits) sowie die KI-Werkzeuge für Ihre Institution prüfen. Siehe auch die [DICOM-Konformitätserklärung](dicom-conformance-statement.md) und [HIPAA Safe Harbor und MIDI-B](#hipaa-safe-harbor-and-midi-b). Dieses Handbuch ist betriebliche Anleitung, keine Rechtsberatung.
