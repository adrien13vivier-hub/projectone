#!/usr/bin/env python3
"""
Portfolio Analyzer v7.0 -- MOTEUR MULTI-UTILISATEUR
================================================================================
Le script n'est plus calque sur un portefeuille en dur. Il prend un PROFIL en
entree (JSON) et produit un rapport isole par utilisateur.

UTILISATION
-----------
  python portfolio_analyzer.py --portfolio data/portfolios/portfolio_alice.json
  python portfolio_analyzer.py --user alice
  python portfolio_analyzer.py --all-users        # les 5 profils en un seul run

ISOLATION PAR UTILISATEUR
-------------------------
  reports/<user>/history.csv          historique CSV
  reports/<user>/daily_report.md      rapport Markdown
  reports/<user>/charts/              graphiques PNG
  docs/<user>/index.html              page consultable (Cloudflare)

MUTUALISATION DES APPELS API
----------------------------
  cache/market_cache.json est PARTAGE par tous les utilisateurs : les donnees
  de marche sont indexees par ticker, pas par personne.
  En mode --all-users, un memo en RAM (_MEMO) garantit qu'un ticker detenu par
  plusieurs utilisateurs n'est interroge qu'UNE SEULE FOIS.
  Exemple : 5 utilisateurs detenant Palantir = 1 appel, pas 5.

PARAMETRES PORTES PAR LE PROFIL (et non plus codes en dur)
----------------------------------------------------------
  lignes du portefeuille, watchlist, indices suivis, courtier et sa grille de
  frais, devise de reference.

Format du profil : voir api/load_portfolio.py
================================================================================
"""

import os
import sys
import argparse
import re as _re
import csv
import json
import logging
import time
import threading
import shutil
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

# --- CHEMINS ------------------------------------------------------------------
# Le cache de MARCHE est volontairement PARTAGE : les cours, historiques et
# sentiments sont des donnees publiques identiques pour tous les utilisateurs.
# C'est ce qui permet de ne pas multiplier les appels API par le nombre de
# comptes.
CACHE_PATH        = "cache/market_cache.json"
PORTFOLIOS_DIR    = "data/portfolios"
BROKERS_PATH      = "data/brokers.json"
LEGACY_CACHE_PATH = "cache/session_cache.json"

# Chemins propres a l'utilisateur courant -- reaffectes par set_user().
USER         = "default"
HISTORY_PATH = "reports/default/history.csv"
CHARTS_DIR   = "reports/default/charts"
REPORT_PATH  = "reports/default/daily_report.md"


def slugify(value: str) -> str:
    """Normalise un nom d'utilisateur en identifiant de dossier sur."""
    s = _re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "default").strip().lower())
    return s.strip("-") or "default"


def set_user(username: str):
    """Bascule tous les chemins de sortie vers l'utilisateur indique."""
    global USER, HISTORY_PATH, CHARTS_DIR, REPORT_PATH
    USER         = slugify(username)
    HISTORY_PATH = f"reports/{USER}/history.csv"
    CHARTS_DIR   = f"reports/{USER}/charts"
    REPORT_PATH  = f"reports/{USER}/daily_report.md"
    os.makedirs(CHARTS_DIR, exist_ok=True)
    os.makedirs(f"docs/{USER}", exist_ok=True)
    _migrate_legacy_files()


def _migrate_legacy_files():
    """Reprend le cache de marche de l'ancienne version.

    Le cache contient des donnees publiques indexees par ticker : il est
    legitimement partageable entre tous les utilisateurs.
    L'ancien reports/history.csv n'est PAS repris automatiquement : il
    appartient a un seul utilisateur et le recopier partout fausserait les
    historiques. Le deplacer une fois a la main (voir README).
    """
    try:
        if os.path.exists(LEGACY_CACHE_PATH) and not os.path.exists(CACHE_PATH):
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            shutil.copyfile(LEGACY_CACHE_PATH, CACHE_PATH)
    except Exception as e:
        _log.warning("Migration ancien format ignoree : %s", e)

# --- FENETRE HISTORIQUE (1 mois) --------------------------------------------
HISTORY_DAYS      = 180     # profondeur de collecte, en cotations JOURNALIERES
CHART_WINDOW_DAYS = 30      # fenetre reellement affichee sur le graphique (1 mois)
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


