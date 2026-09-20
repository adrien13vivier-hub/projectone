#!/usr/bin/env python3
"""
Portfolio Analyzer v7.4 -- NOTATION REFONDUE + CONTEXTE OBLIGATAIRE
================================================================================

CE QUI CHANGE, ET POURQUOI
--------------------------

L'ancienne formule etait :

    note = 0.30 * plus-value_latente
         + 0.20 * sentiment_presse
         + 0.20 * consensus_analystes
         + 0.30 * momentum

Trois defauts structurels :

1. LE PRIX DE REVIENT N'EST PAS UNE PROPRIETE DU TITRE. Deux personnes
   detenant la meme action recevaient deux notes differentes selon leur date
   d'achat. Le titre, lui, vaut la meme chose pour tout le monde.

2. LE PRIX COMPTAIT DOUBLE. Plus-value (30%) et momentum (30%) mesurent la
   meme chose sur une position recente : 60% de la note disait "ca a monte".
   La formule etait procyclique -- au plus haut juste avant les corrections.

3. AUCUN FONDAMENTAL. Un titre a 90x les benefices pouvait obtenir ACHAT FORT
   parce qu'il avait monte et que la presse etait enthousiaste.

NOUVELLE ARCHITECTURE : DEUX INDICATEURS DISTINCTS
--------------------------------------------------

  NOTE DU TITRE (0-10)  -- ne depend PAS de qui le detient
      Valorisation ............ 22%   PER, PEG, EV/EBITDA, P/B
      Sante financiere ........ 18%   marges, ROE, dette/fonds propres
      Croissance .............. 15%   chiffre d'affaires, benefices
      Momentum ................ 20%   avec penalite de surchauffe
      Consensus analystes ..... 13%
      Sentiment presse ........ 07%
      Risque / volatilite ..... 05%

  MA POSITION           -- specifique au detenteur, PAS dans la note
      plus-value nette, seuil de rentabilite apres frais, poids dans le
      portefeuille, ecart au consensus de prix cible.

La recommandation croise les deux : un titre bien note qu'on detient en
moins-value n'appelle pas la meme action qu'un titre mal note en plus-value.

GESTION DES DONNEES MANQUANTES
------------------------------
L'ancienne version mettait 5.0 par defaut, ce qui tirait silencieusement
toutes les notes vers le milieu. Desormais une composante absente est
EXCLUE et les poids restants sont renormalises. Un INDICE DE CONFIANCE
(part des poids reellement disponibles) accompagne chaque note : une note
de 8/10 calculee sur 40% des criteres n'a pas la valeur d'une note de 8/10
calculee sur 95%.

LIMITES ASSUMEES -- a lire avant de s'y fier
--------------------------------------------
- Aucune formule ne predit les rendements futurs. Ceci est un outil de
  hierarchisation et d'alerte, pas un signal d'achat.
- Les seuils de valorisation sont GENERALISTES. Un PER de 40 n'a pas le meme
  sens pour un editeur de logiciels et pour une banque. Le PEG corrige
  partiellement en integrant la croissance, mais la comparaison sectorielle
  n'est pas implementee.
- Les fondamentaux EODHD sont trimestriels : ils ne bougent pas d'un jour a
  l'autre. Seuls momentum, sentiment et cours evoluent quotidiennement.
- Les ETF, obligations et cryptos n'ont pas de fondamentaux d'entreprise :
  ils sont notes sur les seules composantes applicables, avec un indice de
  confiance mecaniquement plus bas.

AJOUT v7.4 -- CONTEXTE OBLIGATAIRE
-----------------------------------
Le bloc "Contexte economique" affiche desormais les taux souverains a 10 ans
americain (UST) et francais (OAT) : niveau courant, variation du jour en
points de base, variation sur un mois, et ecart OAT-UST.

Ces taux sont le prix de l'argent sans risque. Ils donnent le referentiel
face auquel toute action est evaluee : quand le 10 ans monte, le rendement
exige sur les actions monte avec lui, ce qui pese mecaniquement sur les
valorisations -- d'autant plus fort que les benefices attendus sont lointains.

Volontairement HORS de la note des titres : c'est un cadre de lecture, pas un
critere de selection. Un taux a 4,5% ne rend pas une entreprise meilleure ou
pire ; il change la barre a franchir, pour toutes en meme temps.
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

# --- MOTEUR DE RISQUE --------------------------------------------------------
# Import tolerant : si risk_engine.py est absent ou casse, le rapport quotidien
# doit continuer de sortir SANS les sections de risque, plutot que d'echouer.
# C'est une fonctionnalite ajoutee, pas une dependance vitale.
try:
    import risk_engine
    RISK_OK = True
    RISK_ERR = None
except Exception as _e:                       # pragma: no cover
    risk_engine = None
    RISK_OK = False
    RISK_ERR = str(_e)

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


def date_seance(now: datetime) -> str:
    """Date ('YYYY-MM-DD') de la seance de bourse que CE rapport decrit.

    BUG CORRIGE (19/09/2026) : history.csv, stops_state.json et
    correlation_history.csv etaient dates avec `now.strftime(...)` -- l'heure
    D'EXECUTION du run, pas la seance decrite. Le declenchement reel arrive
    systematiquement apres minuit heure de Paris (releve entre 00h47 et
    01h25 -- voir la note sur le cron de secours dans
    .github/workflows/daily_analysis.yml) : un run qui rapporte la cloture
    de la veille au soir se retrouvait ainsi date du LENDEMAIN. Avant 6h du
    matin -- largement avant la reouverture de n'importe quelle place
    suivie -- on considere que le rapport decrit encore la seance de la
    veille. Le titre du rapport, lui, continue d'afficher l'heure REELLE de
    generation : ce n'est pas la meme information.
    """
    d = now.date()
    if now.hour < 6:
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


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
# Etat persistant des stops (high-water marks + armement des alertes).
# Volontairement place sous reports/<user>/ : c'est un dossier que le workflow
# GitHub commite deja, aucune modification du YAML n'est donc necessaire.
STOPS_STATE_PATH = "reports/default/stops_state.json"
# Historique de l'indice de correlation moyenne (voir indice_correlation_moyenne
# dans risk_engine.py) -- un fichier dedie, separe de history.csv qui est a la
# granularite de la ligne : ici chaque ligne du CSV est une mesure de tout le
# portefeuille pour un jour donne, pas d'une valeur individuelle.
CORR_HISTORY_PATH = "reports/default/correlation_history.csv"


def slugify(value: str) -> str:
    """Normalise un nom d'utilisateur en identifiant de dossier sur."""
    s = _re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "default").strip().lower())
    return s.strip("-") or "default"


def set_user(username: str):
    """Bascule tous les chemins de sortie vers l'utilisateur indique."""
    global USER, HISTORY_PATH, CHARTS_DIR, REPORT_PATH, STOPS_STATE_PATH, CORR_HISTORY_PATH
    USER         = slugify(username)
    HISTORY_PATH = f"reports/{USER}/history.csv"
    CHARTS_DIR   = f"reports/{USER}/charts"
    REPORT_PATH  = f"reports/{USER}/daily_report.md"
    STOPS_STATE_PATH = f"reports/{USER}/stops_state.json"
    CORR_HISTORY_PATH = f"reports/{USER}/correlation_history.csv"
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
                "pnl_net_pct", "score", "confiance", "rec"]

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
CLOSED:    list = []      # operations closes (plus-values realisees)

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
    "crypto":   {"threshold": 0,    "flat": 0.0,  "rate": 0.005,  "min": 0.0},
    "manuel":   {"threshold": 0,    "flat": 0.0,  "rate": 0.0,    "min": 0.0},
}
BROKERAGE   = {k: dict(v) for k, v in DEFAULT_BROKERAGE.items()}
BROKER_NAME = "Grille par defaut"

PROFILE: dict = {}

# Reglages de risque du profil courant, remplis par apply_profile().
RISQUE: dict = {
    "risque_pct":    1.0,     # % du capital risque par idee
    "poids_max_pct": 15.0,    # plafond de poids sur une ligne
    "vol_cible_pct": 2.0,     # volatilite qu'une ligne sans stop peut apporter
    "liquidites":    None,    # cash disponible, si connu
    "stop_defaut":   None,    # stop applique aux lignes qui n'en declarent pas
}


def apply_profile(profile: dict):
    """Charge un profil utilisateur dans l'etat global du module."""
    global PORTFOLIO, WATCHLIST, INDICES, BROKERAGE, BROKER_NAME, PROFILE, CLOSED
    global RISQUE

    PROFILE   = profile or {}
    settings  = PROFILE.get("settings") or {}

    # Les valeurs sont deja bornees par api/load_portfolio.normalize_profile ;
    # les defauts ci-dessous ne servent qu'aux profils charges sans lui.
    RISQUE = {
        "risque_pct":    settings.get("risque_pct")    or 1.0,
        "poids_max_pct": settings.get("poids_max_pct") or 15.0,
        "vol_cible_pct": settings.get("vol_cible_pct") or 2.0,
        "liquidites":    settings.get("liquidites"),
        "stop_defaut":   settings.get("stop_defaut"),
    }

    PORTFOLIO = PROFILE.get("lines") or []
    WATCHLIST = settings.get("watchlist") or []
    CLOSED    = PROFILE.get("closed") or []

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
    """Frais de courtage pour un montant donne, selon la grille du profil.

    Un livret, un appartement ou une montre de collection ne passent pas par un
    carnet d'ordres : leur imputer un courtage fausserait la plus-value nette.
    Le marche "manuel" retourne donc toujours zero.
    """
    if marche == "manuel":
        return 0.0
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


def _cache_set(session_cache: dict, cle: str, valeur):
    """Ecrit une valeur de repli en cache AVEC sa propre date de fraicheur.

    BUG CORRIGE (19/09/2026) : le cache ne portait qu'une seule date GLOBALE
    (`saved_at`, voir save_session_cache ci-dessus), reecrite a CHAQUE
    sauvegarde du fichier -- y compris un jour ou une valeur donnee n'a PAS
    ete rafraichie (fournisseur en panne, on relit juste l'ancienne). Le
    message affiche a l'utilisateur ("cache du ...") citait alors la date
    du jour meme pour une donnee vieille de plusieurs jours. Chaque entree
    porte maintenant sa propre date, ecrite uniquement quand la valeur est
    REELLEMENT rafraichie (voir _cache_date pour la lecture).
    """
    session_cache[cle] = valeur
    session_cache[f"{cle}__date"] = date_seance(datetime.now(PARIS_TZ))


def _cache_date(session_cache: dict, cle: str) -> str:
    """Date de fraicheur d'une entree de cache (voir _cache_set).

    Repli sur `saved_at` pour un cache ecrit avant ce correctif (entrees
    sans date individuelle) -- imprecis pour une valeur ancienne, mais pas
    pire que le comportement precedent, et evite un "date inconnue" sur
    tout cache existant au moment de la mise a jour.
    """
    return (session_cache.get(f"{cle}__date")
            or session_cache.get("saved_at") or "date inconnue")


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
            _quota_epuiser(api_key_name)
            return None, "HTTP_429_QUOTA"
        if r.status_code == 402:
            # EODHD (et d'autres) renvoient 402 "Payment Required" quand le
            # quota JOURNALIER du plan est atteint -- ce n'est pas une panne
            # ponctuelle, et retenter n'y changera rien avant demain.
            _quota_epuiser(api_key_name)
            return None, "HTTP_402_QUOTA"
        return None, f"HTTP {r.status_code}"
    except requests.exceptions.Timeout:
        return None, "Timeout"
    except requests.exceptions.ConnectionError:
        return None, "Connexion impossible"
    except Exception as e:
        return None, str(e)[:60]


def _quota_epuiser(key: str):
    """Marque une cle comme epuisee pour le reste du run.

    Le compteur local (_QUOTA) n'est qu'une ESTIMATION du quota reel du
    fournisseur -- il peut etre en retard sur la vraie limite si d'autres
    process ou d'autres jours ont deja consomme des appels. Un vrai 402/429
    est la verite terrain : on aligne le compteur local dessus pour que
    TOUS les appels suivants a cette cle, ce run-ci, s'arretent tout de
    suite localement plutot que de retenter et d'echouer un par un.
    """
    with _quota_lock:
        if key in _QUOTA:
            _QUOTA[key]["used"] = _QUOTA[key]["limit"]


def _is_quota_error(err: str) -> bool:
    return err in ("QUOTA_REACHED", "HTTP_429_QUOTA", "HTTP_402_QUOTA") if err else False


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
        saved_at = _cache_date(session_cache, "eur_usd")
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
# CHANGE MULTI-DEVISES
# =============================================================================
# CORRECTION v8 -- BOGUE CORRIGE
# ------------------------------
# Jusqu'ici, TOUTE valeur hors Etats-Unis etait consideree comme cotee en euro
# et renvoyee telle quelle. C'est vrai pour Paris, Amsterdam, Bruxelles,
# Lisbonne, Milan, Francfort et Madrid. C'est FAUX pour Londres (GBP) et pour
# la Suisse (CHF) : une action a 1200 GBX/GBP etait comptabilisee comme
# 1200 EUR, soit une surevaluation d'environ 15%.
#
# Le taux est desormais recupere pour toute devise autre que l'euro. Quand il
# reste introuvable, le cours est conserve MAIS accompagne d'un avertissement
# explicite dans le rapport : mieux vaut un chiffre signale comme douteux
# qu'un chiffre faux presente comme sur.

def get_fx(devise: str, eur_usd: float, session_cache: dict) -> tuple:
    """Combien vaut 1 unite de `devise` en euro. Retourne (taux, source).

    Le dollar reutilise le taux deja obtenu par get_eur_usd() : il est
    interroge une fois par run, sur la source la plus fiable (AlphaVantage).
    Les autres devises passent par EODHD, avec memoisation dans le cache de
    session comme partout ailleurs.
    """
    dev = str(devise or "EUR").strip().upper()
    if dev in ("EUR", ""):
        return 1.0, "identite"
    if dev == "USD":
        return eur_usd, "EUR/USD du run"

    # Le penny sterling (GBX / GBp) vaut un centieme de livre. Certaines places
    # londoniennes publient en pence : une ligne dont la valeur ressort 100 fois
    # trop haute se corrige en ecrivant "currency": "GBX" sur la ligne.
    if dev in ("GBX", "GBP.", "PENCE"):
        taux_gbp, src = get_fx("GBP", eur_usd, session_cache)
        return (None, src) if taux_gbp is None else (taux_gbp / 100.0, f"{src} / 100 (pence)")

    cle = f"fx_{dev}"
    if cle in _MEMO:
        return _MEMO[cle]

    resultat = (None, "indisponible")
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/real-time/{dev}EUR.FOREX",
                         {"api_token": EODHD_KEY, "fmt": "json"}, "eodhd")
        if data and not _is_quota_error(err):
            brut = data.get("close") or data.get("previousClose")
            try:
                taux = float(brut)
                if taux > 0:
                    session_cache[cle] = taux
                    resultat = (taux, "EODHD")
            except (TypeError, ValueError):
                pass

    if resultat[0] is None and session_cache.get(cle):
        # Un taux de change bouge de quelques dixiemes de pourcent par jour :
        # celui de la veille reste largement exploitable.
        resultat = (float(session_cache[cle]), "cache session")

    _MEMO[cle] = resultat
    return resultat


