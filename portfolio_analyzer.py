#!/usr/bin/env python3
"""
Portfolio Analyzer — Daily Report Generator
Uses EODHD (indices + all stocks) + Finnhub (sentiment + analyst consensus)
Runs via GitHub Actions every weekday at 16:00 and 18:30 Paris time.
"""

import os
import requests
from datetime import datetime, timedelta
import pytz

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

FINNHUB_KEY  = os.environ.get("FINNHUB_API_KEY", "")
EODHD_KEY    = os.environ.get("EODHD_API_KEY", "")
FINNHUB_URL  = "https://finnhub.io/api/v1"
EODHD_URL    = "https://eodhd.com/api"

# Boursobank brokerage fee model
# Standard: 1.99€ flat per order under 500€, 3.90€ above — we store per-position fee paid
BROKERAGE_FEES = {
    "PLTR":    1.99,
    "CRWV":    1.99,
    "RIOT":    1.99,
    "JCD.PA":  1.99,
    "ACA.PA":  1.99,
    "ABNX.PA": 1.99,
}

PORTFOLIO = [
    {"name": "Palantir Technologies", "symbol": "PLTR",    "eodhd": "PLTR.US",   "qty": 2,  "avg_cost_eur": 119.06, "currency": "USD"},
    {"name": "CoreWeave",             "symbol": "CRWV",    "eodhd": "CRWV.US",   "qty": 2,  "avg_cost_eur": 93.91,  "currency": "USD"},
    {"name": "Riot Platforms",        "symbol": "RIOT",    "eodhd": "RIOT.US",   "qty": 6,  "avg_cost_eur": 15.84,  "currency": "USD"},
    {"name": "JCDecaux",              "symbol": "JCD.PA",  "eodhd": "JCD.PA",    "qty": 2,  "avg_cost_eur": 17.77,  "currency": "EUR"},
    {"name": "Cr\u00e9dit Agricole SA",   "symbol": "ACA.PA",  "eodhd": "ACA.PA",    "qty": 10, "avg_cost_eur": 16.90,  "currency": "EUR"},
    {"name": "Abionyx Pharma",        "symbol": "ABNX.PA", "eodhd": "ABNX.PA",   "qty": 10, "avg_cost_eur": 3.84,   "currency": "EUR"},
]

INDICES = {
    "S&P 500":    "GSPC.INDX",
    "CAC 40":     "FCHI.INDX",
    "Nikkei 225": "N225.INDX",
}

WEIGHTS = {"price": 0.40, "sentiment": 0.35, "market": 0.25}

# ─── EODHD HELPERS ────────────────────────────────────────────────────────────

def eodhd_get(endpoint: str, params: dict) -> dict:
    params["api_token"] = EODHD_KEY
    params["fmt"] = "json"
    try:
        r = requests.get(f"{EODHD_URL}/{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[WARN] EODHD {endpoint}: {e}")
        return {}

