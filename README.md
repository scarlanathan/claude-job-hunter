# Job Hunter : recherche d'emploi et candidatures automatisées avec Claude

Skill Claude Code qui transforme Claude en assistant de recherche d'emploi :

1. **Cherche** des offres (API officielle France Travail, LinkedIn, Indeed et autres sites via Apify)
2. **Évalue** chaque offre par rapport à ton CV (score de 0 à 100 avec explication)
3. **Rédige** une lettre de motivation adaptée à chaque offre (optionnel)
4. **Postule à ta place** : par email, en remplissant les formulaires en ligne, ou dans ton navigateur
5. **Suit** chaque candidature : statut, historique, relances, tableau de bord

> Par défaut, Claude te montre chaque candidature et attend ton accord avant de l'envoyer.
> Le mode 100 % automatique existe, mais c'est toi qui l'actives (voir [Mode automatique](#7-mode-automatique)).

---

## Sommaire

1. [Contenu du dossier](#1-contenu-du-dossier)
2. [Installation](#2-installation)
3. [Obtenir les accès (clés API, email)](#3-obtenir-les-accès)
4. [Première utilisation](#4-première-utilisation)
5. [Utilisation au quotidien](#5-utilisation-au-quotidien)
6. [Comment Claude postule à ta place](#6-comment-claude-postule-à-ta-place)
7. [Mode automatique](#7-mode-automatique)
8. [Suivi des candidatures](#8-suivi-des-candidatures)
9. [Référence de la configuration](#9-référence-de-la-configuration)
10. [Référence des commandes](#10-référence-des-commandes)
11. [Coûts](#11-coûts)
12. [Sécurité, confidentialité et limites](#12-sécurité-confidentialité-et-limites)
13. [Dépannage](#13-dépannage)

---

## 1. Contenu du dossier

```
skills_employ/
├── README.md                          ← ce fichier
└── .claude/skills/job-hunter/         ← le skill (dossier caché « .claude »)
    ├── SKILL.md                       instructions que Claude suit
    ├── scripts/
    │   ├── common.py                  chemins, config, base de données
    │   ├── search_jobs.py             recherche (France Travail + Apify)
    │   ├── tracker.py                 suivi des candidatures
    │   ├── send_email.py              candidature / relance par email
    │   ├── ats_autofill.py            remplissage automatique des formulaires en ligne
    │   ├── check_replies.py           lecture des réponses des recruteurs (IMAP)
    │   └── make_letter_pdf.py         lettre de motivation → PDF
    ├── requirements.txt               dépendances Python
    ├── references/
    │   ├── sources.md                 configurer France Travail et Apify, ajouter une source
    │   ├── apply_methods.md           les méthodes de candidature en détail
    │   ├── cover_letter.md            règles de rédaction des lettres
    │   └── interview.md               préparation d'entretien et suite
    └── templates/
        ├── config.example.json        modèle de configuration
        ├── profile.example.json       modèle de profil candidat
        ├── email_candidature.txt      modèle d'email de candidature
        ├── relance.txt                modèle d'email de relance
        └── remerciement.txt           modèle de remerciement après entretien
```

Tes données personnelles ne sont **pas** dans ce dossier. Elles vont dans `C:\Users\<toi>\.job-hunter\` :

```
~/.job-hunter/
├── config.json         ta recherche et tes règles d'envoi
├── profile.json        ton identité, ton CV, tes réponses types
├── tracker.db          la base de suivi (SQLite)
├── letters/            lettres et emails générés
├── searches/           résultats bruts de chaque recherche (JSON)
├── screenshots/        captures des formulaires remplis
├── browser-profile/    sessions du navigateur automatisé
├── candidatures.csv    export pour Excel
└── dashboard.html      tableau de bord
```

Pour mettre ces données ailleurs, définis la variable `JOB_HUNTER_HOME` (ex. `setx JOB_HUNTER_HOME "D:\Emploi"`).

---

## 2. Installation

### Prérequis

| Élément | Obligatoire | Utilité |
|---|---|---|
| [Claude Code](https://claude.com/claude-code) (terminal, application de bureau ou VS Code) | ✅ | fait tourner le skill |
| Python 3.10 ou plus récent | ✅ | les scripts |
| Paquet `requests` | ✅ | appels aux API |
| Paquet `reportlab` | recommandé | lettres en PDF |
| Paquet `playwright` + Chromium | recommandé | remplissage des formulaires en ligne |
| Extension [Claude in Chrome](https://claude.com/chrome) | optionnel | candidatures LinkedIn / Indeed, formulaires complexes |
| Connecteur Gmail ou Outlook dans Claude | optionnel | brouillons, envoi, lecture des réponses des recruteurs |

### Commandes

```powershell
python --version                       # doit afficher 3.10 ou plus
pip install requests reportlab playwright
python -m playwright install chromium
```

### Rendre le skill disponible

- **Dans ce projet uniquement** : rien à faire. Lance Claude Code depuis `skills_employ\`, le skill est détecté automatiquement.
- **Dans tous tes projets** : copie le dossier dans tes skills personnels :
  ```powershell
  Copy-Item -Recurse "$HOME\Desktop\skills_employ\.claude\skills\job-hunter" "$HOME\.claude\skills\"
  ```

Pour vérifier : dans Claude Code, tape `/job-hunter` ou demande « quels skills as-tu ? ».

---

## 3. Obtenir les accès

Les secrets vont dans des **variables d'environnement**, jamais dans les fichiers de configuration.
Sous Windows, `setx` les enregistre de façon permanente. **Ferme puis rouvre le terminal (et Claude Code) ensuite.**

### 3.1 France Travail (gratuit, recommandé en France)

1. Crée un compte sur **https://francetravail.io**.
2. Va dans *Mes applications*, puis *Créer une application*.
3. Abonne l'application à l'API **« Offres d'emploi v2 »**.
4. Copie l'identifiant client et la clé secrète :
   ```powershell
   setx FRANCE_TRAVAIL_CLIENT_ID "PAR_xxxxxxxx"
   setx FRANCE_TRAVAIL_CLIENT_SECRET "xxxxxxxxxxxxxxxx"
   ```

### 3.2 Apify (LinkedIn, Indeed, Glassdoor… : payant à l'usage, avec crédit gratuit mensuel)

1. Crée un compte sur **https://apify.com**.
2. Va dans *Settings*, puis *API & Integrations* : copie ton jeton personnel.
   ```powershell
   setx APIFY_TOKEN "apify_api_xxxxxxxxxxxxxxxx"
   ```
3. Les « acteurs » (robots de collecte) déjà configurés sont `curious_coder/linkedin-jobs-scraper` et `misceres/indeed-scraper`.
   Leurs paramètres d'entrée peuvent changer. Vérifie l'onglet **Input** de chaque acteur sur Apify et ajuste `config.json` si besoin.
   Pour ajouter un autre site (Welcome to the Jungle, Glassdoor, Hellowork…), voir `references/sources.md`.

### 3.3 Envoi des emails

Choisis **une** des options :

**A. SMTP (envoi entièrement autonome, recommandé pour le mode auto)**

- **Gmail** :
  1. Active la validation en 2 étapes sur ton compte Google.
  2. Crée un **mot de passe d'application** sur https://myaccount.google.com/apppasswords.
  3. Enregistre-le (c'est un code de 16 caractères, pas ton vrai mot de passe) :
     ```powershell
     setx JOB_HUNTER_SMTP_PASSWORD "abcd efgh ijkl mnop"
     ```
  4. Dans `config.json`, mets `smtp_host: smtp.gmail.com`, `smtp_port: 465`, `smtp_user: ton.adresse@gmail.com`.
- **Outlook / Hotmail** : `smtp-mail.outlook.com`, port `587`. Microsoft bloque de plus en plus ce mode ; si ça échoue, utilise l'option B.
- **Autre fournisseur** : reprends les réglages SMTP de ton hébergeur. Le port 465 utilise SSL, tout autre port utilise STARTTLS.

**B. Connecteurs Claude (sans mot de passe)**

- **Outlook / Microsoft 365** : Claude peut envoyer directement.
- **Gmail** : Claude crée des **brouillons** prêts à partir ; tu cliques sur « Envoyer ».
- Active-les dans les paramètres de Claude (*Connecteurs*). Ils servent aussi à lire les réponses des recruteurs.

### Récapitulatif des variables

| Variable | Obligatoire pour |
|---|---|
| `FRANCE_TRAVAIL_CLIENT_ID`, `FRANCE_TRAVAIL_CLIENT_SECRET` | source `francetravail` |
| `APIFY_TOKEN` | sources `linkedin`, `indeed`, `multi`… |
| `JOB_HUNTER_SMTP_PASSWORD` | `send_email.py` (et `check_replies.py`) |
| `JOB_HUNTER_IMAP_PASSWORD` | optionnel : `check_replies.py`, si différent du mot de passe SMTP |
| `JOB_HUNTER_HOME` | optionnel : dossier des données |

Il suffit d'une seule source pour commencer (France Travail, par exemple).

Pour vérifier l'installation : `python tracker.py doctor --online` (dans `scripts\`). Chaque ligne
`ERR` indique quoi corriger ; la connexion SMTP est testée sans rien envoyer.

---

## 4. Première utilisation

Ouvre Claude Code dans `skills_employ\` et écris simplement :

> « Voici mon CV : C:\Users\Nathan\Documents\CV.pdf. Je cherche un poste de développeur Python en CDI à Lyon ou en télétravail, minimum 40 k€. »

Claude va :

1. lancer `tracker.py init` (création de `~/.job-hunter/`) ;
2. lire ton CV et remplir `profile.json` (identité, expériences, compétences…) ;
3. te poser **en une seule fois** les questions qui manquent : contrat, mobilité, salaire, exclusions, mode de validation, réponses aux questions fréquentes (permis, préavis, disponibilité…) ;
4. remplir `config.json` ;
5. lancer une première recherche et te présenter les meilleures offres.

**Relis `~/.job-hunter/profile.json`** une fois : tout ce que Claude écrira sur toi viendra de là.
Tu peux aussi fournir une lettre de motivation type : Claude s'en servira comme référence de ton et de style.

---

## 5. Utilisation au quotidien

Tu parles normalement à Claude. Exemples :

| Tu dis | Claude fait |
|---|---|
| « Cherche-moi de nouvelles offres » | recherche, puis évaluation et top des offres |
| « Cherche des postes de data analyst à Nantes, 20 max » | recherche ciblée |
| « Montre-moi les offres au-dessus de 75 » | liste filtrée |
| « Prépare les candidatures pour les 3 premières » | lettres et emails, puis aperçu à valider |
| « Envoie » / « Oui pour la 1 et la 3 » | envoi, puis mise à jour du suivi |
| « Postule à cette offre : https://… » | ajout manuel, évaluation, candidature |
| « Où en sont mes candidatures ? » | statistiques et tableau de bord |
| « Qui dois-je relancer ? » | relances dues et brouillons de relance |
| « Regarde si j'ai eu des réponses » | lecture de ta boîte mail et mise à jour des statuts |
| « J'ai un entretien chez Acme mardi 14 h » | statut `entretien`, note, événement d'agenda proposé |

### Le cycle complet

```
 Recherche ──▶ Évaluation ──▶ Sélection ──▶ Préparation ──▶ Validation ──▶ Envoi ──▶ Suivi / relance
 search_jobs   score 0-100    (toi ou      lettre + email   (toi, sauf     email /    tracker.py
               par Claude      auto ≥ 75)   ou formulaire    mode auto)     formulaire  due / export
```

### Comment Claude note une offre

| Critère | Points |
|---|---|
| Compétences et expérience demandées vs ton CV | 40 |
| Niveau / séniorité cohérent | 20 |
| Lieu, télétravail, contrat conformes à tes préférences | 20 |
| Salaire (s'il est indiqué) ≥ ton minimum | 10 |
| Secteur / intérêt | 10 |
| Un critère rédhibitoire (`deal_breakers`) présent | score plafonné à 20 |

Score ≥ `min_score_shortlist` (60) : l'offre est **sélectionnée** ; en dessous, elle est **écartée**.

---

## 6. Comment Claude postule à ta place

LinkedIn, Indeed et les logiciels de recrutement n'ont **pas d'API publique pour postuler**. Claude postule donc comme toi : par email, ou en remplissant les formulaires dans un navigateur. Il choisit la méthode dans cet ordre :

| Situation | Méthode | Automatique ? |
|---|---|---|
| L'offre donne une adresse email | **Email** depuis ta boîte, CV + lettre en PDF (`send_email.py`) | ✅ entièrement |
| Formulaire Greenhouse, Lever, Ashby, Workable, Teamtailor, SmartRecruiters, Recruitee, site carrière | **Remplissage automatique** (`ats_autofill.py`) | ✅ si tous les champs sont reconnus |
| Site avec compte (Welcome to the Jungle, Workday, Taleo…) | Remplissage automatique ou Claude in Chrome, après **une connexion manuelle** | ⚠️ presque |
| LinkedIn « Candidature simplifiée », Indeed « Postuler » | **Claude in Chrome**, dans ton navigateur, étape par étape | ⚠️ possible, à petit volume |
| Aucun moyen de candidater en ligne | Claude te donne le lien et le dossier prêt | ❌ |

### 6.1 Par email

1. Claude génère le texte (`letters/<ID>-email.txt`) et la lettre PDF.
2. Il lance `send_email.py` **sans** `--confirm` : c'est un **aperçu** (destinataire, objet, texte, pièces jointes).
3. Après ton accord, il relance la commande avec `--confirm` : l'email part, le statut passe à `envoyee`, une relance est programmée 8 jours plus tard.

Le script refuse lui-même d'envoyer deux fois la même offre, une deuxième relance, ou au-delà du plafond quotidien. Les pièces jointes s'appellent `CV_Prenom_Nom.pdf` et `LM_Prenom_Nom_Entreprise.pdf`.

L'email part de ta vraie adresse et apparaît dans tes « Envoyés » ; les réponses arrivent normalement chez toi.

### 6.2 Formulaires en ligne

`ats_autofill.py` :

1. ouvre un **vrai navigateur visible** (Chromium) avec un profil qui garde tes connexions ;
2. clique sur « Postuler » si nécessaire ;
3. remplit prénom, nom, email, téléphone, LinkedIn, GitHub, site, ville, lettre de motivation (texte ou fichier) et joint ton CV, y compris dans les formulaires intégrés (iframes) ;
4. fait une capture d'écran (`screenshots/<ID>.png`) ;
5. répond aux listes déroulantes et boutons radio couverts par tes `standard_answers` (autorisation de travail, visa, préavis, disponibilité, permis…) ;
6. écrit le résultat dans `screenshots/<ID>.json`, avec la liste des champs **non remplis** et les choix proposés.

Claude te pose les questions restantes, et tu les saisis dans la fenêtre ouverte. Ce navigateur n'est pas ton Chrome : si Claude in Chrome est installé, Claude préfère remplir tout le formulaire avec lui. Pour l'envoi :

- **par défaut**, la fenêtre reste ouverte : tu vérifies et cliques sur « Envoyer » ;
- avec `--submit`, le script clique lui-même, **seulement si aucun champ ne manque** ; le statut ne passe à `envoyee` que si la page de confirmation est détectée.

### 6.3 LinkedIn et Indeed

Claude passe par **Claude in Chrome** : il travaille dans ton Chrome, où tu es déjà connecté. Il ouvre l'offre, remplit chaque étape et s'arrête avant « Envoyer » pour te montrer le récapitulatif (sauf en mode auto).

> ⚠️ **Risque** : LinkedIn et Indeed interdisent l'automatisation dans leurs conditions d'utilisation et peuvent restreindre ou bannir un compte.
> Le skill reste volontairement lent (une offre à la fois, plafond quotidien) et n'utilise pas de robot d'envoi en masse.

---

## 7. Mode automatique

Dans `~/.job-hunter/config.json`, section `apply` :

```json
"apply": {
  "validation": "auto",
  "daily_cap": 15,
  "min_score_shortlist": 60,
  "min_score_auto": 75,
  "followup_days": 8,
  "cover_letter": "when_useful"
}
```

| Valeur de `validation` | Comportement |
|---|---|
| `each` (défaut) | tu valides chaque candidature |
| `batch` | Claude prépare tout, tu valides la liste d'un coup |
| `auto` | Claude envoie seul les offres avec un score ≥ `min_score_auto`, au plus `daily_cap` par jour (vérifié par les scripts via `--auto`) |

Même en mode `auto`, Claude **s'arrête et te demande** :
- devant un CAPTCHA ou une vérification d'identité ;
- devant une question dont la réponse n'est pas dans ton profil (il l'enregistre ensuite pour la prochaine fois) ;
- quand un site exige la création d'un compte.

**Conseil** : garde `each` pour tes 5 à 10 premières candidatures, le temps de vérifier la qualité des lettres, puis passe en `auto`.

### Faire tourner la routine tous les jours

La routine : chercher, évaluer, postuler aux offres retenues, faire les relances dues, te résumer ce qui est parti.

- **Pendant une session ouverte** : dans Claude Code, tape
  `/loop 24h Lance ma routine job-hunter : recherche, évaluation, candidatures, relances, résumé`
- **Sans rien ouvrir (Planificateur de tâches Windows)** :
  1. Autorise les scripts sans confirmation dans `skills_employ\.claude\settings.json` :
     ```json
     { "permissions": { "allow": ["Bash(python *)", "PowerShell(python *)"] } }
     ```
  2. Crée une tâche planifiée (ex. tous les jours à 9 h) qui exécute, dans le dossier `skills_employ` :
     ```powershell
     claude -p "Lance ma routine job-hunter quotidienne et écris le résumé dans ~/.job-hunter/resume-du-jour.md"
     ```
  Les candidatures LinkedIn / Indeed via Chrome et le remplissage des formulaires demandent un navigateur ouvert : en tâche de fond, privilégie l'email et les formulaires simples.

---

## 8. Suivi des candidatures

### Statuts

| Statut | Signification |
|---|---|
| `a_evaluer` | importée, pas encore analysée |
| `selectionnee` | bon match, à préparer |
| `ecartee` | ne correspond pas |
| `preparee` | lettre / formulaire prêt, en attente d'envoi |
| `envoyee` | candidature partie (relance programmée) |
| `relancee` | relance envoyée |
| `entretien` | entretien obtenu |
| `offre` | proposition reçue 🎉 |
| `refusee` | refus de l'employeur |
| `abandonnee` | abandon de ta part |

### Relances

- `followup_days` (8 jours par défaut) après l'envoi, la candidature apparaît dans `tracker.py due`.
- Claude propose une relance courte (modèle `templates/relance.txt`), envoyée avec `send_email.py --followup` : pas de CV joint, statut `relancee`.
- Une seule relance par offre ; sans réponse deux semaines plus tard, Claude propose de passer l'offre en `abandonnee`.

### Réponses des recruteurs

Demande « regarde si j'ai eu des réponses ». Avec le connecteur Gmail ou Outlook, Claude cherche les emails des entreprises concernées ; sinon il lance `check_replies.py`, qui lit ta boîte en IMAP (`email.imap_host`) et rattache chaque réponse à une candidature. Claude lit chaque réponse avant de mettre à jour le statut (`entretien`, `refusee`, `offre`).

### Entretiens

Quand tu obtiens un entretien, Claude prépare une fiche (`letters/<ID>-entretien.md`) : l'entreprise, les besoins de l'offre reliés à ton CV, les questions probables, les questions à poser. Il propose ensuite un email de remerciement après l'entretien (`templates/remerciement.txt`).

### Statistiques

`python tracker.py stats` donne aussi le **taux d'entretien par source et par méthode** : tu vois où tes candidatures marchent le mieux.

### Tableau de bord

```powershell
python tracker.py export
```
crée `~/.job-hunter/candidatures.csv` (s'ouvre dans Excel) et `~/.job-hunter/dashboard.html` (à ouvrir dans le navigateur).

---

## 9. Référence de la configuration

### `config.json`

| Clé | Description |
|---|---|
| `search.keywords` | liste de postes / mots-clés recherchés |
| `search.locations` | villes (`"Lyon"`, `"Saint-Denis (93)"`), codes département (`"69"`) ou codes INSEE (`"69123"`) |
| `search.distance_km` | rayon autour d'une ville pour France Travail (10 par défaut) |
| `search.country` | code pays (`FR`) pour les acteurs Apify |
| `search.max_per_source` | nombre max d'offres par source **et par combinaison** mot-clé × lieu |
| `search.posted_within_days` | ancienneté maximale des offres |
| `search.exclude_keywords` | mots entiers qui excluent une offre (titre ou entreprise) : « stage », « alternance »… |
| `search.exclude_description_keywords` | mots entiers qui excluent une offre s'ils sont dans la description |
| `search.apify_max_charge_usd` | dépense maximale par run Apify |
| `search.parallel` | nombre de recherches lancées en même temps (4) |
| `search.exclude_companies` | entreprises à ignorer |
| `search.sources` | sources utilisées par défaut |
| `sources.<nom>` | définition d'une source : `type` (`apify` / `francetravail`), `actor`, `input` |
| `apply.*` | règles d'envoi (voir [Mode automatique](#7-mode-automatique)) |
| `apply.cover_letter` | `always`, `when_useful` (si l'offre la demande ou candidature par email), `never` |
| `email.*` | serveur SMTP, adresse d'envoi, nom affiché ; `imap_host` / `imap_port` pour lire les réponses |

Dans les `input` Apify, ces mots entre accolades sont remplacés automatiquement : `{keywords}`, `{location}`, `{max}`, `{days}`, `{country}`, `{linkedin_search_url}`.

> Attention au volume : 2 mots-clés × 2 villes × 3 sources = 12 requêtes. Avec Apify, ça compte dans le coût.

### `profile.json`

| Section | Contenu |
|---|---|
| `identity` | prénom, nom, email, téléphone, ville, LinkedIn, GitHub, site |
| `documents.cv_pdf` | **chemin du CV en PDF** (obligatoire pour postuler) |
| `documents.cover_letter_base` | lettre type optionnelle (référence de style) |
| `summary`, `skills`, `experiences`, `education`, `languages` | contenu du CV, utilisé pour l'évaluation et les lettres |
| `preferences` | contrats, télétravail, salaire minimum, mobilité, `deal_breakers` |
| `standard_answers` | réponses aux questions fréquentes des formulaires : autorisation de travail, préavis, disponibilité, prétentions, permis… |

Plus `standard_answers` est complet, moins Claude a besoin de te demander quoi que ce soit. Tu peux y ajouter tes propres clés : `annees_experience_python` est utilisée pour toute question contenant « années », « expérience » et « python ».

---

## 10. Référence des commandes

Claude lance ces commandes lui-même ; tu peux aussi les utiliser à la main, depuis `.claude\skills\job-hunter\scripts\`.

### Recherche

```powershell
python search_jobs.py                                           # selon config.json
python search_jobs.py --sources francetravail --keywords "comptable" --locations 75 92 --max 50
python search_jobs.py --sources linkedin --days 3 --no-import   # tester sans importer
```

### Suivi

```powershell
python tracker.py init
python tracker.py doctor [--online]
python tracker.py list [--status selectionnee preparee] [--min-score 70] [--limit 50]
python tracker.py show <ID> [--brief]
python tracker.py score <ID> 82 "raison" [--detail '{"competences": 35, "seniorite": 17, "lieu_contrat": 20, "salaire": 5, "interet": 5}']
python tracker.py score-batch scores.json
python tracker.py check <ID>                     # l'offre est-elle encore en ligne ?
python tracker.py status <ID> envoyee [--method email] [--note "..."] [--letter lettre.pdf]
python tracker.py note <ID> "Entretien mardi 14h"
python tracker.py add --title "Poste" --company "Entreprise" [--url ...] [--email ...] [--location ...] [--description ...]
python tracker.py due
python tracker.py stats
python tracker.py export
```
Un début d'identifiant suffit s'il est unique (`show 7cc1`) ; s'il est ambigu, la commande refuse et liste les candidats.

### Candidatures

```powershell
# Lettre texte → PDF
python make_letter_pdf.py ~/.job-hunter/letters/<ID>-lettre.md   # lignes « > » alignées à droite

# Email : aperçu, puis envoi réel avec --confirm
python send_email.py --job <ID> --to rh@entreprise.fr --subject "Candidature – Poste – Prénom Nom" `
  --body-file ~/.job-hunter/letters/<ID>-email.txt --letter ~/.job-hunter/letters/<ID>-lettre.pdf [--confirm | --auto]

# Relance
python send_email.py --job <ID> --to rh@entreprise.fr --subject "Re: Candidature – Poste" `
  --body-file relance.txt --followup --confirm

# Formulaire en ligne (ajouter --submit pour cliquer sur Envoyer)
python ats_autofill.py --job <ID> [--url <formulaire>] --letter lettre.pdf --letter-text lettre.md [--submit [--auto]]

# Réponses des recruteurs (IMAP)
python check_replies.py [--days 30]
```

---

## 11. Coûts

| Élément | Coût |
|---|---|
| API France Travail | gratuit |
| Apify | crédit gratuit mensuel, puis paiement à l'usage (selon l'acteur : au résultat ou au temps de calcul). Commence avec `--max 20` et surveille la console Apify ; `search.apify_max_charge_usd` plafonne chaque run. |
| Envoi par Gmail / Outlook | gratuit |
| Claude | selon ton abonnement Claude / ta consommation d'API |

---

## 12. Sécurité, confidentialité et limites

**Ce que Claude ne fait jamais :**
- inventer une expérience, un diplôme ou une compétence absente de ton CV / profil ;
- taper un mot de passe, contourner un CAPTCHA ou créer un faux compte ;
- postuler deux fois à la même offre ;
- dépasser le plafond quotidien d'envois.

**Confidentialité :**
- tes données (profil, CV, suivi) restent **sur ton ordinateur**, dans `~/.job-hunter/` ;
- les clés et mots de passe sont dans des variables d'environnement, pas dans des fichiers ;
- les offres passent par Apify / France Travail ; tes candidatures partent uniquement vers les recruteurs.

**Limites connues :**
- les acteurs Apify sont maintenus par des tiers : leurs paramètres et leurs champs de sortie peuvent changer (voir `references/sources.md`) ;
- `ats_autofill.py` reconnaît les champs courants et les questions couvertes par `standard_answers` ; les listes déroulantes en JavaScript et les questions spécifiques sont complétées par toi ;
- Workday, Taleo et les formulaires très longs passent mieux par Claude in Chrome ;
- envoyer plus d'une vingtaine d'emails par jour depuis une boîte personnelle augmente le risque de finir en spam ;
- l'automatisation sur LinkedIn / Indeed comporte un risque pour ton compte (voir [6.3](#63-linkedin-et-indeed)).

**Qualité plutôt que quantité** : 10 candidatures ciblées avec une vraie lettre donnent en général plus d'entretiens que 100 envois génériques. C'est pour ça que le score minimum existe.

---

## 13. Dépannage

| Problème | Solution |
|---|---|
| `APIFY_TOKEN non défini` (ou autre variable) | `setx ...` puis **ferme et rouvre** le terminal et Claude Code. Vérifie avec `echo $env:APIFY_TOKEN`. |
| France Travail : `HTTP 401` / `invalid_scope` | Vérifie que l'application est bien abonnée à « Offres d'emploi v2 » sur francetravail.io, et le nom du scope dans `search_jobs.py` → `francetravail_token()`. |
| France Travail : 0 résultat sur une ville | Lis l'avertissement affiché (ville ambiguë ou introuvable) ; écris `Ville (NN)`, le code INSEE, ou le code département. |
| Une offre apparaît en double | La déduplication compare titre + entreprise normalisés ; si les titres diffèrent vraiment, passe l'un des deux en `ecartee`. |
| Apify : `HTTP 404` | Nom d'acteur incorrect ou acteur retiré : cherche un remplaçant dans l'Apify Store. |
| Apify : offres sans titre ni entreprise | Les champs de sortie de l'acteur ont changé : ajoute leurs noms dans `normalize_generic()` (`search_jobs.py`). |
| Gmail : `Username and Password not accepted` | Il faut un **mot de passe d'application** (validation en 2 étapes activée), pas ton mot de passe habituel. |
| `Plafond quotidien atteint` | Normal : augmente `apply.daily_cap` si tu le souhaites, ou attends le lendemain. |
| `Playwright manquant` | `pip install playwright` puis `python -m playwright install chromium`. |
| Le formulaire ne se remplit pas | Regarde `screenshots/<ID>.png`. Si le formulaire est derrière une connexion, connecte-toi une fois dans la fenêtre ouverte, puis relance. Sinon, demande à Claude de passer par Claude in Chrome. |
| `CV introuvable` | Corrige `documents.cv_pdf` dans `profile.json` (chemin complet vers un PDF). |
| Accents bizarres dans le terminal | Les scripts écrivent en UTF-8 ; dans un vieux terminal, lance `chcp 65001`. |
| Repartir de zéro | Supprime `~/.job-hunter/tracker.db` (le suivi) ou tout le dossier `~/.job-hunter/` (suivi, configuration et profil). |
