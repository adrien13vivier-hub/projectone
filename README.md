# 📊 Portfolio Analyzer v3.1

Rapport quotidien automatisé à **16h00 Paris** — Finnhub + EODHD avec fallbacks croisés complets.

## Structure

```
portfolio-analyzer/
├── portfolio_analyzer.py
├── .github/workflows/daily_analysis.yml
├── reports/daily_report.md
└── README.md
```

## Secrets GitHub requis

| Nom | Description |
|-----|-------------|
| `FINNHUB_API_KEY` | Clé Finnhub (sentiment, consensus, forex) |
| `EODHD_API_KEY` | Clé EODHD régénérée (cours, indices, news) |

**Settings → Secrets and variables → Actions → New repository secret**

## Fallbacks croisés v3.1

| Donnée | Source principale | Fallback |
|--------|-----------------|----------|
| Cours US | EODHD `real-time/*.US` | Finnhub `quote` |
| Cours Euronext `.PA` | EODHD `real-time/*.PA` | Finnhub `quote` |
| Taux EUR/USD | Finnhub `forex/rates` | EODHD `EURUSD.FOREX` |
| Indices macro | EODHD `*.INDX` | Finnhub `^GSPC/^FCHI/^N225` |
| Sentiment presse | Finnhub `news-sentiment` | Analyse lexicale EODHD news |
| Consensus analystes | Finnhub `recommendation-trends` | EODHD `fundamentals` |
| Actualités entreprise | EODHD `news` | Finnhub `company-news` |
| Actualités macro | EODHD `news?t=general` | Finnhub `news?category=general` |

## Algorithme de décision

| Composante | Poids |
|------------|-------|
| Performance vs. prix de revient | 40 % |
| Sentiment + consensus analystes | 35 % |
| Tendance macro | 25 % |

| Score | Recommandation |
|-------|----------------|
| ≥ 7.5 | 🟢 ACHAT FORT |
| ≥ 6.0 | 🔵 ACHAT MODÉRÉ |
| ≥ 4.5 | 🟡 GARDER |
| ≥ 3.0 | 🟠 À ÉVITER |
| < 3.0 | 🔴 VENDRE |

## Frais courtage BoursoBank (Découverte — 13/11/2025)

| Marché | Barème |
|--------|--------|
| Euronext Paris/Amsterdam/Bruxelles | 1,99 € ≤ 500 € · 0,60 % au-delà |
| Bourses américaines | 6,95 € ≤ 6 000 € · 0,12 % au-delà |
| Bourses européennes hors Euronext | 11,95 € ≤ 4 000 € · 0,30 % au-delà |

## Ajustement saisonnier cron

| Saison | Cron |
|--------|------|
| Été CEST (UTC+2) | `0 14 * * 1-5` |
| Hiver CET (UTC+1) | `0 15 * * 1-5` |
