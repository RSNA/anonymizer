# Verarbeiten

**Verarbeiten**-Werkzeuge ändern anonymisierte **Pixel** oder **Serien-/Studiennamen** nach dem Import. Arbeiten Sie an **einer Serie** in der Serienansicht (geöffnet aus [Ansicht](../07-view/)) oder an **vielen Studien** aus dem Datensatz ([KI-Stapelverarbeitung](05-run-on-many-studies/)).

Modelle und Lizenzen werden einmal vom Willkommen-Bildschirm eingerichtet — siehe [KI-Funktionen einrichten](../03-ai-features-setup/) vor den Werkzeugkapiteln unten.

## Werkzeuge

| Kapitel | Werkzeug | Demo-Serie | Was Sie üben |
| --- | --- | --- | --- |
| 8.1 | [Pixel-PHI entfernen](02-remove-burned-in-text/) (eingebrannter Text) | **`davidson_cxr`**, **`us_rgb_single_frame`** | Erkennen → schwärzen; Erkennen → in den Hintergrund einblenden |
| 8.2 | [Namen harmonisieren](03-harmonize-names/) | **`CT_Head_With_Contrast`**, **`davidson_cxr`**, **`us_rgb_single_frame`** | CT-Ergebnisse + Hirn-Prompt; planare XR/US-Playbook-Quellen |
| 8.3 | [Gesichter unscharf machen](04-blur-faces/) | **`CT_Head_With_Contrast`** | Gesichtsunschärfe, Modus **Gaussian** |
| 8.4 | [Auf vielen Studien ausführen](05-run-on-many-studies/) | Ausgewählte Studien | Dieselben Werkzeuge über eine Kohorte stapeln |

Demo-Serien liegen unter `tests/controller/assets/test_dcm_files/`. Importieren ([Suchen](../06-search/)), dann Serienansicht aus dem Datensatz öffnen ([Ansicht](../07-view/) — Rechtsklick auf die Serie).

## Lernreihenfolge

1. [KI-Funktionen einrichten](../03-ai-features-setup/) abschließen, damit Modelle bereit sind.
2. **Pixel-PHI entfernen** auf `davidson_cxr` durchgehen (schwärzen), dann Einblenden auf `us_rgb_single_frame` ausprobieren.
3. **Harmonisieren** auf `CT_Head_With_Contrast` durchgehen, dann die planaren Demos auf `davidson_cxr` und `us_rgb_single_frame`; **Gesichtsunschärfe** auf derselben CT-Kopfserie.
4. **Auf vielen Studien ausführen** nutzen, wenn Sie dieselben Werkzeuge auf einer Kohorte brauchen.

## Nächste Schritte

1. Beginnen Sie mit [8.1 Pixel-PHI entfernen](02-remove-burned-in-text/)
2. Wenn die Verarbeitung gut aussieht, [Senden](../09-send/) anonymisierter Patienten oder [ohne Oberfläche ausführen](../10-headless/) auf einem Laborserver
