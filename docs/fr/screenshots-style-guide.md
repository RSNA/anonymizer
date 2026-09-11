# Guide de style des captures d’écran

Pour les auteurs qui mettent à jour ce manuel.

## Règles de capture

- **Thème :** mode clair
- **Langue :** capturer l’interface en anglais (`en_US`) pendant la finalisation du manuel anglais
- **PHI :** fixtures de test uniquement — jamais de vraies données patient
- **Stockage :** les captures vivent sous chaque flux numéroté comme `shots/macos/*.png` et `shots/windows/*.png`
- **Catalogue :** [`docs/screenshots-manifest.yaml`](../screenshots-manifest.yaml) liste chaque élément UX et chaque capture
- **Échelle / résolution :** la capture stocke les **points UI logiques** (Retina 2× → 1 px PNG ≈ 1 pt app), puis `normalize_for_docs` force chaque PNG à **`DOCS_SHOT_MAX_WIDTH`** (960) : les fenêtres larges sont réduites, les dialogues étroits sont letterboxés (pas d’upscale UI). Même largeur de fichier ⇒ même échelle MkDocs ⇒ texte UI le plus petit cohérent entre les pages.
- **Pas d’ombres :** les captures macOS utilisent `screencapture -o` (omettre l’ombre de fenêtre) ; la frange douce résiduelle est retirée avant enregistrement. Ne pas livrer de captures avec drop shadows.
- **Coins :** macOS utilise la capture par ID de fenêtre (`screencapture -l`) pour que les PNG gardent coins arrondis et alpha ; Windows utilise PrintWindow / BitBlt

## Dossiers de flux de travail

```
docs/en/02-install/shots/{macos,windows}/
docs/en/03-ai-features-setup/shots/{macos,windows}/
docs/en/05-create-project/shots/{macos,windows}/
docs/en/06-search/shots/{macos,windows}/
docs/en/07-view/shots/{macos,windows}/
docs/en/08-process/02-remove-burned-in-text/shots/{macos,windows}/
docs/en/08-process/03-harmonize-names/shots/{macos,windows}/
docs/en/08-process/04-blur-faces/shots/{macos,windows}/
docs/en/08-process/05-run-on-many-studies/shots/{macos,windows}/
docs/en/09-send/shots/{macos,windows}/
```

Markdown embarque le chemin **macOS** (le JS du site bascule vers Windows pour les visiteurs Windows) :

`![…](shots/macos/Welcome.png)`

## Capture automatisée

Les outils vivent dans [`src/docs_help/`](../../src/docs_help/) (pas le paquet d’application livré).

**Responsabilité développeur :** récupérer le code le plus récent, lancer la capture sur **macOS** puis à nouveau sur **Windows**, puis committer et pousser les deux arbres PNG. Il n’y a pas de grab CI/cloud.

Nécessite un affichage bureau avec permission de capture d’écran (Enregistrement de l’écran macOS ; accès bureau Windows) ; Orthanc sur `127.0.0.1:4242` (AE `ORTHANC`) pour les captures Rechercher/Requête. Si les captures sont vides, réattribuez la permission de capture et relancez avec `--force`.

```bash
uv run python -m docs_help --language en_US
uv run python -m docs_help --language en_US --force
uv run python -m docs_help --language en_US --force --only Welcome
```

- Écrit `docs/<lang>/<chapter>/shots/<os>/` où `<os>` est `macos` ou `windows` (OS hôte ; `--platform auto`)
- **Reprise par défaut** (`--skip-existing`) ; utilisez `--force` ou `--force-shot ID` pour refaire
- Les démos Traiter utilisent uniquement des fixtures **non synthétiques** :
  - **8.1** Supprimer le PHI pixel → `davidson_cxr` (noircir) + `us_rgb_single_frame` (fusion + Zone d'exclusion sous mindray)
  - **8.2** Harmoniser → `CT_Head_With_Contrast` (Vue des séries → résultats terminés → invite cerveau → coupe du milieu segmentée) + `davidson_cxr` / `us_rgb_single_frame` (sources Playbook planaires)
  - **8.3** Flou facial → `CT_Head_With_Contrast` (Gaussien)
  - **8.4** Lots → les deux fixtures sélectionnées dans Jeu de données
- Soft-fail des captures Traiter lourdes en IA lorsque les modèles manquent
- Hard-fail des captures Rechercher dépendantes d’Orthanc lorsque C-ECHO échoue
- Si un PNG Windows manque, le site publié retombe sur l’image macOS

## Captures prioritaires (V19)

Bienvenue ; Fonctions IA ; Paramètres de création de projet (+ sous-dialogues) ; Tableau de bord ; Rechercher ; Vue (Jeu de données + édition description série/étude + Projections + Série + CSV Recherche de Patient) ; Traiter (Supprimer le PHI pixel, Harmoniser, Face, lots) ; Envoyer (initial → sélection → envoi → envoyé).
