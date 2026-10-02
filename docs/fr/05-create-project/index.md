# Créer un projet

Un **projet** regroupe les paramètres et le stockage anonymisé. Créez-le une fois dans la fenêtre bureau, même si un serveur exécutera ensuite le mode [headless](../10-headless/).

## Objectif

Ouvrir un projet propre avec un dossier de stockage et une identité de site prêts pour l’import.

## Créer un nouveau projet

1. Depuis **Fichier → Nouveau projet**, ouvrez **Paramètres du nouveau projet**.
2. Choisissez un **Nom du projet** (court, moins de 16 caractères) et confirmez le **Répertoire de stockage**.
3. Vérifiez Site ID et UID Root (laissez en général les valeurs par défaut, sauf si vous continuez un site Java Anonymizer).
4. Confirmez les modalités et les paramètres réseau avec l’informatique si vous interrogez un PACS.
5. Enregistrez / créez le projet. Le **Tableau de bord** s’ouvre.

![Paramètres du nouveau projet](shots/macos/NewProjectSettings.png)

## Actions courantes sur le projet


| Action | Comment |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| Fermer | **Fichier → Fermer le projet** ou fermer la fenêtre |
| Rouvrir | **Fichier → Ouvrir récent** |
| Cloner les paramètres | **Fichier → Cloner le projet** dans un nouveau dossier de stockage (aucune image copiée). Gardez un UID Root unique par projet. |




## Ce qui indique que tout va bien

- Le Tableau de bord affiche le nom du projet et le Site ID.
- Le répertoire de stockage existe et est accessible en écriture.
- Vous pouvez ouvrir le **Jeu de données** actuellement constitué (vide jusqu’à l’import) en cliquant sur **Vue**.



## Quand vous parlez à l’informatique

Partagez ces idées (les détails sont dans les dialogues Paramètres du projet) :

