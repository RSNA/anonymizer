# Verarbeiten

**Verarbeiten** erledigt De-Identifikationsarbeit, die der Import nicht leistet: eingebrannten Text auf Bildern entfernen, Rest-PHI in Freitext-Tags und Berichten finden, Serien- und Studiennamen mit Harmonisieren standardisieren und Gesichter auf geeigneten Kopfuntersuchungen unscharf machen. Führen Sie ein Werkzeug an einer Serie in der [Serienansicht](../07-view/index.md#series-view-what-you-can-do) aus, indem Sie im Datensatz mit Rechtsklick die Serie öffnen, oder an vielen Studien mit [KI-Stapelverarbeitung](05-run-on-many-studies/index.md) aus dem Datensatz.

Zum Stichproben-Check von DICOM-Tags ohne Änderung nutzen Sie Serienansicht-[Metadata](../07-view/index.md#metadata-dicom-tags). Nach Harmonisieren auf CT oder MR Anatomie-Chips latchen oder Benutzer-ROIs unter [Annotation](../07-view/index.md#annotation) malen. Annotationssegmente sind auf CT und MR dreidimensional und auf planar XR, US und MG zweidimensional.

Modelle und Lizenzen werden einmal vom Willkommen-Bildschirm eingerichtet — siehe [KI-Funktionen einrichten](../03-ai-features-setup/index.md) vor den Werkzeugkapiteln unten.

## Standort-Workflow {#recommended-site-workflow}

Wenige Serien in der Serienansicht prüfen (QA), dann mit KI-Stapel aus dem Datensatz skalieren:

1. **Import** über [Suchen](../06-search/index.md); Stichproben in der [Serienansicht](../07-view/index.md#series-view-what-you-can-do) öffnen.
2. **Harmonisieren** einer CT/MR- und planaren Stichprobe; Namen mit [Studien- und Serienbeschreibungen bearbeiten](../07-view/index.md#edit-study-and-series-descriptions) und [Beschreibungszuordnungen](../07-view/index.md#description-mappings) korrigieren. Latchen oder malen unter [Annotation](../07-view/index.md#annotation). CT/MR-Organvolumina: [Analytics](../07-view/index.md#analytics).
3. **Gesichtsunschärfe** auf einer geeigneten Kopfserie; den Stapel-Modus behalten (Demo: Gaussian).
4. **Embedded PHI** — [8.1](02-remove-burned-in-text/index.md): [Pixel](02-remove-burned-in-text/index.md#pixel), [Metadata](02-remove-burned-in-text/index.md#metadata) und [Reports](02-remove-burned-in-text/index.md#reports) an Stichproben.
5. **Stapel** derselben Optionen auf der Kohorte mit [KI-Stapelverarbeitung](05-run-on-many-studies/index.md); Beschreibungszuordnungen bevorzugen eingeschaltet lassen.

Kapitel 8.1–8.3 lehren jedes Werkzeug; 8.4 ist der Kohortenschritt.

## Werkzeuge

| Kapitel | Werkzeug | Demo-Serie | Was Sie üben |
| --- | --- | --- | --- |
| 8.1 | [Embedded PHI](02-remove-burned-in-text/index.md) — [Pixel](02-remove-burned-in-text/index.md#pixel) / [Metadata](02-remove-burned-in-text/index.md#metadata) / [Reports](02-remove-burned-in-text/index.md#reports) | `davidson_cxr`, `us_rgb_single_frame`, `demo_report_pdf` | Pixel Detect→Remove; Metadata Detect PHI; Report Text Review |
| 8.2 | [Namen harmonisieren](03-harmonize-names/index.md) | `CT_Head_With_Contrast`, `davidson_cxr`, `us_rgb_single_frame` | CT-Ergebnisse + Hirn-Prompt; [Annotation](../07-view/index.md#annotation) 2D/3D; CT/MR-[Analytics](../07-view/index.md#analytics)-Organvolumina; planar XR/US-Playbook |
| 8.3 | [Gesichter unscharf machen](04-blur-faces/index.md) | `CT_Head_With_Contrast` | Gesichtsunschärfe, Modus Gaussian |
| 8.4 | [Auf vielen Studien ausführen](05-run-on-many-studies/index.md) | Ausgewählte Studien | Dieselben Werkzeuge über eine Kohorte stapeln |

Demo-Serien liegen unter `tests/controller/assets/test_dcm_files/`. Importieren ([Suchen](../06-search/index.md)), dann Serienansicht aus dem Datensatz öffnen ([Ansicht](../07-view/index.md) — Rechtsklick auf die Serie).

## Lernreihenfolge

1. [KI-Funktionen einrichten](../03-ai-features-setup/index.md) abschließen, damit Modelle bereit sind.
2. Embedded PHI [Pixel](02-remove-burned-in-text/index.md#pixel) auf `davidson_cxr` / `us_rgb_single_frame`, dann [Metadata](02-remove-burned-in-text/index.md#metadata) und [Reports](02-remove-burned-in-text/index.md#reports) an einem Beispielbericht.
3. Harmonisieren auf `CT_Head_With_Contrast` durchgehen, dann die planaren Demos auf `davidson_cxr` und `us_rgb_single_frame`; Segmente unter [Annotation](../07-view/index.md#annotation) prüfen oder malen; auf CT/MR Harmonize-Organvolumen-Diagramme in [Analytics](../07-view/index.md#analytics); Gesichtsunschärfe auf derselben CT-Kopfserie.
4. Auf vielen Studien ausführen nutzen, wenn Sie dieselben Werkzeuge auf einer Kohorte brauchen — siehe [Standort-Workflow](#recommended-site-workflow) für das Muster Serienansicht-QA → Datensatz-Stapel.

## Nächste Schritte

1. Beginnen Sie mit [8.1 Embedded PHI](02-remove-burned-in-text/index.md)
2. Wenn die Verarbeitung gut aussieht, [Senden](../09-send/index.md) anonymisierter Patienten oder [ohne Oberfläche ausführen](../10-headless/index.md) auf einem Laborserver
