#!/usr/bin/env python3
"""
Portfolio Analyzer — Daily Report Generator
Uses Finnhub API to analyze portfolio positions and generate a Markdown report.
Runs via GitHub Actions every day at 16:00 Paris time.
"""

import os
import json
import requests
from datetime import datetime
import pytz

# ─── CONFIGURATION ───────────────────────────────────────────────────────────────────────────────────

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
BASE_URL = "https://finnhub.io/api/v1"

# EUR/USD rate fallback (used if live rate fetch fails)
EUR_USD_FALLBACK = 1.08

# Portfolio definition
PORTFOLIO = [
    {
        "name": "Palantir Technologies",
        "symbol": "PLTR",
        "isin": "US69608A1088",
        "qty": 2,
        "avg_cost_eur": 119.06,
        "currency": "USD",
        "exchange": "US",
    },
    {
        "name": "CoreWeave",
        "symbol": "CRWV",
        "isin": "US21873S1087",
        "qty": 2,
        "avg_cost_eur": 93.91,
        "currency": "USD",
        "exchange": "US",
    },
    {
        "name": "Riot Platforms",
        "symbol": "RIOT",
        "isin": "US7672921050",
        "qty": 6,
        "avg_cost_eur": 15.84,
        "currency": "USD",
        "exchange": "US",
    },
    {
        "name": "JCDecaux",
        "symbol": "JCD.PA",
        "isin": "FR0000077919",
        "qty": 2,
        "avg_cost_eur": 17.77,
        "currency": "EUR",
        "exchange": "PA",
    },
    {
        "name": "Crédit Agricole SA",
        "symbol": "ACA.PA",
        "isin": "FR0000045072",
        "qty": 10,
        "avg_cost_eur": 16.90,
        "currency": "EUR",
        "exchange": "PA",
    },
    {
        "name": "Abionyx Pharma",
        "symbol": "ABNX.PA",
        "isin": "FR0012616852",
        "qty": 10,
        "avg_cost_eur": 3.84,
        "currency": "EUR",
        "exchange": "PA",
    },
]

INDICES = {
    "S&P 500":    "^GSPC",
    "CAC 40":     "^FCHI",
    "Nikkei 225": "^N225",
}

