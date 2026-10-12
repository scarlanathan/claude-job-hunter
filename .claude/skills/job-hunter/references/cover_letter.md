# Rédiger une lettre de motivation adaptée

## Principes
- **250 à 350 mots**, une page, en français sauf si l'offre est en anglais (alors en anglais).
- Spécifique : au moins 2 éléments tirés de l'offre (missions, stack, produit, valeurs) et
  2 preuves tirées du CV (résultats chiffrés quand le CV en contient).
- Si `documents.cover_letter_base` existe, reprends son ton et sa structure, pas ses phrases.
- Aucun fait inventé, aucune compétence absente du profil. Un manque évident (ex. 5 ans demandés,
  3 ans d'expérience) se traite en mettant en avant ce qui compense, sans mentir.
- Bannir les formules creuses : « Je me permets de… », « dynamique et motivé », « votre
  entreprise leader ». Pas de répétition du CV ligne à ligne.

## Structure
```
Prénom Nom
Ville · téléphone · email · LinkedIn

> <Entreprise>
> <Ville>, le <date du jour>

Objet : Candidature au poste de <intitulé exact> (réf. <si fournie>)

Madame, Monsieur,            ← ou « Madame X, » si le recruteur est nommé

§1 Accroche (2-3 phrases) : le poste, et pourquoi CETTE entreprise (un fait précis de l'offre
   ou du site).
§2 Vous → moi (4-6 phrases) : 2-3 besoins clés de l'offre, chacun relié à une expérience ou un
   résultat concret du CV.
§3 Ce que j'apporte de plus / envie (2-3 phrases) : soft skill démontrée, projet, langue,
   disponibilité.
§4 Conclusion (1-2 phrases) : disponibilité pour un échange.

Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.
Prénom Nom
```
Les lignes préfixées par `> ` forment un bloc aligné à droite dans le PDF (`make_letter_pdf.py`).

Pour une start-up ou une offre au ton informel, une formule finale plus simple
(« Au plaisir d'échanger avec vous, ») est acceptable.

## Version courte pour un email
Quand la candidature part par email, le corps de l'email est une lettre condensée (5-8 lignes)
et la lettre complète est jointe en PDF si `cover_letter` vaut `always` ou si l'offre la demande.

## Champ « Pourquoi nous rejoindre ? » des formulaires
3-5 phrases, mêmes règles : un fait sur l'entreprise + une preuve du CV + la motivation.

## Contrôle des faits (obligatoire)
Avant de montrer la lettre, dresse pour toi la liste de chaque affirmation factuelle (poste occupé,
durée, outil, résultat chiffré, diplôme, langue) avec sa source exacte dans `profile.json`
(ex. `experiences[1].highlights[0]`). Une affirmation sans source est supprimée ou reformulée,
jamais conservée « parce qu'elle sonne bien ». Si l'utilisateur demande à voir le contrôle,
montre-lui ce tableau.

## Contrôle avant de montrer à l'utilisateur
- [ ] Nom de l'entreprise et intitulé du poste exacts (pas d'autre entreprise laissée par erreur)
- [ ] Contrôle des faits fait : chaque affirmation a sa source dans le CV / profile.json
- [ ] Longueur respectée, orthographe vérifiée
- [ ] Date du jour, coordonnées correctes
