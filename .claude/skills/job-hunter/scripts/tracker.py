"""Suivi des candidatures (SQLite dans $JOB_HUNTER_HOME/tracker.db).

Commandes :
  init                                  crée ~/.job-hunter avec config.json et profile.json
  doctor                                vérifie l'installation (fichiers, CV, variables, dépendances, SMTP)
  list [--status S ...] [--min-score N] [--limit N]
  show ID [--brief]                     détail d'une offre (--brief : description tronquée)
  score ID SCORE "raison" [--detail JSON]   note de 0 à 100 donnée par l'IA
  score-batch FICHIER.json              plusieurs notes d'un coup : [{"id", "score", "reason", "detail"}]
  status ID STATUT [--note ...] [--method ...] [--letter PATH]
  note ID "texte"
  add --title ... --company ... [--url ...] [--email ...]   ajout manuel
  check ID                              l'offre est-elle encore en ligne ?
  due                                   relances à faire aujourd'hui
  stats                                 statuts, envois du jour, résultats par source et par méthode
  export                                CSV + tableau de bord HTML
"""
import argparse
import csv
import html
import importlib.util
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from common import (CONFIG_PATH, DB_PATH, HOME, PROFILE_PATH, STATUSES, db, ensure_home, load_config,
                    log_event, now_iso, previous_applications, sent_today)

SCORE_PARTS = {"competences": 40, "seniorite": 20, "lieu_contrat": 20, "salaire": 10, "interet": 10}


def short(row):
    score = "--" if row["score"] is None else f"{row['score']:>2}"
    via = row["contact_email"] and "@" or (row["apply_url"] and "↗" or " ")
    return f"{row['id']}  {score}  {row['status']:<12} {via} {(row['title'] or '')[:55]:<55}  {(row['company'] or '')[:25]:<25} {(row['location'] or '')[:20]}"


def cmd_init(_):
    ensure_home()
    db().close()
    print(f"Dossier prêt : {HOME}\n  - config.json  (recherche, sources, règles d'envoi)\n  - profile.json (identité, CV, réponses types)\n  - tracker.db\nPuis : python tracker.py doctor")


def cmd_list(a):
    q, params = "SELECT * FROM jobs WHERE 1=1", []
    if a.status:
        q += f" AND status IN ({','.join('?' * len(a.status))})"
        params += a.status
    if a.min_score is not None:
        q += " AND score >= ?"
        params.append(a.min_score)
    q += " ORDER BY score IS NULL, score DESC, created_at DESC LIMIT ?"
    params.append(a.limit)
    rows = db().execute(q, params).fetchall()
    print("ID            SC  STATUT         TITRE / ENTREPRISE / LIEU   (@ = email de contact, ↗ = lien de candidature)")
    for r in rows:
        print(short(r))
    print(f"\n{len(rows)} offre(s)")


def get(conn, jid):
    rows = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchall() or \
        conn.execute("SELECT * FROM jobs WHERE id LIKE ?", (jid + "%",)).fetchall()
    if not rows:
        sys.exit(f"Offre introuvable : {jid}")
    if len(rows) > 1:
        sys.exit(f"ID ambigu « {jid} » : " + ", ".join(f"{r['id']} ({r['title']})" for r in rows[:5])
                 + ". Donne plus de caractères.")
    return rows[0]


def cmd_show(a):
    conn = db()
    r = get(conn, a.id)
    for k in r.keys():
        if k not in ("raw", "description", "dedup_key") and r[k]:
            print(f"{k:<16}: {r[k]}")
    for p in previous_applications(conn, r):
        print(f"ATTENTION       : déjà candidaté chez {p['company']} le {(p['applied_at'] or '')[:10]} "
              f"({p['title']}, {p['status']}, {p['id']})")
    desc = r["description"] or "(vide)"
    if a.brief and len(desc) > 1500:
        desc = desc[:1500] + f"… [{len(desc) - 1500} caractères de plus : show sans --brief]"
    print("\n--- Description ---\n" + desc)
    print("\n--- Historique ---")
    for e in conn.execute("SELECT * FROM events WHERE job_id = ? ORDER BY at", (r["id"],)):
        print(f"{e['at']}  {e['type']:<12} {e['detail'] or ''}")


