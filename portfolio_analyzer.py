#!/usr/bin/env python3
"""
Portfolio Analyzer v5.5
================================================================================
ARCHITECTURE DES CLES API v5.5 - OPTIMISATION QUOTAS PLANS GRATUITS

  Cle API          | Mission v5.5                                  | Quota gratuit reel
  AlphaVantage     | EUR/USD * Historique US * Sentiment US (NLP)  | 25 req/jour -> ~7/run
  TwelveData       | Cours US temps reel (batch)                   | 800/jour  -> <=9/run
  EODHD            | Cours EU * Indices * News EU * Historique EU  | 20/jour   -> ~12/run
  Finnhub          | Sentiment EU * Consensus * News US watchlist  | 60/min illimite/jour
  OpenRouter       | Synthese RSS Yahoo Finance (DeepSeek v3 free) | illimite (free tier)
                   | Fallback donnees si EODHD/autres echouent     |

  REGLES CLES v5.5 :
  - EODHD N'EST JAMAIS appele pour les cours US si TwelveData a repondu.
  - AlphaVantage NEWS_SENTIMENT remplace Finnhub pour le sentiment des valeurs US.
  - AlphaVantage TIME_SERIES_MONTHLY pour l'historique US.
  - News societes EU (DEC.PA, ACA.PA, ABNX.PA) -> EODHD seul.
  - News societes US (watchlist) -> Finnhub company-news (libere EODHD).
  - Finnhub assure le sentiment des valeurs Euronext (.PA).
  - OpenRouter/DeepSeek v3 flash :
      * Flux RSS Yahoo Finance -> titres bruts -> synthese 2-3 phrases FR par asset
      * La synthese est nettoyee (\n internes supprimes) -> blockquote Markdown mono-ligne
      * Fallback si une source de donnees principale echoue completement
  - Logs : niveau WARNING uniquement (compatible cron / stdout silencieux).

  BUDGET APPELS PAR RUN :
    AlphaVantage : 1 (EUR/USD) + 3 (hist US) + 3-6 (sentiment US) = ~7-10/run
    TwelveData   : <=9 (cours US batch)
    EODHD        : 3 (cours EU) + 3 (indices) + 3 (news EU) + 3 (hist EU) = ~12/run
    Finnhub      : 3 (sentiment EU) + 6 (consensus) + 3 (news US) = ~12-15/run
    OpenRouter   : 1 appel par asset (RSS + synthese) = ~12/run (portfolio + watchlist)

Scoring v5.5 (inchange) :
  Prix vs PRU        : 30 %
  Sentiment presse   : 20 %
  Consensus analystes: 20 %
  Historique mensuel : 30 %
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
OPENROUTER_KEY   = os.environ.get("OPENROUTER_API_KEY", "")

for k, v in [("FINNHUB_API_KEY", FINNHUB_KEY), ("EODHD_API_KEY", EODHD_KEY),
             ("TWELVEDATA_API_KEY", TWELVEDATA_KEY), ("ALPHAVANTAGE_API_KEY", ALPHAVANTAGE_KEY),
             ("OPENROUTER_API_KEY", OPENROUTER_KEY)]:
    if not v:
        _log.warning("Cle absente : %s -- fallback cache active pour cette source", k)

FH_BASE  = "https://finnhub.io/api/v1"
EOD_BASE = "https://eodhd.com/api"
TD_BASE  = "https://api.twelvedata.com"
AV_BASE  = "https://www.alphavantage.co/query"
OR_BASE  = "https://openrouter.ai/api/v1/chat/completions"
OR_MODEL = "deepseek/deepseek-chat-v3-0324:free"
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
    "alphavantage": {"used": 0, "limit": 23},
    "twelvedata":   {"used": 0, "limit": 60},
    "eodhd":        {"used": 0, "limit": 18},
    "finnhub":      {"used": 0, "limit": 55},
    "openrouter":   {"used": 0, "limit": 200},
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
# OPENROUTER / DEEPSEEK V3 FLASH
# =============================================================================

def _openrouter_chat(prompt: str, timeout: int = 30, max_tokens: int = 300) -> tuple:
    """Appel DeepSeek v3 flash via OpenRouter.

    Retourne (texte_reponse, erreur_str|None).
    Le modele est toujours deepseek/deepseek-chat-v3-0324:free.
    max_tokens est parametrable pour limiter la longueur de la reponse.
    """
    if not OPENROUTER_KEY:
        return None, "OPENROUTER_KEY absente"
    if not _quota_ok("openrouter"):
        return None, "QUOTA_REACHED"
    _quota_inc("openrouter")
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://github.com/adrien13vivier-hub/projectone",
            "X-Title":       "Portfolio Analyzer",
        }
        payload = {
            "model": OR_MODEL,
            "messages": [
                {
                    "role":    "system",
                    "content": (
                        "Tu es un assistant financier specialise. "
                        "Reponds toujours en francais. "
                        "Sois factuel, concis et neutre. "
                        "Ne retourne JAMAIS de sauts de ligne dans ta reponse : "
                        "ecris tout sur une seule ligne continue."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens":   max_tokens,
            "temperature":  0.3,
        }
        r = requests.post(OR_BASE, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return text if text else None, None
        if r.status_code == 429:
            return None, "HTTP_429_QUOTA"
        return None, f"HTTP {r.status_code}"
    except requests.exceptions.Timeout:
        return None, "Timeout"
    except requests.exceptions.ConnectionError:
        return None, "Connexion impossible"
    except Exception as e:
        return None, str(e)[:60]


# =============================================================================
# FLUX RSS YAHOO FINANCE
# =============================================================================

_rss_cache: dict = {}


def _fetch_yahoo_rss(ticker_yf: str, n: int = 6) -> list:
    """Recupere les n derniers titres d'actualite depuis le flux RSS Yahoo Finance.

    Retourne une liste de chaines (titres bruts).
    On limite volontairement a 6 titres pour garder le prompt court et la
    synthese focalisee sur l'essentiel.
    """
    if ticker_yf in _rss_cache:
        return _rss_cache[ticker_yf][:n]

    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={ticker_yf}&region=US&lang=en-US"
    )
    try:
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0 PortfolioAnalyzer/5.5"})
        if r.status_code != 200:
            _rss_cache[ticker_yf] = []
            return []
        root = ET.fromstring(r.content)
        titles = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())
            if len(titles) >= n:
                break
        _rss_cache[ticker_yf] = titles
        return titles
    except Exception as e:
        _log.warning("RSS Yahoo Finance (%s) : %s", ticker_yf, e)
        _rss_cache[ticker_yf] = []
        return []


# =============================================================================
# SYNTHESE ACTUALITE VIA DEEPSEEK (RSS + OpenRouter)
# =============================================================================

_synthesis_cache: dict = {}

# Nombre maximum de tokens alloues a la synthese d'actualite.
# 120 tokens = environ 2-3 phrases courtes en francais, ce qui est suffisant
# pour un bloc d'actualite dans le rapport. Cela evite les reponses trop longues
# et garantit que le blockquote Markdown reste lisible.
_SYNTHESIS_MAX_TOKENS = 120


def _clean_synthesis(text: str) -> str:
    """Supprime les sauts de ligne internes pour garantir un blockquote Markdown valide.

    DeepSeek peut retourner un texte multi-lignes meme si on lui demande de ne
    pas le faire. On joint toutes les lignes non-vides avec un espace.
    """
    lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()]
    return " ".join(lines)


def get_news_synthesis(asset: dict) -> tuple:
    """Recupere les titres RSS Yahoo Finance et les fait synthetiser par DeepSeek.

    Retourne (synthese_str, source_str).
    - synthese_str : resume 2-3 phrases MAX en francais sur UNE SEULE LIGNE,
                     ou liste de titres bruts si OR indispo.
    - source_str   : "DeepSeek/RSS" | "RSS brut" | "Aucune actualite"

    Contraintes de longueur :
    - On limite le RSS a 6 titres (signal/bruit optimal).
    - Le prompt impose explicitement 2 phrases maximum (contrainte stricte).
    - max_tokens=120 coupe la generation au-dela de ~2 phrases.
    - _clean_synthesis() supprime les \n residuels.
    """
    ticker_yf = asset.get("ticker_yf") or asset.get("ticker_fh", "")
    name      = asset["name"]
    key       = ticker_yf

    if key in _synthesis_cache:
        return _synthesis_cache[key]

    titles = _fetch_yahoo_rss(ticker_yf, n=6)

    if not titles:
        _synthesis_cache[key] = ("Aucune actualite disponible via RSS.", "RSS Yahoo vide")
        return _synthesis_cache[key]

    if OPENROUTER_KEY and _quota_ok("openrouter"):
        titres_str = "\n".join(f"- {t}" for t in titles)
        prompt = (
            f"Voici les dernieres manchettes d'actualite financiere "
            f"concernant {name} (source : Yahoo Finance RSS) :\n\n"
            f"{titres_str}\n\n"
            "Redige EXACTEMENT 2 phrases en francais (pas plus) qui resument "
            "les points cles de cette actualite. "
            "Sois factuel et neutre. "
            "N'utilise PAS de puces, de listes, ni de sauts de ligne. "
            "Ecris les 2 phrases a la suite sur une seule ligne."
        )
        text, err = _openrouter_chat(prompt, max_tokens=_SYNTHESIS_MAX_TOKENS)
        if text:
            text_clean = _clean_synthesis(text)
            result = (text_clean, "DeepSeek v3 / RSS Yahoo Finance")
            _synthesis_cache[key] = result
            return result
        _log.warning("OpenRouter synthese (%s) : %s", name, err)

    # Fallback : retourne les titres bruts si DeepSeek indispo
    brut = " | ".join(titles[:3])
    result = (brut, "RSS Yahoo Finance (brut)")
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

    # Fallback OpenRouter : demande le taux EUR/USD a DeepSeek
    if OPENROUTER_KEY and _quota_ok("openrouter"):
        text, or_err = _openrouter_chat(
            "Quel est le taux de change EUR/USD actuel approximatif ? "
            "Reponds uniquement avec un nombre decimal (ex: 0.9234), sans texte supplementaire."
        )
        if text:
            try:
                rate = float(text.strip().replace(",", "."))
                if 0.5 < rate < 2.0:
                    return rate, "OpenRouter/DeepSeek (fallback AV)", False, \
                        f"EUR/USD via DeepSeek ({', '.join(errors)})"
            except ValueError:
                pass

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


# --- Analyse lexicale v5.5 : fenetre de negation ------------------------------
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


def get_monthly_history(asset: dict, eur_usd: float, months: int = 6) -> tuple:
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
            "Performance comparee du portefeuille -- base 100 (6 mois, EUR)",
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
# RAPPORT PRINCIPAL
# =============================================================================

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
    sources_log      = {}

    us_tickers = [a["ticker_td"] for a in PORTFOLIO if a.get("ticker_td")]
    watch_td   = [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    td_prices  = td_fetch_batch(list(set(us_tickers + watch_td))) if TWELVEDATA_KEY else {}

    eur_usd, eurusd_src, eurusd_cache, eurusd_note = get_eur_usd(session_cache)
    new_cache["eur_usd"] = eur_usd
    sources_log["EUR/USD"] = eurusd_src
    if eurusd_cache:
        cache_warnings.append(eurusd_note)
    elif eurusd_note and "indisponible" in eurusd_note:
        api_errors.append(f"EUR/USD : {eurusd_note}")
    if eurusd_note:
        divergence_log.append(f"EUR/USD : {eurusd_note}")

    indices_data = {n: get_index(s) for n, s in INDICES.items()}
    for idx_name, d in indices_data.items():
        sources_log[idx_name] = d["source"]
        if "Indisponible" in d["source"]:
            api_errors.append(f"Indice {idx_name} : {d['source']}")
    macro_score = score_macro(indices_data)
    macro_label = ("Haussiere" if macro_score >= 6
                   else "Baissiere" if macro_score <= 4 else "Neutre")
    macro_news  = get_macro_news(5)

    lines += [
        f"# Rapport de Portefeuille v5.5 -- {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
        "", "---", "",
        "## Contexte Economique", "",
        f"**Tendance : {macro_label}** | Score macro : {macro_score:.1f}/10",
        f"**EUR/USD :** 1 EUR = {1/eur_usd:.4f} USD",
        "",
        "| Indice | Variation | Cours |",
        "|--------|-----------|-------|",
    ]
    for name, d in indices_data.items():
        arr = "^" if d["change_pct"] > 0 else "v" if d["change_pct"] < 0 else "-"
        lines.append(f"| {name} | {arr} {d['change_pct']:+.2f}% | {d['price']:,.2f} |")

    if macro_news:
        lines += ["", "**Manchettes macro :**", ""]
        for t in macro_news:
            if t: lines.append(f"- {t}")

    lines += ["", "---", "", "## Analyse par Valeur", ""]

    total_cout = total_vm = total_pnl_brut = total_pnl_net = 0.0
    summaries  = []

    prices = {}
    for asset in PORTFOLIO:
        price_eur, chg, price_src, price_cache, div_note = get_price_eur(
            asset, eur_usd, td_prices, session_cache)
        prices[asset["ticker_eod"]] = (price_eur, chg, price_src, price_cache, div_note)

    asset_results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_asset = {
            executor.submit(_fetch_asset_data, asset, eur_usd, td_prices, session_cache): asset
            for asset in PORTFOLIO
        }
        for future in as_completed(future_to_asset):
            asset = future_to_asset[future]
            try:
                asset_results[asset["ticker_eod"]] = future.result()
            except Exception as exc:
                _log.warning("Erreur thread %s : %s", asset["name"], exc)
                asset_results[asset["ticker_eod"]] = {
                    "news": [], "bull": 50.0, "bear": 50.0, "sent_src": "Erreur",
                    "cs": 5.0, "cons_str": "N/D", "cons_src": "Erreur",
                    "h_dates": [], "h_closes": [], "h_src": "Erreur",
                    "h_cache": False, "h_err": str(exc),
                    "synthesis": "Erreur lors de la recuperation.", "synth_src": "Erreur",
                }

    for asset in PORTFOLIO:
        ticker = asset["ticker_eod"]

        price_eur, chg, price_src, price_cache, div_note = prices[ticker]
        sources_log[ticker] = {"cours": price_src}

        if div_note:
            divergence_log.append(f"{asset['name']} : {div_note}")
        if price_cache:
            cache_warnings.append(f"{asset['name']} -- cours : {div_note or price_src}")
        if price_eur is None:
            lines += [
                f"### {asset['name']} `{ticker}`",
                "",
                "> Cours totalement indisponible -- aucune source ni cache",
                "", "---", "",
            ]
            api_errors.append(f"{asset['name']} : cours totalement indisponible")
            continue

        new_cache[f"price_{ticker}"] = price_eur

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

        r         = asset_results[ticker]
        news      = r["news"]
        bull      = r["bull"]
        bear      = r["bear"]
        sent_src  = r["sent_src"]
        cs        = r["cs"]
        cons_str  = r["cons_str"]
        cons_src  = r["cons_src"]
        h_dates   = r["h_dates"]
        h_closes  = r["h_closes"]
        h_src     = r["h_src"]
        h_cache   = r["h_cache"]
        h_err     = r["h_err"]
        synthesis = r["synthesis"]
        synth_src = r["synth_src"]

        sources_log[ticker]["sentiment"]  = sent_src
        sources_log[ticker]["consensus"]  = cons_src
        sources_log[ticker]["historique"] = h_src
        sources_log[ticker]["synthese"]   = synth_src

        if h_cache:
            cache_warnings.append(f"{asset['name']} -- historique : {h_err or h_src}")
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

        chg_arrow  = "^" if chg > 0 else "v" if chg < 0 else "-"
        pnl_b_icon = "+" if pnl_brut >= 0 else "-"
        pnl_n_icon = "+" if pnl_net  >= 0 else "-"
