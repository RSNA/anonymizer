# De-Identifizierungsprotokoll

Diese Seite fasst in einfacher Sprache zusammen, wie der Anonymizer dem DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)) folgt.

## Was entfernt oder ersetzt wird

- Patientenname und ID werden zu projektspezifischen anonymisierten Werten (Standort-ID + fortlaufende Patientennummer). Dieselbe Person behält dieselbe anonymisierte ID über Studien im Projekt.
- UIDs werden durch neue, für das Projekt abgeleitete Werte ersetzt (in aktuellen Versionen aus Originalen gehasht), sodass Verknüpfungen zwischen Bildern konsistent bleiben, ohne Quell-UIDs offenzulegen.
- Viele klinische Workflow- und Private Tags werden entfernt.
- Die Datei vermerkt, dass die Patientenidentität entfernt wurde, und nennt den RSNA DICOM Anonymizer als Methode.

## Daten

Daten werden pro Patient verschoben (hash-basierter Versatz), sodass **Reihenfolge und Abstände** der Studien eines Patienten aussagekräftig bleiben, Kalenderdaten aber nicht die Originale sind. Tageszeiten bleiben typischerweise unverändert.

## Was behalten werden kann (Teiloptionen)

Beispiele für behaltenen klinischen Kontext (je nach Skript- / Profiloptionen):

- Studien- und Serienbeschreibungen (Seriennamen können Sie später mit Harmonisieren standardisieren)
- Geschlecht, Alter, Größe, Gewicht und ähnliche Merkmale, wenn konfiguriert
- Hersteller / Modell, wenn konfiguriert

## Pixel- und Gesichtsoptionen im DICOM-Profil

Die klassischen Profiloptionen „clean pixel data“ und „clean recognizable visual features“ werden **nicht** allein als automatische DICOM-Profilbits beansprucht. In V19 nutzen Sie stattdessen optionale KI-Funktionen:

- [Eingebrannten Text entfernen](08-process/02-remove-burned-in-text)
- [Gesichter unscharf machen](08-process/04-blur-faces)

## Structured Reports und Overlays

Curve-/Overlay-Gruppen werden entfernt. Ob Structured-Report-Objekte akzeptiert werden, steuern die Speicherklassen-Einstellungen des Projekts.

!!! note "Für Compliance-Prüfung"
    Lassen Sie Ihren Datenschutzbeauftragten das Anonymizer-Skript und die KI-Werkzeuge für Ihre Institution prüfen. Dieses Handbuch ist betriebliche Anleitung, keine Rechtsberatung.
