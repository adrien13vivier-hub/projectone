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
    "alphavantage": {"used": 0, "limit": 20},   # était 23, corrigé à 20
    "twelvedata":   {"used": 0, "limit": 60},
    "eodhd":        {"used": 0, "limit": 80},   # CORRECTION CRITIQUE : était 18 !
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

# Longueur max d'un titre RSS pour eviter les debordements de blockquote Markdown.
_RSS_TITLE_MAX = 120


def _clean_title(raw: str) -> str:
    """Supprime les retours a la ligne et tronque a _RSS_TITLE_MAX caracteres."""
    cleaned = " ".join(raw.replace("\r", " ").replace("\n", " ").split()).strip()
    if len(cleaned) > _RSS_TITLE_MAX:
        cleaned = cleaned[:_RSS_TITLE_MAX].rstrip() + "\u2026"
    return cleaned


def _fetch_yahoo_rss(ticker_yf: str, n: int = 6) -> list:
    """Recupere les n derniers titres d'actualite depuis le flux RSS Yahoo Finance.

    Retourne une liste de chaines sur UNE seule ligne chacune (sans \\n interne).
    """
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
# SYNTHESE ACTUALITE -- titres RSS bruts (pas d'IA)
# =============================================================================

_synthesis_cache: dict = {}


def get_news_synthesis(asset: dict) -> tuple:
    """Recupere les titres RSS Yahoo Finance et les retourne bruts (3 max).

    Retourne (synthese_str, source_str).
    - synthese_str : titres separes par " | ", garantis sur une seule ligne
    - source_str   : "RSS Yahoo Finance" | "RSS Yahoo vide"
    """
    ticker_yf = asset.get("ticker_yf") or asset.get("ticker_fh", "")
    key = ticker_yf

    if key in _synthesis_cache:
        return _synthesis_cache[key]

    titles = _fetch_yahoo_rss(ticker_yf, n=6)

    if not titles:
        result = ("Aucune actualite disponible via RSS.", "RSS Yahoo vide")
        _synthesis_cache[key] = result
        return result

    # Jointure + nettoyage final : on s'assure qu'aucun \n residuel ne subsiste
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
# NEWS (titres bruts Finnhub/EODHD -- conserves pour le scoring sentiment)
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
    """Retourne (bull_pct, bear_pct, source_str)."""

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


# --- Analyse lexicale v6.0 : fenetre de negation ------------------------------
_NEGATORS  = {"not", "no", "never", "without", "hardly", "barely", "scarcely"}
_NEG_WINDOW = 3


def _lexical_sentiment(news: list) -> tuple:
    """Analyse lexicale avec gestion des negations (fenetre de 3 tokens)."""
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
# CONSENSUS -- Finnhub principal * EODHD fallback
# =============================================================================

def get_consensus(asset: dict) -> tuple:
    """Retourne (score/10, detail_str, source_str)."""
    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/stock/recommendation",
                         {"symbol": asset["ticker_fh"], "token": FINNHUB_KEY},
                         "finnhub")
        if isinstance(data, list) and data and not _is_quota_error(err):
            latest = data[0]
            strong_buy  = int(latest.get("strongBuy",  0))
            buy         = int(latest.get("buy",         0))
            hold        = int(latest.get("hold",        0))
            sell        = int(latest.get("sell",        0))
            strong_sell = int(latest.get("strongSell",  0))
            total = strong_buy + buy + hold + sell + strong_sell
            if total > 0:
                score = (strong_buy * 10 + buy * 7.5 + hold * 5 +
                         sell * 2.5 + strong_sell * 0) / total
                detail = (f"SB:{strong_buy} B:{buy} H:{hold} "
                          f"S:{sell} SS:{strong_sell} [{latest.get('period','?')}]")
                return round(score, 2), detail, "Finnhub"
        fh_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        fh_err = "cle absente"

    if EODHD_KEY:
        sym = asset["ticker_eod"].replace(".PA", ".PA").replace(".US", ".US")
        data, err = _get(f"{EOD_BASE}/fundamentals/{sym}",
                         {"api_token": EODHD_KEY, "filter": "Highlights", "fmt": "json"},
                         "eodhd")
        if isinstance(data, dict) and not _is_quota_error(err):
            hl = data.get("Highlights", {})
            target = hl.get("AnalystTargetPrice")
            rating = hl.get("RecommendationKey", "")
            mapping = {"strong_buy": 10, "buy": 7.5, "hold": 5,
                       "sell": 2.5, "strong_sell": 0}
            if rating and rating.lower() in mapping:
                score = mapping[rating.lower()]
                detail = f"Rating EODHD : {rating} | Target : {target or 'N/D'}"
                return round(score, 2), detail, f"EODHD (fallback FH:{fh_err})"
        eod_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        eod_err = "cle absente"

    return 5.0, "N/D", f"Neutre par defaut (FH:{fh_err}, EOD:{eod_err})"