def taux_ligne(asset: dict, eur_usd: float, session_cache: dict = None) -> float:
    """Combien vaut 1 unite de cotation de cette ligne, en euro.

    CORRECTION v8 -- SECOND BOGUE DE DEVISE, PLUS INSIDIEUX QUE LE PREMIER
    ----------------------------------------------------------------------
    Le cours du jour et l'HISTORIQUE etaient converti par des chemins
    differents : le cours passait par eur_usd pour les valeurs americaines,
    l'historique aussi -- mais pour tout le reste, l'historique etait pris tel
    quel (fx = 1.0). Consequence pour un crypto-actif, publie en dollar mais
    route hors du chemin "us" : le cours ressortait en euro et l'historique en
    dollar. Le plus haut servant de reference au stop suiveur etait donc environ
    16% trop haut, et le stop se declenchait beaucoup trop tot.

    Une seule fonction calcule desormais ce taux, et les deux chemins
    l'utilisent.
    """
    devise = str(asset.get("devise") or "").upper()
    if not devise:
        # Profil charge sans passer par api/load_portfolio : on retombe sur la
        # devise usuelle du marche interne.
        devise = "USD" if asset.get("marche") in ("us", "crypto") else "EUR"
    cache = session_cache if isinstance(session_cache, dict) else session_cache_global
    taux, _src = get_fx(devise, eur_usd, cache if isinstance(cache, dict) else {})
    return 1.0 if taux is None else taux


def variation_jour_pct(price_eur, h_closes):
    """Variation du jour en %, recalculee depuis l'historique deja telecharge.

    BUG CORRIGE (19/09/2026) : la variation renvoyee par les fournisseurs
    n'etait pas fiable -- TwelveData ne la renvoie jamais (0.0 code en dur
    cote appelant), et celle d'EODHD pouvait rester a +0.00% un jour ou la
    ligne avait pourtant nettement bouge. Ce calcul n'a besoin d'aucun appel
    supplementaire : `h_closes` est deja telecharge pour le momentum.

    Le run tourne apres la cloture de tous les marches (22h37 Paris) : la
    derniere cloture de l'historique (`h_closes[-1]`) correspond donc
    normalement DEJA a la seance du jour. On le verifie en la comparant au
    cours recu par ailleurs (`price_eur`) : s'ils concordent a moins de
    0,5 % pres, l'historique inclut bien le jour et la variation se lit
    entre les deux dernieres clotures. Sinon (run declenche en cours de
    seance, historique pas encore a jour), `h_closes[-1]` est la veille et
    la variation se lit entre le cours du jour et cette derniere cloture.

    Retourne None si le calcul est impossible (moins de 2 clotures, ou
    cours du jour absent) -- l'appelant garde alors la valeur fournisseur.
    """
    closes = [c for c in (h_closes or []) if c is not None]
    if len(closes) < 2 or not price_eur:
        return None
    dernier, avant = closes[-1], closes[-2]
    if not dernier or not avant:
        return None
    if abs(price_eur - dernier) / dernier <= 0.005:
        return round((dernier - avant) / avant * 100, 2)
    return round((price_eur - dernier) / dernier * 100, 2)


# =============================================================================
# COURS (tous marches) -- Orchestrateur
# =============================================================================

def get_price_eur(asset: dict, eur_usd: float, td_prices: dict,
                  session_cache: dict) -> tuple:
    """Cours d'une ligne, converti en euros.

    BUG CORRIGE (19/09/2026) : les `float(raw)` / `float(data.get("change_p",
    0.0))` directs plantaient (ValueError) des qu'un fournisseur renvoyait
    "NA" au lieu d'un chiffre -- une exception non rattrapee ici sautait le
    repli sur le cache session tout en bas de la fonction, la ligne perdait
    alors sa valeur sans meme essayer le dernier cours connu. `_f()` renvoie
    None plutot que de lever, ce qui laisse le code continuer normalement
    vers le prochain repli (TwelveData -> EODHD -> cache -> indisponible).
    """
    td_val = eod_val = None
    note   = None
    chg    = 0.0
    errors = []
    cache_key = f"price_{asset['ticker_eod']}"

    # Les crypto-actifs suivent le meme chemin que les valeurs americaines :
    # EODHD les publie en dollar (BTC-USD.CC), la conversion est identique.
    # Leur ticker_td est None, l'etape TwelveData est donc silencieusement
    # sautee et EODHD prend la main.
    if asset["marche"] in ("us", "crypto"):
        if TWELVEDATA_KEY and asset.get("ticker_td"):
            td_ticker = asset.get("ticker_td")
            td_raw    = _f(td_prices.get(td_ticker)) if td_ticker else None
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
                raw = _f(data.get("close")) if _f(data.get("close")) else _f(data.get("previousClose"))
                if raw and raw > 0:
                    chg     = _f(data.get("change_p")) or 0.0
                    eod_val = round(raw * eur_usd, 4)
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
                raw = _f(data.get("close")) if _f(data.get("close")) else _f(data.get("previousClose"))
                if raw and raw > 0:
                    chg_val = _f(data.get("change_p")) or 0.0
                    devise = str(asset.get("devise") or "EUR").upper()
                    taux, fx_src = get_fx(devise, eur_usd, session_cache)
                    if taux is None:
                        # On publie quand meme, mais le doute est ecrit noir sur
                        # blanc a cote du chiffre.
                        return (round(raw, 4), chg_val,
                                "EODHD", False,
                                f"Cours en {devise} NON CONVERTI en euro "
                                f"(taux {devise}/EUR indisponible)")
                    note_fx = None if devise in ("EUR", "") else \
                        f"converti depuis {devise} au taux {taux:.4f} ({fx_src})"
                    return (round(raw * taux, 4), chg_val,
                            "EODHD", False, note_fx)
                errors.append("EODHD:cours nul")
            elif _is_quota_error(err):
                errors.append("EODHD:quota atteint")
            else:
                errors.append(f"EODHD:{err}")
        else:
            errors.append("EODHD:cle absente")

    if session_cache.get(cache_key):
        saved_at = _cache_date(session_cache, cache_key)
        return (session_cache[cache_key], 0.0, "Cache", True,
                f"Cours non disponible ({', '.join(errors)}) -- cache du {saved_at} utilise")

    return None, 0.0, f"Indisponible ({', '.join(errors)})", False, None


# =============================================================================
# COURS WATCHLIST -- exclusivement Yahoo Finance (aucun quota paye)
# =============================================================================
# La watchlist ne sert qu'a surveiller des titres non detenus : pas de cout
# de revient, pas de score, pas de validation croisee necessaire. La faire
# passer par le meme chemin que le portefeuille (TwelveData + EODHD) grevait
# un quota deja compte au plus juste pour des lignes qui ne pesent sur aucune
# decision de gestion. Yahoo est gratuit, sans cle, deja utilise pour les
# fondamentaux et les actualites RSS de cette meme watchlist -- ne reste plus
# qu'a l'utiliser aussi pour le cours.

def get_price_yahoo(asset: dict, eur_usd: float, session_cache: dict) -> tuple:
    """Cours d'un titre de watchlist via Yahoo Finance uniquement.

    Meme forme de retour que get_price_eur -- (prix_eur, variation_pct,
    source, from_cache, note) -- pour ne rien changer au code d'affichage
    qui consomme ce tuple.

    La variation est recalculee a la main depuis prix du jour / cloture
    precedente plutot que de faire confiance a regularMarketChangePercent :
    certains champs Yahoo sont des fractions (0.015) et d'autres deja des
    pourcentages (1.5) selon le module, et ce n'est pas documente de
    maniere fiable. Le calcul manuel evite ce risque de confusion.
    """
    ticker_yf = asset.get("ticker_yf")
    cache_key = f"price_yahoo_{ticker_yf or asset.get('ticker_eod', '')}"

    if not ticker_yf:
        if session_cache.get(cache_key):
            saved_at = _cache_date(session_cache, cache_key)
            return (session_cache[cache_key], 0.0, "Cache", True,
                    f"Cours non disponible (Yahoo:ticker absent) -- cache du {saved_at} utilise")
        return None, 0.0, "Indisponible (Yahoo:ticker absent)", False, None

    brut, motif = _yahoo_summary(ticker_yf, modules="price")
    prix = _yv(brut, "regularMarketPrice") if brut else None

    if prix is not None:
        # Yahoo publie le penny sterling sous le code "GBp" (p minuscule) --
        # get_fx() attend "GBX" pour reconnaitre ce cas particulier (memes
        # 100x que documente plus haut pour taux_ligne). Il faut le detecter
        # AVANT toute mise en majuscule, sans quoi "GBp" devient "GBP" (la
        # livre entiere) et le cours ressort cent fois trop haut.
        devise_brute = str(brut.get("currency") or "")
        devise = "GBX" if devise_brute == "GBp" else devise_brute.upper()
        prec = _yv(brut, "regularMarketPreviousClose")
        chg = round((prix - prec) / prec * 100.0, 2) if prec else 0.0

        taux, fx_src = (1.0, "identite") if not devise else get_fx(devise, eur_usd, session_cache)
        if taux is None:
            return (round(prix, 4), chg, "Yahoo Finance", False,
                    f"Cours en {devise} NON CONVERTI en euro "
                    f"(taux {devise}/EUR indisponible)")
        note_fx = None if devise in ("EUR", "") else \
            f"converti depuis {devise} au taux {taux:.4f} ({fx_src})"
        prix_eur = round(prix * taux, 4)
        _cache_set(session_cache, cache_key, prix_eur)
        return prix_eur, chg, "Yahoo Finance", False, note_fx

    if session_cache.get(cache_key):
        saved_at = _cache_date(session_cache, cache_key)
        return (session_cache[cache_key], 0.0, "Cache", True,
                f"Cours non disponible (Yahoo:{motif or 'cours nul'}) -- "
                f"cache du {saved_at} utilise")

    return None, 0.0, f"Indisponible (Yahoo:{motif or 'cours nul'})", False, None


# =============================================================================
# INDICES -- EODHD principal * Finnhub fallback
# =============================================================================

def get_index(symbols: dict) -> dict:
    """Cours d'un indice. price/change_pct valent None si indisponible.

    BUG CORRIGE (19/09/2026) : cette fonction renvoyait {"price": 0.0,
    "change_pct": 0.0} en cas d'echec (quota EODHD atteint, "NA", etc.),
    et cette valeur inventee s'affichait dans le rapport comme un vrai
    "+0.00%" -- indiscernable d'une seance sans mouvement. `get_bond_yield`
    evitait deja ce piege (voir sa docstring) ; meme regle ici. `_f()`
    remplace les `float()` directs, qui plantaient tout le rapport de
    l'utilisateur des qu'un fournisseur renvoyait "NA" au lieu d'un chiffre.
    """
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/real-time/{symbols['eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json"},
                         "eodhd")
        if data and not _is_quota_error(err):
            prix = _f(data.get("close")) or _f(data.get("previousClose"))
            if prix is not None:
                return {"price":      prix,
                        "change_pct": _f(data.get("change_p")),
                        "source":     "EODHD"}
        eod_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        eod_err = "cle absente"

    if FINNHUB_KEY:
        data, err = _get(f"{FH_BASE}/quote",
                         {"symbol": symbols["fh"], "token": FINNHUB_KEY},
                         "finnhub")
        if data and not _is_quota_error(err):
            prix = _f(data.get("c"))
            if prix is not None:
                return {"price":      prix,
                        "change_pct": _f(data.get("dp")),
                        "source":     "Finnhub (fallback)"}
        fh_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        fh_err = "cle absente"

    return {"price": None, "change_pct": None,
            "source": f"Indisponible (EODHD:{eod_err}, Finnhub:{fh_err})"}


# =============================================================================
# TAUX SOUVERAINS 10 ANS
# =============================================================================
# EODHD (.GBOND) en source principale, AlphaVantage TREASURY_YIELD en secours
# -- ce dernier ne couvre QUE les Etats-Unis, l'OAT n'a donc pas de repli.

BONDS = {
    "UST 10 ans (US)": {"eod": "US10Y.GBOND", "av": "10year"},
    "OAT 10 ans (FR)": {"eod": "FR10Y.GBOND", "av": None},
}


def get_bond_yield(symbols: dict) -> dict:
    """Taux 10 ans. Retourne yield=None si indisponible.

    On ne renvoie JAMAIS 0.0 en cas d'echec : un taux a 0% est une valeur
    plausible, elle serait affichee telle quelle et lue comme une information.
    None force l'appelant a traiter l'absence explicitement.

    La variation du jour n'est calculee que si la cloture veille est fournie
    ET distincte de la cloture courante : sinon on renvoie None plutot qu'un
    zero qui se confondrait avec une seance sans mouvement.
    """
    if EODHD_KEY:
        data, err = _get(f"{EOD_BASE}/real-time/{symbols['eod']}",
                         {"api_token": EODHD_KEY, "fmt": "json"},
                         "eodhd")
        if data and not _is_quota_error(err):
            brut = data.get("close")
            veille = data.get("previousClose")
            if brut in (None, "", "NA"):
                brut = veille
                veille = None
            if brut not in (None, "", "NA"):
                try:
                    y = float(brut)
                    chg_bp = None
                    if veille not in (None, "", "NA"):
                        chg_bp = round((y - float(veille)) * 100, 1)
                    return {"yield": y, "change_bp": chg_bp, "source": "EODHD"}
                except (TypeError, ValueError):
                    pass
        eod_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        eod_err = "cle absente"

    if ALPHAVANTAGE_KEY and symbols.get("av"):
        data, err = _get(AV_BASE, {
            "function": "TREASURY_YIELD",
            "interval": "daily",
            "maturity": symbols["av"],
            "apikey":   ALPHAVANTAGE_KEY,
        }, "alphavantage")
        if isinstance(data, dict) and data.get("data") and not _is_quota_error(err):
            pts = [p for p in data["data"] if p.get("value") not in (None, "", ".")]
            if pts:
                try:
                    y = float(pts[0]["value"])
                    chg_bp = (round((y - float(pts[1]["value"])) * 100, 1)
                              if len(pts) > 1 else None)
                    return {"yield": y, "change_bp": chg_bp,
                            "source": "AlphaVantage (repli)"}
                except (TypeError, ValueError, KeyError):
                    pass
        av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
    else:
        av_err = "non couvert"

    return {"yield": None, "change_bp": None,
            "source": f"Indisponible (EODHD:{eod_err}, AlphaVantage:{av_err})"}


def get_bond_trend(symbols: dict, jours: int = 30):
    """Variation du taux sur `jours`, en points de base.

    Le mouvement mensuel dit bien plus que la seance du jour : un 10 ans qui
    a pris 40 pb en un mois signale un reajustement macro, la ou +2 pb dans
    la journee n'est que du bruit. Retourne None si l'historique manque.
    """
    if not EODHD_KEY:
        return None
    from_d = str(date.today() - timedelta(days=jours + 12))   # marge week-ends/feries
    to_d   = str(date.today())
    dates, closes, _err = _eodhd_daily(symbols["eod"], from_d, to_d, 1.0)
    if len(closes) < 2:
        return None

    serie = _parse_serie(dates, closes)
    if len(serie) < 2:
        return None
    dernier_dt, dernier = serie[-1]
    cible = dernier_dt - timedelta(days=jours)
    passe = [v for dt, v in serie if dt <= cible]
    ref = passe[-1] if passe else serie[0][1]
    return round((dernier - ref) * 100, 1)


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

# Le sentiment de presse Bull/Bear a ete RETIRE (v8.1).
#
# Il reposait sur un comptage de mots-cles anglais dans les titres
# d'actualite. Sur une dizaine de titres, ce comptage produisait des
# valeurs extremes et instables -- 100/0 un jour, 0/100 le lendemain --
# sans rapport fiable avec la realite. Il n'entrait deja plus dans la note
# depuis la v7.3 ; l'afficher entretenait l'illusion d'une mesure.
#
# La synthese d'actualite (get_news_synthesis) reste en place : elle
# resume ce que dit la presse au lieu de pretendre le quantifier.


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

    # ANCIEN COMPORTEMENT : on renvoyait 5.0, « neutre par defaut ». Cette
    # valeur inventee entrait dans la note ET comptait comme un critere
    # disponible : elle remontait la confiance affichee tout en tirant la note
    # vers le milieu. Le reste du fichier applique deja la regle inverse pour
    # les actifs non cotes (« inventer une valeur neutre reviendrait a
    # mentir ») : on l'applique ici aussi.
    return (None, "N/D", f"indisponible (Finnhub:{fh_err}, EODHD:{eod_err})")


# =============================================================================
# FONDAMENTAUX
# =============================================================================

def _f(valeur):
    """Conversion tolerante en float. Retourne None plutot que 0 si absent,
    pour ne pas confondre 'donnee manquante' et 'valeur nulle'.

    Definie une seule fois desormais (v7.4 la definissait deux fois -- la
    seconde, plus loin dans le fichier, l'emportait silencieusement ; les
    deux etaient quasi identiques, celle-ci reprend la version la plus
    tolerante, qui traite aussi "-" comme une valeur absente)."""
    if valeur in (None, "", "NA", "N/A", "None", "-"):
        return None
    try:
        v = float(valeur)
        return None if v != v else v          # ecarte les NaN
    except (ValueError, TypeError):
        return None


# =============================================================================
# YAHOO FINANCE — acces direct, sans cle
# =============================================================================
# EODHD renvoie HTTP 403 sur /fundamentals : l'endpoint n'est pas inclus dans
# l'abonnement utilise. Valorisation, sante financiere et croissance — 59 % du
# poids de la note — restaient donc introuvables, d'ou une confiance bloquee
# a 41 %.
#
# Yahoo publie ces memes ratios gratuitement et couvre Euronext comme les
# places asiatiques. Il n'y a AUCUNE cle a demander. En revanche, depuis 2023,
# ses endpoints exigent une poignee de main en deux temps :
#
#   1. visiter fc.yahoo.com pour obtenir des cookies de session
#   2. demander un "crumb" a /v1/test/getcrumb, AVEC CES COOKIES et SANS
#      l'en-tete Accept: application/json — cet endpoint precis repond 406
#      si on le lui envoie, contrairement a tous les autres
#
# Sauter l'une des deux etapes donne un crumb accepte en apparence mais
# refuse a l'appel suivant (401 Invalid Crumb).
#
# Tout est fait avec `requests`, deja present : aucune dependance nouvelle,
# donc rien a installer sur le serveur ni dans le workflow.

YH_FC      = "https://fc.yahoo.com"
YH_CRUMB   = "https://query1.finance.yahoo.com/v1/test/getcrumb"
YH_SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"

# Yahoo limite par ADRESSE IP. Une session reutilisee sur tout le run evite de
# refaire la poignee de main a chaque titre, ce qui compte beaucoup sur les
# machines partagees d'un service d'integration continue.
_yh = {"session": None, "crumb": None}
_yh_lock = threading.Lock()


def _yahoo_poignee(force: bool = False):
    """Etablit (ou renouvelle) la session Yahoo. Retourne le crumb ou None."""
    with _yh_lock:
        if _yh["crumb"] and not force:
            return _yh["crumb"]

        entetes = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0 Safari/537.36"),
        }
        try:
            sess = requests.Session()
            sess.headers.update(entetes)
            # Etape 1 : recuperer les cookies. Yahoo repond souvent 404 ici,
            # c'est sans importance : seuls les cookies nous interessent.
            try:
                sess.get(YH_FC, timeout=10)
            except requests.RequestException:
                pass
            # Etape 2 : le crumb. Pas d'en-tete Accept JSON, sinon 406.
            r = sess.get(YH_CRUMB, timeout=10)
            crumb = (r.text or "").strip()
            if r.status_code != 200 or not crumb or len(crumb) > 40 or "<" in crumb:
                _yh["session"], _yh["crumb"] = None, None
                return None
            _yh["session"], _yh["crumb"] = sess, crumb
            return crumb
        except requests.RequestException:
            _yh["session"], _yh["crumb"] = None, None
            return None


