#!/usr/bin/env python3
"""
Portfolio Analyzer v5.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARCHITECTURE DES CLÉS API v5.2 — OPTIMISATION QUOTAS PLANS GRATUITS

  ┌──────────────────┬──────────────────────────────────────────────┬────────────────────────┐
  │ Clé API          │ Mission v5.2                                 │ Quota gratuit réel     │
  ├──────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ AlphaVantage     │ EUR/USD · Historique US · Sentiment US (NLP) │ 25 req/jour → ~7/run   │
  │ TwelveData       │ Cours US temps réel (batch)                  │ 800/jour  → ≤9/run     │
  │ EODHD            │ Cours EU · Indices · News EU · Historique EU │ 20/jour   → ~12/run ✅  │
  │ Finnhub          │ Sentiment EU · Consensus · News US watchlist │ 60/min illimité/jour   │
  └──────────────────┴──────────────────────────────────────────────┴────────────────────────┘

  RÈGLES CLÉS v5.2 :
  • EODHD N'EST JAMAIS appelé pour les cours US si TwelveData a répondu.
  • AlphaVantage NEWS_SENTIMENT remplace Finnhub pour le sentiment des valeurs US
    (score NLP intégré, plus précis que l'analyse lexicale).
  • AlphaVantage TIME_SERIES_MONTHLY remplace TIME_SERIES_DAILY pour l'historique US.
  • News sociétés EU (DEC.PA, ACA.PA, ABNX.PA) → EODHD seul (Finnhub plan free
    ne couvre pas les small/mid caps européennes).
  • News sociétés US (watchlist) → Finnhub company-news (libère EODHD).
  • Finnhub assure le sentiment des valeurs Euronext (.PA).

  BUDGET APPELS PAR RUN :
    AlphaVantage : 1 (EUR/USD) + 3 (hist US) + 3–6 (sentiment US) = ~7–10/run
    TwelveData   : ≤9 (cours US batch)
    EODHD        : 3 (cours EU) + 3 (indices) + 3 (news EU) + 3 (hist EU) = ~12/run
    Finnhub      : 3 (sentiment EU) + 6 (consensus) + 3 (news US) = ~12–15/run

Scoring v5.2 (inchangé) :
  Prix vs PRU        : 30 %
  Sentiment presse   : 20 %
  Consensus analystes: 20 %
  Historique mensuel : 30 %
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import csv
import json
import time
import threading  # PATCH : ajout pour _quota_lock
import requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# ─── CLÉS API ────────────────────────────────────────────────────────────────
FINNHUB_KEY      = os.environ.get("FINNHUB_API_KEY", "")
EODHD_KEY        = os.environ.get("EODHD_API_KEY", "")
TWELVEDATA_KEY   = os.environ.get("TWELVEDATA_API_KEY", "")
ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")

for k, v in [("FINNHUB_API_KEY", FINNHUB_KEY), ("EODHD_API_KEY", EODHD_KEY),
             ("TWELVEDATA_API_KEY", TWELVEDATA_KEY), ("ALPHAVANTAGE_API_KEY", ALPHAVANTAGE_KEY)]:
    if not v:
        print(f"[WARN] Clé absente : {k} — fallback cache activé pour cette source")

FH_BASE  = "https://finnhub.io/api/v1"
EOD_BASE = "https://eodhd.com/api"
TD_BASE  = "https://api.twelvedata.com"
AV_BASE  = "https://www.alphavantage.co/query"
PARIS_TZ = ZoneInfo("Europe/Paris")

DIVERGENCE_THRESHOLD_PCT = 2.0
CACHE_PATH   = "cache/session_cache.json"
HISTORY_PATH = "reports/history.csv"
CHARTS_DIR   = "reports/charts"
HISTORY_COLS = ["date", "time", "ticker", "name", "price_eur", "cost_eur",
                "qty", "vm", "pnl_brut", "pnl_brut_pct", "pnl_net",
                "pnl_net_pct", "score", "rec"]

# ─── QUOTAS JOURNALIERS PAR CLÉ (limites réelles plans gratuits) ─────────────
_QUOTA = {
    "alphavantage": {"used": 0, "limit": 23},   # 25/jour réel → budget run: 23
    "twelvedata":   {"used": 0, "limit": 60},   # 800/jour → budget run: 60
    "eodhd":        {"used": 0, "limit": 18},   # 20/jour réel → budget run: 18
    "finnhub":      {"used": 0, "limit": 55},   # 60 req/min → budget run: 55
}

# PATCH : Lock global pour protéger _QUOTA en contexte multi-thread
_quota_lock = threading.Lock()  # PATCH : ajout du lock threading


def _quota_ok(key: str) -> bool:
    with _quota_lock:  # PATCH : acquisition du lock avant lecture
        q = _QUOTA.get(key)
        return q["used"] < q["limit"] if q else True


def _quota_inc(key: str):
    with _quota_lock:  # PATCH : acquisition du lock avant écriture
        if key in _QUOTA:
            _QUOTA[key]["used"] += 1

def _quota_status() -> dict:
    return {k: f"{v['used']}/{v['limit']}" for k, v in _QUOTA.items()}


# ─── PORTEFEUILLE ─────────────────────────────────────────────────────────────
PORTFOLIO = [
    {"name": "Palantir Technologies", "isin": "US69608A1088",
     "ticker_fh": "PLTR",    "ticker_eod": "PLTR.US",  "ticker_td": "PLTR",  "ticker_av": "PLTR",
     "qty": 2,  "cost_eur": 119.06, "marche": "us"},
    {"name": "CoreWeave",             "isin": "US21873S1087",
     "ticker_fh": "CRWV",    "ticker_eod": "CRWV.US",  "ticker_td": "CRWV",  "ticker_av": "CRWV",
     "qty": 2,  "cost_eur": 93.91,  "marche": "us"},
    {"name": "Riot Platforms",        "isin": "US7672921050",
     "ticker_fh": "RIOT",    "ticker_eod": "RIOT.US",  "ticker_td": "RIOT",  "ticker_av": "RIOT",
     "qty": 6,  "cost_eur": 15.84,  "marche": "us"},
    {"name": "JCDecaux",              "isin": "FR0000077919",
     "ticker_fh": "DEC.PA",  "ticker_eod": "DEC.PA",   "ticker_td": None,    "ticker_av": None,
     "qty": 2,  "cost_eur": 17.77,  "marche": "euronext"},
    {"name": "Crédit Agricole SA",    "isin": "FR0000045072",
     "ticker_fh": "ACA.PA",  "ticker_eod": "ACA.PA",   "ticker_td": None,    "ticker_av": None,
     "qty": 10, "cost_eur": 16.90,  "marche": "euronext"},
    {"name": "Abionyx Pharma",        "isin": "FR0012616852",
     "ticker_fh": "ABNX.PA", "ticker_eod": "ABNX.PA",  "ticker_td": None,    "ticker_av": None,
     "qty": 10, "cost_eur": 3.84,   "marche": "euronext"},
]

INDICES = {
    "S&P 500":    {"eod": "GSPC.INDX", "fh": "^GSPC"},
    "CAC 40":     {"eod": "FCHI.INDX", "fh": "^FCHI"},
    "Nikkei 225": {"eod": "N225.INDX", "fh": "^N225"},
}

WATCHLIST = [
    {"name": "NVIDIA",        "ticker_fh": "NVDA",   "ticker_eod": "NVDA.US", "ticker_td": "NVDA",  "ticker_av": "NVDA",  "marche": "us",       "sector": "IA / Semi-conducteurs"},
    {"name": "Microsoft",     "ticker_fh": "MSFT",   "ticker_eod": "MSFT.US", "ticker_td": "MSFT",  "ticker_av": "MSFT",  "marche": "us",       "sector": "IA / Cloud"},
    {"name": "Coinbase",      "ticker_fh": "COIN",   "ticker_eod": "COIN.US", "ticker_td": "COIN",  "ticker_av": "COIN",  "marche": "us",       "sector": "Crypto / Fintech"},
    {"name": "LVMH",          "ticker_fh": "MC.PA",  "ticker_eod": "MC.PA",   "ticker_td": None,    "ticker_av": None,    "marche": "euronext", "sector": "Luxe / Consommation"},
    {"name": "TotalEnergies", "ticker_fh": "TTE.PA", "ticker_eod": "TTE.PA",  "ticker_td": None,    "ticker_av": None,    "marche": "euronext", "sector": "Énergie"},
    {"name": "Airbus",        "ticker_fh": "AIR.PA", "ticker_eod": "AIR.PA",  "ticker_td": None,    "ticker_av": None,    "marche": "euronext", "sector": "Aéronautique / Défense"},
]

BROKERAGE = {
    "euronext": {"threshold": 500,  "flat": 1.99,  "rate": 0.006,  "min": 1.99},
    "us":       {"threshold": 6000, "flat": 6.95,  "rate": 0.0012, "min": 6.95},
}

def calc_fee(amount: float, marche: str) -> float:
    t = BROKERAGE.get(marche, BROKERAGE["euronext"])
    return round(max(t["flat"] if amount <= t["threshold"] else t["rate"] * amount, t["min"]), 2)


# ══════════════════════════════════════════════════════════════════════════════
# CACHE SESSION  (fallback GitHub)
# ══════════════════════════════════════════════════════════════════════════════

def load_session_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_session_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    cache["date"]     = str(date.today())
    cache["saved_at"] = datetime.now(PARIS_TZ).strftime("%d/%m/%Y %H:%M")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# COUCHE HTTP  (quota-aware)
# ══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict, api_key_name: str, timeout: int = 12) -> tuple:
    if not _quota_ok(api_key_name):
        return None, "QUOTA_REACHED"
    _quota_inc(api_key_name)
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json(), None
        if r.status_code == 429:
            return None, "HTTP_429_QUOTA"
        return None, f"HTTP {r.status_code}"
    except requests.exceptions.Timeout:
        return None, "Timeout"
    except requests.exceptions.ConnectionError:
        return None, "Connexion impossible"
    except Exception as e:
        return None, str(e)[:60]

def _is_quota_error(err: str) -> bool:
    return err in ("QUOTA_REACHED", "HTTP_429_QUOTA") if err else False


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION CROISÉE
# ══════════════════════════════════════════════════════════════════════════════

def cross_validate(val1: float, src1: str, val2: float, src2: str) -> tuple:
    if val1 and val2 and val1 > 0 and val2 > 0:
        ecart_pct = abs(val1 - val2) / val1 * 100
        if ecart_pct > DIVERGENCE_THRESHOLD_PCT:
            mediane = round((val1 + val2) / 2, 4)
            note = (f"⚠️ Divergence {ecart_pct:.1f}% entre {src1} ({val1:.4f}) "
                    f"et {src2} ({val2:.4f}) → médiane : {mediane:.4f}")
            return mediane, note
    return val1 if val1 and val1 > 0 else val2, None


# ══════════════════════════════════════════════════════════════════════════════
# ① EUR/USD ── AlphaVantage  (1 appel/run)
#    Fallback → cache session
# ══════════════════════════════════════════════════════════════════════════════

def get_eur_usd(session_cache: dict) -> tuple:
    errors = []
    if ALPHAVANTAGE_KEY:
        data, err = _get(AV_BASE, {
            "function":      "CURRENCY_EXCHANGE_RATE",
            "from_currency": "USD",
            "to_currency":   "EUR",
            "apikey":        ALPHAVANTAGE_KEY,
        }, "alphavantage")
        if isinstance(data, dict):
            rate_info = data.get("Realtime Currency Exchange Rate", {})
            rate_str  = rate_info.get("5. Exchange Rate")
            if rate_str:
                try:
                    return float(rate_str), "AlphaVantage", False, None
                except ValueError:
                    pass
            if data.get("Note") or data.get("Information"):
                errors.append("AlphaVantage:quota")
            else:
                errors.append(f"AlphaVantage:{err or 'vide'}")
        elif _is_quota_error(err):
            errors.append("AlphaVantage:quota atteint")
        else:
            errors.append(f"AlphaVantage:{err or 'vide'}")
    else:
        errors.append("AlphaVantage:clé absente")

    if session_cache.get("eur_usd"):
        saved_at = session_cache.get("saved_at", "date inconnue")
        return (session_cache["eur_usd"], "Cache", True,
                f"EUR/USD non disponible ({', '.join(errors)}) — cache du {saved_at} utilisé")

    return (0.92, "Défaut 0.92", False,
            f"❌ EUR/USD indisponible ({', '.join(errors)}) — valeur de secours 0.92 appliquée")


# ══════════════════════════════════════════════════════════════════════════════
# ② COURS US ── TwelveData  (batch = 1 crédit par ticker)
#    Plan free : 800 crédits/jour — ≤9 tickers ✅
# ══════════════════════════════════════════════════════════════════════════════

_td_cache:     dict  = {}
_td_last_call: float = 0.0
_td_errors:    dict  = {}

def td_fetch_batch(tickers: list) -> dict:
    global _td_last_call
    to_fetch = [t for t in tickers if t and t not in _td_cache]
    if not to_fetch:
        return {t: _td_cache.get(t) for t in tickers if t}

    elapsed = time.time() - _td_last_call
    if elapsed < 3 and _td_last_call > 0:  # PATCH 2 : seuil anti-spam 10s → 3s
        time.sleep(3 - elapsed)             # PATCH 2 : sleep réduit à 3s max

    results = {}
    for i in range(0, len(to_fetch), 6):
        batch = to_fetch[i:i+6]
        data, err = _get(f"{TD_BASE}/price",
                         {"symbol": ",".join(batch), "apikey": TWELVEDATA_KEY},
                         "twelvedata")
        _td_last_call = time.time()

        if isinstance(data, dict):
            for ticker in batch:
                item = data.get(ticker, {})
                if isinstance(item, dict) and item.get("price") and item.get("status") != "error":
                    try:
                        val = float(item["price"])
                        results[ticker]   = val
                        _td_cache[ticker] = val
                    except Exception:
                        results[ticker]   = None
                        _td_errors[ticker] = "Valeur non numérique"
                else:
                    results[ticker]   = None
                    _td_errors[ticker] = (item.get("message", err or "vide")
                                          if isinstance(item, dict) else (err or "vide"))
        else:
            for ticker in batch:
                results[ticker]   = None
                _td_errors[ticker] = err or "Réponse invalide"

        if i + 6 < len(to_fetch):
            time.sleep(3)  # PATCH 2 : sleep inter-batches 12s → 3s

    for t in tickers:
        if t and t not in results:
            results[t] = _td_cache.get(t)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ③ COURS (tous marchés) ── Orchestrateur
#    US      → TwelveData (principal) ; EODHD UNIQUEMENT si TwelveData échoue
#    Euronext → EODHD (seul)
#    Fallback final → cache session
# ══════════════════════════════════════════════════════════════════════════════

def get_price_eur(asset: dict, eur_usd: float, td_prices: dict,
                  session_cache: dict) -> tuple:
    td_val = eod_val = None
    note   = None
    chg    = 0.0
    errors = []
    cache_key = f"price_{asset['ticker_eod']}"

    if asset["marche"] == "us":
        # ① TwelveData (spécialiste US) — principal
        if TWELVEDATA_KEY:
            td_ticker = asset.get("ticker_td")
            td_raw    = td_prices.get(td_ticker) if td_ticker else None
            if td_raw and td_raw > 0:
                td_val = round(td_raw * eur_usd, 4)
            elif td_ticker:
                errors.append(f"TwelveData:{_td_errors.get(td_ticker, 'indisponible')}")
        else:
            errors.append("TwelveData:clé absente")

        # ② EODHD US — UNIQUEMENT si TwelveData a échoué (court-circuit)
        if td_val is None and EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                             {"api_token": EODHD_KEY, "fmt": "json"},
                             "eodhd")
            if data and not _is_quota_error(err):
                raw = data.get("close") or data.get("previousClose")
                if raw and float(raw) > 0:
                    chg     = float(data.get("change_p", 0.0))
                    eod_val = round(float(raw) * eur_usd, 4)
                else:
                    errors.append("EODHD:cours nul")
            elif _is_quota_error(err):
                errors.append("EODHD:quota atteint")
            else:
                errors.append(f"EODHD:{err}")

        if td_val and eod_val:
            final, note = cross_validate(td_val, "TwelveData", eod_val, "EODHD")
            return final, chg, "TwelveData+EODHD", False, note
        if td_val:  return td_val,  0.0, "TwelveData", False, None
        if eod_val: return eod_val, chg, "EODHD",      False, None

    else:  # Euronext — EODHD seul
        if EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                             {"api_token": EODHD_KEY, "fmt": "json"},
                             "eodhd")
            if data and not _is_quota_error(err):
                raw = data.get("close") or data.get("previousClose")
                if raw and float(raw) > 0:
                    return round(float(raw), 4), float(data.get("change_p", 0.0)), "EODHD", False, None
                errors.append("EODHD:cours nul")
            elif _is_quota_error(err):
                errors.append("EODHD:quota atteint")
            else:
                errors.append(f"EODHD:{err}")
        else:
            errors.append("EODHD:clé absente")

    # Fallback universel : cache session
    if session_cache.get(cache_key):
        saved_at = session_cache.get("saved_at", "date inconnue")
        return (session_cache[cache_key], 0.0, "Cache", True,
                f"Cours non disponible ({', '.join(errors)}) — cache du {saved_at} utilisé")

    return None, 0.0, f"Indisponible ({', '.join(errors)})", False, None


# ══════════════════════════════════════════════════════════════════════════════
# ④ INDICES ── EODHD principal · Finnhub fallback
# ══════════════════════════════════════════════════════════════════════════════

def get_index(symbols: dict) -> dict:
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/real-time/{symbols['eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json"},
                         "eodhd")
        if data and not _is_quota_error(err):
            raw = data.get("close") or data.get("previousClose")
            if raw:
                return {"price":      float(raw),
                        "change_pct": float(data.get("change_p", 0.0)),
                        "source":     "EODHD"}
        eod_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        eod_err = "clé absente"

    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/quote",
                         {"symbol": symbols["fh"], "token": FINNHUB_KEY},
                         "finnhub")
        if data and data.get("c") and not _is_quota_error(err):
            return {"price":      float(data["c"]),
                    "change_pct": float(data.get("dp", 0.0)),
                    "source":     "Finnhub (fallback)"}
        fh_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        fh_err = "clé absente"

    return {"price": 0.0, "change_pct": 0.0,
            "source": f"❌ Indisponible (EODHD:{eod_err}, Finnhub:{fh_err})"}


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ NEWS ── Logique différenciée par marché
#    EU (.PA) → EODHD seul (Finnhub plan free ne couvre pas les EU small/mid caps)
#    US       → Finnhub company-news (libère quota EODHD)
#    Macro    → EODHD général · Finnhub fallback
# ══════════════════════════════════════════════════════════════════════════════

_news_cache: dict = {}

def get_company_news(asset: dict, n: int = 2) -> list:
    key = asset["ticker_eod"]
    if key in _news_cache:
        return _news_cache[key][:n]
    from_d = str(date.today() - timedelta(days=7))
    to_d   = str(date.today())

    if asset.get("marche") == "euronext":
        # EU → EODHD seul (Finnhub ne couvre pas les small/mid caps EU)
        if EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/news",
                             {"s": asset["ticker_eod"], "limit": max(n, 10),
                              "from": from_d, "api_token": EODHD_KEY, "fmt": "json"},
                             "eodhd")
            if isinstance(data, list) and data and not _is_quota_error(err):
                titles = [i.get("title", "") for i in data if i.get("title")]
                _news_cache[key] = titles
                return titles[:n]
        _news_cache[key] = []
        return []
    else:
        # US → Finnhub en premier (libère EODHD)
        if FINNHUB_KEY:
            data, err = _get(f"{FH_BASE}/company-news",
                             {"symbol": asset["ticker_fh"], "from": from_d,
                              "to": to_d, "token": FINNHUB_KEY},
                             "finnhub")
            if isinstance(data, list) and data and not _is_quota_error(err):
                titles = [i.get("headline", "") for i in data if i.get("headline")]
                _news_cache[key] = titles
                return titles[:n]
        # Fallback EODHD si Finnhub échoue
        if EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/news",
                             {"s": asset["ticker_eod"], "limit": max(n, 10),
                              "from": from_d, "api_token": EODHD_KEY, "fmt": "json"},
                             "eodhd")
            if isinstance(data, list) and data and not _is_quota_error(err):
                titles = [i.get("title", "") for i in data if i.get("title")]
                _news_cache[key] = titles
                return titles[:n]
        _news_cache[key] = []
        return []

def get_macro_news(n: int = 5) -> list:
    # EODHD général en premier
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/news",
                         {"t": "general", "limit": n,
                          "api_token": EODHD_KEY, "fmt": "json"},
                         "eodhd")
        if isinstance(data, list) and data and not _is_quota_error(err):
            return [i.get("title", "") for i in data if i.get("title")]

    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/news",
                         {"category": "general", "token": FINNHUB_KEY},
                         "finnhub")
        if isinstance(data, list) and data and not _is_quota_error(err):
            return [i.get("headline", "") for i in data[:n] if i.get("headline")]
    return []


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ SENTIMENT ── Logique différenciée par marché
#    US  → AlphaVantage NEWS_SENTIMENT (NLP intégré, plus précis)
#          Fallback : Finnhub news-sentiment → analyse lexicale
#    EU  → Finnhub news-sentiment (.PA)
#          Fallback : analyse lexicale sur news EODHD
# ══════════════════════════════════════════════════════════════════════════════

def get_sentiment(asset: dict) -> tuple:
    """Retourne (bull_pct, bear_pct, source_str)."""

    if asset.get("marche") == "us":
        # ── US : AlphaVantage NEWS_SENTIMENT (NLP) ───────────────────────
        ticker_av = asset.get("ticker_av")
        if ALPHAVANTAGE_KEY and ticker_av:
            data, err = _get(AV_BASE, {
                "function":    "NEWS_SENTIMENT",
                "tickers":     ticker_av,
                "limit":       50,
                "apikey":      ALPHAVANTAGE_KEY,
            }, "alphavantage")
            if isinstance(data, dict) and data.get("feed") and not _is_quota_error(err):
                scores = []
                for item in data["feed"]:
                    for ts in item.get("ticker_sentiment", []):
                        if ts.get("ticker") == ticker_av:
                            try:
                                scores.append(float(ts.get("ticker_sentiment_score", 0)))
                            except (ValueError, TypeError):
                                pass
                if scores:
                    avg = sum(scores) / len(scores)
                    # avg ∈ [-1, 1] → bull% = (avg+1)/2*100
                    bull = round((avg + 1) / 2 * 100, 1)
                    bear = round(100 - bull, 1)
                    return bull, bear, "AlphaVantage NLP"
            # Fallback AV : quota ou pas de données
            av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            av_err = "clé absente" if not ALPHAVANTAGE_KEY else "ticker_av absent"

        # Fallback US : Finnhub news-sentiment
        if FINNHUB_KEY:
            data, err = _get(f"{FH_BASE}/news-sentiment",
                             {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY},
                             "finnhub")
            if data and data.get("sentiment") and not _is_quota_error(err):
                bull = float(data["sentiment"].get("bullishPercent", 0.5)) * 100
                bear = float(data["sentiment"].get("bearishPercent", 0.5)) * 100
                return round(bull, 1), round(bear, 1), f"Finnhub (fallback AV:{av_err})"
            fh_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            fh_err = "clé absente"

        # Fallback US final : lexical sur news
        news = _news_cache.get(asset["ticker_eod"]) or get_company_news(asset, n=10)
        if news:
            bull, bear = _lexical_sentiment(news)
            return bull, bear, f"Lexical (AV:{av_err}, FH:{fh_err})"
        return 50.0, 50.0, f"Neutre par défaut (AV:{av_err}, FH:{fh_err})"

    else:
        # ── EU : Finnhub news-sentiment ────────────────────────────────────
        if FINNHUB_KEY:
            data, err = _get(f"{FH_BASE}/news-sentiment",
                             {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY},
                             "finnhub")
            if data and data.get("sentiment") and not _is_quota_error(err):
                bull = float(data["sentiment"].get("bullishPercent", 0.5)) * 100
                bear = float(data["sentiment"].get("bearishPercent", 0.5)) * 100
                return round(bull, 1), round(bear, 1), "Finnhub"
            fh_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            fh_err = "clé absente"

        # Fallback EU : lexical sur news EODHD (0 appel supplémentaire)
        news = _news_cache.get(asset["ticker_eod"]) or get_company_news(asset, n=10)
        if news:
            bull, bear = _lexical_sentiment(news)
            return bull, bear, f"Lexical EODHD (Finnhub:{fh_err})"
        return 50.0, 50.0, f"Neutre par défaut (Finnhub:{fh_err})"

def _lexical_sentiment(news: list) -> tuple:
    bull_w = {"growth", "buy", "bullish", "surge", "record", "beat", "strong",
              "gain", "up", "rise", "soar", "profit", "positive", "upgrade"}
    bear_w = {"loss", "sell", "bearish", "drop", "miss", "weak", "cut", "down",
              "fall", "decline", "risk", "negative", "downgrade", "warn"}
    words = " ".join(news).lower().split()
    b = 0
    s = 0
    for w in words:
        if w in bull_w:
            b += 1
        elif w in bear_w:
            s += 1
    t = b + s or 1
    return round(b / t * 100, 1), round(s / t * 100, 1)


# ══════════════════════════════════════════════════════════════════════════════
# ⑦ CONSENSUS ── Finnhub principal · EODHD fundamentals fallback
# ══════════════════════════════════════════════════════════════════════════════

def get_consensus(asset: dict) -> tuple:
    """Retourne (score/10, detail_str, source_str)."""
    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/stock/recommendation",
                         {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY},
                         "finnhub")
        if isinstance(data, list) and data and not _is_quota_error(err):
            r  = data[0]
            sb = r.get("strongBuy", 0); b = r.get("buy", 0)
            h  = r.get("hold", 0);      s = r.get("sell", 0); ss = r.get("strongSell", 0)
            total = sb + b + h + s + ss
            if total > 0:
                score = (sb*10 + b*7.5 + h*5 + s*2.5) / total
                return round(score, 2), f"SB:{sb} B:{b} H:{h} S:{s} SS:{ss}", "Finnhub"
        fh_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        fh_err = "clé absente"

    # Fallback : EODHD fundamentals
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/fundamentals/{asset['ticker_eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json", "filter": "AnalystRatings"},
                         "eodhd")
        if isinstance(data, dict) and data.get("Rating") and not _is_quota_error(err):
            rat   = data["Rating"]
            label = str(rat.get("Rating", "")).lower()
            tp    = rat.get("TargetPrice", "N/D")
            m     = {"strong buy": 9.0, "buy": 7.5, "hold": 5.0,
                     "sell": 2.5, "strong sell": 0.5}
            score = m.get(label, 5.0)
            return score, f"Rating:{rat.get('Rating','?')} TP:{tp}$", f"EODHD (fallback Finnhub:{fh_err})"
        eod_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        eod_err = "clé absente"

    return (5.0, "N/D", f"Neutre par défaut (Finnhub:{fh_err}, EODHD:{eod_err})")


# ══════════════════════════════════════════════════════════════════════════════
# ⑧ HISTORIQUE MENSUEL ── Logique différenciée par marché
#    US  → AlphaVantage TIME_SERIES_MONTHLY (données déjà mensuelles)
#          Fallback : Finnhub candles hebdo → cache
#    EU  → EODHD eod mensuel ajusté (principal)
#          Fallback : Finnhub candles hebdo → cache
# ══════════════════════════════════════════════════════════════════════════════

session_cache_global: dict = {}

def get_monthly_history(asset: dict, eur_usd: float, months: int = 6) -> tuple:
    """Retourne (dates_list, prices_eur_list, source_str, cache_flag: bool, error_str|None)."""
    from_d    = str(date.today() - timedelta(days=months * 31))
    to_d      = str(date.today())
    cache_key = f"hist_{asset['ticker_eod']}"

    if asset.get("marche") == "us":
        # ── US : AlphaVantage TIME_SERIES_MONTHLY ────────────────────────
        ticker_av = asset.get("ticker_av")
        if ALPHAVANTAGE_KEY and ticker_av:
            data, err = _get(AV_BASE, {
                "function": "TIME_SERIES_MONTHLY",  # PATCH 1 : TIME_SERIES_DAILY → TIME_SERIES_MONTHLY
                "symbol":   ticker_av,              # PATCH 1 : suppression de outputsize:compact
                "apikey":   ALPHAVANTAGE_KEY,
            }, "alphavantage")
            if isinstance(data, dict) and data.get("Monthly Time Series") and not _is_quota_error(err):  # PATCH 1 : clé JSON Monthly Time Series
                ts = data["Monthly Time Series"]  # PATCH 1 : lecture directe des données mensuelles
                dates  = []
                closes = []
                for month_str, vals in sorted(ts.items()):  # PATCH 1 : plus de boucle d'agrégation
                    if month_str < from_d:
                        continue
                    try:
                        dates.append(month_str[:7])                          # PATCH 1 : clé YYYY-MM
                        closes.append(round(float(vals["4. close"]) * eur_usd, 2))  # PATCH 1 : close direct
                    except (ValueError, TypeError, KeyError):
                        pass
                if len(dates) >= 2:
                    return dates, closes, "AlphaVantage", False, None
            av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            av_err = "clé absente" if not ALPHAVANTAGE_KEY else "ticker_av absent"

        # Fallback US : Finnhub candles hebdo → agrégés en mois
        if FINNHUB_KEY:
            dates, closes, src, cache_flag, err_str = _finnhub_candles(asset, eur_usd, months)
            if dates:
                return dates, closes, f"Finnhub (fallback AV:{av_err})", cache_flag, err_str
            fh_err = err_str or "vide"
        else:
            fh_err = "clé absente"

        # Fallback final : cache
        if session_cache_global.get(cache_key):
            saved_at = session_cache_global.get("saved_at", "date inconnue")
            cached   = session_cache_global[cache_key]
            return (cached.get("dates", []), cached.get("closes", []),
                    "Cache", True,
                    f"Historique US non disponible (AV:{av_err}, FH:{fh_err}) — cache du {saved_at}")
        return ([], [], f"Indisponible (AV:{av_err}, FH:{fh_err})", False,
                "Historique indisponible — graphique non généré")

    else:
        # ── EU : EODHD eod mensuel ajusté ────────────────────────────────
        if EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/eod/{asset['ticker_eod']}",
                             {"api_token": EODHD_KEY, "fmt": "json",
                              "period": "m", "from": from_d, "to": to_d},
                             "eodhd")
            if isinstance(data, list) and len(data) >= 2 and not _is_quota_error(err):
                dates  = [d["date"] for d in data if d.get("adjusted_close") or d.get("close")]
                closes = [float(d.get("adjusted_close") or d.get("close", 0)) for d in data
                          if d.get("adjusted_close") or d.get("close")]
                return dates, closes, "EODHD", False, None
            eod_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            eod_err = "clé absente"

        # Fallback EU : Finnhub candles hebdo
        if FINNHUB_KEY:
            dates, closes, src, cache_flag, err_str = _finnhub_candles(asset, eur_usd, months)
            if dates:
                return dates, closes, f"Finnhub (fallback EODHD:{eod_err})", cache_flag, err_str
            fh_err = err_str or "vide"
        else:
            fh_err = "clé absente"

        # Fallback cache
        if session_cache_global.get(cache_key):
            saved_at = session_cache_global.get("saved_at", "date inconnue")
            cached   = session_cache_global[cache_key]
            return (cached.get("dates", []), cached.get("closes", []),
                    "Cache", True,
                    f"Historique EU non disponible (EODHD:{eod_err}, FH:{fh_err}) — cache du {saved_at}")
        return ([], [], f"Indisponible (EODHD:{eod_err}, FH:{fh_err})", False,
                "Historique indisponible — graphique non généré")

def _finnhub_candles(asset: dict, eur_usd: float, months: int) -> tuple:
    """Retourne (dates, closes, src, cache_flag, err_str) via Finnhub candles hebdo."""
    from_ts = int((datetime.now() - timedelta(days=months * 31)).timestamp())
    to_ts   = int(datetime.now().timestamp())
    data, err = _get(f"{FH_BASE}/stock/candle",
                     {"symbol": asset["ticker_fh"], "resolution": "W",
                      "from": from_ts, "to": to_ts, "token": FINNHUB_KEY},
                     "finnhub")
    if isinstance(data, dict) and data.get("s") == "ok" and data.get("c") and not _is_quota_error(err):
        monthly: dict = {}
        for ts, cl in zip(data["t"], data["c"]):
            month_key = datetime.fromtimestamp(ts).strftime("%Y-%m")
            monthly[month_key] = cl
        dates  = sorted(monthly.keys())
        closes = [round(monthly[k] * eur_usd, 2)
                  if asset.get("marche") == "us" else round(monthly[k], 2)
                  for k in dates]
        return dates, closes, "Finnhub", False, None
    err_str = "quota atteint" if _is_quota_error(err) else (err or "vide")
    return [], [], "Finnhub", False, err_str


# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_history(dates: list, closes: list) -> tuple:
    if len(closes) < 2:
        return 5.0, "NEUTRE", 0.0, 0.0, 0.0
    def safe_ret(idx_from, idx_to=-1):
        try:
            return (closes[idx_to] / closes[idx_from] - 1) * 100
        except (IndexError, ZeroDivisionError):
            return 0.0
    ret_1m = safe_ret(-2)
    ret_3m = safe_ret(-4) if len(closes) >= 4 else safe_ret(0)
    ret_6m = safe_ret(-7) if len(closes) >= 7 else safe_ret(0)
    score = 5.0
    if ret_1m >  5: score += 1.5
    elif ret_1m > 2: score += 0.75
    elif ret_1m < -5: score -= 1.5
    elif ret_1m < -2: score -= 0.75
    if ret_3m > 10: score += 2.0
    elif ret_3m > 5: score += 1.0
    elif ret_3m < -10: score -= 2.0
    elif ret_3m < -5: score -= 1.0
    if ret_6m > 15: score += 1.5
    elif ret_6m > 7: score += 0.75
    elif ret_6m < -15: score -= 1.5
    elif ret_6m < -7: score -= 0.75
    score = round(max(0.0, min(10.0, score)), 2)
    label = "HAUSSIER" if score >= 6.5 else "BAISSIER" if score <= 3.5 else "NEUTRE"
    return score, label, ret_1m, ret_3m, ret_6m

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
                  consensus, macro_score, hist_score, hist_label, total_score):
    p1 = (f"Gain net **{net_pnl_eur:+.2f} € ({net_pnl_pct:+.1f}%)** après frais."
          if net_pnl_eur >= 0
          else f"Perte nette **{net_pnl_eur:+.2f} € ({net_pnl_pct:+.1f}%)** après frais.")
    p2 = (f"Consensus **haussier** (score {sc:.1f}/10, Bull {bull:.0f}%)."
          if sc >= 7 else
          f"Consensus **neutre** ({bull:.0f}% bull / {bear:.0f}% bear)."
          if sc >= 5 else
          f"Consensus **défavorable** (score {sc:.1f}/10, Bear {bear:.0f}%).")
    p3 = ("Contexte macro **favorable**." if macro_score >= 6
          else "Contexte macro **défavorable**." if macro_score <= 4
          else "Contexte macro **neutre**.")
    p4 = f"Momentum mensuel **{hist_label}** (score historique {hist_score:.1f}/10)."
    return f"{p1} {p2} {p3} {p4}"


# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIQUE MENSUEL
# ══════════════════════════════════════════════════════════════════════════════

def generate_monthly_chart(asset, dates, closes, cost_eur, chart_path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        if len(dates) < 2:
            return False
        os.makedirs(os.path.dirname(chart_path), exist_ok=True)
        dt_dates = []
        for d in dates:
            try:
                dt_dates.append(datetime.strptime(d + "-01" if len(d) == 7 else d, "%Y-%m-%d"))
            except Exception:
                pass
        if len(dt_dates) < 2:
            return False
        perf = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        line_color = "#16a34a" if perf >= 0 else "#dc2626"
        fill_color = "#dcfce7" if perf >= 0 else "#fee2e2"
        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#f9f8f5")
        ax.set_facecolor("#f9f8f5")
        ax.plot(dt_dates, closes, color=line_color, linewidth=2.5,
                marker="o", markersize=5, zorder=3)
        ax.fill_between(dt_dates, closes, min(closes) * 0.97,
                        alpha=0.18, color=fill_color)
        ax.axhline(y=cost_eur, color="#6b7280", linestyle="--", linewidth=1.2,
                   alpha=0.8, label=f"PRU : {cost_eur:.2f} €")
        ax.annotate(f"{closes[0]:.2f}€", (dt_dates[0], closes[0]),
                    textcoords="offset points", xytext=(-10, 8),
                    fontsize=8, color="#374151")
        ax.annotate(f"{closes[-1]:.2f}€\n({perf:+.1f}%)", (dt_dates[-1], closes[-1]),
                    textcoords="offset points", xytext=(8, 0),
                    fontsize=9, fontweight="bold", color=line_color)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        plt.xticks(rotation=30, ha="right", fontsize=8)
        ax.yaxis.set_major_formatter(plt.FormatStrFormatter("%.2f€"))
        ax.tick_params(axis="y", labelsize=8)
        ax.grid(axis="y", linestyle=":", alpha=0.4, color="#d1d5db")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#e5e7eb")
        ax.spines["bottom"].set_color("#e5e7eb")
        ax.set_title(f"{asset['name']} — Historique mensuel 6 mois (€)",
                     fontsize=11, fontweight="bold", color="#111827", pad=12)
        ax.set_ylabel("Cours (€)", fontsize=8, color="#6b7280")
        ax.legend(fontsize=8, framealpha=0.6)
        plt.tight_layout()
        plt.savefig(chart_path, dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        return True
    except Exception as e:
        print(f"[WARN] Graphique {asset['name']} non généré : {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# HISTORIQUE CSV
# ══════════════════════════════════════════════════════════════════════════════

def append_history(now: datetime, rows: list):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    exists = os.path.isfile(HISTORY_PATH)
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[INFO] Historique CSV mis à jour : {len(rows)} lignes.")


# ══════════════════════════════════════════════════════════════════════════════
# HELPER PARALLÉLISATION  # PATCH : nouvelle fonction
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_asset_data(asset: dict, eur_usd: float,  # PATCH : nouvelle fonction helper
                      td_prices: dict, session_cache: dict) -> dict:  # PATCH :
    """Regroupe les 4 appels par asset pour ThreadPoolExecutor.  # PATCH :
    Retourne un dict structuré avec news, sentiment, consensus, historique."""  # PATCH :
    news = get_company_news(asset, 2)                          # PATCH : appel 1/4 — news société
    bull, bear, sent_src = get_sentiment(asset)                # PATCH : appel 2/4 — sentiment
    cs, cons_str, cons_src = get_consensus(asset)              # PATCH : appel 3/4 — consensus
    h_dates, h_closes, h_src, h_cache, h_err = get_monthly_history(  # PATCH : appel 4/4
        asset, eur_usd                                         # PATCH :
    )                                                          # PATCH :
    return {                     # PATCH : retour dict structuré
        "news":      news,       # PATCH :
        "bull":      bull,       # PATCH :
        "bear":      bear,       # PATCH :
        "sent_src":  sent_src,   # PATCH :
        "cs":        cs,         # PATCH :
        "cons_str":  cons_str,   # PATCH :
        "cons_src":  cons_src,   # PATCH :
        "h_dates":   h_dates,    # PATCH :
        "h_closes":  h_closes,   # PATCH :
        "h_src":     h_src,      # PATCH :
        "h_cache":   h_cache,    # PATCH :
        "h_err":     h_err,      # PATCH :
    }                            # PATCH :


# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def build_report() -> tuple:
    global session_cache_global
    now              = datetime.now(PARIS_TZ)
    lines            = []
    divergence_log   = []
    api_errors       = []
    cache_warnings   = []
    session_cache    = load_session_cache()
    session_cache_global = session_cache
    new_cache        = {}
    history_rows     = []
    charts_generated = []
    sources_log      = {}

    # ── Batch TwelveData (cours US + watchlist) ────────────────────────────
    print("[INFO] Batch TwelveData (cours US)...")
    us_tickers = [a["ticker_td"] for a in PORTFOLIO if a.get("ticker_td")]
    watch_td   = [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    td_prices  = td_fetch_batch(list(set(us_tickers + watch_td))) if TWELVEDATA_KEY else {}

    # ── EUR/USD ────────────────────────────────────────────────────────────
    print("[INFO] EUR/USD (AlphaVantage)...")
    eur_usd, eurusd_src, eurusd_cache, eurusd_note = get_eur_usd(session_cache)
    new_cache["eur_usd"] = eur_usd
    sources_log["EUR/USD"] = eurusd_src
    if eurusd_cache:
        cache_warnings.append(eurusd_note)
    elif eurusd_note and "❌" in eurusd_note:
        api_errors.append(f"EUR/USD : {eurusd_note}")
    if eurusd_note:
        divergence_log.append(f"EUR/USD : {eurusd_note}")

    # ── Indices macro ──────────────────────────────────────────────────────
    print("[INFO] Indices macro (EODHD)...")
    indices_data = {n: get_index(s) for n, s in INDICES.items()}
    for idx_name, d in indices_data.items():
        sources_log[idx_name] = d["source"]
        if "❌" in d["source"]:
            api_errors.append(f"Indice {idx_name} : {d['source']}")
    macro_score = score_macro(indices_data)
    macro_label = ("📈 Haussière" if macro_score >= 6
                   else "📉 Baissière" if macro_score <= 4 else "➡️ Neutre")
    macro_news  = get_macro_news(5)

    lines += [
        f"# 📊 Rapport de Portefeuille v5.2 — {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        "", "---", "",
        "## 🌍 Contexte Économique", "",
        f"**Tendance : {macro_label}** | Score macro : {macro_score:.1f}/10",
        f"**EUR/USD :** 1 EUR = {1/eur_usd:.4f} USD",
        "",
        "| Indice | Variation | Cours |",
        "|--------|-----------|-------|",
    ]
    for name, d in indices_data.items():
        arr = "▲" if d["change_pct"] > 0 else "▼" if d["change_pct"] < 0 else "—"
        lines.append(f"| {name} | {arr} {d['change_pct']:+.2f}% | {d['price']:,.2f} |")

    if macro_news:
        lines += ["", "**📰 Manchettes macro :**", ""]
        for t in macro_news:
            if t: lines.append(f"- {t}")

    lines += ["", "---", "", "## 📈 Analyse par Valeur", ""]

    total_cout = total_vm = total_pnl_brut = total_pnl_net = 0.0
    summaries  = []

    # ── Cours par asset (séquentiel — TwelveData batch déjà fait) ──────────
    prices = {}  # PATCH : pré-collecte des cours avant la parallélisation
    for asset in PORTFOLIO:  # PATCH :
        price_eur, chg, price_src, price_cache, div_note = get_price_eur(  # PATCH :
            asset, eur_usd, td_prices, session_cache)  # PATCH :
        prices[asset["ticker_eod"]] = (price_eur, chg, price_src, price_cache, div_note)  # PATCH :

    # ── Lancement parallèle : news + sentiment + consensus + historique ───
    print("[INFO] Lancement parallèle des données par asset...")  # PATCH : log parallélisation
    from concurrent.futures import ThreadPoolExecutor  # PATCH : import executor

    futures = {}  # PATCH : dict future → asset
    with ThreadPoolExecutor(max_workers=4) as executor:  # PATCH : pool de 4 workers
        for asset in PORTFOLIO:  # PATCH : soumission de toutes les tâches
            future = executor.submit(  # PATCH :
                _fetch_asset_data,     # PATCH :
                asset, eur_usd, td_prices, session_cache  # PATCH :
            )  # PATCH :
            futures[future] = asset  # PATCH : associe chaque future à son asset

    # ── Collecte des résultats indexés par ticker ─────────────────────────
    asset_results = {}  # PATCH : stockage des résultats parallèles
    for future, asset in futures.items():  # PATCH :
        try:  # PATCH :
            asset_results[asset["ticker_eod"]] = future.result()  # PATCH :
        except Exception as exc:  # PATCH : capture d'erreur par thread
            print(f"[WARN] Erreur thread {asset['name']} : {exc}")  # PATCH :
            asset_results[asset["ticker_eod"]] = {  # PATCH : valeurs neutres en cas d'échec
                "news": [], "bull": 50.0, "bear": 50.0, "sent_src": "Erreur",  # PATCH :
                "cs": 5.0, "cons_str": "N/D", "cons_src": "Erreur",           # PATCH :
                "h_dates": [], "h_closes": [], "h_src": "Erreur",             # PATCH :
                "h_cache": False, "h_err": str(exc),                           # PATCH :
            }  # PATCH :

    # ── Boucle de rendu (ordre garanti = ordre PORTFOLIO) ─────────────────
    for asset in PORTFOLIO:
        print(f"[INFO] Rendu {asset['name']}...")  # PATCH : message mis à jour
        ticker = asset["ticker_eod"]  # PATCH : alias local

        price_eur, chg, price_src, price_cache, div_note = prices[ticker]  # PATCH : lecture pré-collecte
        sources_log[ticker] = {"cours": price_src}  # PATCH :

        if div_note:
            divergence_log.append(f"{asset['name']} : {div_note}")
        if price_cache:
            cache_warnings.append(f"{asset['name']} — cours : {div_note or price_src}")
        if price_eur is None:
            lines += [
                f"### ❌ {asset['name']} `{ticker}`",
                "",
                "> **❌ Cours totalement indisponible** — aucune source ni cache",
                "", "---", "",
            ]
            api_errors.append(f"{asset['name']} : cours totalement indisponible")
            continue

        new_cache[f"price_{ticker}"] = price_eur  # PATCH : utilise alias ticker

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

        r = asset_results[ticker]  # PATCH : lecture du résultat parallèle

        news     = r["news"]       # PATCH :
        bull     = r["bull"]       # PATCH :
        bear     = r["bear"]       # PATCH :
        sent_src = r["sent_src"]   # PATCH :
        cs       = r["cs"]         # PATCH :
        cons_str = r["cons_str"]   # PATCH :
        cons_src = r["cons_src"]   # PATCH :
        h_dates  = r["h_dates"]    # PATCH :
        h_closes = r["h_closes"]   # PATCH :
        h_src    = r["h_src"]      # PATCH :
        h_cache  = r["h_cache"]    # PATCH :
        h_err    = r["h_err"]      # PATCH :

        sources_log[ticker]["sentiment"]  = sent_src  # PATCH :
        sources_log[ticker]["consensus"]  = cons_src  # PATCH :
        sources_log[ticker]["historique"] = h_src     # PATCH :

        if h_cache:
            cache_warnings.append(f"{asset['name']} — historique : {h_err or h_src}")
        if h_err and not h_cache:
            api_errors.append(f"{asset['name']} historique : {h_err}")

        h_score, h_label, ret_1m, ret_3m, ret_6m = score_history(h_dates, h_closes)
        sc_price = score_price(price_eur, cost)

        sentiment_score = round(bull / 10, 2)
        total_score = round(
            sc_price * 0.30 +
            sentiment_score * 0.20 +
            cs * 0.20 +
            h_score * 0.30,
            2
        )
        rec = recommend(total_score)

        chart_path     = f"{CHARTS_DIR}/{ticker.replace('.', '_')}.png"
        chart_ok       = generate_monthly_chart(asset, h_dates, h_closes, cost, chart_path)
        chart_rel_path = f"charts/{ticker.replace('.', '_')}.png"
        if chart_ok:
            charts_generated.append(chart_rel_path)

        chg_arrow  = "▲" if chg > 0 else "▼" if chg < 0 else "—"
        pnl_b_icon = "🟢" if pnl_brut >= 0 else "🔴"
        pnl_n_icon = "🟢" if pnl_net  >= 0 else "🔴"

        lines += [
            f"### {asset['name']} `{ticker}`",
            "",
            f"| Cours | Variation | VM | P&L Brut | P&L Net | Score | Recomm. |",
            f"|-------|-----------|-----|----------|---------|-------|---------|",
            f"| {price_eur:.2f} € | {chg_arrow} {chg:+.2f}% | {vm:.2f} € "
            f"| {pnl_b_icon} {pnl_brut:+.2f} € ({pnl_brut_p:+.1f}%) "
            f"| {pnl_n_icon} {pnl_net:+.2f} € ({pnl_net_p:+.1f}%) "
            f"| **{total_score:.1f}/10** | {rec} |",
            "",
        ]

        if chart_ok:
            lines += [f"![Historique {asset['name']}]({chart_rel_path})", ""]

        lines += [
            f"**📰 Actualités récentes :**",
            "",
        ]
        for t in news:
            if t: lines.append(f"- {t}")
        if not news:
            lines.append("- *Aucune actualité disponible*")

        lines += [
            "",
            f"**🧠 Sentiment :** Bull {bull:.0f}% / Bear {bear:.0f}% *(source : {sent_src})*",
            f"**📊 Consensus :** {cons_str} *(source : {cons_src})*",
            "",
            f"**📈 Momentum mensuel :** {h_label} "
            f"(1M: {ret_1m:+.1f}% / 3M: {ret_3m:+.1f}% / 6M: {ret_6m:+.1f}%) "
            f"*(source : {h_src})*",
            "",
            f"**💡 Justification :** "
            f"{justification(asset['name'], pnl_net, pnl_net_p, cs, bull, bear, cons_str, macro_score, h_score, h_label, total_score)}",
            "",
            "---",
            "",
        ]

        total_cout    += cout
        total_vm      += vm
        total_pnl_brut += pnl_brut
        total_pnl_net  += pnl_net

        history_rows.append({
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
            "ticker": ticker, "name": asset["name"],
            "price_eur": price_eur, "cost_eur": cost,
            "qty": qty, "vm": vm,
            "pnl_brut": pnl_brut, "pnl_brut_pct": pnl_brut_p,
            "pnl_net": pnl_net, "pnl_net_pct": pnl_net_p,
            "score": total_score, "rec": rec,
        })
        summaries.append({
            "name": asset["name"], "ticker": ticker,
            "vm": vm, "pnl_net": pnl_net, "pnl_net_p": pnl_net_p,
            "score": total_score, "rec": rec,
        })

    # ── Synthèse portefeuille ──────────────────────────────────────────────
    total_pnl_b_pct = round(total_pnl_brut / total_cout * 100, 2) if total_cout else 0
    total_pnl_n_pct = round(total_pnl_net  / total_cout * 100, 2) if total_cout else 0
    pf_icon = "🟢" if total_pnl_net >= 0 else "🔴"

    lines += [
        "## 💼 Synthèse Portefeuille", "",
        f"| Coût total | Valeur marché | P&L Brut | P&L Net |",
        f"|------------|---------------|----------|---------|",
        f"| {total_cout:.2f} € | {total_vm:.2f} € "
        f"| {pf_icon} {total_pnl_brut:+.2f} € ({total_pnl_b_pct:+.1f}%) "
        f"| {pf_icon} {total_pnl_net:+.2f} € ({total_pnl_n_pct:+.1f}%) |",
        "", "---", "",
        "### 🏆 Classement par Score", "",
        "| Valeur | VM | P&L Net | Score | Recomm. |",
        "|--------|----|---------|-------|---------|",
    ]
    for s in sorted(summaries, key=lambda x: x["score"], reverse=True):
        icon = "🟢" if s["pnl_net"] >= 0 else "🔴"
        lines.append(
            f"| {s['name']} | {s['vm']:.2f} € "
            f"| {icon} {s['pnl_net']:+.2f} € ({s['pnl_net_p']:+.1f}%) "
            f"| **{s['score']:.1f}/10** | {s['rec']} |"
        )

    # ── Watchlist ──────────────────────────────────────────────────────────
    lines += ["", "---", "", "## 👁️ Watchlist", ""]
    for w in WATCHLIST:
        w_price = None
        w_src   = "N/D"
        if w.get("marche") == "us" and w.get("ticker_td"):
            raw = td_prices.get(w["ticker_td"])
            if raw and raw > 0:
                w_price = round(raw * eur_usd, 2)
                w_src   = "TwelveData"
        if w_price is None and EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/real-time/{w['ticker_eod']}",
                             {"api_token": EODHD_KEY, "fmt": "json"}, "eodhd")
            if data and not _is_quota_error(err):
                raw = data.get("close") or data.get("previousClose")
                if raw and float(raw) > 0:
                    factor  = eur_usd if w.get("marche") == "us" else 1.0
                    w_price = round(float(raw) * factor, 2)
                    w_src   = "EODHD"
        # News watchlist US → Finnhub
        w_news = []
        if w.get("marche") == "us" and FINNHUB_KEY:
            from_d = str(date.today() - timedelta(days=7))
            to_d   = str(date.today())
            data, err = _get(f"{FH_BASE}/company-news",
                             {"symbol": w["ticker_fh"], "from": from_d,
                              "to": to_d, "token": FINNHUB_KEY}, "finnhub")
            if isinstance(data, list) and data and not _is_quota_error(err):
                w_news = [i.get("headline", "") for i in data[:2] if i.get("headline")]
        price_str = f"{w_price:.2f} €" if w_price else "N/D"
        lines += [
            f"**{w['name']}** `{w['ticker_fh']}` — {w['sector']} | Cours : {price_str} *(source : {w_src})*",
            "",
        ]
        for t in w_news:
            if t: lines.append(f"- {t}")
        if w_news:
            lines.append("")

    # ── Footer technique ───────────────────────────────────────────────────
    quota_str = " | ".join(f"{k}: {v}" for k, v in _quota_status().items())
    lines += [
        "", "---", "",
        "## ⚙️ Informations Techniques", "",
        f"**Quotas API :** {quota_str}",
        f"**Sources utilisées :** {json.dumps(sources_log, ensure_ascii=False)}",
        "",
    ]

    if divergence_log:
        lines += ["**⚠️ Journal des divergences :**", ""]
        for d in divergence_log:
            lines.append(f"- {d}")
        lines.append("")

    if cache_warnings:
        lines += ["**🗄️ Avertissements cache :**", ""]
        for w in cache_warnings:
            lines.append(f"- {w}")
        lines.append("")

    if api_errors:
        lines += ["**❌ Erreurs API :**", ""]
        for e in api_errors:
            lines.append(f"- {e}")
        lines.append("")

    lines += [
        f"*Rapport généré le {now.strftime('%d/%m/%Y à %H:%M')} (heure de Paris)*",
        f"*Charts générés : {len(charts_generated)}*",
    ]

    report_text = "\n".join(lines)
    os.makedirs("reports", exist_ok=True)
    with open("reports/daily_report.md", "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"[INFO] Rapport écrit : reports/daily_report.md")

    new_cache["sources_log"] = sources_log
    for row in history_rows:
        ticker = row["ticker"]
        h_data = asset_results.get(ticker, {})
        if h_data.get("h_dates") and h_data.get("h_closes"):
            new_cache[f"hist_{ticker}"] = {
                "dates":  h_data["h_dates"],
                "closes": h_data["h_closes"],
            }
    save_session_cache(new_cache)
    append_history(now, history_rows)

    return report_text, api_errors, cache_warnings


if __name__ == "__main__":
    report, errors, warnings = build_report()
    if errors:
        print(f"\n[WARN] {len(errors)} erreur(s) API détectée(s).")
    if warnings:
        print(f"[INFO] {len(warnings)} avertissement(s) cache.")
    print("[INFO] Terminé.")
