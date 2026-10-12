"""Pré-remplit un formulaire de candidature en ligne (Greenhouse, Lever, Ashby, Workable,
SmartRecruiters, Teamtailor, Welcome to the Jungle, formulaires carrière classiques) à partir de profile.json.

Ouvre un navigateur Chromium visible avec un profil persistant (les connexions sont conservées
d'une fois sur l'autre). Ce n'est PAS le Chrome de l'utilisateur : Claude in Chrome ne peut pas
reprendre la main dans cette fenêtre. Le script remplit ce qu'il reconnaît (identité, liens, CV,
lettre, et les listes / boutons radio couverts par standard_answers), fait une capture d'écran,
puis écrit le résultat en JSON (stdout et screenshots/ID.json) avec les champs `missing`.

Par défaut il NE SOUMET PAS : la fenêtre reste ouverte (--wait secondes) pour que l'utilisateur
termine et clique sur « Envoyer ». Lance-le donc en arrière-plan et lis screenshots/ID.json.
--submit clique sur le bouton d'envoi si rien ne manque et si les garde-fous l'autorisent
(statut, plafond quotidien ; avec --auto, mode auto et score minimal).

  pip install playwright && python -m playwright install chromium
  python ats_autofill.py --job ID [--url URL] [--letter lettre.pdf] [--letter-text lettre.txt] [--submit [--auto]]
"""
import argparse
import json
import re
import sys
from pathlib import Path

from common import HOME, SCREENSHOTS_DIR, ascii_fold, db, load_config, load_profile, send_blockers
from tracker import apply_status, get

DESCRIBE_JS = """el => {
  const txt = n => (n && n.innerText || '').trim();
  let label = '';
  if (el.labels && el.labels.length) label = [...el.labels].map(txt).join(' ');
  if (!label && el.getAttribute('aria-labelledby'))
    label = el.getAttribute('aria-labelledby').split(' ').map(i => txt(document.getElementById(i))).join(' ');
  if (!label && el.type !== 'radio' && el.type !== 'checkbox') {
    const l = el.closest('label, .field, .form-group, .application-question, [class*=field]');
    if (l) label = txt(l).slice(0, 200);
  }
  // Question d'un groupe de boutons radio / cases : légende du fieldset ou texte du conteneur.
  let group = '';
  if (el.type === 'radio' || el.type === 'checkbox') {
    const fs = el.closest('fieldset, [role=radiogroup], [role=group], .application-question, .form-group, .field, [class*=question]');
    if (fs) { const lg = fs.querySelector('legend, [class*=label], [class*=question]'); group = (txt(lg) || txt(fs)).slice(0, 200); }
  }
  const options = el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(Boolean) : [];
  const r = el.getBoundingClientRect();
  return {
    tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(), name: el.name || '',
    desc: [el.name, el.id, el.placeholder, el.getAttribute('aria-label'), el.getAttribute('autocomplete'), label]
          .filter(Boolean).join(' | ').toLowerCase(),
    label: label.slice(0, 120), group, options,
    required: el.required || el.getAttribute('aria-required') === 'true',
    filled: el.type === 'file' ? el.files.length > 0
          : (el.type === 'radio' || el.type === 'checkbox') ? el.checked
          : el.tagName === 'SELECT' ? el.selectedIndex > 0 : !!(el.value && el.value.trim()),
    visible: el.type === 'file' || (r.width > 0 && r.height > 0),
  };
}"""

SKIP_TYPES = {"hidden", "submit", "button", "image", "reset", "search"}
SUBMIT_RE = re.compile(r"submit|envoyer|postuler|apply|send application|soumettre|valider ma candidature", re.I)
CONFIRM_RE = re.compile(
    r"merci (pour|de) votre candidature|candidature (a bien été |a été )?(envoyée|reçue|transmise|enregistrée)|"
    r"thank you for (your )?appl|application (has been |was )?(submitted|received|sent)|we('ve| have) received your", re.I)

# Questions fréquentes -> clé de standard_answers. Ordre important : le premier motif gagne
# (« permis de travail » doit passer avant « permis » = permis de conduire).
STANDARD_QUESTIONS = [
    (r"sponsor|visa", "needs_sponsorship"),
    (r"authori[sz]|autoris|legally (able|eligible)|right to work|droit de travailler|permis de travail|work permit",
     "work_authorization_eu"),
    (r"notice period|pr[ée]avis", "notice_period"),
    (r"start date|available|disponibilit|date de d[ée]but|quand pouvez", "available_from"),
    (r"salar|r[ée]mun[ée]ration|pr[ée]tentions|compensation|package", "salary_expectation"),
    (r"relocat|d[ée]m[ée]nag", "willing_to_relocate"),
    (r"permis de conduire|driv|\bpermis\b", "driving_licence"),
    (r"hear about|how did you (find|learn)|comment avez-vous connu|o[uù] avez-vous (vu|trouv)", "how_did_you_hear"),
]
BUILTIN_KEYS = {k for _, k in STANDARD_QUESTIONS}
YES = {"oui", "yes", "y", "true"}
NO = {"non", "no", "n", "false"}


