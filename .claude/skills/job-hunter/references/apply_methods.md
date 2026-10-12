# Comment l'IA postule à la place de l'utilisateur

Il n'existe pas d'API publique « postuler » chez LinkedIn, Indeed ou les ATS : leurs API de
candidature (Greenhouse, Lever…) exigent la clé de l'**employeur**. L'IA postule donc comme un
humain : par email, ou en remplissant le formulaire dans un navigateur. Quatre méthodes, de la
plus fiable à la plus risquée.

## 1. Email (le plus fiable, 100 % automatisable)

Quand une offre donne une adresse (France Travail, PME, cabinets, sites carrière), l'email avec
CV + lettre en PDF est la meilleure option.

### a) SMTP via `send_email.py` (envoi réellement autonome)
- **Gmail** : active la validation en 2 étapes, puis crée un *mot de passe d'application* sur
  https://myaccount.google.com/apppasswords. `smtp.gmail.com`, port `465`.
- **Outlook/Hotmail** : `smtp-mail.outlook.com`, port `587` (Microsoft désactive progressivement
  l'authentification par mot de passe ; si ça échoue, utilise la méthode b).
- **OVH / autres** : voir les réglages SMTP de ton hébergeur.
- `setx JOB_HUNTER_SMTP_PASSWORD "xxxx xxxx xxxx xxxx"`.
- Les emails partent depuis ta vraie boîte et apparaissent dans « Envoyés » : les réponses
  arrivent normalement.

### b) Connecteurs Claude
- **Outlook (Microsoft 365)** : `outlook_send_mail` envoie directement (pièces jointes selon le
  connecteur ; sinon `outlook_create_draft` puis l'utilisateur joint le CV).
- **Gmail** : le connecteur crée des **brouillons** (`create_draft`) : l'utilisateur n'a qu'à
  ouvrir et cliquer « Envoyer ». Bon compromis si tu ne veux pas de mot de passe d'application.
- Ces connecteurs servent aussi à **lire les réponses** pour mettre le suivi à jour.

Garde-fous appliqués par `send_email.py` lui-même : refus si l'offre a déjà été envoyée, si une
relance a déjà été faite, ou si le plafond quotidien (candidatures + relances, tous canaux) est
atteint. `--confirm` = l'utilisateur a validé ; `--auto` = envoi sans validation, accepté seulement
si `apply.validation` vaut `auto` et si le score atteint `min_score_auto`.
Les pièces jointes partent sous le nom `CV_Prenom_Nom.pdf` / `LM_Prenom_Nom_Entreprise.pdf`, et une
relance répond dans le fil de l'email d'origine.

Bonnes pratiques : objet clair (« Candidature – Poste – Prénom Nom »), corps court (5-8 lignes),
PDF nommés `CV_Prenom_Nom.pdf` / `LM_Prenom_Nom_Entreprise.pdf`, pas plus de ~20 envois par jour
depuis une boîte perso (au-delà, risque de passer en spam).

## 2. Formulaires ATS pré-remplis (`ats_autofill.py`)

La majorité des offres des entreprises renvoient vers un ATS : Greenhouse, Lever, Ashby,
Workable, SmartRecruiters, Teamtailor, Recruitee, Welcome to the Jungle, Workday, Taleo,
SuccessFactors.

```
pip install playwright
python -m playwright install chromium
python ats_autofill.py --job ID --letter lettre.pdf --letter-text lettre.md
```

- Navigateur **visible**, profil persistant : tu te connectes une fois (Workday, WTTJ, etc.), la
  session est gardée.
- Remplit : prénom, nom, nom complet, email, téléphone, LinkedIn, GitHub, site, ville, lettre
  (champ texte ou fichier), CV (premier champ fichier). Gère les formulaires dans des iframes
  (Greenhouse embarqué).
- Listes déroulantes et boutons radio : remplis quand la question correspond à une entrée de
  `standard_answers` (autorisation de travail, visa, préavis, disponibilité, salaire, mobilité,
  permis, « comment nous avez-vous connus ») et que la réponse figure parmi les choix (« Oui »
  coïncide avec « Yes »). Une clé ajoutée par l'utilisateur, ex. `annees_experience_python`, est
  reconnue si tous ses mots figurent dans la question.
- Le reste (questions spécifiques, consentements, listes déroulantes JavaScript) part dans
  `missing`, avec les choix proposés : l'IA y répond depuis `standard_answers` ou demande à
  l'utilisateur, qui saisit dans la fenêtre ouverte.
- Le résultat est aussi écrit dans `screenshots/<ID>.json` : le script garde la fenêtre ouverte
  jusqu'à 15 min, donc lance-le **en arrière-plan** et lis ce fichier.
- Ne soumet pas sauf `--submit` (et seulement si rien ne manque, que l'offre n'est pas déjà
  envoyée et que le plafond n'est pas atteint ; `--auto` vérifie en plus le mode et le score).
  Après le clic, le statut ne passe à `envoyee` que si une page de confirmation est détectée.
- **Ce navigateur n'est pas le Chrome de l'utilisateur** : Claude in Chrome ne peut pas agir dans
  la fenêtre Playwright. Si Claude in Chrome est disponible, fais tout le formulaire avec lui
  (méthode 3) plutôt que de commencer avec ce script.
- Workday / Taleo : formulaires en plusieurs pages avec création de compte obligatoire : préfère
  Claude in Chrome étape par étape.

## 3. Claude in Chrome / navigateur intégré / computer use (le plus polyvalent)

L'IA pilote le **vrai Chrome de l'utilisateur**, déjà connecté à LinkedIn, Indeed, WTTJ, APEC,
Hellowork… Elle lit la page, remplit chaque étape, téléverse le CV et s'arrête avant l'envoi
final pour validation. C'est la méthode à utiliser pour :
- LinkedIn **Candidature simplifiée** (Easy Apply), Indeed **Postuler**,
- les formulaires multi-étapes et les questions de présélection,
- tout ce que `ats_autofill.py` n'a pas su terminer.

Prérequis : extension Claude in Chrome installée et autorisée sur les sites concernés (ou
l'application de bureau Claude avec son navigateur intégré / computer use).

## 4. Ce qui est déconseillé

- **Bots d'envoi en masse sur LinkedIn / Indeed** (scripts headless qui enchaînent des dizaines
  d'Easy Apply) : interdit par leurs conditions d'utilisation, détection fréquente, restriction ou
  bannissement du compte. Si l'utilisateur veut quand même du volume sur ces plateformes : rester
  dans son navigateur, une offre à la fois, avec pauses, sous `daily_cap`.
- Contourner les CAPTCHA, les vérifications d'identité ou créer de faux comptes.
- Candidater sans lire l'offre : un score faible = pas d'envoi. 10 candidatures ciblées valent
  mieux que 100 génériques (et les recruteurs repèrent les lettres génériques).

## Choix rapide

```
offre.contact_email ?            → email (send_email.py / Outlook / brouillon Gmail)
apply_url sur un ATS ?           → Claude in Chrome si disponible, sinon ats_autofill.py
                                   (champs restants saisis par l'utilisateur dans la fenêtre)
LinkedIn / Indeed ?              → Claude in Chrome, validation avant envoi
autre / aucun lien de candidature → dossier prêt + lien donné à l'utilisateur
```