# --- PROFIL UTILISATEUR -------------------------------------------------------
# Ces quatre structures ne contiennent plus rien en dur : elles sont remplies
# par apply_profile() a partir du JSON de l'utilisateur.

PORTFOLIO: list = []
WATCHLIST: list = []

# Indices macro par defaut. Un profil peut fournir sa propre selection.
DEFAULT_INDICES = {
    "S&P 500":    {"eod": "GSPC.INDX", "fh": "^GSPC"},
    "CAC 40":     {"eod": "FCHI.INDX", "fh": "^FCHI"},
    "Nikkei 225": {"eod": "N225.INDX", "fh": "^N225"},
}
INDICES = dict(DEFAULT_INDICES)

# Grille de frais neutre, utilisee si le profil ne precise aucun courtier.
DEFAULT_BROKERAGE = {
    "euronext": {"threshold": 500,  "flat": 1.99, "rate": 0.006,  "min": 1.99},
    "us":       {"threshold": 6000, "flat": 6.95, "rate": 0.0012, "min": 6.95},
}
BROKERAGE   = {k: dict(v) for k, v in DEFAULT_BROKERAGE.items()}
BROKER_NAME = "Grille par defaut"

PROFILE: dict = {}


def apply_profile(profile: dict):
    """Charge un profil utilisateur dans l'etat global du module."""
    global PORTFOLIO, WATCHLIST, INDICES, BROKERAGE, BROKER_NAME, PROFILE

    PROFILE   = profile or {}
    settings  = PROFILE.get("settings") or {}

    PORTFOLIO = PROFILE.get("lines") or []
    WATCHLIST = settings.get("watchlist") or []

    idx = settings.get("indices")
    if isinstance(idx, dict) and idx:
        INDICES = idx
    elif isinstance(idx, list) and idx:
        INDICES = {n: DEFAULT_INDICES[n] for n in idx if n in DEFAULT_INDICES} or dict(DEFAULT_INDICES)
    else:
        INDICES = dict(DEFAULT_INDICES)

    fees = settings.get("fees")
    if isinstance(fees, dict) and fees:
        BROKERAGE = {k: dict(v) for k, v in fees.items()}
    else:
        BROKERAGE = {k: dict(v) for k, v in DEFAULT_BROKERAGE.items()}
    BROKER_NAME = settings.get("broker_label") or settings.get("broker") or "Grille par defaut"

    set_user(PROFILE.get("username") or "default")


def calc_fee(amount: float, marche: str) -> float:
    """Frais de courtage pour un montant donne, selon la grille du profil."""
    t = BROKERAGE.get(marche) or BROKERAGE.get("euronext") or DEFAULT_BROKERAGE["euronext"]
    flat  = float(t.get("flat", 0.0))
    rate  = float(t.get("rate", 0.0))
    seuil = float(t.get("threshold", 0.0))
    mini  = float(t.get("min", 0.0))
    brut  = flat if (seuil and amount <= seuil) else rate * amount
    return round(max(brut, mini), 2)


# =============================================================================
# MUTUALISATION DES APPELS API
# =============================================================================
# Indexe par TICKER et non par utilisateur : si trois profils detiennent la
# meme valeur, elle n'est interrogee qu'une fois pour l'ensemble du run.

_MEMO: dict = {}


def memo_stats() -> dict:
    return {"entrees": len(_MEMO)}


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
                         headers={"User-Agent": "Mozilla/5.0 PortfolioAnalyzer/6.3"})
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


def _eodhd_daily(ticker_eod: str, from_d: str, to_d: str, fx: float = 1.0) -> tuple:
    """Cotations JOURNALIERES EODHD. Retourne (dates, closes, erreur)."""
    data, err = _get(f"{EOD_BASE}/eod/{ticker_eod}",
                     {"api_token": EODHD_KEY, "fmt": "json",
                      "period": "d", "from": from_d, "to": to_d},
                     "eodhd")
    if isinstance(data, list) and len(data) >= 2 and not _is_quota_error(err):
        dates, closes = [], []
        for row in data:
            px = row.get("adjusted_close") or row.get("close")
            if not px:
                continue
            try:
                dates.append(str(row["date"])[:10])
                closes.append(round(float(px) * fx, 4))
            except (ValueError, TypeError, KeyError):
                continue
        if len(dates) >= 2:
            return dates, closes, None
    return [], [], ("quota atteint" if _is_quota_error(err) else (err or "vide"))