def rules(profile, letter_text):
    i = profile["identity"]
    full = f"{i['first_name']} {i['last_name']}".strip()
    # Ordre important : le premier motif qui correspond gagne.
    # "nom"/"name" seuls sont ambigus (nom de l'entreprise, de l'école...) : on les exclut dans ces cas.
    not_org = r"^(?!.*(company|entreprise|soci[ée]t[ée]|employer|employeur|school|école|ecole|référent|referent))"
    return [
        (r"first.?name|given.?name|prénom|prenom|firstname", i["first_name"]),
        (r"last.?name|family.?name|surname|nom de famille|lastname", i["last_name"]),
        (not_org + r".*(full.?name|nom complet|your name|\bname\b)", full),
        (not_org + r".*\bnom\b", i["last_name"]),
        (r"e-?mail|courriel", i["email"]),
        (r"phone|téléphone|telephone|mobile|portable|\btel\b", i["phone"]),
        (r"linkedin", i.get("linkedin", "")),
        (r"github", i.get("github", "")),
        (r"website|portfolio|site web|personal site", i.get("website", "")),
        (r"\bcity\b|ville|location|localisation|current location", i.get("city", "")),
        (r"cover.?letter|lettre|motivation|why do you want|pourquoi", letter_text),
    ]


def standard_answer(question, answers):
    """Réponse type pour une question, ou None. Les clés ajoutées par l'utilisateur dans
    standard_answers sont reconnues si leurs mots (séparés par _) figurent tous dans la question."""
    q = ascii_fold(question)
    if not q.strip():
        return None
    for rx, key in STANDARD_QUESTIONS:
        if answers.get(key) and re.search(ascii_fold(rx), q):
            return answers[key]
    for key, val in answers.items():
        if key.startswith("_") or not val or key in BUILTIN_KEYS:
            continue
        words = [w for w in ascii_fold(key).split("_") if len(w) > 2]
        if words and all(w in q for w in words):
            return val
    return None


def matches_answer(option, answer):
    """« Oui » coïncide avec « Yes », « Oui, j'ai le permis B »… ; sinon égalité ou début du texte."""
    o, a = ascii_fold(option).strip(" .*"), ascii_fold(str(answer)).strip(" .*")
    if not o or o in ("select", "choisir", "--", "selectionner", "veuillez choisir"):
        return False
    first = re.split(r"[\s,.;:()/-]+", o)[0]
    if a in YES:
        return first in YES
    if a in NO:
        return first in NO
    return o == a or o.startswith(a) or (len(o) > 3 and a.startswith(o))