def update(conn, jid, **fields):
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), jid))


def check_detail(detail, score):
    """Le détail doit suivre la grille du skill et additionner au score (hors plafond deal-breaker)."""
    if not detail:
        return None
    unknown = set(detail) - set(SCORE_PARTS)
    if unknown:
        return f"clés inconnues {sorted(unknown)} (attendu : {', '.join(SCORE_PARTS)})"
    over = [k for k, v in detail.items() if not 0 <= v <= SCORE_PARTS[k]]
    if over:
        return "valeurs hors barème : " + ", ".join(f"{k}={detail[k]}/{SCORE_PARTS[k]}" for k in over)
    if sum(detail.values()) != score and score > 20:
        return f"la somme du détail ({sum(detail.values())}) ne correspond pas au score ({score})"
    return None


def set_score(conn, jid, score, reason, detail, threshold):
    r = get(conn, jid)
    err = check_detail(detail, score)
    if err:
        raise ValueError(f"{r['id']} : {err}")
    fields = {"score": score, "score_reason": reason,
              "score_detail": json.dumps(detail, ensure_ascii=False) if detail else None}
    if r["status"] == "a_evaluer":
        fields["status"] = "selectionnee" if score >= threshold else "ecartee"
    update(conn, r["id"], **fields)
    log_event(conn, r["id"], "score", f"{score} - {reason}")
    return r["id"], fields.get("status")


def cmd_score(a):
    conn = db()
    detail = json.loads(a.detail) if a.detail else None
    try:
        jid, status = set_score(conn, a.id, a.score, a.reason, detail,
                                load_config()["apply"].get("min_score_shortlist", 60))
    except ValueError as e:
        sys.exit(str(e))
    conn.commit()
    print(f"{jid} : score {a.score}" + (f", statut -> {status}" if status else ""))


def cmd_score_batch(a):
    conn = db()
    threshold = load_config()["apply"].get("min_score_shortlist", 60)
    items = json.loads(Path(a.file).read_text(encoding="utf-8"))
    errors = []
    for it in items:
        try:
            jid, status = set_score(conn, it["id"], int(it["score"]), it.get("reason", ""), it.get("detail"), threshold)
            print(f"{jid} : {it['score']}" + (f" -> {status}" if status else ""))
        except (ValueError, KeyError, SystemExit) as e:
            errors.append(f"{it.get('id', '?')} : {e}")
    conn.commit()
    if errors:
        print("\nNon enregistrés :", *errors, sep="\n  - ", file=sys.stderr)
        sys.exit(1)


def apply_status(conn, jid, status, method=None, letter=None, note=None):
    fields = {"status": status}
    if method:
        fields["method"] = method
    if letter:
        fields["letter_path"] = letter
    if status in ("envoyee", "relancee"):
        days = load_config()["apply"].get("followup_days", 8)
        fields["next_action_date"] = (date.today() + timedelta(days=days)).isoformat()
        if status == "envoyee":
            fields["applied_at"] = now_iso()
    if status in ("refusee", "abandonnee", "offre", "ecartee"):
        fields["next_action_date"] = None
    update(conn, jid, **fields)
    log_event(conn, jid, status, " | ".join(x for x in (method, note) if x))


def cmd_status(a):
    conn = db()
    r = get(conn, a.id)
    if a.status in ("envoyee", "relancee"):
        cap = load_config()["apply"].get("daily_cap", 15)
        n = sent_today(conn)
        if n >= cap:
            print(f"ATTENTION : plafond quotidien déjà atteint ({n}/{cap}). Plus aucun envoi aujourd'hui, "
                  "y compris LinkedIn / Indeed.", file=sys.stderr)
        if a.status == "envoyee" and r["status"] in ("envoyee", "relancee", "entretien", "offre", "refusee"):
            print(f"ATTENTION : cette offre avait déjà le statut '{r['status']}'.", file=sys.stderr)
    apply_status(conn, r["id"], a.status, a.method, a.letter, a.note)
    conn.commit()
    print(f"{r['id']} -> {a.status}")


