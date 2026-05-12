#!/usr/bin/env python3
"""
Portfolio Analyzer v3.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Finnhub + EODHD avec fallbacks croisés complets sur
chaque type de donnée. Aucune donnée ne reste vide
tant qu'au moins une API répond.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# ─── CLÉS API ────────────────────────────────────────────────────────────────
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
EODHD_KEY   = os.environ.get("EODHD_API_KEY", "")

if not FINNHUB_KEY:
    raise EnvironmentError("Secret GitHub manquant : FINNHUB_API_KEY")
if not EODHD_KEY:
    raise EnvironmentError("Secret GitHub manquant : EODHD_API_KEY")

FH_BASE  = "https://finnhub.io/api/v1"
EOD_BASE = "https://eodhd.com/api"
PARIS_TZ = ZoneInfo("Europe/Paris")

# ─── PORTEFEUILLE ─────────────────────────────────────────────────────────────
PORTFOLIO = [
    {"name": "Palantir Technologies", "isin": "US69608A1088",
     "ticker_fh": "PLTR",    "ticker_eod": "PLTR.US",  "qty": 2,  "cost_eur": 119.06, "marche": "us"},
    {"name": "CoreWeave",             "isin": "US21873S1087",
     "ticker_fh": "CRWV",    "ticker_eod": "CRWV.US",  "qty": 2,  "cost_eur": 93.91,  "marche": "us"},
    {"name": "Riot Platforms",        "isin": "US7672921050",
     "ticker_fh": "RIOT",    "ticker_eod": "RIOT.US",  "qty": 6,  "cost_eur": 15.84,  "marche": "us"},
    {"name": "JCDecaux",              "isin": "FR0000077919",
     "ticker_fh": "DEC.PA",  "ticker_eod": "DEC.PA",   "qty": 2,  "cost_eur": 17.77,  "marche": "euronext"},
    {"name": "Crédit Agricole SA",    "isin": "FR0000045072",
     "ticker_fh": "ACA.PA",  "ticker_eod": "ACA.PA",   "qty": 10, "cost_eur": 16.90,  "marche": "euronext"},
    {"name": "Abionyx Pharma",        "isin": "FR0012616852",
     "ticker_fh": "ABNX.PA", "ticker_eod": "ABNX.PA",  "qty": 10, "cost_eur": 3.84,   "marche": "euronext"},
]

# ─── INDICES MACRO ─────────────────────────────────────────────────────────────
INDICES = {
    "S&P 500":    {"eod": "GSPC.INDX", "fh": "^GSPC"},
    "CAC 40":     {"eod": "FCHI.INDX", "fh": "^FCHI"},
    "Nikkei 225": {"eod": "N225.INDX", "fh": "^N225"},
}

# ─── WATCHLIST HORS PORTEFEUILLE ───────────────────────────────────────────────
WATCHLIST = [
    {"name": "NVIDIA",        "ticker_fh": "NVDA",   "ticker_eod": "NVDA.US", "marche": "us",       "sector": "IA / Semi-conducteurs"},
    {"name": "Microsoft",     "ticker_fh": "MSFT",   "ticker_eod": "MSFT.US", "marche": "us",       "sector": "IA / Cloud"},
    {"name": "Coinbase",      "ticker_fh": "COIN",   "ticker_eod": "COIN.US", "marche": "us",       "sector": "Crypto / Fintech"},
    {"name": "LVMH",          "ticker_fh": "MC.PA",  "ticker_eod": "MC.PA",   "marche": "euronext", "sector": "Luxe / Consommation"},
    {"name": "TotalEnergies", "ticker_fh": "TTE.PA", "ticker_eod": "TTE.PA",  "marche": "euronext", "sector": "Énergie"},
    {"name": "Airbus",        "ticker_fh": "AIR.PA", "ticker_eod": "AIR.PA",  "marche": "euronext", "sector": "Aéronautique / Défense"},
]

# ─── FRAIS COURTAGE BOURSOBANK (Découverte — brochure 13/11/2025) ─────────────
BROKERAGE = {
    "euronext":             {"threshold": 500,  "flat": 1.99,  "rate": 0.006,  "min": 1.99},
    "us":                   {"threshold": 6000, "flat": 6.95,  "rate": 0.0012, "min": 6.95},
    "europe_hors_euronext": {"threshold": 4000, "flat": 11.95, "rate": 0.003,  "min": 11.95},
}

def calc_fee(amount: float, marche: str) -> float:
    t = BROKERAGE.get(marche, BROKERAGE["euronext"])
    fee = t["flat"] if amount <= t["threshold"] else t["rate"] * amount
    return round(max(fee, t["min"]), 2)

# ══════════════════════════════════════════════════════════════════════════════
# COUCHE D'ABSTRACTION API
# Chaque fonction essaie la source principale puis le fallback.
# Retourne toujours un résultat typé — jamais d'exception fatale.
# ══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict, timeout: int = 10):
    """HTTP GET sécurisé, retourne None en cas d'erreur."""
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── 1. TAUX EUR/USD ────────────────────────────────────────────────────────────
def get_eur_usd() -> tuple:
    """Retourne (taux: float, source: str). 1 USD = taux EUR."""
    # Source 1 — Finnhub forex/rates
    data = _get(f"{FH_BASE}/forex/rates", {"base": "USD", "token": FINNHUB_KEY})
    if data and data.get("quote", {}).get("EUR"):
        return float(data["quote"]["EUR"]), "Finnhub forex/rates"

    # Fallback — EODHD EURUSD.FOREX
    data = _get(f"{EOD_BASE}/real-time/EURUSD.FOREX",
                {"api_token": EODHD_KEY, "fmt": "json"})
    if data and data.get("close"):
        eurusd = float(data["close"])  # combien de USD pour 1 EUR
        return round(1 / eurusd, 6), "EODHD EURUSD.FOREX"

    return 0.92, "⚠️ Valeur par défaut (APIs indisponibles)"


