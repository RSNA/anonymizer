# Protocole de désidentification

Cette page résume en langage clair comment l’Anonymizer suit le DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)).

## Ce qui est supprimé ou remplacé

- Le nom et l’identifiant du patient deviennent des valeurs anonymisées limitées au projet (Site ID + numéro de patient séquentiel). La même personne conserve le même identifiant anonymisé d’une étude à l’autre dans le projet.
- Les UID sont remplacés par de nouvelles valeurs dérivées pour le projet (hachées à partir des originaux dans les versions actuelles) afin que les liens entre images restent cohérents sans exposer les UID sources.
- De nombreux tags de flux clinique et tags privés sont supprimés.
- Le fichier enregistre que l’identité du patient a été retirée et nomme le RSNA DICOM Anonymizer comme méthode.

## Dates

Les dates sont décalées par patient (offset basé sur un hash) pour que l’**ordre et l’espacement** des études d’un patient restent significatifs, sans que les dates calendaires soient les originales. L’heure de la journée est en général laissée telle quelle.

## Ce qui peut être conservé (options partielles)

Exemples de contexte clinique retenu (selon le script / les options de profil) :

- Descriptions d’étude et de série (vous pourrez plus tard standardiser les noms de série avec Harmoniser)
- Sexe, âge, taille, poids et caractéristiques similaires lorsque configurés
- Fabricant / modèle lorsque configurés

## Options pixel et visage dans le profil DICOM

Les options classiques du profil « clean pixel data » et « clean recognizable visual features » ne sont **pas** revendiquées comme bits de profil DICOM automatiques à elles seules. En V19, utilisez plutôt les Fonctions IA optionnelles :

- [Supprimer le texte incrusté](08-process/02-remove-burned-in-text)
- [Flouter les visages](08-process/04-blur-faces)

## Comptes rendus structurés et overlays

Les groupes courbe/overlay sont supprimés. L’acceptation des objets Structured Report est contrôlée par les paramètres de classe de stockage du projet.

!!! note "Pour la revue de conformité"
    Faites revoir le script d’anonymisation et les outils IA par votre responsable de la confidentialité pour votre établissement. Ce manuel est un guide opérationnel, pas un avis juridique.
