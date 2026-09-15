#!/usr/bin/env python3
"""
backend.py  v1.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Serveur FastAPI local — hébergement personnel, max 5 utilisateurs.

Nouveautés v1.2 :
  • Chaque utilisateur a un slot horaire : 22h30, 22h35, 22h40, 22h45, 22h50
  • Un scheduler APScheduler déclenche automatiquement l'analyse au bon slot
  • À la création du compte, un lien Cloudflare Pages personnel est généré
    (sous-répertoire /report/<username>/index.html) et renvoyé dans la réponse
  • generate_html.py est appelé avec --user <username> --output docs/<username>/
  • L'analyse manuelle depuis l'interface reste disponible

Endpoints :
  POST /api/login              → jeton JWT
  GET  /api/portfolio/{user}   → lignes du portefeuille
  POST /api/portfolio/{user}   → sauvegarder les lignes
  POST /api/analyze/{user}     → lancer l'analyse manuellement
  GET  /api/users              → liste des utilisateurs (admin)
  POST /api/users              → créer un compte (admin, max 5)
  DELETE /api/users/{username} → supprimer un compte (admin)
  GET  /api/status             → statut serveur + prochain slot par user
  GET  /                       → sert interface.html
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, status, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import List, Optional
import sqlite3, bcrypt, jwt as pyjwt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# ── Config ──────────────────────────────────────────────────────────
ROOT             = Path(__file__).parent.parent
DATA_DIR         = ROOT / "data"
PORTFOLIOS       = DATA_DIR / "portfolios"
DB_PATH          = DATA_DIR / "users.db"
INTERFACE        = ROOT / "interface.html"
ANALYZER         = ROOT / "portfolio_analyzer.py"
GEN_HTML         = ROOT / "generate_html.py"
GEN_CHART        = ROOT / "generate_chart.py"
GEN_PORTAL       = ROOT / "generate_portal.py"
MAX_USERS        = int(os.getenv("MAX_USERS", "10"))
JWT_SECRET       = os.getenv("JWT_SECRET", "")

# Exposition publique : autorise l'inscription libre. Tant que cette variable
# vaut "0", le service reste utilisable en local mais n'accepte aucune
# inscription depuis l'exterieur.
INSCRIPTION_LIBRE = os.getenv("INSCRIPTION_LIBRE", "0") == "1"

# Mot de passe du compte administrateur, impose au premier demarrage.
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "")

_DEFAUTS_INTERDITS = {"", "changeme-secret-local", "secret", "changeme"}

if JWT_SECRET in _DEFAUTS_INTERDITS:
    # Le secret signe les jetons de session. Une valeur par defaut est PUBLIQUE :
    # elle figure dans ce fichier, donc sur GitHub. N'importe qui pourrait forger
    # un jeton « role: admin » sans connaitre le moindre mot de passe.
    #
    # L'ancienne version ne refusait ce cas que si INSCRIPTION_LIBRE=1. C'etait
    # insuffisant : le site est joignable depuis l'exterieur quelle que soit
    # l'ouverture des inscriptions. Plutot que d'empecher le demarrage — ce qui
    # mettrait le site hors service le jour d'une mise a jour — on fabrique une
    # cle au hasard au premier lancement et on la conserve, comme pour les cles
    # de notification. Rien a definir, et aucune valeur connue d'avance.
    import secrets as _secrets
    _CHEMIN_SECRET = DATA_DIR / "jwt_secret.txt"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if _CHEMIN_SECRET.exists():
            JWT_SECRET = _CHEMIN_SECRET.read_text(encoding="utf-8").strip()
        if JWT_SECRET in _DEFAUTS_INTERDITS:
            JWT_SECRET = _secrets.token_hex(32)
            _CHEMIN_SECRET.write_text(JWT_SECRET, encoding="utf-8")
            try:
                os.chmod(_CHEMIN_SECRET, 0o600)
            except OSError:
                pass
            print(f"[SECURITE] JWT_SECRET non defini : une cle a ete generee dans "
                  f"{_CHEMIN_SECRET}. Les sessions ouvertes devront etre refaites "
                  f"une fois. Ce fichier ne doit jamais partir sur GitHub.")
    except OSError as _e:
        raise RuntimeError(
            f"JWT_SECRET n'est pas defini et la cle de secours n'a pas pu etre "
            f"ecrite dans {DATA_DIR} ({_e}). Definis JWT_SECRET toi-meme :\n"
            '  python -c "import secrets;print(secrets.token_hex(32))"'
        )
JWT_ALG          = "HS256"
JWT_EXPIRE       = 60 * 8   # 8 heures

# URL de base Cloudflare Pages — à adapter à ton projet
CLOUDFLARE_BASE  = os.getenv("CLOUDFLARE_PAGES_URL", "https://projectone.pages.dev")

# Heure d'analyse : 22h37 Paris, marches US et Euronext fermes.
# Euronext ferme a 17h30 ; New York a 22h00 heure de Paris. Les 37 minutes de
# marge laissent les prix d'enchere de cloture se consolider.
#
# Minute volontairement atypique : GitHub documente que les taches planifiees
# peuvent etre retardees quand trop de depots demandent le meme creneau, et
# les minutes rondes sont les plus encombrees.
ANALYSE_HEURE  = int(os.getenv("ANALYSE_HEURE",  "22"))
ANALYSE_MINUTE = int(os.getenv("ANALYSE_MINUTE", "37"))

# D'OU VIENT L'HEURE AFFICHEE.
# Le site a longtemps annonce 22h30 alors que le code prevoit 22h37, sans
# qu'on puisse savoir pourquoi : une variable d'environnement posee sur la
# machine ecrasait la valeur, en silence. On trace desormais la provenance,
# et /api/version la publie.
_SOURCES_HORAIRE = [n for n in ("ANALYSE_HEURE", "ANALYSE_MINUTE",
                                "HEURE_ANALYSE_GROUPEE")
                    if os.getenv(n)]
if _SOURCES_HORAIRE:
    print(f"[Horaire] Valeur(s) imposee(s) par l'environnement : "
          f"{', '.join(_SOURCES_HORAIRE)}. Sans elles, l'analyse serait "
          f"programmee a 22h37.")

# Les utilisateurs etaient espaces de 5 minutes a partir de 22h30, pour etaler
# les appels API plutot que de les lancer tous ensemble :
# 22h30, 22h35, 22h40, 22h45, 22h50.
# Les creneaux decales ont ete SUPPRIMES.
#
# Chaque creneau etait un processus separe, donc un memo qui repartait de
# zero : une valeur detenue par plusieurs utilisateurs etait reinterrogee
# a chaque passage. Mesure sur 5 profils partageant 2 valeurs :
#   groupe  :  68 appels
#   decale  : 120 appels  (+76 %)
# AlphaVantage, plafonne a 25 par jour, passait de 7 a 11.
#
# Tous les profils sont desormais traites en UN SEUL passage
# (portfolio_analyzer.py --all-users), ou le memo partage garantit qu'un
# ticker n'est interroge qu'une fois pour l'ensemble des utilisateurs.
SLOT_PAS_MINUTES = 0

# Planification LOCALE des analyses, desactivee par defaut.
#
# Pourquoi par defaut a l'arret : l'analyse de reference est celle de GitHub
# Actions, qui traite TOUS les profils dans un seul processus (--all-users).
# Un memo partage y garantit qu'une valeur detenue par plusieurs utilisateurs
# n'est interrogee qu'UNE fois.
#
# Un planificateur local produit l'inverse : un processus par utilisateur,
# donc un memo qui repart de zero a chaque creneau. Mesure sur 5 profils
# partageant 2 valeurs : 68 appels en groupe contre 120 en decale, soit
# +76 %. AlphaVantage, plafonne a 25 par jour, passe de 7 a 11.
#
# S'y ajoute un risque plus grave : cette machine n'a pas les cles API. Un
# planificateur actif y produirait chaque soir des rapports aux chiffres
# faux, ecrits dans history.csv, sans aucun message d'erreur.
#
# Mettre PLANIFICATION_LOCALE=1 n'a de sens QUE si les quatre cles API sont
# presentes sur cette machine, et en acceptant le surcout d'appels.
PLANIFICATION_LOCALE = os.getenv("PLANIFICATION_LOCALE", "0") == "1"

# Heure unique d'analyse, identique pour tous. Sert a informer l'utilisateur
# ET a programmer le declenchement : une seule source, donc l'affichage ne
# peut plus mentir sur l'heure reelle. C'etait le cas jusqu'ici : la page
# annoncait « 22h37 » pendant que /api/status renvoyait 22h30, 22h35, 22h40...
HEURE_ANALYSE_GROUPEE = os.getenv(
    "HEURE_ANALYSE_GROUPEE", f"{ANALYSE_HEURE}h{ANALYSE_MINUTE:02d}")

# Declenchement de l'analyse a l'heure, depuis CETTE machine.
#
# POURQUOI. Les crons de GitHub Actions ne sont pas ponctuels. Sur ce depot,
# les declenchements de 20h37 UTC sont arrives entre 22h48 et 23h32 UTC,
# chaque jour, soit plus de deux heures de retard. Aucun reglage cote GitHub
# n'y change quoi que ce soit.
#
# Cette machine est allumee en permanence et son horloge est juste. Elle
# appelle donc GitHub a l'heure dite ; l'analyse continue de tourner chez
# GitHub, ou vivent les cles API. Seul le top depart change de camp.
#
# Ne PAS confondre avec PLANIFICATION_LOCALE, qui ferait tourner l'analyse
# ICI (un processus par utilisateur, sans les cles : des chiffres faux).
DECLENCHEMENT_DISTANT = os.getenv("DECLENCHEMENT_DISTANT", "1") == "1"
WORKFLOW_ANALYSE      = os.getenv("WORKFLOW_ANALYSE", "daily_analysis.yml")
# Jours de declenchement : lundi-vendredi. Les bourses sont fermees le week-end.
JOURS_ANALYSE         = os.getenv("JOURS_ANALYSE", "mon-fri")


def creneau_utilisateur(slot_idx: int) -> tuple:
    """(heure, minute) du creneau d'un utilisateur, heure de Paris.

    RELIQUE. Avec SLOT_PAS_MINUTES = 0, cette fonction renvoie la meme heure
    pour tout le monde : l'analyse est groupee. Elle n'est conservee que pour
    la planification LOCALE (desactivee par defaut) et pour qu'un profil
    ancien ne fasse pas planter le demarrage.

    Ce qui s'affiche a l'utilisateur ne passe plus par ici mais par
    HEURE_ANALYSE_GROUPEE : c'est ce qui garantit que la page n'annonce pas
    une heure differente de celle du declenchement reel.
    """
    total  = ANALYSE_MINUTE + max(0, int(slot_idx)) * SLOT_PAS_MINUTES
    heure  = (ANALYSE_HEURE + total // 60) % 24
    return heure, total % 60


# Conserve pour compatibilite : offsets en minutes apres ANALYSE_HEURE.
SLOT_MINUTES = [ANALYSE_MINUTE + i * SLOT_PAS_MINUTES for i in range(5)]

DATA_DIR.mkdir(exist_ok=True)
PORTFOLIOS.mkdir(exist_ok=True)

# ── Base de données ─────────────────────────────────────────────────
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username    TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'user',
            created_at  TEXT NOT NULL,
            slot_index  INTEGER NOT NULL DEFAULT 0,
            report_url  TEXT NOT NULL DEFAULT ''
        )
    """)
    con.commit()
    # Migration : ajoute les colonnes si absentes (upgrade depuis v1.1)
    cols = [r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()]
    if "slot_index" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN slot_index INTEGER NOT NULL DEFAULT 0")
    if "report_url" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN report_url TEXT NOT NULL DEFAULT ''")
    # Abonnements aux notifications. Un utilisateur peut en avoir plusieurs :
    # un par appareil, et l'iPhone en cree un nouveau a chaque reinstallation
    # du raccourci. L'adresse (endpoint) est l'identifiant unique.
    con.execute("""
        CREATE TABLE IF NOT EXISTS push_subs (
            endpoint   TEXT PRIMARY KEY,
            username   TEXT NOT NULL,
            p256dh     TEXT NOT NULL,
            auth       TEXT NOT NULL,
            appareil   TEXT NOT NULL DEFAULT '',
            cree_le    TEXT NOT NULL
        )
    """)
    con.commit()
    # Compte admin par défaut si la table est vide
    if not con.execute("SELECT 1 FROM users").fetchone():
        # admin123 etait code en dur : un service expose avec ce mot de
        # passe est ouvert a quiconque a lu le depot.
        mdp_admin = ADMIN_PASSWORD or ("admin123" if not INSCRIPTION_LIBRE else "")
        if not mdp_admin:
            raise RuntimeError(
                "Premier demarrage avec INSCRIPTION_LIBRE=1 : definis "
                "ADMIN_PASSWORD avant de lancer le service."
            )
        if mdp_admin == "admin123":
            print("[SECURITE] Compte admin cree avec le mot de passe par defaut.")
            print("           Change-le avant toute exposition du service.")
        hashed = bcrypt.hashpw(mdp_admin.encode(), bcrypt.gensalt()).decode()
        from api.load_portfolio import lien_rapport as _lr
        report_url = _lr("admin", CLOUDFLARE_BASE)
        con.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?)",
            ("admin", hashed, "admin",
             datetime.now(timezone.utc).isoformat(), 0, report_url)
        )
        con.commit()
    con.close()

