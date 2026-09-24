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