# =============================================================================
# HISTORIQUE MENSUEL (3 mois)
# =============================================================================

def _alphavantage_monthly(asset: dict) -> list | None:
    """Retourne liste de (date_str, close_float) sur 3 mois, ou None."""
    ticker_av = asset.get("ticker_av")
    if not ALPHAVANTAGE_KEY or not ticker_av:
        return None
    data, err = _get(AV_BASE, {
        "function": "TIME_SERIES_MONTHLY",
        "symbol":   ticker_av,
        "apikey":   ALPHAVANTAGE_KEY,
    }, "alphavantage")
    if not isinstance(data, dict) or _is_quota_error(err):
        return None
    ts = data.get("Monthly Time Series", {})
    if not ts:
        return None
    cutoff = date.today() - timedelta(days=91)
    pts = []
    for d_str, vals in sorted(ts.items(), reverse=True):
        try:
            if date.fromisoformat(d_str) < cutoff:
                break
            pts.append((d_str, float(vals["4. close"])))
        except Exception:
            continue
    return pts if pts else None


def _finnhub_candles(asset: dict) -> list | None:
    """Retourne liste de (date_str, close_float) via Finnhub candles, ou None."""
    if not FINNHUB_KEY:
        return None
    now_ts   = int(datetime.now().timestamp())
    from_ts  = int((datetime.now() - timedelta(days=91)).timestamp())
    data, err = _get(f"{FH_BASE}/stock/candle",
                     {"symbol": asset["ticker_fh"], "resolution": "M",
                      "from": from_ts, "to": now_ts, "token": FINNHUB_KEY},
                     "finnhub")
    if not isinstance(data, dict) or data.get("s") != "ok" or _is_quota_error(err):
        return None
    closes = data.get("c", [])
    times  = data.get("t", [])
    if not closes or len(closes) != len(times):
        return None
    pts = []
    for ts_val, close in zip(times, closes):
        d_str = datetime.fromtimestamp(ts_val).strftime("%Y-%m-%d")
        pts.append((d_str, float(close)))
    return pts if pts else None


def _eodhd_monthly(asset: dict) -> list | None:
    """Retourne liste de (date_str, close_float) via EODHD, ou None."""
    if not EODHD_KEY:
        return None
    from_d = str(date.today() - timedelta(days=91))
    to_d   = str(date.today())
    data, err = _get(f"{EOD_BASE}/eod/{asset['ticker_eod']}",
                     {"api_token": EODHD_KEY, "period": "m",
                      "from": from_d, "to": to_d, "fmt": "json"},
                     "eodhd")
    if not isinstance(data, list) or _is_quota_error(err):
        return None
    pts = []
    for row in data:
        try:
            pts.append((row["date"], float(row["close"])))
        except Exception:
            continue
    return pts if pts else None


def get_history(asset: dict) -> tuple:
    """Retourne (points_list, source_str) avec points_list = [(date, close), ...]."""
    pts = _alphavantage_monthly(asset)
    if pts:
        return pts, "AlphaVantage"

    pts = _finnhub_candles(asset)
    if pts:
        return pts, "Finnhub"

    pts = _eodhd_monthly(asset)
    if pts:
        return pts, "EODHD"

    return [], "Indisponible"


