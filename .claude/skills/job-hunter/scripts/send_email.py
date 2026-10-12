"""Envoi d'une candidature par email (SMTP) avec CV et lettre en pièces jointes, puis mise à jour du suivi.

Sans --confirm ni --auto, le script affiche seulement l'aperçu : rien n'est envoyé.

  python send_email.py --job ID --to rh@exemple.fr --subject "Candidature ..." --body-file email.txt \
      [--letter lettre.pdf] [--attach autre.pdf] [--followup] --confirm

  --confirm  l'utilisateur a validé cet envoi
  --auto     envoi sans validation humaine : exige apply.validation = "auto" et score >= min_score_auto

Refusé dans tous les cas : offre déjà envoyée (une candidature par offre), seconde relance,
plafond quotidien atteint. Une relance reprend le fil de l'email d'origine (In-Reply-To).

Mot de passe SMTP : variable d'environnement JOB_HUNTER_SMTP_PASSWORD.
"""
import argparse
import mimetypes
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from common import ascii_fold, db, load_config, load_profile, previous_applications, send_blockers
from tracker import apply_status, get, update


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_fold(text).title()).strip("_")


def attachment_name(kind, profile, job):
    """CV_Prenom_Nom.pdf / LM_Prenom_Nom_Entreprise.pdf : ce que le recruteur voit, pas nos ID internes."""
    i = profile["identity"]
    parts = [kind, slug(i.get("first_name", "")), slug(i.get("last_name", ""))]
    if kind == "LM":
        parts.append(slug(job["company"] or "")[:30])
    return "_".join(p for p in parts if p) + ".pdf"


def smtp_connect(cfg, password):
    host, port = cfg["email"]["smtp_host"], int(cfg["email"].get("smtp_port", 465))
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=60)
    else:
        s = smtplib.SMTP(host, port, timeout=60)
        s.starttls(context=ctx)
    s.login(cfg["email"]["smtp_user"], password)
    return s


def build(cfg, profile, job, a):
    msg = EmailMessage()
    sender = cfg["email"]["smtp_user"]
    msg["From"] = f'{cfg["email"].get("from_name", "")} <{sender}>'
    msg["To"] = a.to
    msg["Subject"] = a.subject
    msg["Reply-To"] = profile["identity"].get("email") or sender
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    if a.followup and job["message_id"]:
        msg["In-Reply-To"] = job["message_id"]
        msg["References"] = job["message_id"]
    msg.set_content(Path(a.body_file).read_text(encoding="utf-8"))
    files = [] if a.followup else [(profile["documents"]["cv_pdf"], attachment_name("CV", profile, job))]
    if a.letter:
        files.append((a.letter, attachment_name("LM", profile, job) if a.letter.lower().endswith(".pdf")
                      else Path(a.letter).name))
    files += [(f, Path(f).name) for f in a.attach or []]
    for f, name in files:
        p = Path(f)
        if not p.exists():
            sys.exit(f"Pièce jointe introuvable : {p}")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=name)
    return msg, files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True, help="ID de l'offre dans le suivi")
    ap.add_argument("--to", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--letter", help="lettre de motivation (PDF de préférence)")
    ap.add_argument("--attach", nargs="*")
    ap.add_argument("--followup", action="store_true", help="email de relance (pas de CV joint, statut -> relancee)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--confirm", action="store_true", help="envoyer réellement (validé par l'utilisateur)")
    mode.add_argument("--auto", action="store_true", help="envoyer sans validation (mode auto, score vérifié)")
    a = ap.parse_args()

    cfg, profile, conn = load_config(), load_profile(), db()
    job = get(conn, a.job)
    msg, files = build(cfg, profile, job, a)

    print(f"Offre   : {job['title']} - {job['company']} ({job['id']}) · statut {job['status']} · score {job['score']}")
    print(f"De      : {msg['From']}\nÀ       : {msg['To']}\nObjet   : {msg['Subject']}")
    if msg["In-Reply-To"]:
        print("Fil     : réponse à l'email de candidature d'origine")
    print(f"PJ      : {', '.join(f'{name} ({Path(f).name})' for f, name in files) or '(aucune)'}")
    for p in previous_applications(conn, job):
        print(f"ATTENTION : déjà candidaté chez {p['company']} le {(p['applied_at'] or '')[:10]} ({p['title']}, {p['status']})")
    print("-" * 60 + "\n" + Path(a.body_file).read_text(encoding="utf-8") + "\n" + "-" * 60)

    blockers = send_blockers(conn, job, cfg, followup=a.followup, auto=a.auto)
    if blockers:
        print("ENVOI IMPOSSIBLE :", *blockers, sep="\n  - ")
        if a.confirm or a.auto:
            sys.exit("Rien n'a été envoyé.")
    if not (a.confirm or a.auto):
        print("APERÇU SEULEMENT : relance avec --confirm pour envoyer.")
        return

    password = os.environ.get("JOB_HUNTER_SMTP_PASSWORD")
    if not password:
        sys.exit("JOB_HUNTER_SMTP_PASSWORD non défini. Rien n'a été envoyé.")
    with smtp_connect(cfg, password) as s:
        s.send_message(msg)

    status = "relancee" if a.followup else "envoyee"
    if not a.followup:
        update(conn, job["id"], message_id=msg["Message-ID"])
    note = a.subject + (" (envoi automatique)" if a.auto else "")
    apply_status(conn, job["id"], status, method=f"email:{a.to}", letter=a.letter, note=note)
    conn.commit()
    print(f"Envoyé. Statut -> {status}")
    host = cfg["email"].get("smtp_host", "")
    if "gmail" not in host:
        print("Note : hors Gmail, une copie n'apparaît pas forcément dans « Envoyés ».")


if __name__ == "__main__":
    main()
