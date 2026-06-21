# Pont Interface → portfolio_analyzer.py

## Architecture

```
interface.html  (navigateur)
      │  POST /api/portfolio/{user}   → sauvegarde
      │  POST /api/analyze/{user}     → lance l'analyse
      ▼
 api/backend.py  (FastAPI, tourne en local)
      │  écrit data/active_portfolio.json
      │  appelle portfolio_analyzer.py --portfolio data/active_portfolio.json
      │  appelle generate_html.py
      ▼
 data/active_portfolio.json
      │
      ▼
 api/load_portfolio.py  (module utilitaire)
      │  load_portfolio()  →  liste de dicts
      ▼
 portfolio_analyzer.py  (cœur de l'analyse)
      │  lit PORTFOLIO depuis load_portfolio() OU --portfolio <fichier>
      ▼
 reports/daily_report.md  →  generate_html.py  →  docs/index.html
```

## Lancer le serveur

```bash
# Installer les dépendances supplémentaires
pip install fastapi uvicorn[standard] bcrypt pyjwt

# Démarrer
python start.py

# Ou avec rechargement auto (développement)
python start.py --reload
```

Puis ouvrir **http://localhost:8000** dans ton navigateur.

## Intégrer dans portfolio_analyzer.py

Remplace le bloc `PORTFOLIO = [...]` codé en dur par :

```python
import argparse
from api.load_portfolio import load_portfolio

parser = argparse.ArgumentParser()
parser.add_argument("--portfolio", default=None,
                    help="Chemin vers un fichier JSON de portefeuille (optionnel)")
args, _ = parser.parse_known_args()

if args.portfolio:
    PORTFOLIO = load_portfolio(args.portfolio)
else:
    # Fallback : liste codée en dur (si lancé manuellement sans interface)
    PORTFOLIO = [
        # ... tes lignes habituelles ...
    ]
```

## Format JSON du portefeuille

```json
{
  "username": "adrien",
  "saved_at": "2026-06-21T10:00:00+00:00",
  "lines": [
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
  ]
}
```

## Stockage local

| Chemin | Contenu |
|---|---|
| `data/users.db` | SQLite — comptes utilisateurs (bcrypt) |
| `data/portfolios/portfolio_{user}.json` | Portefeuille sauvegardé par utilisateur |
| `data/active_portfolio.json` | Portefeuille actif transmis à l'analyseur |
| `reports/daily_report.md` | Rapport Markdown généré |
| `docs/index.html` | Rapport HTML final |