def cmd_note(a):
    conn = db()
    r = get(conn, a.id)
    notes = ((r["notes"] or "") + f"\n[{now_iso()}] {a.text}").strip()
    update(conn, r["id"], notes=notes)
    log_event(conn, r["id"], "note", a.text)
    conn.commit()
    print("Note ajoutée.")


def cmd_add(a):
    from search_jobs import import_jobs, job_id
    job = {"source": "manuel", "title": a.title, "company": a.company, "location": a.location or "",
           "url": a.url or "", "apply_url": a.apply_url or "", "contact_email": a.email or "",
           "contract": "", "salary": "", "remote": "", "description": a.description or "",
           "posted_at": "", "raw": {}}
    new, dupes = import_jobs([job])
    jid = job_id(job["url"], job["title"], job["company"], job["location"])
    if new:
        print("Ajoutée :", jid)
    else:
        print("Déjà dans le suivi :", ", ".join(dupes) or jid)


CLOSED_RE = re.compile(
    r"no longer accepting applications|n'accepte plus de candidatures|this job (has )?expired|"
    r"offre (n'est plus disponible|expirée|a expiré|pourvue)|annonce (n'est plus|a été) (en ligne|disponible|supprimée)|"
    r"job (is )?no longer available|position (has been )?filled|cette offre n'existe plus", re.I)


def cmd_check(a):
    import requests
    conn = db()
    r = get(conn, a.id)
    url = r["apply_url"] or r["url"]
    if not url:
        sys.exit("Aucune URL pour cette offre.")
    try:
        resp = requests.get(url, timeout=30, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "fr-FR,fr;q=0.9"})
    except requests.RequestException as e:
        sys.exit(f"Injoignable : {e}")
    m = CLOSED_RE.search(resp.text or "")
    if resp.status_code in (404, 410) or m:
        why = m.group(0) if m else f"HTTP {resp.status_code}"
        print(f"FERMÉE probablement ({why}) : {resp.url}")
        sys.exit(2)
    print(f"En ligne (HTTP {resp.status_code}) : {resp.url}")
    if resp.status_code >= 400:
        print("Réponse en erreur : vérifier dans le navigateur (certains sites bloquent les scripts).")


def cmd_due(_):
    rows = db().execute(
        "SELECT * FROM jobs WHERE next_action_date IS NOT NULL AND next_action_date <= ? "
        "AND status IN ('envoyee', 'relancee') ORDER BY next_action_date",
        (date.today().isoformat(),),
    ).fetchall()
    for r in rows:
        print(f"{short(r)}  (prévu {r['next_action_date']}, envoyée le {(r['applied_at'] or '')[:10]})")
    print(f"\n{len(rows)} relance(s) à faire")


def funnel(conn, label, expr):
    """Taux de réponse par source ou par méthode : c'est là qu'il faut concentrer l'effort."""
    rows = conn.execute(
        f"""SELECT {expr} AS k, COUNT(*) AS total,
                   SUM(applied_at IS NOT NULL) AS envoyees,
                   SUM(status IN ('entretien', 'offre')) AS entretiens,
                   SUM(status = 'refusee') AS refus
            FROM jobs GROUP BY k ORDER BY envoyees DESC, total DESC"""
    ).fetchall()
    print(f"\n{label:<14} {'offres':>6} {'envoyées':>9} {'entretiens':>11} {'refus':>6}  taux d'entretien")
    for r in rows:
        rate = f"{100 * r['entretiens'] / r['envoyees']:.0f} %" if r["envoyees"] else "-"
        print(f"{(r['k'] or '?')[:14]:<14} {r['total']:>6} {r['envoyees']:>9} {r['entretiens']:>11} {r['refus']:>6}  {rate}")


def cmd_stats(_):
    conn = db()
    for s in STATUSES:
        n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (s,)).fetchone()[0]
        if n:
            print(f"{s:<13} {n}")
    cap = load_config()["apply"].get("daily_cap", 15)
    print(f"\nEnvois aujourd'hui (candidatures + relances) : {sent_today(conn)}/{cap}")
    funnel(conn, "source", "source")
    funnel(conn, "méthode", "CASE WHEN instr(method, ':') THEN substr(method, 1, instr(method, ':') - 1) ELSE method END")