- **Serveur local** — adresse, port et AE Title que cet ordinateur utilise pour **recevoir** les images.
- **Serveur de requête** — l’archive hospitalière que vous interrogez et depuis laquelle vous récupérez.
- **Serveur d’exportation** ou **AWS** — où les études anonymisées seront envoyées.
- **Modalités / classes de stockage / transfer syntaxes** — quels types d’images sont autorisés.
- **Délais réseau** — combien de temps attendre les archives lentes.
- **Script d’anonymisation** — quelles balises DICOM sont conservées, supprimées ou transformées (voir [Éditeur du script d’anonymisation](#éditeur-du-script-danonymisation)).
- **Table de correspondance des patients** — mapping CTP `.properties` optionnel pour PatientID et décalage de date (voir [Table de correspondance des patients](#table-de-correspondance-des-patients)).

Si le projet vivra sur un serveur de laboratoire, continuez avec [Exécution sans interface](../10-headless/).

## Paramètres du projet (tous les contrôles)

Ouvrez **Fichier → Paramètres du projet** (ou Paramètres du nouveau projet à la création). Configurez-les avant Rechercher / Envoyer :

### Serveur local

Adresse, port et AE Title que cet ordinateur utilise pour **recevoir** les images.

![Serveur local](shots/macos/LocalServer.png)

### Serveur de requête

Archive hospitalière utilisée par **Rechercher** sur le Tableau de bord.

![Serveur de requête](shots/macos/QueryServer.png)

### Serveur d’exportation

Destination DICOM utilisée lorsque vous **Envoyer** (l’étiquette des paramètres peut encore dire Export Server).

![Serveur d’exportation](shots/macos/ExportServer.png)

### AWS Cognito (optionnel)

Identifiants pour Envoyer vers S3 lorsque activé.

![AWS Cognito](shots/macos/AWSCognito.png)

### Délais réseau

Combien de temps attendre les archives lentes.

![Délais réseau](shots/macos/NetworkTimeouts.png)

### Modalités / classes de stockage / transfer syntaxes

Quels types d’images et encodages sont autorisés.

![Modalités](shots/macos/Modalities.png)
![Classes de stockage](shots/macos/StorageClasses.png)
![Transfer Syntaxes](shots/macos/TransferSyntaxes.png)

### Éditeur du script d’anonymisation

Le **script d’anonymisation** du projet est un fichier XML compatible CTP listant chaque balise DICOM connue et l’action associée. La valeur par défaut fournie suit le profil DICOM Basic Application Confidentiality décrit dans [Protocole de dé-identification](../deidentification-protocol.md).

Ouvrez **Fichier → Paramètres du projet** (ou Paramètres du nouveau projet), puis cliquez sur **Modifier le script d’anonymisation**. Pour un nouveau projet, vous pouvez aussi **Parcourir** d’abord un autre modèle `.script`.

#### Vues

| Vue | Contenu |
| --- | --- |
| **Actifs** (par défaut) | Balises **conservées** ou **transformées** (pas `@remove()`). La liste du quotidien — environ 1,5k lignes au lieu de ~4,6k. |
| **Supprimés** | Balises marquées `@remove()` (supprimées à l’anonymisation). |
| **Tous** | Toutes les règles de balise du script. |

La recherche et le filtre **Opérande** s’appliquent dans la vue courante. La liste est **paginée** (Précédent / Suivant) pour garder la fenêtre réactive.

#### Modifier une règle

1. Sélectionnez une ligne dans la liste.
2. Modifiez **Nom** (libellé seulement) ou **Opérande** dans le panneau de détail.
3. Opérandes pris en charge : **Conserver**, **Supprimer**, **Vider**, **UID**, **ID patient**, **Accession**, **Hacher la date**, **Rechercher l’ID patient**, **Rechercher le décalage de date**, **Arrondir l’âge** (avec paramètre de largeur).
4. Choisir **Supprimer** retire la balise de la vue Actifs (elle reste dans le script en `@remove()`).

#### Ajouter une balise (chemin habituel)

1. Cliquez sur **Ajouter depuis les supprimés…**.
2. Recherchez dans la liste des balises supprimées et sélectionnez une balise déjà connue du script.
3. Choisissez l’opérande initial (par défaut **Conserver**) → **Ajouter**.
4. La balise apparaît sous **Actifs** et est sélectionnée pour d’autres modifications.

Utilisez **Ajouter depuis le dictionnaire…** uniquement si la balise **n’est pas** déjà dans le script (cas rare). La recherche dictionnaire est plafonnée et temporisée.

#### Enregistrer

- **Accepter** valide les opérandes, écrit une copie privée sous `{stockage}/private/{site_id}-anonymizer.script`, recharge les règles d’anonymisation actives et met à jour les Paramètres du projet. L’asset par défaut fourni n’est jamais écrasé.
- **Rétablir** recharge le fichier depuis le disque et abandonne les modifications non enregistrées.
- **Annuler** ferme sans enregistrer.

!!! tip "Tables de correspondance et script"
    Charger une **Table de correspondance des patients** peut aussi réécrire les opérandes Patient ID / date en `@lookup(...)`. Modifiez le script ensuite si vous avez besoin d’autres changements au niveau des balises.

### Table de correspondance des patients

Mapping CTP `.properties` optionnel des identifiants patients PHI vers des identifiants anonymisés et des décalages de date. Parcourir → prévisualiser → Accepter.

!!! note "Projets existants"
    Charger une table de correspondance **ne** ré-anonymise **pas** les fichiers déjà présents dans le jeu de données — ils restent inchangés. Les patients déjà importés continuent de fonctionner sans ligne dans la table. Les fichiers **nouveaux** dont l’identifiant patient PHI est absent de la table sont mis en quarantaine comme **Lookup_Miss** et ne sont pas stockés.

![Table de correspondance](shots/macos/LookupTable.png)

### Niveaux de journalisation

Augmentez la journalisation anonymizer / réseau lors du dépannage avec l’informatique.

![Niveaux de journalisation](shots/macos/LoggingLevels.png)

## Tableau de bord après création

![Tableau de bord](shots/macos/Dashboard.png)

Le Tableau de bord expose les principaux boutons de flux de travail : **Rechercher**, **Vue** et **Envoyer**.

## En cas d’échec

- Chemin de stockage non accessible en écriture → choisissez un autre dossier.
- Nom trop long → raccourcissez le nom du projet.
- Avertissement de clonage sur UID Root → utilisez une racine unique par projet pour éviter les collisions d’identifiants.
- L’éditeur de script **Accepter** a rejeté → corrigez les opérandes `@…` non pris en charge indiqués dans l’erreur (les littéraux sans `@`, comme de rares constantes CTP, sont autorisés).

## Prochaines étapes

Continuez avec [Rechercher](../06-search/) pour importer des études dans le projet.