def _yahoo_summary(symbole: str, modules: str = None) -> tuple:
    """Modules quoteSummary d'un titre. Retourne (dict, motif_si_echec).

    `modules` par defaut couvre les fondamentaux (valorisation, sante,
    croissance). Un appelant qui n'a besoin que du cours (la watchlist, par
    exemple) passe un jeu de modules plus leger -- inutile de faire payer a
    Yahoo une requete plus grosse que necessaire, et inutile de risquer une
    limitation de debit pour des donnees qu'on n'utilisera pas.
    """
    modules = modules or "defaultKeyStatistics,financialData,summaryDetail"

    for tentative in (1, 2):
        crumb = _yahoo_poignee(force=(tentative == 2))
        if not crumb:
            return {}, "poignee de main impossible"
        try:
            r = _yh["session"].get(
                f"{YH_SUMMARY}/{symbole}",
                params={"modules": modules, "corsDomain": "finance.yahoo.com",
                        "formatted": "false", "crumb": crumb},
                timeout=15)
        except requests.RequestException as e:
            return {}, f"{type(e).__name__}"

        if r.status_code == 401 and tentative == 1:
            continue                      # crumb perime : on refait la poignee
        if r.status_code == 429:
            # Limitation par IP. Inutile d'insister dans le meme run.
            return {}, "429 (limite de debit Yahoo)"
        if r.status_code != 200:
            return {}, f"HTTP {r.status_code}"

        try:
            res = (r.json().get("quoteSummary") or {}).get("result") or []
        except ValueError:
            return {}, "reponse non-JSON"
        if not res:
            return {}, "ticker inconnu"

        fusion = {}
        for bloc in res[0].values():
            if isinstance(bloc, dict):
                fusion.update(bloc)
        return fusion, ""

    return {}, "401 apres renouvellement du crumb"


def _yv(d: dict, *cles):
    """Premiere valeur numerique exploitable parmi plusieurs cles possibles.

    Avec formatted=false Yahoo renvoie des nombres bruts, mais certains champs
    reviennent parfois sous la forme {"raw": 1.23}. On accepte les deux.
    """
    for c in cles:
        v = d.get(c)
        if isinstance(v, dict):
            v = v.get("raw")
        if v in (None, "", {}):
            continue
        try:
            f = float(v)
            if f == f:
                return f
        except (ValueError, TypeError):
            continue
    return None


def _fonda_yahoo(ticker_yf: str) -> tuple:
    """Ratios fondamentaux via Yahoo Finance."""
    if not ticker_yf:
        return {}, "ticker absent"

    brut, motif = _yahoo_summary(ticker_yf)
    if not brut:
        return {}, motif or "vide"

    ratios = {
        # Valorisation
        "per":         _yv(brut, "trailingPE"),
        "per_fwd":     _yv(brut, "forwardPE"),
        "peg":         _yv(brut, "pegRatio", "trailingPegRatio"),
        "ev_ebitda":   _yv(brut, "enterpriseToEbitda"),
        "p_book":      _yv(brut, "priceToBook"),
        "p_sales":     _yv(brut, "priceToSalesTrailing12Months"),
        # Sante financiere
        "marge_nette": _yv(brut, "profitMargins"),
        "marge_ope":   _yv(brut, "operatingMargins"),
        "roe":         _yv(brut, "returnOnEquity"),
        "roa":         _yv(brut, "returnOnAssets"),
        # Croissance
        "croiss_ca":   _yv(brut, "revenueGrowth"),
        "croiss_ben":  _yv(brut, "earningsGrowth", "earningsQuarterlyGrowth"),
        # Risque
        "beta":        _yv(brut, "beta"),
        "haut_52s":    _yv(brut, "fiftyTwoWeekHigh"),
        "bas_52s":     _yv(brut, "fiftyTwoWeekLow"),
        # Divers
        "dividende":   _yv(brut, "dividendYield"),
        "bpa":         _yv(brut, "trailingEps"),
    }
    ratios = {k: v for k, v in ratios.items() if v is not None}
    return (ratios, "Yahoo Finance") if ratios else ({}, "aucun ratio")


def _fonda_eodhd(ticker_eod: str) -> tuple:
    """Ratios via EODHD. Renvoie 403 si l'abonnement n'inclut pas le flux
    Fundamentals — conserve en repli au cas ou l'offre changerait."""
    if not EODHD_KEY:
        return {}, "cle absente"

    data, err = _get(f"{EOD_BASE}/fundamentals/{ticker_eod}",
                     {"api_token": EODHD_KEY, "fmt": "json"}, "eodhd")
    if not isinstance(data, dict) or not data or _is_quota_error(err):
        return {}, ("quota atteint" if _is_quota_error(err) else (err or "vide"))

    hi = data.get("Highlights") or {}
    va = data.get("Valuation") or {}
    te = data.get("Technicals") or {}
    if not hi and not va and not te:
        if any(k in data for k in ("PERatio", "ProfitMargin", "MarketCapitalization")):
            hi = va = te = data
        else:
            return {}, "structure inattendue"

    ratios = {
        "per": _f(hi.get("PERatio")) or _f(va.get("TrailingPE")),
        "per_fwd": _f(va.get("ForwardPE")), "peg": _f(hi.get("PEGRatio")),
        "ev_ebitda": _f(va.get("EnterpriseValueEbitda")),
        "p_book": _f(va.get("PriceBookMRQ")), "p_sales": _f(va.get("PriceSalesTTM")),
        "marge_nette": _f(hi.get("ProfitMargin")),
        "marge_ope": _f(hi.get("OperatingMarginTTM")),
        "roe": _f(hi.get("ReturnOnEquityTTM")), "roa": _f(hi.get("ReturnOnAssetsTTM")),
        "croiss_ca": _f(hi.get("QuarterlyRevenueGrowthYOY")),
        "croiss_ben": _f(hi.get("QuarterlyEarningsGrowthYOY")),
        "beta": _f(te.get("Beta")), "haut_52s": _f(te.get("52WeekHigh")),
        "bas_52s": _f(te.get("52WeekLow")), "dividende": _f(hi.get("DividendYield")),
        "bpa": _f(hi.get("EarningsShare")),
    }
    ratios = {k: v for k, v in ratios.items() if v is not None}
    return (ratios, "EODHD") if ratios else ({}, "aucun ratio exploitable")


