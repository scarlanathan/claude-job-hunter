"""Recherche d'offres via Apify et l'API France Travail, normalisation et import dans le suivi.

Exemples :
  python search_jobs.py                                  # tout ce qui est dans config.json
  python search_jobs.py --sources linkedin --keywords "data engineer" --locations Lyon --max 30
  python search_jobs.py --sources francetravail --no-import  # juste afficher

Lieux (--locations / config.json) : nom de ville (« Lyon », « Saint-Denis (93) » pour lever une
ambiguïté), code département (« 69 »), ou code INSEE de commune (« 69123 »).

Variables d'environnement :
  APIFY_TOKEN                     sources de type "apify"
  FRANCE_TRAVAIL_CLIENT_ID/SECRET source "francetravail"
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests

from common import (HOME, SEARCHES_DIR, ascii_fold, db, dedup_key, ensure_home, load_config, log_event,
                    now_iso)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IGNORED_EMAILS = ("noreply", "no-reply", "donotreply", "example.", "privacy", "rgpd", "gdpr", "dpo@")
FT_API = "https://api.francetravail.io/partenaire/offresdemploi/v2"


# --------------------------------------------------------------------------- Apify

def fill_template(value, ctx):
    """Remplace les {placeholders} connus récursivement ; "{max}" seul devient un entier.

    Les accolades qui ne sont pas des placeholders connus restent telles quelles."""
    if isinstance(value, str):
        if value == "{max}":
            return int(ctx["max"])
        return re.sub(r"\{(\w+)\}", lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), value)
    if isinstance(value, list):
        return [fill_template(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: fill_template(v, ctx) for k, v in value.items() if not k.startswith("_")}
    return value


def linkedin_search_url(keywords, location, days):
    params = {"keywords": keywords, "location": location, "f_TPR": f"r{days * 86400}"}
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


def run_apify(actor, actor_input, token, max_items=None, max_charge_usd=None, max_wait=900):
    api = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}"}
    # Plafonds appliqués par Apify lui-même : nombre de résultats facturés et dépense du run.
    params = {}
    if max_items:
        params["maxItems"] = int(max_items)
    if max_charge_usd:
        params["maxTotalChargeUsd"] = float(max_charge_usd)
    r = requests.post(f"{api}/acts/{actor.replace('/', '~')}/runs", json=actor_input, params=params,
                      headers=headers, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Apify {actor} : HTTP {r.status_code} {r.text[:300]}")
    run = r.json()["data"]
    deadline = time.time() + max_wait
    while run["status"] in ("READY", "RUNNING"):
        if time.time() > deadline:
            raise RuntimeError(f"Apify {actor} : run {run['id']} trop long, toujours {run['status']}")
        time.sleep(5)
        run = requests.get(f"{api}/actor-runs/{run['id']}", headers=headers, timeout=60).json()["data"]
    if run["status"] != "SUCCEEDED":
        raise RuntimeError(f"Apify {actor} : run terminé en {run['status']}")
    items = requests.get(
        f"{api}/datasets/{run['defaultDatasetId']}/items",
        params={"clean": "true", "format": "json"},
        headers=headers,
        timeout=120,
    )
    items.raise_for_status()
    return items.json()


# ------------------------------------------------------------------ France Travail

_ft_lock = threading.Lock()
_ft_token = {"value": None, "expires": 0.0}


def francetravail_token():
    """Jeton OAuth réutilisé tant qu'il est valide (et partagé entre les threads)."""
    with _ft_lock:
        if _ft_token["value"] and time.time() < _ft_token["expires"] - 60:
            return _ft_token["value"]
        cid = os.environ.get("FRANCE_TRAVAIL_CLIENT_ID")
        secret = os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET")
        if not cid or not secret:
            raise RuntimeError("FRANCE_TRAVAIL_CLIENT_ID / FRANCE_TRAVAIL_CLIENT_SECRET non définis")
        r = requests.post(
            "https://entreprise.francetravail.fr/connexion/oauth2/access_token",
            params={"realm": "/partenaire"},
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": secret,
                "scope": "api_offresdemploiv2 o2dsoffre",
            },
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"France Travail token : HTTP {r.status_code} {r.text[:300]}")
        data = r.json()
        _ft_token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in", 1499)))
        return _ft_token["value"]


