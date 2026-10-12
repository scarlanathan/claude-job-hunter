"""Chemins, configuration et accès à la base de suivi, partagés par tous les scripts."""
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("JOB_HUNTER_HOME", Path.home() / ".job-hunter"))
CONFIG_PATH = HOME / "config.json"
PROFILE_PATH = HOME / "profile.json"
DB_PATH = HOME / "tracker.db"
LETTERS_DIR = HOME / "letters"
SEARCHES_DIR = HOME / "searches"
SCREENSHOTS_DIR = HOME / "screenshots"

STATUSES = [
    "a_evaluer",    # importée, pas encore analysée
    "selectionnee", # bon match, à préparer
    "ecartee",      # mauvais match
    "preparee",     # lettre / email prêts, en attente de validation
    "envoyee",      # candidature envoyée
    "relancee",     # relance envoyée
    "entretien",    # entretien obtenu
    "offre",        # proposition reçue
    "refusee",      # refus de l'employeur
    "abandonnee",   # abandon côté candidat
]
# Statuts à partir desquels une candidature (hors relance) peut partir.
SENDABLE = ("selectionnee", "preparee", "a_evaluer")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ascii_fold(text):
    """« Société Générale » -> « societe generale » (comparaisons sans accents ni casse)."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def dedup_key(title, company):
    """Clé titre+entreprise normalisée : repère la même offre publiée sur plusieurs sites."""
    t = re.sub(r"\(.*?\)|\b[hf]\s*/\s*[hf]\b|\bm\s*/\s*f\b", " ", ascii_fold(title))
    c = re.sub(r"\b(sas|sasu|sa|sarl|group|groupe|france|inc|ltd|gmbh)\b", " ", ascii_fold(company))
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s).strip()
    return f"{norm(t)}|{norm(c)}" if norm(t) and norm(c) else ""


def ensure_home():
    for d in (HOME, LETTERS_DIR, SEARCHES_DIR, SCREENSHOTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        shutil.copy(SKILL_DIR / "templates" / "config.example.json", CONFIG_PATH)
    if not PROFILE_PATH.exists():
        shutil.copy(SKILL_DIR / "templates" / "profile.example.json", PROFILE_PATH)


def load_json(path):
    if not path.exists():
        sys.exit(f"Fichier manquant : {path}. Lance d'abord : python tracker.py init")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config():
    return load_json(CONFIG_PATH)


def load_profile():
    return load_json(PROFILE_PATH)


# Colonnes ajoutées après la première version : migrées à l'ouverture de la base.
MIGRATIONS = {"message_id": "TEXT", "score_detail": "TEXT", "dedup_key": "TEXT"}


def db():
    HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            source TEXT, title TEXT, company TEXT, location TEXT,
            url TEXT, apply_url TEXT, contact_email TEXT,
            contract TEXT, salary TEXT, remote TEXT,
            description TEXT, posted_at TEXT,
            score INTEGER, score_reason TEXT,
            status TEXT DEFAULT 'a_evaluer',
            method TEXT, letter_path TEXT,
            applied_at TEXT, next_action_date TEXT,
            notes TEXT, raw TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT, at TEXT, type TEXT, detail TEXT
        );
        """
    )
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    missing = {c: t for c, t in MIGRATIONS.items() if c not in cols}
    for col, typ in missing.items():
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    if "dedup_key" in missing:
        for r in conn.execute("SELECT id, title, company FROM jobs").fetchall():
            conn.execute("UPDATE jobs SET dedup_key = ? WHERE id = ?", (dedup_key(r["title"], r["company"]), r["id"]))
    if missing:
        conn.commit()
    return conn


def log_event(conn, job_id, type_, detail=""):
    conn.execute(
        "INSERT INTO events (job_id, at, type, detail) VALUES (?, ?, ?, ?)",
        (job_id, now_iso(), type_, detail),
    )


def sent_today(conn):
    """Candidatures et relances parties aujourd'hui (tous canaux confondus)."""
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE type IN ('envoyee', 'relancee') AND at >= ?",
        (date.today().isoformat(),),
    ).fetchone()[0]


def previous_applications(conn, job):
    """Autres candidatures déjà envoyées dans la même entreprise."""
    company = ascii_fold(job["company"]).strip()
    if not company:
        return []
    return [r for r in conn.execute(
        "SELECT id, title, status, applied_at, company FROM jobs WHERE id != ? AND applied_at IS NOT NULL",
        (job["id"],),
    ) if ascii_fold(r["company"]).strip() == company]


def send_blockers(conn, job, cfg, *, followup=False, auto=False):
    """Raisons d'interdire un envoi. Liste vide = envoi autorisé.

    Ces garde-fous sont appliqués par le code, pas seulement par les consignes du skill :
    une seule candidature par offre, une seule relance, plafond quotidien, et en mode
    automatique (envoi sans validation humaine) un score minimal.
    """
    apply_cfg = cfg["apply"]
    reasons = []
    if followup:
        if job["status"] != "envoyee":
            reasons.append(f"relance impossible : statut '{job['status']}' (une seule relance, après un envoi)")
    elif job["status"] not in SENDABLE:
        reasons.append(f"déjà traitée : statut '{job['status']}' (une seule candidature par offre)")
    cap = apply_cfg.get("daily_cap", 15)
    n = sent_today(conn)
    if n >= cap:
        reasons.append(f"plafond quotidien atteint ({n}/{cap})")
    if auto:
        if apply_cfg.get("validation") != "auto":
            reasons.append("envoi automatique refusé : config.json > apply.validation n'est pas 'auto'")
        threshold = apply_cfg.get("min_score_auto", 75)
        if job["score"] is None or job["score"] < threshold:
            reasons.append(f"score {job['score']} < min_score_auto ({threshold})")
    return reasons
