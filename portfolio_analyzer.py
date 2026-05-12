#!/usr/bin/env python3
"""
Portfolio Analyzer v3.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Protocole 3 sources avec validation croisée :

  COURS US      : TwelveData (batch) → EODHD → Finnhub
  EUR/USD       : TwelveData → Finnhub → EODHD → valeur par défaut
  COURS EU (.PA): EODHD → Finnhub
  INDICES MACRO : EODHD → Finnhub
  SENTIMENT     : Finnhub → EODHD (analyse lexicale)
  CONSENSUS     : Finnhub → EODHD fundamentals
  NEWS          : EODHD → Finnhub

Validation croisée : si écart > 2% entre deux sources sur
un même cours → ⚠️ Divergence signalée dans le rapport.

Plan TwelveData gratuit : 8 crédits/minute, US uniquement.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import time
import requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# ─── CLÉS API ────────────────────────────────────────────────────────────────
FINNHUB_KEY    = os.environ.get("FINNHUB_API_KEY", "")
EODHD_KEY      = os.environ.get("EODHD_API_KEY", "")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_API_KEY", "")

if not FINNHUB_KEY:
    raise EnvironmentError("Secret GitHub manquant : FINNHUB_API_KEY")
if not EODHD_KEY:
    raise EnvironmentError("Secret GitHub manquant : EODHD_API_KEY")
if not TWELVEDATA_KEY:
    raise EnvironmentError("Secret GitHub manquant : TWELVEDATA_API_KEY")

FH_BASE  = "https://finnhub.io/api/v1"
EOD_BASE = "https://eodhd.com/api"
TD_BASE  = "https://api.twelvedata.com"
PARIS_TZ = ZoneInfo("Europe/Paris")

DIVERGENCE_THRESHOLD_PCT = 2.0

# ─── PORTEFEUILLE ─────────────────────────────────────────────────────────────
PORTFOLIO = [
    {"name": "Palantir Technologies", "isin": "US69608A1088",
     "ticker_fh": "PLTR",    "ticker_eod": "PLTR.US",  "ticker_td": "PLTR",
     "qty": 2,  "cost_eur": 119.06, "marche": "us"},
    {"name": "CoreWeave",             "isin": "US21873S1087",
     "ticker_fh": "CRWV",    "ticker_eod": "CRWV.US",  "ticker_td": "CRWV",
     "qty": 2,  "cost_eur": 93.91,  "marche": "us"},
    {"name": "Riot Platforms",        "isin": "US7672921050",
     "ticker_fh": "RIOT",    "ticker_eod": "RIOT.US",  "ticker_td": "RIOT",
     "qty": 6,  "cost_eur": 15.84,  "marche": "us"},
    {"name": "JCDecaux",              "isin": "FR0000077919",
     "ticker_fh": "DEC.PA",  "ticker_eod": "DEC.PA",   "ticker_td": None,
     "qty": 2,  "cost_eur": 17.77,  "marche": "euronext"},
    {"name": "Crédit Agricole SA",    "isin": "FR0000045072",
     "ticker_fh": "ACA.PA",  "ticker_eod": "ACA.PA",   "ticker_td": None,
     "qty": 10, "cost_eur": 16.90,  "marche": "euronext"},
    {"name": "Abionyx Pharma",        "isin": "FR0012616852",
     "ticker_fh": "ABNX.PA", "ticker_eod": "ABNX.PA",  "ticker_td": None,
     "qty": 10, "cost_eur": 3.84,   "marche": "euronext"},
]

INDICES = {
    "S&P 500":    {"eod": "GSPC.INDX", "fh": "^GSPC"},
    "CAC 40":     {"eod": "FCHI.INDX", "fh": "^FCHI"},
    "Nikkei 225": {"eod": "N225.INDX", "fh": "^N225"},
}

WATCHLIST = [
    {"name": "NVIDIA",        "ticker_fh": "NVDA",   "ticker_eod": "NVDA.US", "ticker_td": "NVDA",  "marche": "us",       "sector": "IA / Semi-conducteurs"},
    {"name": "Microsoft",     "ticker_fh": "MSFT",   "ticker_eod": "MSFT.US", "ticker_td": "MSFT",  "marche": "us",       "sector": "IA / Cloud"},
    {"name": "Coinbase",      "ticker_fh": "COIN",   "ticker_eod": "COIN.US", "ticker_td": "COIN",  "marche": "us",       "sector": "Crypto / Fintech"},
    {"name": "LVMH",          "ticker_fh": "MC.PA",  "ticker_eod": "MC.PA",   "ticker_td": None,    "marche": "euronext", "sector": "Luxe / Consommation"},
    {"name": "TotalEnergies", "ticker_fh": "TTE.PA", "ticker_eod": "TTE.PA",  "ticker_td": None,    "marche": "euronext", "sector": "Énergie"},
    {"name": "Airbus",        "ticker_fh": "AIR.PA", "ticker_eod": "AIR.PA",  "ticker_td": None,    "marche": "euronext", "sector": "Aéronautique / Défense"},
]

BROKERAGE = {
    "euronext": {"threshold": 500,  "flat": 1.99,  "rate": 0.006,  "min": 1.99},
    "us":       {"threshold": 6000, "flat": 6.95,  "rate": 0.0012, "min": 6.95},
}

def calc_fee(amount: float, marche: str) -> float:
    t = BROKERAGE.get(marche, BROKERAGE["euronext"])
    return round(max(t["flat"] if amount <= t["threshold"] else t["rate"] * amount, t["min"]), 2)

# ══════════════════════════════════════════════════════════════════════════════
# COUCHE HTTP
# ══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict, timeout: int = 10):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLE DE VALIDATION CROISÉE
# ══════════════════════════════════════════════════════════════════════════════

def cross_validate(val1: float, src1: str, val2: float, src2: str) -> tuple:
    """Compare deux prix. Si écart > seuil → signale divergence et retourne médiane."""
    if val1 and val2 and val1 > 0 and val2 > 0:
        ecart_pct = abs(val1 - val2) / val1 * 100
        if ecart_pct > DIVERGENCE_THRESHOLD_PCT:
            mediane = round((val1 + val2) / 2, 4)
            note = (f"⚠️ Divergence {ecart_pct:.1f}% entre {src1} ({val1:.4f}) "
                    f"et {src2} ({val2:.4f}) → médiane utilisée : {mediane:.4f}")
            return mediane, note
    return val1 if val1 and val1 > 0 else val2, None

# ══════════════════════════════════════════════════════════════════════════════
# BATCH TWELVEDATA — 1 requête pour tous les tickers US
# ══════════════════════════════════════════════════════════════════════════════

_td_cache = {}
_td_last_call = 0.0

def td_fetch_batch(tickers: list) -> dict:
    """Récupère les prix de tous les tickers US en une seule requête TwelveData.
    Respecte la limite de 8 crédits/minute avec pause automatique.
    Retourne dict {ticker: price_float ou None}."""
    global _td_last_call

    to_fetch = [t for t in tickers if t not in _td_cache]
    if not to_fetch:
        return {t: _td_cache.get(t) for t in tickers}

    elapsed = time.time() - _td_last_call
    if elapsed < 10 and _td_last_call > 0:
        time.sleep(10 - elapsed)

    results = {}
    for i in range(0, len(to_fetch), 6):
        batch = to_fetch[i:i+6]
        symbol_str = ",".join(batch)
        data = _get(f"{TD_BASE}/price",
                    {"symbol": symbol_str, "apikey": TWELVEDATA_KEY})
        _td_last_call = time.time()

        if isinstance(data, dict):
            for ticker in batch:
                item = data.get(ticker, {})
                if isinstance(item, dict) and item.get("price") and item.get("status") != "error":
                    try:
                        results[ticker] = float(item["price"])
                        _td_cache[ticker] = results[ticker]
                    except Exception:
                        results[ticker] = None
                else:
                    results[ticker] = None
        else:
            for ticker in batch:
                results[ticker] = None

        if i + 6 < len(to_fetch):
            time.sleep(12)

    for t in tickers:
        if t not in results:
            results[t] = _td_cache.get(t)
    return results

# ══════════════════════════════════════════════════════════════════════════════
# SOURCES DE DONNÉES
# ══════════════════════════════════════════════════════════════════════════════

def get_eur_usd() -> tuple:
    """Retourne (1_USD_en_EUR, source, note_divergence_ou_None).
    Priorité : TwelveData → Finnhub → EODHD."""
    td_val, fh_val = None, None

    data = _get(f"{TD_BASE}/price", {"symbol": "EUR/USD", "apikey": TWELVEDATA_KEY})
    if data and data.get("price"):
        eurusd = float(data["price"])
        td_val = round(1 / eurusd, 6)

    data = _get(f"{FH_BASE}/forex/rates", {"base": "USD", "token": FINNHUB_KEY})
    if data and data.get("quote", {}).get("EUR"):
        fh_val = float(data["quote"]["EUR"])

    if td_val and fh_val:
        final, note = cross_validate(td_val, "TwelveData", fh_val, "Finnhub")
        src = "TwelveData ✓ Finnhub" if not note else "Médiane TwelveData/Finnhub"
        return final, src, note

    if td_val: return td_val, "TwelveData", None
    if fh_val: return fh_val, "Finnhub", None

    data = _get(f"{EOD_BASE}/real-time/EURUSD.FOREX",
                {"api_token": EODHD_KEY, "fmt": "json"})
    if data and data.get("close"):
        return round(1 / float(data["close"]), 6), "EODHD", None

    return 0.92, "⚠️ Valeur par défaut", None


def get_price_eur(asset: dict, eur_usd: float, td_prices: dict) -> tuple:
    """Retourne (prix_eur, chg_pct, source, note_divergence).
    US  : TwelveData (batch) → EODHD → Finnhub
    EUR : EODHD → Finnhub"""
    td_val, eod_val = None, None
    note = None
    chg  = 0.0

    if asset["marche"] == "us":
        td_raw = td_prices.get(asset.get("ticker_td"))
        if td_raw and td_raw > 0:
            td_val = round(td_raw * eur_usd, 4)

        data = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                    {"api_token": EODHD_KEY, "fmt": "json"})
        if data:
            raw = data.get("close") or data.get("previousClose")
            if raw and float(raw) > 0:
                chg = float(data.get("change_p", 0.0))
                eod_val = round(float(raw) * eur_usd, 4)

        if td_val and eod_val:
            final, note = cross_validate(td_val, "TwelveData", eod_val, "EODHD")
            src = "TwelveData ✓ EODHD" if not note else "Médiane TwelveData/EODHD"
            return final, chg, src, note
        if td_val:  return td_val, 0.0, "TwelveData", None
        if eod_val: return eod_val, chg, "EODHD", None

        data = _get(f"{FH_BASE}/quote",
                    {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
        if data and data.get("c") and float(data["c"]) > 0:
            raw = float(data["c"])
            return round(raw * eur_usd, 4), float(data.get("dp", 0.0)), "Finnhub", None

    else:
        data = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                    {"api_token": EODHD_KEY, "fmt": "json"})
        if data:
            raw = data.get("close") or data.get("previousClose")
            if raw and float(raw) > 0:
                chg = float(data.get("change_p", 0.0))
                eod_val = round(float(raw), 4)

        data_fh = _get(f"{FH_BASE}/quote",
                       {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
        if data_fh and data_fh.get("c") and float(data_fh["c"]) > 0:
            fh_val = round(float(data_fh["c"]), 4)
            if eod_val:
                final, note = cross_validate(eod_val, "EODHD", fh_val, "Finnhub")
                src = "EODHD ✓ Finnhub" if not note else "Médiane EODHD/Finnhub"
                return final, chg, src, note
            return fh_val, float(data_fh.get("dp", 0.0)), "Finnhub", None

        if eod_val: return eod_val, chg, "EODHD", None

    return None, 0.0, "N/D", None


def get_index(symbols: dict) -> dict:
    """EODHD → Finnhub. TwelveData non disponible plan gratuit pour indices."""
    data = _get(f"{EOD_BASE}/real-time/{symbols['eod']}",
                {"api_token": EODHD_KEY, "fmt": "json"})
    if data and (data.get("close") or data.get("previousClose")):
        return {
            "price":      float(data.get("close") or data.get("previousClose", 0)),
            "change_pct": float(data.get("change_p", 0.0)),
            "source":     "EODHD",
        }
    data = _get(f"{FH_BASE}/quote",
                {"symbol": symbols["fh"], "token": FINNHUB_KEY})
    if data and data.get("c"):
        return {"price": float(data["c"]),
                "change_pct": float(data.get("dp", 0.0)), "source": "Finnhub"}
    return {"price": 0.0, "change_pct": 0.0, "source": "N/D"}


def get_sentiment(asset: dict) -> tuple:
    data = _get(f"{FH_BASE}/news-sentiment",
                {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
    if data and data.get("sentiment"):
        bull = float(data["sentiment"].get("bullishPercent", 0.5)) * 100
        bear = float(data["sentiment"].get("bearishPercent", 0.5)) * 100
        return round(bull, 1), round(bear, 1), "Finnhub"

    news = get_company_news(asset, n=10)
    if news:
        bull_w = {"growth", "buy", "bullish", "surge", "record", "beat", "strong",
                  "gain", "up", "rise", "soar", "profit", "positive", "upgrade"}
        bear_w = {"loss", "sell", "bearish", "drop", "miss", "weak", "cut", "down",
                  "fall", "decline", "risk", "negative", "downgrade", "warn"}
        words  = " ".join(news).lower().split()
        b = sum(1 for w in words if w in bull_w)
        s = sum(1 for w in words if w in bear_w)
        t = b + s or 1
        return round(b/t*100, 1), round(s/t*100, 1), "EODHD (lexical)"
    return 50.0, 50.0, "⚠️ Indisponible"


def get_consensus(asset: dict) -> tuple:
    data = _get(f"{FH_BASE}/stock/recommendation",
                {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
    if isinstance(data, list) and data:
        r = data[0]
        sb = r.get("strongBuy", 0); b = r.get("buy", 0)
        h  = r.get("hold", 0);      s = r.get("sell", 0); ss = r.get("strongSell", 0)
        total = sb + b + h + s + ss
        if total > 0:
            score = (sb*10 + b*7.5 + h*5 + s*2.5) / total
            return round(score, 2), f"SB:{sb} B:{b} H:{h} S:{s} SS:{ss}", "Finnhub"

    data = _get(f"{EOD_BASE}/fundamentals/{asset['ticker_eod']}",
                {"api_token": EODHD_KEY, "fmt": "json", "filter": "AnalystRatings"})
    if isinstance(data, dict) and data.get("Rating"):
        rat   = data["Rating"]
        label = str(rat.get("Rating", "")).lower()
        tp    = rat.get("TargetPrice", "N/D")
        m     = {"strong buy": 9.0, "buy": 7.5, "hold": 5.0, "sell": 2.5, "strong sell": 0.5}
        score = m.get(label, 5.0)
        return score, f"Rating:{rat.get('Rating','?')} TP:{tp}$", "EODHD"

    return 5.0, "N/D", "⚠️ Indisponible"


def get_company_news(asset: dict, n: int = 2) -> list:
    from_d = str(date.today() - timedelta(days=7))
    to_d   = str(date.today())

    data = _get(f"{EOD_BASE}/news",
                {"s": asset["ticker_eod"], "limit": n, "from": from_d,
                 "api_token": EODHD_KEY, "fmt": "json"})
    if isinstance(data, list) and data:
        return [i.get("title", "") for i in data if i.get("title")]

    data = _get(f"{FH_BASE}/company-news",
                {"symbol": asset["ticker_fh"], "from": from_d,
                 "to": to_d, "token": FINNHUB_KEY})
    if isinstance(data, list) and data:
        return [i.get("headline", "") for i in data[:n] if i.get("headline")]
    return []


def get_macro_news(n: int = 5) -> list:
    data = _get(f"{EOD_BASE}/news",
                {"t": "general", "limit": n, "api_token": EODHD_KEY, "fmt": "json"})
    if isinstance(data, list) and data:
        return [i.get("title", "") for i in data if i.get("title")]
    data = _get(f"{FH_BASE}/news", {"category": "general", "token": FINNHUB_KEY})
    if isinstance(data, list) and data:
        return [i.get("headline", "") for i in data[:n] if i.get("headline")]
    return []


# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_price(current, cost):
    pnl = (current - cost) / cost * 100
    return round(max(0.0, min(10.0, 5.0 + pnl / 10.0)), 2)

def score_macro(indices_data):
    chgs = [v["change_pct"] for v in indices_data.values() if v["change_pct"] != 0]
    return round(max(0.0, min(10.0, 5.0 + sum(chgs)/len(chgs))), 2) if chgs else 5.0

def recommend(score):
    if score >= 7.5: return "🟢 ACHAT FORT"
    if score >= 6.0: return "🔵 ACHAT MODÉRÉ"
    if score >= 4.5: return "🟡 GARDER"
    if score >= 3.0: return "🟠 À ÉVITER"
    return "🔴 VENDRE"

def justification(name, net_pnl_eur, net_pnl_pct, sc, bull, bear,
                  consensus, macro_score, total_score):
    p1 = (f"Gain net **{net_pnl_eur:+.2f} € ({net_pnl_pct:+.1f}%)** après frais."
          if net_pnl_eur >= 0
          else f"Perte nette **{net_pnl_eur:+.2f} € ({net_pnl_pct:+.1f}%)** après frais.")
    p2 = (f"Consensus **haussier** (score {sc:.1f}/10, Bull {bull:.0f}%) — {consensus}."
          if sc >= 7 else
          f"Consensus **neutre** ({bull:.0f}% bull / {bear:.0f}% bear) — {consensus}."
          if sc >= 5 else
          f"Consensus **défavorable** (score {sc:.1f}/10, Bear {bear:.0f}%) — {consensus}.")
    p3 = ("Contexte macro **favorable**." if macro_score >= 6
          else "Contexte macro **défavorable**." if macro_score <= 4
          else "Contexte macro **neutre**.")
    return f"{p1} {p2} {p3}"


# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT
# ══════════════════════════════════════════════════════════════════════════════

def build_report() -> str:
    now = datetime.now(PARIS_TZ)
    lines = []
    divergence_log = []

    print("[INFO] Chargement batch TwelveData (cours US)...")
    us_tickers = [a["ticker_td"] for a in PORTFOLIO if a.get("ticker_td")]
    watch_td   = [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    all_td     = list(set(us_tickers + watch_td))
    td_prices  = td_fetch_batch(all_td)
    print(f"[INFO] TwelveData batch : {td_prices}")

    print("[INFO] EUR/USD...")
    eur_usd, eurusd_src, eurusd_note = get_eur_usd()
    if eurusd_note:
        divergence_log.append(f"EUR/USD : {eurusd_note}")

    print("[INFO] Indices macro...")
    indices_data = {n: get_index(s) for n, s in INDICES.items()}
    macro_score  = score_macro(indices_data)
    macro_label  = ("📈 Haussière" if macro_score >= 6
                    else "📉 Baissière" if macro_score <= 4 else "➡️ Neutre")

    macro_news = get_macro_news(5)

    lines += [
        f"# 📊 Rapport de Portefeuille — {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        "", "---", "",
        "## 🌍 Contexte Économique", "",
        f"**Tendance : {macro_label}** | Score macro : {macro_score:.1f}/10",
        f"**EUR/USD :** 1 EUR = {1/eur_usd:.4f} USD _(source : {eurusd_src})_",
        "",
        "| Indice | Variation | Cours | Source |",
        "|--------|-----------|-------|--------|",
    ]
    for name, d in indices_data.items():
        arr = "▲" if d["change_pct"] > 0 else "▼" if d["change_pct"] < 0 else "—"
        lines.append(f"| {name} | {arr} {d['change_pct']:+.2f}% | {d['price']:,.2f} | {d['source']} |")

    if macro_news:
        lines += ["", "**📰 Manchettes macro :**", ""]
        for t in macro_news:
            if t: lines.append(f"- {t}")

    lines += ["", "---", "", "## 📈 Analyse par Valeur", ""]

    total_cout = total_vm = total_pnl_brut = total_pnl_net = 0.0
    summaries  = []

    for asset in PORTFOLIO:
        print(f"[INFO] {asset['name']}...")
        price_eur, chg, price_src, div_note = get_price_eur(asset, eur_usd, td_prices)

        if div_note:
            divergence_log.append(f"{asset['name']} : {div_note}")

        if price_eur is None:
            lines += [
                f"### ⚠️ {asset['name']} `{asset['ticker_eod']}`",
                "> Cours indisponible sur TwelveData + EODHD + Finnhub.", "", "---", "",
            ]
            continue

        qty, cost, marche = asset["qty"], asset["cost_eur"], asset["marche"]
        vm         = round(price_eur * qty, 2)
        cout       = round(cost * qty, 2)
        fee_a      = calc_fee(cout, marche)
        fee_v      = calc_fee(vm, marche)
        cout_reel  = round(cout + fee_a, 2)
        pnl_brut   = round(vm - cout, 2)
        pnl_brut_p = round(pnl_brut / cout * 100, 2)
        pnl_net    = round(vm - cout_reel - fee_v, 2)
        pnl_net_p  = round(pnl_net / cout_reel * 100, 2)

        ps = score_price(price_eur, cost)
        bull, bear, sent_src = get_sentiment(asset)
        cs, cons_str, cons_src = get_consensus(asset)
        sc = round((bull / 10 + cs) / 2, 2)
        total_score = round(ps * 0.40 + sc * 0.35 + macro_score * 0.25, 2)
        rec = recommend(total_score)
        news = get_company_news(asset, 2)
        news_str = news[0] if news else "Aucune actualité récente."
        justif = justification(asset["name"], pnl_net, pnl_net_p,
                               sc, bull, bear, cons_str, macro_score, total_score)

        total_cout += cout
        total_vm   += vm
        total_pnl_brut += pnl_brut
        total_pnl_net  += pnl_net
        summaries.append({"name": asset["name"], "score": total_score,
                          "pnl_brut_pct": pnl_brut_p, "pnl_net": pnl_net})

        src_badge = f"_{price_src}_"
        div_flag  = f" `{div_note}`" if div_note else ""
        icon      = "📗" if pnl_brut >= 0 else "📕"

        lines += [
            f"### {icon} {asset['name']} `{asset['ticker_eod']}`",
            "",
            "| Champ | Valeur |",
            "|-------|--------|",
            f"| **Cours actuel** | {price_eur:.2f} € ({chg:+.2f}%) · {src_badge}{div_flag} |",
            f"| **Prix de revient** | {cost:.2f} € · Coût total {cout:.2f} € |",
            f"| **Frais achat payés** | {fee_a:.2f} € · Coût réel {cout_reel:.2f} € |",
            f"| **Valeur marché** | {vm:.2f} € |",
            f"| **PnL brut latent** | {pnl_brut:+.2f} € ({pnl_brut_p:+.2f}%) |",
            f"| **Frais vente estimés** | {fee_v:.2f} € |",
            f"| **PnL net si vente** | {pnl_net:+.2f} € ({pnl_net_p:+.2f}%) |",
            f"| **Sentiment presse** | Bull {bull:.0f}% / Bear {bear:.0f}% · _{sent_src}_ |",
            f"| **Consensus analystes** | {cons_str} · _{cons_src}_ |",
            f"| **Score** | {total_score:.1f}/10 (Prix {ps:.1f} · Sent {sc:.1f} · Macro {macro_score:.1f}) |",
            "",
            f"📰 **Actualité :** {news_str}",
            "",
            f"**⚡ {rec}**",
            "",
            f"💬 {justif}",
            "", "---", "",
        ]

    tot_p  = round(total_pnl_brut / total_cout * 100, 2) if total_cout else 0
    tot_np = round(total_pnl_net  / total_cout * 100, 2) if total_cout else 0
    lines += [
        "## 💼 Résumé Global",
        "",
        "| | Montant |",
        "|--|--------|",
        f"| Coût total investi | {total_cout:.2f} € |",
        f"| Valeur marché totale | {total_vm:.2f} € |",
        f"| PnL brut latent | {total_pnl_brut:+.2f} € ({tot_p:+.2f}%) |",
        f"| PnL net estimé | {total_pnl_net:+.2f} € ({tot_np:+.2f}%) |",
        "", "---", "",
    ]

    if divergence_log:
        lines += [
            "## ⚠️ Journal de Validation Croisée",
            "",
            "_Divergences détectées entre sources (> 2%) — médiane utilisée automatiquement :_",
            "",
        ]
        for d in divergence_log:
            lines.append(f"- {d}")
        lines += ["", "---", ""]
    else:
        lines += [
            "## ✅ Validation Croisée",
            "",
            "_Aucune divergence détectée entre les sources ce jour. Données cohérentes._",
            "", "---", "",
        ]

    best  = max(summaries, key=lambda x: x["score"]) if summaries else None
    worst = min(summaries, key=lambda x: x["score"]) if summaries else None
    ctx   = ("Marchés en dynamique **positive**." if macro_score >= 6
             else "Marchés sous **pression baissière**." if macro_score <= 4
             else "Marchés en phase **neutre**.")

    lines += ["## 🧭 Conclusion Stratégique", "", ctx, ""]
    if best and worst:
        lines += [
            f"**Meilleure position :** {best['name']} (score {best['score']:.1f}/10, "
            f"PnL brut {best['pnl_brut_pct']:+.1f}%)",
            f"**Position à surveiller :** {worst['name']} (score {worst['score']:.1f}/10, "
            f"PnL net {worst['pnl_net']:+.2f} €)",
            "",
        ]

    # Watchlist — header sans backtick parasite (correction v3.2.1)
    lines += [
        "### 🔭 Watchlist — Top 3 Valeurs Hors Portefeuille",
        "",
        "| Valeur | Secteur | Cours | Var. | Score | Sentiment |",
        "|--------|---------|-------|------|-------|-----------|",
    ]
    watch_res = []
    for w in WATCHLIST:
        pe, chg, src, _ = get_price_eur(w, eur_usd, td_prices)
        if not pe:
            continue
        bull, bear, _ = get_sentiment(w)
        cs, cons_str, _ = get_consensus(w)
        sc = round((bull / 10 + cs) / 2, 2)
        watch_res.append({"name": w["name"], "sector": w["sector"],
                          "price": pe, "chg": chg, "sc": sc, "bull": bull})
    watch_res.sort(key=lambda x: x["sc"], reverse=True)
    for w in watch_res[:3]:
        arr = "▲" if w["chg"] > 0 else "▼"
        lines.append(
            f"| **{w['name']}** | {w['sector']} | {w['price']:.2f} € "
            f"| {arr} {w['chg']:+.2f}% | {w['sc']:.1f}/10 | Bull {w['bull']:.0f}% |"
        )

    lines += [
        "",
        "---",
        "",
        f"_Rapport v3.2 — {now.strftime('%d/%m/%Y à %H:%M')} Paris_",
        "_Sources : TwelveData (cours US) + EODHD (Euronext/indices) + Finnhub (sentiment/consensus)_",
        f"_EUR/USD : 1 EUR = {1/eur_usd:.4f} USD — {eurusd_src}_",
        "_Frais courtage BoursoBank Découverte (brochure 13/11/2025)_",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    os.makedirs("reports", exist_ok=True)
    with open("reports/daily_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("✅ Rapport v3.2 généré : reports/daily_report.md")
