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

from fastapi import FastAPI, HTTPException, Depends, status
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
MAX_USERS        = 5
JWT_SECRET       = os.getenv("JWT_SECRET", "")

# Exposition publique : autorise l'inscription libre. Tant que cette variable
# vaut "0", le service reste utilisable en local mais n'accepte aucune
# inscription depuis l'exterieur.
INSCRIPTION_LIBRE = os.getenv("INSCRIPTION_LIBRE", "0") == "1"

# Mot de passe du compte administrateur, impose au premier demarrage.
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "")

_DEFAUTS_INTERDITS = {"", "changeme-secret-local", "secret", "changeme"}

if JWT_SECRET in _DEFAUTS_INTERDITS:
    if INSCRIPTION_LIBRE:
        # Le secret signe les jetons de session. Une valeur par defaut est
        # publique : n'importe qui pourrait forger un jeton « role: admin »
        # sans connaitre le moindre mot de passe. Inacceptable des lors que
        # le service est joignable depuis l'exterieur.
        raise RuntimeError(
            "JWT_SECRET absent ou laisse a sa valeur par defaut alors que "
            "INSCRIPTION_LIBRE=1. Genere une cle et relance :\n"
            "  python -c \"import secrets;print(secrets.token_hex(32))\"\n"
            "puis definis JWT_SECRET avec cette valeur."
        )
    JWT_SECRET = "changeme-secret-local"
    print("[SECURITE] JWT_SECRET non defini : valeur de developpement utilisee.")
    print("           Acceptable en local uniquement. Ne PAS exposer ce service.")
JWT_ALG          = "HS256"
JWT_EXPIRE       = 60 * 8   # 8 heures

# URL de base Cloudflare Pages — à adapter à ton projet
CLOUDFLARE_BASE  = os.getenv("CLOUDFLARE_PAGES_URL", "https://projectone.pages.dev")

# Heure d'analyse : 22h30 Paris, marches US et Euronext fermes.
# Euronext ferme a 17h30 ; New York a 22h00 heure de Paris. La demi-heure
# de marge laisse les prix d'enchere de cloture se consolider.
ANALYSE_HEURE  = int(os.getenv("ANALYSE_HEURE",  "22"))
ANALYSE_MINUTE = int(os.getenv("ANALYSE_MINUTE", "30"))

# Les utilisateurs sont espaces de 5 minutes a partir de 22h30, pour etaler
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

# Heure unique d'analyse, identique pour tous. Sert uniquement a informer
# l'utilisateur : l'execution reelle est declenchee par le planificateur
# distant, en un seul passage groupe.
HEURE_ANALYSE_GROUPEE = os.getenv("HEURE_ANALYSE_GROUPEE", "22h37")


def creneau_utilisateur(slot_idx: int) -> tuple:
    """(heure, minute) du creneau d'un utilisateur, heure de Paris.

    Le calcul passe par un total en minutes puis retombe sur une heure :
    au-dela de cinq inscrits, les creneaux debordent proprement sur l'heure
    suivante au lieu de produire une minute invalide (22h65).
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

# ── Scheduler APScheduler ────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Europe/Paris")

def _scheduled_job(username: str):
    print(f"[Scheduler] Déclenchement analyse pour '{username}' — {datetime.now()}")
    result = run_analysis_for(username)
    status_str = "✅ OK" if result.get("success") else f"❌ Erreur: {result.get('error', '?')}"
    print(f"[Scheduler] {username} → {status_str}")

def rebuild_scheduler():
    """Relit la BDD et synchronise les jobs APScheduler."""
    scheduler.remove_all_jobs()

    if not PLANIFICATION_LOCALE:
        print("[Scheduler] Planification locale desactivee.")
        print("            L'analyse est produite par GitHub Actions a 22h37,")
        print("            en un seul passage pour tous les profils.")
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

class PortfolioSave(BaseModel):
    lines:    List[PortfolioLine]
    settings: Optional[ProfileSettings] = None

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


@app.get("/api/status")
def status_check():
    con = get_db()
    nb_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    rows = con.execute("SELECT username, slot_index, report_url FROM users ORDER BY slot_index").fetchall()
    con.close()
    slots = []
    for r in rows:
        s_h, s_m = creneau_utilisateur(r["slot_index"])
        slots.append({
            "username":   r["username"],
            "slot":       f"{s_h}h{s_m:02d}",
            "report_url": lien_rapport(r["username"], CLOUDFLARE_BASE)
        })
    return {
        "status":   "ok",
        "users":    nb_users,
        "max_users": MAX_USERS,
        "time":     datetime.now(timezone.utc).isoformat(),
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


@app.post("/api/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    _verrou(f"login:{form.username}")
    con = get_db()
    row = con.execute(
        "SELECT password_hash, role, report_url FROM users WHERE username=?", (form.username,)
    ).fetchone()
    con.close()
    if not row or not bcrypt.checkpw(form.password.encode(), row["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    _TENTATIVES.pop(f"login:{form.username}", None)
    token = create_token(form.username, row["role"])
    return {
        "access_token": token,
        "token_type":   "bearer",
        "username":     form.username,
        "role":         row["role"],
        # Recalculee a chaque connexion, jamais relue depuis la base : la
        # colonne report_url est un instantane fige a la creation du compte.
        # Si CLOUDFLARE_PAGES_URL a ete renseigne apres coup, ou si le compte
        # a ete renomme, cette colonne reste fausse indefiniment.
        "report_url":   lien_rapport(form.username, CLOUDFLARE_BASE)
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
            "closed":   ancien.get("closed", []),
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
             "suffixe": f["suffixe"]} for c, f in MARCHES.items()]


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


@app.post("/api/analyze/{username}")
def trigger_analysis(username: str, user: dict = Depends(current_user)):
    """Déclenche l'analyse manuellement (hors planning automatique)."""
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
        s_h, s_m = creneau_utilisateur(r["slot_index"])
        result.append({
            "username":   r["username"],
            "role":       r["role"],
            "created_at": r["created_at"],
            "slot":       f"{s_h}h{s_m:02d} (Paris)",
            "report_url": lien_rapport(r["username"], CLOUDFLARE_BASE)
        })
    return result


class Inscription(BaseModel):
    username: str
    password: str


def _slug_utilisateur(brut: str) -> str:
    """Identifiant sur : minuscules, lettres, chiffres, tirets.

    Le nom devient un nom de fichier (portfolio_<nom>.json) et un dossier.
    Laisser passer un point ou une barre oblique permettrait d'ecrire
    ailleurs que dans data/portfolios/.
    """
    import re as _re2
    net = _re2.sub(r"[^a-z0-9_-]+", "-", str(brut or "").strip().lower()).strip("-")
    return net[:24]


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