def get_fundamentals(asset: dict) -> tuple:
    """Ratios fondamentaux. Yahoo en source principale, EODHD en repli.

    Les deux sources sont FUSIONNEES : si Yahoo rend dix ratios sur douze,
    EODHD complete les deux manquants au lieu d'etre ignore. La source
    affichee liste celles qui ont reellement contribue, pour que le rapport
    reste verifiable.

    Toutes les valeurs sont conservees en PROPORTION (0.18 pour 18 %) ; la
    conversion en pourcentage se fait une seule fois, dans la notation.
    """
    if str(asset.get("asset_type", "action")).lower() in ("etf", "obligation", "crypto"):
        return {}, f"non applicable ({asset.get('asset_type')})"

    fusion, sources, motifs = {}, [], []
    for nom, appel in (("Yahoo", lambda: _fonda_yahoo(asset.get("ticker_yf"))),
                       ("EODHD", lambda: _fonda_eodhd(asset["ticker_eod"]))):
        try:
            ratios, src = appel()
        except Exception as e:
            ratios, src = {}, f"{type(e).__name__}"
        if ratios:
            nouveaux = {k: v for k, v in ratios.items() if k not in fusion}
            if nouveaux:
                fusion.update(nouveaux)
                sources.append(src)
        else:
            motifs.append(f"{nom}:{src}")
        # Les trois composantes manquantes sont couvertes : inutile
        # d'interroger une source de plus et de consommer du quota.
        if all(k in fusion for k in ("per", "marge_nette", "croiss_ca")):
            break

    if fusion:
        return fusion, " + ".join(sources)
    return {}, " / ".join(motifs) or "indisponible"


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
    # Toutes les series sortent d'ici EN EURO, quelle que soit la place. C'est
    # indispensable : le stop suiveur compare le cours du jour au plus haut de
    # cette serie, les deux doivent etre dans la meme monnaie.
    taux = taux_ligne(asset, eur_usd)

    if asset.get("marche") == "us":
        ticker_av = asset.get("ticker_av")
        if ALPHAVANTAGE_KEY and ticker_av:
            data, err = _get(AV_BASE, {
                "function":   "TIME_SERIES_DAILY",
                "symbol":     ticker_av,
                # BUG CORRIGE (19/09/2026) : "compact" ne renvoie que les 100
                # DERNIERES seances -- pour un titre au calendrier charge,
                # cela peut representer moins de 5 mois et non 6 (un "6M
                # +22.9%" du rapport affichait en realite une fenetre de
                # ~4,7 mois). "full" ne coute pas d'appel supplementaire
                # (toujours 1 requete), seulement plus de lignes dans la
                # reponse : gratuit vis-a-vis du quota.
                "outputsize": "full",
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
                        closes.append(round(float(vals["4. close"]) * taux, 4))
                    except (ValueError, TypeError, KeyError):
                        pass
                # AlphaVantage TIME_SERIES_DAILY n'est PAS ajuste des
                # operations sur titre (splits, regroupements) -- seule sa
                # variante "_ADJUSTED" l'est, et elle est reservee aux plans
                # payants. Un split non ajuste produit un saut d'un jour a
                # l'autre d'un facteur ~2, ~3, ~4... qu'aucun mouvement de
                # marche normal n'egale : au-dela de 40% en une seance, on
                # rejette la serie plutot que de laisser un faux effondrement
                # (ou une fausse envolee) fausser le momentum, la volatilite,
                # et surtout un stop suiveur qui se calerait sur un plus haut
                # pre-split. On retombe alors sur EODHD (adjusted_close).
                saut_suspect = any(
                    closes[i - 1] and abs(closes[i] - closes[i - 1]) / closes[i - 1] >= 0.40
                    for i in range(1, len(closes))
                )
                if len(dates) >= 2 and not saut_suspect:
                    return dates, closes, "AlphaVantage", False, None
                if saut_suspect:
                    av_err = "serie ecartee (saut >= 40% -- split non ajuste suspecte)"
                else:
                    av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
            else:
                av_err = "quota atteint" if _is_quota_error(err) else (err or "vide")
        else:
            av_err = "cle absente" if not ALPHAVANTAGE_KEY else "ticker_av absent"

        if EODHD_KEY:
            dates, closes, eod_err = _eodhd_daily(asset["ticker_eod"], from_d, to_d, taux)
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
            saved_at = _cache_date(session_cache_global, cache_key)
            cached   = session_cache_global[cache_key]
            return (cached.get("dates", []), cached.get("closes", []),
                    "Cache", True,
                    f"Historique US non disponible (AV:{av_err}, EODHD:{eod_err}, FH:{fh_err}) -- cache du {saved_at}")
        return ([], [], f"Indisponible (AV:{av_err}, EODHD:{eod_err}, FH:{fh_err})", False,
                "Historique indisponible -- graphique non genere")

    else:
        if EODHD_KEY:
            dates, closes, eod_err = _eodhd_daily(asset["ticker_eod"], from_d, to_d, taux)
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
            saved_at = _cache_date(session_cache_global, cache_key)
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
        # Meme regle que partout : la serie sort en euro. On ne teste plus le
        # marche, on applique le taux de la devise de cotation de la ligne.
        taux   = taux_ligne(asset, eur_usd)
        closes = [round(daily[k] * taux, 4) for k in dates]
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


# =============================================================================
# NOTATION
# =============================================================================
# Chaque fonction renvoie (note_sur_10, disponible) ou None quand la donnee
# manque. Une composante absente est EXCLUE du calcul, jamais remplacee par
# une valeur neutre : c'est ce qui permet a l'indice de confiance d'etre
# honnete sur ce que la note recouvre reellement.


def _palier(valeur, paliers: list) -> float:
    """Note par paliers. `paliers` = [(seuil, note), ...] du meilleur au pire.
    Le premier seuil dont la valeur est >= (ou <= si decroissant) l'emporte."""
    for seuil, note in paliers:
        if valeur >= seuil:
            return note
    return paliers[-1][1]


def _palier_inverse(valeur, paliers: list) -> float:
    """Idem, mais plus la valeur est BASSE, meilleure est la note
    (PER, dette, EV/EBITDA...)."""
    for seuil, note in paliers:
        if valeur <= seuil:
            return note
    return paliers[-1][1]


# ── Valorisation ────────────────────────────────────────────────────────────

def score_valorisation(f: dict):
    """Le titre est-il cher ? Note haute = bon marche.

    Le PEG prime sur le PER brut : il rapporte le multiple a la croissance,
    ce qui evite de sanctionner mecaniquement une entreprise qui croit vite.
    """
    notes, poids = [], []

    peg = f.get("peg")
    if peg is not None and peg > 0:
        notes.append(_palier_inverse(peg, [(0.5, 10), (1.0, 8.5), (1.5, 7),
                                           (2.0, 5), (3.0, 3), (float("inf"), 1)]))
        poids.append(3.0)          # meilleur indicateur isole

    per = f.get("per_fwd") or f.get("per")
    if per is not None:
        if per <= 0:
            notes.append(2.0)      # entreprise deficitaire
            poids.append(2.0)
        else:
            notes.append(_palier_inverse(per, [(10, 9.5), (15, 8.5), (20, 7),
                                               (28, 5.5), (40, 3.5),
                                               (60, 2), (float("inf"), 0.5)]))
            poids.append(2.5)

    ev = f.get("ev_ebitda")
    if ev is not None and ev > 0:
        notes.append(_palier_inverse(ev, [(6, 9.5), (10, 8), (14, 6.5),
                                          (20, 4.5), (30, 2.5), (float("inf"), 1)]))
        poids.append(2.0)

    pb = f.get("p_book")
    if pb is not None and pb > 0:
        notes.append(_palier_inverse(pb, [(1.0, 9.5), (2.0, 8), (3.5, 6.5),
                                          (6.0, 4.5), (10.0, 2.5), (float("inf"), 1)]))
        poids.append(1.0)

    ps = f.get("p_sales")
    if ps is not None and ps > 0:
        notes.append(_palier_inverse(ps, [(1, 9.5), (3, 8), (6, 6),
                                          (10, 4), (20, 2), (float("inf"), 0.5)]))
        poids.append(1.0)

    if not notes:
        return None
    return round(sum(n * p for n, p in zip(notes, poids)) / sum(poids), 2)


# ── Sante financiere ────────────────────────────────────────────────────────

def score_sante(f: dict):
    """Rentabilite et solidite. Note haute = entreprise saine."""
    notes, poids = [], []

    mn = f.get("marge_nette")
    if mn is not None:
        pct = mn * 100
        notes.append(_palier(pct, [(25, 10), (15, 8.5), (10, 7),
                                   (5, 5.5), (0, 3.5), (-float("inf"), 1)]))
        poids.append(2.5)

    mo = f.get("marge_ope")
    if mo is not None:
        pct = mo * 100
        notes.append(_palier(pct, [(30, 10), (20, 8.5), (12, 7),
                                   (6, 5.5), (0, 3.5), (-float("inf"), 1)]))
        poids.append(2.0)

    roe = f.get("roe")
    if roe is not None:
        pct = roe * 100
        # Un ROE tres eleve peut venir d'un fort endettement plutot que
        # d'une rentabilite reelle : on ne recompense pas au-dela de 40%.
        notes.append(10.0 if 20 <= pct <= 40 else
                     _palier(pct, [(40, 8.5), (15, 8), (10, 6.5),
                                   (5, 5), (0, 3.5), (-float("inf"), 1)]))
        poids.append(2.5)

    roa = f.get("roa")
    if roa is not None:
        pct = roa * 100
        notes.append(_palier(pct, [(12, 10), (8, 8.5), (5, 7),
                                   (2, 5.5), (0, 4), (-float("inf"), 1.5)]))
        poids.append(1.5)

    if not notes:
        return None
    return round(sum(n * p for n, p in zip(notes, poids)) / sum(poids), 2)


# ── Croissance ──────────────────────────────────────────────────────────────

def score_croissance(f: dict):
    """Dynamique du chiffre d'affaires et des benefices."""
    notes, poids = [], []

    ca = f.get("croiss_ca")
    if ca is not None:
        pct = ca * 100
        notes.append(_palier(pct, [(30, 10), (20, 9), (12, 7.5), (6, 6),
                                   (0, 4.5), (-10, 2.5), (-float("inf"), 1)]))
        poids.append(3.0)

    ben = f.get("croiss_ben")
    if ben is not None:
        pct = ben * 100
        notes.append(_palier(pct, [(40, 10), (25, 9), (15, 7.5), (5, 6),
                                   (0, 4.5), (-20, 2.5), (-float("inf"), 1)]))
        poids.append(2.0)

    if not notes:
        return None
    return round(sum(n * p for n, p in zip(notes, poids)) / sum(poids), 2)


# ── Momentum ────────────────────────────────────────────────────────────────
# NOTE : _parse_serie() est definie plus haut (section NOTATION). Elle etait
# dupliquee ici a l'identique -- doublon supprime, aucun changement de
# comportement.

def score_history(dates: list, closes: list) -> tuple:
    """Momentum, AVEC penalite de surchauffe.

    Difference majeure avec l'ancienne version : la note ne croit plus
    indefiniment avec la hausse. Un titre ayant pris plus de 60% en six mois
    est plus expose a une correction qu'un titre en progression reguliere.
    L'ancienne formule le notait au maximum -- exactement au pire moment.

    Retourne (note, label, ret_1m, ret_3m, ret_6m).
    """
    serie = _parse_serie(dates, closes)
    if len(serie) < 2:
        return None, "INDISPONIBLE", 0.0, 0.0, 0.0

    last_dt, last_px = serie[-1]

    def ret_since(nb_jours: int) -> float:
        cible = last_dt - timedelta(days=nb_jours)
        passe = [px for dt, px in serie if dt <= cible]
        ref = passe[-1] if passe else serie[0][1]
        return 0.0 if ref <= 0 else (last_px / ref - 1) * 100

    ret_1m, ret_3m, ret_6m = ret_since(30), ret_since(90), ret_since(180)

    note = 5.0
    note += _palier(ret_1m, [(8, 1.4), (4, 1.0), (1, 0.5), (-1, 0),
                             (-4, -0.6), (-8, -1.2), (-float("inf"), -1.8)])
    note += _palier(ret_3m, [(15, 1.8), (8, 1.3), (3, 0.7), (-3, 0),
                             (-8, -0.9), (-15, -1.6), (-float("inf"), -2.2)])
    note += _palier(ret_6m, [(25, 1.6), (12, 1.1), (4, 0.6), (-4, 0),
                             (-12, -0.8), (-25, -1.5), (-float("inf"), -2.0)])

    # Surchauffe : une progression parabolique se paie tot ou tard.
    if ret_6m > 100:
        note -= 3.0
    elif ret_6m > 60:
        note -= 2.0
    elif ret_6m > 40:
        note -= 1.0

    # Capitulation : apres une chute severe, on cesse d'enfoncer la note.
    # Le titre peut etre en difficulte reelle comme survendu -- l'un dans
    # l'autre, l'information n'est plus discriminante.
    if ret_6m < -50:
        note += 1.0

    note = round(max(0.0, min(10.0, note)), 2)
    label = ("HAUSSIER" if note >= 6.5 else
             "BAISSIER" if note <= 3.5 else "NEUTRE")
    return note, label, ret_1m, ret_3m, ret_6m


# ── Risque ──────────────────────────────────────────────────────────────────

def score_risque(f: dict, dates: list, closes: list, taux: float = 1.0):
    """Volatilite et position dans le canal 52 semaines.

    Note haute = risque contenu. Le beta mesure l'amplitude par rapport au
    marche ; la position dans le canal annuel indique s'il reste de la marge
    avant le plus haut.

    `taux` : BUG CORRIGE (19/09/2026). `closes` (l'historique) est deja
    converti en euros par l'appelant, mais `haut_52s`/`bas_52s` viennent
    tels quels de Yahoo/EODHD, dans la devise NATIVE du titre (dollar pour
    les valeurs US, pence pour Londres...). Comparer un cours en euros a un
    canal en dollars faussait la position d'environ 13% pour les valeurs US
    (au taux courant), et rendait le calcul absurde en GBX (facteur ~85).
    `taux` est le meme facteur de conversion que celui applique a `closes`
    (voir `taux_ligne`) : par defaut 1.0, pour ne rien changer aux appels
    qui ne le fournissent pas (tests existants notamment).
    """
    notes, poids = [], []

    beta = f.get("beta")
    if beta is not None and beta > 0:
        notes.append(_palier_inverse(beta, [(0.7, 9.5), (1.0, 8), (1.3, 6.5),
                                            (1.8, 4.5), (2.5, 2.5),
                                            (float("inf"), 1)]))
        poids.append(2.0)

    haut, bas = f.get("haut_52s"), f.get("bas_52s")
    if haut and bas and taux:
        haut, bas = haut * taux, bas * taux
    serie = _parse_serie(dates, closes)
    if haut and bas and serie and haut > bas:
        pos = (serie[-1][1] - bas) / (haut - bas) * 100
        # Au plus haut annuel : peu de marge. Au plus bas : signal negatif.
        notes.append(4.0 if pos >= 95 else 5.5 if pos >= 80 else
                     7.5 if pos >= 50 else 8.0 if pos >= 25 else 5.0)
        poids.append(1.5)

    # Volatilite realisee sur la periode disponible
    if len(serie) >= 20:
        rends = [(serie[i][1] / serie[i - 1][1] - 1)
                 for i in range(1, len(serie)) if serie[i - 1][1] > 0]
        if rends:
            moy = sum(rends) / len(rends)
            var = sum((r - moy) ** 2 for r in rends) / len(rends)
            vol_ann = (var ** 0.5) * (252 ** 0.5) * 100
            notes.append(_palier_inverse(vol_ann, [(15, 9.5), (25, 8), (35, 6.5),
                                                   (50, 4.5), (70, 2.5),
                                                   (float("inf"), 1)]))
            poids.append(2.0)

    if not notes:
        return None
    return round(sum(n * p for n, p in zip(notes, poids)) / sum(poids), 2)


# ── Agregation ──────────────────────────────────────────────────────────────

# Le sentiment de presse a ete retire de la note en v7.3, puis SUPPRIME
# entierement en v8.1.
#
# Les deux sources exploitables (AlphaVantage NEWS_SENTIMENT, Finnhub
# news-sentiment) etant payantes sur les offres utilisees, le repli etait un
# comptage de mots-cles anglais sur une dizaine de titres. Ce comptage
# produisait des valeurs extremes et instables, sans rapport fiable avec la
# realite. La synthese d'actualite le remplace : elle resume ce que dit la
# presse au lieu de pretendre le quantifier.
POIDS_NOTE = {
    "valorisation": 0.24,
    "sante":        0.19,
    "croissance":   0.16,
    "momentum":     0.21,
    "consensus":    0.15,
    "risque":       0.05,
}

# ── APPLICABLE N'EST PAS DISPONIBLE (v14) ───────────────────────────────────
#
# LE SYMPTOME : le profil adrisis affichait 41 % de confiance en permanence,
# et on a longtemps cru a une panne de la source de fondamentaux.
#
# LA CAUSE : ce profil ne contient que des ETF. Un ETF n'a ni PER, ni marge
# nette, ni croissance du chiffre d'affaires — ce ne sont pas des donnees
# manquantes, ce sont des grandeurs qui N'EXISTENT PAS pour ce type d'actif.
# L'ancien calcul mettait dans le meme sac « la source n'a pas repondu » et
# « la question n'a pas de sens ici », et sortait 41 % dans les deux cas.
#
# Trois etats, donc, et non deux :
#   - applicable et disponible   -> compte au numerateur et au denominateur
#   - applicable mais manquante  -> compte au denominateur seul (la confiance
#                                   baisse, c'est le but : il y a un defaut)
#   - non applicable             -> sort des deux (aucun defaut a signaler),
#                                   mais reste ENUMEREE dans le rapport.
#
# Consequence a garder en tete : un ETF peut afficher 100 % de confiance sur
# deux criteres seulement. C'est exact, et c'est pour cela que le nombre de
# criteres retenus est publie a cote — et que recommend() refuse de trancher
# en dessous de trois.
CRITERES_ENTREPRISE = ("valorisation", "sante", "croissance", "consensus")

NON_APPLICABLES = {
    "etf":        CRITERES_ENTREPRISE,
    "obligation": CRITERES_ENTREPRISE,
    "crypto":     CRITERES_ENTREPRISE,
    "metal":      CRITERES_ENTREPRISE,
}


def criteres_applicables(classe: str) -> set:
    """Les criteres qui ont un sens pour cette classe d'actif."""
    hors = set(NON_APPLICABLES.get(str(classe or "action").lower(), ()))
    return {k for k in POIDS_NOTE if k not in hors}


def note_titre(composantes: dict, classe: str = "action") -> tuple:
    """Agrege les composantes en une note sur 10.

    Retourne (note, confiance_%, detail, non_applicables, manquants).

    La confiance est la part des poids APPLICABLES qui ont effectivement pu
    etre calcules. Elle doit accompagner la note partout ou celle-ci est
    affichee : 8.5/10 a 35 % de confiance ne se lit pas comme 8.5/10 a 90 %.
    """
    applicables = criteres_applicables(classe)
    non_appl = sorted(k for k in POIDS_NOTE if k not in applicables)

    dispo = {k: v for k, v in composantes.items()
             if v is not None and k in applicables}
    manquants = sorted(k for k in applicables if composantes.get(k) is None)

    if not dispo:
        return None, 0.0, {}, non_appl, manquants

    poids_dispo = sum(POIDS_NOTE[k] for k in dispo)
    poids_appl = sum(POIDS_NOTE[k] for k in applicables)
    note = sum(v * POIDS_NOTE[k] for k, v in dispo.items()) / poids_dispo
    confiance = round(poids_dispo / poids_appl * 100, 1)
    return round(note, 2), confiance, dispo, non_appl, manquants


def score_position(price_eur, cost_eur, pnl_net_pct, poids_pct):
    """Indicateurs propres au detenteur. VOLONTAIREMENT hors de la note.

    Le prix d'achat est de l'histoire personnelle : il ne dit rien de la
    qualite du titre. Il reste utile pour decider quoi faire, d'ou son
    calcul separe.
    """
    return {
        "pnl_net_pct":   pnl_net_pct,
        "poids_pct":     poids_pct,
        "concentration": ("forte" if poids_pct >= 40 else
                          "notable" if poids_pct >= 25 else "mesuree"),
        "seuil_rentab":  round(cost_eur * (1 + max(0.0, -pnl_net_pct) / 100), 2),
    }


def compute_closed_trades(closes: list) -> tuple:
    """Plus-values realisees sur les positions vendues.

    Le rapport photographie le portefeuille a l'instant T : une ligne vendue
    en disparait entierement, et le gain qu'elle a produit avec elle. Ce
    registre conserve la trace de ces operations.

    Convention de frais identique aux positions ouvertes : aller-retour,
    c'est-a-dire les frais d'achat ET ceux de vente.

    Le taux de change est celui FIGE au moment de la vente : le gain de
    change fait partie du resultat et ne doit pas etre recalcule avec un
    taux ulterieur.
    """
    ops, tot_brut, tot_net, tot_invest = [], 0.0, 0.0, 0.0

    for op in closes or []:
        qty     = float(op.get("qty", 0))
        achat   = float(op.get("buy_price_eur", 0))
        vente   = float(op.get("sell_price", 0))
        taux    = float(op.get("fx_at_sale", 1.0)) or 1.0
        marche  = op.get("marche", "euronext")

        if qty <= 0 or achat <= 0 or vente <= 0:
            continue

        montant_achat = round(achat * qty, 2)
        produit_brut  = round(vente * qty * taux, 2)

        frais_achat = calc_fee(montant_achat, marche)
        frais_vente = calc_fee(produit_brut,  marche)
        frais_tot   = round(frais_achat + frais_vente, 2)

        pv_brute = round(produit_brut - montant_achat, 2)
        pv_nette = round(pv_brute - frais_tot, 2)

        ops.append({
            "name":          op.get("name", "?"),
            "ticker":        op.get("ticker", ""),
            "qty":           qty,
            "buy_price_eur": achat,
            "sell_price":    vente,
            "sell_currency": op.get("sell_currency", "EUR"),
            "fx_at_sale":    taux,
            "sell_date":     op.get("sell_date", ""),
            "montant_achat": montant_achat,
            "produit_brut":  produit_brut,
            "frais":         frais_tot,
            "pv_brute":      pv_brute,
            "pv_nette":      pv_nette,
            "pv_pct":        round(pv_nette / montant_achat * 100, 2) if montant_achat else 0.0,
            "note":          op.get("note", ""),
        })

        tot_brut   += pv_brute
        tot_net    += pv_nette
        tot_invest += montant_achat

    totaux = {
        "nb":       len(ops),
        "brut":     round(tot_brut, 2),
        "net":      round(tot_net, 2),
        "investi":  round(tot_invest, 2),
        "pct":      round(tot_net / tot_invest * 100, 2) if tot_invest else 0.0,
    }
    return ops, totaux


def score_macro(indices_data):
    # get_index() peut renvoyer change_pct=None (indice indisponible, quota
    # atteint) : `None != 0` vaut True en Python, donc None se glissait dans
    # `chgs` et `sum()` plantait tout le rapport. On exclut explicitement les
    # indices indisponibles -- un score macro calcule sur zero indice
    # disponible reste a 5.0 ("Neutre"), inchange, mais ce 5.0-la ne doit
    # jamais etre confondu avec un vrai zero.
    chgs = [v["change_pct"] for v in indices_data.values()
            if v["change_pct"] is not None and v["change_pct"] != 0]
    return round(max(0.0, min(10.0, 5.0 + sum(chgs) / len(chgs))), 2) if chgs else 5.0


def recommend(note, confiance: float = 100.0, pnl_net_pct: float = 0.0,
              nb_criteres: int = 6):
    """Recommandation croisant qualite du titre et situation du detenteur."""
    if note is None:
        return "DONNEES INSUFFISANTES"

    # En dessous de 40 % de confiance, la note repose sur une part trop faible
    # des criteres APPLICABLES pour fonder une recommandation tranchee.
    if confiance < 40:
        return "A EXAMINER (donnees partielles)"

    # Deuxieme garde-fou, ajoute en v14. Depuis que la confiance se calcule
    # sur les criteres applicables, un ETF peut atteindre 100 % avec deux
    # criteres seulement — momentum et risque. Le pourcentage est exact, mais
    # deux criteres ne suffisent pas a dire « RENFORCER » ou « SORTIR ».
    if nb_criteres < 3:
        return "A EXAMINER (peu de criteres)"

    if note >= 7.5:
        return "RENFORCER"
    if note >= 6.0:
        return "CONSERVER"
    if note >= 4.5:
        # Zone grise : la situation du detenteur departage.
        return "SURVEILLER" if pnl_net_pct >= 0 else "SURVEILLER (en moins-value)"
    if note >= 3.0:
        return "ALLEGER"
    return "SORTIR"


def justification(name, net_pnl_eur, net_pnl_pct, detail: dict,
                  note, confiance, hist_label, macro_score,
                  non_applicables=(), manquants=(), classe_label="Actif"):
    """Explique la note en citant les composantes qui l'ont faite bouger."""
    if note is None:
        return "Donnees insuffisantes pour etablir une note."

    libelles = {"valorisation": "valorisation", "sante": "sante financiere",
                "croissance": "croissance", "momentum": "momentum",
                "consensus": "consensus analystes", "risque": "profil de risque"}

    tri     = sorted(detail.items(), key=lambda x: x[1], reverse=True)
    forces  = [f"{libelles[k]} {v:.1f}" for k, v in tri[:2] if v >= 6.5]
    faibles = [f"{libelles[k]} {v:.1f}" for k, v in tri[-2:] if v <= 4.5]

    p = [f"Note {note:.1f}/10 (confiance {confiance:.0f}%)."]
    if forces:
        p.append("Points forts : " + ", ".join(forces) + ".")
    if faibles:
        p.append("Points faibles : " + ", ".join(faibles) + ".")
    p.append(f"Momentum {hist_label}.")
    p.append(f"Position : {net_pnl_eur:+.2f} EUR ({net_pnl_pct:+.1f}%) apres frais.")

    # Les deux phrases qui suivent disent des choses DIFFERENTES et ne doivent
    # pas etre confondues : l'une constate qu'une question n'a pas de sens
    # pour cet actif, l'autre qu'une reponse attendue n'est pas arrivee.
    if non_applicables:
        p.append(f"{len(non_applicables)} critere(s) sans objet pour un actif "
                 f"de type {str(classe_label).lower()} ("
                 + ", ".join(libelles.get(k, k) for k in non_applicables)
                 + ") : ils sont exclus du calcul, pas comptes comme manquants.")
    if manquants:
        p.append("Critere(s) attendu(s) mais non obtenu(s) : "
                 + ", ".join(libelles.get(k, k) for k in manquants) + ".")
    elif confiance < 60:
        p.append("Note etablie sur une partie seulement des criteres.")
    return " ".join(p)


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
    """Ajoute les releves du jour, en respectant l'en-tete deja en place.

    La v7.2 introduit une colonne `confiance`. Un historique ecrit par une
    version anterieure n'a pas cette colonne : on ne peut pas y ajouter des
    lignes plus larges que son en-tete sans le rendre illisible. Le fichier
    est donc migre une fois -- ancien contenu conserve, colonne manquante
    laissee vide sur les lignes historiques.
    """
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)

    entete = None
    if os.path.isfile(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, newline="", encoding="utf-8") as f:
                entete = next(csv.reader(f), None)
        except Exception as e:
            _log.warning("Historique illisible (%s) -- ajout sans migration", e)

    # Migration : on reecrit le fichier avec le nouveau jeu de colonnes.
    if entete and set(entete) != set(HISTORY_COLS):
        manquantes = [c for c in HISTORY_COLS if c not in entete]
        try:
            with open(HISTORY_PATH, newline="", encoding="utf-8") as f:
                anciennes = list(csv.DictReader(f))
            with open(HISTORY_PATH, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=HISTORY_COLS, extrasaction="ignore")
                w.writeheader()
                for ligne in anciennes:
                    w.writerow({c: ligne.get(c, "") for c in HISTORY_COLS})
            _log.info("Historique migre : colonne(s) ajoutee(s) %s", manquantes)
            entete = HISTORY_COLS
        except Exception as e:
            _log.error("Migration de l'historique impossible (%s)", e)
            entete = entete or HISTORY_COLS

    colonnes = entete or HISTORY_COLS
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=colonnes, extrasaction="ignore")
        if not entete:
            writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in colonnes})


