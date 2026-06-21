#!/usr/bin/env python3
"""
backend.py  v1.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Serveur FastAPI local — hébergement personnel, max 5 utilisateurs.

Nouveautés v1.2 :
  • Chaque utilisateur a un slot horaire : 16h00, 16h10, 16h20, 16h30, 16h40
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
MAX_USERS        = 5
JWT_SECRET       = os.getenv("JWT_SECRET", "changeme-secret-local")
JWT_ALG          = "HS256"
JWT_EXPIRE       = 60 * 8   # 8 heures

# URL de base Cloudflare Pages — à adapter à ton projet
CLOUDFLARE_BASE  = os.getenv("CLOUDFLARE_PAGES_URL", "https://projectone.pages.dev")

# Slots horaires : 16h00, 16h10, … (un slot par position d'inscription)
SLOT_MINUTES = [0, 10, 20, 30, 40]   # offset en minutes après 16h00 (heure Paris)

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
        hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        report_url = f"{CLOUDFLARE_BASE}/report/admin/index.html"
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
        json.dumps({"username": username, "lines": lines}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Dossier de sortie propre à l'utilisateur
    out_dir = ROOT / "docs" / username
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

    rc1 = run([str(ANALYZER), "--portfolio", str(input_file)], "portfolio_analyzer")
    rc2 = run([str(GEN_HTML), "--user", username, "--output", str(out_dir)], "generate_html")

    success = (rc1 == 0 and rc2 == 0)
    return {
        "success": success,
        "username": username,
        "lines_analyzed": len(lines),
        "report_url": f"/report/{username}/index.html" if success else None,
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
    con = get_db()
    rows = con.execute("SELECT username, slot_index FROM users").fetchall()
    con.close()
    for row in rows:
        uname      = row["username"]
        slot_idx   = row["slot_index"]
        offset_min = SLOT_MINUTES[slot_idx] if slot_idx < len(SLOT_MINUTES) else slot_idx * 10
        hour       = 16
        minute     = offset_min
        scheduler.add_job(
            _scheduled_job,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Europe/Paris"),
            args=[uname],
            id=f"analyze_{uname}",
            replace_existing=True
        )
        print(f"[Scheduler] Job enregistré : {uname} → 16h{minute:02d} heure Paris")

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
    name:           str
    ticker_finnhub: str
    ticker_eodhd:   str
    isin:           Optional[str] = ""
    quantity:       float
    buy_price:      float
    market:         str          # us | euronext | xetra | lse | autre
    broker:         str
    currency:       str          # EUR | USD | GBP
    asset_type:     Optional[str] = "action"

class PortfolioSave(BaseModel):
    lines: List[PortfolioLine]

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
        offset = SLOT_MINUTES[r["slot_index"]] if r["slot_index"] < len(SLOT_MINUTES) else r["slot_index"] * 10
        slots.append({
            "username":   r["username"],
            "slot":       f"16h{offset:02d}",
            "report_url": r["report_url"]
        })
    return {
        "status":   "ok",
        "users":    nb_users,
        "max_users": MAX_USERS,
        "time":     datetime.now(timezone.utc).isoformat(),
        "schedule": slots
    }


@app.post("/api/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    con = get_db()
    row = con.execute(
        "SELECT password_hash, role, report_url FROM users WHERE username=?", (form.username,)
    ).fetchone()
    con.close()
    if not row or not bcrypt.checkpw(form.password.encode(), row["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    token = create_token(form.username, row["role"])
    return {
        "access_token": token,
        "token_type":   "bearer",
        "username":     form.username,
        "role":         row["role"],
        "report_url":   row["report_url"]
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
    pfile.write_text(
        json.dumps({
            "username":  username,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "lines":    [l.model_dump() for l in data.lines]
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return {"saved": len(data.lines), "file": str(pfile)}


@app.post("/api/analyze/{username}")
def trigger_analysis(username: str, user: dict = Depends(current_user)):
    """Déclenche l'analyse manuellement (hors planning automatique)."""
    if user["sub"] != username and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès interdit")
    result = run_analysis_for(username)
    if not result.get("success") and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/users")
def list_users(admin: dict = Depends(require_admin)):
    con = get_db()
    rows = con.execute(
        "SELECT username, role, created_at, slot_index, report_url FROM users ORDER BY slot_index"
    ).fetchall()
    con.close()
    result = []
    for r in rows:
        offset = SLOT_MINUTES[r["slot_index"]] if r["slot_index"] < len(SLOT_MINUTES) else r["slot_index"] * 10
        result.append({
            "username":   r["username"],
            "role":       r["role"],
            "created_at": r["created_at"],
            "slot":       f"16h{offset:02d} (Paris)",
            "report_url": r["report_url"]
        })
    return result


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
    offset_min = SLOT_MINUTES[slot_index] if slot_index < len(SLOT_MINUTES) else slot_index * 10

    # Lien Cloudflare Pages personnel
    report_url = f"{CLOUDFLARE_BASE}/report/{data.username}/index.html"

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
        trigger=CronTrigger(hour=16, minute=offset_min, timezone="Europe/Paris"),
        args=[data.username],
        id=f"analyze_{data.username}",
        replace_existing=True
    )
    print(f"[Scheduler] Nouveau job : {data.username} → 16h{offset_min:02d} heure Paris")

    return {
        "created":    data.username,
        "slot":       f"16h{offset_min:02d} (heure Paris)",
        "report_url": report_url
    }


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
    # Supprime le job scheduler
    job_id = f"analyze_{username}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        print(f"[Scheduler] Job supprimé : {username}")
    return {"deleted": username}