# ── 2. COURS EN TEMPS RÉEL ────────────────────────────────────────────────────
def get_price_eur(asset: dict, eur_usd: float) -> tuple:
    """Retourne (prix_eur, variation_jour_pct, source).
    Priorité : EODHD → Finnhub → None."""
    # Source 1 — EODHD real-time
    data = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                {"api_token": EODHD_KEY, "fmt": "json"})
    if data:
        price_raw = data.get("close") or data.get("previousClose")
        if price_raw and float(price_raw) > 0:
            chg = float(data.get("change_p", 0.0))
            raw = float(price_raw)
            eur = raw * eur_usd if asset["marche"] == "us" else raw
            return round(eur, 4), round(chg, 4), "EODHD"

    # Fallback — Finnhub quote
    data = _get(f"{FH_BASE}/quote",
                {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
    if data and data.get("c") and float(data["c"]) > 0:
        raw = float(data["c"])
        chg = float(data.get("dp", 0.0))
        eur = raw * eur_usd if asset["marche"] == "us" else raw
        return round(eur, 4), round(chg, 4), "Finnhub"

    return None, 0.0, "N/D"


# ── 3. INDICES MACRO ──────────────────────────────────────────────────────────
def get_index(name: str, symbols: dict) -> dict:
    """Retourne {price, change_pct, source}.
    Priorité : EODHD → Finnhub."""
    # Source 1 — EODHD
    data = _get(f"{EOD_BASE}/real-time/{symbols['eod']}",
                {"api_token": EODHD_KEY, "fmt": "json"})
    if data and (data.get("close") or data.get("previousClose")):
        return {
            "price":      float(data.get("close") or data.get("previousClose", 0)),
            "change_pct": float(data.get("change_p", 0.0)),
            "source":     "EODHD",
        }

    # Fallback — Finnhub
    data = _get(f"{FH_BASE}/quote",
                {"symbol": symbols["fh"], "token": FINNHUB_KEY})
    if data and data.get("c"):
        return {
            "price":      float(data["c"]),
            "change_pct": float(data.get("dp", 0.0)),
            "source":     "Finnhub",
        }

    return {"price": 0.0, "change_pct": 0.0, "source": "N/D"}


# ── 4. ACTUALITÉS ENTREPRISE ──────────────────────────────────────────────────
def get_company_news(asset: dict, n: int = 2) -> list:
    """Retourne liste de titres. Priorité : EODHD → Finnhub."""
    from_d = str(date.today() - timedelta(days=7))
    to_d   = str(date.today())

    # Source 1 — EODHD news
    data = _get(f"{EOD_BASE}/news",
                {"s": asset["ticker_eod"], "limit": n, "from": from_d,
                 "api_token": EODHD_KEY, "fmt": "json"})
    if isinstance(data, list) and data:
        return [item.get("title", "") for item in data if item.get("title")]

    # Fallback — Finnhub company-news
    data = _get(f"{FH_BASE}/company-news",
                {"symbol": asset["ticker_fh"], "from": from_d,
                 "to": to_d, "token": FINNHUB_KEY})
    if isinstance(data, list) and data:
        return [item.get("headline", "") for item in data[:n] if item.get("headline")]

    return []


# ── 5. SENTIMENT PRESSE ────────────────────────────────────────────────────────
def get_sentiment(asset: dict) -> tuple:
    """Retourne (bull_pct, bear_pct, source).
    Priorité : Finnhub news-sentiment → analyse lexicale EODHD news."""
    # Source 1 — Finnhub news-sentiment
    data = _get(f"{FH_BASE}/news-sentiment",
                {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
    if data and data.get("sentiment"):
        bull = float(data["sentiment"].get("bullishPercent", 0.5)) * 100
        bear = float(data["sentiment"].get("bearishPercent", 0.5)) * 100
        return round(bull, 1), round(bear, 1), "Finnhub"

    # Fallback — analyse lexicale sur titres EODHD
    news = get_company_news(asset, n=10)
    if news:
        bull_words = {"growth", "buy", "bullish", "surge", "record", "beat", "strong",
                      "gain", "up", "rise", "soar", "profit", "positive", "upgrade"}
        bear_words = {"loss", "sell", "bearish", "drop", "miss", "weak", "cut", "down",
                      "fall", "decline", "risk", "negative", "downgrade", "warn"}
        all_words  = " ".join(news).lower().split()
        b_count    = sum(1 for w in all_words if w in bull_words)
        s_count    = sum(1 for w in all_words if w in bear_words)
        total      = b_count + s_count or 1
        bull = round(b_count / total * 100, 1)
        bear = round(s_count / total * 100, 1)
        return bull, bear, "EODHD (analyse lexicale)"

    return 50.0, 50.0, "⚠️ Indisponible"


# ── 6. CONSENSUS ANALYSTES ────────────────────────────────────────────────────
def get_consensus(asset: dict) -> tuple:
    """Retourne (score 0-10, consensus_str, source).
    Priorité : Finnhub recommendation-trends → EODHD fundamentals."""
    # Source 1 — Finnhub
    data = _get(f"{FH_BASE}/stock/recommendation",
                {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
    if isinstance(data, list) and data:
        r = data[0]
        sb = r.get("strongBuy", 0); b = r.get("buy", 0)
        h  = r.get("hold", 0);      s = r.get("sell", 0)
        ss = r.get("strongSell", 0)
        total = sb + b + h + s + ss
        if total > 0:
            score = (sb * 10 + b * 7.5 + h * 5 + s * 2.5 + ss * 0) / total
            cstr  = f"StrongBuy:{sb} Buy:{b} Hold:{h} Sell:{s} StrongSell:{ss}"
            return round(score, 2), cstr, "Finnhub"

    # Fallback — EODHD fundamentals AnalystRatings
    data = _get(f"{EOD_BASE}/fundamentals/{asset['ticker_eod']}",
                {"api_token": EODHD_KEY, "fmt": "json", "filter": "AnalystRatings"})
    if isinstance(data, dict) and data.get("Rating"):
        rat   = data["Rating"]
        label = str(rat.get("Rating", "")).lower()
        tp    = rat.get("TargetPrice", "N/D")
        score_map = {"strong buy": 9.0, "buy": 7.5, "hold": 5.0,
                     "sell": 2.5, "strong sell": 0.5}
        score = score_map.get(label, 5.0)
        cstr  = f"Rating: {rat.get('Rating', '?')} | TargetPrice: {tp} $"
        return score, cstr, "EODHD"

    return 5.0, "N/D", "⚠️ Indisponible"


# ── 7. ACTUALITÉS MACRO ────────────────────────────────────────────────────────
def get_macro_news(n: int = 5) -> list:
    """Priorité : EODHD general news → Finnhub market news."""
    data = _get(f"{EOD_BASE}/news",
                {"t": "general", "limit": n, "api_token": EODHD_KEY, "fmt": "json"})
    if isinstance(data, list) and data:
        return [i.get("title", "") for i in data if i.get("title")]

    # Fallback — Finnhub market news
    data = _get(f"{FH_BASE}/news",
                {"category": "general", "token": FINNHUB_KEY})
    if isinstance(data, list) and data:
        return [i.get("headline", "") for i in data[:n] if i.get("headline")]

    return []


# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_price(current: float, cost: float) -> float:
    pnl = (current - cost) / cost * 100
    return round(max(0.0, min(10.0, 5.0 + pnl / 10.0)), 2)

def score_macro(indices_data: dict) -> float:
    changes = [v["change_pct"] for v in indices_data.values() if v["change_pct"] != 0]
    if not changes:
        return 5.0
    avg = sum(changes) / len(changes)
    return round(max(0.0, min(10.0, 5.0 + avg)), 2)

def recommend(score: float) -> str:
    if score >= 7.5: return "🟢 ACHAT FORT"
    if score >= 6.0: return "🔵 ACHAT MODÉRÉ"
    if score >= 4.5: return "🟡 GARDER"
    if score >= 3.0: return "🟠 À ÉVITER"
    return "🔴 VENDRE"

def build_justification(name, net_pnl_eur, net_pnl_pct,
                        sc, bull, bear, consensus,
                        macro_score, total_score) -> str:
    if net_pnl_eur >= 0:
        p1 = (f"La position affiche un **gain net de {net_pnl_eur:+.2f} € "
              f"({net_pnl_pct:+.1f}%)** après frais, confirmant une plus-value réelle.")
    else:
        p1 = (f"La position est en **perte nette de {net_pnl_eur:+.2f} € "
              f"({net_pnl_pct:+.1f}%)** après frais d'achat et vente estimés.")

    if sc >= 7:
        p2 = (f"Le consensus analystes est **fortement haussier** (score {sc:.1f}/10), "
              f"avec {bull:.0f}% de sentiment positif — {consensus}.")
    elif sc >= 5:
        p2 = (f"Le consensus est **neutre** (score {sc:.1f}/10) : "
              f"{bull:.0f}% bull / {bear:.0f}% bear — {consensus}.")
    else:
        p2 = (f"Le consensus est **défavorable** (score {sc:.1f}/10) : "
              f"{bear:.0f}% de couverture négative — {consensus}.")

    if macro_score >= 6:
        p3 = "Le contexte macro est **favorable** ce jour, soutenant les positions risquées."
    elif macro_score <= 4:
        p3 = "Le contexte macro est **défavorable**, ce qui pèse sur l'ensemble des actifs."
    else:
        p3 = "Le contexte macro est **neutre**, sans catalyseur directionnel fort."

    return f"{p1} {p2} {p3}"


# ══════════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU RAPPORT
# ══════════════════════════════════════════════════════════════════════════════

def build_report() -> str:
    now = datetime.now(PARIS_TZ)

    # Taux de change
    eur_usd, eurusd_src = get_eur_usd()

    # Indices macro
    indices_data = {name: get_index(name, syms) for name, syms in INDICES.items()}
    macro_score  = score_macro(indices_data)
    macro_label  = ("📈 Haussière" if macro_score >= 6
                    else "📉 Baissière" if macro_score <= 4 else "➡️ Neutre")

    # Actualités macro
    macro_news = get_macro_news(5)

    # En-tête rapport
    lines = [
        f"# 📊 Rapport de Portefeuille — {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        "",
        "---",
        "",
        "## 🌍 Contexte Économique",
        "",
        f"**Tendance générale : {macro_label}** (score macro : {macro_score:.1f}/10)",
        f"**Taux EUR/USD :** 1 EUR = {1/eur_usd:.4f} USD _(source : {eurusd_src})_",
        "",
        "| Indice | Variation | Dernier cours | Source |",
        "|--------|-----------|--------------|--------|",
    ]
    for name, d in indices_data.items():
        arrow = "▲" if d["change_pct"] > 0 else "▼" if d["change_pct"] < 0 else "—"
        lines.append(
            f"| {name} | {arrow} {d['change_pct']:+.2f}% "
            f"| {d['price']:,.2f} | {d['source']} |"
        )

    if macro_news:
        lines += ["", "**📰 Manchettes macro du jour :**", ""]
        for title in macro_news:
            if title:
                lines.append(f"- {title}")

    lines += ["", "---", "", "## 📈 Analyse par Valeur", ""]

    # Variables d'accumulation
    total_cout_investi  = 0.0
    total_valeur_marche = 0.0
    total_pnl_brut      = 0.0
    total_pnl_net       = 0.0
    summaries           = []

    for asset in PORTFOLIO:
        name     = asset["name"]
        qty      = asset["qty"]
        cost_eur = asset["cost_eur"]
        marche   = asset["marche"]

        # Cours
        price_eur, chg_today, price_src = get_price_eur(asset, eur_usd)

        if price_eur is None:
            lines += [
                f"### ⚠️ {name} `{asset['ticker_eod']}` ({asset['isin']})",
                "",
                "> **Cours indisponible sur les deux APIs (EODHD + Finnhub).**",
                "> Vérifiez le ticker sur [eodhd.com](https://eodhd.com) "
                "ou [finnhub.io](https://finnhub.io).",
                "",
                "---", "",
            ]
            continue

        # PnL
        valeur_marche = round(price_eur * qty, 2)
        cout_total    = round(cost_eur * qty, 2)
        fee_achat     = calc_fee(cout_total, marche)
        fee_vente_sim = calc_fee(valeur_marche, marche)
        cout_reel     = round(cout_total + fee_achat, 2)

        pnl_brut_eur  = round(valeur_marche - cout_total, 2)
        pnl_brut_pct  = round(pnl_brut_eur / cout_total * 100, 2)
        net_pnl_eur   = round(valeur_marche - cout_reel - fee_vente_sim, 2)
        net_pnl_pct   = round(net_pnl_eur / cout_reel * 100, 2)

        pnl_icon = "📗" if pnl_brut_eur >= 0 else "📕"

        # Données analytiques
        bull, bear, sent_src         = get_sentiment(asset)
        cons_score, cons_str, cons_src = get_consensus(asset)
        news_titles                  = get_company_news(asset, 2)
        news_str = news_titles[0] if news_titles else "Aucune actualité récente."

        # Score global
        ps          = score_price(price_eur, cost_eur)
        sc          = round((bull / 10 + cons_score) / 2, 2)
        total_score = round(ps * 0.40 + sc * 0.35 + macro_score * 0.25, 2)
        rec         = recommend(total_score)

        justif = build_justification(
            name, net_pnl_eur, net_pnl_pct,
            sc, bull, bear, cons_str, macro_score, total_score
        )

        # Accumulation totaux
        total_cout_investi  += cout_total
        total_valeur_marche += valeur_marche
        total_pnl_brut      += pnl_brut_eur
        total_pnl_net       += net_pnl_eur
        summaries.append({
            "name": name, "rec": rec, "score": total_score,
            "pnl_brut_pct": pnl_brut_pct, "net_pnl_eur": net_pnl_eur,
        })

        lines += [
            f"### {pnl_icon} {name} `{asset['ticker_eod']}` ({asset['isin']})",
            "",
            "| Champ | Valeur |",
            "|-------|--------|",
            f"| **Cours actuel** | {price_eur:.2f} € ({chg_today:+.2f}% aujourd'hui) · _source : {price_src}_ |",
            f"| **Prix de revient unitaire** | {cost_eur:.2f} € |",
            f"| **Coût total investi** | {cout_total:.2f} € |",
            f"| **Frais d'achat payés** | {fee_achat:.2f} € |",
            f"| **Coût réel total** _(base rentabilité)_ | {cout_reel:.2f} € |",
            f"| **Valeur de marché actuelle** | {valeur_marche:.2f} € |",
            f"| **PnL brut latent** | {pnl_brut_eur:+.2f} € ({pnl_brut_pct:+.2f}%) |",
            f"| **Frais de vente estimés** | {fee_vente_sim:.2f} € |",
            f"| **PnL net si vente aujourd'hui** | {net_pnl_eur:+.2f} € ({net_pnl_pct:+.2f}%) |",
            f"| **Sentiment presse** | Bull {bull:.0f}% / Bear {bear:.0f}% · _source : {sent_src}_ |",
            f"| **Consensus analystes** | {cons_str} · _source : {cons_src}_ |",
            f"| **Score total** | {total_score:.1f}/10 "
            f"(Prix {ps:.1f} · Sentiment {sc:.1f} · Macro {macro_score:.1f}) |",
            "",
            f"**📰 Dernière actualité :** {news_str}",
            "",
            f"**⚡ Recommandation : {rec}**",
            "",
            f"**💬 Justification :** {justif}",
            "",
            "---",
            "",
        ]

    # Résumé portefeuille
    tot_pnl_brut_pct = round(total_pnl_brut / total_cout_investi * 100, 2) if total_cout_investi else 0
    tot_pnl_net_pct  = round(total_pnl_net  / total_cout_investi * 100, 2) if total_cout_investi else 0

    lines += [
        "## 💼 Résumé Global du Portefeuille",
        "",
        "| | Montant |",
        "|--|--------|",
        f"| **Coût total investi** | {total_cout_investi:.2f} € |",
        f"| **Valeur de marché totale** | {total_valeur_marche:.2f} € |",
        f"| **PnL brut latent** | {total_pnl_brut:+.2f} € ({tot_pnl_brut_pct:+.2f}%) |",
        f"| **PnL net estimé** _(frais achat + vente)_ | {total_pnl_net:+.2f} € ({tot_pnl_net_pct:+.2f}%) |",
        "",
        "---",
        "",
    ]

    # Conclusion stratégique
    best  = max(summaries, key=lambda x: x["score"]) if summaries else None
    worst = min(summaries, key=lambda x: x["score"]) if summaries else None

    if macro_score >= 6:
        macro_ctx = ("Les marchés affichent une dynamique **positive** ce jour, "
                     "ce qui soutient l'ensemble des positions risquées du portefeuille.")
    elif macro_score <= 4:
        macro_ctx = ("Les marchés sont sous **pression baissière**, "
                     "ce qui appelle à la prudence sur les positions les plus spéculatives.")
    else:
        macro_ctx = ("Les marchés évoluent dans un registre **neutre**, "
                     "sans catalyseur fort dans un sens ou dans l'autre.")

    lines += [
        "## 🧭 Conclusion & Synthèse Stratégique",
        "",
        macro_ctx,
        "",
    ]

    if best and worst:
        lines += [
            f"Au sein du portefeuille, **{best['name']}** est la valeur la plus solide "
            f"(score {best['score']:.1f}/10, PnL brut {best['pnl_brut_pct']:+.1f}%) — "
            f"position à conserver et potentiellement à renforcer.",
            "",
            f"À l'inverse, **{worst['name']}** présente le profil le plus fragile "
            f"(score {worst['score']:.1f}/10, PnL net {worst['net_pnl_eur']:+.2f} €). "
            f"Une réévaluation est recommandée avant toute décision.",
            "",
        ]

    # Watchlist hors portefeuille
    lines += [
        "### 🔭 3 Valeurs à Fort Potentiel Hors Portefeuille",
        "",
        "_(Sélectionnées sur score de sentiment + consensus analystes du jour)_",
        "",
        "| Valeur | Secteur | Cours | Variation | Score | Sentiment | Consensus |",
        "|--------|---------|-------|-----------|-------|-----------|----------|",
    ]

    watch_results = []
    for w in WATCHLIST:
        price_eur, chg, src = get_price_eur(w, eur_usd)
        if not price_eur:
            continue
        bull, bear, _ = get_sentiment(w)
        cons_score, cons_str, _ = get_consensus(w)
        sc = round((bull / 10 + cons_score) / 2, 2)
        watch_results.append({
            "name": w["name"], "sector": w["sector"],
            "price": price_eur, "chg": chg, "sc": sc,
            "bull": bull, "cons": cons_str,
        })
    watch_results.sort(key=lambda x: x["sc"], reverse=True)

    for w in watch_results[:3]:
        arrow = "▲" if w["chg"] > 0 else "▼"
        lines.append(
            f"| **{w['name']}** | {w['sector']} | {w['price']:.2f} € "
            f"| {arrow} {w['chg']:+.2f}% | {w['sc']:.1f}/10 "
            f"| Bull {w['bull']:.0f}% | {w['cons']} |"
        )

    lines += [
        "",
        "> Ces valeurs présentent un **fort consensus haussier** ce jour et une cohérence "
        "sectorielle avec les positions actuelles (IA, crypto, Europe).",
        "",
        "---",
        "",
        f"_Rapport généré le {now.strftime('%d/%m/%Y à %H:%M')} heure de Paris._",
        f"_Sources données : EODHD (principal) + Finnhub (fallback). "
        f"Taux EUR/USD : {1/eur_usd:.4f} — source : {eurusd_src}._",
        "_Frais de courtage : BoursoBank offre Découverte (brochure 13/11/2025)._",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    os.makedirs("reports", exist_ok=True)
    out = "reports/daily_report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ Rapport généré : {out}")
