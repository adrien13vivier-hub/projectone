# 📊 Portfolio Analyzer v3.2

Rapport quotidien automatisé à **16h00 Paris** — 3 sources avec validation croisée.

## Architecture des sources

```
COURS US      : TwelveData (batch 1 requête) → EODHD → Finnhub
EUR/USD       : TwelveData → Finnhub → EODHD
COURS EU (.PA): EODHD → Finnhub
INDICES MACRO : EODHD → Finnhub
SENTIMENT     : Finnhub → EODHD (analyse lexicale)
CONSENSUS     : Finnhub → EODHD fundamentals
NEWS          : EODHD → Finnhub
```

## Protocole de validation croisée

Si deux sources retournent un écart > **2%** sur un même cours :
- ⚠️ Divergence signalée dans le rapport (section dédiée)
- La **médiane** des deux valeurs est utilisée automatiquement
- Chaque donnée affiche sa source réelle dans le rapport

## Secrets GitHub requis (3)

| Nom | Description |
|-----|-------------|
| `FINNHUB_API_KEY` | Sentiment, consensus, forex fallback |
| `EODHD_API_KEY` | Euronext, indices, news, fundamentals |
| `TWELVEDATA_API_KEY` | Cours US en temps réel (batch) |

**Settings → Secrets and variables → Actions → New repository secret**

## Limites plan TwelveData gratuit

| Capacité | Valeur |
|----------|--------|
| Crédits/minute | 8 |
| Crédits/jour | 800 |
| Indices (SPX, CAC40...) | ❌ Plan payant |
| Actions Euronext | ❌ Plan payant |
| Actions US (PLTR, CRWV, RIOT...) | ✅ |
| Forex (EUR/USD) | ✅ |

Le script gère automatiquement le rate limiting (pause entre batches).

## Algorithme de décision

| Composante | Poids |
|------------|-------|
| Performance vs. prix de revient | 40% |
| Sentiment + consensus analystes | 35% |
| Tendance macro | 25% |

| Score | Recommandation |
|-------|----------------|
| ≥ 7.5 | 🟢 ACHAT FORT |
| ≥ 6.0 | 🔵 ACHAT MODÉRÉ |
| ≥ 4.5 | 🟡 GARDER |
| ≥ 3.0 | 🟠 À ÉVITER |
| < 3.0 | 🔴 VENDRE |

## Changelog

### v3.2 (2026-05-12)
- ✅ Intégration TwelveData comme source principale cours US + EUR/USD
- ✅ Batch unique TwelveData (1 requête = portefeuille + watchlist US)
- ✅ Protocole validation croisée 3 sources avec détection divergence > 2%
- ✅ Médiane automatique en cas de divergence
- ✅ Affichage source réelle pour chaque donnée dans le rapport
- ✅ Rate limiting TwelveData géré automatiquement (8 crédits/min)
- ✅ Tests live confirmés : PLTR ✅, CRWV ✅, RIOT ✅, EUR/USD ✅
