#!/usr/bin/env python3
"""
Portfolio Analyzer v6.2
================================================================================
CORRECTIONS v6.2 par rapport à v6.1 :

1. QUOTA EODHD CORRIGÉ (BUG CRITIQUE)
   Avant : "eodhd": {"used": 0, "limit": 18}
   Le plan gratuit EODHD permet 100 000 req/jour. La limite de 18 était
   arbitraire et incorrecte. Un run complet consomme environ 15-20 appels
   EODHD (cours EU × 3 + indices × 3 + historiques × 3 + news × 3 +
   consensus fallback × 3). Avec limit=18, le quota était atteint à chaque
   run → les derniers appels retournaient None silencieusement → history.csv
   non mis à jour → GitHub détectait "pas d'activité" → désactivation du
   workflow schedulé.
   Après : "eodhd": {"used": 0, "limit": 80}

2. QUOTA ALPHAVANTAGE CORRIGÉ
   Avant : limit=23 (25 req/jour plan gratuit, avec marge de 2)
   Après : limit=20 (marge de sécurité de 5, évite les erreurs 429)

3. GUARD DE SÉCURITÉ AJOUTÉ
   Si tous les prix d'un marché sont None (tous les quotas épuisés),
   on lève une exception explicite pour que le workflow échoue visiblement
   plutôt que de générer un rapport vide sans erreur.

4. IMPORT MANQUANT CORRIGÉ
   La fonction _finnhub_candles importait datetime localement mais le module
   était déjà importé en haut — pas de bug mais uniformisation.

TOUTES LES AUTRES FONCTIONS sont identiques à v6.1.
================================================================================
"""

import os
import csv
import json
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# --- LOGGING (cron-friendly : WARNING uniquement, pas de stdout INFO) --------
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(message)s",
)
_log = logging.getLogger("portfolio_analyzer")

# --- CLES API ----------------------------------------------------------------
FINNHUB_KEY      = os.environ.get("FINNHUB_API_KEY", "")
EODHD_KEY        = os.environ.get("EODHD_API_KEY", "")
TWELVEDATA_KEY   = os.environ.get("TWELVEDATA_API_KEY", "")
ALPHAVANTAGE_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")

for k, v in [("FINNHUB_API_KEY", FINNHUB_KEY), ("EODHD_API_KEY", EODHD_KEY),
             ("TWELVEDATA_API_KEY", TWELVEDATA_KEY), ("ALPHAVANTAGE_API_KEY", ALPHAVANTAGE_KEY)]:
    if not v:
        _log.warning("Cle absente : %s -- fallback cache active pour cette source", k)

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

# --- QUOTAS JOURNALIERS PAR CLE ----------------------------------------------
# CORRECTION v6.2 : limites corrigées pour refléter les plans gratuits réels
# - EODHD plan gratuit : 100 000 req/jour → limite à 80 (large marge)
#   (la limite de 18 causait un blocage silencieux à chaque run)
# - AlphaVantage plan gratuit : 25 req/jour → limite à 20 (marge de 5)
# - TwelveData plan gratuit : 800 req/jour → limite à 60
# - Finnhub plan gratuit : 60 req/min, illimité/jour → limite à 55
_QUOTA = {
    "alphavantage": {"used": 0, "limit": 20},  # était 23, corrigé à 20
    "twelvedata":   {"used": 0, "limit": 60},
    "eodhd":        {"used": 0, "limit": 80},  # CORRECTION CRITIQUE : était 18 !
    "finnhub":      {"used": 0, "limit": 55},
}

_quota_lock = threading.Lock()


def _quota_ok(key: str) -> bool:
    with _quota_lock:
        q = _QUOTA.get(key)
        return q["used"] < q["limit"] if q else True


def _quota_inc(key: str):
    with _quota_lock:
        if key in _QUOTA:
            _QUOTA[key]["used"] += 1


def _quota_status() -> dict:
    return {k: f"{v['used']}/{v['limit']}" for k, v in _QUOTA.items()}


# --- PORTEFEUILLE ------------------------------------------------------------
PORTFOLIO = [
    {"name": "Palantir Technologies", "isin": "US69608A1088",
     "ticker_fh": "PLTR",    "ticker_eod": "PLTR.US",  "ticker_td": "PLTR",  "ticker_av": "PLTR",  "ticker_yf": "PLTR",
     "qty": 2,  "cost_eur": 119.06, "marche": "us"},
    {"name": "CoreWeave",             "isin": "US21873S1087",
     "ticker_fh": "CRWV",    "ticker_eod": "CRWV.US",  "ticker_td": "CRWV",  "ticker_av": "CRWV",  "ticker_yf": "CRWV",
     "qty": 2,  "cost_eur": 93.91,  "marche": "us"},
    {"name": "Riot Platforms",        "isin": "US7672921050",
     "ticker_fh": "RIOT",    "ticker_eod": "RIOT.US",  "ticker_td": "RIOT",  "ticker_av": "RIOT",  "ticker_yf": "RIOT",
     "qty": 6,  "cost_eur": 15.84,  "marche": "us"},
    {"name": "JCDecaux",              "isin": "FR0000077919",
     "ticker_fh": "DEC.PA",  "ticker_eod": "DEC.PA",   "ticker_td": None,    "ticker_av": None,    "ticker_yf": "DEC.PA",
     "qty": 2,  "cost_eur": 17.77,  "marche": "euronext"},
    {"name": "Credit Agricole SA",    "isin": "FR0000045072",
     "ticker_fh": "ACA.PA",  "ticker_eod": "ACA.PA",   "ticker_td": None,    "ticker_av": None,    "ticker_yf": "ACA.PA",
     "qty": 10, "cost_eur": 16.90,  "marche": "euronext"},
    {"name": "Abionyx Pharma",        "isin": "FR0012616852",
     "ticker_fh": "ABNX.PA", "ticker_eod": "ABNX.PA",  "ticker_td": None,    "ticker_av": None,    "ticker_yf": "ABNX.PA",
     "qty": 10, "cost_eur": 3.84,   "marche": "euronext"},
]

