#!/usr/bin/env python3
"""
backend.py  v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Serveur FastAPI local — hébergement personnel, max 5 utilisateurs.

Endpoints :
  POST /api/login              → jeton JWT
  GET  /api/portfolio/{user}   → lignes du portefeuille
  POST /api/portfolio/{user}   → sauvegarder les lignes
  POST /api/analyze/{user}     → exporter portfolio_{user}.json
                                 puis lancer portfolio_analyzer.py
                                 puis lancer generate_html.py
  GET  /api/users              → liste des utilisateurs (admin)
  POST /api/users              → créer un compte (admin, max 5)
  DELETE /api/users/{username} → supprimer un compte (admin)
  GET  /api/status             → statut serveur
  GET  /                       → sert interface.html

Sécurité : bcrypt + JWT (HS256). Clé secrète dans JWT_SECRET (env).
Stockage  : SQLite (data/users.db) + JSON par utilisateur (data/portfolios/).
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

# ── Config ──────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent          # racine du projet
DATA_DIR    = ROOT / "data"
PORTFOLIOS  = DATA_DIR / "portfolios"
DB_PATH     = DATA_DIR / "users.db"
INTERFACE   = ROOT / "interface.html"
ANALYZER    = ROOT / "portfolio_analyzer.py"
GEN_HTML    = ROOT / "generate_html.py"
MAX_USERS   = 5
JWT_SECRET  = os.getenv("JWT_SECRET", "changeme-secret-local")
JWT_ALG     = "HS256"
JWT_EXPIRE  = 60 * 8   # 8 heures

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
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        )
    """)
    con.commit()
    # Compte admin par défaut si la table est vide
    if not con.execute("SELECT 1 FROM users").fetchone():
        hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        con.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            ("admin", hashed, "admin", datetime.now(timezone.utc).isoformat())
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

# ── App FastAPI ──────────────────────────────────────────────────────
app = FastAPI(title="Portfolio Analyzer — Backend local", version="1.0")

# Sert docs/ (rapport HTML généré) en statique
docs_dir = ROOT / "docs"
docs_dir.mkdir(exist_ok=True)
app.mount("/report", StaticFiles(directory=str(docs_dir), html=True), name="report")

# ── Modèles ──────────────────────────────────────────────────────────
class PortfolioLine(BaseModel):
    name: str
    ticker_finnhub: str
    ticker_eodhd: str
    isin: Optional[str] = ""
    quantity: float
    buy_price: float
    market: str          # US | Euronext | Xetra | LSE | Autre
    broker: str
    currency: str        # EUR | USD | GBP
    asset_type: Optional[str] = "action"

class PortfolioSave(BaseModel):
    lines: List[PortfolioLine]

class UserCreate(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"

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
    con.close()
    return {"status": "ok", "users": nb_users, "max_users": MAX_USERS,
            "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    con = get_db()
    row = con.execute(
        "SELECT password_hash, role FROM users WHERE username=?", (form.username,)
    ).fetchone()
    con.close()
    if not row or not bcrypt.checkpw(form.password.encode(), row["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    token = create_token(form.username, row["role"])
    return {"access_token": token, "token_type": "bearer",
            "username": form.username, "role": row["role"]}


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
        json.dumps({"username": username, "saved_at": datetime.now(timezone.utc).isoformat(),
                    "lines": [l.model_dump() for l in data.lines]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return {"saved": len(data.lines), "file": str(pfile)}


@app.post("/api/analyze/{username}")
def run_analysis(username: str, user: dict = Depends(current_user)):
    """Exporte portfolio_{username}.json → PORTFOLIO dans portfolio_analyzer.py,
       lance l'analyse, puis génère le rapport HTML."""
    if user["sub"] != username and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès interdit")

    pfile = PORTFOLIOS / f"portfolio_{username}.json"
    if not pfile.exists():
        raise HTTPException(status_code=400, detail="Aucun portefeuille enregistré pour cet utilisateur")

    portfolio_data = json.loads(pfile.read_text(encoding="utf-8"))
    lines = portfolio_data.get("lines", [])
    if not lines:
        raise HTTPException(status_code=400, detail="Le portefeuille est vide")

    # Écrire le fichier d'entrée pour portfolio_analyzer.py
    input_file = ROOT / "data" / "active_portfolio.json"
    input_file.write_text(
        json.dumps({"username": username, "lines": lines}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

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
    rc2 = run([str(GEN_HTML)], "generate_html")

    success = (rc1 == 0 and rc2 == 0)
    return {
        "success": success,
        "username": username,
        "lines_analyzed": len(lines),
        "report_url": "/report/index.html" if success else None,
        "logs": logs
    }


@app.get("/api/users")
def list_users(admin: dict = Depends(require_admin)):
    con = get_db()
    rows = con.execute("SELECT username, role, created_at FROM users ORDER BY created_at").fetchall()
    con.close()
    return [{"username": r["username"], "role": r["role"], "created_at": r["created_at"]} for r in rows]


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
    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    con.execute(
        "INSERT INTO users VALUES (?,?,?,?)",
        (data.username, hashed, data.role or "user", datetime.now(timezone.utc).isoformat())
    )
    con.commit()
    con.close()
    return {"created": data.username}


@app.delete("/api/users/{username}")
def delete_user(username: str, admin: dict = Depends(require_admin)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Impossible de supprimer le compte admin")
    con = get_db()
    con.execute("DELETE FROM users WHERE username=?", (username,))
    con.commit()
    con.close()
    # Supprime aussi le fichier portefeuille
    pfile = PORTFOLIOS / f"portfolio_{username}.json"
    if pfile.exists():
        pfile.unlink()
    return {"deleted": username}