# =============================================================================
# SCORING
# =============================================================================

def score_asset(price_eur: float, cost_eur: float,
                bull_pct: float, consensus: float,
                history: list) -> tuple:
    """
    Retourne (score_0_10, recommandation_str).

    Poids :
      - Prix vs PRU        30 %  (gain/perte latente)
      - Sentiment          20 %
      - Consensus          20 %
      - Historique 3 mois  30 %  (tendance)
    """
    # --- Composante Prix vs PRU (30 %) ---
    if price_eur and cost_eur and cost_eur > 0:
        pct_chg = (price_eur - cost_eur) / cost_eur * 100
        if   pct_chg >=  15: prix_s = 10
        elif pct_chg >=   5: prix_s = 8
        elif pct_chg >=   0: prix_s = 6
        elif pct_chg >=  -5: prix_s = 4
        elif pct_chg >= -15: prix_s = 2
        else:                 prix_s = 0
    else:
        prix_s = 5

    # --- Composante Sentiment (20 %) ---
    sent_s = round(bull_pct / 10, 2)

    # --- Composante Consensus (20 %) ---
    cons_s = consensus  # déjà en /10

    # --- Composante Historique (30 %) ---
    if len(history) >= 2:
        oldest = history[-1][1]
        newest = history[0][1]
        if oldest > 0:
            trend_pct = (newest - oldest) / oldest * 100
            if   trend_pct >=  10: hist_s = 10
            elif trend_pct >=   3: hist_s = 7
            elif trend_pct >=  -3: hist_s = 5
            elif trend_pct >= -10: hist_s = 3
            else:                  hist_s = 0
        else:
            hist_s = 5
    else:
        hist_s = 5

    score = round(prix_s * 0.30 + sent_s * 0.20 + cons_s * 0.20 + hist_s * 0.30, 2)
    score = max(0.0, min(10.0, score))

    if   score >= 8:   rec = "ACHAT FORT"
    elif score >= 6.5: rec = "ACHAT"
    elif score >= 5:   rec = "CONSERVER"
    elif score >= 3:   rec = "SURVEILLER"
    else:              rec = "VENDRE"

    return score, rec


# =============================================================================
# GRAPHIQUE COMBINE (courbes normalisees base 100)
# =============================================================================

