# Protocole de désidentification

Cette page résume en langage clair comment l’Anonymizer suit le DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)). La réponse formelle § E.1.3 pour les réviseurs est la [Déclaration de conformité DICOM](dicom-conformance-statement.md).

## HIPAA Safe Harbor et MIDI-B {#hipaa-safe-harbor-and-midi-b}

Les sites américains demandent souvent ce qu’il en est de **HIPAA Safe Harbor**. Cette règle est une **méthode de dé-identification** au titre de la Privacy Rule (supprimer les catégories d’identifiants listées, sans connaissance réelle de ré-identification)—pas une certification produit de HHS. L’Anonymizer ne prétend **pas** être « certifié HIPAA » ni « conforme Safe Harbor » en tant que logiciel.

Ce que nous revendiquons *bien* :

- Le chemin d’import par défaut met en œuvre les options de confidentialité DICOM PS 3.15 (Basic Profile et les options de rétention que vous sélectionnez).
- Ces options, ainsi que la clé de réponses / le scoreur officiel public **MIDI-B** utilisés dans les tests, sont conçus autour d’une suppression d’identifiants d’imagerie de type **Safe Harbor**, plus des pratiques de métadonnées de recherche de type TCIA.
- Le **décalage de dates** par défaut conserve l’espacement longitudinal (Modified Dates). Ce n’est **pas** la même chose que la règle Safe Harbor « année seule ». Les sites qui ont besoin de l’année seule (ou d’Expert Determination) doivent fixer la politique avec leur responsable de la confidentialité.
- Le texte dans les pixels, la prose des comptes rendus et les visages nécessitent toujours les étapes IA / Revue de texte de rapport optionnelles lorsque ces objets sont présents.

Utilisez les scores MIDI-B et ce protocole comme **éléments de preuve pour la revue**, pas comme substitut à la détermination institutionnelle.

## Ce qui est supprimé ou remplacé

- Le nom et l’identifiant du patient deviennent des valeurs anonymisées limitées au projet (Site ID + numéro de patient séquentiel). La même personne conserve le même identifiant anonymisé d’une étude à l’autre dans le projet.
- Les UID sont remplacés par de nouvelles valeurs déterministes dérivées pour le projet afin que les liens entre images restent cohérents. Ces hachages sont **sans secret** (liaison stable dans le projet, pas une pseudonymisation à clé) — voir [Remplacements déterministes](#deterministic-replacements-uids-dates-accessions).
- De nombreux tags de flux clinique et tags privés sont supprimés.
- Le fichier enregistre que l’identité du patient a été retirée et nomme le RSNA DICOM Anonymizer comme méthode.

## Dates

Les dates sont décalées par patient (offset basé sur un hash) pour que l’**ordre et l’espacement** des études d’un patient restent significatifs, sans que les dates calendaires soient les originales. L’heure de la journée est en général laissée telle quelle.

## Ce qui peut être conservé (options partielles)

Exemples de contexte clinique retenu (selon le script / les options de profil) :

- Descriptions d’étude et de série (vous pourrez plus tard standardiser les noms de série avec Harmoniser)
- Sexe, âge, taille, poids et caractéristiques similaires lorsque configurés
- Fabricant / modèle lorsque configurés

## Remplacements déterministes (UID, dates, accessions) {#deterministic-replacements-uids-dates-accessions}

Ces transformations sont **intentionnelles** et **sans secret**. Leur rôle est une **liaison stable au sein d’un projet** (et une ligne correspondante dans les tables PHI/UID du projet) — pas une déliaison à clé face à quelqu’un qui connaît déjà une valeur originale candidate.

| Valeur | Comment elle est dérivée | Ce que cela signifie |
| --- | --- | --- |
| **UID DICOM** | Préfixe projet (`uid_root` + id de site) + MD5 tronqué de l’UID d’origine | Même origine → même UID anon. Quiconque peut **deviner** un UID d’origine peut calculer le remplacement et comparer. On ne peut pas utilement **inverser** un UID anon vers une origine inconnue à partir du seul fichier anonymisé. |
| **Dates (`@hashdate`)** | Décalage en jours depuis le MD5 de l’identifiant patient (mod ~10 ans) | Même patient → même décalage ; les intervalles entre les examens de ce patient restent significatifs. |
| **Numéro d’accession** | SHA-256 d’un **mélangeur de projet** (`site_id` / `uid_root`) plus l’accession d’origine | Des projets différents produisent des hachages différents pour la même accession (utile). Le mélangeur n’est **pas** une clé secrète : l’id de site et la racine UID apparaissent dans les UID anonymisés publiés, donc quelqu’un qui détient des données publiées peut le reconstruire et vérifier des accessions devinées. |

**Non revendiqué :** résistance cryptographique à la vérification en ligne lorsque l’attaquant a déjà un UID, un identifiant patient ou une accession d’origine plausibles. C’est attendu pour des constructions publiques et déterministes, et courant parmi les désidentificateurs DICOM ouverts.

**Revendiqué :** les originaux ne sont pas stockés dans le DICOM publié ; la carte faisant autorité vit dans la base privée du projet — gardez cette base hors des paquets d’export/envoi.

## Options pixel et visage dans le profil DICOM {#pixel-and-face-options-in-the-dicom-profile}

Les options classiques du profil « clean pixel data » et « clean recognizable visual features » ne sont **pas** revendiquées comme bits de profil DICOM automatiques à elles seules. En V19, utilisez plutôt les Fonctions IA optionnelles :

- [Supprimer le texte incrusté](08-process/02-remove-burned-in-text/index.md)
- [Flouter les visages](08-process/04-blur-faces/index.md)

## Comptes rendus structurés et overlays

Les groupes courbe/overlay sont supprimés. L’acceptation des objets Structured Report est contrôlée par les paramètres de classe de stockage du projet.

!!! note "Pour la revue de conformité"
    Faites revoir les [options de dé-identification](05-create-project/index.md#2-de-identification-options) et toute [modification personnalisée du script](05-create-project/anonymizer-script.md#4-custom-script-edits), ainsi que les outils IA, par votre responsable de la confidentialité pour votre établissement. Voir aussi la [Déclaration de conformité DICOM](dicom-conformance-statement.md) et [HIPAA Safe Harbor et MIDI-B](#hipaa-safe-harbor-and-midi-b). Ce manuel est un guide opérationnel, pas un avis juridique.