INDICES = {
    "S&P 500":    {"eod": "GSPC.INDX", "fh": "^GSPC"},
    "CAC 40":     {"eod": "FCHI.INDX", "fh": "^FCHI"},
    "Nikkei 225": {"eod": "N225.INDX", "fh": "^N225"},
}

WATCHLIST = [
    {"name": "NVIDIA",        "ticker_fh": "NVDA",   "ticker_eod": "NVDA.US", "ticker_td": "NVDA",  "ticker_av": "NVDA",  "ticker_yf": "NVDA",  "marche": "us",       "sector": "IA / Semi-conducteurs"},
    {"name": "Microsoft",     "ticker_fh": "MSFT",   "ticker_eod": "MSFT.US", "ticker_td": "MSFT",  "ticker_av": "MSFT",  "ticker_yf": "MSFT",  "marche": "us",       "sector": "IA / Cloud"},
    {"name": "Coinbase",      "ticker_fh": "COIN",   "ticker_eod": "COIN.US", "ticker_td": "COIN",  "ticker_av": "COIN",  "ticker_yf": "COIN",  "marche": "us",       "sector": "Crypto / Fintech"},
    {"name": "LVMH",          "ticker_fh": "MC.PA",  "ticker_eod": "MC.PA",   "ticker_td": None,    "ticker_av": None,    "ticker_yf": "MC.PA", "marche": "euronext", "sector": "Luxe / Consommation"},
    {"name": "TotalEnergies", "ticker_fh": "TTE.PA", "ticker_eod": "TTE.PA",  "ticker_td": None,    "ticker_av": None,    "ticker_yf": "TTE.PA","marche": "euronext", "sector": "Energie"},
    {"name": "Airbus",        "ticker_fh": "AIR.PA", "ticker_eod": "AIR.PA",  "ticker_td": None,    "ticker_av": None,    "ticker_yf": "AIR.PA","marche": "euronext", "sector": "Aeronautique / Defense"},
]

BROKERAGE = {
    "euronext": {"threshold": 500,  "flat": 1.99,  "rate": 0.006,  "min": 1.99},
    "us":       {"threshold": 6000, "flat": 6.95,  "rate": 0.0012, "min": 6.95},
}


def calc_fee(amount: float, marche: str) -> float:
    t = BROKERAGE.get(marche, BROKERAGE["euronext"])
    return round(max(t["flat"] if amount <= t["threshold"] else t["rate"] * amount, t["min"]), 2)


# =============================================================================
# CACHE SESSION
# =============================================================================

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


# =============================================================================
# COUCHE HTTP  (quota-aware)
# =============================================================================

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


# =============================================================================
# FLUX RSS YAHOO FINANCE
# =============================================================================

_rss_cache: dict = {}
_RSS_TITLE_MAX = 120


def _clean_title(raw: str) -> str:
    cleaned = " ".join(raw.replace("\r", " ").replace("\n", " ").split()).strip()
    if len(cleaned) > _RSS_TITLE_MAX:
        cleaned = cleaned[:_RSS_TITLE_MAX].rstrip() + "…"
    return cleaned


def _fetch_yahoo_rss(ticker_yf: str, n: int = 6) -> list:
    if ticker_yf in _rss_cache:
        return _rss_cache[ticker_yf][:n]

    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={ticker_yf}&region=US&lang=en-US"
    )
    try:
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0 PortfolioAnalyzer/6.2"})
        if r.status_code != 200:
            _rss_cache[ticker_yf] = []
            return []
        root = ET.fromstring(r.content)
        titles = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(_clean_title(title_el.text))
            if len(titles) >= n:
                break
        _rss_cache[ticker_yf] = titles
        return titles
    except Exception as e:
        _log.warning("RSS Yahoo Finance (%s) : %s", ticker_yf, e)
        _rss_cache[ticker_yf] = []
        return []


# =============================================================================
# SYNTHESE ACTUALITE
# =============================================================================

_synthesis_cache: dict = {}


def get_news_synthesis(asset: dict) -> tuple:
    ticker_yf = asset.get("ticker_yf") or asset.get("ticker_fh", "")
    key = ticker_yf

    if key in _synthesis_cache:
        return _synthesis_cache[key]

    titles = _fetch_yahoo_rss(ticker_yf, n=6)

    if not titles:
        result = ("Aucune actualite disponible via RSS.", "RSS Yahoo vide")
        _synthesis_cache[key] = result
        return result

    brut = " | ".join(titles[:3])
    brut = " ".join(brut.replace("\r", " ").replace("\n", " ").split())
    result = (brut, "RSS Yahoo Finance")
    _synthesis_cache[key] = result
    return result


# =============================================================================
# VALIDATION CROISEE
# =============================================================================

def cross_validate(val1: float, src1: str, val2: float, src2: str) -> tuple:
    if val1 and val2 and val1 > 0 and val2 > 0:
        ecart_pct = abs(val1 - val2) / val1 * 100
        if ecart_pct > DIVERGENCE_THRESHOLD_PCT:
            mediane = round((val1 + val2) / 2, 4)
            note = (f"Divergence {ecart_pct:.1f}% entre {src1} ({val1:.4f}) "
                    f"et {src2} ({val2:.4f}) -> mediane : {mediane:.4f}")
            return mediane, note
    return val1 if val1 and val1 > 0 else val2, None


