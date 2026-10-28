# Déclaration de conformité DICOM

Cette page est la réponse du produit aux [exigences de conformité DICOM PS 3.15 § E.1.3](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/sect_E.1.3.html) pour les applications qui revendiquent le **Basic Application Level Confidentiality Profile**.

Elle s’adresse aux responsables de la confidentialité et aux réviseurs. Le flux opérationnel quotidien est dans le [Protocole de désidentification](deidentification-protocol.md) et sous [Créer un projet](05-create-project/index.md#2-de-identification-options).

!!! note "Portée de cette revendication"
    La conformité signifie ici que le **chemin d’import** met en œuvre le Basic Profile (et les options de l’Annexe E sélectionnées) en appliquant le script d’anonymisation du projet aux attributs DICOM. Le nettoyage optionnel des pixels, comptes rendus, descripteurs et visages s’exécute **après** l’import lorsque ces options et fonctions IA sont activées. Cette déclaration n’est pas un avis juridique ni une certification HIPAA du produit — voir [HIPAA Safe Harbor et MIDI-B](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b).

## Profil et options revendiqués

| Élément | Revendication |
| --- | --- |
| Profil | **Basic Application Level Confidentiality Profile** (code CID 7050 113100) |
| Catalogue d’attributs | [PS 3.15 Table E.1-1](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) — l’extrait empaqueté `e1_1_retain_tags.json` pilote les overlays d’options de rétention à la compilation |
| Tampons de méthode | `(0012,0062) Patient Identity Removed = YES`; `(0012,0063) Deidentification Method = RSNA DICOM ANONYMIZER`; codes d’option sélectionnés dans `(0012,0064) Deidentification Method Code Sequence` |
| Règles faisant autorité par projet | Script compilé `{site_id}-anonymizer.script` à côté de `ProjectModel.json` (depuis `default-anonymizer.script` empaqueté plus overlays, ou un script personnalisé importé) |

## Checklist E.1.3

### Quels attributs sont supprimés pendant la protection

Sous le **Basic Profile** à l’import (script empaqueté par défaut, sauf si une option de rétention ou une édition personnalisée les conserve) :

- **Toutes les balises privées** (sauf **Retain Safe Private** — chaque élément privé est alors résolu via la base de connaissances des balises privées TCIA ; les slots inconnus sont supprimés).
- **Groupes courbe et overlay**.
- Attributs que Table E.1-1 marque pour suppression ou vidage sous Basic et que le script du projet met en œuvre avec `@remove()`, `@empty()` ou équivalent (date de naissance, noms de médecins, identité d’institution, identité d’appareil, caractéristiques patient et de nombreux identifiants de flux clinique).
- **Encrypted Attributes** et balises de chiffrement associées — **supprimés**, non renseignés.
- UID de signature numérique et éléments de signature associés — **supprimés**.

La liste **complète** supprimer/conserver/transformer d’un projet est le script d’anonymisation compilé (éditeur de script). Les options de rétention modifient les overlays comme dans [Options de dé-identification](05-create-project/index.md#2-de-identification-options). Les éditions personnalisées prévalent jusqu’à ré-acceptation des options (recompilation depuis le défaut empaqueté et **perte** des éditions personnalisées).

### Quels attributs sont remplacés par des valeurs fictives et comment elles sont générées

| Classe d’attribut | Génération des valeurs de remplacement |
| --- | --- |
| **Patient Name / Patient ID** | Site ID plus un numéro de patient séquentiel stable pour cette personne **dans ce projet**. |
| **Accession Number** | Hachage déterministe d’un mélangeur projet (`site_id` / `uid_root`) plus l’accession d’origine. |
| **UID DICOM** (Study, Series, SOP Instance, Frame of Reference et autres règles `@uid`) | Préfixe projet (`uid_root` + site id) + MD5 tronqué de l’UID d’origine — même origine → même remplacement **dans le projet**. |
| **Dates / DateTimes** | Stratégie par patient ou essai : `@hashdate` par défaut ; ou `@lookup`, `@incrementdate`, `@rebasedate`. L’heure de la journée est en général inchangée. Voir [Dates](deidentification-protocol.md#dates). |
| **Patient Age** | Arrondi à une bande de cinq ans (`@round`) même avec **Retain Patient Characteristics**. |
| **Autres vidages Basic** | `@empty()` ou littéraux fixes selon le script. |

Détails : [Remplacements déterministes](deidentification-protocol.md#deterministic-replacements-uids-dates-accessions).

**Retain UIDs** conserve les UID d’origine. **Full Dates** conserve les dates calendaires d’origine.

### Encrypted Attributes Data Sets (ré-identification)

**Non pris en charge.** L’Anonymizer ne place **pas** les originaux dans un Encrypted Attributes Data Set pour ré-identification ultérieure et ne sélectionne **pas** de clés de chiffrement à cette fin.

- Le script par défaut **supprime** Encrypted Attributes Sequence / Encrypted Content / balises associées du groupe 0400 si présentes.
- La carte original↔anonyme faisant autorité vit dans la **base privée du projet** — à exclure des paquets d’export/Envoi.

### Portée de l’intégrité référentielle des valeurs de remplacement

| Portée | Comportement |
| --- | --- |
| **Au sein d’un projet** | Même Patient ID, Accession ou UID d’origine → même valeur anonymisée pour chaque SOP Instance du projet. |
| **Frame of Reference et UID associés** | Règles `@uid` remappées de façon cohérente si Retain UIDs est désactivé. Certaines séquences RT/référence sont supprimées sous Basic. |
| **Retraitement de la même Study** | Ré-import dans le **même** projet réutilise les maps PHI/UID stockées. Recompiler les options **ne** réécrit **pas** les fichiers déjà stockés. |
| **Entre projets** | **Non** garanti. |
| **Entre sites avec seulement le DICOM publié** | Remplacements **sans secret** ; voir les réserves sur les remplacements déterministes. |

### Quels attributs et valeurs sont insérés pendant la protection

| Tag | Valeur / comportement |
| --- | --- |
| `(0012,0062) Patient Identity Removed` | `YES` (créé via `@always()` si absent) |
| `(0012,0063) Deidentification Method` | `RSNA DICOM ANONYMIZER` |
| `(0012,0064) Deidentification Method Code Sequence` | Un item DCM par code d’option **exécuté** |
| `(0028,0303) Longitudinal Temporal Information Modified` | `MODIFIED` lorsqu’une stratégie de décalage de dates s’exécute |
| `(0012,0052)` / `(0012,0053)` (chemin rebase) | Offset From Event et Event Type `REGISTRATION` avec `@rebasedate` |

Les règles `@always()…` peuvent aussi **créer** des éléments non séquence absents avec un littéral fixe.

### Transfer Syntaxes pour Encrypted Attributes Data Set

**Non applicable.** Aucun Encrypted Attributes Data Set n’est créé.

### Quelles options sont prises en charge

| Option (CID 7050) | Prise en charge ? | Quand |
| --- | --- | --- |
| Basic Application Confidentiality Profile (113100) | **Oui** (toujours) | Import |
| Clean Pixel Data (113101) | **Oui** | Après import — Embedded PHI (modèles requis) |
| Clean Recognizable Visual Features (113102) | **Oui** | Après import — Flouter les visages (modèles requis) |
| Clean Graphics (113103) | **Sélectionnable seulement** | Intention seulement — voir la note ci-dessous |
| Clean Structured Content (113104) | **Oui** | Après import — Revue de texte de rapport / AI Batch |
| Clean Descriptors (113105) | **Oui** | Après import — texte de métadonnées |
| Retain Longitudinal Temporal Information Full Dates (113106) | **Oui** | Import (exclusif avec Modified Dates) |
| Retain Longitudinal Temporal Information Modified Dates (113107) | **Oui** | Import (préréglage Retain) |
| Retain Patient Characteristics (113108) | **Oui** | Import |
| Retain Device Identity (113109) | **Oui** | Import |
| Retain UIDs (113110) | **Oui** | Import |
| Retain Safe Private (113111) | **Oui** | Import (KB TCIA) |
| Retain Institution Identity (113112) | **Oui** | Import |

Préréglages et UI : [Créer un projet — Options de dé-identification](05-create-project/index.md#2-de-identification-options). Significations : [Protocole de désidentification](deidentification-protocol.md).

!!! note "Pourquoi Clean Graphics n’est pas exécuté"
    L’option DICOM **Clean Graphics** vise les graphiques incrustés **non textuels** dans les pixels (logos, règles, marques décoratives) au-delà des groupes courbe/overlay habituels. Sous le Basic Profile, ce produit **supprime déjà les groupes courbe et overlay** à l’import. Les graphiques incrustés non textuels restants sont rares dans les archives de recherche clinique modernes (la plupart du PHI pixel résiduel est du **texte**, traité par Clean Pixel Data / Embedded PHI). Un détecteur/nettoyeur séparé pour ce cas legacy n’a pas été priorisé ; sélectionner Clean Graphics n’enregistre que l’intention du projet et **n’exécute ni ne tamponne** aucune tâche de traitement.

### Restrictions supplémentaires

- **Pas de chemin Encrypted Attributes / clé publique** — aucune taille de clé ni suite cryptographique revendiquée.
- Les options **Clean\*** exigent des fonctions IA installées.
- Des **scripts CTP personnalisés** peuvent être importés ; opérandes inconnus refusés ; les règles de date doivent correspondre à Study Date.
- **Ré-accepter les options** recompile et **abandonne** les éditions de script personnalisées ; les instances déjà importées ne sont pas ré-anonymisées.
- Les scores **MIDI-B** sont des éléments de preuve pour la revue d’en-tête, pas un substitut à la détermination institutionnelle ([protocole](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b)).

!!! note "Pour la revue de conformité"
    Faites revoir cette déclaration avec les [options de dé-identification](05-create-project/index.md#2-de-identification-options), le script compilé et toute [modification personnalisée du script](05-create-project/index.md#4-custom-script-edits). Ce manuel est une documentation opérationnelle et normative, pas un avis juridique.