def get_monthly_history(asset: dict, eur_usd: float, days: int = HISTORY_DAYS) -> tuple:
    from_d    = str(date.today() - timedelta(days=days))
    to_d      = str(date.today())
    cache_key = f"hist_{asset['ticker_eod']}"

    if asset.get("marche") == "us":
        ticker_av = asset.get("ticker_av")
        if ALPHAVANTAGE_KEY and ticker_av:
            data, err = _get(AV_BASE, {
                "function":   "TIME_SERIES_DAILY",
                "symbol":     ticker_av,
                "outputsize": "compact",
                "apikey":     ALPHAVANTAGE_KEY,
            }, "alphavantage")
            ts = data.get("Time Series (Daily)") if isinstance(data, dict) else None
            if ts and not _is_quota_error(err):
                dates  = []
                closes = []
                for day_str, vals in sorted(ts.items()):
                    if day_str < from_d:
                        continue
                    try:
                        dates.append(day_str[:10])
                        closes.append(round(float(vals["4. close"]) * eur_usd, 4))
                    except (ValueError, TypeError, KeyError):
                        pass
                if len(dates) >= 2:
                    return dates, closes, "AlphaVantage", False, None
            av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            av_err = "cle absente" if not ALPHAVANTAGE_KEY else "ticker_av absent"

        if EODHD_KEY:
            dates, closes, eod_err = _eodhd_daily(asset["ticker_eod"], from_d, to_d, eur_usd)
            if dates:
                return dates, closes, f"EODHD (fallback AV:{av_err})", False, None
        else:
            eod_err = "cle absente"

        if FINNHUB_KEY:
            dates, closes, src, cache_flag, err_str = _finnhub_candles(asset, eur_usd, days)
            if dates:
                return dates, closes, f"Finnhub (fallback AV:{av_err}, EODHD:{eod_err})", cache_flag, err_str
            fh_err = err_str or "vide"
        else:
            fh_err = "cle absente"

        if session_cache_global.get(cache_key):
            saved_at = session_cache_global.get("saved_at", "date inconnue")
            cached   = session_cache_global[cache_key]
            return (cached.get("dates", []), cached.get("closes", []),
                    "Cache", True,
                    f"Historique US non disponible (AV:{av_err}, EODHD:{eod_err}, FH:{fh_err}) -- cache du {saved_at}")
        return ([], [], f"Indisponible (AV:{av_err}, EODHD:{eod_err}, FH:{fh_err})", False,
                "Historique indisponible -- graphique non genere")

    else:
        if EODHD_KEY:
            dates, closes, eod_err = _eodhd_daily(asset["ticker_eod"], from_d, to_d, 1.0)
            if dates:
                return dates, closes, "EODHD", False, None
        else:
            eod_err = "cle absente"

        if FINNHUB_KEY:
            dates, closes, src, cache_flag, err_str = _finnhub_candles(asset, eur_usd, days)
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


def _finnhub_candles(asset: dict, eur_usd: float, days: int) -> tuple:
    from_ts = int((datetime.now() - timedelta(days=days)).timestamp())
    to_ts   = int(datetime.now().timestamp())
    data, err = _get(f"{FH_BASE}/stock/candle",
                     {"symbol": asset["ticker_fh"], "resolution": "D",
                      "from": from_ts, "to": to_ts, "token": FINNHUB_KEY},
                     "finnhub")
    if isinstance(data, dict) and data.get("s") == "ok" and data.get("c") and not _is_quota_error(err):
        daily: dict = {}
        for ts, cl in zip(data["t"], data["c"]):
            day_key = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            daily[day_key] = cl
        dates  = sorted(daily.keys())
        closes = [round(daily[k] * eur_usd, 4)
                  if asset.get("marche") == "us" else round(daily[k], 4)
                  for k in dates]
        return dates, closes, "Finnhub", False, None
    err_str = "quota atteint" if _is_quota_error(err) else (err or "vide")
    return [], [], "Finnhub", False, err_str


