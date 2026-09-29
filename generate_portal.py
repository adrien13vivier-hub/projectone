#!/usr/bin/env python3
"""
Récapitulatif des liens privés + taux de change du jour.
================================================================================

CE QUE CE SCRIPT NE FAIT PLUS : construire docs/index.html. Cette page est la
page d'accueil PUBLIQUE de ProjectOne (effets visuels, présentation) — un
fichier fixe, entretenu à la main, comme interface.html. La reconstruire
chaque nuit depuis un modèle neutre écraserait silencieusement tout ce qui y
est écrit.

Ce script ne fait donc plus que deux choses, aucune des deux ne touchant à
docs/index.html :
  1. Publier docs/taux-change.json (via ecrire_taux_change ci-dessous).
  2. Imprimer, dans les logs GitHub Actions (privés si le dépôt l'est), le
     récapitulatif des liens privés de chaque profil — jamais publié.

Chaque rapport vit sous docs/r/<jeton>/, où <jeton> est un identifiant
aléatoire de 16 caractères. L'adresse fait office de clé d'accès : elle est
transmise à l'utilisateur à son inscription, et lui seul la connaît.
"""

import csv
import html
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).resolve().parent
REPORTS    = ROOT / "reports"
DOCS       = ROOT / "docs"
PORTFOLIOS = ROOT / "data" / "portfolios"

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


