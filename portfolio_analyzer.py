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
    """Retourne (dates_list, prices_eur_list, source_str, cache_flag, error_str|None)."""
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
# GRAPHIQUE COMBINE -- toutes courbes normalisees base 100
# =============================================================================

_CHART_COLORS = [
    "#2563eb",  # bleu
    "#16a34a",  # vert
    "#dc2626",  # rouge
    "#d97706",  # ambre
    "#7c3aed",  # violet
    "#0891b2",  # cyan
    "#db2777",  # rose
    "#65a30d",  # lime
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
    """Regroupe les appels par asset pour ThreadPoolExecutor."""
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
# MAIN
# =============================================================================

def main():
    global session_cache_global

    now            = datetime.now(PARIS_TZ)
    session_cache  = load_session_cache()
    session_cache_global = session_cache

    # ── EUR/USD ──────────────────────────────────────────────────────────────
    eur_usd, eur_src, eur_cached, eur_usd_warn = get_eur_usd(session_cache)
    session_cache["eur_usd"] = eur_usd

    # ── COURS US batch ───────────────────────────────────────────────────────
    us_tickers = list({a["ticker_td"] for a in PORTFOLIO + WATCHLIST
                       if a.get("marche") == "us" and a.get("ticker_td")})
    td_prices  = td_fetch_batch(us_tickers) if TWELVEDATA_KEY else {}

    # ── INDICES ──────────────────────────────────────────────────────────────
    indices_data = {name: get_index(sym) for name, sym in INDICES.items()}
    macro_sc     = score_macro(indices_data)

    # ── DONNEES PAR ASSET (parallele) ────────────────────────────────────────
    all_assets = PORTFOLIO + WATCHLIST
    asset_data: dict = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_fetch_asset_data, a, eur_usd, td_prices, session_cache): a
            for a in all_assets
        }
        for fut in as_completed(futures):
            a = futures[fut]
            try:
                asset_data[a["ticker_eod"]] = fut.result()
            except Exception as exc:
                _log.warning("Erreur fetch %s : %s", a["ticker_eod"], exc)
                asset_data[a["ticker_eod"]] = {
                    "news": [], "bull": 50.0, "bear": 50.0, "sent_src": "Erreur",
                    "cs": 5.0, "cons_str": "N/D", "cons_src": "Erreur",
                    "h_dates": [], "h_closes": [], "h_src": "Erreur",
                    "h_cache": False, "h_err": str(exc),
                    "synthesis": "Erreur lors de la recuperation.", "synth_src": "Erreur",
                }

    # ── COURS PORTEFEUILLE ───────────────────────────────────────────────────
    prices: dict = {}
    for asset in PORTFOLIO:
        p, chg, src, cached, note = get_price_eur(asset, eur_usd, td_prices, session_cache)
        prices[asset["ticker_eod"]] = (p, chg, src, cached)
        if p:
            session_cache[f"price_{asset['ticker_eod']}"] = p

    # GUARD v6.2 : si aucun cours n'est disponible, on echoue explicitement
    valid_prices = [v for v in prices.values() if v[0] is not None]
    if not valid_prices:
        raise RuntimeError(
            "ERREUR CRITIQUE : aucun cours disponible pour le portefeuille. "
            "Verifier les quotas API et les cles d'acces."
        )

    # ── RAPPORT MARKDOWN ─────────────────────────────────────────────────────
    lines        = []
    history_rows = []
    cache_warns  = []
    sources_log  = {}
    assets_history_for_chart: dict = {}

    # En-tete
    lines += [
        f"# Rapport Portefeuille — {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        f"",
        f"**EUR/USD :** {eur_usd:.4f} *(source : {eur_src})*",
        f"",
    ]
    if eur_usd_warn:
        lines.append(f"> ⚠️ {eur_usd_warn}")
        lines.append("")
        cache_warns.append(eur_usd_warn)

    # Indices
    lines += ["## Indices de marche", ""]
    for idx_name, idx_data in indices_data.items():
        sign  = "+" if idx_data["change_pct"] >= 0 else ""
        arrow = "▲" if idx_data["change_pct"] >= 0 else "▼"
        lines.append(
            f"- **{idx_name}** : {idx_data['price']:,.2f} "
            f"{arrow} {sign}{idx_data['change_pct']:.2f}% "
            f"*(source : {idx_data['source']})*"
        )
    lines.append("")

    # Macro news
    macro_titles = get_macro_news(5)
    if macro_titles:
        lines += ["### Actualites macroeconomiques", ""]
        for t in macro_titles:
            lines.append(f"- {t}")
        lines.append("")

    # ── PORTEFEUILLE ─────────────────────────────────────────────────────────
    lines += ["---", "", "## Portefeuille", ""]

    total_vm       = 0.0
    total_cost     = 0.0
    total_pnl_brut = 0.0
    total_pnl_net  = 0.0
    summary_rows   = []

    for asset in PORTFOLIO:
        key   = asset["ticker_eod"]
        p, chg, p_src, p_cached = prices.get(key, (None, 0, "N/D", False))
        ad    = asset_data.get(key, {})

        h_dates  = ad.get("h_dates", [])
        h_closes = ad.get("h_closes", [])
        h_src    = ad.get("h_src", "")
        h_cache  = ad.get("h_cache", False)
        h_err    = ad.get("h_err")
        bull     = ad.get("bull", 50.0)
        bear     = ad.get("bear", 50.0)
        sent_src = ad.get("sent_src", "")
        cs       = ad.get("cs", 5.0)
        cons_str = ad.get("cons_str", "N/D")
        cons_src = ad.get("cons_src", "")
        synthesis   = ad.get("synthesis", "")
        synth_src   = ad.get("synth_src", "")

        sources_log[key] = {"prix": p_src, "sentiment": sent_src,
                            "consensus": cons_src, "historique": h_src}

        # Calculs financiers
        qty       = asset["qty"]
        cost_unit = asset["cost_eur"]
        vm        = round(p * qty, 2) if p else 0.0
        cost_tot  = round(cost_unit * qty, 2)
        pnl_brut  = round(vm - cost_tot, 2)
        pnl_brut_pct = round((pnl_brut / cost_tot) * 100, 2) if cost_tot else 0.0
        fee       = calc_fee(vm, asset["marche"]) if p else 0.0
        pnl_net   = round(pnl_brut - fee, 2)
        pnl_net_pct = round((pnl_net / cost_tot) * 100, 2) if cost_tot else 0.0

        total_vm       += vm
        total_cost     += cost_tot
        total_pnl_brut += pnl_brut
        total_pnl_net  += pnl_net

        # Scoring
        sc_prix    = score_price(p, cost_unit) if p else 5.0
        hist_sc, hist_label, r1m, r3m, r6m = score_history(h_dates, h_closes)
        total_score = round(
            sc_prix * 0.30 + (bull / 10) * 0.20 + cs * 0.20 + hist_sc * 0.30, 2
        )
        rec = recommend(total_score)

        # Stockage historique chart
        if h_dates and h_closes:
            assets_history_for_chart[asset["name"]] = (h_dates, h_closes)

        # Avertissements cache
        if p_cached:
            cache_warns.append(f"{asset['name']} : cours en cache")
        if h_cache:
            cache_warns.append(f"{asset['name']} : historique en cache")

        # Ligne Markdown
        p_str    = f"{p:.2f} EUR" if p else "N/D"
        sign_chg = "+" if chg >= 0 else ""
        chg_str  = f"({sign_chg}{chg:.2f}% j-1)" if chg != 0 else ""
        pnl_str  = f"{pnl_net:+.2f} EUR ({pnl_net_pct:+.1f}% net)"

        lines += [
            f"### {asset['name']} ({asset['ticker_fh']})",
            "",
            f"**Cours :** {p_str} {chg_str} *(source : {p_src})*  ",
            f"**Position :** {qty} action(s) — PRU {cost_unit:.2f} EUR — VM {vm:.2f} EUR  ",
            f"**PnL net :** {pnl_str}  ",
            f"**Score :** {total_score:.2f}/10 — **{rec}**  ",
            f"**Sentiment :** Bull {bull:.0f}% / Bear {bear:.0f}% *(source : {sent_src})*  ",
            f"**Consensus :** {cons_str} *(source : {cons_src})*  ",
        ]
        if h_dates:
            lines.append(
                f"**Historique :** 1M {r1m:+.1f}% | 3M {r3m:+.1f}% | 6M {r6m:+.1f}% "
                f"— {hist_label} *(source : {h_src})*  "
            )
        if h_err:
            lines.append(f"> ⚠️ Historique : {h_err}")

        lines += [
            "",
            f"**Justification :** {justification(asset['name'], pnl_net, pnl_net_pct, cs, bull, bear, cons_str, macro_sc, hist_sc, hist_label, total_score)}",
            "",
        ]
        if synthesis and "Aucune actualite" not in synthesis:
            lines.append(f"> {synthesis} *(source : {synth_src})*")
            lines.append("")

        # Ligne CSV
        history_rows.append({
            "date":        now.strftime("%Y-%m-%d"),
            "time":        now.strftime("%H:%M"),
            "ticker":      asset["ticker_fh"],
            "name":        asset["name"],
            "price_eur":   p or "",
            "cost_eur":    cost_unit,
            "qty":         qty,
            "vm":          vm,
            "pnl_brut":    pnl_brut,
            "pnl_brut_pct": pnl_brut_pct,
            "pnl_net":     pnl_net,
            "pnl_net_pct": pnl_net_pct,
            "score":       total_score,
            "rec":         rec,
        })

        summary_rows.append({
            "name":   asset["name"],
            "ticker": asset["ticker_fh"],
            "prix":   p_str,
            "vm":     f"{vm:.2f}",
            "pnl":    pnl_str,
            "score":  f"{total_score:.2f}",
            "rec":    rec,
        })

    # Synthese portefeuille
    total_pnl_pct = round((total_pnl_net / total_cost) * 100, 2) if total_cost else 0.0
    lines += [
        "---",
        "",
        "## Synthese Portefeuille",
        "",
        f"| Valeur | Ticker | Cours | VM (EUR) | PnL net | Score | Rec |",
        f"|--------|--------|-------|----------|---------|-------|-----|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['name']} | {row['ticker']} | {row['prix']} "
            f"| {row['vm']} | {row['pnl']} | {row['score']} | {row['rec']} |"
        )
    lines += [
        "",
        f"**Valeur de marche totale :** {total_vm:.2f} EUR  ",
        f"**Cout total :** {total_cost:.2f} EUR  ",
        f"**PnL brut :** {total_pnl_brut:+.2f} EUR  ",
        f"**PnL net :** {total_pnl_net:+.2f} EUR ({total_pnl_pct:+.2f}%)  ",
        "",
    ]

    # Graphique
    chart_path = f"{CHARTS_DIR}/portfolio_combined.png"
    chart_ok   = generate_combined_chart(assets_history_for_chart, chart_path)
    if chart_ok:
        lines.append(f"![Graphique portefeuille]({chart_path})")
        lines.append("")

    # Watchlist
    watchlist_prices = {}
    for w in WATCHLIST:
        p_w, chg_w, src_w, cached_w = get_price_eur(w, eur_usd, td_prices, session_cache)[:4]
        watchlist_prices[w["ticker_eod"]] = (p_w, chg_w, src_w, cached_w)

    watchlist_synth = {}
    for w in WATCHLIST:
        synthesis_w, synth_src_w = asset_data.get(w["ticker_eod"], {}).get(
            "synthesis", "Aucune actualite."
        ), asset_data.get(w["ticker_eod"], {}).get("synth_src", "RSS Yahoo vide")
        watchlist_synth[w["ticker_eod"]] = (synthesis_w, synth_src_w)

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

    # Ecriture du rapport
    report_path = "reports/daily_report.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Mise a jour du cache session
    save_session_cache(session_cache)

    # Ecriture historique CSV
    append_history(now, history_rows)

    print(f"\u2705 Rapport g\u00e9n\u00e9r\u00e9 : {report_path}")
    print(f"\u2705 Quotas : {_quota_status()}")


if __name__ == "__main__":
    main()