def generate_combined_chart(portfolio_histories: dict) -> bool:
    """
    Genere un graphique multi-lignes normalisees base 100 pour toutes les positions.
    Sauvegarde dans reports/charts/portfolio_combined.png.
    Retourne True si succes.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime as dt

        os.makedirs(CHARTS_DIR, exist_ok=True)

        fig, ax = plt.subplots(figsize=(12, 6))
        plotted = 0

        for name, (pts, src) in portfolio_histories.items():
            if not pts or len(pts) < 2:
                continue
            try:
                dates  = [dt.strptime(p[0][:10], "%Y-%m-%d") for p in reversed(pts)]
                closes = [p[1] for p in reversed(pts)]
                base   = closes[0]
                if base <= 0:
                    continue
                norm = [c / base * 100 for c in closes]
                ax.plot(dates, norm, marker="o", markersize=3, linewidth=1.5, label=name)
                plotted += 1
            except Exception:
                continue

        if plotted == 0:
            return False

        ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.set_title("Performance normalisee base 100 — 3 derniers mois", fontsize=13)
        ax.set_ylabel("Base 100")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        chart_path = os.path.join(CHARTS_DIR, "portfolio_combined.png")
        plt.savefig(chart_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return True

    except Exception as e:
        _log.warning("Graphique combine : %s", e)
        return False


# =============================================================================
# HISTORY CSV
# =============================================================================

def update_history(rows: list):
    """Ajoute les lignes du jour dans reports/history.csv."""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    write_header = not os.path.exists(HISTORY_PATH)
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in HISTORY_COLS})


# =============================================================================
# MAIN
# =============================================================================

def main():
    now          = datetime.now(PARIS_TZ)
    session_cache = load_session_cache()

    # -- EUR/USD ---------------------------------------------------------------
    eur_usd, eur_usd_src, eur_usd_cached, eur_usd_warn = get_eur_usd(session_cache)
    if not eur_usd_cached:
        session_cache["eur_usd"] = eur_usd

    # -- Cours US (batch TwelveData) ------------------------------------------
    us_tickers = [a.get("ticker_td") for a in PORTFOLIO + WATCHLIST
                  if a["marche"] == "us" and a.get("ticker_td")]
    td_prices  = td_fetch_batch(list(set(us_tickers))) if TWELVEDATA_KEY and us_tickers else {}

    # -- Indices ---------------------------------------------------------------
    indices_data = {name: get_index(syms) for name, syms in INDICES.items()}

    # -- Analyse parallele (portfolio + watchlist) -----------------------------
    def analyse_asset(asset: dict, is_watchlist: bool = False) -> dict:
        price, chg, p_src, p_cached, p_note = get_price_eur(
            asset, eur_usd, td_prices, session_cache)

        if price and not p_cached:
            session_cache[f"price_{asset['ticker_eod']}"] = price

        bull, bear, sent_src   = get_sentiment(asset)
        cons, cons_det, cons_src = get_consensus(asset)
        history, hist_src      = get_history(asset)
        synth, synth_src       = get_news_synthesis(asset)

        if price and asset.get("cost_eur"):
            sc, rec = score_asset(price, asset["cost_eur"], bull, cons, history)
        else:
            sc, rec = 5.0, "CONSERVER"

        return {
            "asset":      asset,
            "price":      price,
            "chg":        chg,
            "p_src":      p_src,
            "p_cached":   p_cached,
            "p_note":     p_note,
            "bull":       bull,
            "bear":       bear,
            "sent_src":   sent_src,
            "cons":       cons,
            "cons_det":   cons_det,
            "cons_src":   cons_src,
            "history":    history,
            "hist_src":   hist_src,
            "synth":      synth,
            "synth_src":  synth_src,
            "score":      sc,
            "rec":        rec,
            "is_watchlist": is_watchlist,
        }

    all_assets = [(a, False) for a in PORTFOLIO] + [(a, True) for a in WATCHLIST]
    results    = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(analyse_asset, a, w): (a, w)
                   for a, w in all_assets}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                results[r["asset"]["ticker_eod"]] = r
            except Exception as e:
                a, _ = futures[fut]
                _log.warning("Erreur analyse %s : %s", a.get("name"), e)

    # -- Guard v6.2 : si tous les prix US ou EU sont None, on plante visiblement
    us_prices  = [results[a["ticker_eod"]]["price"]
                  for a in PORTFOLIO if a["marche"] == "us"
                  and a["ticker_eod"] in results]
    eu_prices  = [results[a["ticker_eod"]]["price"]
                  for a in PORTFOLIO if a["marche"] == "euronext"
                  and a["ticker_eod"] in results]

    if us_prices and all(p is None for p in us_prices):
        raise RuntimeError(
            "ERREUR CRITIQUE : aucun cours US disponible (tous les quotas API sont épuisés). "
            "Vérifiez les secrets GitHub et les quotas AlphaVantage/TwelveData/EODHD."
        )
    if eu_prices and all(p is None for p in eu_prices):
        raise RuntimeError(
            "ERREUR CRITIQUE : aucun cours Euronext disponible (tous les quotas API sont épuisés). "
            "Vérifiez les secrets GitHub et le quota EODHD."
        )

    # -- Graphique combine -----------------------------------------------------
    portfolio_histories = {
        results[a["ticker_eod"]]["asset"]["name"]: (
            results[a["ticker_eod"]]["history"],
            results[a["ticker_eod"]]["hist_src"]
        )
        for a in PORTFOLIO if a["ticker_eod"] in results
    }
    chart_ok = generate_combined_chart(portfolio_histories)

    # -- Lecture image base64 pour rapport Markdown ---------------------------
    chart_b64 = ""
    chart_path = os.path.join(CHARTS_DIR, "portfolio_combined.png")
    if chart_ok and os.path.exists(chart_path):
        import base64
        with open(chart_path, "rb") as f:
            chart_b64 = base64.b64encode(f.read()).decode()

    # -- Mise a jour history.csv -----------------------------------------------
    history_rows = []
    for a in PORTFOLIO:
        r = results.get(a["ticker_eod"])
        if not r:
            continue
        price = r["price"]
        qty   = a["qty"]
        cost  = a["cost_eur"]
        if price:
            vm        = round(price * qty, 2)
            fee_buy   = calc_fee(cost * qty, a["marche"])
            fee_sell  = calc_fee(vm, a["marche"])
            pnl_brut  = round(vm - cost * qty, 2)
            pnl_net   = round(pnl_brut - fee_buy - fee_sell, 2)
            pnl_b_pct = round(pnl_brut / (cost * qty) * 100, 2) if cost else 0
            pnl_n_pct = round(pnl_net  / (cost * qty) * 100, 2) if cost else 0
        else:
            vm = pnl_brut = pnl_net = pnl_b_pct = pnl_n_pct = ""
        history_rows.append({
            "date":        now.strftime("%Y-%m-%d"),
            "time":        now.strftime("%H:%M"),
            "ticker":      a["ticker_fh"],
            "name":        a["name"],
            "price_eur":   price or "",
            "cost_eur":    cost,
            "qty":         qty,
            "vm":          vm,
            "pnl_brut":    pnl_brut,
            "pnl_brut_pct": pnl_b_pct,
            "pnl_net":     pnl_net,
            "pnl_net_pct": pnl_n_pct,
            "score":       r["score"],
            "rec":         r["rec"],
        })
    update_history(history_rows)

    # -- Construction du rapport Markdown --------------------------------------
    sources_log  = {}
    cache_warns  = []
    lines        = []

    # En-tete
    lines += [
        f"# Rapport Portfolio — {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        "",
        f"**EUR/USD :** {eur_usd:.4f} *(source : {eur_usd_src})*",
        "",
    ]

    # Indices
    lines.append("## Marchés")
    lines.append("")
    for idx_name, idx_data in indices_data.items():
        chg_sign = "+" if idx_data["change_pct"] >= 0 else ""
        lines.append(
            f"- **{idx_name}** : {idx_data['price']:,.2f} "
            f"({chg_sign}{idx_data['change_pct']:.2f}%) "
            f"*(source : {idx_data['source']})*"
        )
    lines.append("")

    # Portfolio
    lines += ["---", "", "## Portefeuille", ""]

    total_vm    = 0.0
    total_cost  = 0.0
    total_pnl_n = 0.0

    for a in PORTFOLIO:
        r = results.get(a["ticker_eod"])
        if not r:
            lines.append(f"### {a['name']} — données indisponibles")
            lines.append("")
            continue

        price  = r["price"]
        qty    = a["qty"]
        cost   = a["cost_eur"]
        p_src  = r["p_src"]

        sources_log[a["ticker_fh"]] = {
            "prix": p_src, "sentiment": r["sent_src"],
            "consensus": r["cons_src"], "historique": r["hist_src"]
        }

        if r["p_cached"]:
            cache_warns.append(r["p_note"] or f"{a['name']} : prix depuis cache")

        # Calculs financiers
        if price:
            vm       = round(price * qty, 2)
            fee_buy  = calc_fee(cost * qty, a["marche"])
            fee_sell = calc_fee(vm, a["marche"])
            pnl_brut = round(vm - cost * qty, 2)
            pnl_net  = round(pnl_brut - fee_buy - fee_sell, 2)
            pnl_pct  = round(pnl_brut / (cost * qty) * 100, 2) if cost else 0
            pnl_sign = "+" if pnl_brut >= 0 else ""
            chg_sign = "+" if r["chg"] >= 0 else ""
            total_vm    += vm
            total_cost  += cost * qty
            total_pnl_n += pnl_net
        else:
            vm = fee_buy = fee_sell = pnl_brut = pnl_net = pnl_pct = 0
            pnl_sign = chg_sign = ""

        # Bloc position
        lines.append(f"### {a['name']} `{a['ticker_fh']}`")
        lines.append("")
        if price:
            lines.append(
                f"**Cours :** {price:.2f} EUR "
                f"({chg_sign}{r['chg']:.2f}%) "
                f"*(source : {p_src})*"
            )
            if r["p_note"]:
                lines.append(f"  *{r['p_note']}*")
            lines.append(
                f"**Position :** {qty} × {cost:.2f} EUR = "
                f"{cost*qty:.2f} EUR investis"
            )
            lines.append(
                f"**Valeur marché :** {vm:.2f} EUR | "
                f"**PnL brut :** {pnl_sign}{pnl_brut:.2f} EUR ({pnl_sign}{pnl_pct:.2f}%) | "
                f"**PnL net :** {'+' if pnl_net>=0 else ''}{pnl_net:.2f} EUR"
            )
        else:
            lines.append(f"**Cours :** N/D *(source : {p_src})*")

        lines.append(
            f"**Sentiment :** Bull {r['bull']:.1f}% / Bear {r['bear']:.1f}% "
            f"*(source : {r['sent_src']})*"
        )
        lines.append(
            f"**Consensus :** {r['cons']:.1f}/10 — {r['cons_det']} "
            f"*(source : {r['cons_src']})*"
        )
        hist_summary = ""
        if r["history"] and len(r["history"]) >= 2:
            oldest = r["history"][-1]
            newest = r["history"][0]
            hist_summary = (
                f"{oldest[0]} : {oldest[1]:.2f} → "
                f"{newest[0]} : {newest[1]:.2f} "
                f"*(source : {r['hist_src']})*"
            )
        lines.append(f"**Historique 3 mois :** {hist_summary or 'N/D'}")
        lines.append(f"**Score :** {r['score']:.2f}/10 → **{r['rec']}**")
        lines.append("")

        synth = r.get("synth", "")
        synth_src = r.get("synth_src", "")
        if synth and "Aucune actualite" not in synth:
            lines.append(f"> {synth} *(source : {synth_src})*")
        lines.append("")

    # Synthese portefeuille
    if total_cost > 0:
        total_pnl_brut = total_vm - total_cost
        total_pct      = round(total_pnl_brut / total_cost * 100, 2)
        pnl_sign       = "+" if total_pnl_brut >= 0 else ""
        lines += [
            "---",
            "",
            "## Synthèse Portefeuille",
            "",
            f"| Métrique | Valeur |",
            f"|---|---|",
            f"| Valeur marché totale | {total_vm:.2f} EUR |",
            f"| Coût total investi   | {total_cost:.2f} EUR |",
            f"| PnL brut total       | {pnl_sign}{total_pnl_brut:.2f} EUR ({pnl_sign}{total_pct:.2f}%) |",
            f"| PnL net total        | {'+' if total_pnl_n>=0 else ''}{total_pnl_n:.2f} EUR |",
            "",
        ]

    # Graphique
    if chart_b64:
        lines += [
            "## Graphique Performance Combinée",
            "",
            f"![Performance normalisée base 100](data:image/png;base64,{chart_b64})",
            "",
        ]

    # Watchlist
    lines += ["", "---", "", "## Watchlist", ""]
    for w in WATCHLIST:
        key_w = w["ticker_eod"]
        r_w   = results.get(key_w)
        if not r_w:
            lines.append(f"**{w['name']}** `{w['ticker_fh']}` — données indisponibles")
            lines.append("")
            continue
        p_val  = r_w["price"]
        p_src  = r_w["p_src"]
        p_str  = f"{p_val:.2f} EUR" if p_val else "N/D"
        synth_w     = r_w.get("synth", "")
        synth_src_w = r_w.get("synth_src", "")

        lines.append(
            f"**{w['name']}** `{w['ticker_fh']}` — {w.get('sector', '')} "
            f"| Cours : {p_str} *(source : {p_src})*"
        )
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

    # Ecriture du rapport
    report_path = "reports/daily_report.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    save_session_cache(session_cache)

    print(f"✅ Rapport généré : {report_path}")
    print(f"✅ Quotas : {_quota_status()}")


if __name__ == "__main__":
    main()