CORR_HISTORY_COLS = ["date", "indice_pct", "n_paires", "n_lignes",
                     "min_pct", "max_pct", "classe"]


def append_correlation_history(now: datetime, indice: dict):
    """Ajoute la mesure du jour de l'indice de correlation moyenne.

    Fichier separe de history.csv : celui-ci est a la granularite de la
    ligne (un ticker par ligne), celui-la a la granularite du portefeuille
    entier (une seule mesure par jour). Les melanger aurait force soit des
    colonnes vides sur chaque ligne de titre, soit une ligne "fantome" sans
    ticker dans un fichier qui n'en attend pas.

    N'ecrit rien quand l'indice est indisponible (moins de deux lignes
    exploitables) : une valeur vide dans un historique cense etre numerique
    causerait plus de confusion qu'une absence de ligne ce jour-la.
    """
    indice = indice or {}
    if indice.get("indice_pct") is None:
        return

    os.makedirs(os.path.dirname(CORR_HISTORY_PATH), exist_ok=True)
    nouveau = not os.path.isfile(CORR_HISTORY_PATH)
    try:
        with open(CORR_HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CORR_HISTORY_COLS)
            if nouveau:
                writer.writeheader()
            writer.writerow({
                "date":       date_seance(now),
                "indice_pct": indice.get("indice_pct"),
                "n_paires":   indice.get("n_paires"),
                "n_lignes":   indice.get("n_lignes"),
                "min_pct":    indice.get("min_pct"),
                "max_pct":    indice.get("max_pct"),
                "classe":     risk_engine.classe_correlation(indice.get("indice_pct")),
            })
    except Exception as e:
        _log.warning("Historique de correlation non ecrit (%s)", e)


# =============================================================================
# REPARTITION MULTI-ACTIFS
# =============================================================================

