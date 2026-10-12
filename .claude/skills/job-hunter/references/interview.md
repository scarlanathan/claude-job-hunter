# Préparer un entretien et assurer la suite

Quand une candidature passe au statut `entretien`.

## Fiche de préparation

Enregistre-la dans `letters/<ID>-entretien.md` et montre-la à l'utilisateur. Une page, pas plus.

1. **Logistique** : date, heure, format (visio, téléphone, sur place + adresse), interlocuteurs
   et leur rôle s'ils sont connus. Propose de créer l'événement dans l'agenda (connecteur
   Google Calendar ou Outlook) s'il n'existe pas.
2. **L'entreprise en 5 lignes** (WebSearch / WebFetch sur le site et l'actualité récente) :
   activité, taille, actualité des 12 derniers mois, produit ou équipe concernée. Cite les sources.
3. **L'offre décodée** : les 3-4 besoins principaux, avec pour chacun l'expérience du CV qui y
   répond (même règle que la lettre : chaque exemple vient de `profile.json`).
4. **Questions probables + pistes de réponse** (6-8) : présentation en 2 minutes, motivation pour
   ce poste, une question par besoin clé (format STAR : situation, tâche, action, résultat, à
   partir des `highlights` du profil), et le point faible prévisible de la candidature (score
   et `score_reason` dans le suivi) avec une façon honnête d'y répondre.
5. **Questions à poser** (3-4) : sur l'équipe, les priorités des premiers mois, la suite du
   processus. Pas de question dont la réponse est sur le site.
6. **Salaire** : la valeur de `standard_answers.salary_expectation` si elle existe ; sinon,
   demande à l'utilisateur avant l'entretien. N'invente jamais de fourchette à sa place.

`python tracker.py note ID "Entretien RH le 14/10 14h, visio, avec Mme X"` pour garder la trace.

## Après l'entretien

- **Remerciement** (le jour même ou le lendemain) : `templates/remerciement.txt`, adapté avec un
  point précis abordé pendant l'échange : demande-le à l'utilisateur, ne le devine pas. Envoi
  comme une candidature (aperçu puis validation). Si la candidature d'origine est partie par
  email, utilise `send_email.py --followup` sur la même offre uniquement si le statut est encore
  `envoyee` ; sinon, connecteur Gmail / Outlook (réponse dans le fil).
- Note le compte rendu : `tracker.py note ID "..."` (impressions, prochaines étapes, délai annoncé).
- Pas de réponse au-delà du délai annoncé + 3 jours ouvrés : propose une relance courte.
- Issue : `tracker.py status ID offre` ou `refusee`. En cas de refus après entretien, propose un
  court message demandant un retour : c'est souvent la seule source d'information utile.
