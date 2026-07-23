#!/usr/bin/env python3
"""
Portfolio Analyzer v6.4
================================================================================
CHANGEMENTS v6.4 par rapport à v6.3 :

1. PORTEFEUILLE — JCDecaux (DEC.PA) supprimé : 2 actions vendues à 19,26 €.

2. HISTORIQUE — get_monthly_history() appelé avec months=1 au lieu de months=3
   (problèmes de collecte et d'échelle avec 3 mois).

TOUTES LES AUTRES FONCTIONS sont identiques à v6.3.
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
_QUOTA = {
    "alphavantage": {"used": 0, "limit": 20},
    "twelvedata":   {"used": 0, "limit": 60},
    "eodhd":        {"used": 0, "limit": 80},
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
        clean