def ft_get(path, params=None):
    return requests.get(
        f"{FT_API}{path}",
        params=params,
        headers={"Authorization": f"Bearer {francetravail_token()}", "Accept": "application/json"},
        timeout=60,
    )


_communes_lock = threading.Lock()


def ft_communes():
    """Référentiel des communes France Travail, mis en cache 30 jours dans $JOB_HUNTER_HOME."""
    cache = HOME / "ft_communes.json"
    with _communes_lock:
        if cache.exists() and time.time() - cache.stat().st_mtime < 30 * 86400:
            return json.loads(cache.read_text(encoding="utf-8"))
        r = ft_get("/referentiel/communes")
        if r.status_code >= 400:
            raise RuntimeError(f"France Travail référentiel communes : HTTP {r.status_code} {r.text[:200]}")
        cache.write_text(r.text, encoding="utf-8")
        return r.json()


def ft_location_params(location, distance_km):
    """« 69 » -> département, « 69123 » -> commune, « Lyon » / « Saint-Denis (93) » -> code INSEE."""
    if not location:
        return {}, None
    if re.fullmatch(r"\d{2}|2[AB]|97\d", location):
        return {"departement": location}, None
    if re.fullmatch(r"\d{5}|2[AB]\d{3}", location):
        return {"commune": location, "distance": distance_km}, None
    m = re.fullmatch(r"(.+?)\s*\((\d{2}|2[AB]|97\d)\)", location.strip())
    name, dept = (m.group(1), m.group(2)) if m else (location, None)
    key = re.sub(r"[^a-z0-9]+", " ", ascii_fold(name)).strip()
    hits = [c for c in ft_communes()
            if re.sub(r"[^a-z0-9]+", " ", ascii_fold(c.get("libelle", ""))).strip() == key
            and (not dept or c.get("codeDepartement") == dept)]
    if not hits:
        # Paris, Lyon, Marseille sont parfois découpées en arrondissements dans le référentiel.
        hits = [c for c in ft_communes()
                if re.sub(r"[^a-z0-9]+", " ", ascii_fold(c.get("libelle", ""))).strip().startswith(key + " ")
                and (not dept or c.get("codeDepartement") == dept)]
        if hits:
            return {"departement": hits[0]["codeDepartement"]}, \
                f"« {location} » : recherche élargie au département {hits[0]['codeDepartement']}"
        return {}, f"« {location} » introuvable dans le référentiel : ajouté aux mots-clés"
    warn = None
    if len({c.get("codeDepartement") for c in hits}) > 1:
        warn = (f"« {location} » ambigu ({', '.join(sorted({c['codeDepartement'] for c in hits}))}) : "
                f"{hits[0]['codeDepartement']} retenu. Précise « {name} (NN) ».")
    return {"commune": hits[0]["code"], "distance": distance_km}, warn


