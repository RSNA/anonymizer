# Traiter

**Traiter** termine le travail de désidentification que l’import ne fait pas : nettoyer le texte incrusté sur les images, trouver le PHI restant dans les tags texte libre et les comptes rendus, standardiser les noms de série et d’étude avec Harmoniser, et flouter les visages sur les examens tête éligibles. Lancez un outil sur une série dans [Vue des séries](../07-view/index.md#series-view-what-you-can-do) en cliquant droit sur la série dans Jeu de données, ou sur plusieurs études avec [Traitement par lots IA](05-run-on-many-studies/index.md) depuis Jeu de données.

Pour contrôler les tags DICOM sans les modifier, utilisez [Metadata](../07-view/index.md#metadata-dicom-tags) dans Vue des séries. Après Harmoniser sur CT ou MR, verrouillez les puces d’anatomie ou peignez des ROI utilisateur sous [Annotation](../07-view/index.md#annotation). Les segments d’annotation sont en 3D sur CT et MR, et en 2D sur XR, US et MG planaire.

Les modèles et licences se configurent une fois depuis Bienvenue — voir [Configuration des Fonctions IA](../03-ai-features-setup/index.md) avant les chapitres d’outils ci-dessous.

## Flux sur site {#recommended-site-workflow}

QA quelques séries en Vue des séries, puis montez en charge avec le lot IA depuis Jeu de données :

1. **Importer** via [Rechercher](../06-search/index.md) ; ouvrez des échantillons en [Vue des séries](../07-view/index.md#series-view-what-you-can-do).
2. **Harmoniser** un échantillon CT/MR et planaire ; corrigez les noms avec [Modifier les descriptions d’étude et de série](../07-view/index.md#edit-study-and-series-descriptions) et [Correspondances de description](../07-view/index.md#description-mappings). Verrouillez ou peignez sous [Annotation](../07-view/index.md#annotation). Volumes d’organes CT/MR : [Analytics](../07-view/index.md#analytics).
3. **Flou facial** sur une série tête éligible ; gardez le mode du lot (démo : Gaussien).
4. **Embedded PHI** — [8.1](02-remove-burned-in-text/index.md) : [Pixel](02-remove-burned-in-text/index.md#pixel), [Metadata](02-remove-burned-in-text/index.md#metadata) et [Reports](02-remove-burned-in-text/index.md#reports) sur échantillons.
5. **Lot** des mêmes options sur la cohorte avec [Traitement par lots IA](05-run-on-many-studies/index.md) ; laissez Préférer les correspondances de description activé.

Les chapitres 8.1–8.3 enseignent chaque outil ; 8.4 est l’étape cohorte.

## Outils

| Chapitre | Outil | Série de démo | Ce que vous pratiquez |
| --- | --- | --- | --- |
| 8.1 | [Embedded PHI](02-remove-burned-in-text/index.md) — [Pixel](02-remove-burned-in-text/index.md#pixel) / [Metadata](02-remove-burned-in-text/index.md#metadata) / [Reports](02-remove-burned-in-text/index.md#reports) | `davidson_cxr`, `us_rgb_single_frame`, `demo_report_pdf` | Pixel Detect→Remove ; Metadata Detect PHI ; Report Text Review |
| 8.2 | [Harmoniser les noms](03-harmonize-names/index.md) | `CT_Head_With_Contrast`, `davidson_cxr`, `us_rgb_single_frame` | Résultats CT + invite cerveau ; [Annotation](../07-view/index.md#annotation) 2D/3D ; volumes d’organes CT/MR [Analytics](../07-view/index.md#analytics) ; Playbook XR/US planaire |
| 8.3 | [Flouter les visages](04-blur-faces/index.md) | `CT_Head_With_Contrast` | Flou facial, mode Gaussien |
| 8.4 | [Exécuter sur plusieurs études](05-run-on-many-studies/index.md) | Études sélectionnées | Lancer les mêmes outils sur une cohorte |

Les séries de démo sont sous `tests/controller/assets/test_dcm_files/`. Importez-les ([Rechercher](../06-search/index.md)), puis ouvrez Vue des séries depuis Jeu de données ([Vue](../07-view/index.md) — clic droit sur la série).

## Ordre d’apprentissage

1. Terminez [Configuration des Fonctions IA](../03-ai-features-setup/index.md) pour que les modèles soient prêts.
2. Parcourez Embedded PHI [Pixel](02-remove-burned-in-text/index.md#pixel) sur `davidson_cxr` / `us_rgb_single_frame`, puis [Metadata](02-remove-burned-in-text/index.md#metadata) et [Reports](02-remove-burned-in-text/index.md#reports) sur un compte rendu d’échantillon.
3. Parcourez Harmoniser sur `CT_Head_With_Contrast`, puis les démos planaires sur `davidson_cxr` et `us_rgb_single_frame` ; revoyez ou peignez des segments sous [Annotation](../07-view/index.md#annotation) ; sur CT/MR consultez les graphiques de volume d’organes Harmonize dans [Analytics](../07-view/index.md#analytics) ; Flou facial sur la même série CT tête.
4. Utilisez Exécuter sur plusieurs études lorsque vous avez besoin des mêmes outils sur une cohorte — voir [Flux sur site](#recommended-site-workflow) pour le motif QA Vue des séries → lot Jeu de données.

## Prochaines étapes

1. Commencez par [8.1 Embedded PHI](02-remove-burned-in-text/index.md)
2. Une fois le traitement satisfaisant, [Envoyer](../09-send/index.md) les patients anonymisés, ou [exécuter sans interface](../10-headless/index.md) sur un serveur de laboratoire