# =============================================================================
# SCORING
# =============================================================================

def _parse_serie(dates: list, closes: list) -> list:
    """(date, cours) triee. Tolere "YYYY-MM-DD" et "YYYY-MM" (ancien cache)."""
    serie = []
    for d, c in zip(dates or [], closes or []):
        try:
            s = str(d)
            iso = s + "-01" if len(s) == 7 else s[:10]
            dt  = datetime.strptime(iso, "%Y-%m-%d")
            v   = float(c)
            if v > 0:
                serie.append((dt, v))
        except Exception:
            continue
    serie.sort(key=lambda x: x[0])
    return serie


def score_history(dates: list, closes: list) -> tuple:
    if len(closes) < 2:
        return 5.0, "NEUTRE", 0.0, 0.0, 0.0

    serie = _parse_serie(dates, closes)
    if len(serie) < 2:
        return 5.0, "NEUTRE", 0.0, 0.0, 0.0

    last_dt, last_px = serie[-1]

    def ret_since(nb_days: int) -> float:
        """Rendement depuis la cotation la plus proche d'il y a nb_days."""
        target = last_dt - timedelta(days=nb_days)
        passe  = [px for dt, px in serie if dt <= target]
        ref    = passe[-1] if passe else serie[0][1]
        if ref <= 0:
            return 0.0
        return (last_px / ref - 1) * 100

    ret_1m = ret_since(30)
    ret_3m = ret_since(90)
    ret_6m = ret_since(180)
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
# GRAPHIQUE COMBINE  — FIX v6.3
# =============================================================================

_CHART_COLORS = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706",
    "#7c3aed", "#0891b2", "#db2777", "#65a30d",
]