def autofill(page, profile, cv, letter_pdf, letter_text):
    filled, missing = [], []
    patterns = [(re.compile(p, re.I), v) for p, v in rules(profile, letter_text)]
    answers = profile.get("standard_answers", {})
    cv_done = False
    radio_groups = {}
    for frame in page.frames:
        for el in frame.query_selector_all("input, textarea, select"):
            try:
                info = el.evaluate(DESCRIBE_JS)
            except Exception:
                continue
            if info["type"] in SKIP_TYPES or not info["visible"]:
                continue
            if info["type"] in ("radio", "checkbox"):
                key = (id(frame), info["name"] or info["group"])
                g = radio_groups.setdefault(key, {"question": info["group"], "items": [], "required": False,
                                                  "checked": False, "type": info["type"]})
                g["items"].append((el, info["label"]))
                g["required"] |= info["required"]
                g["checked"] |= info["filled"]
                continue
            if info["filled"]:
                continue
            if info["type"] == "file":
                if re.search(r"cover|lettre|motivation", info["desc"]) and letter_pdf:
                    el.set_input_files(letter_pdf); filled.append(("lettre (fichier)", info["label"]))
                elif not cv_done and not re.search(r"cover|lettre|motivation", info["desc"]):
                    el.set_input_files(cv); cv_done = True; filled.append(("CV", info["label"]))
                elif info["required"]:
                    missing.append(info)
                continue
            if info["tag"] == "select":
                ans = standard_answer(info["label"] or info["desc"], answers)
                opt = next((o for o in info["options"] if ans and matches_answer(o, ans)), None)
                if opt:
                    el.select_option(label=opt); filled.append((opt[:40], info["label"]))
                elif info["required"]:
                    missing.append({**info, "hint": f"réponse type « {ans} » absente des choix" if ans else ""})
                continue
            value = next((v for rx, v in patterns if v and rx.search(info["desc"])), None)
            if value is None:
                value = standard_answer(info["label"] or info["desc"], answers)
            if value is None:
                if info["required"] or info["tag"] == "textarea":
                    missing.append(info)
                continue
            el.fill(str(value))
            filled.append((str(value)[:40], info["label"]))

    for g in radio_groups.values():
        if g["checked"]:
            continue
        ans = standard_answer(g["question"], answers)
        # Cases à cocher : seulement les consentements obligatoires restent à l'utilisateur.
        target = next(((el, lab) for el, lab in g["items"] if ans and matches_answer(lab, ans)), None) \
            if g["type"] == "radio" else None
        if target:
            target[0].check(); filled.append((target[1][:40], g["question"][:80]))
        elif g["required"] or g["type"] == "radio":
            missing.append({"label": g["question"], "desc": g["question"].lower(), "type": g["type"],
                            "tag": "input", "required": g["required"],
                            "options": [lab for _, lab in g["items"]][:10],
                            "hint": f"réponse type « {ans} » absente des choix" if ans else ""})
    return filled, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True)
    ap.add_argument("--url", help="URL du formulaire (sinon apply_url ou url de l'offre)")
    ap.add_argument("--letter", help="lettre au format PDF")
    ap.add_argument("--letter-text", help="fichier texte de la lettre, pour les champs texte")
    ap.add_argument("--submit", action="store_true", help="cliquer sur le bouton d'envoi")
    ap.add_argument("--auto", action="store_true", help="avec --submit : envoi sans validation (mode auto, score vérifié)")
    ap.add_argument("--wait", type=int, default=900, help="secondes d'attente fenêtre ouverte (défaut 15 min)")
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright manquant : pip install playwright && python -m playwright install chromium")

    profile, conn, cfg = load_profile(), db(), load_config()
    job = get(conn, a.job)
    if a.submit:
        blockers = send_blockers(conn, job, cfg, auto=a.auto)
        if blockers:
            sys.exit("Envoi refusé, formulaire non ouvert :\n  - " + "\n  - ".join(blockers))
    url = a.url or job["apply_url"] or job["url"]
    if "jobs.lever.co" in url and not url.rstrip("/").endswith("/apply"):
        url = url.rstrip("/") + "/apply"
    cv = profile["documents"]["cv_pdf"]
    if not Path(cv).exists():
        sys.exit(f"CV introuvable : {cv} (à corriger dans profile.json)")
    letter_text = Path(a.letter_text).read_text(encoding="utf-8") if a.letter_text else ""
    result_path = SCREENSHOTS_DIR / f"{job['id']}.json"
    result_path.unlink(missing_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(HOME / "browser-profile"), headless=False, locale="fr-FR")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        # Beaucoup de pages d'offre ont un bouton « Postuler » avant le formulaire.
        if not page.query_selector("input[type=file]"):
            btn = page.get_by_role("button", name=re.compile(r"postuler|apply|candidater", re.I)).or_(
                page.get_by_role("link", name=re.compile(r"postuler|apply now|candidater", re.I)))
            if btn.count():
                btn.first.click()
                page.wait_for_timeout(3000)

        filled, missing = autofill(page, profile, cv, a.letter, letter_text)
        shot = SCREENSHOTS_DIR / f"{job['id']}.png"
        page.screenshot(path=str(shot), full_page=True)

        submitted = confirmed = False
        after = None
        if a.submit and not missing:
            btn = page.get_by_role("button", name=SUBMIT_RE)
            if btn.count():
                btn.last.click()
                page.wait_for_timeout(6000)
                after = SCREENSHOTS_DIR / f"{job['id']}-apres-envoi.png"
                page.screenshot(path=str(after), full_page=True)
                submitted = True
                confirmed = any(CONFIRM_RE.search(_body_text(f)) for f in page.frames)

        result = {
            "job": job["id"], "url": page.url, "screenshot": str(shot), "submitted": submitted,
            "confirmed": confirmed, "screenshot_after": str(after) if after else None,
            "filled": [{"value": v, "field": f} for v, f in filled],
            "missing": [{"field": m["label"] or m["desc"][:80], "type": m["type"] or m["tag"],
                         "required": m["required"], **({"options": m["options"][:15]} if m.get("options") else {}),
                         **({"hint": m["hint"]} if m.get("hint") else {})} for m in missing],
            "window_open": not submitted,
        }
        out = json.dumps(result, ensure_ascii=False, indent=2)
        result_path.write_text(out, encoding="utf-8")
        print(out, flush=True)

        if submitted and confirmed:
            apply_status(conn, job["id"], "envoyee", method=f"formulaire:{url}", letter=a.letter,
                         note="envoi automatique" if a.auto else None)
            conn.commit()
            ctx.close()
            return
        if submitted:
            apply_status(conn, job["id"], "preparee", method=f"formulaire:{url}", letter=a.letter,
                         note="bouton d'envoi cliqué mais pas de confirmation détectée : vérifier la capture")
            conn.commit()
            print("Envoi NON confirmé : regarde la capture après envoi et la fenêtre.", flush=True)
        else:
            apply_status(conn, job["id"], "preparee", method=f"formulaire:{url}", letter=a.letter,
                         note="formulaire pré-rempli, en attente de l'envoi par l'utilisateur")
            conn.commit()
            print("Fenêtre laissée ouverte : vérifie, complète et clique sur Envoyer, puis ferme-la.", flush=True)
        try:
            page.wait_for_event("close", timeout=a.wait * 1000)
        except Exception:
            pass
        ctx.close()


def _body_text(frame):
    try:
        return frame.inner_text("body", timeout=2000) or ""
    except Exception:
        return ""


if __name__ == "__main__":
    main()