def get_eodhd_quote(ticker: str) -> dict:
    """Returns latest EOD quote: close, previousClose, change_p"""
    data = eodhd_get(f"real-time/{ticker}", {"s": ticker})
    if isinstance(data, dict) and data.get("close"):
        return data
    # fallback: end-of-day historical
    today = datetime.now(pytz.UTC).date()
    from_date = (today - timedelta(days=5)).isoformat()
    hist = eodhd_get(f"eod/{ticker}", {"from": from_date, "to": today.isoformat(), "period": "d"})
    if isinstance(hist, list) and len(hist) >= 2:
        last = hist[-1]
        prev = hist[-2]
        last["previousClose"] = prev["close"]
        last["change_p"] = (last["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0
        last["close"] = last["close"]
        return last
    elif isinstance(hist, list) and len(hist) == 1:
        last = hist[-1]
        last["previousClose"] = last["close"]
        last["change_p"] = 0
        return last
    return {}

def get_eur_usd_rate() -> float:
    data = eodhd_get("real-time/EURUSD.FOREX", {"s": "EURUSD.FOREX"})
    try:
        rate = float(data.get("close") or data.get("previousClose") or 0)
        if rate > 0:
            return rate
    except Exception:
        pass
    # Finnhub fallback
    try:
        r = requests.get(f"{FINNHUB_URL}/forex/rates", params={"base": "EUR", "token": FINNHUB_KEY}, timeout=10)
        return r.json()["quote"]["USD"]
    except Exception:
        return 1.08

def get_index_changes() -> dict:
    changes = {}
    for name, ticker in INDICES.items():
        q = get_eodhd_quote(ticker)
        cp = q.get("change_p") or q.get("change_percent")
        if cp is not None:
            try:
                changes[name] = float(str(cp).replace("%", ""))
                continue
            except Exception:
                pass
        c  = float(q.get("close") or 0)
        pc = float(q.get("previousClose") or q.get("open") or 0)
        if c and pc:
            changes[name] = (c - pc) / pc * 100
    return changes

# ─── FINNHUB HELPERS ──────────────────────────────────────────────────────────

def finnhub_get(endpoint: str, params: dict) -> dict:
    params["token"] = FINNHUB_KEY
    try:
        r = requests.get(f"{FINNHUB_URL}/{endpoint}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[WARN] Finnhub {endpoint}: {e}")
        return {}

def get_news_sentiment(symbol: str) -> dict:
    return finnhub_get("news-sentiment", {"symbol": symbol.replace(".PA", "")})

def get_recommendation_trends(symbol: str) -> list:
    data = finnhub_get("stock/recommendation", {"symbol": symbol.replace(".PA", "")})
    return data if isinstance(data, list) else []

def get_company_news(symbol: str) -> list:
    today = datetime.now(pytz.UTC).date()
    week_ago = today - timedelta(days=7)
    data = finnhub_get("company-news", {
        "symbol": symbol.replace(".PA", ""),
        "from": week_ago.isoformat(),
        "to": today.isoformat(),
    })
    return data if isinstance(data, list) else []

# ─── SCORING ──────────────────────────────────────────────────────────────────

def score_price(pct: float) -> float:
    return max(0.0, min(10.0, 5.0 + pct / 4.0))

def score_sentiment(sentiment_data: dict, recommendations: list) -> float:
    news_score = 5.0
    company_score = sentiment_data.get("sentiment", {}).get("companyNewsScore")
    if company_score is not None:
        news_score = float(company_score) * 10.0

    analyst_score = 5.0
    if recommendations:
        l = recommendations[0]
        buy  = l.get("buy", 0) + l.get("strongBuy", 0)
        hold = l.get("hold", 0)
        sell = l.get("sell", 0) + l.get("strongSell", 0)
        total = buy + hold + sell
        if total > 0:
            analyst_score = (buy * 10 + hold * 5) / total
    return news_score * 0.5 + analyst_score * 0.5

def score_market(index_changes: dict) -> float:
    if not index_changes:
        return 5.0
    avg = sum(index_changes.values()) / len(index_changes)
    return max(0.0, min(10.0, 5.0 + avg * 2.5))

def final_recommendation(score: float) -> str:
    if score >= 8.0:   return "\U0001f7e2 **ACHAT FORT**"
    elif score >= 6.5: return "\U0001f7e1 **ACHAT MOD\u00c9R\u00c9**"
    elif score >= 5.0: return "\U0001f535 **GARDER**"
    elif score >= 3.5: return "\U0001f7e0 **\u00c0 \u00c9VITER**"
    else:              return "\U0001f534 **VENDRE**"

def analyst_consensus_label(recommendations: list) -> str:
    if not recommendations:
        return "N/A"
    l = recommendations[0]
    buy  = l.get("buy", 0) + l.get("strongBuy", 0)
    hold = l.get("hold", 0)
    sell = l.get("sell", 0) + l.get("strongSell", 0)
    total = buy + hold + sell
    if total == 0:
        return "N/A"
    parts = []
    if buy:  parts.append(f"Buy: {buy}")
    if hold: parts.append(f"Hold: {hold}")
    if sell: parts.append(f"Sell: {sell}")
    majority = max([("Buy", buy), ("Hold", hold), ("Sell", sell)], key=lambda x: x[1])
    return f"{majority[0]} ({' | '.join(parts)})"

def sentiment_label(s: dict) -> str:
    score = s.get("sentiment", {}).get("companyNewsScore")
    if score is None:
        return "Neutre (donn\u00e9es indisponibles)"
    score = float(score)
    if score >= 0.6:   return f"Positif ({score:.2f})"
    elif score >= 0.4: return f"Neutre ({score:.2f})"
    else:              return f"N\u00e9gatif ({score:.2f})"

def market_trend_label(index_changes: dict) -> str:
    if not index_changes:
        return "Ind\u00e9termin\u00e9 (donn\u00e9es indisponibles)"
    avg = sum(index_changes.values()) / len(index_changes)
    details = " | ".join(f"{k}: {v:+.2f}%" for k, v in index_changes.items())
    if avg > 0.5:   return f"\U0001f4c8 Haussi\u00e8re ({details})"
    elif avg < -0.5: return f"\U0001f4c9 Baissi\u00e8re ({details})"
    else:            return f"\u27a1\ufe0f Neutre ({details})"

def build_justification(name: str, latent_pct: float, latent_eur: float,
                         daily_pct: float, score: float,
                         sentiment_txt: str, consensus_txt: str,
                         index_changes: dict, fee: float) -> str:
    trend = "haussier" if sum(index_changes.values()) / max(len(index_changes), 1) > 0 else "baissier"
    fee_note = f" (frais de courtage Boursobank de {fee:.2f}\u20ac int\u00e9gr\u00e9s dans le calcul)"
    if score >= 8.0:
        return (f"{name} affiche une performance latente de {latent_pct:+.1f}% ({latent_eur:+.2f}\u20ac){fee_note}. "
                f"Le contexte macro est {trend} et le consensus analystes est tr\u00e8s favorable ({consensus_txt}). "
                f"Le sentiment de presse est {sentiment_txt.lower()}. Tous les indicateurs convergent : renforcement opportun.")
    elif score >= 6.5:
        return (f"{name} est en {latent_pct:+.1f}% ({latent_eur:+.2f}\u20ac){fee_note}. "
                f"Le march\u00e9 est globalement {trend}. Consensus : {consensus_txt}. "
                f"Sentiment : {sentiment_txt.lower()}. La dynamique est positive mais sans signal d\u2019entr\u00e9e urgent — "
                f"un renforcement progressif est envisageable sur repli.")
    elif score >= 5.0:
        return (f"{name} est \u00e0 {latent_pct:+.1f}% ({latent_eur:+.2f}\u20ac){fee_note}. "
                f"Variation du jour : {daily_pct:+.2f}%. Pas de catalyseur clair identifi\u00e9. "
                f"Consensus : {consensus_txt}. Sentiment : {sentiment_txt.lower()}. "
                f"Conserver la position sans la renforcer tant que le march\u00e9 reste {trend}.")
    elif score >= 3.5:
        return (f"Position fragile : {latent_pct:+.1f}% ({latent_eur:+.2f}\u20ac){fee_note}. "
                f"Variation du jour inqui\u00e9tante : {daily_pct:+.2f}%. Sentiment : {sentiment_txt.lower()}. "
                f"Consensus : {consensus_txt}. Poser un stop-loss et \u00e9viter de renforcer dans ce contexte {trend}.")
    else:
        return (f"Signal de vente d\u00e9clench\u00e9 : {latent_pct:+.1f}% ({latent_eur:+.2f}\u20ac){fee_note}. "
                f"Contexte macro {trend}, sentiment {sentiment_txt.lower()}, consensus faible ({consensus_txt}). "
                f"Solder la position limite les pertes suppl\u00e9mentaires.")

def build_conclusion(positions: list, index_changes: dict, market_score: float) -> str:
    avg_market = sum(index_changes.values()) / max(len(index_changes), 1) if index_changes else 0
    trend_word = "haussier" if avg_market > 0.5 else ("baissier" if avg_market < -0.5 else "neutre")
    index_str = " | ".join(f"{k}: {v:+.2f}%" for k, v in index_changes.items()) if index_changes else "donn\u00e9es indisponibles"

    gainers = [p for p in positions if p["latent_pct"] > 0]
    losers  = [p for p in positions if p["latent_pct"] < 0]
    best    = max(positions, key=lambda x: x["latent_pct"])
    worst   = min(positions, key=lambda x: x["latent_pct"])

    lines = []
    lines.append("## \U0001f9e0 Conclusion G\u00e9n\u00e9rale")
    lines.append("")
    lines.append(f"**Contexte macro du jour :** {index_str}. ")
    lines.append(f"Les march\u00e9s sont actuellement en phase **{trend_word}**, ce qui ")
    if trend_word == "haussier":
        lines.append("soutient les positions risqu\u00e9es (tech, crypto-li\u00e9es) du portefeuille.")
    elif trend_word == "baissier":
        lines.append("incite \u00e0 la prudence et \u00e0 r\u00e9duire l\u2019exposition aux actifs volatils.")
    else:
        lines.append("ne donne pas de direction claire \u2014 rester vigilant et attendre une confirmation.")
    lines.append("")
    lines.append(f"**Positions en gain ({len(gainers)}/{len(positions)}) :** " +
                 ", ".join(f"{p['name']} ({p['latent_pct']:+.1f}%)" for p in gainers) if gainers else "**Aucune position en gain.**")
    lines.append("")
    if losers:
        lines.append(f"**Positions en perte ({len(losers)}/{len(positions)}) :** " +
                     ", ".join(f"{p['name']} ({p['latent_pct']:+.1f}%)" for p in losers))
        lines.append("")
    lines.append(f"**Meilleure performance :** {best['name']} \u00e0 {best['latent_pct']:+.1f}%")
    lines.append(f"**Performance \u00e0 surveiller :** {worst['name']} \u00e0 {worst['latent_pct']:+.1f}%")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### \U0001f4a1 Recommandations Hors Portefeuille (haute conviction)")
    lines.append("")
    lines.append("Ces suggestions sont coh\u00e9rentes avec le profil de risque du portefeuille actuel (tech US + crypto + mid-caps FR) :")
    lines.append("")
    if trend_word in ("haussier", "neutre"):
        lines.append("| Valeur | Ticker | Th\u00e8se | Niveau de confiance |")
        lines.append("|--------|--------|-------|---------------------|")
        lines.append("| **NVIDIA** | `NVDA` | Leader IA incontournable, croissance datacenter explosive, consensus Buy massif | \u2b50\u2b50\u2b50\u2b50\u2b50 Tr\u00e8s \u00e9lev\u00e9 |")
        lines.append("| **Microsoft** | `MSFT` | Exposition IA via Azure + OpenAI, r\u00e9silience en cas de correction, dividende | \u2b50\u2b50\u2b50\u2b50 \u00c9lev\u00e9 |")
        lines.append("| **MicroStrategy** | `MSTR` | Proxy Bitcoin structurel, coh\u00e9rent avec d\u00e9tention de RIOT dans le portefeuille | \u2b50\u2b50\u2b50 Mod\u00e9r\u00e9 (volatilit\u00e9 \u00e9lev\u00e9e) |")
        lines.append("| **Safran** | `SAF.PA` | Fleuron industriel fran\u00e7ais, carnet de commandes record, d\u00e9corr\u00e9l\u00e9 du secteur tech | \u2b50\u2b50\u2b50\u2b50 \u00c9lev\u00e9 |")
        lines.append("| **ASML** | `ASML.PA` | Monopole mondial sur les machines EUV, indispensable \u00e0 toute la cha\u00eene semi-conducteurs | \u2b50\u2b50\u2b50\u2b50\u2b50 Tr\u00e8s \u00e9lev\u00e9 |")
    else:
        lines.append("| Valeur | Ticker | Th\u00e8se | Niveau de confiance |")
        lines.append("|--------|--------|-------|---------------------|")
        lines.append("| **Gold ETF** | `GLD` | Valeur refuge en contexte baissier, couverture naturelle contre la volatilit\u00e9 | \u2b50\u2b50\u2b50\u2b50\u2b50 Tr\u00e8s \u00e9lev\u00e9 |")
        lines.append("| **NVIDIA** | `NVDA` | Point d\u2019entr\u00e9e attractif en cas de repli tech, fondamentaux solides | \u2b50\u2b50\u2b50\u2b50 \u00c9lev\u00e9 |")
        lines.append("| **Sanofi** | `SAN.PA` | D\u00e9fensif, dividende r\u00e9gulier, non corr\u00e9l\u00e9 au cycle tech | \u2b50\u2b50\u2b50\u2b50 \u00c9lev\u00e9 |")
        lines.append("| **L\u2019Or\u00e9al** | `OR.PA` | R\u00e9silience historique en baisse de march\u00e9, marque premium mondiale | \u2b50\u2b50\u2b50\u2b50 \u00c9lev\u00e9 |")
    lines.append("")
    lines.append("> \u26a0\ufe0f *Ces recommandations sont g\u00e9n\u00e9r\u00e9es automatiquement \u00e0 titre informatif et ne constituent pas un conseil en investissement r\u00e9glement\u00e9.*")
    return "\n".join(lines)

# ─── MAIN REPORT ──────────────────────────────────────────────────────────────

def generate_report() -> str:
    paris_tz  = pytz.timezone("Europe/Paris")
    now_paris = datetime.now(paris_tz)
    timestamp = now_paris.strftime("%d/%m/%Y \u00e0 %H:%M (heure de Paris)")

    print("[INFO] Fetching EUR/USD rate...")
    eur_usd = get_eur_usd_rate()
    print(f"[INFO] EUR/USD = {eur_usd:.4f}")

    print("[INFO] Fetching index data...")
    index_changes = get_index_changes()
    print(f"[INFO] Indices: {index_changes}")
    market_score = score_market(index_changes)
    trend_label  = market_trend_label(index_changes)

    lines = []
    lines.append(f"# \U0001f4ca Rapport de Portefeuille \u2014 {timestamp}")
    lines.append("")
    lines.append(f"> G\u00e9n\u00e9r\u00e9 automatiquement via GitHub Actions | Taux EUR/USD : **{eur_usd:.4f}** | Source : EODHD + Finnhub")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## \U0001f30d Contexte de March\u00e9")
    lines.append("")
    if index_changes:
        lines.append(f"Tendance g\u00e9n\u00e9rale : **{trend_label}**")
        lines.append("")
        lines.append("| Indice | Variation du jour |")
        lines.append("|--------|-------------------|")
        for name, chg in index_changes.items():
            emoji = "\U0001f4c8" if chg > 0 else "\U0001f4c9"
            lines.append(f"| {name} | {emoji} {chg:+.2f}% |")
    else:
        lines.append("Tendance g\u00e9n\u00e9rale : Donn\u00e9es indisponibles pour cette session.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## \U0001f4c1 Analyse des Positions")
    lines.append("")

    portfolio_total_invested = 0.0
    portfolio_total_current  = 0.0
    portfolio_total_fees     = 0.0
    positions_data = []

    for asset in PORTFOLIO:
        name     = asset["name"]
        symbol   = asset["symbol"]
        eodhd    = asset["eodhd"]
        qty      = asset["qty"]
        avg_cost = asset["avg_cost_eur"]
        currency = asset["currency"]
        fee      = BROKERAGE_FEES.get(symbol, 1.99)

        print(f"[INFO] Analyzing {name} ({eodhd})...")

        quote           = get_eodhd_quote(eodhd)
        sentiment_data  = get_news_sentiment(symbol)
        recommendations = get_recommendation_trends(symbol)
        news            = get_company_news(symbol)

        current_raw = float(quote.get("close") or quote.get("adjusted_close") or 0.0)
        prev_raw    = float(quote.get("previousClose") or quote.get("open") or current_raw)

        if currency == "USD" and eur_usd > 0:
            current_eur = current_raw / eur_usd
            prev_eur    = prev_raw    / eur_usd
        else:
            current_eur = current_raw
            prev_eur    = prev_raw

        daily_pct = (current_eur - prev_eur) / prev_eur * 100 if prev_eur > 0 else 0.0

        # PnL includes brokerage fee spread over position
        fee_per_share    = fee / qty
        real_cost        = avg_cost + fee_per_share
        latent_eur_gross = (current_eur - avg_cost) * qty
        latent_eur_net   = latent_eur_gross - fee
        latent_pct       = (current_eur - real_cost) / real_cost * 100 if real_cost > 0 and current_eur > 0 else 0.0

        total_invested = real_cost * qty
        total_current  = current_eur * qty
        portfolio_total_invested += total_invested
        portfolio_total_current  += total_current
        portfolio_total_fees     += fee

        p_score  = score_price(latent_pct)
        s_score  = score_sentiment(sentiment_data, recommendations)
        weighted = p_score * WEIGHTS["price"] + s_score * WEIGHTS["sentiment"] + market_score * WEIGHTS["market"]

        reco          = final_recommendation(weighted)
        consensus_txt = analyst_consensus_label(recommendations)
        sentiment_txt = sentiment_label(sentiment_data)
        headline      = news[0]["headline"] if news else "Aucune actualit\u00e9 r\u00e9cente disponible."
        status_emoji  = "\U0001f7e2" if latent_pct >= 0 else "\U0001f534"

        positions_data.append({"name": name, "latent_pct": latent_pct, "score": weighted})

        lines.append(f"### {status_emoji} {name} (`{symbol}`)")
        lines.append("")
        lines.append("| Param\u00e8tre | Valeur |")
        lines.append("|-----------|--------|")
        lines.append(f"| Quantit\u00e9 | {qty} action(s) |")
        lines.append(f"| Prix de revient brut | {avg_cost:.2f}\u20ac |")
        lines.append(f"| Frais Boursobank | {fee:.2f}\u20ac |")
        lines.append(f"| Prix de revient r\u00e9el (frais inclus) | {real_cost:.2f}\u20ac/action |")
        lines.append(f"| Cours actuel | {current_eur:.2f}\u20ac |")
        lines.append(f"| Variation du jour | {daily_pct:+.2f}% |")
        lines.append(f"| **P&L latent net** | **{latent_pct:+.2f}% ({latent_eur_net:+.2f}\u20ac)** |")
        lines.append(f"| Valeur totale position | {total_current:.2f}\u20ac |")
        lines.append(f"| Consensus analystes | {consensus_txt} |")
        lines.append(f"| Sentiment presse | {sentiment_txt} |")
        lines.append(f"| Score pond\u00e9r\u00e9 | {weighted:.1f}/10 |")
        lines.append("")
        lines.append("**\U0001f4f0 Derni\u00e8re actualit\u00e9**")
        lines.append(f"> {headline}")
        lines.append("")
        lines.append(f"**\U0001f3af Action recommand\u00e9e : {reco}**")
        lines.append("")
        justif = build_justification(name, latent_pct, latent_eur_net, daily_pct,
                                     weighted, sentiment_txt, consensus_txt, index_changes, fee)
        lines.append(f"**\U0001f4ac Justification :** {justif}")
        lines.append("")
        lines.append("---")
        lines.append("")

    total_pnl     = portfolio_total_current - portfolio_total_invested
    total_pnl_pct = total_pnl / portfolio_total_invested * 100 if portfolio_total_invested > 0 else 0
    pnl_emoji     = "\U0001f4c8" if total_pnl >= 0 else "\U0001f4c9"

    lines.append("## \U0001f4b0 R\u00e9sum\u00e9 du Portefeuille")
    lines.append("")
    lines.append("| | Valeur |")
    lines.append("|-|--------|")
    lines.append(f"| Capital investi (frais inclus) | {portfolio_total_invested:.2f}\u20ac |")
    lines.append(f"| Frais de courtage totaux | {portfolio_total_fees:.2f}\u20ac |")
    lines.append(f"| Valorisation actuelle | {portfolio_total_current:.2f}\u20ac |")
    lines.append(f"| **P&L latent net** | **{pnl_emoji} {total_pnl:+.2f}\u20ac ({total_pnl_pct:+.2f}%)** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(build_conclusion(positions_data, index_changes, market_score))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Rapport g\u00e9n\u00e9r\u00e9 le {timestamp} \u2014 Donn\u00e9es : [EODHD](https://eodhd.com) + [Finnhub](https://finnhub.io). Ce rapport est informatif et ne constitue pas un conseil en investissement.*")

    return "\n".join(lines)

if __name__ == "__main__":
    if not EODHD_KEY:
        raise EnvironmentError("EODHD_API_KEY environment variable not set.")
    report_md = generate_report()
    os.makedirs("reports", exist_ok=True)
    with open("reports/daily_report.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    print("[OK] Report saved to reports/daily_report.md")