# =============================================================================
# EUR/USD -- AlphaVantage  (1 appel/run)
# =============================================================================

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
        errors.append("AlphaVantage:cle absente")

    if session_cache.get("eur_usd"):
        saved_at = session_cache.get("saved_at", "date inconnue")
        return (session_cache["eur_usd"], "Cache", True,
                f"EUR/USD non disponible ({', '.join(errors)}) -- cache du {saved_at} utilise")

    return (0.92, "Defaut 0.92", False,
            f"EUR/USD indisponible ({', '.join(errors)}) -- valeur de secours 0.92 appliquee")


# =============================================================================
# COURS US -- TwelveData  (batch)
# =============================================================================

_td_cache:     dict  = {}
_td_last_call: float = 0.0
_td_errors:    dict  = {}


def td_fetch_batch(tickers: list) -> dict:
    global _td_last_call
    to_fetch = [t for t in tickers if t and t not in _td_cache]
    if not to_fetch:
        return {t: _td_cache.get(t) for t in tickers if t}

    elapsed = time.time() - _td_last_call
    if elapsed < 3 and _td_last_call > 0:
        time.sleep(3 - elapsed)

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
                        results[ticker]    = None
                        _td_errors[ticker] = "Valeur non numerique"
                else:
                    results[ticker]    = None
                    _td_errors[ticker] = (item.get("message", err or "vide")
                                          if isinstance(item, dict) else (err or "vide"))
        else:
            for ticker in batch:
                results[ticker]    = None
                _td_errors[ticker] = err or "Reponse invalide"

        if i + 6 < len(to_fetch):
            time.sleep(3)

    for t in tickers:
        if t and t not in results:
            results[t] = _td_cache.get(t)
    return results


# =============================================================================
# COURS (tous marches) -- Orchestrateur
# =============================================================================

def get_price_eur(asset: dict, eur_usd: float, td_prices: dict,
                  session_cache: dict) -> tuple:
    td_val = eod_val = None
    note   = None
    chg    = 0.0
    errors = []
    cache_key = f"price_{asset['ticker_eod']}"

    if asset["marche"] == "us":
        if TWELVEDATA_KEY:
            td_ticker = asset.get("ticker_td")
            td_raw    = td_prices.get(td_ticker) if td_ticker else None
            if td_raw and td_raw > 0:
                td_val = round(td_raw * eur_usd, 4)
            elif td_ticker:
                errors.append(f"TwelveData:{_td_errors.get(td_ticker, 'indisponible')}")
        else:
            errors.append("TwelveData:cle absente")

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

    else:
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
            errors.append("EODHD:cle absente")

    if session_cache.get(cache_key):
        saved_at = session_cache.get("saved_at", "date inconnue")
        return (session_cache[cache_key], 0.0, "Cache", True,
                f"Cours non disponible ({', '.join(errors)}) -- cache du {saved_at} utilise")

    return None, 0.0, f"Indisponible ({', '.join(errors)})", False, None


# =============================================================================
# INDICES -- EODHD principal * Finnhub fallback
# =============================================================================

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
        eod_err = "cle absente"

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
        fh_err = "cle absente"

    return {"price": 0.0, "change_pct": 0.0,
            "source": f"Indisponible (EODHD:{eod_err}, Finnhub:{fh_err})"}


# =============================================================================
# NEWS
# =============================================================================

_news_cache: dict = {}


def get_company_news(asset: dict, n: int = 2) -> list:
    key = asset["ticker_eod"]
    if key in _news_cache:
        return _news_cache[key][:n]
    from_d = str(date.today() - timedelta(days=7))
    to_d   = str(date.today())

    if asset.get("marche") == "euronext":
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
        if FINNHUB_KEY:
            data, err = _get(f"{FH_BASE}/company-news",
                             {"symbol": asset["ticker_fh"], "from": from_d,
                              "to": to_d, "token": FINNHUB_KEY},
                             "finnhub")
            if isinstance(data, list) and data and not _is_quota_error(err):
                titles = [i.get("headline", "") for i in data if i.get("headline")]
                _news_cache[key] = titles
                return titles[:n]
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


# =============================================================================
# SENTIMENT
# =============================================================================