WEIGHTS = {
    "price":     0.40,
    "sentiment": 0.35,
    "market":    0.25,
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────────────────────────

def finnhub_get(endpoint: str, params: dict) -> dict:
    params["token"] = FINNHUB_API_KEY
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[WARN] Finnhub request failed ({endpoint}): {e}")
        return {}


def get_eur_usd_rate() -> float:
    data = finnhub_get("forex/rates", {"base": "EUR"})
    try:
        return data["quote"]["USD"]
    except Exception:
        print(f"[WARN] Could not fetch EUR/USD rate; using fallback {EUR_USD_FALLBACK}")
        return EUR_USD_FALLBACK


def get_quote(symbol: str) -> dict:
    return finnhub_get("quote", {"symbol": symbol})


def get_news_sentiment(symbol: str) -> dict:
    return finnhub_get("news-sentiment", {"symbol": symbol})


def get_recommendation_trends(symbol: str) -> list:
    return finnhub_get("stock/recommendation", {"symbol": symbol})


def get_company_news(symbol: str) -> list:
    from datetime import timedelta
    today = datetime.now(pytz.UTC).date()
    week_ago = today - timedelta(days=7)
    data = finnhub_get("company-news", {
        "symbol": symbol,
        "from": week_ago.isoformat(),
        "to": today.isoformat(),
    })
    return data if isinstance(data, list) else []


# ─── SCORING ─────────────────────────────────────────────────────────────────────────────────────

def score_price(pct_change: float) -> float:
    return max(0.0, min(10.0, 5.0 + pct_change / 4.0))


def score_sentiment(sentiment_data: dict, recommendations: list) -> float:
    news_score = 5.0
    sentiment = sentiment_data.get("sentiment", {})
    company_score = sentiment.get("companyNewsScore", None)
    if company_score is not None:
        news_score = company_score * 10.0

    analyst_score = 5.0
    if recommendations:
        latest = recommendations[0]
        buy   = latest.get("buy", 0) + latest.get("strongBuy", 0)
        hold  = latest.get("hold", 0)
        sell  = latest.get("sell", 0) + latest.get("strongSell", 0)
        total = buy + hold + sell
        if total > 0:
            analyst_score = (buy * 10 + hold * 5 + sell * 0) / total

    return (news_score * 0.5 + analyst_score * 0.5)


def score_market(index_changes: dict) -> float:
    if not index_changes:
        return 5.0
    avg = sum(index_changes.values()) / len(index_changes)
    return max(0.0, min(10.0, 5.0 + avg * 2.5))


def final_recommendation(total_score: float) -> str:
    if total_score >= 8.0:
        return "🟢 **ACHAT FORT**"
    elif total_score >= 6.5:
        return "🟡 **ACHAT MODÉRÉ**"
    elif total_score >= 5.0:
        return "🔵 **GARDER**"
    elif total_score >= 3.5:
        return "🟠 **À ÉVITER**"
    else:
        return "🔴 **VENDRE**"


def analyst_consensus_label(recommendations: list) -> str:
    if not recommendations:
        return "N/A"
    latest = recommendations[0]
    buy   = latest.get("buy", 0) + latest.get("strongBuy", 0)
    hold  = latest.get("hold", 0)
    sell  = latest.get("sell", 0) + latest.get("strongSell", 0)
    total = buy + hold + sell
    if total == 0:
        return "N/A"
    parts = []
    if buy:   parts.append(f"Buy: {buy}")
    if hold:  parts.append(f"Hold: {hold}")
    if sell:  parts.append(f"Sell: {sell}")
    majority = max([("Buy", buy), ("Hold", hold), ("Sell", sell)], key=lambda x: x[1])
    return f"{majority[0]} ({' | '.join(parts)})"


def sentiment_label(s: dict) -> str:
    score = s.get("sentiment", {}).get("companyNewsScore", None)
    if score is None:
        return "Neutre (données indisponibles)"
    if score >= 0.6:
        return f"Positif ({score:.2f})"
    elif score >= 0.4:
        return f"Neutre ({score:.2f})"
    else:
        return f"Négatif ({score:.2f})"


# ─── INDEX CONTEXT ────────────────────────────────────────────────────────────────────────────────

def get_index_changes() -> dict:
    changes = {}
    for name, symbol in INDICES.items():
        q = get_quote(symbol)
        if q and q.get("pc") and q.get("c"):
            prev = q["pc"]
            curr = q["c"]
            if prev > 0:
                changes[name] = (curr - prev) / prev * 100
    return changes


def market_trend_label(index_changes: dict) -> str:
    if not index_changes:
        return "Indéterminé (données indisponibles)"
    avg = sum(index_changes.values()) / len(index_changes)
    details = " | ".join(f"{k}: {v:+.2f}%" for k, v in index_changes.items())
    if avg > 0.5:
        return f"📈 Haussière ({details})"
    elif avg < -0.5:
        return f"📉 Baissière ({details})"
    else:
        return f"➡️ Neutre ({details})"


# ─── REPORT GENERATION ────────────────────────────────────────────────────────────────────────────

def generate_report() -> str:
    paris_tz  = pytz.timezone("Europe/Paris")
    now_paris = datetime.now(paris_tz)
    timestamp = now_paris.strftime("%d/%m/%Y à %H:%M (heure de Paris)")

    print("[INFO] Fetching EUR/USD rate...")
    eur_usd = get_eur_usd_rate()

    print("[INFO] Fetching index data...")
    index_changes = get_index_changes()
    market_score  = score_market(index_changes)
    trend_label   = market_trend_label(index_changes)

    lines = []
    lines.append(f"# 📊 Rapport de Portefeuille — {timestamp}")
    lines.append("")
    lines.append(f"> Généré automatiquement par GitHub Actions | Taux EUR/USD : **{eur_usd:.4f}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🌍 Contexte de Marché")
    lines.append("")
    lines.append(f"Tendance générale : {trend_label}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📁 Analyse des Positions")
    lines.append("")

    portfolio_total_invested = 0.0
    portfolio_total_current  = 0.0

    for asset in PORTFOLIO:
        name     = asset["name"]
        symbol   = asset["symbol"]
        qty      = asset["qty"]
        avg_cost = asset["avg_cost_eur"]
        currency = asset["currency"]

        print(f"[INFO] Analyzing {name} ({symbol})...")

        quote           = get_quote(symbol)
        sentiment_data  = get_news_sentiment(symbol)
        recommendations = get_recommendation_trends(symbol)
        news            = get_company_news(symbol)

        current_raw = quote.get("c", 0.0)
        prev_raw    = quote.get("pc", 0.0)

        if currency == "USD":
            current_eur = current_raw / eur_usd if eur_usd else current_raw
            prev_eur    = prev_raw    / eur_usd if eur_usd else prev_raw
        else:
            current_eur = current_raw
            prev_eur    = prev_raw

        daily_pct = (current_eur - prev_eur) / prev_eur * 100 if prev_eur > 0 else 0.0

        if avg_cost > 0 and current_eur > 0:
            latent_pct = (current_eur - avg_cost) / avg_cost * 100
            latent_eur = (current_eur - avg_cost) * qty
        else:
            latent_pct = 0.0
            latent_eur = 0.0

        total_invested = avg_cost * qty
        total_current  = current_eur * qty
        portfolio_total_invested += total_invested
        portfolio_total_current  += total_current

        p_score  = score_price(latent_pct)
        s_score  = score_sentiment(sentiment_data, recommendations)
        weighted = (
            p_score      * WEIGHTS["price"] +
            s_score      * WEIGHTS["sentiment"] +
            market_score * WEIGHTS["market"]
        )
        reco          = final_recommendation(weighted)
        consensus_txt = analyst_consensus_label(recommendations)
        sentiment_txt = sentiment_label(sentiment_data)
        headline      = news[0]["headline"] if news else "Aucune actualité récente."
        status_emoji  = "🟢" if latent_pct >= 0 else "🔴"

        lines.append(f"### {status_emoji} {name} (`{symbol}`)")
        lines.append("")
        lines.append("| Paramètre | Valeur |")
        lines.append("|-----------|--------|")
        lines.append(f"| Quantité | {qty} action(s) |")
        lines.append(f"| Prix de revient | {avg_cost:.2f} € |")
        lines.append(f"| Cours actuel (converti EUR) | {current_eur:.2f} € |")
        lines.append(f"| Variation du jour | {daily_pct:+.2f}% |")
        lines.append(f"| **Statut latent** | **{latent_pct:+.2f}% ({latent_eur:+.2f} €)** |")
        lines.append(f"| Valeur totale position | {total_current:.2f} € |")
        lines.append(f"| Consensus analystes | {consensus_txt} |")
        lines.append(f"| Sentiment presse | {sentiment_txt} |")
        lines.append(f"| Score pondéré | {weighted:.1f}/10 |")
        lines.append("")
        lines.append("**📰 Analyse Flash**")
        lines.append(f"> {headline}")
        lines.append("")
        lines.append(f"**🎯 Action recommandée : {reco}**")
        lines.append("")

        if weighted >= 6.5:
            justif = (f"Le titre affiche {latent_pct:+.1f}% vs. coût. Sentiment {sentiment_txt.lower()} et consensus favorable ({consensus_txt}). La tendance macro soutient la position.")
        elif weighted >= 5.0:
            justif = (f"Position à {latent_pct:+.1f}% vs. coût. Pas de signal fort — conserver en attendant plus de visibilité. Consensus : {consensus_txt}.")
        else:
            justif = (f"Position en {latent_pct:+.1f}% vs. coût. Sentiment {sentiment_txt.lower()} et consensus faible ({consensus_txt}). Réduire l'exposition ou poser un stop-loss est prudent.")

        lines.append(f"**💬 Justification :** {justif}")
        lines.append("")
        lines.append("---")
        lines.append("")

    total_pnl     = portfolio_total_current - portfolio_total_invested
    total_pnl_pct = (total_pnl / portfolio_total_invested * 100) if portfolio_total_invested > 0 else 0

    lines.append("## 📈 Résumé du Portefeuille")
    lines.append("")
    lines.append("| | Valeur |")
    lines.append("|-|--------|")
    lines.append(f"| Capital investi | {portfolio_total_invested:.2f} € |")
    lines.append(f"| Valorisation actuelle | {portfolio_total_current:.2f} € |")
    lines.append(f"| **P&L latent total** | **{total_pnl:+.2f} € ({total_pnl_pct:+.2f}%)** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Rapport généré le {timestamp} — Données fournies par [Finnhub](https://finnhub.io). Ce rapport est informatif et ne constitue pas un conseil en investissement.*")

    return "\n".join(lines)


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not FINNHUB_API_KEY:
        raise EnvironmentError("FINNHUB_API_KEY environment variable not set.")

    report_md = generate_report()

    output_path = "reports/daily_report.md"
    os.makedirs("reports", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"[OK] Report saved to {output_path}")
    print("\n" + "=" * 60 + "\n")
    print(report_md)