init_db()

# ── JWT ─────────────────────────────────────────────────────────────
def create_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE)
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> dict:
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expiré")
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/login")

def current_user(token: str = Depends(oauth2)) -> dict:
    return decode_token(token)

def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Réservé à l'admin")
    return user

# ── Analyse d'un utilisateur ─────────────────────────────────────────
from api.load_portfolio import lien_rapport, dossier_rapport


def run_analysis_for(username: str) -> dict:
    """Exporte le portefeuille, lance l'analyseur et génère le rapport HTML.
    Rapport déposé dans docs/<username>/index.html."""
    pfile = PORTFOLIOS / f"portfolio_{username}.json"
    if not pfile.exists():
        return {"success": False, "error": "Aucun portefeuille enregistré"}

    portfolio_data = json.loads(pfile.read_text(encoding="utf-8"))
    lines = portfolio_data.get("lines", [])
    if not lines:
        return {"success": False, "error": "Portefeuille vide"}

    input_file = DATA_DIR / f"active_portfolio_{username}.json"
    input_file.write_text(
        json.dumps({"username": username,
                    "settings": portfolio_data.get("settings", {}),
                    "lines":    lines}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Dossier de sortie propre à l'utilisateur
    out_dir = ROOT / dossier_rapport(username)
    out_dir.mkdir(parents=True, exist_ok=True)

    logs = []
    def run(cmd, label):
        t0 = time.time()
        result = subprocess.run(
            [sys.executable] + cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300
        )
        elapsed = round(time.time() - t0, 1)
        logs.append({"step": label, "returncode": result.returncode,
                     "elapsed_s": elapsed,
                     "stdout": result.stdout[-2000:] if result.stdout else "",
                     "stderr": result.stderr[-2000:] if result.stderr else ""})
        return result.returncode

    rc1 = run([str(ANALYZER), "--portfolio", str(input_file), "--user", username], "portfolio_analyzer")
    rc2 = run([str(GEN_HTML),  "--user", username, "--output", str(out_dir)], "generate_html")
    run([str(GEN_CHART),  "--user", username], "generate_chart")
    run([str(GEN_PORTAL)], "generate_portal")

    success = (rc1 == 0 and rc2 == 0)
    return {
        "success": success,
        "username": username,
        "lines_analyzed": len(lines),
        "report_url": (lien_rapport(username, CLOUDFLARE_BASE) if success else None),
        "logs": logs
    }

# ── Notifications Web Push ───────────────────────────────────────────
#
# Le chiffrement et la signature vivent dans api/push.py, ecrits avec la
# seule bibliotheque `cryptography` pour eviter une compilation a
# l'installation. Ici on ne gere que les abonnements et l'envoi groupe.
#
# RAPPEL IPHONE : la notification n'arrive que si le site a ete ajoute a
# l'ecran d'accueil. Depuis un onglet Safari, Apple refuse l'autorisation
# sans message. Aucun code ne contourne cela.
PUSH_SUJET = os.getenv("PUSH_SUJET", "mailto:admin@localhost")
VAPID_PATH = DATA_DIR / "vapid.json"

try:
    from api import push as _push
    _CLES_PUSH = _push.ClesVapid.charger_ou_creer(VAPID_PATH) if _push.DISPONIBLE else None
except Exception as _e:
    _push, _CLES_PUSH = None, None
    print(f"[push] Module indisponible : {type(_e).__name__}: {_e}")


def etat_push() -> dict:
    """Ce que le serveur sait faire en matiere de notifications."""
    if _push is None:
        return {"disponible": False,
                "motif": "module api/push.py absent ou illisible"}
    if not _push.DISPONIBLE:
        return {"disponible": False,
                "motif": f"bibliotheque cryptography absente ({_push.MOTIF_INDISPO}). "
                         f"Installer avec : pip install cryptography"}
    if _CLES_PUSH is None:
        return {"disponible": False, "motif": "cles VAPID non initialisees"}
    return {"disponible": True, "cle_publique": _CLES_PUSH.publique_b64}


def _abonnements(username: str = None) -> list:
    con = get_db()
    if username:
        rows = con.execute("SELECT * FROM push_subs WHERE username=?",
                           (username,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM push_subs").fetchall()
    con.close()
    return [dict(r) for r in rows]


def _oublier_abonnement(endpoint: str) -> None:
    con = get_db()
    con.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))
    con.commit()
    con.close()


def notifier(username: str, titre: str, corps: str, url: str = "/") -> dict:
    """Notifie tous les appareils d'un utilisateur. Ne leve jamais.

    Un abonnement que le service declare perime est supprime sur-le-champ :
    sinon on le reessaierait chaque soir, indefiniment.
    """
    etat = etat_push()
    if not etat.get("disponible"):
        return {"envoyes": 0, "echecs": 0, "motif": etat.get("motif")}

    message = {"titre": titre, "corps": corps, "url": url,
               "quand": datetime.now(timezone.utc).astimezone().strftime("%H:%M")}
    envoyes = echecs = 0
    for ab in _abonnements(username):
        r = _push.envoyer(ab, message, _CLES_PUSH, PUSH_SUJET)
        if r.ok:
            envoyes += 1
        else:
            echecs += 1
            if r.perime:
                _oublier_abonnement(ab["endpoint"])
                print(f"[push] Abonnement perime retire pour {username}.")
            else:
                print(f"[push] Echec vers {username} : {r.code} {r.detail[:120]}")
    return {"envoyes": envoyes, "echecs": echecs}


def notifier_tous(titre: str, corps: str, url: str = "/") -> dict:
    """Meme chose, pour tous les comptes ayant un abonnement."""
    total = {"envoyes": 0, "echecs": 0}
    vus = {a["username"] for a in _abonnements()}
    for u in vus:
        r = notifier(u, titre, corps, url)
        total["envoyes"] += r.get("envoyes", 0)
        total["echecs"] += r.get("echecs", 0)
    if vus:
        print(f"[push] {titre} -> {total['envoyes']} envoi(s), "
              f"{total['echecs']} echec(s) sur {len(vus)} compte(s).")
    return total


# ── Scheduler APScheduler ────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Europe/Paris")

def _scheduled_job(username: str):
    print(f"[Scheduler] Déclenchement analyse pour '{username}' — {datetime.now()}")
    result = run_analysis_for(username)
    status_str = "✅ OK" if result.get("success") else f"❌ Erreur: {result.get('error', '?')}"
    print(f"[Scheduler] {username} → {status_str}")

def _sync_configure() -> bool:
    """github_sync est-il utilisable ? Import tolerant : le module peut manquer."""
    try:
        from api import github_sync
        return github_sync.est_configure()
    except Exception:
        return False


def _publier_liens_rapport():
    """Pousse data/report_links.json vers le depot. Ne leve jamais."""
    try:
        from api import github_sync
        from api.load_portfolio import charger_liens
        table = charger_liens()
        if not table:
            print("[Liens] Aucun jeton local a publier.")
            return
        res = github_sync.pousser_liens(table)
        marque = "OK" if res.get("ok") else "ECHEC"
        print(f"[Liens] Publication de {len(table)} jeton(s) : {marque} "
              f"({res.get('etat')}) {res.get('detail', '')}")
    except Exception as e:
        print(f"[Liens] Publication impossible : {type(e).__name__}: {e}")


def _declencher_analyse_distante():
    """Demande a GitHub de lancer l'analyse. Appele par le planificateur.

    Ne leve jamais : une panne reseau a 22h37 ne doit pas tuer le
    planificateur, sinon le tir du lendemain ne partirait pas non plus.
    """
    horodatage = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    try:
        from api import github_sync
        res = github_sync.declencher_analyse(WORKFLOW_ANALYSE)
    except Exception as e:
        res = {"ok": False, "etat": "erreur", "detail": f"{type(e).__name__}: {e}"}

    global _DERNIER_DECLENCHEMENT
    _DERNIER_DECLENCHEMENT = {"quand": horodatage, **res}
    _ecrire_dernier_declenchement(_DERNIER_DECLENCHEMENT)

    # Une notification par abonne : c'est le seul moment ou le serveur sait
    # avec certitude qu'il se passe quelque chose.
    if res.get("ok"):
        notifier_tous("Analyse lancee",
                      f"L'analyse de ce soir est partie a {horodatage[-5:]}. "
                      f"Le rapport sera pret dans quelques minutes.",
                      "/")
    marque = "OK" if res.get("ok") else "ECHEC"
    print(f"[Analyse] {horodatage} — declenchement GitHub : {marque} "
          f"({res.get('etat')}) {res.get('detail', '')}")


# Dernier declenchement tente, expose par /api/status pour pouvoir verifier
# depuis le site que le tir de la veille est bien parti.
#
# CONSERVE SUR DISQUE. Tant qu'il ne vivait qu'en memoire, un redemarrage du
# service le remettait a zero : /api/status affichait « null » en permanence,
# et il devenait impossible de savoir si le declenchement de 22h37 avait
# fonctionne la veille. C'est exactement le doute qu'on cherchait a lever.
DECLENCHEMENT_PATH = DATA_DIR / "dernier_declenchement.json"


def _lire_dernier_declenchement() -> dict:
    try:
        return json.loads(DECLENCHEMENT_PATH.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _ecrire_dernier_declenchement(valeur: dict) -> None:
    try:
        DECLENCHEMENT_PATH.write_text(
            json.dumps(valeur, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[Analyse] Trace du declenchement non ecrite : {e}")


_DERNIER_DECLENCHEMENT: dict = _lire_dernier_declenchement()


def rebuild_scheduler():
    """Relit la BDD et synchronise les jobs APScheduler."""
    scheduler.remove_all_jobs()

    # ── Declenchement a l'heure, depuis cette machine ──────────────────────
    # Un seul job pour tout le monde : l'analyse est groupee cote GitHub.
    if DECLENCHEMENT_DISTANT:
        scheduler.add_job(
            _declencher_analyse_distante,
            trigger=CronTrigger(hour=ANALYSE_HEURE, minute=ANALYSE_MINUTE,
                                day_of_week=JOURS_ANALYSE,
                                timezone="Europe/Paris"),
            id="declenchement_github",
            replace_existing=True,
            misfire_grace_time=3600,   # une coupure d'une heure ne perd pas le tir
            coalesce=True,             # jamais deux tirs pour un seul retard
        )
        print(f"[Scheduler] Declenchement GitHub programme : "
              f"{ANALYSE_HEURE}h{ANALYSE_MINUTE:02d} Paris, {JOURS_ANALYSE}.")
        if not _sync_configure():
            print("            ATTENTION : GITHUB_TOKEN/GITHUB_REPO absents, "
                  "le declenchement echouera.")

    # ── Rattrapage au demarrage : publier la table des jetons ──────────────
    # Les jetons de rapport sont fabriques ICI et doivent exister dans le
    # depot, sinon GitHub Actions en genere d'autres au moment de publier et
    # les adresses remises aux utilisateurs ne menent nulle part. C'est
    # exactement ce qui est arrive aux comptes crees apres adrien.
    #
    # Le correctif pousse la table a chaque inscription, mais les comptes
    # deja crees restent orphelins : ce rattrapage les recupere, une fois,
    # au demarrage du service. Differe de 20 secondes pour ne pas retarder
    # l'ouverture du port.
    scheduler.add_job(
        _publier_liens_rapport,
        trigger="date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=20),
        id="rattrapage_liens",
        replace_existing=True,
    )

    if not PLANIFICATION_LOCALE:
        print("[Scheduler] Planification locale desactivee (analyse executee "
              "par GitHub Actions, en un seul passage pour tous les profils).")
        return

    manquantes = [k for k, v in (("FINNHUB_API_KEY", os.getenv("FINNHUB_API_KEY")),
                                 ("EODHD_API_KEY", os.getenv("EODHD_API_KEY")),
                                 ("TWELVEDATA_API_KEY", os.getenv("TWELVEDATA_API_KEY")),
                                 ("ALPHAVANTAGE_API_KEY", os.getenv("ALPHAVANTAGE_API_KEY")))
                  if not v]
    if manquantes:
        # Sans cles, l'analyseur ne s'arrete pas : il produit des cours
        # aberrants et les ecrit dans l'historique. Mieux vaut ne rien
        # planifier que de corrompre les donnees en silence.
        print(f"[Scheduler] Planification locale demandee mais cles absentes : "
              f"{', '.join(manquantes)}")
        print("            Aucun job enregistre : une analyse sans cles produirait")
        print("            des chiffres faux et polluerait history.csv.")
        return

    con = get_db()
    rows = con.execute("SELECT username, slot_index FROM users").fetchall()
    con.close()
    for row in rows:
        uname      = row["username"]
        slot_idx   = row["slot_index"]
        hour, minute = creneau_utilisateur(slot_idx)
        scheduler.add_job(
            _scheduled_job,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Europe/Paris"),
            args=[uname],
            id=f"analyze_{uname}",
            replace_existing=True
        )
        print(f"[Scheduler] Job enregistré : {uname} → {hour}h{minute:02d} heure Paris")

scheduler.start()
rebuild_scheduler()

# ── App FastAPI ──────────────────────────────────────────────────────
app = FastAPI(title="Portfolio Analyzer — Backend local", version="1.2")

# Monte chaque sous-dossier docs/<username> dynamiquement
# Note : le montage statique global /report pointe sur docs/
docs_dir = ROOT / "docs"
docs_dir.mkdir(exist_ok=True)
app.mount("/report", StaticFiles(directory=str(docs_dir), html=True), name="report")

# ── Modèles ──────────────────────────────────────────────────────────
class PortfolioLine(BaseModel):
    """Une ligne telle que saisie dans l'interface.

    Un seul ticker suffit : api/load_portfolio.py en dérive les variantes
    attendues par chaque fournisseur de données.

    Depuis la v8 la ligne peut décrire un actif NON COTÉ (livret, immobilier,
    collection). Dans ce cas `ticker`, `quantity` et `buy_price` n'ont pas de
    sens : seul `value` est renseigné. C'est pourquoi ces trois champs sont
    devenus facultatifs — la validation réelle est faite par
    api/load_portfolio.normaliser_ligne(), qui connaît la règle par classe
    d'actif et renvoie un message d'erreur lisible.
    """
    name:        str
    ticker:      Optional[str] = None
    isin:        Optional[str] = ""
    quantity:    Optional[float] = None
    buy_price:   Optional[float] = None
    market:      Optional[str] = None    # code de place, voir MARCHES
    currency:    Optional[str] = None    # déduit de la place si absent
    asset_type:  Optional[str] = "action"
    asset_class: Optional[str] = None    # action, etf, crypto, cash, immobilier…
    account:     Optional[str] = ""      # compte / courtier détenteur
    tags:        Optional[List[str]] = None
    stop:        Optional[dict] = None   # {"type": "trailing", "value": 15}
    value:       Optional[float] = None  # actifs non cotés : valeur actuelle
    buy_value:   Optional[float] = None  # actifs non cotés : prix d'acquisition

class WatchItem(BaseModel):
    name:   str
    ticker: str
    market: Optional[str] = "us"
    sector: Optional[str] = ""

class ProfileSettings(BaseModel):
    broker:        Optional[str]  = "autre"
    custom_fees:   Optional[dict] = None
    indices:       Optional[List[str]] = None
    watchlist:     Optional[List[WatchItem]] = None
    # Réglages de risque (bornés par api/load_portfolio.normalize_profile)
    risque_pct:    Optional[float] = None   # % du capital risqué par idée
    poids_max_pct: Optional[float] = None   # plafond de poids par ligne
    vol_cible_pct: Optional[float] = None   # volatilité visée par ligne
    liquidites:    Optional[float] = None   # cash disponible pour de nouvelles entrées
    stop_defaut:   Optional[dict]  = None   # stop appliqué aux lignes sans stop
    capital_reference: Optional[float] = None  # force le capital de dimensionnement

class VenteRealisee(BaseModel):
    """Une position soldee, conservee hors du portefeuille courant.

    Le rapport photographie le portefeuille a l'instant T : une ligne vendue
    en disparait, et le gain qu'elle a produit avec elle. Ce registre en garde
    la trace, et portfolio_analyzer.compute_closed_trades() le lit tel quel.

    `buy_price_eur` est un prix de revient EN EUROS ; `sell_price` est exprime
    dans `sell_currency` et converti par `fx_at_sale`, taux FIGE au jour de la
    vente. Le gain de change fait partie du resultat : le recalculer avec un
    taux posterieur le fausserait.
    """
    name:          str
    ticker:        Optional[str] = ""
    qty:           float
    buy_price_eur: float
    sell_price:    float
    sell_currency: Optional[str] = "EUR"
    fx_at_sale:    Optional[float] = 1.0
    sell_date:     Optional[str] = ""
    marche:        Optional[str] = "euronext"
    note:          Optional[str] = ""


class PortfolioSave(BaseModel):
    lines:    List[PortfolioLine]
    settings: Optional[ProfileSettings] = None
    # Absent => on conserve le registre existant. Present => il remplace
    # l'ancien : c'est ce qui permet de corriger ou supprimer une vente.
    closed:   Optional[List[VenteRealisee]] = None

class UserCreate(BaseModel):
    username: str
    password: str
    role:     Optional[str] = "user"

# ── Routes ───────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def serve_interface():
    if INTERFACE.exists():
        return FileResponse(str(INTERFACE), media_type="text/html")
    raise HTTPException(status_code=404, detail="interface.html introuvable")


VERSION_APP = "8.1"


@app.get("/api/version")
def version_app():
    """Version reellement en service sur CETTE machine.

    Sert a repondre a une question simple et jusqu'ici sans reponse : le
    fichier que je viens de corriger est-il celui qui tourne ? Le doute a
    coute une semaine sur ce projet, ou deux correctifs presents dans le
    depot n'etaient pas actifs sur le serveur.
    """
    import platform
    try:
        horodatage = datetime.fromtimestamp(
            Path(__file__).stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        horodatage = None
    return {
        "version":            VERSION_APP,
        "fichier_backend":    str(Path(__file__)),
        "modifie_le":         horodatage,
        "python":             platform.python_version(),
        "heure_analyse":      HEURE_ANALYSE_GROUPEE,
        "heure_source":       (", ".join(_SOURCES_HORAIRE)
                               if _SOURCES_HORAIRE else "valeur par defaut du code"),
        "max_users":          MAX_USERS,
        "push":               etat_push(),
        "etalement_creneaux": SLOT_PAS_MINUTES,
        "declenchement_distant": DECLENCHEMENT_DISTANT,
        "analyse_manuelle":   ANALYSE_MANUELLE_OUVERTE,
        "inscription_libre":  INSCRIPTION_LIBRE,
        "cloudflare_base":    CLOUDFLARE_BASE,
    }


# ── Fichiers exiges par iOS pour une application installee ───────────
#
# Apple ne delivre de notification que si le site a ete ajoute a l'ecran
# d'accueil. Pour cela il lui faut un manifeste et des icones, et le
# travailleur de service doit etre servi depuis la RACINE du site, sinon sa
# portee ne couvre pas les pages.

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifeste():
    f = ROOT / "manifest.webmanifest"
    if f.exists():
        return FileResponse(str(f), media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="manifest.webmanifest introuvable")


@app.get("/sw.js", include_in_schema=False)
def travailleur_de_service():
    f = ROOT / "sw.js"
    if f.exists():
        # Pas de cache : un travailleur de service fige est tres penible a
        # remplacer une fois installe sur un telephone.
        return FileResponse(str(f), media_type="application/javascript",
                            headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="sw.js introuvable")


@app.get("/icone-{taille}.png", include_in_schema=False)
def icone(taille: str):
    if taille not in ("180", "192", "512"):
        raise HTTPException(status_code=404, detail="Taille inconnue")
    f = ROOT / f"icone-{taille}.png"
    if f.exists():
        return FileResponse(str(f), media_type="image/png")
    raise HTTPException(status_code=404, detail="Icone introuvable")


# ── Abonnements aux notifications ────────────────────────────────────

class DesabonnementPush(BaseModel):
    endpoint: str = ""


class AbonnementPush(BaseModel):
    endpoint: str
    p256dh:   str
    auth:     str
    appareil: Optional[str] = ""


@app.get("/api/push/cle-publique")
def push_cle_publique(user: dict = Depends(current_user)):
    """Ce que le navigateur doit connaitre pour s'abonner."""
    etat = etat_push()
    etat["abonnements"] = len(_abonnements(user["sub"]))
    return etat


@app.post("/api/push/abonnement", status_code=201)
def push_abonner(data: AbonnementPush, user: dict = Depends(current_user)):
    if not etat_push().get("disponible"):
        raise HTTPException(status_code=503,
                            detail=etat_push().get("motif", "Notifications indisponibles"))
    con = get_db()
    con.execute(
        "INSERT INTO push_subs (endpoint, username, p256dh, auth, appareil, cree_le) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(endpoint) DO UPDATE SET username=excluded.username, "
        "p256dh=excluded.p256dh, auth=excluded.auth, appareil=excluded.appareil",
        (data.endpoint, user["sub"], data.p256dh, data.auth,
         (data.appareil or "")[:120], datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()
    return {"ok": True, "abonnements": len(_abonnements(user["sub"]))}


@app.delete("/api/push/abonnement")
def push_desabonner(corps: Optional[DesabonnementPush] = Body(default=None),
                    endpoint: str = "", user: dict = Depends(current_user)):
    """Desabonne UN appareil, celui dont l'adresse est fournie.

    L'adresse passe par le corps de la requete et non par l'URL : c'est un
    identifiant d'appareil, il n'a rien a faire dans un journal de serveur.
    Sans adresse, on retombe sur l'ancien comportement — tous les appareils —
    ce qui reste utile pour repartir de zero.
    """
    cible = ((corps.endpoint if corps else "") or endpoint or "").strip()
    con = get_db()
    if cible:
        con.execute("DELETE FROM push_subs WHERE endpoint=? AND username=?",
                    (cible, user["sub"]))
    else:
        con.execute("DELETE FROM push_subs WHERE username=?", (user["sub"],))
    con.commit()
    con.close()
    return {"ok": True, "abonnements": len(_abonnements(user["sub"]))}


@app.post("/api/push/test")
def push_test(user: dict = Depends(current_user)):
    """Envoie une notification a soi-meme, pour verifier toute la chaine."""
    _verrou(f"push:{user['sub']}", maximum=10)
    if not _abonnements(user["sub"]):
        raise HTTPException(
            status_code=400,
            detail="Aucun appareil abonne. Activez d'abord les notifications.")
    r = notifier(user["sub"], "ProjectOne",
                 "Notification de test : la chaine fonctionne.", "/")
    if not r.get("envoyes"):
        raise HTTPException(
            status_code=502,
            detail=("Aucun envoi n'a abouti. " + str(r.get("motif") or "")).strip())
    return r


@app.get("/api/status")
def status_check():
    con = get_db()
    nb_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    rows = con.execute("SELECT username, slot_index, report_url FROM users ORDER BY slot_index").fetchall()
    con.close()
    # Une seule heure pour tout le monde. Les creneaux etales de 5 minutes
    # (22h30, 22h35, 22h40...) ont ete supprimes : l'analyse est GROUPEE,
    # un seul passage traite tous les profils et mutualise les appels API.
    # Cette liste conserve la cle "slot" pour ne pas casser une interface
    # ancienne, mais elle vaut la meme chose sur toutes les lignes.
    slots = []
    for r in rows:
        slots.append({
            "username":   r["username"],
            "slot":       HEURE_ANALYSE_GROUPEE,
            "report_url": lien_rapport(r["username"], CLOUDFLARE_BASE)
        })
    return {
        "status":   "ok",
        "users":    nb_users,
        "max_users": MAX_USERS,
        "time":     datetime.now(timezone.utc).isoformat(),
        "analyse": {
            "heure":     HEURE_ANALYSE_GROUPEE,
            "fuseau":    "Europe/Paris",
            "jours":     JOURS_ANALYSE,
            "groupee":   True,
            "declenchee_par": ("ce serveur (a l'heure), avec les crons GitHub "
                               "en filet de securite"
                               if DECLENCHEMENT_DISTANT
                               else "les crons GitHub Actions uniquement"),
            # On relit le fichier plutot que la variable en memoire : si
            # l'analyse a ete lancee par un autre processus (cron GitHub,
            # second worker uvicorn), la variable de CELUI-CI n'en sait rien
            # et la page afficherait « null » alors que tout a fonctionne.
            "dernier_declenchement": (_lire_dernier_declenchement()
                                      or _DERNIER_DECLENCHEMENT or None),
        },
        "schedule": slots
    }


# Limitation des tentatives, en memoire. Suffisant pour un service a cinq
# comptes : sans elle, rien n'empeche d'essayer des mots de passe en boucle.
_TENTATIVES: dict = {}
_MAX_TENTATIVES = 8
_FENETRE_S      = 300          # 8 essais par tranche de 5 minutes


def _verrou(cle: str, maximum: int = _MAX_TENTATIVES):
    maintenant = time.time()
    essais = [t for t in _TENTATIVES.get(cle, []) if maintenant - t < _FENETRE_S]
    if len(essais) >= maximum:
        attente = int(_FENETRE_S - (maintenant - essais[0]))
        raise HTTPException(
            status_code=429,
            detail=f"Trop de tentatives. Reessaie dans {max(1, attente // 60) } minute(s)."
        )
    essais.append(maintenant)
    _TENTATIVES[cle] = essais


def _slug_utilisateur(brut: str) -> str:
    """Identifiant sur : minuscules, lettres, chiffres, tirets.

    Le nom devient un nom de fichier (portfolio_<nom>.json) et un dossier.
    Laisser passer un point ou une barre oblique permettrait d'ecrire
    ailleurs que dans data/portfolios/.
    """
    import re as _re2
    net = _re2.sub(r"[^a-z0-9_-]+", "-", str(brut or "").strip().lower()).strip("-")
    return net[:24]


def _trouver_utilisateur(con, saisi: str):
    """Retrouve un compte a partir de ce que l'utilisateur a tape.

    CORRECTION — C'ETAIT LE BOGUE DE CONNEXION
    ------------------------------------------
    L'inscription normalise le nom (minuscules, espaces retires) : qui
    s'inscrit sous « Pete33 » est enregistre « pete33 ». La connexion, elle,
    interrogeait la base avec le texte brut. Se reconnecter en tapant son nom
    exactement comme a l'inscription renvoyait donc « Identifiants
    incorrects », sans aucun moyen de comprendre pourquoi. Un espace laisse
    par la saisie automatique du telephone suffisait aussi.

    On cherche desormais d'abord tel quel — pour ne pas casser un compte
    ancien dont le nom stocke ne serait pas normalise — puis sur le nom
    normalise.
    """
    brut = str(saisi or "")
    row = con.execute(
        "SELECT username, password_hash, role FROM users WHERE username=?",
        (brut,)).fetchone()
    if row:
        return row
    net = _slug_utilisateur(brut)
    if net and net != brut:
        return con.execute(
            "SELECT username, password_hash, role FROM users WHERE username=?",
            (net,)).fetchone()
    return None


@app.post("/api/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    # Le verrou porte sur le nom NORMALISE : sinon il suffisait de changer la
    # casse a chaque essai pour repartir a zero et tester des mots de passe
    # en boucle.
    cle_verrou = f"login:{_slug_utilisateur(form.username)}"
    _verrou(cle_verrou)
    con = get_db()
    row = _trouver_utilisateur(con, form.username)
    con.close()
    if not row or not bcrypt.checkpw(form.password.encode(), row["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    _TENTATIVES.pop(cle_verrou, None)
    # A partir d'ici on n'utilise QUE le nom stocke en base : le jeton, les
    # chemins de fichiers et les droits en dependent.
    nom = row["username"]
    token = create_token(nom, row["role"])
    return {
        "access_token": token,
        "token_type":   "bearer",
        "username":     nom,
        "role":         row["role"],
        # Recalculee a chaque connexion, jamais relue depuis la base : la
        # colonne report_url est un instantane fige a la creation du compte.
        # Si CLOUDFLARE_PAGES_URL a ete renseigne apres coup, ou si le compte
        # a ete renomme, cette colonne reste fausse indefiniment.
        "report_url":   lien_rapport(nom, CLOUDFLARE_BASE)
    }


@app.get("/api/portfolio/{username}")
def get_portfolio(username: str, user: dict = Depends(current_user)):
    if user["sub"] != username and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès interdit")
    pfile = PORTFOLIOS / f"portfolio_{username}.json"
    if not pfile.exists():
        return {"lines": []}
    return json.loads(pfile.read_text(encoding="utf-8"))


@app.post("/api/portfolio/{username}")
def save_portfolio(username: str, data: PortfolioSave, user: dict = Depends(current_user)):
    if user["sub"] != username and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès interdit")
    pfile = PORTFOLIOS / f"portfolio_{username}.json"
    settings = data.settings.model_dump() if data.settings else {}
    if settings.get("watchlist"):
        settings["watchlist"] = [w for w in settings["watchlist"] if w.get("name")]
    # Ne pas ecrire de reglage a None : sinon un enregistrement depuis
    # l'interface ecraserait une valeur choisie a la main dans le JSON par un
    # null, et la normalisation retomberait sur le defaut sans prevenir.
    settings = {k: v for k, v in settings.items() if v is not None}

    # CORRECTION : l'historique des ventes vit dans le meme fichier mais n'est
    # PAS gere par l'interface. Sans cette reprise, chaque enregistrement du
    # portefeuille effacait silencieusement toutes les plus-values realisees.
    ancien = {}
    if pfile.exists():
        try:
            ancien = json.loads(pfile.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            ancien = {}

    pfile.write_text(
        json.dumps({
            "username": username,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "settings": settings,
            # Sans cette reprise, chaque enregistrement du portefeuille
            # effacait silencieusement toutes les plus-values realisees.
            "closed":   ([v.model_dump() for v in data.closed]
                         if data.closed is not None
                         else ancien.get("closed", [])),
            "lines":    [{k: v for k, v in l.model_dump().items() if v is not None}
                         for l in data.lines]
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Contrôle immédiat : on renvoie les lignes rejetées pour que l'interface
    # puisse les signaler à l'utilisateur avant qu'il lance une analyse.
    erreurs = []
    try:
        from api.load_portfolio import load_profile
        erreurs = load_profile(str(pfile), username).get("erreurs", [])
    except Exception:
        pass

    # Le rapport quotidien est produit par GitHub Actions, qui ne lit que le
    # depot. Sans cette poussee, un stop pose ici resterait invisible demain.
    # L'ecriture locale a deja reussi : une panne de synchronisation est
    # signalee, jamais bloquante.
    try:
        from api import github_sync
        sync = github_sync.pousser_profil(username,
                                          json.loads(pfile.read_text(encoding="utf-8")))
    except Exception as e:
        sync = {"ok": False, "etat": "erreur", "detail": f"{type(e).__name__}: {e}"}

    return {"saved": len(data.lines), "file": str(pfile),
            "erreurs": erreurs, "sync": sync}


@app.get("/api/sync-status")
def sync_status(user: dict = Depends(current_user)):
    """Etat de la synchronisation GitHub, affiche dans l'interface."""
    from api import github_sync
    return github_sync.etat()


@app.get("/api/brokers")
def list_brokers():
    """Catalogue des courtiers proposés dans l'interface."""
    from api.load_portfolio import charger_courtiers
    cat = charger_courtiers()
    return [{"code": c, "label": f.get("label", c), "note": f.get("note", ""),
             "fees": f.get("fees", {})} for c, f in cat.items()]


@app.get("/api/markets")
def list_markets():
    """Places de cotation reconnues, pour alimenter le menu déroulant."""
    from api.load_portfolio import MARCHES
    return [{"code": c, "label": f["label"], "devise": f["devise"],
             "suffixe": f["suffixe"], "marche": f.get("marche", "euronext")}
            for c, f in MARCHES.items()]


@app.get("/api/asset-classes")
def list_asset_classes():
    """Classes d'actifs reconnues, pour alimenter le menu déroulant.

    `manuel` dit à l'interface s'il faut demander un ticker et une quantité
    (False) ou une simple valeur (True).
    """
    from api.load_portfolio import CLASSES_ACTIFS
    return [{"code": c, "label": f["label"], "manuel": f["manuel"],
             "place": f.get("place")}
            for c, f in sorted(CLASSES_ACTIFS.items(), key=lambda kv: kv[1]["ordre"])]


@app.get("/api/stop-types")
def list_stop_types():
    """Types de stop reconnus, avec leur libellé et le paramètre attendu."""
    return [
        {"code": "none",     "label": "Aucun",           "parametre": None},
        {"code": "percent",  "label": "Pourcentage",     "parametre": "% sous le prix de revient"},
        {"code": "absolute", "label": "Absolu",          "parametre": "prix plancher"},
        {"code": "trailing", "label": "Suiveur",         "parametre": "% sous le plus haut"},
        {"code": "vq",       "label": "VQ (volatilite)", "parametre": None},
    ]


# Analyse manuelle : FERMEE.
#
# Le bouton a ete retire de l'interface, mais retirer un bouton ne ferme pas
# une porte : l'adresse restait appelable directement. Or une analyse lancee
# ICI tourne sans les cles API, produit des cours faux et les ecrit dans
# history.csv — un historique corrompu ne se repare pas.
#
# La route est conservee plutot que supprimee, pour qu'un onglet reste ouvert
# sur une ancienne version de la page recoive une explication au lieu d'un
# « 404 » incomprehensible.
ANALYSE_MANUELLE_OUVERTE = os.getenv("ANALYSE_MANUELLE_OUVERTE", "0") == "1"


@app.post("/api/analyze/{username}")
def trigger_analysis(username: str, user: dict = Depends(current_user)):
    """Analyse manuelle — desactivee."""
    if not ANALYSE_MANUELLE_OUVERTE:
        raise HTTPException(
            status_code=403,
            detail=(f"Le lancement manuel est desactive. L'analyse part "
                    f"automatiquement a {HEURE_ANALYSE_GROUPEE} (heure de Paris), "
                    f"du lundi au vendredi, pour tous les portefeuilles a la fois."))
    if user["sub"] != username and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès interdit")
    result = run_analysis_for(username)
    if not result.get("success") and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class ChangementMotDePasse(BaseModel):
    ancien: str
    nouveau: str


class ChangementNom(BaseModel):
    nouveau: str
    mot_de_passe: str


@app.post("/api/account/password")
def changer_mot_de_passe(data: ChangementMotDePasse,
                         user: dict = Depends(current_user)):
    """Change son propre mot de passe.

    L'ancien mot de passe est exige : sans cela, un jeton vole suffirait a
    verrouiller le compte de son proprietaire.
    """
    _verrou(f"pwd:{user['sub']}")

    con = get_db()
    row = con.execute("SELECT password_hash FROM users WHERE username=?",
                      (user["sub"],)).fetchone()
    if not row or not bcrypt.checkpw(data.ancien.encode(), row["password_hash"].encode()):
        con.close()
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect.")

    if len(data.nouveau) < 10:
        con.close()
        raise HTTPException(status_code=422,
                            detail="Le nouveau mot de passe doit faire au moins "
                                   "10 caracteres.")
    if data.nouveau == data.ancien:
        con.close()
        raise HTTPException(status_code=422,
                            detail="Le nouveau mot de passe est identique a l'ancien.")

    hashed = bcrypt.hashpw(data.nouveau.encode(), bcrypt.gensalt()).decode()
    con.execute("UPDATE users SET password_hash=? WHERE username=?",
                (hashed, user["sub"]))
    con.commit()
    con.close()
    _TENTATIVES.pop(f"pwd:{user['sub']}", None)
    return {"ok": True, "message": "Mot de passe modifie."}


@app.post("/api/account/username")
def changer_nom(data: ChangementNom, user: dict = Depends(current_user)):
    """Renomme son propre compte.

    Le nom d'utilisateur n'est pas qu'une etiquette : il designe le fichier
    de profil (portfolio_<nom>.json), le dossier de rapports et le jeton du
    lien public. Tout doit suivre, sinon le compte pointerait vers un profil
    vide pendant que les vraies donnees resteraient orphelines.

    Cas particulier volontaire : si un profil porte DEJA le nouveau nom et
    contient des lignes, il est conserve tel quel. C'est la situation du
    compte « admin » cree par le systeme alors que les donnees reelles
    vivent sous un autre nom : on rattache le compte aux donnees, on
    n'ecrase jamais les donnees avec un profil vide.
    """
    ancien = user["sub"]
    nouveau = _slug_utilisateur(data.nouveau)

    if len(nouveau) < 3:
        raise HTTPException(status_code=422,
                            detail="Le nom doit faire au moins 3 caracteres "
                                   "(lettres, chiffres et tirets).")
    if nouveau == ancien:
        raise HTTPException(status_code=422, detail="C'est deja ton nom actuel.")

    _verrou(f"rename:{ancien}")

    con = get_db()
    row = con.execute("SELECT * FROM users WHERE username=?", (ancien,)).fetchone()
    if not row or not bcrypt.checkpw(data.mot_de_passe.encode(),
                                     row["password_hash"].encode()):
        con.close()
        raise HTTPException(status_code=401, detail="Mot de passe incorrect.")
    if con.execute("SELECT 1 FROM users WHERE username=?", (nouveau,)).fetchone():
        con.close()
        raise HTTPException(status_code=409, detail="Ce nom est deja pris.")

    src  = PORTFOLIOS / f"portfolio_{ancien}.json"
    dst  = PORTFOLIOS / f"portfolio_{nouveau}.json"

    def _lignes(f):
        try:
            return len(json.loads(f.read_text(encoding="utf-8")).get("lines") or [])
        except Exception:
            return 0

    remarque = ""
    if dst.exists() and _lignes(dst) > 0:
        # Les donnees en place priment. On refuse d'ecraser un portefeuille
        # rempli par un profil vide.
        if _lignes(src) > 0:
            con.close()
            raise HTTPException(
                status_code=409,
                detail=f"Un portefeuille existe deja sous « {nouveau} » ET sous "
                       f"« {ancien} », tous deux remplis. Fusionne-les a la main "
                       f"avant de renommer.")
        remarque = (f"Le portefeuille existant de « {nouveau} » a ete conserve : "
                    f"ton compte y est desormais rattache.")
        if src.exists():
            src.unlink()
    elif src.exists():
        profil = json.loads(src.read_text(encoding="utf-8"))
        profil["username"] = nouveau
        dst.write_text(json.dumps(profil, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        src.unlink()

    # Le jeton du lien public suit le compte, pour ne pas invalider une
    # adresse deja transmise. Si le nouveau nom en possede deja un, il est
    # conserve : c'est lui qui correspond aux rapports publies.
    try:
        from api.load_portfolio import charger_liens, enregistrer_liens
        table = charger_liens()
        if not table.get(nouveau) and table.get(ancien):
            table[nouveau] = table[ancien]
        table.pop(ancien, None)
        enregistrer_liens(table)
    except Exception as e:
        print(f"[Renommage] Jeton non transfere : {e}")

    # Historique et graphiques
    a_rep, n_rep = ROOT / "reports" / ancien, ROOT / "reports" / nouveau
    if a_rep.exists() and not n_rep.exists():
        try:
            a_rep.rename(n_rep)
        except Exception as e:
            print(f"[Renommage] Dossier reports non deplace : {e}")

    con.execute("UPDATE users SET username=? WHERE username=?", (nouveau, ancien))
    con.commit()
    con.close()

    # Depot : publier le profil sous le nouveau nom, retirer l'ancien.
    sync = {"etat": "non configure"}
    try:
        from api import github_sync
        if dst.exists():
            sync = github_sync.pousser_profil(
                nouveau, json.loads(dst.read_text(encoding="utf-8")))
        github_sync.supprimer_fichier(
            f"data/portfolios/portfolio_{ancien}.json",
            f"Compte {ancien} renomme en {nouveau}")
        from api.load_portfolio import charger_liens as _cl
        github_sync.pousser_liens(_cl())
    except Exception as e:
        sync = {"ok": False, "etat": "erreur", "detail": f"{type(e).__name__}: {e}"}

    if scheduler.running:
        try:
            scheduler.remove_job(f"analyse_{ancien}")
        except Exception:
            pass
        slot_h, slot_m = creneau_utilisateur(row["slot_index"])
        scheduler.add_job(
            func=lambda u=nouveau: run_analysis_for(u),
            trigger=CronTrigger(hour=slot_h, minute=slot_m, timezone="Europe/Paris"),
            id=f"analyse_{nouveau}", replace_existing=True,
        )

    return {"ok": True, "ancien": ancien, "nouveau": nouveau,
            "remarque": remarque, "sync": sync,
            "message": "Nom modifie. Reconnecte-toi avec le nouveau nom."}


@app.get("/api/users")
def list_users(admin: dict = Depends(require_admin)):
    con = get_db()
    rows = con.execute(
        "SELECT username, role, created_at, slot_index, report_url FROM users ORDER BY slot_index"
    ).fetchall()
    con.close()
    result = []
    for r in rows:
        result.append({
            "username":   r["username"],
            "role":       r["role"],
            "created_at": r["created_at"],
            "slot":       f"{HEURE_ANALYSE_GROUPEE} (Paris)",
            "report_url": lien_rapport(r["username"], CLOUDFLARE_BASE)
        })
    return result


class Inscription(BaseModel):
    username: str
    password: str


@app.get("/api/inscription-ouverte")
def inscription_ouverte():
    """Consulte par l'interface pour afficher ou non le formulaire."""
    con = get_db()
    nb = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    return {"ouverte": INSCRIPTION_LIBRE and nb < MAX_USERS,
            "places_restantes": max(0, MAX_USERS - nb),
            "max": MAX_USERS}


@app.post("/api/register", status_code=201)
def register(data: Inscription):
    """Inscription autonome, sans intervention de l'administrateur.

    Volontairement fermee par defaut : elle ne s'active qu'avec
    INSCRIPTION_LIBRE=1, pour qu'un service lance en local ne devienne pas
    ouvert par accident.
    """
    if not INSCRIPTION_LIBRE:
        raise HTTPException(status_code=403,
                            detail="Les inscriptions ne sont pas ouvertes.")

    _verrou(f"register:global", maximum=20)

    nom = _slug_utilisateur(data.username)
    if len(nom) < 3:
        raise HTTPException(status_code=422,
                            detail="Le nom doit faire au moins 3 caracteres "
                                   "(lettres, chiffres et tirets).")
    if len(data.password) < 10:
        # Ce mot de passe protege un portefeuille reel sur un service
        # joignable depuis internet : six caracteres ne suffisent pas.
        raise HTTPException(status_code=422,
                            detail="Le mot de passe doit faire au moins "
                                   "10 caracteres.")

    con = get_db()
    nb = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if nb >= MAX_USERS:
        con.close()
        raise HTTPException(status_code=409,
                            detail=f"Les {MAX_USERS} places sont prises.")
    if con.execute("SELECT 1 FROM users WHERE username=?", (nom,)).fetchone():
        con.close()
        raise HTTPException(status_code=409, detail="Ce nom est deja pris.")

    used = [r[0] for r in con.execute("SELECT slot_index FROM users").fetchall()]
    slot_index   = next((i for i in range(MAX_USERS) if i not in used), nb)
    slot_h, slot_m = creneau_utilisateur(slot_index)
    report_url   = lien_rapport(nom, CLOUDFLARE_BASE)

    pfile = PORTFOLIOS / f"portfolio_{nom}.json"
    if not pfile.exists():
        pfile.parent.mkdir(parents=True, exist_ok=True)
        pfile.write_text(json.dumps({
            "username": nom,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "settings": {"broker": "autre", "indices": ["S&P 500", "CAC 40"],
                         "watchlist": []},
            "lines":    [], "closed": []
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    con.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                (nom, hashed, "user",
                 datetime.now(timezone.utc).isoformat(), slot_index, report_url))
    con.commit()
    con.close()

    # Le profil vierge doit rejoindre le depot, sinon l'analyse quotidienne
    # ignorera ce nouvel utilisateur.
    try:
        from api import github_sync
        from api.load_portfolio import charger_liens
        sync = github_sync.pousser_profil(nom, json.loads(pfile.read_text(encoding="utf-8")))
        # Le jeton doit rejoindre le depot en meme temps que le profil.
        # Sinon GitHub Actions, ne le trouvant pas, en genere un autre au
        # moment de publier : l'adresse remise ici ne menerait nulle part.
        liens = github_sync.pousser_liens(charger_liens())
        if sync.get("ok") and not liens.get("ok"):
            sync = {"ok": False, "etat": "jeton non publie",
                    "detail": "Le profil est parti mais la table des liens non : "
                              "l'adresse du rapport ne fonctionnera pas."}
    except Exception as e:
        sync = {"ok": False, "etat": "erreur", "detail": f"{type(e).__name__}: {e}"}

    if scheduler.running:
        scheduler.add_job(
            func=lambda u=nom: run_analysis_for(u),
            trigger=CronTrigger(hour=slot_h, minute=slot_m, timezone="Europe/Paris"),
            id=f"analyse_{nom}", replace_existing=True,
        )

    # Meme horaire pour tout le monde : l'analyse est groupee, ce qui divise
    # le nombre d'appels aux fournisseurs de donnees.
    creneau = f"{HEURE_ANALYSE_GROUPEE} (heure Paris), analyse groupee quotidienne"
    return {
        "username":   nom,
        "slot":       creneau,
        "report_url": report_url,
        "sync":       sync,
        "message":    ("Compte cree. Conserve l'adresse de ton rapport : elle "
                       "vaut cle d'acces et ne sera plus affichee ainsi."),
    }


@app.post("/api/users", status_code=201)
def create_user(data: UserCreate, admin: dict = Depends(require_admin)):
    con = get_db()
    nb = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if nb >= MAX_USERS:
        con.close()
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_USERS} utilisateurs atteint")
    existing = con.execute("SELECT 1 FROM users WHERE username=?", (data.username,)).fetchone()
    if existing:
        con.close()
        raise HTTPException(status_code=409, detail="Nom d'utilisateur déjà pris")
    if len(data.password) < 6:
        con.close()
        raise HTTPException(status_code=422, detail="Le mot de passe doit faire au moins 6 caractères")

    # Attribution du slot libre suivant
    used_slots = [r[0] for r in con.execute("SELECT slot_index FROM users").fetchall()]
    slot_index = next((i for i in range(MAX_USERS) if i not in used_slots), nb)
    slot_h, slot_m = creneau_utilisateur(slot_index)

    # Adresse Cloudflare personnelle, batie sur un jeton aleatoire.
    # Le nom d'utilisateur n'apparait pas dans l'URL : un chemin devinable
    # exposerait le portefeuille des autres comptes, Cloudflare Pages ne
    # sachant pas authentifier les visiteurs.
    report_url = lien_rapport(data.username, CLOUDFLARE_BASE)

    # Profil vierge, pour que l'utilisateur trouve un support a remplir
    # des sa premiere connexion.
    pfile = PORTFOLIOS / f"portfolio_{data.username}.json"
    if not pfile.exists():
        pfile.parent.mkdir(parents=True, exist_ok=True)
        pfile.write_text(json.dumps({
            "username": data.username,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "settings": {"broker": "autre", "indices": ["S&P 500", "CAC 40"],
                         "watchlist": []},
            "lines":    []
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    con.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?)",
        (data.username, hashed, data.role or "user",
         datetime.now(timezone.utc).isoformat(), slot_index, report_url)
    )
    con.commit()
    con.close()

    # Ajoute immédiatement le job au scheduler
    scheduler.add_job(
        _scheduled_job,
        trigger=CronTrigger(hour=slot_h, minute=slot_m, timezone="Europe/Paris"),
        args=[data.username],
        id=f"analyze_{data.username}",
        replace_existing=True
    )
    print(f"[Scheduler] Nouveau job : {data.username} → {slot_h}h{slot_m:02d} heure Paris")

    return {
        "created":    data.username,
        "slot":       f"{slot_h}h{slot_m:02d} (heure Paris)",
        "report_url": report_url,
        "message":    ("Transmets cette adresse a l'utilisateur : elle vaut cle "
                       "d'acces a son rapport et n'est communiquee qu'une fois.")
    }


@app.post("/api/users/{username}/rotate-link")
def rotate_link(username: str, admin: dict = Depends(require_admin)):
    """Revoque l'adresse actuelle et en genere une nouvelle.

    A utiliser si un utilisateur a diffuse son lien par erreur. L'ancien
    dossier docs/r/<ancien_jeton>/ doit etre supprime du depot pour que
    l'ancienne adresse cesse effectivement de repondre.
    """
    from api.load_portfolio import jeton_rapport, dossier_rapport as _dr
    ancien = _dr(username, creer=False)
    jeton_rapport(username, rotation=True)
    nouveau_lien = lien_rapport(username, CLOUDFLARE_BASE)

    con = get_db()
    con.execute("UPDATE users SET report_url=? WHERE username=?", (nouveau_lien, username))
    con.commit()
    con.close()

    return {"username": username, "report_url": nouveau_lien,
            "a_supprimer": ancien,
            "message": f"Supprime {ancien}/ du depot pour couper l'ancien acces."}


@app.delete("/api/users/{username}")
def delete_user(username: str, admin: dict = Depends(require_admin)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Impossible de supprimer le compte admin")
    con = get_db()
    con.execute("DELETE FROM users WHERE username=?", (username,))
    con.commit()
    con.close()
    # Supprime le portefeuille
    pfile = PORTFOLIOS / f"portfolio_{username}.json"
    if pfile.exists():
        pfile.unlink()
    # Retire le rapport publie et le jeton associe
    try:
        import shutil as _shutil
        from api.load_portfolio import charger_liens, enregistrer_liens, dossier_rapport as _dr
        dossier = ROOT / _dr(username, creer=False)
        if dossier.exists():
            _shutil.rmtree(dossier)
        table = charger_liens()
        table.pop(username.strip().lower(), None)
        enregistrer_liens(table)
        from api import github_sync as _gs
        _gs.pousser_liens(table)
    except Exception as e:
        print(f"[Suppression] Nettoyage partiel pour {username} : {e}")
    # Supprime le job scheduler
    job_id = f"analyze_{username}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        print(f"[Scheduler] Job supprimé : {username}")
    return {"deleted": username}

# ---------------------------------------------------------------------------
# Passerelle vers les services externes (analyse d'action, bot de trading).
#
# api/external.py definit neuf routes sous /api/external/, toutes protegees
# par current_user. Sans ces deux lignes, le module est du code mort : les
# onglets « Bot de trading » et « Analyse d'action » de l'interface
# interrogent des adresses qui repondent 404.
#
# L'import est tolerant : si le fichier de configuration des services est
# absent, le reste du backend continue de fonctionner normalement.
# ---------------------------------------------------------------------------
try:
    from api.external import construire_routeur as _routeur_externe
    app.include_router(_routeur_externe(current_user))
    print("[External] Passerelle analyse + bot activee.")
except Exception as _e:
    print(f"[External] Passerelle non activee : {type(_e).__name__}: {_e}")