def _nombre_simple(valeur):
    """float() tolerant, utilise sur les valeurs venues du profil."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


ORDRE_CLASSES = ["action", "etf", "obligation", "crypto", "metal",
                 "cash", "immobilier", "collection", "autre"]

LIBELLE_CLASSES = {
    "action": "Actions", "etf": "ETF / Fonds", "obligation": "Obligations",
    "crypto": "Crypto", "metal": "Métaux précieux", "cash": "Liquidités",
    "immobilier": "Immobilier", "collection": "Collection", "autre": "Autre",
}


def calc_repartition(results: list, total_vm: float) -> dict:
    """Ventile la valeur de marche selon quatre axes de lecture.

    classe  : quel type d'actif -- la vue de risque la plus large
    devise  : a quelle monnaie on est expose -- souvent le risque oublie
    compte  : ou se trouvent les avoirs -- utile pour la fiscalite et le suivi
    tag     : la grille de lecture personnelle de l'utilisateur

    Un actif peut porter PLUSIEURS tags : la somme des poids par tag peut donc
    depasser 100%. C'est voulu -- ce sont des etiquettes, pas une partition.
    Les lignes sans tag sont regroupees sous « Sans etiquette » pour que le
    total reste lisible.
    """
    def _vide():
        return {"entrees": [], "total": round(total_vm or 0.0, 2)}

    if not results or not total_vm:
        return {"classe": _vide(), "devise": _vide(),
                "compte": _vide(), "tag": _vide()}

    par_classe, par_devise, par_compte, par_tag = {}, {}, {}, {}

    for r in results:
        a  = r["asset"]
        vm = float(r.get("vm") or 0.0)
        if vm <= 0:
            continue

        classe = a.get("asset_class") or "action"
        par_classe[classe] = par_classe.get(classe, 0.0) + vm

        devise = str(a.get("devise") or "EUR").upper()
        par_devise[devise] = par_devise.get(devise, 0.0) + vm

        compte = (a.get("account") or "").strip() or "Non affecté"
        par_compte[compte] = par_compte.get(compte, 0.0) + vm

        tags = a.get("tags") or []
        if not tags:
            par_tag["Sans étiquette"] = par_tag.get("Sans étiquette", 0.0) + vm
        for t in tags:
            par_tag[t] = par_tag.get(t, 0.0) + vm

    def _formater(table: dict, libelles: dict = None, ordre: list = None) -> dict:
        entrees = []
        for cle, montant in table.items():
            entrees.append({
                "cle":     cle,
                "libelle": (libelles or {}).get(cle, cle),
                "montant": round(montant, 2),
                "part":    round(montant / total_vm * 100, 2),
            })
        if ordre:
            rang = {c: i for i, c in enumerate(ordre)}
            entrees.sort(key=lambda e: (rang.get(e["cle"], 99), -e["montant"]))
        else:
            entrees.sort(key=lambda e: -e["montant"])
        return {"entrees": entrees, "total": round(total_vm, 2)}

    return {
        "classe": _formater(par_classe, LIBELLE_CLASSES, ORDRE_CLASSES),
        "devise": _formater(par_devise),
        "compte": _formater(par_compte),
        "tag":    _formater(par_tag),
    }


# =============================================================================
# STOPS, ALERTES ET DIMENSIONNEMENT
# =============================================================================

def evaluer_risque(results: list, asset_data: dict, capital_ref: float,
                   eur_usd: float, aujourdhui: str, session_cache: dict = None) -> dict:
    """Passe tout le portefeuille au moteur de risque.

    Cette fonction est un ADAPTATEUR : elle traduit les structures internes de
    l'analyseur vers le format attendu par risk_engine, appelle le moteur, puis
    persiste l'etat des high-water marks. Aucun calcul de risque n'est fait
    ici -- c'est ce qui permet de tester le moteur sans l'analyseur.

    Elle ne leve jamais. Si risk_engine est absent ou echoue, on retourne une
    structure vide et le rapport sort sans les sections de risque.
    """
    vide = {"disponible": False, "motif": RISK_ERR or "moteur indisponible",
            "lignes": [], "resume": {"actifs": 0, "franchis": 0, "alertes": 0,
                                     "sans_stop": 0, "total": 0},
            "capital_ref": capital_ref, "reglages": dict(RISQUE),
            "exposition_correlee": [],
            "indice_correlation": {"indice_pct": None, "n_paires": 0,
                                   "n_lignes": 0, "min_pct": None, "max_pct": None}}

    if not RISK_OK:
        return vide

    try:
        etat = risk_engine.charger_etat(STOPS_STATE_PATH)

        # Deux lignes du portefeuille peuvent partager le meme ticker (deux
        # comptes, ou une fusion PRU pas encore declenchee). asset_data et les
        # cours restent lus par le VRAI ticker (une seule cotation existe) --
        # mais la cle transmise au moteur de risque doit etre UNIQUE par
        # ligne, sinon la deuxieme ecrase l'etat de stop (high-water mark) de
        # la premiere, et rien en aval ne peut plus distinguer les deux lignes
        # (valeur de marche, poids, groupe correle). La premiere occurrence
        # garde la cle nue, pour ne pas perdre l'historique de stop deja
        # enregistre sous ce ticker.
        _occurrences = {}
        entrees = []
        for r in results:
            a = r["asset"]
            # Les actifs non cotes n'ont ni cours de cloture ni historique :
            # un stop suiveur n'a aucun sens sur un appartement. On les ecarte
            # explicitement plutot que de les laisser produire un stop bancal.
            if a.get("manuel"):
                continue
            ticker = a.get("ticker_eod") or a.get("name")
            d   = asset_data.get(ticker) or {}
            n = _occurrences.get(ticker, 0) + 1
            _occurrences[ticker] = n
            cle = ticker if n == 1 else f"{ticker}#{n}"
            entrees.append({
                "cle":    cle,
                "nom":    a.get("name", ticker),
                "compte": a.get("account", ""),
                "cours":  r.get("price_eur"),
                "cout":   a.get("cost_eur"),
                "closes": d.get("h_closes") or [],
                # Dates alignees avec "closes" -- transmises pour que la
                # correlation entre une ligne US et une ligne europeenne
                # s'aligne sur les VRAIES dates communes plutot que sur les N
                # derniers points de chaque serie (voir risk_engine.correlation).
                "dates":  d.get("h_dates") or [],
                "ligne":  a,
                # Rattachee ici, dans le meme ordre que `results` : c'est ce
                # qui permet de la reaffecter par position plus bas, sans
                # repasser par un dict indexe par ticker (voir vm_par_cle).
                "vm":     r.get("vm"),
                # Un stop absolu peut etre libelle en devise etrangere. Le
                # taux vient de get_fx, memoise : aucun appel supplementaire.
                "eur_par_devise": taux_ligne(a, eur_usd, session_cache),
            })

        sortie = risk_engine.evaluer_portefeuille(
            entrees,
            etat=etat,
            capital=capital_ref,
            reglages=RISQUE,
            aujourdhui=aujourdhui,
        )

        if not risk_engine.sauver_etat(STOPS_STATE_PATH, sortie["etat"]):
            _log.warning("Etat des stops non sauvegarde (%s) -- les high-water "
                         "marks repartiront du plus haut connu au prochain run",
                         STOPS_STATE_PATH)

        # On rattache la valeur de marche a chaque ligne : le rendu en a besoin
        # pour comparer la taille detenue a la taille suggeree.
        #
        # BUG CORRIGE (19/09/2026) : un dict {ticker: vm} ecrasait la valeur
        # des lignes precedentes des qu'un meme ticker apparaissait plusieurs
        # fois (WPEA x3 chez adrisis, ABNX x2 chez adrien) -- toutes les
        # lignes en double affichaient alors la VM de la DERNIERE d'entre
        # elles. `evaluer_portefeuille` traite `entrees` un par un et rend
        # `sortie["lignes"]` dans le meme ordre, sans en perdre ni en
        # ajouter (une ligne en erreur reste presente, voir risk_engine) :
        # la reaffectation par POSITION est donc exacte, meme pour des
        # tickers en double.
        assert len(entrees) == len(sortie["lignes"]), (
            "evaluer_portefeuille a change le nombre de lignes -- "
            "la reaffectation par position n'est plus valide")
        for e, l in zip(entrees, sortie["lignes"]):
            l["vm"] = e.get("vm")

        # Exposition correlee : le plafond de poids ne voit qu'une ligne a la
        # fois. On lui fournit le poids ACTUEL (vm / capital), pas la taille
        # suggeree par dimensionner() -- c'est bien de ce qui est deja detenu
        # qu'on veut savoir si ca bouge ensemble.
        donnees_par_cle = {e["cle"]: e for e in entrees}
        candidats = []
        if capital_ref:
            for l in sortie["lignes"]:
                vm = _nombre_simple(l.get("vm"))
                if vm is None:
                    continue
                e = donnees_par_cle.get(l["cle"]) or {}
                candidats.append({
                    "nom":       l.get("nom"),
                    "closes":    e.get("closes") or [],
                    "dates":     e.get("dates") or [],
                    "poids_pct": vm / capital_ref * 100.0,
                })
        exposition_correlee = risk_engine.exposition_correlee(candidats)
        # Contrairement au groupement ci-dessus, l'indice ne depend pas du
        # poids : une ligne coteE avec un historique suffisant compte, qu'elle
        # pese beaucoup ou peu dans le portefeuille. `candidats` porte deja
        # `closes` pour chaque ligne -- rien a recalculer.
        indice_correlation = risk_engine.indice_correlation_moyenne(candidats)

        return {
            "disponible": True, "motif": None,
            "lignes":  sortie["lignes"],
            "resume":  sortie["resume"],
            "capital_ref": capital_ref,
            "reglages": dict(RISQUE),
            "exposition_correlee": exposition_correlee,
            "indice_correlation": indice_correlation,
        }
    except Exception as e:
        _log.error("Moteur de risque en echec : %s -- rapport genere sans les "
                   "sections de risque", e)
        return {**vide, "motif": str(e)}


# =============================================================================
# ALERTE PAR COURRIEL
# =============================================================================
# Le rapport ne sert a rien s'il faut penser a l'ouvrir. Un franchissement de
# stop est le seul evenement de ce programme qui merite d'interrompre la
# journee : c'est le seul qui declenche un envoi.
#
# ENTIEREMENT OPTIONNEL. Sans les variables d'environnement ci-dessous, la
# fonction ne fait rien et ne signale rien -- pas de secret configure n'est pas
# une erreur, c'est un choix. Aucune exception ne remonte : un serveur SMTP
# injoignable ne doit jamais faire echouer le rapport quotidien.

MAIL_SERVER   = os.environ.get("MAIL_SERVER", "")
MAIL_PORT     = os.environ.get("MAIL_PORT", "465")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
MAIL_FROM     = os.environ.get("MAIL_FROM", "") or MAIL_USERNAME
MAIL_TO       = os.environ.get("MAIL_TO", "")


def mail_configure() -> bool:
    return bool(MAIL_SERVER and MAIL_TO and MAIL_FROM)


def corps_alerte(alertes: list, lien: str = "") -> tuple:
    """(sujet, texte) du courriel d'alerte. Separe de l'envoi pour etre testable."""
    n = len(alertes)
    noms = ", ".join(a["nom"] for a in alertes[:3])
    if n > 3:
        noms += f" et {n - 3} autre(s)"
    sujet = (f"[Portfolio] {n} stop{'s' if n > 1 else ''} franchi"
             f"{'s' if n > 1 else ''} : {noms}")

    lignes = [
        (f"{n} position a clôturé sous son stop aujourd'hui." if n == 1
         else f"{n} positions ont clôturé sous leur stop aujourd'hui."),
        "",
    ]
    for a in alertes:
        st = a.get("stop") or {}
        lignes += [
            f"- {a['nom']}" + (f" ({a['compte']})" if a.get("compte") else ""),
            f"    clôture      : {a.get('cours')}",
            f"    stop         : {st.get('niveau')}  ({st.get('description', '')})",
            f"    type de stop : {st.get('type_label', '')}",
            "",
        ]
    lignes += [
        "Règle : le franchissement est constaté sur la CLÔTURE, pas en séance.",
        "Une seule alerte par franchissement ; elle se ré-arme si le cours",
        "repasse au-dessus du niveau.",
        "",
        "Ce message est une alerte de surveillance, pas un conseil de vente.",
    ]
    if lien:
        lignes += ["", f"Rapport complet : {lien}"]
    return sujet, "\n".join(lignes)


def envoyer_alertes(risque: dict, lien: str = "") -> bool:
    """Envoie le courriel d'alerte s'il y a lieu. Retourne True si envoye."""
    if not risque or not risque.get("disponible"):
        return False
    alertes = [l for l in risque.get("lignes", []) if (l.get("stop") or {}).get("alerte")]
    if not alertes:
        return False
    if not mail_configure():
        _log.info("%d alerte(s) de stop -- envoi courriel non configure", len(alertes))
        return False

    try:
        import smtplib
        from email.message import EmailMessage

        sujet, texte = corps_alerte(alertes, lien)
        msg = EmailMessage()
        msg["Subject"] = sujet
        msg["From"]    = MAIL_FROM
        msg["To"]      = MAIL_TO
        msg.set_content(texte)

        port = int(MAIL_PORT or 465)
        if port == 465:
            # 465 = SMTPS : le chiffrement est etabli avant tout dialogue.
            with smtplib.SMTP_SSL(MAIL_SERVER, port, timeout=20) as serveur:
                if MAIL_USERNAME:
                    serveur.login(MAIL_USERNAME, MAIL_PASSWORD)
                serveur.send_message(msg)
        else:
            with smtplib.SMTP(MAIL_SERVER, port, timeout=20) as serveur:
                serveur.ehlo()
                if serveur.has_extn("starttls"):
                    serveur.starttls()
                    serveur.ehlo()
                elif MAIL_USERNAME:
                    # Refus deliberé : sans TLS, s'authentifier revient a
                    # envoyer le mot de passe en clair sur le reseau. Mieux
                    # vaut pas d'alerte qu'un identifiant compromis.
                    raise RuntimeError(
                        f"{MAIL_SERVER}:{port} ne propose pas STARTTLS -- "
                        f"envoi annule pour ne pas transmettre le mot de passe "
                        f"en clair. Utiliser le port 465 (SMTPS).")
                if MAIL_USERNAME:
                    serveur.login(MAIL_USERNAME, MAIL_PASSWORD)
                serveur.send_message(msg)

        print(f"Alerte envoyee a {MAIL_TO} : {len(alertes)} stop(s) franchi(s)")
        return True
    except Exception as e:
        # Un envoi rate n'invalide pas le rapport : l'alerte reste visible dans
        # la section « Stops et Alertes ».
        _log.error("Envoi de l'alerte impossible (%s) -- l'alerte reste dans le rapport", e)
        return False


# =============================================================================
# BLOCS MARKDOWN -- RISQUE ET REPARTITION
# =============================================================================
# Ces deux fonctions ne produisent QUE du texte. Elles ne calculent rien et ne
# lisent aucun etat global : on peut les appeler avec une structure de test et
# comparer le rendu, ce qui est exactement ce que fait le harnais hors ligne.

def _classe_vol(valeur) -> str:
    """Etiquette de volatilite, deleguee au moteur quand il est present."""
    if RISK_OK:
        return risk_engine.classe_volatilite(valeur)
    return ""


def _md_nombre(valeur, decimales: int = 2, defaut: str = "--") -> str:
    """Nombre formate avec espace fine comme separateur de milliers."""
    v = _nombre_simple(valeur)
    if v is None:
        return defaut
    return f"{v:,.{decimales}f}".replace(",", " ")


ETIQUETTE_STATUT = {
    "ok":            "OK",
    "franchi":       "FRANCHI",
    "aucun":         "Aucun",
    "incalculable":  "Incalculable",
}


def bloc_md_stops(risque: dict) -> list:
    """Section « Stops et Alertes » du rapport Markdown."""
    if not risque or not risque.get("disponible"):
        motif = (risque or {}).get("motif")
        if not motif:
            return []
        return ["", "---", "", "## Stops et Alertes", "",
                f"> Section indisponible : {motif}", ""]

    lignes_r = risque.get("lignes") or []
    if not lignes_r:
        return []

    res = risque.get("resume") or {}
    reg = risque.get("reglages") or {}
    out = ["", "---", "", "## Stops et Alertes", ""]

    out += [
        f"**Stops actifs : {res.get('actifs', 0)}** | "
        f"**Franchis : {res.get('franchis', 0)}** | "
        f"**Sans stop : {res.get('sans_stop', 0)}** | "
        f"Nouvelles alertes du jour : {res.get('alertes', 0)}",
        "",
        "Règle de franchissement : la CLÔTURE du jour passe sous le niveau. "
        "Une seule alerte par franchissement ; le déclencheur se ré-arme quand "
        "le cours repasse au-dessus. Les stops suiveurs et VQ montent avec le "
        "cours et ne redescendent jamais.",
        "",
    ]

    # Alertes du jour, mises en avant avant le tableau.
    alertes = [l for l in lignes_r if (l.get("stop") or {}).get("alerte")]
    if alertes:
        out += ["**ALERTES DU JOUR :**", ""]
        for l in alertes:
            st = l["stop"]
            out.append(f"- **{l['nom']}** a clôturé à {_md_nombre(l.get('cours'))} EUR, "
                       f"sous son stop {st.get('type_label', '')} de "
                       f"{_md_nombre(st.get('niveau'))} EUR.")
        out.append("")

    # Amorcages : premier calcul d'une ligne, le high-water mark est reconstitue.
    amorces = [l for l in lignes_r if (l.get("stop") or {}).get("amorcage")
               and (l.get("stop") or {}).get("niveau") is not None]
    if amorces:
        out += [
            "*Première évaluation pour : "
            + ", ".join(l["nom"] for l in amorces)
            + ". Le plus haut de référence a été reconstitué depuis l'historique "
              "disponible ; un statut « franchi » dès ce premier passage décrit "
              "donc une situation déjà en place, pas un événement du jour.*",
            "",
        ]

    out += [
        "| Valeur | Compte | Type | Configuration | Niveau | Cloture | Distance | Statut |",
        "|--------|--------|------|---------------|--------|---------|----------|--------|",
    ]
    for l in lignes_r:
        st = l.get("stop") or {}
        statut = ETIQUETTE_STATUT.get(st.get("statut"), st.get("statut", "--"))
        dist = st.get("distance_pct")
        dist_s = "--" if dist is None else f"{dist:+.1f}%"
        out.append(
            f"| {l['nom']} | {l.get('compte') or '--'} "
            f"| {st.get('type_label', '--')} | {st.get('description', '--')} "
            f"| {_md_nombre(st.get('niveau'))} | {_md_nombre(l.get('cours'))} "
            f"| {dist_s} | {statut} |"
        )
    out.append("")

    # ── Dimensionnement ──────────────────────────────────────────────────────
    out += [
        "### Dimensionnement des positions",
        "",
        f"Capital de référence : **{_md_nombre(risque.get('capital_ref'))} EUR** "
        f"(valeurs cotées + liquidités, hors actifs illiquides). "
        f"Risque par idée : **{reg.get('risque_pct', 1.0):.4g} %**, soit "
        f"**{_md_nombre((risque.get('capital_ref') or 0) * (reg.get('risque_pct', 1.0)) / 100)} EUR**. "
        f"Plafond de poids par ligne : {reg.get('poids_max_pct', 15.0):.4g} %.",
        "",
        "Formule : montant = (capital x risque) / distance au stop. Deux valeurs "
        "de volatilités différentes reçoivent ainsi le même risque, pas le même "
        "montant.",
        "",
        "| Valeur | Volatilite an. | Amplitude/jour | VQ | Distance stop "
        "| Taille suggeree | Detenu | Ecart |",
        "|--------|----------------|----------------|-----|---------------"
        "|-----------------|--------|-------|",
    ]
    for l in lignes_r:
        vol = l.get("vol") or {}
        t   = l.get("taille") or {}
        st  = l.get("stop") or {}

        if vol.get("vol_ann_pct") is None:
            vol_s = "--"
        else:
            qualif = [_classe_vol(vol["vol_ann_pct"])]
            if not vol.get("fiable"):
                # Historique court : la volatilite est publiee, mais on dit
                # sur quoi elle repose plutot que de la presenter comme sure.
                qualif.append(f"{vol.get('n_obs', 0)} clotures")
            vol_s = f"{vol['vol_ann_pct']:.1f} % ({', '.join(qualif)})"
        atr_s = "--" if vol.get("atr_pct") is None else f"{vol['atr_pct']:.2f} %"
        vq_s  = "--" if vol.get("vq_pct") is None else f"{vol['vq_pct']:.1f} %"
        dist  = st.get("distance_pct")
        dist_s = "--" if dist is None else f"{dist:.1f} %"

        montant = t.get("montant")
        if montant is None:
            taille_s, ecart_s = "--", "--"
        else:
            taille_s = f"{_md_nombre(montant)} EUR"
            if t.get("bride"):
                taille_s += f" ({t['bride']})"
            vm = _nombre_simple(l.get("vm"))
            ecart_s = "--" if vm is None else f"{_md_nombre(vm - montant)} EUR"
        out.append(
            f"| {l['nom']} | {vol_s} | {atr_s} | {vq_s} | {dist_s} | {taille_s} "
            f"| {_md_nombre(l.get('vm'))} EUR | {ecart_s} |"
        )
    out += [
        "",
        "*« Amplitude/jour » : de combien la valeur bouge en moyenne d'une "
        "cloture a l'autre. C'est la lecture concrete de la volatilite.*",
        "",
        "*« Écart » = ce qui est détenu moins ce que le budget de risque "
        "justifierait. Positif : la ligne est plus grosse que le risque accepté. "
        "Ce n'est pas un ordre de vente, c'est un écart à expliquer.*",
        "",
    ]

    out += bloc_md_exposition_correlee(risque.get("exposition_correlee") or [],
                                       risque.get("indice_correlation") or {})
    return out


def bloc_md_exposition_correlee(groupes: list, indice: dict = None) -> list:
    """Sous-section « Exposition corrélée » (dans Stops et Alertes).

    Le plafond de poids par ligne ne voit pas les positions qui bougent
    ensemble : cette sous-section regroupe les lignes dont les rendements
    quotidiens sont corrélés au-delà du seuil (0.7 par défaut), sur
    l'historique déjà récupéré pour la volatilité -- aucun appel API de plus.

    Un groupe sans dépassement du seuil d'alerte reste affiché : savoir que
    deux lignes bougent ensemble est utile même sous le seuil.

    `indice` (optionnel) ajoute en tête un chiffre unique -- la corrélation
    MOYENNE sur toutes les paires, pas seulement celles au-dessus du seuil.
    Les deux mesures répondent à des questions différentes : le tableau dit
    QUELLES lignes bougent ensemble, l'indice dit si le portefeuille, DANS
    L'ENSEMBLE, bouge comme un bloc ou de façon indépendante. Suivi dans le
    temps via `reports/<user>/correlation_history.csv`.
    """
    out = ["", "### Exposition corrélée", ""]

    indice = indice or {}
    if indice.get("indice_pct") is not None:
        classe = risk_engine.classe_correlation(indice["indice_pct"])
        out += [
            f"**Corrélation moyenne du portefeuille : {indice['indice_pct']:+.1f} %** "
            f"({classe}) -- calculée sur {indice['n_paires']} paire(s) de lignes "
            f"({indice['n_lignes']} ligne(s) cotée(s) avec un historique suffisant). "
            f"Étendue observée : de {indice['min_pct']:+.1f} % à {indice['max_pct']:+.1f} %.",
            "",
            "*Plus ce chiffre est proche de 0, plus les lignes bougent "
            "indépendamment les unes des autres -- une diversification qui se "
            "voit dans les mouvements réels, pas seulement dans les "
            "étiquettes de classe d'actif ou de secteur. Un chiffre élevé et "
            "négatif est aussi une forme de concentration, sur le pari inverse.*",
            "",
        ]

    if not groupes:
        out += [
            "Aucun regroupement de lignes fortement corrélées (seuil "
            f"{risk_engine.CORRELATION_SEUIL:.2f}) détecté sur l'historique "
            "disponible. *Ceci ne garantit rien sur la corrélation future : "
            "seul le passé récent est mesuré.*",
            "",
        ]
        return out

    out += [
        "Lignes dont les mouvements quotidiens sont fortement corrélés entre "
        "eux -- prises ensemble, elles pèsent plus qu'un plafond de poids par "
        "ligne ne le laisse penser. Un signal d'attention, pas une prévision.",
        "",
        "| Groupe | Poids cumulé | Alerte |",
        "|--------|--------------|--------|",
    ]
    for g in groupes:
        alerte_s = "⚠️ Oui" if g.get("alerte") else "Non"
        out.append(f"| {', '.join(g.get('lignes') or [])} "
                   f"| {_md_nombre(g.get('poids_pct'))} % | {alerte_s} |")
    out += [
        "",
        f"*Seuil de corrélation : {risk_engine.CORRELATION_SEUIL:.2f}. Seuil "
        f"d'alerte sur le poids cumulé : {risk_engine.EXPOSITION_ALERTE_PCT:.4g} %.*",
        "",
    ]
    return out


def bloc_md_repartition(repartition: dict) -> list:
    """Section « Repartition » du rapport Markdown."""
    if not repartition:
        return []
    axes = [("classe", "Par classe d'actif"), ("devise", "Par devise"),
            ("compte", "Par compte"), ("tag", "Par étiquette")]
    if not any((repartition.get(a) or {}).get("entrees") for a, _ in axes):
        return []

    out = ["", "---", "", "## Repartition", ""]
    for cle, titre in axes:
        bloc_axe = repartition.get(cle) or {}
        entrees  = bloc_axe.get("entrees") or []
        if not entrees:
            continue
        # Un seul poste a 100% n'apprend rien : on n'encombre pas le rapport.
        if len(entrees) == 1 and cle in ("devise", "compte", "tag"):
            continue
        out += [f"**{titre}**", "",
                "| Poste | Montant | Part |",
                "|-------|---------|------|"]
        for e in entrees:
            out.append(f"| {e['libelle']} | {_md_nombre(e['montant'])} EUR "
                       f"| {e['part']:.1f}% |")
        out.append("")
    out += [
        "*Un actif peut porter plusieurs étiquettes : la somme des parts par "
        "étiquette peut dépasser 100 %.*",
        "",
    ]
    return out


# =============================================================================
# HELPER PARALLELISATION
# =============================================================================

def _fetch_asset_data(asset: dict, eur_usd: float,
                      td_prices: dict, session_cache: dict) -> dict:
    # get_company_news() a ete retire d'ici (19/09/2026) : son resultat
    # n'etait lu nulle part, ni dans le markdown ni dans generate_html.py --
    # c'etaient 1 a 2 appels EODHD/Finnhub perdus par actif cote, a chaque
    # run, sur un quota deja serre. La synthese d'actualite (RSS Yahoo, sans
    # cle ni quota) reste affichee via get_news_synthesis.
    cs, cons_str, cons_src = get_consensus(asset)
    h_dates, h_closes, h_src, h_cache, h_err = get_monthly_history(asset, eur_usd)
    synthesis, synth_src = get_news_synthesis(asset)
    fonda, fonda_src = get_fundamentals(asset)
    return {
        "cs": cs, "cons_str": cons_str, "cons_src": cons_src,
        "h_dates": h_dates, "h_closes": h_closes, "h_src": h_src,
        "h_cache": h_cache, "h_err": h_err,
        "synthesis": synthesis, "synth_src": synth_src,
        "fonda": fonda, "fonda_src": fonda_src,
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
    jour_seance = date_seance(now)
    os.makedirs(CHARTS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    os.makedirs("cache", exist_ok=True)
    os.makedirs(f"docs/{USER}", exist_ok=True)

    session_cache = shared_cache if shared_cache is not None else load_session_cache()
    session_cache_global = session_cache

    # ── 0. Separation cotees / manuelles ─────────────────────────────────────
    # Un livret, un appartement ou une montre n'ont ni ticker, ni cours, ni
    # historique. Les exclure ICI, une fois, evite d'avoir a s'en souvenir dans
    # chacune des dix etapes suivantes -- et surtout evite de bruler du quota
    # API a interroger des tickers qui n'existent pas.
    COTEES = [a for a in PORTFOLIO if not a.get("manuel")]

    # ── 1. EUR/USD ────────────────────────────────────────────────────────────
    eur_usd, eur_usd_src, eur_usd_cache, eur_usd_warn = get_eur_usd(session_cache)
    # BUG CORRIGE (19/09/2026) : cette ligne ecrasait le cache MEME quand la
    # valeur venait deja du cache (eur_usd_cache=True) ou d'une valeur de
    # secours codee en dur (0.92, ni mesuree ni fraiche) -- le rafraichissant
    # ainsi a chaque run sans jamais avoir ete reellement mis a jour. On ne
    # cache desormais qu'une valeur REELLEMENT obtenue aujourd'hui.
    if not eur_usd_cache and eur_usd_src != "Defaut 0.92":
        _cache_set(session_cache, "eur_usd", eur_usd)

    # ── 2. Cours US en batch (TwelveData) ─────────────────────────────────────
    us_tickers = [a["ticker_td"] for a in COTEES if a.get("ticker_td")]
    us_tickers += [w["ticker_td"] for w in WATCHLIST if w.get("ticker_td")]
    td_prices = td_fetch_batch(list(set(filter(None, us_tickers)))) if TWELVEDATA_KEY else {}

    # ── 3. Cours par position + données parallèles ────────────────────────────
    # Seuls les tickers encore inconnus du memo sont interroges : c'est ici que
    # se joue la mutualisation entre utilisateurs.
    a_faire_px = {a["ticker_eod"]: a for a in COTEES
                  if f"px:{a['ticker_eod']}" not in _MEMO}
    a_faire_ad = {a["ticker_eod"]: a for a in COTEES
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
                    "news": [],
                    "cs": None, "cons_str": "N/D", "cons_src": "erreur",
                    "h_dates": [], "h_closes": [], "h_src": "erreur",
                    "h_cache": False, "h_err": str(e),
                        "synthesis": "Données indisponibles.", "synth_src": "",
                        "fonda": {}, "fonda_src": "erreur",
                    }

    prices     = {a["ticker_eod"]: _MEMO[f"px:{a['ticker_eod']}"] for a in COTEES}
    asset_data = {a["ticker_eod"]: _MEMO[f"ad:{a['ticker_eod']}"] for a in COTEES}

    # ── 4. Indices macro ──────────────────────────────────────────────────────
    # Memoise par nom d'indice (comme les taux 10 ans juste en dessous) : en
    # mode --all-users, le S&P 500 et le CAC 40 sont les memes pour tout le
    # monde. Avant ce correctif, chaque utilisateur re-interrogeait EODHD
    # pour les memes deux indices -- un des postes qui faisait atteindre le
    # quota journalier avant la fin du run (voir get_index).
    indices_data = {}
    for idx_name, idx_sym in INDICES.items():
        cle = f"idx:{idx_name}"
        if cle not in _MEMO:
            _MEMO[cle] = get_index(idx_sym)
        indices_data[idx_name] = _MEMO[cle]

    macro_score = score_macro(indices_data)

    # ── 4 bis. Taux 10 ans (contexte obligataire) ────────────────────────────
    # Memoise par symbole : en mode --all-users, les taux sont les memes pour
    # tout le monde et ne sont donc interroges qu'une fois par run.
    bonds_data = {}
    for b_name, b_sym in BONDS.items():
        cle = f"bond:{b_sym['eod']}"
        if cle not in _MEMO:
            info = get_bond_yield(b_sym)
            if info["yield"] is not None:
                info["trend_bp"] = get_bond_trend(b_sym)
                session_cache[f"bond_{b_sym['eod']}"] = info["yield"]
            else:
                # Repli sur le dernier niveau connu : un taux souverain bouge
                # lentement, une valeur de la veille reste informative -- a
                # condition de le signaler.
                garde = session_cache.get(f"bond_{b_sym['eod']}")
                info = ({"yield": float(garde), "change_bp": None, "trend_bp": None,
                         "source": "Cache session (niveau precedent)"}
                        if garde else {**info, "trend_bp": None})
            _MEMO[cle] = info
        bonds_data[b_name] = _MEMO[cle]

    # ── 5. Watchlist cours ────────────────────────────────────────────────────
    # Yahoo Finance uniquement (get_price_yahoo) -- volontaire : la watchlist
    # ne detient rien, ne pese sur aucun quota EODHD/TwelveData deja compte au
    # plus juste pour le portefeuille reel. Prefixe de cache dedie ("wpxy:")
    # pour ne jamais melanger avec d'anciennes valeurs mises en cache via
    # l'ancien chemin ("wpx:").
    watchlist_prices = {}
    for w in WATCHLIST:
        k = f"wpxy:{w['ticker_eod']}"
        if k not in _MEMO:
            p, chg, src, from_cache, note = get_price_yahoo(w, eur_usd, session_cache)
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
        **{n: bonds_data[n]["source"] for n in bonds_data},
    }
    assets_history = {}

    for asset in PORTFOLIO:
        key = asset["ticker_eod"]

        # ── Actif NON COTE : la valeur vient de la saisie, pas d'une API ─────
        # On produit un resultat au meme format que les autres pour que tout
        # l'aval (totaux, repartition, stops, rendu HTML) le traite sans avoir
        # a connaitre le cas particulier. Les champs d'analyse boursiere sont
        # a None : un appartement n'a ni PER, ni consensus d'analystes, et
        # inventer une valeur neutre reviendrait a mentir.
        if asset.get("manuel"):
            valeur   = float(asset.get("valeur_manuelle") or asset.get("cost_eur") or 0.0)
            cout_m   = float(asset.get("cost_eur") or valeur)
            pnl_m    = round(valeur - cout_m, 2)
            pnl_m_pct = round(pnl_m / cout_m * 100, 2) if cout_m else 0.0

            history_rows.append({
                "date": jour_seance, "time": now.strftime("%H:%M"),
                "ticker": key, "name": asset["name"],
                "price_eur": valeur, "cost_eur": cout_m, "qty": 1,
                "vm": valeur, "pnl_brut": pnl_m, "pnl_brut_pct": pnl_m_pct,
                "pnl_net": pnl_m, "pnl_net_pct": pnl_m_pct,
                "score": "", "confiance": 0, "rec": "NON COTE",
            })
            sources_log[key] = {"cours": "Saisie manuelle"}
            results.append({
                "asset": asset, "price_eur": valeur, "chg_pct": 0.0,
                "price_src": "Saisie manuelle", "vm": valeur,
                "pnl_brut": pnl_m, "pnl_brut_pct": pnl_m_pct,
                "pnl_net": pnl_m, "pnl_net_pct": pnl_m_pct,
                "score": None, "confiance": 0.0, "detail": {}, "fonda": {},
                "non_appl": sorted(POIDS_NOTE), "manquants": [],
                "classe_label": asset.get("classe_label", "Actif"),
                "fonda_src": "sans objet",
                "position": None, "rec": "NON COTE",
                "just": (f"{asset.get('classe_label', 'Actif')} valorise a la main : "
                         f"{valeur:,.2f} EUR. Aucune donnee de marche n'est "
                         f"collectee pour cette ligne.").replace(",", " "),
                "cs": None,
                "cons_str": "N/D", "cons_src": "sans objet",
                "hist_label": "N/D", "ret_1m": 0.0, "ret_3m": 0.0, "ret_6m": 0.0,
                "h_src": "sans objet", "synthesis": "", "synth_src": "",
            })
            continue

        price_info = prices.get(key, (None, 0.0, "manquant", False, None))
        price_eur, chg_pct, price_src, price_cache, price_note = price_info

        d = asset_data.get(key, {})
        h_dates  = d.get("h_dates", [])
        h_closes = d.get("h_closes", [])

        # BUG CORRIGE (19/09/2026) : chg_pct du fournisseur n'etait pas
        # fiable -- toujours a 0.0 cote TwelveData (jamais renvoye par
        # cross_validate), et pas toujours juste cote EODHD (une ligne
        # pouvait afficher +0.00% un jour ou son historique montrait une
        # vraie hausse a deux chiffres). On le recalcule depuis les deux
        # dernieres clotures de l'historique deja telecharge, deja en EUR.
        # Le chiffre fournisseur reste utilise si le recalcul est impossible
        # (historique trop court) : mieux vaut un chiffre imprecis qu'aucun.
        chg_recalc = variation_jour_pct(price_eur, h_closes)
        if chg_recalc is not None:
            chg_pct = chg_recalc

        if h_closes and not d.get("h_cache"):
            _cache_set(session_cache, f"hist_{key}", {"dates": h_dates, "closes": h_closes})

        if price_eur and not price_cache:
            _cache_set(session_cache, f"price_{key}", price_eur)

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

        # ── NOTE DU TITRE : independante du detenteur ────────────────────
        fonda = d.get("fonda") or {}
        sc_hist, hist_label, ret_1m, ret_3m, ret_6m = score_history(h_dates, h_closes)
        cs   = d.get("cs")

        composantes = {
            "valorisation": score_valorisation(fonda),
            "sante":        score_sante(fonda),
            "croissance":   score_croissance(fonda),
            "momentum":     sc_hist,
            "consensus":    cs,
            "risque":       score_risque(fonda, h_dates, h_closes,
                                         taux_ligne(asset, eur_usd, session_cache)),
        }
        classe_actif = asset.get("asset_class") or asset.get("asset_type") or "action"
        total_score, confiance, detail, non_appl, manquants = note_titre(
            composantes, classe_actif)

        rec  = recommend(total_score, confiance, pnl_net_pct, len(detail))
        just = justification(asset["name"], pnl_net, pnl_net_pct, detail,
                             total_score, confiance, hist_label, macro_score,
                             non_appl, manquants,
                             asset.get("classe_label") or classe_actif)

        history_rows.append({
            "date":         jour_seance,
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
            "score":        total_score if total_score is not None else "",
            "confiance":    confiance,
            "rec":          rec,
        })

        # Toute note sur le cours remonte, qu'elle vienne du cache ou d'une
        # conversion de devise : un chiffre accompagne d'une reserve doit
        # toujours porter cette reserve jusqu'au rapport.
        if price_note:
            cache_warns.append(f"{asset['name']} -- cours : {price_note}")
        if d.get("h_cache") and d.get("h_err"):
            cache_warns.append(f"{asset['name']} -- historique : {d['h_err']}")

        sources_log[key] = {
            "cours":     price_src,
            "consensus": d.get("cons_src", "N/D"),
            "historique": d.get("h_src",   "N/D"),
            "synthese":  d.get("synth_src","N/D"),
            "fondamentaux": d.get("fonda_src", "N/D"),
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
            "confiance":    confiance,
            "detail":       detail,
            # Deux listes distinctes, parce que ce sont deux situations
            # distinctes : « la question n'a pas de sens pour cet actif » et
            # « la reponse n'est pas arrivee ». Le rapport les affiche a part.
            "non_appl":     non_appl,
            "manquants":    manquants,
            "classe_label": asset.get("classe_label") or classe_actif,
            "fonda":        fonda,
            "fonda_src":    d.get("fonda_src", "N/D"),
            "position":     score_position(price_eur, cost_eur, pnl_net_pct, 0.0),
            "rec":          rec,
            "just":         just,
            "cs":           cs,
            "cons_str":     d.get("cons_str", "N/D"),
            "cons_src":     d.get("cons_src", "N/D"),
            "hist_label":   hist_label,
            "ret_1m":       ret_1m,
            "ret_3m":       ret_3m,
            "ret_6m":       ret_6m,
            "h_src":        d.get("h_src", "N/D"),
            "synthesis":    d.get("synthesis", ""),
            "synth_src":    d.get("synth_src", ""),
        })

    # ── 8. Tri par score décroissant ─────────────────────────────────────────
    results.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)

    # ── 9. Totaux portefeuille ────────────────────────────────────────────────
    total_vm       = round(sum(r["vm"] for r in results), 2)
    total_cost     = round(sum(r["asset"]["cost_eur"] * r["asset"]["qty"] for r in results), 2)
    total_pnl_brut = round(sum(r["pnl_brut"] for r in results), 2)
    total_pnl_brut_pct = round(total_pnl_brut / total_cost * 100, 2) if total_cost else 0
    total_pnl_net  = round(sum(r["pnl_net"] for r in results), 2)
    total_pnl_net_pct = round(total_pnl_net / total_cost * 100, 2) if total_cost else 0

    # ── 9 bis. Repartition multi-actifs ──────────────────────────────────────
    repartition = calc_repartition(results, total_vm)

    # ── 9 ter. Capital de reference pour le dimensionnement ──────────────────
    # QUEL CAPITAL ? La question n'est pas anodine. Risquer 1% de 673 000 EUR
    # dont 480 000 d'immobilier, c'est risquer 6 730 EUR par idee sur un
    # portefeuille boursier de 67 000 EUR : un dixieme du portefeuille sur une
    # seule ligne. Absurde.
    #
    # Le capital de reference retenu est donc le capital REELLEMENT MOBILISABLE
    # en bourse : valeurs cotees + liquidites. L'immobilier, les collections et
    # les autres actifs illiquides en sont exclus. Un profil peut imposer sa
    # propre valeur via settings.capital_reference.
    capital_ref = _nombre_simple(PROFILE.get("settings", {}).get("capital_reference"))
    if capital_ref is None or capital_ref <= 0:
        capital_ref = round(sum(
            r["vm"] for r in results
            if (not r["asset"].get("manuel")) or r["asset"].get("asset_class") == "cash"
        ), 2)
    capital_ref = capital_ref or total_vm

    # ── 9 quater. Stops, alertes et dimensionnement ─────────────────────────
    risque = evaluer_risque(results, asset_data, capital_ref, eur_usd,
                            jour_seance, session_cache)

    # ── 10. Graphique combiné ─────────────────────────────────────────────────
    chart_path   = os.path.join(CHARTS_DIR, "portfolio_combined.png")
    chart_ok     = generate_combined_chart(assets_history, chart_path)

    # ── 11. Sauvegarde cache ──────────────────────────────────────────────────
    if save_cache:
        save_session_cache(session_cache)

    # ── 12. Historique CSV ────────────────────────────────────────────────────
    append_history(now, history_rows)
    append_correlation_history(now, risque.get("indice_correlation"))

    # ── 13. Génération du rapport Markdown ───────────────────────────────────
    macro_trend = "Haussiere" if macro_score >= 6 else "Baissiere" if macro_score <= 4 else "Neutre"

    lines = [
        f"# Rapport de Portefeuille v7.5 -- {now.strftime('%d/%m/%Y %H:%M')} (Paris)",
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
        chg   = idx_val["change_pct"]
        prix  = idx_val["price"]
        # BUG CORRIGE (19/09/2026) : chg/prix valaient 0.0 (jamais None) meme
        # quand l'indice etait indisponible (quota EODHD atteint) -- "0.00%"
        # s'affichait comme si c'etait une vraie seance plate. Desormais
        # get_index() renvoie None dans ce cas, et on l'affiche comme tel.
        if chg is None or prix is None:
            lines.append(f"| {idx_name} | n/d | n/d |")
            continue
        sym  = "^" if chg >= 0 else "v"
        sign = "+" if chg >= 0 else ""
        prix_fmt = f"{prix:,.2f}".replace(",", " ")
        lines.append(f"| {idx_name} | {sym} {sign}{chg:.2f}% | {prix_fmt} |")

    lines += [""]
    # Contexte obligataire
    if any(b.get("yield") is not None for b in bonds_data.values()):
        lines += [
            "**Taux souverains 10 ans :**",
            "",
            "| Taux | Variation | Niveau | Sur 1 mois |",
            "|------|-----------|--------|------------|",
        ]
        for b_name, b in bonds_data.items():
            if b.get("yield") is None:
                lines.append(f"| {b_name} | n/d | n/d | n/d |")
                continue

            chg = b.get("change_bp")
            if chg is None:
                var = "--"
            else:
                var = f"{'^' if chg >= 0 else 'v'} {'+' if chg >= 0 else ''}{chg:.1f} pb"

            tr = b.get("trend_bp")
            trend = "--" if tr is None else f"{'+' if tr >= 0 else ''}{tr:.0f} pb"

            lines.append(f"| {b_name} | {var} | {b['yield']:.2f}% | {trend} |")

        us = bonds_data.get("UST 10 ans (US)", {}).get("yield")
        fr = bonds_data.get("OAT 10 ans (FR)", {}).get("yield")
        if us is not None and fr is not None:
            lines.append(f"| Ecart OAT - UST | -- | {(fr - us) * 100:+.0f} pb | -- |")
        lines += [""]

    # Memoise pour la meme raison que les indices juste au-dessus : les
    # manchettes macro generales ne dependent pas de l'utilisateur.
    if "macro_news" not in _MEMO:
        _MEMO["macro_news"] = get_macro_news(5)
    macro_news = _MEMO["macro_news"]
    if macro_news:
        lines.append("**Manchettes macro :**")
        lines.append("")
        for n in macro_news:
            lines.append(f"- {n}")
    # ── Stops et alertes ─────────────────────────────────────────────────────
    lines += bloc_md_stops(risque)

    # ── Repartition multi-actifs ─────────────────────────────────────────────
    lines += bloc_md_repartition(repartition)

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

        note_s = (f"**{r['score']}/10** ({r['confiance']:.0f}%)"
                  if r["score"] is not None else "n/d")
        ret_1m_s = f"{r['ret_1m']:+.1f}%"
        ret_3m_s = f"{r['ret_3m']:+.1f}%"
        ret_6m_s = f"{r['ret_6m']:+.1f}%"

        lines += [
            f"### {asset['name']} `{asset['ticker_eod']}`",
            "",
            "| Cours | Variation | VM | P&L Brut | P&L Net | Note (confiance) | Recomm. |",
            "|-------|-----------|-----|----------|---------|------------------|---------|",
            f"| {r['price_eur']:.2f} EUR | {chg_str} | {r['vm']:.2f} EUR "
            f"| {pnl_b_str} | {pnl_n_str} | {note_s} | {r['rec']} |",
            "",
        ]

        synth = r.get("synthesis", "").strip()
        synth_src_val = r.get("synth_src", "RSS Yahoo Finance (brut)").strip()
        if synth and "Aucune actualite" not in synth:
            lines.append(f"**Actualite recente :** *(source : {synth_src_val})*")
            lines.append("")
            lines.append(f"> {synth}")
            lines.append("")

        # Detail de la note : chaque composante et son poids reel
        detail = r.get("detail") or {}
        if detail:
            libelles = {"valorisation": "Valorisation", "sante": "Sante financiere",
                        "croissance": "Croissance", "momentum": "Momentum",
                        "consensus": "Consensus", "risque": "Risque"}
            lines += ["**Detail de la note :**", "",
                      "| Composante | Note | Poids |",
                      "|------------|------|-------|"]
            poids_dispo = sum(POIDS_NOTE[k] for k in detail)
            for cle in POIDS_NOTE:
                if cle in detail:
                    part = POIDS_NOTE[cle] / poids_dispo * 100
                    lines.append(f"| {libelles[cle]} | {detail[cle]:.1f}/10 | {part:.0f}% |")
            lines.append("")

            # DEUX PHRASES, DEUX SENS. Les melanger etait le defaut corrige en
            # v14 : un ETF affichait « non disponible : valorisation, sante,
            # croissance » comme s'il s'agissait d'une panne, alors que ces
            # grandeurs n'existent pas pour un ETF.
            non_appl = [libelles[k] for k in POIDS_NOTE if k in (r.get("non_appl") or [])]
            manquants = [libelles[k] for k in POIDS_NOTE if k in (r.get("manquants") or [])]

            if non_appl:
                lines.append(f"*Sans objet pour un actif de type "
                             f"{str(r.get('classe_label', 'actif')).lower()} : "
                             f"{', '.join(non_appl)}. Ces criteres n'existent pas "
                             f"pour ce type d'actif : ils sont exclus du calcul et "
                             f"ne font PAS baisser l'indice de confiance.*")
                lines.append("")
            if manquants:
                motif = r.get("fonda_src", "")
                precision = ""
                if motif and any(a in ("Valorisation", "Sante financiere", "Croissance")
                                 for a in manquants):
                    precision = f" Motif cote fondamentaux : {motif}."
                lines.append(f"*Attendu mais non obtenu : {', '.join(manquants)} "
                             f"-- poids redistribues sur les composantes ci-dessus. "
                             f"C'est ce qui fait baisser l'indice de confiance."
                             f"{precision}*")
                lines.append("")

        # Ratios fondamentaux bruts, pour verification manuelle
        f_r = r.get("fonda") or {}
        if f_r:
            morceaux = []
            for cle, lib, suffixe in (("per", "PER", ""), ("peg", "PEG", ""),
                                      ("ev_ebitda", "EV/EBITDA", ""),
                                      ("p_book", "P/B", ""),
                                      ("marge_nette", "Marge nette", "%"),
                                      ("roe", "ROE", "%"),
                                      ("croiss_ca", "Croiss. CA", "%"),
                                      ("beta", "Beta", "")):
                v = f_r.get(cle)
                if v is None:
                    continue
                if suffixe == "%":
                    v *= 100
                morceaux.append(f"{lib} {v:.1f}{suffixe}")
            if morceaux:
                lines.append(f"**Fondamentaux :** {' | '.join(morceaux)} "
                             f"*(source : {r.get('fonda_src', 'N/D')})*")

        lines += [
            f"**Consensus analystes :** {r['cons_str']} *(source : {r['cons_src']})*",
            f"**Perf. historique :** 1M {ret_1m_s} | 3M {ret_3m_s} | 6M {ret_6m_s} -- {r['hist_label']} *(source : {r['h_src']})*",
            "",
            f"**Justification :** {r['just']}",
            "",
            "---",
            "",
        ]

    # ── Plus-values réalisées ─────────────────────────────────────────────────
    ops_closes, tot_closes = compute_closed_trades(CLOSED)
    if ops_closes:
        signe_t = "+" if tot_closes["net"] >= 0 else "-"
        lines += [
            "",
            "## Plus-values realisees",
            "",
            "*Positions vendues. Ces lignes ne figurent plus dans le portefeuille "
            "et n'entrent pas dans la valorisation ci-dessus.*",
            "",
            "| Valeur | Qte | Achat | Vente | Produit | Frais A/R | +/- value nette |",
            "|--------|-----|-------|-------|---------|-----------|-----------------|",
        ]
        for o in ops_closes:
            sg = "+" if o["pv_nette"] >= 0 else "-"
            vente_s = f"{o['sell_price']:.2f} {o['sell_currency']}"
            if o["sell_currency"] != "EUR":
                vente_s += f" @ {o['fx_at_sale']:.5f}"
            lines.append(
                f"| {o['name']} | {o['qty']:g} | {o['buy_price_eur']:.2f} EUR "
                f"| {vente_s} | {o['produit_brut']:.2f} EUR | {o['frais']:.2f} EUR "
                f"| **{sg}{abs(o['pv_nette']):.2f} EUR ({sg}{abs(o['pv_pct']):.1f}%)** |"
            )
        lines += [
            f"| **TOTAL** | — | **{tot_closes['investi']:.2f} EUR** | — | — | — "
            f"| **{signe_t}{abs(tot_closes['net']):.2f} EUR "
            f"({signe_t}{abs(tot_closes['pct']):.1f}%)** |",
            "",
        ]
        for o in ops_closes:
            if o["sell_date"]:
                lines.append(f"- {o['name']} : vendu le {o['sell_date']}"
                             + (f" — {o['note']}" if o["note"] else ""))
        lines += ["", "---"]

    # ── Synthèse portefeuille ─────────────────────────────────────────────────
    lines += [
        "## Synthese Portefeuille",
        "",
        "| Valeur | Cours EUR | VM EUR | P&L Brut | P&L Net | Note | Conf. | Recomm. |",
        "|--------|-----------|--------|----------|---------|------|-------|---------|",
    ]
    for r in results:
        pnl_b_sign = "+" if r["pnl_brut"] >= 0 else "-"
        pnl_n_sign = "+" if r["pnl_net"] >= 0 else "-"
        # Les colonnes de note sont construites a part : la concatenation
        # implicite de f-strings lie plus fort que le ternaire, un
        # `... if ... else ...` en fin d'expression escamoterait les
        # colonnes precedentes.
        cell_note = (f"{r['score']}/10 | {r['confiance']:.0f}%"
                     if r["score"] is not None else "n/d | -")
        lines.append(
            f"| {r['asset']['name']} | {r['price_eur']:.2f} | {r['vm']:.2f} "
            f"| {pnl_b_sign}{abs(r['pnl_brut']):.2f} ({pnl_b_sign}{abs(r['pnl_brut_pct']):.1f}%) "
            f"| {pnl_n_sign}{abs(r['pnl_net']):.2f} ({pnl_n_sign}{abs(r['pnl_net_pct']):.1f}%) "
            f"| {cell_note} | {r['rec']} |"
        )

    total_pnl_b_sign = "+" if total_pnl_brut >= 0 else "-"
    total_pnl_n_sign = "+" if total_pnl_net  >= 0 else "-"
    lines += [
        f"| **TOTAL** | — | **{total_vm:.2f}** "
        f"| **{total_pnl_b_sign}{abs(total_pnl_brut):.2f} ({total_pnl_b_sign}{abs(total_pnl_brut_pct):.1f}%)** "
        f"| **{total_pnl_n_sign}{abs(total_pnl_net):.2f} ({total_pnl_n_sign}{abs(total_pnl_net_pct):.1f}%)** "
        f"| — | — | — |",
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
        lines += ["", "## Avertissements Donnees", ""]
        for w in cache_warns:
            lines.append(f"- ⚠️  {w}")
        lines.append("")

    if eur_usd_warn:
        lines += ["", f"> ⚠️  {eur_usd_warn}", ""]

    report_path = REPORT_PATH
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Alerte courriel APRES ecriture du rapport : si l'envoi echoue, le rapport
    # est deja sur le disque et l'alerte y figure.
    try:
        lien_rapport_utilisateur = ""
        try:
            from api.load_portfolio import lien_rapport as _lien
            lien_rapport_utilisateur = _lien(USER, creer=False)
        except Exception:
            pass
        envoyer_alertes(risque, lien_rapport_utilisateur)
    except Exception as e:
        _log.error("Etape d'alerte ignoree : %s", e)

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
