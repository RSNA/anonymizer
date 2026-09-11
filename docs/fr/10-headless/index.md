# Exécution sans interface

Utilisez le mode headless sur un **laboratoire ou serveur** lorsque vous n’avez pas besoin de la fenêtre bureau. Créez et configurez d’abord le projet dans l’interface graphique.

## Objectif

- Continuer à recevoir du DICOM dans un projet existant, et/ou
- Lancer un lot IA une fois sur ce projet, puis quitter.

## Deux commandes

### 1. Réception uniquement (écouteur DICOM)

```bash
rsna-anonymizer -c path/to/ProjectModel.json
```

L’application charge le projet et écoute les images entrantes avec les paramètres de serveur local du projet.

### 2. Lot IA une fois, puis quitter

```bash
rsna-anonymizer -c path/to/ProjectModel.json --ai-batch path/to/AiBatchConfig.json --ai-batch-run
```

`-c` / `--config` et `--ai-batch` sont tous deux requis avec `--ai-batch-run`.

## À quoi sert chaque fichier

| Fichier | Objectif |
| --- | --- |
| **ProjectModel.json** | Site, nom de projet, chemin de stockage, nœuds DICOM, modalités, délais — la définition du projet. |
| **AiBatchConfig.json** | Quels outils IA lancer, modes de flou/OCR, sélection d’études (`all` ou une liste), remplacements optionnels de résolution CT/MR. |

Exemple de configuration de lot IA (téléchargeable : [`AiBatchConfig.example.json`](AiBatchConfig.example.json)) :

```json
{
  "algorithms": ["harmonize", "face_blur", "remove_pixel_phi"],
  "blur_mode": "gaussian",
  "pixel_phi_removal_mode": "blackout",
  "use_modality_whitelist": true,
  "include_brain_structures": false,
  "ct_segmentation_mode": "3mm",
  "mr_segmentation_mode": "3mm",
  "studies": "all",
  "skip_already_processed": true
}
```

Les listes blanches OCR restent sous le répertoire `whitelists/` du projet (comme dans l’interface graphique).

## Prérequis

- Projet déjà créé dans l’interface graphique ([Créer un projet](../05-create-project/)).
- Modèles et licence visage déjà configurés sur **cette machine** ([Configuration des Fonctions IA](../03-ai-features-setup)).
- Assez de mémoire libre pour les algorithmes sélectionnés.

## Ce qui indique que tout va bien

- Mode réception : le processus reste en cours ; les nouvelles études apparaissent sous le stockage / Jeu de données lorsque vous ouvrez l’interface plus tard.
- Mode lot : le journal montre les phases et un résumé ; le processus quitte à la fin (code de sortie 0 en cas de succès).

## Échecs courants

| Problème | À vérifier |
| --- | --- |
| `--ai-batch-run` sans fichiers | Fournissez à la fois `-c` et `--ai-batch` |
| Erreurs de gate de fonction | Téléchargez modèles / licence sur ce poste |
| Liste d’études vide | Importez d’abord des données, ou corrigez `studies` dans AiBatchConfig |
| Mémoire insuffisante | Réduisez la charge concurrente ; voir [Dépannage](../troubleshooting.md) |

## Pour les cliniciens

Le mode headless ne **remplace pas** la relecture d’un échantillon dans Jeu de données ou Vue des séries. Utilisez l’interface pour la configuration initiale et les contrôles qualité ; utilisez headless pour la réception de routine ou un lot de nuit.

!!! tip "Même travail que le lot de l’interface"
    Étapes bureau : [Exécuter sur plusieurs études](../08-process/05-run-on-many-studies/). Headless utilise les mêmes outils IA avec une recette JSON.

## Prochaines étapes

1. [Dépannage](../troubleshooting.md) si quelque chose échoue
2. [Tutoriels](../tutorials/) pour de courts parcours
3. Retour à [Accueil](../) pour la liste complète des chapitres
