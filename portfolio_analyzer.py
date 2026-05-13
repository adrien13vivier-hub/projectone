#!/usr/bin/env python3
"""
Portfolio Analyzer v5.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARCHITECTURE DES CLÉS API v5.0
  Chaque clé est affectée à sa SPÉCIALITÉ pour minimiser la
  consommation journalière.

  ┌────────────────────┬────────────────────────────────────────────┐
  │ Clé API            │ Spécialité (usage primaire)                │
  ├────────────────────┼────────────────────────────────────────────┤
  │ TwelveData         │ Cours US en temps réel (batch unique)      │
  │ EODHD              │ Cours Euronext + historique mensuel + news │
  │ Finnhub            │ Sentiment analystes + consensus            │
  │ AlphaVantage       │ EUR/USD forex temps réel                   │
  └────────────────────┴────────────────────────────────────────────┘

  FALLBACK (si quota journalier dépassé ou API hors service) :
    → Lecture du dernier rapport connu : cache/session_cache.json
    → Si le cache lui-même est absent : valeur par défaut marquée
      ❌ DONNÉES ERRONÉES dans le rapport.
    → Toute donnée issue du cache est signalée dans le rapport
      avec la mention ⚠️ DONNÉE ISSUE DU CACHE et la date de sauvegarde.

  SUPPRESSIONS v5.0 :
    - Les sources ne sont plus affichées dans les cellules du tableau
      par valeur (cours, sentiment, consensus, historique).
    - Un seul bloc technique "🔧 Sources du run" en fin de rapport
      liste la source réelle utilisée pour chaque donnée.

Scoring v5.0 (inchangé) :
  Prix vs PRU       : 30 %
  Sentiment presse  : 20 %
  Consensus         : 20 %
  Historique mensuel: 30 %
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import csv
import json
import time
import requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# ─── CLÉS API ────────────────────────────────────────────────────────────────
FINNHUB_KEY      = os.environ.get("FINNHUB_API_KEY", "")
EODHD_KEY        = os.environ.get("EODHD_API_KEY", "")
TWELVEDATA_KEY   = os.environ.get("TWELVEDATA_API_KEY", "")
ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")

missing_keys = []
for k, v in [("FINNHUB_API_KEY", FINNHUB_KEY), ("EODHD_API_KEY", EODHD_KEY),
             ("TWELVEDATA_API_KEY", TWELVEDATA_KEY), ("ALPHAVANTAGE_API_KEY", ALPHAVANTAGE_KEY)]:
    if not v:
        missing_keys.append(k)
if missing_keys:
    # Avertissement mais pas de crash : on bascule sur le cache
    print(f"[WARN] Clés manquantes : {', '.join(missing_keys)} — fallback cache activé")

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

# ─── PORTEFEUILLE ─────────────────────────────────────────────────────────────
PORTFOLIO = [
    {"name": "Palantir Technologies", "isin": "US69608A1088",
     "ticker_fh": "PLTR",    "ticker_eod": "PLTR.US",  "ticker_td": "PLTR",
     "ticker_av": "PLTR",
     "qty": 2,  "cost_eur": 119.06, "marche": "us"},
    {"name": "CoreWeave",             "isin": "US21873S1087",
     "ticker_fh": "CRWV",    "ticker_eod": "CRWV.US",  "ticker_td": "CRWV",
     "ticker_av": "CRWV",
     "qty": 2,  "cost_eur": 93.91,  "marche": "us"},
    {"name": "Riot Platforms",        "isin": "US7672921050",
     "ticker_fh": "RIOT",    "ticker_eod": "RIOT.US",  "ticker_td": "RIOT",
     "ticker_av": "RIOT",
     "qty": 6,  "cost_eur": 15.84,  "marche": "us"},
    {"name": "JCDecaux",              "isin": "FR0000077919",
     "ticker_fh": "DEC.PA",  "ticker_eod": "DEC.PA",   "ticker_td": None,
     "ticker_av": "DEC.PAR",
     "qty": 2,  "cost_eur": 17.77,  "marche": "euronext"},
    {"name": "Crédit Agricole SA",    "isin": "FR0000045072",
     "ticker_fh": "ACA.PA",  "ticker_eod": "ACA.PA",   "ticker_td": None,
     "ticker_av": "ACA.PAR",
     "qty": 10, "cost_eur": 16.90,  "marche": "euronext"},
    {"name": "Abionyx Pharma",        "isin": "FR0012616852",
     "ticker_fh": "ABNX.PA", "ticker_eod": "ABNX.PA",  "ticker_td": None,
     "ticker_av": "ABNX.PAR",
     "qty": 10, "cost_eur": 3.84,   "marche": "euronext"},
]

INDICES = {
    "S&P 500":    {"eod": "GSPC.INDX", "fh": "^GSPC"},
    "CAC 40":     {"eod": "FCHI.INDX", "fh": "^FCHI"},
    "Nikkei 225": {"eod": "N225.INDX", "fh": "^N225"},
}

WATCHLIST = [
    {"name": "NVIDIA",        "ticker_fh": "NVDA",   "ticker_eod": "NVDA.US", "ticker_td": "NVDA",  "ticker_av": "NVDA",    "marche": "us",       "sector": "IA / Semi-conducteurs"},
    {"name": "Microsoft",     "ticker_fh": "MSFT",   "ticker_eod": "MSFT.US", "ticker_td": "MSFT",  "ticker_av": "MSFT",    "marche": "us",       "sector": "IA / Cloud"},
    {"name": "Coinbase",      "ticker_fh": "COIN",   "ticker_eod": "COIN.US", "ticker_td": "COIN",  "ticker_av": "COIN",    "marche": "us",       "sector": "Crypto / Fintech"},
    {"name": "LVMH",          "ticker_fh": "MC.PA",  "ticker_eod": "MC.PA",   "ticker_td": None,    "ticker_av": "MC.PAR",  "marche": "euronext", "sector": "Luxe / Consommation"},
    {"name": "TotalEnergies", "ticker_fh": "TTE.PA", "ticker_eod": "TTE.PA",  "ticker_td": None,    "ticker_av": "TTE.PAR", "marche": "euronext", "sector": "Énergie"},
    {"name": "Airbus",        "ticker_fh": "AIR.PA", "ticker_eod": "AIR.PA",  "ticker_td": None,    "ticker_av": "AIR.PAR", "marche": "euronext", "sector": "Aéronautique / Défense"},
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
            data = json.load(f)
        # On accepte n'importe quelle date (pas seulement aujourd'hui)
        # pour que le fallback fonctionne si les APIs sont toutes down
        return data
    except Exception:
        return {}

def save_session_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    cache["date"]     = str(date.today())
    cache["saved_at"] = datetime.now(PARIS_TZ).strftime("%d/%m/%Y %H:%M")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# COUCHE HTTP
# ══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict, timeout: int = 10) -> tuple:
    """Retourne (data, erreur_str|None)."""
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json(), None
        return None, f"HTTP {r.status_code}"
    except requests.exceptions.Timeout:
        return None, "Timeout"
    except requests.exceptions.ConnectionError:
        return None, "Connexion impossible"
    except Exception as e:
        return None, str(e)[:60]


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
# ① EUR/USD — SPÉCIALITÉ : Alpha Vantage  (CURRENCY_EXCHANGE_RATE)
#    Quota AV gratuit : ~500 req/jour, 5 req/min → 1 appel/run = ✅ parfait
#    Fallback 1 : TwelveData  (8 crédits/min plan free)
#    Fallback 2 : Finnhub     (60 appels/min plan free)
#    Fallback 3 : EODHD       (100 000 req/mois)
#    Fallback 4 : cache session
# ══════════════════════════════════════════════════════════════════════════════

def get_eur_usd(session_cache: dict) -> tuple:
    """
    Retourne (eur_usd_ratio, source_str, note|None).
    eur_usd_ratio = combien d'EUR pour 1 USD → price_usd * ratio = price_eur.
    """
    errors = []

    # ① Alpha Vantage (spécialiste forex)
    if ALPHAVANTAGE_KEY:
        data, err = _get(AV_BASE, {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": "USD",
            "to_currency":   "EUR",
            "apikey": ALPHAVANTAGE_KEY,
        })
        if isinstance(data, dict):
            rate_info = data.get("Realtime Currency Exchange Rate", {})
            rate_str  = rate_info.get("5. Exchange Rate")
            if rate_str:
                try:
                    return float(rate_str), "AlphaVantage", None
                except ValueError:
                    pass
            if data.get("Note") or data.get("Information"):
                errors.append("AlphaVantage:quota")
            else:
                errors.append(f"AlphaVantage:{err or 'vide'}")
        else:
            errors.append(f"AlphaVantage:{err or 'vide'}")
    else:
        errors.append("AlphaVantage:clé absente")

    # Fallback 1 : TwelveData
    if TWELVEDATA_KEY:
        data, err = _get(f"{TD_BASE}/price", {"symbol": "EUR/USD", "apikey": TWELVEDATA_KEY})
        if data and data.get("price"):
            try:
                return round(1 / float(data["price"]), 6), "TwelveData", None
            except Exception:
                pass
        errors.append(f"TwelveData:{err or 'vide'}")

    # Fallback 2 : Finnhub
    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/forex/rates", {"base": "USD", "token": FINNHUB_KEY})
        if data and data.get("quote", {}).get("EUR"):
            return float(data["quote"]["EUR"]), "Finnhub", None
        errors.append(f"Finnhub:{err or 'vide'}")

    # Fallback 3 : EODHD
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/real-time/EURUSD.FOREX",
                         {"api_token": EODHD_KEY, "fmt": "json"})
        if data and data.get("close"):
            try:
                return round(1 / float(data["close"]), 6), "EODHD", None
            except Exception:
                pass
        errors.append(f"EODHD:{err or 'vide'}")

    # Fallback 4 : cache session
    if session_cache.get("eur_usd"):
        saved_at = session_cache.get("saved_at", "date inconnue")
        return (session_cache["eur_usd"],
                f"CACHE ({saved_at})",
                f"⚠️ EUR/USD issu du cache — APIs indisponibles : {', '.join(errors)}")

    return (0.92, "DÉFAUT 0.92",
            f"❌ EUR/USD erroné — aucune source disponible : {', '.join(errors)}")


# ══════════════════════════════════════════════════════════════════════════════
# ② COURS US — SPÉCIALITÉ : TwelveData  (batch unique = ~1 crédit par ticker)
#    Plan free TwelveData : 800 crédits/jour → 9 tickers = 9 crédits ✅
#    Fallback : EODHD (real-time US)
#    Fallback 2 : cache session
# ══════════════════════════════════════════════════════════════════════════════

_td_cache: dict  = {}
_td_last_call: float = 0.0
_td_errors: dict = {}

def td_fetch_batch(tickers: list) -> dict:
    global _td_last_call
    to_fetch = [t for t in tickers if t and t not in _td_cache]
    if not to_fetch:
        return {t: _td_cache.get(t) for t in tickers if t}

    elapsed = time.time() - _td_last_call
    if elapsed < 10 and _td_last_call > 0:
        time.sleep(10 - elapsed)

    results = {}
    for i in range(0, len(to_fetch), 6):
        batch = to_fetch[i:i+6]
        data, err = _get(f"{TD_BASE}/price",
                         {"symbol": ",".join(batch), "apikey": TWELVEDATA_KEY})
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
                        _td_errors[ticker] = "Valeur non numérique"
                else:
                    results[ticker] = None
                    _td_errors[ticker] = (item.get("message", err or "vide")
                                          if isinstance(item, dict) else (err or "vide"))
        else:
            for ticker in batch:
                results[ticker] = None
                _td_errors[ticker] = err or "Réponse invalide"

        if i + 6 < len(to_fetch):
            time.sleep(12)

    for t in tickers:
        if t and t not in results:
            results[t] = _td_cache.get(t)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# ③ COURS EURONEXT + INDICES — SPÉCIALITÉ : EODHD
#    Plan free EODHD : 100 000 req/mois ≈ 3 333/jour
#    Usage : 6 Euronext + 3 indices + 6 historiques + 6 news = ~21 appels ✅
#    Fallback cours EU : Finnhub
#    Fallback indices  : Finnhub
# ══════════════════════════════════════════════════════════════════════════════

def get_price_eur(asset: dict, eur_usd: float, td_prices: dict,
                  session_cache: dict) -> tuple:
    """
    Retourne (price_eur, chg_pct, source_str, div_note|None).
    source_str est utilisé uniquement dans le bloc technique en fin de rapport.
    """
    td_val = eod_val = None
    note   = None
    chg    = 0.0
    errors = []
    cache_key = f"price_{asset['ticker_eod']}"

    if asset["marche"] == "us":
        # ① TwelveData (spécialiste US)
        if TWELVEDATA_KEY:
            td_ticker = asset.get("ticker_td")
            td_raw    = td_prices.get(td_ticker) if td_ticker else None
            if td_raw and td_raw > 0:
                td_val = round(td_raw * eur_usd, 4)
            elif td_ticker:
                errors.append(f"TwelveData:{_td_errors.get(td_ticker, 'indisponible')}")
        else:
            errors.append("TwelveData:clé absente")

        # ② EODHD (fallback US)
        if EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                             {"api_token": EODHD_KEY, "fmt": "json"})
            if data:
                raw = data.get("close") or data.get("previousClose")
                if raw and float(raw) > 0:
                    chg     = float(data.get("change_p", 0.0))
                    eod_val = round(float(raw) * eur_usd, 4)
                else:
                    errors.append("EODHD:cours nul")
            else:
                errors.append(f"EODHD:{err}")

        if td_val and eod_val:
            final, note = cross_validate(td_val, "TwelveData", eod_val, "EODHD")
            return final, chg, ("TwelveData+EODHD" if not note else "Médiane TW/EOD"), note
        if td_val:  return td_val,  0.0, "TwelveData", None
        if eod_val: return eod_val, chg, "EODHD", None

        # ③ Finnhub (fallback US)
        if FINNHUB_KEY:
            data, err = _get(f"{FH_BASE}/quote",
                             {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
            if data and data.get("c") and float(data["c"]) > 0:
                return round(float(data["c"]) * eur_usd, 4), float(data.get("dp", 0.0)), "Finnhub", None
            errors.append(f"Finnhub:{err or 'vide'}")

    else:  # Euronext
        # ① EODHD (spécialiste Euronext)
        if EODHD_KEY:
            data, err = _get(f"{EOD_BASE}/real-time/{asset['ticker_eod']}",
                             {"api_token": EODHD_KEY, "fmt": "json"})
            if data:
                raw = data.get("close") or data.get("previousClose")
                if raw and float(raw) > 0:
                    chg     = float(data.get("change_p", 0.0))
                    eod_val = round(float(raw), 4)
                else:
                    errors.append("EODHD:cours nul")
            else:
                errors.append(f"EODHD:{err}")
        else:
            errors.append("EODHD:clé absente")

        # ② Finnhub (fallback EU)
        if FINNHUB_KEY:
            data, err = _get(f"{FH_BASE}/quote",
                             {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
            if data and data.get("c") and float(data["c"]) > 0:
                fh_val = round(float(data["c"]), 4)
                if eod_val:
                    final, note = cross_validate(eod_val, "EODHD", fh_val, "Finnhub")
                    return final, chg, ("EODHD+Finnhub" if not note else "Médiane EOD/FH"), note
                return fh_val, float(data.get("dp", 0.0)), "Finnhub", None
            else:
                errors.append(f"Finnhub:{err or 'vide'}")

        if eod_val:
            return eod_val, chg, "EODHD", None

    # Fallback universel : cache session
    if session_cache.get(cache_key):
        saved_at = session_cache.get("saved_at", "date inconnue")
        return (session_cache[cache_key], 0.0,
                f"CACHE ({saved_at})",
                f"⚠️ Cours issu du cache GitHub ({saved_at}) — {', '.join(errors)}")

    return None, 0.0, f"INDISPONIBLE ({', '.join(errors)})", None


# ══════════════════════════════════════════════════════════════════════════════
# ④ INDICES MACRO — SPÉCIALITÉ : EODHD
# ══════════════════════════════════════════════════════════════════════════════

def get_index(symbols: dict) -> dict:
    # ① EODHD
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/real-time/{symbols['eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json"})
        if data and (data.get("close") or data.get("previousClose")):
            return {"price":      float(data.get("close") or data.get("previousClose", 0)),
                    "change_pct": float(data.get("change_p", 0.0)),
                    "source":     "EODHD"}
        eod_err = err or "vide"
    else:
        eod_err = "clé absente"

    # ② Finnhub (fallback)
    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/quote",
                         {"symbol": symbols["fh"], "token": FINNHUB_KEY})
        if data and data.get("c"):
            return {"price":      float(data["c"]),
                    "change_pct": float(data.get("dp", 0.0)),
                    "source":     "Finnhub"}
        fh_err = err or "vide"
    else:
        fh_err = "clé absente"

    return {"price": 0.0, "change_pct": 0.0,
            "source": f"❌ INDISPONIBLE (EODHD:{eod_err}, Finnhub:{fh_err})"}


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ NEWS — SPÉCIALITÉ : EODHD
# ══════════════════════════════════════════════════════════════════════════════

_news_cache: dict = {}

def get_company_news(asset: dict, n: int = 2) -> list:
    key = asset["ticker_eod"]
    if key in _news_cache:
        return _news_cache[key][:n]
    from_d = str(date.today() - timedelta(days=7))
    to_d   = str(date.today())
    if EODHD_KEY:
        data, _ = _get(f"{EOD_BASE}/news",
                       {"s": asset["ticker_eod"], "limit": max(n, 10),
                        "from": from_d, "api_token": EODHD_KEY, "fmt": "json"})
        if isinstance(data, list) and data:
            titles = [i.get("title", "") for i in data if i.get("title")]
            _news_cache[key] = titles
            return titles[:n]
    if FINNHUB_KEY:
        data, _ = _get(f"{FH_BASE}/company-news",
                       {"symbol": asset["ticker_fh"], "from": from_d,
                        "to": to_d, "token": FINNHUB_KEY})
        if isinstance(data, list) and data:
            titles = [i.get("headline", "") for i in data if i.get("headline")]
            _news_cache[key] = titles
            return titles[:n]
    _news_cache[key] = []
    return []

def get_macro_news(n: int = 5) -> list:
    if EODHD_KEY:
        data, _ = _get(f"{EOD_BASE}/news",
                       {"t": "general", "limit": n, "api_token": EODHD_KEY, "fmt": "json"})
        if isinstance(data, list) and data:
            return [i.get("title", "") for i in data if i.get("title")]
    if FINNHUB_KEY:
        data, _ = _get(f"{FH_BASE}/news", {"category": "general", "token": FINNHUB_KEY})
        if isinstance(data, list) and data:
            return [i.get("headline", "") for i in data[:n] if i.get("headline")]
    return []


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ SENTIMENT — SPÉCIALITÉ : Finnhub  (news-sentiment endpoint dédié)
#    Plan free Finnhub : 60 req/min → 6 actifs + 6 watchlist = 12 appels ✅
#    Fallback : lexical sur cache news EODHD (0 appel supplémentaire)
# ══════════════════════════════════════════════════════════════════════════════

def get_sentiment(asset: dict) -> tuple:
    """
    Retourne (bull_pct, bear_pct, source_str).
    source_str réservé au bloc technique final.
    """
    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/news-sentiment",
                         {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
        if data and data.get("sentiment"):
            bull = float(data["sentiment"].get("bullishPercent", 0.5)) * 100
            bear = float(data["sentiment"].get("bearishPercent", 0.5)) * 100
            return round(bull, 1), round(bear, 1), "Finnhub"
        fh_err = err or "vide"
    else:
        fh_err = "clé absente"

    # Fallback : analyse lexicale sur news EODHD (0 appel supplémentaire)
    news = _news_cache.get(asset["ticker_eod"]) or get_company_news(asset, n=10)
    if news:
        bull_w = {"growth", "buy", "bullish", "surge", "record", "beat", "strong",
                  "gain", "up", "rise", "soar", "profit", "positive", "upgrade"}
        bear_w = {"loss", "sell", "bearish", "drop", "miss", "weak", "cut", "down",
                  "fall", "decline", "risk", "negative", "downgrade", "warn"}
        words = " ".join(news).lower().split()
        b = sum(1 for w in words if w in bull_w)
        s = sum(1 for w in words if w in bear_w)
        t = b + s or 1
        return round(b/t*100, 1), round(s/t*100, 1), f"Finnhub indispo ({fh_err}) → lexical EODHD"

    return (50.0, 50.0,
            f"❌ Indisponible (Finnhub:{fh_err}, aucune news EODHD)")


# ══════════════════════════════════════════════════════════════════════════════
# ⑦ CONSENSUS — SPÉCIALITÉ : Finnhub  (/stock/recommendation)
#    Plan free Finnhub : 60 req/min → 6 actifs = 6 appels ✅
#    Fallback : EODHD fundamentals (AnalystRatings)
# ══════════════════════════════════════════════════════════════════════════════

def get_consensus(asset: dict) -> tuple:
    """
    Retourne (score/10, detail_str, source_str).
    source_str réservé au bloc technique final.
    """
    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/stock/recommendation",
                         {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY})
        if isinstance(data, list) and data:
            r  = data[0]
            sb = r.get("strongBuy", 0); b = r.get("buy", 0)
            h  = r.get("hold", 0);      s = r.get("sell", 0); ss = r.get("strongSell", 0)
            total = sb + b + h + s + ss
            if total > 0:
                score = (sb*10 + b*7.5 + h*5 + s*2.5) / total
                return round(score, 2), f"SB:{sb} B:{b} H:{h} S:{s} SS:{ss}", "Finnhub"
        fh_err = err or "vide"
    else:
        fh_err = "clé absente"

    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/fundamentals/{asset['ticker_eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json", "filter": "AnalystRatings"})
        if isinstance(data, dict) and data.get("Rating"):
            rat   = data["Rating"]
            label = str(rat.get("Rating", "")).lower()
            tp    = rat.get("TargetPrice", "N/D")
            m     = {"strong buy": 9.0, "buy": 7.5, "hold": 5.0,
                     "sell": 2.5, "strong sell": 0.5}
            score = m.get(label, 5.0)
            return score, f"Rating:{rat.get('Rating','?')} TP:{tp}$", f"Finnhub indispo ({fh_err}) → EODHD"
        eod_err = err or "vide"
    else:
        eod_err = "clé absente"

    return (5.0, "Consensus indisponible",
            f"❌ Indisponible (Finnhub:{fh_err}, EODHD:{eod_err})")


# ══════════════════════════════════════════════════════════════════════════════
# ⑧ HISTORIQUE MENSUEL — SPÉCIALITÉ : EODHD  (eod mensuel ajusté)
#    6 actifs × 1 appel = 6 appels/run ✅
#    Fallback : Finnhub candles hebdo
#    Fallback 2 : cache session
# ══════════════════════════════════════════════════════════════════════════════

def get_monthly_history(asset: dict, eur_usd: float, months: int = 6) -> tuple:
    """
    Retourne (dates_list, prices_eur_list, source_str, error_str|None).
    source_str réservé au bloc technique final.
    """
    from_d = str(date.today() - timedelta(days=months * 31))
    to_d   = str(date.today())
    cache_key = f"hist_{asset['ticker_eod']}"

    # ① EODHD EOD mensuel
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/eod/{asset['ticker_eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json",
                          "period": "m", "from": from_d, "to": to_d})
        if isinstance(data, list) and len(data) >= 2:
            dates  = [d["date"] for d in data if d.get("adjusted_close") or d.get("close")]
            closes = [float(d.get("adjusted_close") or d.get("close", 0)) for d in data
                      if d.get("adjusted_close") or d.get("close")]
            if asset["marche"] == "us":
                closes = [round(c * eur_usd, 2) for c in closes]
            return dates, closes, "EODHD", None
        eod_err = err or "vide"
    else:
        eod_err = "clé absente"

    # ② Finnhub candles hebdo → agrégés en mois
    if FINNHUB_KEY:
        from_ts = int((datetime.now() - timedelta(days=months * 31)).timestamp())
        to_ts   = int(datetime.now().timestamp())
        data, err = _get(f"{FH_BASE}/stock/candle",
                         {"symbol": asset["ticker_fh"], "resolution": "W",
                          "from": from_ts, "to": to_ts, "token": FINNHUB_KEY})
        if isinstance(data, dict) and data.get("s") == "ok" and data.get("c"):
            monthly: dict = {}
            for ts, cl in zip(data["t"], data["c"]):
                month_key = datetime.fromtimestamp(ts).strftime("%Y-%m")
                monthly[month_key] = cl
            dates  = sorted(monthly.keys())
            closes = [round(monthly[k] * eur_usd, 2)
                      if asset["marche"] == "us" else round(monthly[k], 2)
                      for k in dates]
            return dates, closes, "Finnhub (candles hebdo)", None
        fh_err = err or "vide"
    else:
        fh_err = "clé absente"

    # ③ Cache session
    if session_cache_global.get(cache_key):
        saved_at = session_cache_global.get("saved_at", "date inconnue")
        cached   = session_cache_global[cache_key]
        return (cached.get("dates", []), cached.get("closes", []),
                f"CACHE ({saved_at})",
                f"⚠️ Historique issu du cache GitHub ({saved_at})")

    return ([], [],
            f"❌ Indisponible (EODHD:{eod_err}, Finnhub:{fh_err})",
            "Historique indisponible")


# Variable globale pour que get_monthly_history puisse accéder au cache
session_cache_global: dict = {}


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


def generate_monthly_chart(asset: dict, dates: list, closes: list,
                            cost_eur: float, chart_path: str) -> bool:
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
        ax.plot(dt_dates, closes, color=line_color, linewidth=2.5, marker="o", markersize=5, zorder=3)
        ax.fill_between(dt_dates, closes, min(closes) * 0.97, alpha=0.18, color=fill_color)
        ax.axhline(y=cost_eur, color="#6b7280", linestyle="--", linewidth=1.2, alpha=0.8,
                   label=f"PRU : {cost_eur:.2f} €")
        ax.annotate(f"{closes[0]:.2f}€", (dt_dates[0], closes[0]),
                    textcoords="offset points", xytext=(-10, 8), fontsize=8, color="#374151")
        ax.annotate(f"{closes[-1]:.2f}€\n({perf:+.1f}%)", (dt_dates[-1], closes[-1]),
                    textcoords="offset points", xytext=(8, 0), fontsize=9,
                    fontweight="bold", color=line_color)
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
        plt.savefig(chart_path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return True
    except Exception as e:
        print(f"[WARN] Graphique {asset['name']} non généré : {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# SCORING & RECOMMANDATION
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
# RAPPORT PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def build_report() -> tuple:
    global session_cache_global
    now            = datetime.now(PARIS_TZ)
    lines          = []
    divergence_log = []
    api_errors     = []
    cache_warnings = []   # données issues du cache → mentionnées dans le rapport
    session_cache  = load_session_cache()
    session_cache_global = session_cache
    new_cache      = {}
    history_rows   = []
    charts_generated = []
    sources_log    = {}   # ticker → {cours, sentiment, consensus, historique}

    print("[INFO] Batch TwelveData (cours US)...")
    us_tickers = [a["ticker_td"] for a in PORTFOLIO if a.get("ticker_td")]
    watch_td   = [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    td_prices  = td_fetch_batch(list(set(us_tickers + watch_td))) if TWELVEDATA_KEY else {}

    print("[INFO] EUR/USD (AlphaVantage)...")
    eur_usd, eurusd_src, eurusd_note = get_eur_usd(session_cache)
    if eurusd_note:
        if "❌" in eurusd_note:
            api_errors.append(f"EUR/USD : {eurusd_src}")
        else:
            cache_warnings.append(eurusd_note)
        divergence_log.append(f"EUR/USD : {eurusd_note}")
    new_cache["eur_usd"] = eur_usd
    sources_log["EUR/USD"] = eurusd_src

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
        f"# 📊 Rapport de Portefeuille v5.0 — {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
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

    for asset in PORTFOLIO:
        print(f"[INFO] {asset['name']}...")
        news = get_company_news(asset, 2)
        price_eur, chg, price_src, div_note = get_price_eur(
            asset, eur_usd, td_prices, session_cache)
        sources_log[asset["ticker_eod"]] = {"cours": price_src}

        if div_note:
            divergence_log.append(f"{asset['name']} : {div_note}")
        if price_src and "CACHE" in price_src:
            cache_warnings.append(f"{asset['name']} — cours : {div_note or price_src}")
        if price_src and "INDISPONIBLE" in price_src:
            api_errors.append(f"{asset['name']} cours : {price_src}")

        if price_eur is None:
            lines += [
                f"### ❌ {asset['name']} `{asset['ticker_eod']}`",
                "",
                "> **❌ Cours totalement indisponible** — aucune source ni cache",
                "", "---", "",
            ]
            api_errors.append(f"{asset['name']} : cours totalement indisponible")
            continue

        new_cache[f"price_{asset['ticker_eod']}"] = price_eur

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

        bull, bear, sent_src = get_sentiment(asset)
        sources_log[asset["ticker_eod"]]["sentiment"] = sent_src
        if "❌" in sent_src:
            api_errors.append(f"{asset['name']} sentiment : {sent_src}")

        cs, cons_str, cons_src = get_consensus(asset)
        sources_log[asset["ticker_eod"]]["consensus"] = cons_src
        if "❌" in cons_src:
            api_errors.append(f"{asset['name']} consensus : {cons_str}")

        print(f"[INFO] Historique {asset['name']} (EODHD)...")
        h_dates, h_closes, h_src, h_err = get_monthly_history(asset, eur_usd)
        sources_log[asset["ticker_eod"]]["historique"] = h_src
        if h_err:
            if "CACHE" in h_src:
                cache_warnings.append(f"{asset['name']} — historique : {h_err}")
            else:
                api_errors.append(f"{asset['name']} historique : {h_src}")
        else:
            # Sauvegarde de l'historique dans le cache pour les prochains fallbacks
            new_cache[f"hist_{asset['ticker_eod']}"] = {
                "dates":  h_dates,
                "closes": h_closes,
            }

        hist_score, hist_label, ret_1m, ret_3m, ret_6m = score_history(h_dates, h_closes)

        chart_filename = f"{CHARTS_DIR}/{asset['ticker_eod'].replace('.', '_')}_monthly.png"
        chart_ok = generate_monthly_chart(asset, h_dates, h_closes, cost, chart_filename)
        if chart_ok:
            charts_generated.append(chart_filename)

        ps          = score_price(price_eur, cost)
        sent_score  = bull / 100 * 10
        total_score = round(ps * 0.30 + sent_score * 0.20 + cs * 0.20 + hist_score * 0.30, 2)
        rec         = recommend(total_score)
        news_str    = news[0] if news else "Aucune actualité récente."
        justif      = justification(asset["name"], pnl_net, pnl_net_p,
                                    (sent_score + cs) / 2, bull, bear, cons_str,
                                    macro_score, hist_score, hist_label, total_score)

        total_cout     += cout
        total_vm       += vm
        total_pnl_brut += pnl_brut
        total_pnl_net  += pnl_net
        summaries.append({"name": asset["name"], "score": total_score,
                          "pnl_brut_pct": pnl_brut_p, "pnl_net": pnl_net})

        history_rows.append({
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
            "ticker": asset["ticker_eod"], "name": asset["name"],
            "price_eur": price_eur, "cost_eur": cost, "qty": qty,
            "vm": vm, "pnl_brut": pnl_brut, "pnl_brut_pct": pnl_brut_p,
            "pnl_net": pnl_net, "pnl_net_pct": pnl_net_p,
            "score": total_score,
            "rec": rec.replace("🟢","").replace("🔵","").replace("🟡","")
                      .replace("🟠","").replace("🔴","").strip(),
        })

        icon      = "📗" if pnl_brut >= 0 else "📕"
        chart_ref = f"\n\n![Historique mensuel]({chart_filename})" if chart_ok else ""
        cache_flag = " _(⚠️ donnée issue du cache)_" if price_src and "CACHE" in price_src else ""
        hist_cache_flag = " _(⚠️ données issues du cache)_" if h_err and h_err and "CACHE" in h_src else ""

        lines += [
            f"### {icon} {asset['name']} `{asset['ticker_eod']}`",
            "",
            "| Champ | Valeur |",
            "|-------|--------|",
            f"| **Cours actuel** | {price_eur:.2f} € ({chg:+.2f}%){cache_flag} |",
            f"| **Prix de revient** | {cost:.2f} € · Coût total {cout:.2f} € |",
            f"| **Frais achat payés** | {fee_a:.2f} € · Coût réel {cout_reel:.2f} € |",
            f"| **Valeur marché** | {vm:.2f} € |",
            f"| **PnL brut latent** | {pnl_brut:+.2f} € ({pnl_brut_p:+.2f}%) |",
            f"| **Frais vente estimés** | {fee_v:.2f} € |",
            f"| **PnL net si vente** | {pnl_net:+.2f} € ({pnl_net_p:+.2f}%) |",
            f"| **Sentiment presse** | Bull {bull:.0f}% / Bear {bear:.0f}% |",
            f"| **Consensus analystes** | {cons_str} |",
            f"| **Historique mensuel** | Ret. 1M {ret_1m:+.1f}% \u00b7 3M {ret_3m:+.1f}% \u00b7 6M {ret_6m:+.1f}%{hist_cache_flag} |",
            f"| **Score** | {total_score:.1f}/10 (Prix {ps:.1f}·30% + Sent {sent_score:.1f}·20% + Cons {cs:.1f}·20% + Hist {hist_score:.1f}·30%) |",
            "",
            f"📰 **Actualité :** {news_str}",
            chart_ref,
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

    # ── Avertissements cache (données anciennes) ───────────────────────────
    if cache_warnings:
        lines += [
            "## ⚠️ Données Issues du Cache",
            "",
            "> Ces données proviennent du **dernier rapport sauvegardé sur GitHub** (cache session).",
            "> Les APIs correspondantes étaient indisponibles lors de ce run.",
            "> **Ne pas prendre de décision d'investissement** sur ces valeurs sans vérification manuelle.",
            "",
        ]
        for w in cache_warnings:
            lines.append(f"- ⚠️ {w}")
        lines += ["", "---", ""]

    # ── Validation croisée ─────────────────────────────────────────────────
    real_divs = [d for d in divergence_log if "⚠️ Divergence" in d]
    if real_divs:
        lines += ["## ⚠️ Validation Croisée", "",
                  "_Divergences > 2% détectées — médiane utilisée :_", ""]
        for d in real_divs:
            lines.append(f"- {d}")
        lines += ["", "---", ""]
    else:
        lines += ["## ✅ Validation Croisée", "",
                  "_Aucune divergence > 2% détectée entre sources._",
                  "", "---", ""]

    # ── Erreurs API ────────────────────────────────────────────────────────
    if api_errors:
        lines += [
            "## 🔴 Erreurs API",
            "",
            "> ⚠️ **Les données suivantes sont indisponibles pour ce run.**",
            "> Vérifiez les APIs concernées avant toute décision.",
            "",
        ]
        for e in api_errors:
            lines.append(f"- ❌ {e}")
        lines += ["", "---", ""]
    else:
        lines += ["## ✅ APIs", "",
                  "_Toutes les sources ont répondu correctement._",
                  "", "---", ""]

    # ── Conclusion stratégique ─────────────────────────────────────────────
    best  = max(summaries, key=lambda x: x["score"]) if summaries else None
    worst = min(summaries, key=lambda x: x["score"]) if summaries else None
    ctx   = ("Marchés en dynamique **positive**." if macro_score >= 6
             else "Marchés sous **pression baissière**." if macro_score <= 4
             else "Marchés en phase **neutre**.")
    lines += ["## 🧭 Conclusion Stratégique", "", ctx, ""]
    if best and worst:
        lines += [
            f"**Meilleure position :** {best['name']} (score {best['score']:.1f}/10, PnL brut {best['pnl_brut_pct']:+.1f}%)",
            f"**Position à surveiller :** {worst['name']} (score {worst['score']:.1f}/10, PnL net {worst['pnl_net']:+.2f} €)",
            "",
        ]

    lines += [
        "### 🔭 Watchlist — Top 3 Valeurs Hors Portefeuille",
        "",
        "| Valeur | Secteur | Cours | Var. | Sentiment | Consensus | Score |",
        "|--------|---------|-------|------|-----------|-----------|-------|",
    ]
    watch_res = []
    for w in WATCHLIST:
        pe, chg, src, _ = get_price_eur(w, eur_usd, td_prices, session_cache)
        if not pe:
            continue
        get_company_news(w, n=10)
        bull, bear, _   = get_sentiment(w)
        cs, cons_str, _ = get_consensus(w)
        sc = round((bull / 100 * 10 + cs) / 2, 2)
        watch_res.append({"name": w["name"], "sector": w["sector"],
                          "price": pe, "chg": chg, "sc": sc,
                          "bull": bull, "cons": cons_str})
    watch_res.sort(key=lambda x: x["sc"], reverse=True)
    for w in watch_res[:3]:
        arr = "▲" if w["chg"] > 0 else "▼"
        lines.append(
            f"| **{w['name']}** | {w['sector']} | {w['price']:.2f} € "
            f"| {arr} {w['chg']:+.2f}% | Bull {w['bull']:.0f}% "
            f"| {w['cons']} | {w['sc']:.1f}/10 |"
        )

    # ── Bloc technique (sources) — en bas, discret ─────────────────────────
    lines += [
        "", "---", "",
        "## 🔧 Sources du Run",
        "",
        "| Donnée | Source utilisée |",
        "|--------|----------------|",
        f"| EUR/USD | {sources_log.get('EUR/USD', '?')} |",
    ]
    for idx_name in INDICES:
        lines.append(f"| Indice {idx_name} | {sources_log.get(idx_name, '?')} |")
    for asset in PORTFOLIO:
        src_info = sources_log.get(asset["ticker_eod"], {})
        if isinstance(src_info, dict):
            c = src_info.get("cours", "?")
            s = src_info.get("sentiment", "?")
            k = src_info.get("consensus", "?")
            h = src_info.get("historique", "?")
            lines.append(f"| {asset['name']} — cours | {c} |")
            lines.append(f"| {asset['name']} — sentiment | {s} |")
            lines.append(f"| {asset['name']} — consensus | {k} |")
            lines.append(f"| {asset['name']} — historique | {h} |")

    lines += [
        "", "---", "",
        f"_Rapport v5.0 — {now.strftime('%d/%m/%Y à %H:%M')} Paris_",
        "_Architecture API : TwelveData (cours US) · EODHD (Euronext/indices/historique/news) · Finnhub (sentiment/consensus) · AlphaVantage (EUR/USD)_",
        "_Scoring : Prix 30% + Sentiment 20% + Consensus 20% + Historique 30%_",
        "_Frais courtage BoursoBank Découverte (brochure 13/11/2025)_",
    ]

    save_session_cache(new_cache)
    append_history(now, history_rows)

    return "\n".join(lines), total_pnl_net, tot_np, api_errors, charts_generated, cache_warnings


if __name__ == "__main__":
    result = build_report()
    report, pnl_net, pnl_pct, api_errors, charts, cache_warnings = result

    os.makedirs("reports", exist_ok=True)
    with open("reports/daily_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    env_file = os.environ.get("GITHUB_ENV", "")
    if env_file:
        has_errors    = "true" if api_errors else "false"
        has_cache     = "true" if cache_warnings else "false"
        errors_list   = " | ".join(api_errors[:5]) if api_errors else "Aucune"
        cache_list    = " | ".join(cache_warnings[:3]) if cache_warnings else "Aucune"
        charts_list   = ",".join(charts) if charts else ""
        with open(env_file, "a") as f:
            f.write(f"PORTFOLIO_PNL_NET={pnl_net:.2f}\n")
            f.write(f"PORTFOLIO_PNL_PCT={pnl_pct:.2f}\n")
            f.write(f"HAS_API_ERRORS={has_errors}\n")
            f.write(f"HAS_CACHE_DATA={has_cache}\n")
            f.write(f"API_ERRORS_SUMMARY={errors_list}\n")
            f.write(f"CACHE_WARNINGS={cache_list}\n")
            f.write(f"CHARTS_LIST={charts_list}\n")

    print(f"✅ Rapport v5.0 — PnL net : {pnl_net:+.2f} € ({pnl_pct:+.2f}%)")
    if cache_warnings:
        print(f"⚠️ {len(cache_warnings)} donnée(s) issue(s) du cache GitHub")
    if api_errors:
        print(f"❌ {len(api_errors)} erreur(s) API : {'; '.join(api_errors[:3])}")