def cmd_export(_):
    conn = db()
    rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    cols = ["id", "status", "score", "title", "company", "location", "source", "method", "applied_at",
            "next_action_date", "url", "apply_url", "contact_email", "score_reason", "notes"]
    csv_path = HOME / "candidatures.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])

    colors = {"selectionnee": "#3b82f6", "preparee": "#a855f7", "envoyee": "#f59e0b", "relancee": "#f97316",
              "entretien": "#10b981", "offre": "#059669", "refusee": "#ef4444", "ecartee": "#9ca3af",
              "abandonnee": "#6b7280", "a_evaluer": "#64748b"}
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    cards = "".join(f'<div class="card" style="border-color:{colors[s]}"><b>{n}</b><span>{s}</span></div>'
                    for s, n in counts.items() if n)
    trs = []
    for r in rows:
        link = r["apply_url"] or r["url"]
        title = html.escape(r["title"] or "")
        cell = f'<a href="{html.escape(link, quote=True)}" target="_blank">{title}</a>' if link else title
        trs.append(
            f"<tr><td><span class='pill' style='background:{colors.get(r['status'], '#999')}'>{r['status']}</span></td>"
            f"<td>{'' if r['score'] is None else r['score']}</td>"
            f"<td>{cell}</td>"
            f"<td>{html.escape(r['company'] or '')}</td><td>{html.escape(r['location'] or '')}</td>"
            f"<td>{html.escape(r['method'] or '')}</td><td>{(r['applied_at'] or '')[:10]}</td>"
            f"<td>{r['next_action_date'] or ''}</td><td class=small>{html.escape(r['score_reason'] or '')}</td></tr>"
        )
    page = f"""<!doctype html><html lang=fr><meta charset=utf-8><title>Candidatures</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#fff;--fg:#111;--muted:#666;--line:#e5e7eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--muted:#999;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui;margin:0;padding:16px}}
.cards{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.card{{border-left:4px solid;padding:8px 12px;background:color-mix(in srgb,var(--fg) 5%,transparent)}}
.card b{{display:block;font-size:20px}} .card span{{color:var(--muted)}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}}
.pill{{color:#fff;border-radius:10px;padding:2px 8px;font-size:12px}} .small{{color:var(--muted);font-size:12px}}
a{{color:inherit}}
</style><h1>Candidatures</h1><p class=small>Mis à jour le {now_iso()}</p>
<div class=cards>{cards}</div><div class=wrap><table><tr><th>Statut</th><th>Score</th><th>Poste</th>
<th>Entreprise</th><th>Lieu</th><th>Méthode</th><th>Envoyée</th><th>Relance</th><th>Analyse</th></tr>
{''.join(trs)}</table></div></html>"""
    html_path = HOME / "dashboard.html"
    html_path.write_text(page, encoding="utf-8")
    print(f"{csv_path}\n{html_path}")


