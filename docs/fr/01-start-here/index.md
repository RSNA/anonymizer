# Commencer ici

## Ce que fait ce programme

Le RSNA DICOM Anonymizer est une application autonome qui **supprime les informations d’identité protégées** des examens d’imagerie médicale et enregistre une copie adaptée à la recherche sur votre ordinateur.

Vous pouvez importer des images depuis un dossier ou un système d’imagerie hospitalier, les revoir, appliquer éventuellement des outils d’IA (suppression du texte incrusté, noms d’étude et de série standardisés, face blur), puis envoyer les études désidentifiées vers un autre système ou une archive cloud.

## Objectif de confidentialité

Les noms de patients, identifiants et autres éléments dans les « étiquettes » du fichier (tags DICOM) sont remplacés ou supprimés. Les dates sont décalées pour que la chronologie d’un patient reste cohérente sans correspondre à la date calendaire. Des outils d’IA optionnels peuvent aussi masquer du texte dessiné sur l’image elle-même et flouter les traits du visage sur les examens de la tête — car ceux-ci peuvent encore identifier quelqu’un après nettoyage des étiquettes.

## Pour qui

- Radiologues et chercheurs en imagerie qui constituent des jeux de données
- Sites qui soumettent des études à des archives de recherche

## Deux façons de travailler


| Mode | Idéal pour |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Fenêtre bureau (GUI)** | Créer des projets, revoir des images, outils d’IA, export |
| **Sans fenêtre (headless)** | Laboratoire/serveur : continuer à recevoir des images ou lancer un lot d’IA la nuit — voir [Exécution sans interface](../10-headless/) |


!!! important "Créez d’abord le projet dans la fenêtre"
    Le mode headless utilise un projet déjà créé et configuré. Commencez par [Créer un projet](../05-create-project/), puis demandez à l’informatique de lancer le mode headless si besoin.

## Prochaines étapes

1. [Installation et premier lancement](../02-install/)
2. [Configuration des Fonctions IA](../03-ai-features-setup/) (depuis Bienvenue)
3. [Mots que nous utilisons](../04-words-we-use/)
4. [Créer un projet](../05-create-project/)
