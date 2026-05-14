# 📊 Portfolio Analyzer v5.1

Rapport quotidien automatisé à **16h00 Paris (CEST)** via GitHub Actions — 4 sources de données avec validation croisée et fallback en cascade.

## Architecture des sources

```
EUR/USD (forex)  : AlphaVantage (principal) → cache session
COURS US         : TwelveData (batch par 6) → EODHD real-time → cache
COURS EU (.PA)   : EODHD (principal) → cache
INDICES MACRO    : EODHD → Finnhub → cache
SENTIMENT presse : Finnhub /news-sentiment → analyse lexicale EODHD
CONSENSUS        : Finnhub /recommendation → EODHD fundamentals
NEWS sociétés    : EODHD → Finnhub
```

## Protocole de validation croisée

Si deux sources retournent un écart > **2%** sur un même cours :
- ⚠️ Divergence signalée dans le rapport (section dédiée)
- La **médiane** des deux valeurs est utilisée automatiquement
- Un email d'alerte est envoyé immédiatement

## Secrets GitHub requis (4)

| Nom | Rôle |
|-----|------|
| `ALPHAVANTAGE_API_KEY` | Taux EUR/USD (forex principal) |
| `EODHD_API_KEY` | Cours Euronext, indices, news, fundamentals |
| `TWELVEDATA_API_KEY` | Cours US en temps réel (batch) |
| `FINNHUB_API_KEY` | Sentiment presse, consensus analystes |

**Settings → Secrets and variables → Actions → New repository secret**

### Secrets SMTP optionnels (envoi mail)

| Nom | Description |
|-----|-------------|
| `MAIL_SERVER` | Serveur SMTP (ex: smtp.gmail.com) |
| `MAIL_PORT` | Port SMTP (ex: 465) |
| `MAIL_USERNAME` | Adresse email expéditeur |
| `MAIL_PASSWORD` | Mot de passe / App password |
| `MAIL_FROM` | Adresse affichée en expéditeur |
| `MAIL_TO` | Adresse destinataire |

## Limites des plans gratuits

| API | Quota gratuit | Usages dans le projet |
|-----|---------------|-----------------------|
| **AlphaVantage** | 25 req/jour | 1 req/run (EUR/USD) |
| **TwelveData** | 800 req/jour · 8 req/min | ~6 req/run (cours US batch) |
| **EODHD** | 100 000 req/jour | Cours EU + indices + news + fundamentals |
| **Finnhub** | 60 req/min | Sentiment + consensus |

> **Note** : TwelveData plan Free couvre uniquement les bourses US et crypto. Les actions Euronext (`.PA`, `.AS`, etc.) et les indices (CAC40, SPX) nécessitent le plan Grow (29$/mois).

## Algorithme de décision v5.1

| Composante | Poids |
|------------|-------|
| Prix vs. prix de revient (historique) | 30% |
| Tendance historique (performance mensuelle) | 30% |
| Sentiment presse + consensus analystes | 20% |
| Consensus analystes | 20% |

| Score | Recommandation |
|-------|----------------|
| ≥ 7.5 | 🟢 ACHAT FORT |
| ≥ 6.0 | 🔵 ACHAT MODÉRÉ |
| ≥ 4.5 | 🟡 GARDER |
| ≥ 3.0 | 🟠 À ÉVITER |
| < 3.0 | 🔴 VENDRE |

## Fichiers générés

| Fichier | Description |
|---------|-------------|
| `reports/daily_report.md` | Rapport Markdown complet du jour |
| `reports/charts/*.png` | Graphiques de performance mensuels |
| `reports/history.csv` | Historique des PnL quotidiens |
| `docs/index.html` | Rapport HTML interactif (Cloudflare Pages) |
| `cache/session_cache.json` | Cache fallback des derniers cours valides |

## Changelog

### v5.1 (2026-05-13)
- ✅ Assignation stricte des clés API par spécialité (AlphaVantage → forex, TwelveData → US, EODHD → EU/indices, Finnhub → sentiment/consensus)
- ✅ Vérification quota journalier avant chaque appel API
- ✅ Cache GitHub comme fallback final si tous les quotas dépassés
- ✅ Suppression de l'affichage des sources dans les cellules du rapport
- ✅ Harmonisation version v5.1 sur tous les fichiers (YAML, HTML, mail)

### v5.0 (2026-05-13)
- ✅ Réaffectation complète des clés API par spécialité
- ✅ Fallback cache GitHub en cas d'échec toutes sources

### v4.1 (2026-05-13)
- ✅ Intégration AlphaVantage comme 4ème source (forex principal)
- ✅ ALPHAVANTAGE_API_KEY ajouté dans le workflow

### v3.2 (2026-05-12)
- ✅ Intégration TwelveData comme source principale cours US + EUR/USD
- ✅ Batch unique TwelveData (1 requête = portefeuille + watchlist US)
- ✅ Protocole validation croisée 3 sources avec détection divergence > 2%
- ✅ Médiane automatique en cas de divergence
- ✅ Rate limiting TwelveData géré automatiquement (8 crédits/min)
