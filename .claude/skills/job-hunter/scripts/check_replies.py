"""Cherche dans la boîte de réception (IMAP) les réponses aux candidatures envoyées.

Alternative aux connecteurs Gmail / Outlook. Rattache chaque email reçu à une candidature
(réponse au fil d'origine, domaine de l'adresse de contact, ou nom de l'entreprise) et propose
une classification : entretien, refus, accusé de réception. Ne modifie PAS le suivi : l'IA
vérifie puis lance `tracker.py status`.

  python check_replies.py              # depuis la dernière vérification (14 jours la première fois)
  python check_replies.py --days 30

Réglages : config.json > email.imap_host (ex. imap.gmail.com), imap_port (993).
Identifiant : email.smtp_user. Mot de passe : JOB_HUNTER_IMAP_PASSWORD, sinon JOB_HUNTER_SMTP_PASSWORD.
"""
import argparse
import email
import imaplib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr

from common import HOME, ascii_fold, db, load_config

LAST_CHECK = HOME / "last_reply_check.txt"
FREE_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "hotmail.fr", "yahoo.fr", "yahoo.com", "live.fr",
             "orange.fr", "free.fr", "laposte.net", "icloud.com", "wanadoo.fr", "sfr.fr"}
CLASSES = [
    ("entretien", r"entretien|rencontrer|[ée]change t[ée]l[ée]phonique|disponibilit[ée]s|cr[ée]neau|visio|"
                  r"interview|schedule a (call|meeting)|calendly|next step"),
    ("refusee", r"malheureusement|regret|pas (pu )?(donner une suite|retenir)|ne correspond pas|"
                r"autres? (candidat|profil)s? (plus|dont)|unfortunately|not (to )?(move|moving) forward|other candidates"),
    ("accuse_reception", r"bien re[çc]u|accus[ée] de r[ée]ception|nous avons re[çc]u|thank you for (your )?appl|"
                         r"we have received|received your application"),
]


def decode(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def body_text(msg):
    for want in ("text/plain", "text/html"):
        for part in msg.walk():
            if part.get_content_type() == want and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                return re.sub(r"<[^>]+>", " ", text) if want == "text/html" else text
    return ""


def classify(text):
    t = ascii_fold(text)
    for name, rx in CLASSES:
        if re.search(ascii_fold(rx), t):
            return name
    return "a_lire"


def match_job(jobs, msg, sender, subject, text):
    refs = f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}"
    for j in jobs:
        if j["message_id"] and j["message_id"] in refs:
            return j, "réponse au fil d'origine"
    domain = sender.rsplit("@", 1)[-1].lower()
    if domain not in FREE_MAIL:
        for j in jobs:
            if j["contact_email"] and j["contact_email"].lower().endswith("@" + domain):
                return j, f"domaine {domain}"
    hay = ascii_fold(f"{sender} {subject} {text[:3000]}")
    for j in jobs:
        company = ascii_fold(j["company"]).strip()
        if len(company) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(company) + r"(?![a-z0-9])", hay):
            return j, f"nom « {j['company']} »"
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="regarder N jours en arrière (sinon depuis la dernière vérification)")
    a = ap.parse_args()

    cfg = load_config()["email"]
    host = cfg.get("imap_host")
    if not host:
        sys.exit("email.imap_host non défini dans config.json (ex. imap.gmail.com).")
    password = os.environ.get("JOB_HUNTER_IMAP_PASSWORD") or os.environ.get("JOB_HUNTER_SMTP_PASSWORD")
    if not password:
        sys.exit("JOB_HUNTER_IMAP_PASSWORD / JOB_HUNTER_SMTP_PASSWORD non défini.")

    if a.days:
        since = date.today() - timedelta(days=a.days)
    elif LAST_CHECK.exists():
        since = date.fromisoformat(LAST_CHECK.read_text().strip()[:10])
    else:
        since = date.today() - timedelta(days=14)

    conn = db()
    jobs = conn.execute("SELECT * FROM jobs WHERE applied_at IS NOT NULL").fetchall()
    if not jobs:
        print("Aucune candidature envoyée dans le suivi.")
        return

    found = []
    with imaplib.IMAP4_SSL(host, int(cfg.get("imap_port", 993))) as imap:
        imap.login(cfg["smtp_user"], password)
        imap.select("INBOX", readonly=True)
        _, data = imap.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        for num in data[0].split():
            _, raw = imap.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(raw[0][1])
            sender = parseaddr(decode(msg.get("From")))[1]
            if sender.lower() == cfg["smtp_user"].lower():
                continue
            subject = decode(msg.get("Subject"))
            text = body_text(msg)
            job, why = match_job(jobs, msg, sender, subject, text)
            if not job:
                continue
            found.append({
                "job": job["id"], "poste": job["title"], "entreprise": job["company"], "statut_actuel": job["status"],
                "de": sender, "objet": subject, "date": decode(msg.get("Date")), "rattachement": why,
                "classification": classify(f"{subject} {text}"),
                "extrait": re.sub(r"\s+", " ", text).strip()[:400],
            })

    print(json.dumps(found, ensure_ascii=False, indent=2))
    print(f"\n{len(found)} réponse(s) rattachée(s) depuis le {since.isoformat()}.", file=sys.stderr)
    if not a.days:
        LAST_CHECK.write_text(datetime.now().isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