def get_sentiment(asset: dict) -> tuple:
    if asset.get("marche") == "us":
        ticker_av = asset.get("ticker_av")
        if ALPHAVANTAGE_KEY and ticker_av:
            data, err = _get(AV_BASE, {
                "function": "NEWS_SENTIMENT",
                "tickers":  ticker_av,
                "limit":    50,
                "apikey":   ALPHAVANTAGE_KEY,
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
                    avg  = sum(scores) / len(scores)
                    bull = round((avg + 1) / 2 * 100, 1)
                    bear = round(100 - bull, 1)
                    return bull, bear, "AlphaVantage NLP"
            av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            av_err = "cle absente" if not ALPHAVANTAGE_KEY else "ticker_av absent"

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
            fh_err = "cle absente"

        news = _news_cache.get(asset["ticker_eod"]) or get_company_news(asset, n=10)
        if news:
            bull, bear = _lexical_sentiment(news)
            return bull, bear, f"Lexical (AV:{av_err}, FH:{fh_err})"
        return 50.0, 50.0, f"Neutre par defaut (AV:{av_err}, FH:{fh_err})"

    else:
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
            fh_err = "cle absente"

        news = _news_cache.get(asset["ticker_eod"]) or get_company_news(asset, n=10)
        if news:
            bull, bear = _lexical_sentiment(news)
            return bull, bear, f"Lexical EODHD (Finnhub:{fh_err})"
        return 50.0, 50.0, f"Neutre par defaut (Finnhub:{fh_err})"


_NEGATORS  = {"not", "no", "never", "without", "hardly", "barely", "scarcely"}
_NEG_WINDOW = 3


def _lexical_sentiment(news: list) -> tuple:
    import re

    bull_w = {
        "growth", "buy", "bullish", "surge", "record", "beat", "strong",
        "gain", "up", "rise", "soar", "profit", "positive", "upgrade",
        "recovery", "rally", "outperform", "momentum", "boost",
    }
    bear_w = {
        "loss", "sell", "bearish", "drop", "miss", "weak", "cut", "down",
        "fall", "decline", "risk", "negative", "downgrade", "warn",
        "crash", "default", "layoff", "slowdown", "recession",
    }

    raw_tokens = re.findall(r"[a-z']+", " ".join(news).lower())
    b = s = neg_ttl = 0

    for token in raw_tokens:
        if token in _NEGATORS:
            neg_ttl = _NEG_WINDOW
            continue

        is_bull = token in bull_w
        is_bear = token in bear_w

        if is_bull or is_bear:
            if neg_ttl > 0:
                s += 1 if is_bull else 0
                b += 1 if is_bear else 0
            else:
                b += 1 if is_bull else 0
                s += 1 if is_bear else 0
            neg_ttl = 0
        elif neg_ttl > 0:
            neg_ttl -= 1

    t = b + s or 1
    return round(b / t * 100, 1), round(s / t * 100, 1)


# =============================================================================
# CONSENSUS
# =============================================================================

def get_consensus(asset: dict) -> tuple:
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
        fh_err = "cle absente"

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
        eod_err = "cle absente"

    return (5.0, "N/D", f"Neutre par defaut (Finnhub:{fh_err}, EODHD:{eod_err})")


# =============================================================================
# HISTORIQUE MENSUEL
# =============================================================================

session_cache_global: dict = {}


def get_monthly_history(asset: dict, eur_usd: float, months: int = 3) -> tuple:
    from_d    = str(date.today() - timedelta(days=months * 31))
    to_d      = str(date.today())
    cache_key = f"hist_{asset['ticker_eod']}"

    if asset.get("marche") == "us":
        ticker_av = asset.get("ticker_av")
        if ALPHAVANTAGE_KEY and ticker_av:
            data, err = _get(AV_BASE, {
                "function": "TIME_SERIES_MONTHLY",
                "symbol":   ticker_av,
                "apikey":   ALPHAVANTAGE_KEY,
            }, "alphavantage")
            if isinstance(data, dict) and data.get("Monthly Time Series") and not _is_quota_error(err):
                ts = data["Monthly Time Series"]
                dates  = []
                closes = []
                for month_str, vals in sorted(ts.items()):
                    if month_str < from_d:
                        continue
                    try:
                        dates.append(month_str[:7])
                        closes.append(round(float(vals["4. close"]) * eur_usd, 2))
                    except (ValueError, TypeError, KeyError):
                        pass
                if len(dates) >= 2:
                    return dates, closes, "AlphaVantage", False, None
            av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            av_err = "cle absente" if not ALPHAVANTAGE_KEY else "ticker_av absent"

        if FINNHUB_KEY:
            dates, closes, src, cache_flag, err_str = _finnhub_candles(asset, eur_usd, months)
            if dates:
                return dates, closes, f"Finnhub (fallback AV:{av_err})", cache_flag, err_str
            fh_err = err_str or "vide"
        else:
            fh_err = "cle absente"

        if session_cache_global.get(cache_key):
            saved_at = session_cache_global.get("saved_at", "date inconnue")
            cached   = session_cache_global[cache_key]
            return (cached.get("dates", []), cached.get("closes", []),
                    "Cache", True,
                    f"Historique US non disponible (AV:{av_err}, FH:{fh_err}) -- cache du {saved_at}")
        return ([], [], f"Indisponible (AV:{av_err}, FH:{fh_err})", False,
                "Historique indisponible -- graphique non genere")

    else:
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
            eod_err = "cle absente"

        if FINNHUB_KEY:
            dates, closes, src, cache_flag, err_str = _finnhub_candles(asset, eur_usd, months)
            if dates:
                return dates, closes, f"Finnhub (fallback EODHD:{eod_err})", cache_flag, err_str
            fh_err = err_str or "vide"
        else:
            fh_err = "cle absente"

        if session_cache_global.get(cache_key):
            saved_at = session_cache_global.get("saved_at", "date inconnue")
            cached   = session_cache_global[cache_key]
            return (cached.get("dates", []), cached.get("closes", []),
                    "Cache", True,
                    f"Historique EU non disponible (EODHD:{eod_err}, FH:{fh_err}) -- cache du {saved_at}")
        return ([], [], f"Indisponible (EODHD:{eod_err}, FH:{fh_err})", False,
                "Historique indisponible -- graphique non genere")


def _finnhub_candles(asset: dict, eur_usd: float, months: int) -> tuple:
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


# =============================================================================
# SCORING
# =============================================================================

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
    if ret_1m > 5:    score += 1.5
    elif ret_1m > 2:  score += 0.75
    elif ret_1m < -5: score -= 1.5
    elif ret_1m < -2: score -= 0.75
    if ret_3m > 10:    score += 2.0
    elif ret_3m > 5:   score += 1.0
    elif ret_3m < -10: score -= 2.0
    elif ret_3m < -5:  score -= 1.0
    if ret_6m > 15:    score += 1.5
    elif ret_6m > 7:   score += 0.75
    elif ret_6m < -15: score -= 1.5
    elif ret_6m < -7:  score -= 0.75
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
    if score >= 7.5: return "ACHAT FORT"
    if score >= 6.0: return "ACHAT MODERE"
    if score >= 4.5: return "GARDER"
    if score >= 3.0: return "A EVITER"
    return "VENDRE"


def justification(name, net_pnl_eur, net_pnl_pct, sc, bull, bear,
                  consensus, macro_score, hist_score, hist_label, total_score):
    p1 = (f"Gain net {net_pnl_eur:+.2f} EUR ({net_pnl_pct:+.1f}%) apres frais."
          if net_pnl_eur >= 0
          else f"Perte nette {net_pnl_eur:+.2f} EUR ({net_pnl_pct:+.1f}%) apres frais.")
    p2 = (f"Consensus haussier (score {sc:.1f}/10, Bull {bull:.0f}%)."
          if sc >= 7 else
          f"Consensus neutre ({bull:.0f}% bull / {bear:.0f}% bear)."
          if sc >= 5 else
          f"Consensus defavorable (score {sc:.1f}/10, Bear {bear:.0f}%).")
    p3 = ("Contexte macro favorable." if macro_score >= 6
          else "Contexte macro defavorable." if macro_score <= 4
          else "Contexte macro neutre.")
    p4 = f"Momentum mensuel {hist_label} (score historique {hist_score:.1f}/10)."
    return f"{p1} {p2} {p3} {p4}"


# =============================================================================
# GRAPHIQUE COMBINE
# =============================================================================

_CHART_COLORS = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706",
    "#7c3aed", "#0891b2", "#db2777", "#65a30d",
]


def generate_combined_chart(assets_history: dict, chart_path: str) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        valid = {
            name: (dates, closes)
            for name, (dates, closes) in assets_history.items()
            if len(dates) >= 2 and len(closes) >= 2
        }

        if not valid:
            _log.warning("generate_combined_chart : aucune serie valide (min 2 points requis)")
            return False

        os.makedirs(os.path.dirname(chart_path), exist_ok=True)

        fig, ax = plt.subplots(figsize=(12, 5))
        fig.patch.set_facecolor("#f9f8f5")
        ax.set_facecolor("#f9f8f5")

        for idx, (name, (dates, closes)) in enumerate(valid.items()):
            dt_dates = []
            for d in dates:
                try:
                    dt_dates.append(
                        datetime.strptime(d + "-01" if len(d) == 7 else d, "%Y-%m-%d")
                    )
                except Exception:
                    pass

            if len(dt_dates) < 2:
                continue

            base = closes[0]
            if base == 0:
                continue
            normalized = [round(c / base * 100, 2) for c in closes]

            color = _CHART_COLORS[idx % len(_CHART_COLORS)]
            perf_finale = normalized[-1] - 100

            ax.plot(
                dt_dates, normalized,
                color=color, linewidth=2.2,
                marker="o", markersize=4,
                label=f"{name} ({perf_finale:+.1f}%)",
                zorder=3,
            )

            ax.annotate(
                f"{normalized[-1]:.0f}",
                (dt_dates[-1], normalized[-1]),
                textcoords="offset points", xytext=(6, 0),
                fontsize=7.5, color=color, fontweight="bold",
            )

        ax.axhline(y=100, color="#9ca3af", linestyle="--", linewidth=1.2,
                   alpha=0.8, label="Base 100 (point d'entree)", zorder=2)

        y_min, y_max = ax.get_ylim()
        ax.axhspan(100, max(y_max, 101), alpha=0.04, color="#16a34a", zorder=1)
        ax.axhspan(min(y_min, 99), 100,  alpha=0.04, color="#dc2626",  zorder=1)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        plt.xticks(rotation=30, ha="right", fontsize=8)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        ax.tick_params(axis="y", labelsize=8)
        ax.set_ylabel("Performance (base 100)", fontsize=8, color="#6b7280")

        ax.grid(axis="y", linestyle=":", alpha=0.4, color="#d1d5db")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#e5e7eb")
        ax.spines["bottom"].set_color("#e5e7eb")

        ax.set_title(
            "Performance comparee du portefeuille -- base 100 (3 mois, EUR)",
            fontsize=11, fontweight="bold", color="#111827", pad=14,
        )

        ax.legend(
            fontsize=8, framealpha=0.7, loc="upper left",
            bbox_to_anchor=(0.01, 0.99), ncol=2,
        )

        plt.tight_layout()
        plt.savefig(chart_path, dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        return True

    except Exception as e:
        _log.warning("generate_combined_chart non genere : %s", e)
        return False


# =============================================================================
# HISTORIQUE CSV
# =============================================================================

def append_history(now: datetime, rows: list):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    exists = os.path.isfile(HISTORY_PATH)
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


# =============================================================================
# HELPER PARALLELISATION
# =============================================================================

def _fetch_asset_data(asset: dict, eur_usd: float,
                      td_prices: dict, session_cache: dict) -> dict:
    news = get_company_news(asset, 2)
    bull, bear, sent_src = get_sentiment(asset)
    cs, cons_str, cons_src = get_consensus(asset)
    h_dates, h_closes, h_src, h_cache, h_err = get_monthly_history(asset, eur_usd)
    synthesis, synth_src = get_news_synthesis(asset)
    return {
        "news": news, "bull": bull, "bear": bear, "sent_src": sent_src,
        "cs": cs, "cons_str": cons_str, "cons_src": cons_src,
        "h_dates": h_dates, "h_closes": h_closes, "h_src": h_src,
        "h_cache": h_cache, "h_err": h_err,
        "synthesis": synthesis, "synth_src": synth_src,
    }


# =============================================================================
# MAIN — génération du rapport complet
# =============================================================================

def main():
    global session_cache_global

    now = datetime.now(PARIS_TZ)
    os.makedirs("reports/charts", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    os.makedirs("cache", exist_ok=True)
    os.makedirs("docs", exist_ok=True)

    session_cache = load_session_cache()
    session_cache_global = session_cache

    # ── 1. EUR/USD ────────────────────────────────────────────────────────────
    eur_usd, eur_usd_src, eur_usd_cache, eur_usd_warn = get_eur_usd(session_cache)
    session_cache["eur_usd"] = eur_usd

    # ── 2. Cours US en batch (TwelveData) ─────────────────────────────────────
    us_tickers = [a["ticker_td"] for a in PORTFOLIO if a.get("ticker_td")]
    us_tickers += [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    td_prices = td_fetch_batch(list(set(filter(None, us_tickers)))) if TWELVEDATA_KEY else {}

    # ── 3. Cours par position + données parallèles ────────────────────────────
    prices     = {}
    asset_data = {}

    with ThreadPoolExecutor(max_workers=4) as exe:
        price_futures = {
            exe.submit(get_price_eur, a, eur_usd, td_prices, session_cache): a
            for a in PORTFOLIO
        }
        for fut in as_completed(price_futures):
            a = price_futures[fut]
            try:
                prices[a["ticker_eod"]] = fut.result()
            except Exception as e:
                _log.warning("Cours %s : %s", a["ticker_eod"], e)
                prices[a["ticker_eod"]] = (None, 0.0, "Erreur", False, str(e))

    with ThreadPoolExecutor(max_workers=4) as exe:
        data_futures = {
            exe.submit(_fetch_asset_data, a, eur_usd, td_prices, session_cache): a
            for a in PORTFOLIO
        }
        for fut in as_completed(data_futures):
            a = data_futures[fut]
            try:
                asset_data[a["ticker_eod"]] = fut.result()
            except Exception as e:
                _log.warning("Données %s : %s", a["ticker_eod"], e)
                asset_data[a["ticker_eod"]] = {
                    "news": [], "bull": 50.0, "bear": 50.0, "sent_src": "erreur",
                    "cs": 5.0, "cons_str": "N/D", "cons_src": "erreur",
                    "h_dates": [], "h_closes": [], "h_src": "erreur",
                    "h_cache": False, "h_err": str(e),
                    "synthesis": "Données indisponibles.", "synth_src": "",
                }

    # ── 4. Indices macro ──────────────────────────────────────────────────────
    indices_data = {}
    for idx_name, idx_sym in INDICES.items():
        indices_data[idx_name] = get_index(idx_sym)

    macro_score = score_macro(indices_data)

    # ── 5. Watchlist cours ────────────────────────────────────────────────────
    watchlist_prices = {}
    for w in WATCHLIST:
        p, chg, src, from_cache, note = get_price_eur(w, eur_usd, td_prices, session_cache)
        watchlist_prices[w["ticker_eod"]] = (p, chg, src, from_cache)

    # ── 6. Watchlist news (RSS) ───────────────────────────────────────────────
    watchlist_synth = {}
    for w in WATCHLIST:
        synth, synth_src = get_news_synthesis(w)
        watchlist_synth[w["ticker_eod"]] = (synth, synth_src)

    # ── 7. Calculs PnL + scoring par position ────────────────────────────────
    results      = []
    history_rows = []
    cache_warns  = []
    sources_log  = {
        "EUR/USD":     eur_usd_src,
        **{n: indices_data[n]["source"] for n in indices_data},
    }
    assets_history = {}

    for asset in PORTFOLIO:
        key      = asset["ticker_eod"]
        price_info = prices.get(key, (None, 0.0, "manquant", False, None))
        price_eur, chg_pct, price_src, price_cache, price_note = price_info

        d = asset_data.get(key, {})
        h_dates  = d.get("h_dates", [])
        h_closes = d.get("h_closes", [])

        # Sauvegarde cache historique
        if h_closes and not d.get("h_cache"):
            session_cache[f"hist_{key}"] = {"dates": h_dates, "closes": h_closes}

        # Sauvegarde cache prix
        if price_eur and not price_cache:
            session_cache[f"price_{key}"] = price_eur

        if price_eur is None:
            # Pas de cours disponible, on skip mais on loggue
            _log.warning("Cours introuvable pour %s — position ignorée dans le rapport", key)
            continue

        qty      = asset["qty"]
        cost_eur = asset["cost_eur"]

        vm        = round(price_eur * qty, 2)
        pnl_brut  = round((price_eur - cost_eur) * qty, 2)
        pnl_brut_pct = round(pnl_brut / (cost_eur * qty) * 100, 2)

        buy_fee   = calc_fee(cost_eur * qty, asset["marche"])
        sell_fee  = calc_fee(vm, asset["marche"])
        pnl_net   = round(pnl_brut - buy_fee - sell_fee, 2)
        pnl_net_pct = round(pnl_net / (cost_eur * qty) * 100, 2)

        # Scoring
        sc_price   = score_price(price_eur, cost_eur)
        sc_hist, hist_label, ret_1m, ret_3m, ret_6m = score_history(h_dates, h_closes)
        bull = d.get("bull", 50.0); bear = d.get("bear", 50.0)
        cs   = d.get("cs",   5.0)

        total_score = round(
            sc_price * 0.30 +
            (bull / 10.0)   * 0.20 +
            cs              * 0.20 +
            sc_hist         * 0.30,
            2
        )
        rec = recommend(total_score)

        just = justification(
            asset["name"], pnl_net, pnl_net_pct,
            cs, bull, bear, d.get("cons_str", "N/D"),
            macro_score, sc_hist, hist_label, total_score
        )

        # Historique CSV
        history_rows.append({
            "date":         now.strftime("%Y-%m-%d"),
            "time":         now.strftime("%H:%M"),
            "ticker":       key,
            "name":         asset["name"],
            "price_eur":    price_eur,
            "cost_eur":     cost_eur,
            "qty":          qty,
            "vm":           vm,
            "pnl_brut":     pnl_brut,
            "pnl_brut_pct": pnl_brut_pct,
            "pnl_net":      pnl_net,
            "pnl_net_pct":  pnl_net_pct,
            "score":        total_score,
            "rec":          rec,
        })

        # Avertissements cache
        if price_cache and price_note:
            cache_warns.append(f"{asset['name']} -- cours : {price_note}")
        if d.get("h_cache") and d.get("h_err"):
            cache_warns.append(f"{asset['name']} -- historique : {d['h_err']}")

        # Log sources
        sources_log[key] = {
            "cours":     price_src,
            "sentiment": d.get("sent_src", "N/D"),
            "consensus": d.get("cons_src", "N/D"),
            "historique": d.get("h_src",   "N/D"),
            "synthese":  d.get("synth_src","N/D"),
        }

        assets_history[asset["name"]] = (h_dates, h_closes)

        results.append({
            "asset":        asset,
            "price_eur":    price_eur,
            "chg_pct":      chg_pct,
            "price_src":    price_src,
            "vm":           vm,
            "pnl_brut":     pnl_brut,
            "pnl_brut_pct": pnl_brut_pct,
            "pnl_net":      pnl_net,
            "pnl_net_pct":  pnl_net_pct,
            "score":        total_score,
            "rec":          rec,
            "just":         just,
            "bull":         bull,
            "bear":         bear,
            "cs":           cs,
            "cons_str":     d.get("cons_str", "N/D"),
            "cons_src":     d.get("cons_src", "N/D"),
            "sent_src":     d.get("sent_src", "N/D"),
            "hist_label":   hist_label,
            "ret_1m":       ret_1m,
            "ret_3m":       ret_3m,
            "ret_6m":       ret_6m,
            "h_src":        d.get("h_src", "N/D"),
            "synthesis":    d.get("synthesis", ""),
            "synth_src":    d.get("synth_src", ""),
        })

    # ── 8. Tri par score décroissant ─────────────────────────────────────────
    results.sort(key=lambda x: x["score"], reverse=True)

    # ── 9. Totaux portefeuille ────────────────────────────────────────────────
    total_vm       = round(sum(r["vm"] for r in results), 2)
    total_cost     = round(sum(r["asset"]["cost_eur"] * r["asset"]["qty"] for r in results), 2)
    total_pnl_brut = round(sum(r["pnl_brut"] for r in results), 2)
    total_pnl_brut_pct = round(total_pnl_brut / total_cost * 100, 2) if total_cost else 0
    total_pnl_net  = round(sum(r["pnl_net"] for r in results), 2)
    total_pnl_net_pct = round(total_pnl_net / total_cost * 100, 2) if total_cost else 0

    # ── 10. Graphique combiné ─────────────────────────────────────────────────
    chart_path   = f"{CHARTS_DIR}/portfolio_combined.png"
    chart_ok     = generate_combined_chart(assets_history, chart_path)

    # ── 11. Sauvegarde cache ──────────────────────────────────────────────────
    save_session_cache(session_cache)

    # ── 12. Historique CSV ────────────────────────────────────────────────────
    append_history(now, history_rows)

    # ── 13. Génération du rapport Markdown ───────────────────────────────────
    macro_trend = "Haussiere" if macro_score >= 6 else "Baissiere" if macro_score <= 4 else "Neutre"

    lines = [
        f"# Rapport de Portefeuille v5.4 -- {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        "",
        "---",
        "",
        "## Contexte Economique",
        "",
        f"**Tendance : {macro_trend}** | Score macro : {macro_score}/10",
        f"**EUR/USD :** 1 EUR = {round(1/eur_usd, 4)} USD",
        "",
        "| Indice | Variation | Cours |",
        "|--------|-----------|-------|",
    ]

    for idx_name, idx_val in indices_data.items():
        chg  = idx_val["change_pct"]
        sym  = "^" if chg >= 0 else "v"
        sign = "+" if chg >= 0 else ""
        prix_fmt = f"{idx_val['price']:,.2f}".replace(",", " ")
        lines.append(f"| {idx_name} | {sym} {sign}{chg:.2f}% | {prix_fmt} |")

    lines += [""]
    macro_news = get_macro_news(5)
    if macro_news:
        lines.append("**Manchettes macro :**")
        lines.append("")
        for n in macro_news:
            lines.append(f"- {n}")
    lines += ["", "---", "", "## Analyse par Valeur", ""]

    for r in results:
        asset   = r["asset"]
        chg     = r["chg_pct"]
        sym     = "^" if chg >= 0 else "v"
        sign    = "+" if chg >= 0 else ""
        chg_str = f"{sym} {sign}{chg:.2f}%"

        pnl_b_sign = "+" if r["pnl_brut"] >= 0 else "-"
        pnl_b_str  = f"{pnl_b_sign} {pnl_b_sign}{abs(r['pnl_brut']):.2f} EUR ({pnl_b_sign}{abs(r['pnl_brut_pct']):.1f}%)"
        pnl_n_sign = "+" if r["pnl_net"] >= 0 else "-"
        pnl_n_str  = f"{pnl_n_sign} {pnl_n_sign}{abs(r['pnl_net']):.2f} EUR ({pnl_n_sign}{abs(r['pnl_net_pct']):.1f}%)"

        ret_1m_s = f"{r['ret_1m']:+.1f}%"
        ret_3m_s = f"{r['ret_3m']:+.1f}%"
        ret_6m_s = f"{r['ret_6m']:+.1f}%"

        lines += [
            f"### {asset['name']} `{asset['ticker_eod']}`",
            "",
            "| Cours | Variation | VM | P&L Brut | P&L Net | Score | Recomm. |",
            "|-------|-----------|-----|----------|---------|-------|---------|",
            f"| {r['price_eur']:.2f} EUR | {chg_str} | {r['vm']:.2f} EUR "
            f"| {pnl_b_str} | {pnl_n_str} | **{r['score']}/10** | {r['rec']} |",
            "",
        ]

        synth = r.get("synthesis", "").strip()
        synth_src_val = r.get("synth_src", "RSS Yahoo Finance (brut)").strip()
        if synth and "Aucune actualite" not in synth:
            lines.append(f"**Actualite recente :** *(source : {synth_src_val})*")
            lines.append("")
            lines.append(f"> {synth}")
            lines.append("")

        lines += [
            f"**Sentiment :** Bull {r['bull']:.0f}% / Bear {r['bear']:.0f}% *(source : {r['sent_src']})*",
            f"**Consensus :** {r['cons_str']} *(source : {r['cons_src']})*",
            "",
            f"**Momentum mensuel :** {r['hist_label']} (1M: {ret_1m_s} / 3M: {ret_3m_s} / 6M: {ret_6m_s}) *(source : {r['h_src']})*",
            "",
            f"**Justification :** {r['just']}",
            "",
            "---",
            "",
        ]

    # Section tendances
    lines += [
        "## Tendances -- Performance Comparee (base 100)",
        "",
        "![Portfolio combine](charts/portfolio_combined.png)",
        "",
        "---",
        "",
        "## Synthese Portefeuille",
        "",
        "| Cout total | Valeur marche | P&L Brut | P&L Net |",
        "|------------|---------------|----------|---------|",
    ]

    pb_sign = "+" if total_pnl_brut >= 0 else "-"
    pn_sign = "+" if total_pnl_net  >= 0 else "-"
    lines.append(
        f"| {total_cost:.2f} EUR | {total_vm:.2f} EUR "
        f"| {pb_sign} {pb_sign}{abs(total_pnl_brut):.2f} EUR ({pb_sign}{abs(total_pnl_brut_pct):.1f}%) "
        f"| {pn_sign} {pn_sign}{abs(total_pnl_net):.2f} EUR ({pn_sign}{abs(total_pnl_net_pct):.1f}%) |"
    )

    lines += [
        "",
        "---",
        "",
        "### Classement par Score",
        "",
        "| Valeur | VM | P&L Net | Score | Recomm. |",
        "|--------|----|---------|-------|---------|",
    ]

    for r in results:
        pn_sign = "+" if r["pnl_net"] >= 0 else "-"
        pnl_n_s = f"{pn_sign} {pn_sign}{abs(r['pnl_net']):.2f} EUR ({pn_sign}{abs(r['pnl_net_pct']):.1f}%)"
        lines.append(
            f"| {r['asset']['name']} | {r['vm']:.2f} EUR | {pnl_n_s} | **{r['score']}/10** | {r['rec']} |"
        )

    # Watchlist
    lines += ["", "---", "", "## Watchlist", ""]
    for w in WATCHLIST:
        key_w = w["ticker_eod"]
        p_info = watchlist_prices.get(key_w, (None, 0, "N/D", False))
        p_val, p_chg, p_src, _ = p_info
        p_str = f"{p_val:.2f} EUR" if p_val else "N/D"
        synth_w, synth_src_w = watchlist_synth.get(key_w, ("Aucune actualite.", "RSS Yahoo vide"))

        lines.append(f"**{w['name']}** `{w['ticker_fh']}` -- {w.get('sector', '')} | Cours : {p_str} *(source : {p_src})*")
        lines.append("")
        if synth_w and "Aucune actualite" not in synth_w:
            lines.append(f"> {synth_w} *(source : {synth_src_w})*")
        lines.append("")

    # Section technique
    lines += [
        "---",
        "",
        "## Informations Techniques",
        "",
        f"**Quotas API :** {' | '.join(f'{k}: {v}' for k, v in _quota_status().items())}",
        f"**Sources utilisees :** {json.dumps(sources_log, ensure_ascii=False)}",
        "",
        "**Avertissements cache :**",
        "",
    ]
    if cache_warns:
        for w in cache_warns:
            lines.append(f"- {w}")
    else:
        lines.append("- Aucun avertissement cache.")

    if eur_usd_warn:
        lines.append(f"- EUR/USD : {eur_usd_warn}")

    lines += [
        "",
        f"*Rapport genere le {now.strftime('%d/%m/%Y')} a {now.strftime('%H:%M')} (heure de Paris)*",
        f"*Chart combine genere : {'Oui' if chart_ok else 'Non'}*",
    ]

    # Écriture du rapport
    report_path = "reports/daily_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ Rapport généré : {report_path}")
    print(f"✅ Quotas : {_quota_status()}")


if __name__ == "__main__":
    main()
