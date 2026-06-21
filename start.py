#!/usr/bin/env python3
"""
start.py — Lance le serveur FastAPI local.

Usage :
    python start.py             # port 8000 (défaut)
    python start.py --port 8080
    python start.py --reload    # rechargement automatique (dev)

Puis ouvrir : http://localhost:8000
"""
import argparse, subprocess, sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Démarrer le serveur Portfolio Analyzer")
parser.add_argument("--port",   type=int, default=8000, help="Port HTTP (défaut: 8000)")
parser.add_argument("--host",   type=str, default="127.0.0.1", help="Adresse d'écoute (défaut: 127.0.0.1)")
parser.add_argument("--reload", action="store_true",  help="Rechargement auto (mode développement)")
args = parser.parse_args()

root = Path(__file__).parent
cmd = [
    sys.executable, "-m", "uvicorn",
    "api.backend:app",
    "--host", args.host,
    "--port", str(args.port),
]
if args.reload:
    cmd.append("--reload")

print(f"\n🚀  Serveur démarré sur  http://{args.host}:{args.port}")
print(f"📊  Interface          →  http://{args.host}:{args.port}/")
print(f"📁  Rapport HTML       →  http://{args.host}:{args.port}/report/index.html")
print(f"📖  API docs           →  http://{args.host}:{args.port}/docs")
print("      (Ctrl+C pour arrêter)\n")

subprocess.run(cmd, cwd=str(root))
