# Traiter

Les outils **Traiter** modifient les **pixels** anonymisés ou les **noms de série / étude** après l’import. Travaillez sur **une série** dans Vue des séries (ouverte depuis [Vue](../07-view/index.md)), ou sur **plusieurs études** depuis Jeu de données ([Traitement par lots IA](05-run-on-many-studies/index.md)).

Les modèles et licences se configurent une fois depuis Bienvenue — voir [Configuration des Fonctions IA](../03-ai-features-setup/index.md) avant les chapitres d’outils ci-dessous.

## Outils

| Chapitre | Outil | Série de démo | Ce que vous pratiquez |
| --- | --- | --- | --- |
| 8.1 | [Supprimer le PHI pixel](02-remove-burned-in-text/index.md) (texte incrusté) | **`davidson_cxr`**, **`us_rgb_single_frame`** | Détecter → noircir ; Détecter → fusionner avec l’arrière-plan |
| 8.2 | [Harmoniser les noms](03-harmonize-names/index.md) | **`CT_Head_With_Contrast`**, **`davidson_cxr`**, **`us_rgb_single_frame`** | Résultats CT + invite cerveau ; sources Playbook XR/US planaires |
| 8.3 | [Flouter les visages](04-blur-faces/index.md) | **`CT_Head_With_Contrast`** | Flou facial, mode **Gaussien** |
| 8.4 | [Exécuter sur plusieurs études](05-run-on-many-studies/index.md) | Études sélectionnées | Lancer les mêmes outils sur une cohorte |

Les séries de démo sont sous `tests/controller/assets/test_dcm_files/`. Importez-les ([Rechercher](../06-search/index.md)), puis ouvrez Vue des séries depuis Jeu de données ([Vue](../07-view/index.md) — clic droit sur la série).

## Ordre d’apprentissage

1. Terminez [Configuration des Fonctions IA](../03-ai-features-setup/index.md) pour que les modèles soient prêts.
2. Parcourez **Supprimer le PHI pixel** sur `davidson_cxr` (noircir), puis essayez la fusion sur `us_rgb_single_frame`.
3. Parcourez **Harmoniser** sur `CT_Head_With_Contrast`, puis les démos planaires sur `davidson_cxr` et `us_rgb_single_frame` ; **Flou facial** sur la même série CT tête.
4. Utilisez **Exécuter sur plusieurs études** lorsque vous avez besoin des mêmes outils sur une cohorte.

## Prochaines étapes

1. Commencez par [8.1 Supprimer le PHI pixel](02-remove-burned-in-text/index.md)
2. Une fois le traitement satisfaisant, [Envoyer](../09-send/index.md) les patients anonymisés, ou [exécuter sans interface](../10-headless/index.md) sur un serveur de laboratoire