def cmd_doctor(a):
    ok = True

    def line(good, msg, hint=""):
        nonlocal ok
        ok &= good is not False
        mark = {True: "OK  ", False: "ERR ", None: "--  "}[good]
        print(f"{mark} {msg}" + (f"\n       → {hint}" if hint and good is not True else ""))

    print(f"Dossier : {HOME}")
    line(CONFIG_PATH.exists(), "config.json", "python tracker.py init")
    line(PROFILE_PATH.exists(), "profile.json", "python tracker.py init")
    if not (CONFIG_PATH.exists() and PROFILE_PATH.exists()):
        sys.exit(1)
    cfg = load_config()
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    ident = profile.get("identity", {})
    line(ident.get("first_name") not in ("", "Prénom", None) and "@" in ident.get("email", ""),
         f"identité : {ident.get('first_name')} {ident.get('last_name')} <{ident.get('email')}>",
         "remplir profile.json > identity à partir du CV")
    cv = profile.get("documents", {}).get("cv_pdf", "")
    line(bool(cv) and Path(cv).exists() and cv.lower().endswith(".pdf"), f"CV : {cv or '(non défini)'}",
         "documents.cv_pdf doit pointer vers un PDF existant")
    line(bool(profile.get("skills")) and profile.get("skills") != ["Python", "SQL"] or None,
         f"compétences : {len(profile.get('skills', []))}", "vérifier que profile.json a été rempli depuis le CV")

    for mod, why in (("requests", "recherche"), ("reportlab", "lettres PDF"), ("playwright", "formulaires ATS (optionnel)")):
        present = importlib.util.find_spec(mod) is not None
        line(present if mod != "playwright" else (present or None), f"module {mod} ({why})",
             f"pip install {mod}" + (" && python -m playwright install chromium" if mod == "playwright" else ""))

    sources = cfg["search"].get("sources", [])
    if any(cfg["sources"].get(s, {}).get("type") == "apify" for s in sources):
        line(bool(os.environ.get("APIFY_TOKEN")), "APIFY_TOKEN", 'setx APIFY_TOKEN "apify_api_..." puis relancer le terminal')
    if "francetravail" in sources:
        line(bool(os.environ.get("FRANCE_TRAVAIL_CLIENT_ID") and os.environ.get("FRANCE_TRAVAIL_CLIENT_SECRET")),
             "FRANCE_TRAVAIL_CLIENT_ID / _SECRET", "voir references/sources.md")
        if a.online and os.environ.get("FRANCE_TRAVAIL_CLIENT_ID"):
            try:
                from search_jobs import francetravail_token
                francetravail_token()
                line(True, "jeton France Travail obtenu")
            except Exception as e:
                line(False, f"jeton France Travail : {e}")

    email = cfg.get("email", {})
    has_pwd = bool(os.environ.get("JOB_HUNTER_SMTP_PASSWORD"))
    line(has_pwd or None, f"SMTP {email.get('smtp_user')} via {email.get('smtp_host')}:{email.get('smtp_port')}",
         "JOB_HUNTER_SMTP_PASSWORD non défini : envoi par connecteur Gmail/Outlook seulement")
    if a.online and has_pwd:
        from send_email import smtp_connect
        try:
            with smtp_connect(cfg, os.environ["JOB_HUNTER_SMTP_PASSWORD"]):
                pass
            line(True, "connexion SMTP réussie (rien n'a été envoyé)")
        except Exception as e:
            line(False, f"connexion SMTP : {e}", "voir references/apply_methods.md")
    if email.get("imap_host"):
        line(has_pwd or None, f"IMAP {email['imap_host']} (lecture des réponses)")

    val = cfg["apply"].get("validation")
    line(val in ("each", "batch", "auto"), f"mode de validation : {val} · plafond {cfg['apply'].get('daily_cap')}/jour")
    if not a.online:
        print("\n(--online pour tester aussi France Travail et la connexion SMTP)")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("doctor"); p.add_argument("--online", action="store_true", help="tester aussi les connexions")
    p = sub.add_parser("list")
    p.add_argument("--status", nargs="+", choices=STATUSES)
    p.add_argument("--min-score", type=int)
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("show"); p.add_argument("id"); p.add_argument("--brief", action="store_true")
    p = sub.add_parser("score"); p.add_argument("id"); p.add_argument("score", type=int); p.add_argument("reason")
    p.add_argument("--detail", help='JSON, ex. {"competences": 32, "seniorite": 15, "lieu_contrat": 20, "salaire": 5, "interet": 8}')
    p = sub.add_parser("score-batch"); p.add_argument("file")
    p = sub.add_parser("status")
    p.add_argument("id"); p.add_argument("status", choices=STATUSES)
    p.add_argument("--note"); p.add_argument("--method"); p.add_argument("--letter")
    p = sub.add_parser("note"); p.add_argument("id"); p.add_argument("text")
    p = sub.add_parser("add")
    for f in ("title", "company"):
        p.add_argument(f"--{f}", required=True)
    for f in ("location", "url", "apply-url", "email", "description"):
        p.add_argument(f"--{f}")
    p = sub.add_parser("check"); p.add_argument("id")
    sub.add_parser("due"); sub.add_parser("stats"); sub.add_parser("export")
    a = ap.parse_args()
    if a.cmd not in ("init", "doctor") and not DB_PATH.exists():
        ensure_home()
    globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