def generate_combined_chart(assets_history: dict, chart_path: str) -> bool:
    try:
        import os
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=CHART_WINDOW_DAYS)

        # --- 1. Parsing de TOUT l'historique disponible, actif par actif ------
        #     (pas de filtre ici : les points anterieurs a la fenetre servent
        #      a amorcer les courbes qui demarrent tard)
        series = {}
        for name, (dates, closes) in assets_history.items():
            points = {}
            for d, c in zip(dates or [], closes or []):
                try:
                    s = str(d)
                    iso = s + "-01" if len(s) == 7 else s[:10]
                    dt  = datetime.strptime(iso, "%Y-%m-%d")
                    val = float(c)
                    if val > 0:
                        points[dt] = val
                except Exception:
                    continue
            if points:
                series[name] = points

        if not series:
            return False

        # --- 2. Axe X COMMUN : les dates situees dans la fenetre 1 mois ------
        common_dates = sorted({dt for pts in series.values() for dt in pts if dt >= cutoff})
        if len(common_dates) < 2:
            # Aucune donnee recente : on retombe sur le dernier mois
            # reellement disponible plutot que d'abandonner le graphique.
            toutes = sorted({dt for pts in series.values() for dt in pts})
            if len(toutes) < 2:
                return False
            borne = toutes[-1] - timedelta(days=CHART_WINDOW_DAYS)
            common_dates = [dt for dt in toutes if dt >= borne]
            if len(common_dates) < 2:
                common_dates = toutes[-2:]

        debut = common_dates[0]

        # --- 3. Projection de CHAQUE actif sur l'axe complet ------------------
        #     amorcage sur le dernier cours connu AVANT la fenetre, puis
        #     forward-fill. Toute valeur ayant au moins 1 cotation est tracee
        #     et couvre 100% de l'axe X.
        valid = {}
        for name, pts in series.items():
            avant = [px for dt, px in sorted(pts.items()) if dt < debut]
            last  = avant[-1] if avant else None

            filled = []
            for dt in common_dates:
                v = pts.get(dt)
                if v is not None:
                    last = v
                filled.append(last)

            first_known = next((v for v in filled if v is not None), None)
            if first_known is None or first_known <= 0:
                continue
            filled = [v if v is not None else first_known for v in filled]

            base = filled[0]
            if base <= 0:
                continue

            valid[name] = (common_dates, [round(v / base * 100, 2) for v in filled])

        if not valid:
            return False

        os.makedirs(os.path.dirname(chart_path), exist_ok=True)

        fig, ax = plt.subplots(figsize=(12, 5))
        fig.patch.set_facecolor("#f9f8f5")
        ax.set_facecolor("#f9f8f5")

        colors = [
            "#2563eb", "#16a34a", "#dc2626", "#d97706",
            "#7c3aed", "#0891b2", "#db2777", "#65a30d",
        ]

        all_y = []
        all_x = []

        for idx, (name, (dt_list, normalized)) in enumerate(valid.items()):
            color = colors[idx % len(colors)]
            perf_finale = normalized[-1] - 100
            all_y.extend(normalized)
            all_x.extend(dt_list)

            ax.plot(
                dt_list, normalized,
                color=color, linewidth=2.2,
                marker="o", markersize=4,
                label=f"{name} ({perf_finale:+.1f}%)",
                zorder=3,
            )
            ax.annotate(
                f"{normalized[-1]:.0f}",
                (dt_list[-1], normalized[-1]),
                textcoords="offset points", xytext=(6, 0),
                fontsize=7.5, color=color, fontweight="bold",
            )

        ax.axhline(
            y=100, color="#9ca3af", linestyle="--",
            linewidth=1.2, alpha=0.8,
            label="Base 100 (début de période)", zorder=2
        )

        ax.relim()
        ax.autoscale_view()

        if all_y:
            y_min = min(min(all_y), 100)
            y_max = max(max(all_y), 100)
            pad = max((y_max - y_min) * 0.12, 3)
            ax.set_ylim(y_min - pad, y_max + pad)

        if all_x:
            ax.set_xlim(min(all_x) - timedelta(days=1), max(all_x) + timedelta(days=2))

        locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        ax.tick_params(axis="y", labelsize=8)
        ax.set_ylabel("Performance (base 100)", fontsize=8, color="#6b7280")

        ax.grid(axis="y", linestyle=":", alpha=0.4, color="#d1d5db")
        ax.grid(axis="x", linestyle=":", alpha=0.2, color="#d1d5db")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#e5e7eb")
        ax.spines["bottom"].set_color("#e5e7eb")

        ax.set_title(
            "Performance comparée du portefeuille — base 100 (30 derniers jours, EUR)",
            fontsize=11, fontweight="bold", color="#111827", pad=14,
        )
        ax.legend(
            fontsize=8, framealpha=0.7, loc="upper left",
            bbox_to_anchor=(0.01, 0.99), ncol=2,
        )

        plt.tight_layout()
        plt.savefig(
            chart_path, dpi=130, bbox_inches="tight",
            facecolor=fig.get_facecolor()
        )
        plt.close(fig)
        return True

    except Exception:
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

