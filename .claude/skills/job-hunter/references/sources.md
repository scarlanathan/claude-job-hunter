# Sources d'offres

## France Travail (gratuit, officiel, recommandé en France)

1. Crée un compte sur https://francetravail.io, puis « Mes applications » → nouvelle application.
2. Abonne l'application à l'API **Offres d'emploi v2**.
3. Récupère l'identifiant client et la clé secrète :
   `setx FRANCE_TRAVAIL_CLIENT_ID "..."` et `setx FRANCE_TRAVAIL_CLIENT_SECRET "..."`.

Détails utilisés par `search_jobs.py` :
- Jeton : `POST https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire`,
  `grant_type=client_credentials`, `scope=api_offresdemploiv2 o2dsoffre`.
- Recherche : `GET https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search`
  avec `motsCles`, `departement` (code à 2 chiffres, ex. `69`), `minCreationDate`/`maxCreationDate`,
  `range=0-149` (150 max par appel).
- Lieux : `69` = département ; `69123` = code INSEE de commune ; `Lyon` ou `Saint-Denis (93)` = ville,
  convertie en code INSEE via le référentiel `/referentiel/communes` (mis en cache 30 jours dans
  `ft_communes.json`), avec un rayon `search.distance_km` (10 km par défaut). Ville introuvable →
  ajoutée aux mots-clés, avec un avertissement.
- Pagination automatique par tranches de 150 jusqu'à `--max` (l'API s'arrête à 3 150 résultats).
- Le jeton OAuth est réutilisé tant qu'il est valide.
- Si l'API répond 401/403 sur le scope, vérifie le nom exact du scope dans la doc de ton application
  sur francetravail.io et adapte `francetravail_token()`.

Les offres France Travail contiennent parfois `contact.courriel` (→ candidature par email possible)
ou `contact.urlPostulation`.

## Apify (payant à l'usage, couvre LinkedIn, Indeed, Glassdoor, Google Jobs…)

1. Compte sur https://apify.com (crédit gratuit mensuel inclus), puis Settings → API & Integrations.
2. `setx APIFY_TOKEN "apify_api_..."`.

Chaque source Apify de `config.json` déclare un `actor` et un modèle d'`input`. Placeholders
disponibles : `{keywords}`, `{location}`, `{max}` (converti en nombre), `{days}`, `{country}`,
`{linkedin_search_url}` (URL de recherche LinkedIn construite avec mots-clés, lieu et période).

Acteurs pré-configurés (populaires, mais **vérifie toujours l'onglet Input de l'acteur** : les
schémas changent et chaque auteur nomme ses champs à sa façon) :

| Source | Acteur | Entrée principale |
|---|---|---|
| linkedin | `curious_coder/linkedin-jobs-scraper` | `urls` (URL de recherche LinkedIn), `count` |
| indeed | `misceres/indeed-scraper` | `position`, `location`, `country`, `maxItems` |
| multi | `iskoren/multi-job-board-scraper` | plusieurs sites en un run (schéma à vérifier) |

Autres pistes dans l'Apify Store (rechercher « jobs scraper ») : Welcome to the Jungle, Glassdoor,
Google Jobs, Hellowork, APEC, Malt (freelance).

### Ajouter un acteur
1. Ouvre sa page Apify → onglet **Input** → bouton JSON pour voir l'entrée exacte.
2. Ajoute une entrée dans `config.json > sources` :
   ```json
   "wttj": {"type": "apify", "actor": "auteur/nom-acteur",
            "input": {"query": "{keywords}", "location": "{location}", "maxItems": "{max}"}}
   ```
3. Teste : `python search_jobs.py --sources wttj --max 5 --no-import` puis regarde le JSON dans
   `searches/`. Si titre/entreprise/lien sortent vides, ajoute les noms de champs de l'acteur dans
   `normalize_generic()` (`pick(item, ...)`).

### Coût
Le prix dépend de l'acteur (au résultat ou au temps de calcul). Commence par `--max 20`, regarde
la consommation dans la console Apify, puis augmente. Deux plafonds sont transmis à Apify à chaque
run : `maxItems` (= `--max`) et `maxTotalChargeUsd` (= `search.apify_max_charge_usd`, ou
`max_charge_usd` dans la source). Les runs sont lancés en parallèle (`search.parallel`, 4 par défaut).

## Doublons et exclusions
- Une offre déjà présente avec le même titre et la même entreprise (normalisés : accents, « H/F »,
  « SAS »… retirés) n'est pas réimportée, même si elle vient d'un autre site.
- `exclude_keywords` (titre + entreprise) et `exclude_description_keywords` (description) sont
  comparés en mots entiers, sans accents ni casse : « stage » n'exclut pas « backstage ».
