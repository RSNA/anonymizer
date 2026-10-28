# Commencer ici

## Ce que fait ce programme

Le RSNA DICOM Anonymizer est une application autonome qui **supprime les informations d’identité protégées** des examens d’imagerie médicale et enregistre une copie adaptée à la recherche sur votre ordinateur.

Vous pouvez importer des images depuis un dossier ou un système d’imagerie hospitalier, les revoir, appliquer éventuellement des outils d’IA (texte incrusté sur les pixels, nettoyage d’entités nommées dans le texte des comptes rendus, noms d’étude et de série standardisés, face blur), puis envoyer les études désidentifiées vers un autre système ou une archive cloud.

## Objectif de confidentialité

Les noms de patients, identifiants et autres éléments dans les « étiquettes » du fichier (tags DICOM) sont remplacés ou supprimés à l’**import** par le script de dé-identification du projet. Les dates sont décalées pour que la chronologie d’un patient reste cohérente sans correspondre à la date calendaire.

Ce parcours de tags ne nettoie **pas** le texte libre des Structured Reports ou Encapsulated PDFs, et n’efface pas les noms dessinés sur les pixels. Lorsque vous conservez des objets de compte rendu (Clean Structured Content), vous devez lancer la **Revue du texte de compte rendu** après l’import : la reconnaissance d’entités nommées (NER) en anglais trouve noms, dates, identifiants, téléphones et plages similaires dans le corps du compte rendu pour que vous puissiez les vider ou les remplacer par des valeurs synthétiques. Séparément, des outils d’IA optionnels peuvent masquer le texte incrusté sur les pixels et flouter les visages sur les examens de la tête — car ceux-ci peuvent encore identifier quelqu’un après nettoyage des étiquettes.

## Normes et tests

Le script par défaut suit le DICOM **Basic Application Confidentiality Profile** ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html)) et les options de rétention que vous choisissez pour le projet. Ce profil et le **Medical Image De-Identification Benchmark (MIDI-B)** public TCIA / NCI sont alignés sur une suppression d’identifiants d’imagerie de type **HIPAA Safe Harbor** (sans prétendre que le produit est « certifié HIPAA »). La dé-identification d’en-tête est vérifiée avec le scoreur officiel MIDI-B (voir [Protocole de désidentification](../deidentification-protocol.md)). La checklist formelle PS 3.15 § E.1.3 figure dans la [Déclaration de conformité DICOM](../dicom-conformance-statement.md). Votre responsable de la confidentialité doit tout de même revoir les options et tout script personnalisé pour votre site — ce manuel est un guide opérationnel, pas un certificat de conformité.

## Pour qui

- Radiologues et chercheurs en imagerie qui constituent des jeux de données
- Sites qui soumettent des études à des archives de recherche

## Deux façons de travailler


| Mode | Idéal pour |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| **Fenêtre bureau (GUI)** | Créer des projets, revoir des images, outils d’IA, export |
| **Sans fenêtre (headless)** | Laboratoire/serveur : continuer à recevoir des images ou lancer un lot d’IA la nuit — voir [Exécution sans interface](../10-headless/index.md) |


!!! important "Créez d’abord le projet dans la fenêtre"
    Le mode headless utilise un projet déjà créé et configuré. Commencez par [Créer un projet](../05-create-project/index.md), puis demandez à l’informatique de lancer le mode headless si besoin.

## Prochaines étapes

1. [Installation et premier lancement](../02-install/index.md)
2. [Configuration des Fonctions IA](../03-ai-features-setup/index.md) (depuis Bienvenue)
3. [Mots que nous utilisons](../04-words-we-use/index.md)
4. [Créer un projet](../05-create-project/index.md)
