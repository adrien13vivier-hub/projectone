# 📊 Portfolio Analyzer — GitHub Actions

Workflow automatisé qui génère chaque jour ouvré à **16h00 (heure de Paris)** un rapport Markdown complet pour ton portefeuille.

## Structure du projet

```
.
├── portfolio_analyzer.py
├── reports/
│   └── daily_report.md          ← rapport généré automatiquement chaque jour
├── .github/
│   └── workflows/
│       └── daily_analysis.yml
└── README.md
```

## ⚠️ Étape indispensable : ajouter ta clé Finnhub

1. Aller sur ton repo GitHub → **Settings → Secrets and variables → Actions**
2. Cliquer **New repository secret**
3. Nom : `FINNHUB_API_KEY` | Valeur : ta clé Finnhub

## ⚠️ Activer les permissions d'écriture

Dans **Settings → Actions → General → Workflow permissions** → sélectionner **Read and write permissions**.

## Lancer manuellement

Aller dans **Actions → Daily Portfolio Analysis → Run workflow**.

## Logique de recommandation

| Score | Recommandation |
|-------|---------------|
| 8–10  | 🟢 ACHAT FORT |
| 6.5–8 | 🟡 ACHAT MODÉRÉ |
| 5–6.5 | 🔵 GARDER |
| 3.5–5 | 🟠 À ÉVITER |
| 0–3.5 | 🔴 VENDRE |

Score = **40% performance vs. coût** + **35% sentiment & analystes** + **25% tendance macro**
