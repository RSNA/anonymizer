# Dépannage

## Modèles et Fonctions IA

| Message / symptôme | Que tenter |
| --- | --- |
| Pas prêt / échec du téléchargement | Revenez à **Bienvenue**, ouvrez **Fonctions IA**, réessayez Télécharger, vérifiez le réseau |
| OpenMP / XGBoost sous macOS | Installez C++ OpenMP une fois : `brew install libomp` (requis pour Fonctions IA / contraste Harmonize) |
| Erreurs de licence | Vérifiez la longueur/le format `aca_` ; validez en ligne |
| Harmonize déjà en cours | Terminez ou annulez l’autre série |
| Outil grisé | Installez le pack CT/MR correspondant |

## Import et quarantaine

| Symptôme | Que tenter |
| --- | --- |
| Fichiers ignorés | Déjà importés (même SOP Instance) |
| Dossiers de quarantaine qui se remplissent | Lisez le nom du dossier (Invalid_DICOM, Missing_Attributes, Lookup_Miss, …) |
| Lookup_Miss | Corrigez la [table de correspondance](05-create-project/) ou l’identifiant patient |

## Lots et mémoire

| Symptôme | Que tenter |
| --- | --- |
| Mémoire insuffisante / arrêté | Fermez d’autres applications ; moins d’études ; voir la boîte d’avertissement mémoire |
| Tout ignoré | Déjà traité — attendu sauf si vous videz le statut/cache |
| Aucune série pour les études | La sélection n’a pas de série DICOM lisible |

## Headless

Guide complet : [Exécution sans interface](10-headless/).

- `--ai-batch-run` nécessite **à la fois** `-c` et `--ai-batch`
- Les gates de fonction échouent si les modèles n’ont jamais été téléchargés sur cette machine
- `studies` vide / pas d’index PHI → importez d’abord dans l’interface graphique

## Affichage

| Symptôme | Que tenter |
| --- | --- |
| Fenêtre Bienvenue minuscule / coupée (macOS) | Utilisez la V19 actuelle ; conseils Tk 9 / réinstallation uv dans [Installation](02-install/) |
| Échec des projections sur US couleur | Mettez à jour vers la V19 actuelle |
