#!/usr/bin/env python3
"""
Page d'accueil publique (docs/index.html) + récapitulatif des liens privés.
================================================================================

Attention à ce que fait ce script, et surtout à ce qu'il NE fait PAS.

Cloudflare Pages sert des fichiers statiques, sans authentification. Tout ce qui
est écrit dans docs/ est lisible par quiconque connaît l'adresse. La page
d'accueil est donc volontairement NEUTRE : aucun nom d'utilisateur, aucun
montant, aucun lien vers les rapports.

Chaque rapport vit sous docs/r/<jeton>/, où <jeton> est un identifiant
aléatoire de 16 caractères. L'adresse fait office de clé d'accès : elle est
transmise à l'utilisateur à son inscription, et lui seul la connaît.

Le récapitulatif des liens est imprimé dans la console (visible dans les logs
GitHub Actions, qui sont privés si le dépôt l'est) et jamais publié.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).resolve().parent
REPORTS    = ROOT / "reports"
DOCS       = ROOT / "docs"
PORTFOLIOS = ROOT / "data" / "portfolios"
OUT        = DOCS / "index.html"

sys.path.insert(0, str(ROOT))


def profils() -> list:
    """Utilisateurs disposant d'un profil enregistré."""
    if not PORTFOLIOS.exists():
        return []
    noms = []
    for f in sorted(PORTFOLIOS.glob("*.json")):
        nom = f.stem
        noms.append(nom[len("portfolio_"):] if nom.startswith("portfolio_") else nom)
    return noms


def dernier_releve(user: str) -> str:
    """Horodatage du dernier relevé, pour le journal uniquement."""
    csv_path = REPORTS / user / "history.csv"
    if not csv_path.exists():
        return "aucun relevé"
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            lignes = list(csv.DictReader(f))
        return f"{lignes[-1]['date']} {lignes[-1]['time']}" if lignes else "aucun relevé"
    except Exception:
        return "illisible"


def construire_page(nb: int) -> str:
    maintenant = datetime.now().strftime("%d/%m/%Y à %H:%M")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Portfolio Analyzer</title>
<style>
  :root {{ --fond:#0d1117; --carte:#161b22; --bord:#30363d;
           --texte:#e6edf3; --doux:#8b949e; --accent:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
          justify-content:center; padding:2rem 1.25rem; background:var(--fond);
          color:var(--texte); line-height:1.6;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .boite {{ max-width:520px; background:var(--carte); border:1px solid var(--bord);
            border-radius:14px; padding:2.25rem; }}
  h1 {{ margin:0 0 .35rem; font-size:1.55rem; letter-spacing:-.02em; }}
  .sous {{ margin:0 0 1.75rem; color:var(--doux); font-size:.92rem; }}
  p {{ margin:0 0 1rem; font-size:.93rem; }}
  .encart {{ background:#0d1117; border:1px solid var(--bord);
             border-left:3px solid var(--accent); border-radius:0 8px 8px 0;
             padding:.9rem 1.1rem; margin:1.5rem 0; font-size:.88rem;
             color:var(--doux); }}
  code {{ background:#21262d; padding:.12rem .4rem; border-radius:4px;
          font-size:.85em; color:var(--accent); }}
  footer {{ margin-top:1.75rem; padding-top:1.25rem; border-top:1px solid var(--bord);
            color:var(--doux); font-size:.78rem; }}
</style>
</head>
<body>
  <div class="boite">
    <h1>Portfolio Analyzer</h1>
    <p class="sous">Analyse de portefeuille automatisée · {nb} profil(s) suivi(s)</p>

    <p>Chaque utilisateur dispose d'une adresse personnelle vers son propre
       rapport, mise à jour automatiquement chaque jour ouvré.</p>

    <div class="encart">
      Ton lien ressemble à <code>/r/xxxxxxxxxxxxxxxx/</code> et t'a été
      communiqué à l'inscription. Garde-le : c'est lui qui donne accès à ton
      rapport. Ne le partage pas.
    </div>

    <p>Lien perdu ? Reconnecte-toi à l'interface de configuration : il y est
       affiché en permanence.</p>

    <footer>
      Page régénérée le {maintenant}. Les analyses produites sont indicatives
      et ne constituent pas un conseil en investissement.
    </footer>
  </div>
</body>
</html>
"""


def main():
    users = profils()

    DOCS.mkdir(parents=True, exist_ok=True)
    OUT.write_text(construire_page(len(users)), encoding="utf-8")
    print(f"✅ Page d'accueil neutre générée : {OUT}")

    if not users:
        print("Aucun profil dans data/portfolios/.")
        return

    # Récapitulatif imprimé, jamais publié.
    try:
        from api.load_portfolio import lien_rapport, dossier_rapport
    except Exception as e:
        print(f"⚠️  Liens indisponibles : {e}")
        return

    print("\n" + "=" * 78)
    print("LIENS PRIVÉS — à transmettre à chaque utilisateur, un par un")
    print("=" * 78)
    for u in users:
        publie = (ROOT / dossier_rapport(u, creer=False) / "index.html").exists()
        etat   = "publié" if publie else "PAS ENCORE PUBLIÉ"
        print(f"\n  {u}")
        print(f"    {lien_rapport(u)}")
        print(f"    dernier relevé : {dernier_releve(u)} — {etat}")
    print("\n" + "=" * 78)
    print("Ces adresses valent mot de passe : ne les mets ni dans le dépôt,")
    print("ni dans une page publiée.")
    print("=" * 78)


if __name__ == "__main__":
    main()