def ecrire_taux_change() -> None:
    """docs/taux-change.json -- taux EUR/USD du jour, publie a cote des
    rapports (v19). Consomme par interface.html pour remplir tout seul le
    "Taux -> EUR" d'une ligne ou d'un rachat saisi en dollars.

    Rien de sensible ici : c'est un chiffre public, pas un rapport personnel.
    En cas d'echec des deux sources (EODHD puis Yahoo Finance, voir
    portfolio_analyzer.get_taux_usd_eur_du_jour), on n'ecrit RIEN plutot que
    de publier une valeur inventee -- le fichier de la veille reste en place,
    ce qui reste plus juste qu'un chiffre fabrique sur lequel quelqu'un
    baserait un prix de revient.
    """
    try:
        from portfolio_analyzer import get_taux_usd_eur_du_jour
    except Exception as e:
        print(f"⚠️  Taux EUR/USD indisponible (import) : {e}")
        return

    taux, source = get_taux_usd_eur_du_jour()
    if taux is None:
        print(f"⚠️  Taux EUR/USD non publié aujourd'hui : {source}")
        return

    chemin = DOCS / "taux-change.json"
    chemin.write_text(json.dumps({
        "eur_usd": round(taux, 6),
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "source":  source,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Taux EUR/USD du jour publié ({source}) : {taux:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE D'ATTENTE (29/09/2026)
# ─────────────────────────────────────────────────────────────────────────────
# Un profil sans aucune position exploitable (ex. mamefat : 4 lignes saisies
# SANS quantite ni prix de revient) ne produit pas de rapport, donc pas de
# docs/r/<jeton>/index.html. Cloudflare Pages servait alors la page
# d'accueil publique a la place -- sans ses styles, puisque ses chemins
# relatifs pointaient dans /r/<jeton>/ -- et l'utilisateur ne savait ni
# pourquoi, ni quoi corriger. On publie a la place une page qui le dit.

_PAGE_ATTENTE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>ProjectOne - Rapport en attente</title>
<style>
  :root {{ --bg:#0b0f14; --card:#131a22; --txt:#e6edf3; --muted:#8b98a5; --acc:#2dd4bf; --warn:#f5b041; }}
  @media (prefers-color-scheme: light) {{ :root {{ --bg:#f5f7f9; --card:#ffffff; --txt:#16202a; --muted:#5b6b7a; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt);
         font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  main {{ max-width:620px; margin:0 auto; padding:48px 16px; }}
  .marque {{ color:var(--acc); font-weight:700; letter-spacing:.04em; font-size:.85rem; text-transform:uppercase; }}
  h1 {{ font-size:1.6rem; margin:.4rem 0 1rem; }}
  .carte {{ background:var(--card); border-radius:14px; padding:20px 18px; margin-top:18px;
           border:1px solid rgba(139,152,165,.18); }}
  .carte h2 {{ font-size:1rem; margin:0 0 .6rem; color:var(--warn); }}
  ul {{ margin:.2rem 0 0; padding-left:1.1rem; }}
  li {{ margin:.25rem 0; }}
  p.note {{ color:var(--muted); font-size:.9rem; margin-top:22px; }}
</style></head>
<body><main>
  <div class="marque">ProjectOne</div>
  <h1>Ton rapport n'est pas encore disponible</h1>
  <p>{explication}</p>
  {bloc_erreurs}
  <div class="carte">
    <h2>Que faire</h2>
    <p style="margin:0">{action}</p>
  </div>
  <p class="note">Vérifié le {date}. Cette page est remplacée automatiquement par ton rapport
  dès la prochaine analyse réussie (chaque nuit).</p>
</main></body></html>
"""


def ecrire_page_attente(user: str, dossier: Path) -> bool:
    """Publie docs/r/<jeton>/index.html quand le rapport n'a pas pu etre
    produit. Ne touche jamais a un dossier nomme d'apres l'utilisateur (sans
    jeton) : ce serait une adresse devinable."""
    if "/r/" not in dossier.as_posix():
        return False
    erreurs, n_lignes = [], None
    try:
        from api.load_portfolio import load_profile
        prof = load_profile(str(PORTFOLIOS / f"portfolio_{user}.json"), user)
        erreurs = prof.get("erreurs") or []
        n_lignes = len(prof.get("lines") or [])
    except Exception as e:
        erreurs = [f"profil illisible ({type(e).__name__})"]

    if n_lignes == 0:
        explication = ("Aucune position de ton portefeuille n'a pu être analysée : "
                       "il manque des informations indispensables.")
        action = ("Ouvre l'application, onglet portefeuille, et renseigne pour chaque "
                  "ligne la <b>quantité détenue</b> et le <b>prix de revient</b> "
                  "(prix d'achat unitaire), puis enregistre.")
    else:
        explication = ("La dernière analyse n'a pas pu produire ton rapport "
                       "(source de données indisponible ou erreur passagère).")
        action = ("Rien à faire de ton côté pour l'instant : l'analyse sera relancée "
                  "cette nuit. Si cette page est toujours là demain, signale-le.")

    bloc = ""
    if erreurs:
        items = "".join(f"<li>{html.escape(str(e))}</li>" for e in erreurs[:30])
        bloc = f'<div class="carte"><h2>Ce qui bloque</h2><ul>{items}</ul></div>'

    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "index.html").write_text(_PAGE_ATTENTE.format(
        explication=explication, bloc_erreurs=bloc, action=action,
        date=datetime.now().strftime("%d/%m/%Y")), encoding="utf-8")
    return True


def main():
    users = profils()

    DOCS.mkdir(parents=True, exist_ok=True)
    ecrire_taux_change()

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
        dossier = ROOT / dossier_rapport(u, creer=False)
        attente = False
        # Pas de rapport produit cette nuit : page d'attente explicite plutot
        # qu'une adresse qui retombe sur la page d'accueil.
        if not (REPORTS / u / "daily_report.md").exists():
            attente = ecrire_page_attente(u, dossier)
        publie = (dossier / "index.html").exists()
        etat   = ("PAGE D'ATTENTE (aucun rapport produit)" if attente
                  else "publié" if publie else "PAS ENCORE PUBLIÉ")
        print(f"\n  {u}")
        print(f"    {lien_rapport(u)}")
        print(f"    dernier relevé : {dernier_releve(u)} — {etat}")
    print("\n" + "=" * 78)
    print("Ces adresses valent mot de passe : ne les mets ni dans le dépôt,")
    print("ni dans une page publiée.")
    print("=" * 78)


if __name__ == "__main__":
    main()
