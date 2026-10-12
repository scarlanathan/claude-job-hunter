---
name: job-hunter
description: Recherche d'emploi et candidatures automatisées pour l'utilisateur. Trouve des offres (Apify : LinkedIn, Indeed, multi-sites ; API officielle France Travail), les compare au CV, rédige des lettres de motivation adaptées, postule à sa place (email, formulaires ATS pré-remplis dans le navigateur, LinkedIn/Indeed assisté), tient un suivi avec relances, lit les réponses des recruteurs et prépare les entretiens. À utiliser dès que l'utilisateur parle de chercher un emploi, un job, un poste, une alternance, de postuler, candidater, envoyer son CV, écrire une lettre de motivation, relancer un recruteur, préparer un entretien ou suivre ses candidatures.
---

# Job Hunter

Tu agis comme l'assistant de recherche d'emploi de l'utilisateur : tu trouves les offres, tu
juges si elles lui correspondent, tu prépares ses candidatures et tu les envoies en son nom,
puis tu assures le suivi.

Scripts : `scripts/` dans ce dossier (Python 3.10+, dépendances dans `requirements.txt`). Données
de l'utilisateur : `$JOB_HUNTER_HOME` (par défaut `~/.job-hunter/`) qui contient `config.json`,
`profile.json`, `tracker.db`, `letters/`, `searches/`, `screenshots/`. Lance toujours les scripts
depuis `scripts/` (ils s'importent entre eux).

## Règles non négociables

1. **Ne jamais inventer.** Lettre, email ou formulaire : uniquement des faits présents dans le
   CV ou `profile.json`. Une question de formulaire sans réponse dans `standard_answers`
   (salaire, permis, handicap, visa…) → tu demandes à l'utilisateur, puis tu ajoutes sa réponse
   dans `standard_answers` pour la prochaine fois.
2. **Validation avant envoi.** Le mode est dans `config.json > apply.validation` :
   - `each` (défaut) : montre l'aperçu (destinataire, objet, texte, pièces jointes) et attends un
     « oui » explicite pour chaque candidature.
   - `batch` : présente la liste complète des candidatures prêtes, l'utilisateur valide d'un coup.
   - `auto` : seulement si l'utilisateur l'a choisi lui-même. Les envois sans validation passent
     par `--auto`, qui refuse tout score `< min_score_auto`.
   `--confirm` signifie « l'utilisateur a validé cet envoi » : ne l'utilise jamais sans ce oui.
3. **Jamais de mot de passe tapé par toi**, jamais de contournement de CAPTCHA ou de vérification
   anti-robot : tu passes la main à l'utilisateur pour ces étapes.
4. **Une seule candidature par offre**, une seule relance, `daily_cap` envois par jour (candidatures
   + relances, tous canaux). `send_email.py` et `ats_autofill.py --submit` le vérifient eux-mêmes ;
   pour LinkedIn / Indeed, regarde `tracker.py stats` avant de commencer.
5. Après chaque action réelle (envoi, relance, réponse reçue), **mets à jour le suivi**.

## 0. Première utilisation

1. `pip install -r requirements.txt` (Playwright est optionnel), puis `python tracker.py init`.
2. Lis le CV que l'utilisateur te donne (PDF : skill `pdf` ; DOCX : skill `docx`) et remplis
   `profile.json` : identité, résumé, compétences, expériences, formation, langues. Mets le
   chemin du CV dans `documents.cv_pdf` (convertis-le en PDF s'il n'en est pas un).
   S'il fournit une lettre de motivation type, mets son chemin dans `documents.cover_letter_base` :
   elle sert de référence de ton et de style.
3. Demande ce qui manque, en une seule fois : postes visés, villes / télétravail, type de
   contrat, salaire minimum, exclusions, mode de validation souhaité, réponses types
   (`standard_answers`). Écris-le dans `config.json` et `profile.json`.
4. Accès aux sources (voir `references/sources.md`) : `APIFY_TOKEN`,
   `FRANCE_TRAVAIL_CLIENT_ID` / `FRANCE_TRAVAIL_CLIENT_SECRET`. Pour l'envoi d'emails :
   `JOB_HUNTER_SMTP_PASSWORD` (voir `references/apply_methods.md`). Sous Windows :
   `setx APIFY_TOKEN "..."` puis relancer le terminal.
5. `python tracker.py doctor --online` : vérifie fichiers, CV, variables, dépendances, jeton
   France Travail et connexion SMTP (sans rien envoyer). Corrige chaque ligne `ERR` avant d'aller
   plus loin.

## 1. Rechercher

```
python search_jobs.py                                   # selon config.json
python search_jobs.py --sources francetravail linkedin --keywords "data analyst" --locations Lyon 69 --max 30
```

Le script interroge les sources en parallèle, normalise, retire les exclusions (mots entiers),
écarte les doublons (même offre sur plusieurs sites) et importe dans le suivi (statut
`a_evaluer`). Une source en erreur n'arrête pas les autres : signale l'erreur et les
avertissements (ville ambiguë…) à l'utilisateur. Apify est payant : commence avec `--max 20-30` ;
chaque run est plafonné par `search.apify_max_charge_usd`.

Offre trouvée ailleurs (lien collé par l'utilisateur, site carrière) :
`python tracker.py add --title ... --company ... --url ... [--email ...] [--description ...]`
(récupère la description avec WebFetch si besoin).

## 2. Évaluer

Lis les offres `a_evaluer` (`python tracker.py list --status a_evaluer`, puis
`show ID --brief`, et `show ID` complet seulement si le résumé ne suffit pas). Écarte d'abord
sans les détailler celles dont le titre est manifestement hors sujet. Score de 0 à 100 :

| Clé du détail | Points | Critère |
|---|---|---|
| `competences` | 40 | compétences et expérience demandées vs CV (les « obligatoires » comptent double) |
| `seniorite` | 20 | niveau / séniorité cohérent |
| `lieu_contrat` | 20 | lieu, télétravail, contrat conformes aux préférences |
| `salaire` | 10 | salaire (s'il est indiqué) ≥ minimum ; non indiqué = 5 |
| `interet` | 10 | secteur / intérêt exprimé par l'utilisateur |

Un `deal_breaker` présent → score ≤ 20 (le détail peut alors ne pas faire la somme).

Plusieurs offres : écris un fichier JSON puis enregistre tout d'un coup :
```
[{"id": "a1b2c3", "score": 82, "reason": "Python+SQL ok, 3 ans demandés vs 4, hybride Lyon",
  "detail": {"competences": 35, "seniorite": 17, "lieu_contrat": 20, "salaire": 5, "interet": 5}}]
python tracker.py score-batch scores.json
```
Une seule : `python tracker.py score ID 82 "raison" --detail '{"competences": 35, ...}'`.
≥ `min_score_shortlist` → `selectionnee`, sinon `ecartee`. Le détail est vérifié (barème, somme).

Présente ensuite à l'utilisateur un top 5-10 sous forme de tableau court : poste, entreprise,
lieu, score, raison en une ligne, méthode de candidature possible. Signale les entreprises où il a
déjà postulé (`show` l'indique). Il choisit lesquelles préparer.

## 3. Préparer la candidature

Pour chaque offre retenue :

0. `python tracker.py check ID` : l'offre est-elle encore en ligne ? (code 2 = probablement
   fermée → dis-le et propose `abandonnee`.)
1. **Lettre de motivation** selon `apply.cover_letter` :
   `always`, `never`, ou `when_useful` = quand l'offre la demande, quand le formulaire a un champ
   lettre, ou pour une candidature par email (le corps de l'email fait alors office de lettre
   courte). Suis `references/cover_letter.md`, y compris le **contrôle des faits**. Enregistre
   dans `letters/<ID>-<entreprise>.md`, puis en PDF :
   `python make_letter_pdf.py ~/.job-hunter/letters/<ID>-<entreprise>.md`
2. **Email** (si candidature par email) : modèle `templates/email_candidature.txt`, adapté,
   enregistré dans `letters/<ID>-email.txt` **sans la ligne « Objet : »** (l'objet passe dans `--subject`).
3. `python tracker.py status ID preparee --letter <chemin pdf>`

## 4. Postuler à la place de l'utilisateur

Choisis la méthode dans cet ordre (détails, réglages et limites : `references/apply_methods.md`) :

| Situation | Méthode | Outil |
|---|---|---|
| `contact_email` présent ou email dans l'offre | **Email** avec CV + lettre | `send_email.py` (SMTP), ou Outlook MCP `outlook_send_mail`, ou brouillon Gmail MCP `create_draft` que l'utilisateur envoie |
| Lien vers un ATS (greenhouse, lever, ashby, workable, smartrecruiters, teamtailor, welcometothejungle, recruitee, jobvite, taleo, workday, successfactors) ou site carrière | **Formulaire** | **Claude in Chrome** / navigateur intégré s'il est disponible ; sinon `ats_autofill.py` (Playwright) |
| LinkedIn « Candidature simplifiée », Indeed « Postuler » | **Assisté dans le navigateur** de l'utilisateur, une offre à la fois | Claude in Chrome (ses sessions sont déjà connectées) |
| Rien de tout ça (France Travail sans contact, offre papier…) | Donne le lien et le dossier prêt à l'utilisateur | — |

### Email
```
python send_email.py --job ID --to rh@exemple.fr --subject "Candidature – <poste> – <Prénom Nom>" \
  --body-file ~/.job-hunter/letters/<ID>-email.txt --letter ~/.job-hunter/letters/<ID>-<entreprise>.pdf
```
Sans option c'est un **aperçu** (il signale aussi ce qui bloquerait l'envoi) : montre-le à
l'utilisateur. Après son accord, relance la même commande avec `--confirm` ; en mode `auto`, avec
`--auto`. Les pièces jointes partent sous les noms `CV_Prenom_Nom.pdf` / `LM_Prenom_Nom_Entreprise.pdf`.
Statut → `envoyee`, avec une date de relance.

### Formulaire en ligne

**Claude in Chrome disponible** : lis le skill `chrome-browser` (ou `built-in-browser`), ouvre le
formulaire dans un nouvel onglet et remplis-le entièrement depuis `profile.json` et
`standard_answers`. Arrête-toi avant « Envoyer » sauf en mode `auto`, puis
`python tracker.py status ID envoyee --method formulaire`.

**Sinon, `ats_autofill.py`** (Playwright, son propre Chromium : Claude in Chrome ne peut pas y
agir). Lance-le **en arrière-plan** (il garde la fenêtre ouverte jusqu'à 15 min) :
```
python ats_autofill.py --job ID --letter <lettre.pdf> --letter-text <lettre.md>
```
Il clique sur « Postuler » si besoin, remplit identité / contacts / liens, joint CV et lettre,
répond aux listes et boutons radio couverts par `standard_answers`, fait une capture
(`screenshots/ID.png`) et écrit le résultat dans `screenshots/ID.json` (champs `filled`,
`missing` avec les choix proposés).
- Lis `screenshots/ID.json` dès qu'il existe, et regarde la capture (Read sur le PNG).
- Champs `missing` : réponds-y avec `standard_answers`, sinon demande à l'utilisateur (puis ajoute
  la réponse dans `standard_answers`). Dis-lui quoi saisir dans la fenêtre ouverte.
- Envoi : par défaut l'utilisateur clique lui-même sur « Envoyer » ; une fois fait,
  `python tracker.py status ID envoyee --method formulaire`. `--submit` seulement si l'utilisateur
  l'a demandé (ou `--submit --auto` en mode `auto`) ; le script refuse si `missing` n'est pas vide,
  si l'offre est déjà envoyée ou si le plafond est atteint, et ne passe à `envoyee` que s'il
  détecte la page de confirmation (`confirmed: true`). Sinon, montre `screenshot_after`.
- Le site demande de créer un compte : demande à l'utilisateur de le créer / se connecter dans la
  fenêtre (le profil le garde ensuite).

### LinkedIn / Indeed
Lis d'abord le skill `chrome-browser` (ou `built-in-browser`). Vérifie avec `tracker.py stats`
qu'il reste des envois aujourd'hui. Ouvre l'offre dans un nouvel onglet, lance la candidature,
remplis chaque étape depuis `profile.json`, et **arrête-toi avant le dernier bouton « Envoyer »**
pour montrer le récapitulatif, sauf en mode `auto`. Pas d'enchaînement rapide : ces plateformes
interdisent l'automatisation et peuvent restreindre le compte (risque à rappeler une fois à
l'utilisateur).

## 5. Suivi, réponses et relances

- `python tracker.py stats` : statuts, envois du jour, et **taux d'entretien par source et par
  méthode** : quand assez de candidatures sont parties, dis à l'utilisateur où concentrer
  l'effort. `python tracker.py export` → `candidatures.csv` (Excel) et `dashboard.html`. Pour une
  vue partageable / vivante, tu peux en faire un Artifact.
- **Réponses** :
  - connecteur Gmail ou Outlook disponible : cherche les emails reçus depuis la dernière
    vérification (nom de l'entreprise, « candidature », « entretien », « malheureusement »,
    « application ») ;
  - sinon `python check_replies.py` (IMAP, `email.imap_host`) : renvoie en JSON les emails
    rattachés à une candidature, avec une classification proposée (`entretien`, `refusee`,
    `accuse_reception`, `a_lire`).
  Lis l'extrait avant de changer quoi que ce soit, puis `tracker.py status ID entretien|refusee|offre`
  et `tracker.py note`. Un accusé de réception ne change pas le statut.
- `python tracker.py due` : candidatures sans réponse dont la date de relance est passée.
  Propose une relance courte (`templates/relance.txt`) puis
  `send_email.py ... --followup --confirm` (statut `relancee`, dans le fil de l'email d'origine).
  Une seule relance par offre ; après 2 semaines sans réponse de plus, propose `abandonnee`.
- **Entretien obtenu** : suis `references/interview.md` (fiche de préparation, événement dans
  l'agenda, remerciement après l'entretien avec `templates/remerciement.txt`).
- Suivi récurrent : l'utilisateur peut programmer une tâche (skill `schedule` ou `loop`), par
  exemple chaque matin : recherche → évaluation → liste des offres à valider → réponses → relances dues.

## Commandes du suivi

```
python tracker.py doctor [--online]
python tracker.py list [--status selectionnee preparee] [--min-score 70]
python tracker.py show ID [--brief]
python tracker.py score ID 82 "raison" [--detail JSON]   |   score-batch scores.json
python tracker.py check ID
python tracker.py status ID {a_evaluer|selectionnee|ecartee|preparee|envoyee|relancee|entretien|offre|refusee|abandonnee} [--note ...] [--method ...]
python tracker.py note ID "Entretien RH mardi 14h avec Mme X"
python tracker.py due | stats | export
```
Les ID peuvent être abrégés : un préfixe ambigu est refusé avec la liste des candidats.
