#!/usr/bin/env python3
"""
load_portfolio.py  v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Module utilitaire : charge data/active_portfolio.json et retourne
la liste PORTFOLIO au format attendu par portfolio_analyzer.py.

Utilisation dans portfolio_analyzer.py :
    from api.load_portfolio import load_portfolio
    PORTFOLIO = load_portfolio()          # remplace la liste codée en dur

Format JSON d'entrée (chaque ligne) :
  {
    "name": "Air Liquide",
    "ticker_finnhub": "AI.PA",
    "ticker_eodhd": "AI.PA",
    "isin": "FR0000120073",
    "quantity": 2,
    "buy_price": 159.50,
    "market": "Euronext",
    "broker": "BoursoBank",
    "currency": "EUR",
    "asset_type": "action"
  }

Format retourné (dict compatible portfolio_analyzer.py) :
  {
    "name":         str,
    "ticker":       str,   # ticker_finnhub
    "ticker_eodhd": str,
    "isin":         str,
    "qty":          float,
    "buy_price":    float,
    "market":       str,
    "broker":       str,
    "currency":     str,
    "asset_type":   str,
  }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import json
from pathlib import Path

DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "active_portfolio.json"


def load_portfolio(path=None) -> list[dict]:
    """
    Charge le JSON du portefeuille actif et retourne une liste de dicts
    au format attendu par portfolio_analyzer.py.

    Args:
        path: chemin optionnel vers un fichier JSON alternatif.
              Par défaut : data/active_portfolio.json

    Returns:
        Liste de dicts {name, ticker, ticker_eodhd, isin, qty,
                        buy_price, market, broker, currency, asset_type}

    Raises:
        FileNotFoundError : si le fichier JSON est absent.
        ValueError        : si le JSON est malformé ou vide.
    """
    src = Path(path) if path else DEFAULT_INPUT

    if not src.exists():
        raise FileNotFoundError(
            f"Fichier portefeuille introuvable : {src}\n"
            "Enregistrez d'abord votre portefeuille depuis l'interface web."
        )

    raw = json.loads(src.read_text(encoding="utf-8"))
    lines = raw.get("lines", [])

    if not lines:
        raise ValueError(
            f"Le fichier {src} ne contient aucune ligne de portefeuille."
        )

    portfolio = []
    for i, line in enumerate(lines):
        try:
            portfolio.append({
                "name":         str(line["name"]).strip(),
                "ticker":       str(line.get("ticker_finnhub", "")).strip(),
                "ticker_eodhd": str(line.get("ticker_eodhd", "")).strip(),
                "isin":         str(line.get("isin", "")).strip(),
                "qty":          float(line["quantity"]),
                "buy_price":    float(line["buy_price"]),
                "market":       str(line.get("market", "Euronext")).strip(),
                "broker":       str(line.get("broker", "Autre")).strip(),
                "currency":     str(line.get("currency", "EUR")).strip(),
                "asset_type":   str(line.get("asset_type", "action")).strip(),
            })
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Ligne {i+1} invalide dans {src} : {e}")

    return portfolio


if __name__ == "__main__":
    # Test rapide en ligne de commande : python api/load_portfolio.py
    import sys
    path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        data = load_portfolio(path_arg)
        print(f"✅ {len(data)} ligne(s) chargée(s) :")
        for p in data:
            print(f"  - {p['name']} ({p['ticker']}) : {p['qty']}× {p['buy_price']} {p['currency']}")
    except (FileNotFoundError, ValueError) as err:
        print(f"❌ {err}")
        sys.exit(1)