def run_francetravail(keywords, location, max_items, days, distance_km=10):
    params = {"motsCles": keywords}
    warn = None
    try:
        loc_params, warn = ft_location_params(location, distance_km)
    except RuntimeError as e:
        loc_params, warn = {}, f"{e} : lieu ajouté aux mots-clés"
    params.update(loc_params)
    if location and not loc_params:
        params["motsCles"] = f"{keywords} {location}"
    if days:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        params["minCreationDate"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        params["maxCreationDate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []
    # 150 offres max par appel : on pagine avec range=début-fin (l'API plafonne l'index de début à 3000).
    for first in range(0, min(max_items, 3150), 150):
        last = min(first + 150, max_items) - 1
        r = ft_get("/offres/search", {**params, "range": f"{first}-{last}"})
        if r.status_code == 204:
            break
        if r.status_code >= 400:
            raise RuntimeError(f"France Travail search : HTTP {r.status_code} {r.text[:300]}")
        page = r.json().get("resultats", [])
        results += page
        if len(page) < last - first + 1:
            break
    return results, warn


# ------------------------------------------------------------------ Normalisation

def pick(d, *keys):
    for k in keys:
        cur = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", []):
            if isinstance(cur, list):
                cur = ", ".join(str(x) for x in cur)
            if isinstance(cur, dict):
                cur = json.dumps(cur, ensure_ascii=False)
            return str(cur).strip()
    return ""


def clean_url(url):
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def find_email(*texts):
    for t in texts:
        for m in EMAIL_RE.findall(t or ""):
            if not any(bad in m.lower() for bad in IGNORED_EMAILS):
                return m
    return ""


def job_id(url, title, company, location):
    key = clean_url(url) or f"{title}|{company}|{location}".lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def normalize_generic(item, source):
    title = pick(item, "title", "jobTitle", "positionName", "position", "name")
    company = pick(item, "companyName", "company.name", "company", "company_name", "employer", "hiringOrganization.name")
    location = pick(item, "location", "jobLocation", "formattedLocation", "place", "city")
    url = pick(item, "link", "jobUrl", "url", "jobPostingUrl", "detailUrl")
    apply_url = pick(item, "applyUrl", "externalApplyLink", "applyLink", "apply_url", "applicationUrl")
    description = pick(item, "descriptionText", "description", "jobDescription", "descriptionHTML", "snippet")
    description = re.sub(r"<[^>]+>", " ", description)
    return {
        "source": source,
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "apply_url": apply_url,
        "contact_email": pick(item, "email", "contactEmail") or find_email(description),
        "contract": pick(item, "employmentType", "jobType", "contractType", "contract"),
        "salary": pick(item, "salary", "salaryInfo", "salaryRange", "salary_text"),
        "remote": pick(item, "workplaceType", "remote", "workType"),
        "description": description,
        "posted_at": pick(item, "postedAt", "publishedAt", "datePosted", "postingDate", "postedDate", "date"),
        "raw": item,
    }


def normalize_francetravail(item):
    url = pick(item, "origineOffre.urlOrigine") or (
        f"https://candidat.francetravail.fr/offres/recherche/detail/{item.get('id', '')}"
    )
    description = pick(item, "description")
    return {
        "source": "francetravail",
        "title": pick(item, "intitule"),
        "company": pick(item, "entreprise.nom"),
        "location": pick(item, "lieuTravail.libelle"),
        "url": url,
        "apply_url": pick(item, "contact.urlPostulation"),
        "contact_email": pick(item, "contact.courriel") or find_email(description, pick(item, "contact.coordonnees1")),
        "contract": pick(item, "typeContratLibelle", "typeContrat"),
        "salary": pick(item, "salaire.libelle", "salaire.commentaire"),
        "remote": "",
        "description": description,
        "posted_at": pick(item, "dateCreation"),
        "raw": item,
    }


def word_re(words):
    """Mots entiers, sans accents ni casse : « stage » n'attrape pas « backstage »."""
    words = [ascii_fold(w).strip() for w in words if w and w.strip()]
    return re.compile(r"(?<![a-z0-9])(" + "|".join(map(re.escape, words)) + r")(?![a-z0-9])") if words else None


def make_excluder(search_cfg):
    title_rx = word_re(search_cfg.get("exclude_keywords", []))
    desc_rx = word_re(search_cfg.get("exclude_description_keywords", []))
    companies = {ascii_fold(c).strip() for c in search_cfg.get("exclude_companies", [])}

    def excluded(job):
        if title_rx and title_rx.search(ascii_fold(f"{job['title']} {job['company']}")):
            return True
        if desc_rx and desc_rx.search(ascii_fold(job["description"])):
            return True
        return ascii_fold(job["company"]).strip() in companies
    return excluded


# ------------------------------------------------------------------ Import

def import_jobs(jobs):
    """Importe les offres nouvelles. Renvoie (nombre ajouté, ID existants pour les doublons).

    Doublon = même URL (même ID) ou même titre + entreprise déjà présent, y compris venu d'un
    autre site (la même offre est souvent publiée sur LinkedIn, Indeed et France Travail)."""
    conn = db()
    new, dupes = 0, []
    known = {r["dedup_key"]: r["id"] for r in conn.execute("SELECT id, dedup_key FROM jobs WHERE dedup_key != ''")}
    for j in jobs:
        jid = job_id(j["url"], j["title"], j["company"], j["location"])
        key = dedup_key(j["title"], j["company"])
        if key and key in known and known[key] != jid:
            dupes.append(known[key])
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO jobs (id, source, title, company, location, url, apply_url,
               contact_email, contract, salary, remote, description, posted_at, raw, dedup_key,
               created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, j["source"], j["title"], j["company"], j["location"], j["url"], j["apply_url"],
             j["contact_email"], j["contract"], j["salary"], j["remote"], j["description"],
             j["posted_at"], json.dumps(j["raw"], ensure_ascii=False), key, now_iso(), now_iso()),
        )
        if cur.rowcount:
            new += 1
            log_event(conn, jid, "importee", j["source"])
            if key:
                known[key] = jid
        else:
            dupes.append(jid)
    conn.commit()
    return new, dupes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", nargs="+", help="noms de sources définies dans config.json")
    ap.add_argument("--keywords", nargs="+")
    ap.add_argument("--locations", nargs="+")
    ap.add_argument("--max", type=int, help="nombre max d'offres par source et par requête")
    ap.add_argument("--days", type=int, help="offres publiées depuis N jours")
    ap.add_argument("--no-import", action="store_true", help="ne pas importer dans le suivi")
    args = ap.parse_args()

    ensure_home()
    cfg = load_config()
    s = cfg["search"]
    sources = args.sources or s["sources"]
    keywords = args.keywords or s["keywords"]
    locations = args.locations or s["locations"] or [""]
    max_items = args.max or s.get("max_per_source", 50)
    days = args.days or s.get("posted_within_days", 7)
    excluded = make_excluder(s)

    def run_one(src_name, src, kw, loc):
        label = f"[{src_name}] '{kw}' @ '{loc}'"
        warn = None
        if src["type"] == "francetravail":
            raw, warn = run_francetravail(kw, loc, max_items, days, s.get("distance_km", 10))
            jobs = [normalize_francetravail(i) for i in raw]
        elif src["type"] == "apify":
            token = os.environ.get("APIFY_TOKEN")
            if not token:
                raise RuntimeError("APIFY_TOKEN non défini")
            ctx = {
                "keywords": kw, "location": loc, "max": max_items, "days": days,
                "country": s.get("country", "FR"),
                "linkedin_search_url": linkedin_search_url(kw, loc, days),
            }
            raw = run_apify(src["actor"], fill_template(src["input"], ctx), token, max_items=max_items,
                            max_charge_usd=src.get("max_charge_usd", s.get("apify_max_charge_usd")))
            jobs = [normalize_generic(i, src_name) for i in raw]
        else:
            raise RuntimeError(f"type de source inconnu : {src['type']}")
        return label, [j for j in jobs if j["title"] and not excluded(j)], warn

    tasks, errors = [], []
    for src_name in sources:
        src = cfg["sources"].get(src_name)
        if not src:
            errors.append(f"source inconnue : {src_name}")
            continue
        tasks += [(src_name, src, kw, loc) for kw in keywords for loc in locations]

    all_jobs, warnings = [], []
    # Les runs Apify durent souvent plusieurs minutes : on les lance en parallèle.
    with ThreadPoolExecutor(max_workers=max(1, int(s.get("parallel", 4)))) as pool:
        futures = [(t, pool.submit(run_one, *t)) for t in tasks]
        for (src_name, _, kw, loc), fut in futures:
            try:
                label, jobs, warn = fut.result()
            except Exception as e:  # une source en panne ne bloque pas les autres
                errors.append(f"[{src_name}] '{kw}' @ '{loc}' : {e}")
                continue
            if warn and warn not in warnings:
                warnings.append(warn)
            print(f"{label} : {len(jobs)} offres")
            all_jobs.extend(jobs)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SEARCHES_DIR / f"search-{stamp}.json"
    out.write_text(json.dumps([{k: v for k, v in j.items() if k != "raw"} for j in all_jobs],
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal : {len(all_jobs)} offres -> {out}")
    if not args.no_import:
        new, dupes = import_jobs(all_jobs)
        print(f"Nouvelles offres ajoutées au suivi : {new} (doublons ignorés : {len(dupes)})")
    if warnings:
        print("\nAvertissements :", *warnings, sep="\n  - ", file=sys.stderr)
    if errors:
        print("\nErreurs :", *errors, sep="\n  - ", file=sys.stderr)
        if not all_jobs:
            sys.exit(1)


if __name__ == "__main__":
    main()