def main(profile: dict = None, shared_cache: dict = None, save_cache: bool = True):
    """Produit le rapport d'UN utilisateur.

    profile      : dict issu de load_profile(). Si None, on garde l'etat courant.
    shared_cache : cache de marche partage entre plusieurs utilisateurs d'un
                   meme run (mode --all-users). Si None, il est charge/sauve ici.
    """
    global session_cache_global

    if profile is not None:
        apply_profile(profile)

    if not PORTFOLIO:
        _log.error("Portefeuille vide pour '%s' -- rien a analyser.", USER)
        return False

    now = datetime.now(PARIS_TZ)
    os.makedirs(CHARTS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    os.makedirs("cache", exist_ok=True)
    os.makedirs(f"docs/{USER}", exist_ok=True)

    session_cache = shared_cache if shared_cache is not None else load_session_cache()
    session_cache_global = session_cache

    # ── 1. EUR/USD ────────────────────────────────────────────────────────────
    eur_usd, eur_usd_src, eur_usd_cache, eur_usd_warn = get_eur_usd(session_cache)
    session_cache["eur_usd"] = eur_usd

    # ── 2. Cours US en batch (TwelveData) ─────────────────────────────────────
    us_tickers = [a["ticker_td"] for a in PORTFOLIO if a.get("ticker_td")]
    us_tickers += [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    td_prices = td_fetch_batch(list(set(filter(None, us_tickers)))) if TWELVEDATA_KEY else {}

    # ── 3. Cours par position + données parallèles ────────────────────────────
    # Seuls les tickers encore inconnus du memo sont interroges : c'est ici que
    # se joue la mutualisation entre utilisateurs.
    a_faire_px = {a["ticker_eod"]: a for a in PORTFOLIO
                  if f"px:{a['ticker_eod']}" not in _MEMO}
    a_faire_ad = {a["ticker_eod"]: a for a in PORTFOLIO
                  if f"ad:{a['ticker_eod']}" not in _MEMO}

    if a_faire_px:
        with ThreadPoolExecutor(max_workers=4) as exe:
            price_futures = {
                exe.submit(get_price_eur, a, eur_usd, td_prices, session_cache): a
                for a in a_faire_px.values()
            }
            for fut in as_completed(price_futures):
                a = price_futures[fut]
                try:
                    _MEMO[f"px:{a['ticker_eod']}"] = fut.result()
                except Exception as e:
                    _log.warning("Cours %s : %s", a["ticker_eod"], e)
                    _MEMO[f"px:{a['ticker_eod']}"] = (None, 0.0, "Erreur", False, str(e))

    if a_faire_ad:
        with ThreadPoolExecutor(max_workers=4) as exe:
            data_futures = {
                exe.submit(_fetch_asset_data, a, eur_usd, td_prices, session_cache): a
                for a in a_faire_ad.values()
            }
            for fut in as_completed(data_futures):
                a = data_futures[fut]
                try:
                    _MEMO[f"ad:{a['ticker_eod']}"] = fut.result()
                except Exception as e:
                    _log.warning("Données %s : %s", a["ticker_eod"], e)
                    _MEMO[f"ad:{a['ticker_eod']}"] = {
                    "news": [], "bull": 50.0, "bear": 50.0, "sent_src": "erreur",
                    "cs": 5.0, "cons_str": "N/D", "cons_src": "erreur",
                    "h_dates": [], "h_closes": [], "h_src": "erreur",
                    "h_cache": False, "h_err": str(e),
                        "synthesis": "Données indisponibles.", "synth_src": "",
                    }

    prices     = {a["ticker_eod"]: _MEMO[f"px:{a['ticker_eod']}"] for a in PORTFOLIO}
    asset_data = {a["ticker_eod"]: _MEMO[f"ad:{a['ticker_eod']}"] for a in PORTFOLIO}

    # ── 4. Indices macro ──────────────────────────────────────────────────────
    indices_data = {}
    for idx_name, idx_sym in INDICES.items():
        indices_data[idx_name] = get_index(idx_sym)

    macro_score = score_macro(indices_data)

    # ── 5. Watchlist cours ────────────────────────────────────────────────────
    watchlist_prices = {}
    for w in WATCHLIST:
        k = f"wpx:{w['ticker_eod']}"
        if k not in _MEMO:
            p, chg, src, from_cache, note = get_price_eur(w, eur_usd, td_prices, session_cache)
            _MEMO[k] = (p, chg, src, from_cache)
        watchlist_prices[w["ticker_eod"]] = _MEMO[k]

    # ── 6. Watchlist news (RSS) ───────────────────────────────────────────────
    watchlist_synth = {}
    for w in WATCHLIST:
        k = f"wsy:{w['ticker_eod']}"
        if k not in _MEMO:
            _MEMO[k] = get_news_synthesis(w)
        watchlist_synth[w["ticker_eod"]] = _MEMO[k]

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

        if h_closes and not d.get("h_cache"):
            session_cache[f"hist_{key}"] = {"dates": h_dates, "closes": h_closes}

        if price_eur and not price_cache:
            session_cache[f"price_{key}"] = price_eur

        if price_eur is None:
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

        if price_cache and price_note:
            cache_warns.append(f"{asset['name']} -- cours : {price_note}")
        if d.get("h_cache") and d.get("h_err"):
            cache_warns.append(f"{asset['name']} -- historique : {d['h_err']}")

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
    chart_path   = os.path.join(CHARTS_DIR, "portfolio_combined.png")
    chart_ok     = generate_combined_chart(assets_history, chart_path)

    # ── 11. Sauvegarde cache ──────────────────────────────────────────────────
    if save_cache:
        save_session_cache(session_cache)

    # ── 12. Historique CSV ────────────────────────────────────────────────────
    append_history(now, history_rows)

    # ── 13. Génération du rapport Markdown ───────────────────────────────────
    macro_trend = "Haussiere" if macro_score >= 6 else "Baissiere" if macro_score <= 4 else "Neutre"

    lines = [
        f"# Rapport de Portefeuille v7.0 -- {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
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
            f"**Consensus analystes :** {r['cons_str']} *(source : {r['cons_src']})*",
            f"**Perf. historique :** 1M {ret_1m_s} | 3M {ret_3m_s} | 6M {ret_6m_s} -- {r['hist_label']} *(source : {r['h_src']})*",
            "",
            f"**Justification :** {r['just']}",
            "",
            "---",
            "",
        ]

    # ── Synthèse portefeuille ─────────────────────────────────────────────────
    lines += [
        "## Synthese Portefeuille",
        "",
        "| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Score | Recomm. |",
        "|--------|-----------|--------|----------|---------|-------|---------|",
    ]
    for r in results:
        pnl_b_sign = "+" if r["pnl_brut"] >= 0 else "-"
        pnl_n_sign = "+" if r["pnl_net"] >= 0 else "-"
        lines.append(
            f"| {r['asset']['name']} | {r['price_eur']:.2f} | {r['vm']:.2f} "
            f"| {pnl_b_sign}{abs(r['pnl_brut']):.2f} ({pnl_b_sign}{abs(r['pnl_brut_pct']):.1f}%) "
            f"| {pnl_n_sign}{abs(r['pnl_net']):.2f} ({pnl_n_sign}{abs(r['pnl_net_pct']):.1f}%) "
            f"| {r['score']}/10 | {r['rec']} |"
        )

    total_pnl_b_sign = "+" if total_pnl_brut >= 0 else "-"
    total_pnl_n_sign = "+" if total_pnl_net  >= 0 else "-"
    lines += [
        f"| **TOTAL** | — | **{total_vm:.2f}** "
        f"| **{total_pnl_b_sign}{abs(total_pnl_brut):.2f} ({total_pnl_b_sign}{abs(total_pnl_brut_pct):.1f}%)** "
        f"| **{total_pnl_n_sign}{abs(total_pnl_net):.2f} ({total_pnl_n_sign}{abs(total_pnl_net_pct):.1f}%)** "
        f"| — | — |",
        "",
        "---",
        "",
    ]

    # ── Watchlist ─────────────────────────────────────────────────────────────
    lines += ["## Watchlist", "", "| Valeur | Secteur | Cours EUR | Variation | Actualite |",
              "|--------|---------|-----------|-----------|-----------|"]
    for w in WATCHLIST:
        p, chg, src, from_cache = watchlist_prices.get(w["ticker_eod"], (None, 0.0, "N/D", False))
        synth_txt, _ = watchlist_synth.get(w["ticker_eod"], ("—", ""))
        if p:
            sym  = "^" if chg >= 0 else "v"
            sign = "+" if chg >= 0 else ""
            p_str   = f"{p:.2f} EUR{'*' if from_cache else ''}"
            chg_str = f"{sym} {sign}{chg:.2f}%"
        else:
            p_str = chg_str = "N/D"
        short_synth = (synth_txt[:80] + "…") if len(synth_txt) > 80 else synth_txt
        lines.append(f"| {w['name']} | {w['sector']} | {p_str} | {chg_str} | {short_synth} |")

    lines += ["", "---", ""]

    # ── Sources & quotas ──────────────────────────────────────────────────────
    lines += ["## Sources et Quotas", ""]
    for k, v in sources_log.items():
        if isinstance(v, dict):
            parts = ", ".join(f"{sk}: {sv}" for sk, sv in v.items())
            lines.append(f"- **{k}** : {parts}")
        else:
            lines.append(f"- **{k}** : {v}")

    lines += ["", f"**Quotas API utilisés :** {_quota_status()}", ""]
    lines += [f"**Profil :** {PROFILE.get('username', USER)} | "
              f"**Courtier :** {BROKER_NAME}", ""]

    if cache_warns:
        lines += ["", "## Avertissements Cache", ""]
        for w in cache_warns:
            lines.append(f"- ⚠️  {w}")
        lines.append("")

    if eur_usd_warn:
        lines += ["", f"> ⚠️  {eur_usd_warn}", ""]

    report_path = REPORT_PATH
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Rapport généré : {report_path}")
    print(f"Quotas finaux  : {_quota_status()}")
    return True


# =============================================================================
# CHARGEMENT DES PROFILS
# =============================================================================

def _normaliser(raw: dict, username: str = None) -> dict:
    """Convertit un JSON de profil vers le format interne.

    On delegue a api/load_portfolio.py quand il est disponible (c'est lui qui
    porte la logique de derivation des tickers et des grilles de courtiers) ;
    sinon on suppose que le JSON est deja au format interne.
    """
    try:
        from api.load_portfolio import normalize_profile
        return normalize_profile(raw, username)
    except Exception as e:
        _log.warning("Normalisation par defaut (api/load_portfolio indisponible : %s)", e)
        prof = dict(raw or {})
        prof.setdefault("username", username or "default")
        prof.setdefault("lines", [])
        prof.setdefault("settings", {})
        return prof


def load_profile(path: str, username: str = None) -> dict:
    """Charge un profil depuis un fichier JSON."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return _normaliser(raw, username or raw.get("username"))


def discover_profiles() -> list:
    """Retourne tous les profils presents dans data/portfolios/."""
    profils = []
    if not os.path.isdir(PORTFOLIOS_DIR):
        return profils
    for fname in sorted(os.listdir(PORTFOLIOS_DIR)):
        if not fname.endswith(".json"):
            continue
        chemin = os.path.join(PORTFOLIOS_DIR, fname)
        uname  = fname[len("portfolio_"):-len(".json")] if fname.startswith("portfolio_") \
                 else fname[:-len(".json")]
        try:
            profils.append(load_profile(chemin, uname))
        except Exception as e:
            _log.error("Profil illisible %s : %s", chemin, e)
    return profils


def run_all_users() -> int:
    """Traite tous les profils dans UN SEUL processus.

    Le cache de marche et le memo sont partages : un ticker detenu par
    plusieurs utilisateurs n'entraine qu'un seul appel API.
    """
    profils = discover_profiles()
    if not profils:
        _log.error("Aucun profil dans %s", PORTFOLIOS_DIR)
        return 1

    cache = load_session_cache()
    ok_count = 0
    for prof in profils:
        uname = prof.get("username", "?")
        print(f"\n=== Analyse : {uname} ({len(prof.get('lines', []))} ligne(s)) ===")
        try:
            if main(prof, shared_cache=cache, save_cache=False):
                ok_count += 1
        except Exception as e:
            _log.error("Echec pour %s : %s", uname, e)

    save_session_cache(cache)
    print(f"\n{ok_count}/{len(profils)} profil(s) traite(s). "
          f"Appels mutualises : {len(_MEMO)} entrees en memo pour "
          f"{sum(len(p.get('lines', [])) for p in profils)} ligne(s) cumulees.")
    print(f"Quotas finaux : {_quota_status()}")
    return 0 if ok_count else 1


def cli():
    ap = argparse.ArgumentParser(
        description="Analyseur de portefeuille multi-utilisateur."
    )
    ap.add_argument("--portfolio", help="Chemin vers un JSON de profil.")
    ap.add_argument("--user",      help="Nom d'utilisateur (lit data/portfolios/portfolio_<user>.json).")
    ap.add_argument("--all-users", action="store_true",
                    help="Traite tous les profils en un seul run (mutualise les appels API).")
    args = ap.parse_args()

    if args.all_users:
        return run_all_users()

    if args.portfolio:
        chemin = args.portfolio
        uname  = args.user
    elif args.user:
        chemin = os.path.join(PORTFOLIOS_DIR, f"portfolio_{slugify(args.user)}.json")
        uname  = args.user
    else:
        ap.error("Preciser --portfolio, --user ou --all-users.")
        return 2

    if not os.path.exists(chemin):
        _log.error("Profil introuvable : %s", chemin)
        return 1

    profil = load_profile(chemin, uname)
    return 0 if main(profil) else 1


if __name__ == "__main__":
    sys.exit(cli())
