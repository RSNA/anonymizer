# Anonymizer-Skript (erweitert)

[De-Identifikationsoptionen](index.md#2-de-identification-options) kompilieren das Projektskript für die meisten Standorte. Nutzen Sie diese Seite, um einzelne Tag-Regeln zu ändern, eine Datumsstrategie zu wählen, eine Patienten-Nachschlagetabelle zu laden oder ein CTP-`.script` zu importieren.

## Editor öffnen

Nach dem Anlegen des Projekts: **Ablage → Projekteinstellungen → Anonymizer-Skript bearbeiten**.

Der Editor lädt `{site_id}-anonymizer.script` neben `ProjectModel.json` im Projektspeicherordner (der Ordner oben im **Dashboard**). Die Dialogzeile **Skript** ist der Pfad dieser Skriptdatei. Das mitgelieferte `default-anonymizer.script` wird nie überschrieben.

Kopfzeilenstatus: Options-Zusammenfassung (**Basic**, **Retain** oder abgekürzt gewählte Optionen). **Custom** bedeutet, dass das live Skript nicht mehr einer frischen Kompilierung der gespeicherten Optionen entspricht.

![Anonymizer-Skript-Editor](shots/macos/AnonymizerScriptEditor.png)

## Ansichten

| Ansicht | Inhalt |
| --- | --- |
| **Aktiv** (Standard) | Regeln, die den Wert behalten oder umwandeln (nicht `@remove()`). |
| **Entfernt** | Regeln mit Operation `@remove()`. |
| **Alle** | Jede Regel im Skript. |

**Suche** und der Werkzeugleisten-Filter **Operand** gelten innerhalb der aktuellen Ansicht.

## Regel ändern {#4-custom-script-edits}

1. Zeile auswählen.
2. Operanden mit dem Werkzeugleisten-Filter **Operand** oder der Detailsteuerung **Operand** prüfen — **So funktioniert dieser Operand** aktualisiert sich sofort; die Regel ändert sich erst mit **Anwenden**.
3. Braucht der Operand einen Parameter, fordert **Anwenden** ihn an (siehe [Operanden](#operands)). **Parameter ändern** bearbeitet den Parameter an einer Regel, die den Operanden bereits nutzt.
4. **@remove()** dann **Anwenden** entfernt das Tag aus **Aktiv** (die Regel bleibt im Skript).

## Operandenkatalog {#operands}

Unterstützte Operationen entsprechen dem Katalog des Skript-Editors und dem Ingest-Walk. Parameter werden bei Bedarf bei **Anwenden** abgefragt. Datums-Delta-Operationen auf Datumsfeldern müssen dieselbe Operation wie **StudyDate** nutzen (Ein-Klick-Angleichung im Editor).

| Operand (Skripttext) | Parameter | Verhalten |
| --- | --- | --- |
| `@keep` | — | Wert unverändert lassen. Behaltener Freitext kann weiterhin durch Embedded PHI / Report-NER gescannt werden. |
| `@safe()` | — | Produkterweiterung (kein CTP): Wert unverändert lassen und von Embedded-PHI- / PseudoPHI-Bulk-NER ausschließen. Für beizubehaltende technische Strings ohne NER-Scrub. |
| `@remove()` | — | Tag aus dem anonymisierten Dataset löschen. |
| `@empty()` | — | Tag behalten, Wert leer setzen. |
| `@uid` | — | Durch stabile anonymisierte UID ersetzen. Gleiche Original-UID → gleiche Anon-UID im Projekt (referenzielle Integrität). |
| `@ptid` | — | Durch die anonymisierte Patienten-ID des Projekts für diesen Patienten ersetzen. |
| `@acc` | — | Durch die anonymisierte Accession-Nummer dieser Studie ersetzen, sofern zugewiesen. Leere Quelle bleibt leer. |
| `@hashdate` | — | Datum/DatumZeit um einen stabilen patientenbezogenen Tagesversatz aus der PHI-Patienten-ID verschieben. Intervalle zwischen Studien dieses Patienten bleiben erhalten. Setzt `(0028,0303) LongitudinalTemporalInformationModified = MODIFIED`, wenn ein Datums-Delta läuft (Code 113107 bei gewähltem Modified Dates). |
| `@lookup(this,ptid)` | — | Ersetzen durch die anonymisierte Patienten-ID aus der Patienten-Nachschlagetabelle (`ptid/`-Zeilen in CTP-`.properties`). Ist die Tabelle nicht geladen, öffnet **Anwenden** **Patienten-Nachschlagetabelle laden**. |
| `@lookup(this,dateoffset)` | — | Patientenbezogenen Tagesversatz aus der Nachschlagetabelle anwenden (`dateoffset/`-Zeilen). Fehlen diese Zeilen, öffnet **Anwenden** **Patienten-Nachschlagetabelle laden**. |
| `@incrementdate(this,n)` | **`n`**: vorzeichenbehafteter ganzzahliger Tagesversatz (studienweites DATEINC). Positiv verschiebt später; negativ früher. Die Bestätigung setzt dasselbe `@incrementdate(this,n)` auf jedes Datums-Delta-Feld im Skript (im Dialog aufgelistet). | Fester Tagesversatz für alle Patienten. Intervalle zwischen Studien eines Patienten bleiben erhalten. |
| `@rebasedate(this,origin)` | **`origin`**: Epochenbeginn als `YYYYMMDD` (acht Ziffern; Standard `19600101`). | TCIA/NCTN-Rebase: anonymisiertes Datum = `origin + (reales Datum − basedate)`. Erfordert `basedate/<PatientID>=YYYYMMDD` in der Nachschlagetabelle. Schreibt `(0012,0052)` / `(0012,0053)=REGISTRATION` aus PHI StudyDate − basedate. Fehlen basedates, öffnet **Anwenden** zuerst **Patienten-Nachschlagetabelle laden**. |
| `@round(this,n)` | **`n`**: Ganzzahl ≥ 1, Altersbandbreite in ganzen Jahren. Alter wird **abgerundet** auf das nächste Vielfache von `n` (VR AS). | Patient Age vergröbern. Breite `5`: `023Y` → `020Y`, `029Y` → `025Y`. |
| `@always()text` | **`text`**: nicht leerer Literalersatz (darf nicht mit `@` beginnen). Gespeichert als `@always()YES`. Bloße Literale ohne `@` (`YES`) in älteren Skripten sind derselbe Operand. | Element auf festen Wert setzen; fehlendes Element anlegen. |
| `@process()` | — | Sequenz-Wrapper (`SQ`) behalten und Skriptregeln rekursiv auf innere Items anwenden. |

Werkzeugleisten-Filter **Operand** **Alle** zeigt jede Regel der Ansicht; ein konkreter Operand filtert die Liste und aktualisiert die Hilfe, ohne bis **Anwenden** zuzuweisen.

## Fehlendes Tag hinzufügen

**Aus Wörterbuch hinzufügen** (untere Leiste) listet DICOM-Wörterbuch-Tags, die im Skript fehlen. **Hinzufügen** legt eine Regel mit Standard `@keep` an. Die Schaltfläche ist ausgeblendet, wenn das Skript das Wörterbuch bereits abdeckt.

## Speichern

| Steuerung | Wirkung |
| --- | --- |
| **Übernehmen** | Operanden prüfen; `{site_id}-anonymizer.script` im Projektspeicherordner schreiben; live Anonymisierungsregeln neu laden; Projekt auf diese Datei zeigen. |
| **Zurücksetzen** | Skriptdatei vom Datenträger neu laden; ungespeicherte Änderungen verwerfen. |
| **Abbrechen** | Schließen ohne Speichern. |

!!! note "Optionen vs. benutzerdefinierte Bearbeitung"
    Das Übernehmen neuer [De-Identifikationsoptionen](index.md#2-de-identification-options) kompiliert aus dem mitgelieferten Standard plus Overlays neu und **verwirft** benutzerdefinierte Skriptbearbeitungen. Bereits gespeicherte Instanzen werden nicht erneut anonymisiert.

## Patienten-Nachschlagetabelle und Datumsangaben {#5-patient-lookup-table-and-dates}

### Longitudinale Datumsangaben {#longitudinal-dates-tcia-style}

| Strategie | Operand | Voraussetzung |
| --- | --- | --- |
| Hash pro Patient | `@hashdate` | Standard kompiliertes Skript; keine Nachschlagetabelle. |
| Lookup-Offset pro Patient | `@lookup(this,dateoffset)` | `dateoffset/`-Zeilen in der Lookup-`.properties`. |
| Studienweiter Offset | `@incrementdate(this,n)` | Parameter `n` (DATEINC); auf alle Datums-Delta-Felder. |
| Epochen-Rebase | `@rebasedate(this,origin)` | `basedate/`-Zeilen; Parameter `origin` (`YYYYMMDD`). |

Alle vier erhalten Intervalle zwischen Studien eines Patienten und setzen Longitudinal Temporal Information Modified wie unter `@hashdate`. Deterministische UID-/Datums-/Accession-Hinweise: [De-Identifikationsprotokoll](../deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

### Patienten-Nachschlagetabelle {#patient-lookup-table}

**Patienten-Nachschlagetabelle laden** öffnen durch:

- **Anwenden** auf `@lookup(this,ptid)`, `@lookup(this,dateoffset)` oder `@rebasedate(this,origin)`, wenn die nötige Tabelle (bzw. `dateoffset`-/`basedate`-Zeilen) nicht geladen ist; oder
- **Lookup-Tabelle laden** / **Lookup-Tabelle ersetzen** neben der Detailsteuerung **Operand** an einer lookup-abhängigen Regel.

![Patienten-Nachschlagetabelle laden](shots/macos/LookupTable.png)

**Patienten-Nachschlagetabelle laden**:

1. **Durchsuchen…** zu einer CTP/TCIA-`.properties`-Datei.
2. Patienten- und Datums-Offset-Zähler sowie die gelisteten **Skriptänderungen** prüfen (`@ptid` → `@lookup(this,ptid)`, `@hashdate` → `@lookup(this,dateoffset)` und passende Datumsfelder).
3. **Übernehmen** speichert eine projekt-private Kopie der Tabelle, schreibt die Regeln um und aktiviert Runtime-Lookup. **Abbrechen** lässt das Skript unverändert.

`.properties`-Schlüssel:

```text
ptid/<PHI-Patienten-ID>=<anonymisierte-Patienten-ID>
dateoffset/<PHI-Patienten-ID>=<vorzeichenbehaftete-ganzzahlige-Tage>
basedate/<PHI-Patienten-ID>=YYYYMMDD
```

`ptid/` allein ist gültig. `dateoffset/` ermöglicht `@lookup(this,dateoffset)`. `basedate/` ermöglicht `@rebasedate(this,origin)`.

!!! note "Lookup nach gespeicherten Dateien"
    Das Laden einer Nachschlagetabelle anonymisiert bereits im Projekt gespeicherte Instanzen **nicht** erneut. Patienten, die bereits im Projekt sind, funktionieren weiter ohne Tabellenzeile. **Neue** Dateien, deren PHI-Patienten-ID fehlt, landen in Quarantäne als **Lookup_Miss** und werden nicht gespeichert.

## CTP-Skript importieren

**Import…** lädt eine benutzerdefinierte `.script`-Datei (keine Lookup-`.properties`). Unbekannte Operanden werden abgelehnt. Datumsregeln müssen zur StudyDate-Operation passen (Ein-Klick-Korrektur verfügbar). Bei **Übernehmen** bestätigen Sie, welche De-Identifikationsoptionen für dieses Skript gespeichert werden (vorausgefüllt aus seinen Regeln).

## Wenn es fehlschlägt

- **Übernehmen** abgelehnt → nicht unterstützte `@…`-Operanden in der Fehlermeldung korrigieren. Leeres `@always()` ist ungültig; nicht leeren `text` angeben. Bloße Literale ohne `@` gelten als feste Werte (`ALWAYS`).

## Siehe auch

- [Projekt anlegen](index.md) — wie Optionen `{site_id}-anonymizer.script` kompilieren
- [De-Identifikationsprotokoll](../deidentification-protocol.md)
- [DICOM-Konformitätserklärung](../dicom-conformance-statement.md)
