#!/usr/bin/env python3
"""
Normalisation des profils utilisateurs — pont interface HTML → analyseur.
================================================================================

L'interface web laisse l'utilisateur saisir une ligne de portefeuille de façon
naturelle : un nom, un ticker, une place de cotation, une quantité, un prix de
revient. L'analyseur, lui, a besoin d'un ticker différent par fournisseur de
données (Finnhub, EODHD, TwelveData, AlphaVantage, Yahoo) et d'un code marché
qui décide du chemin d'appel API.

C'est ce module qui fait la traduction. Il est le SEUL endroit où cette
correspondance est écrite : ni l'interface ni l'analyseur n'ont à la connaître.

Format d'entrée (ce que produit interface.html)
-----------------------------------------------
{
  "username": "alice",
  "settings": {
    "broker": "boursobank",
    "indices": ["S&P 500", "CAC 40"],
    "watchlist": [{"name": "NVIDIA", "ticker": "NVDA", "market": "us",
                   "sector": "Semi-conducteurs"}]
  },
  "lines": [
    {"name": "Air Liquide", "ticker": "AI.PA", "isin": "FR0000120073",
     "market": "euronext_paris", "quantity": 2, "buy_price": 159.50}
  ]
}

Format de sortie (ce que consomme portfolio_analyzer.py)
--------------------------------------------------------
{
  "username": "alice",
  "settings": {"broker": ..., "broker_label": ..., "fees": {...},
               "indices": {...}, "watchlist": [...]},
  "lines": [
    {"name": "Air Liquide", "isin": "FR0000120073",
     "ticker_fh": "AI.PA", "ticker_eod": "AI.PA", "ticker_td": None,
     "ticker_av": None, "ticker_yf": "AI.PA",
     "qty": 2, "cost_eur": 159.50, "marche": "euronext"}
  ]
}
"""

import json
from pathlib import Path

ROOT          = Path(__file__).resolve().parent.parent
BROKERS_PATH  = ROOT / "data" / "brokers.json"
PORTFOLIOS    = ROOT / "data" / "portfolios"
DEFAULT_INPUT = ROOT / "data" / "active_portfolio.json"


# =============================================================================
# PLACES DE COTATION
# =============================================================================
# `suffixe`  : suffixe EODHD / Yahoo du ticker
# `marche`   : code interne de routage API ("us" ou "euronext")
# `devise`   : devise de cotation par défaut de la place

MARCHES = {
    "us":             {"suffixe": ".US",    "marche": "us",       "devise": "USD", "label": "États-Unis (NYSE / Nasdaq)"},
    "euronext_paris": {"suffixe": ".PA",    "marche": "euronext", "devise": "EUR", "label": "Euronext Paris"},
    "euronext_ams":   {"suffixe": ".AS",    "marche": "euronext", "devise": "EUR", "label": "Euronext Amsterdam"},
    "euronext_bru":   {"suffixe": ".BR",    "marche": "euronext", "devise": "EUR", "label": "Euronext Bruxelles"},
    "euronext_lis":   {"suffixe": ".LS",    "marche": "euronext", "devise": "EUR", "label": "Euronext Lisbonne"},
    "euronext_mil":   {"suffixe": ".MI",    "marche": "euronext", "devise": "EUR", "label": "Borsa Italiana"},
    "xetra":          {"suffixe": ".XETRA", "marche": "euronext", "devise": "EUR", "label": "Xetra (Francfort)"},
    "madrid":         {"suffixe": ".MC",    "marche": "euronext", "devise": "EUR", "label": "Bolsa de Madrid"},
    "londres":        {"suffixe": ".LSE",   "marche": "euronext", "devise": "GBP", "label": "London Stock Exchange"},
    "suisse":         {"suffixe": ".SW",    "marche": "euronext", "devise": "CHF", "label": "SIX Swiss Exchange"},
}

SUFFIXE_VERS_MARCHE = {v["suffixe"].lstrip("."): k for k, v in MARCHES.items()}

ALIAS_MARCHES = {
    "usa": "us", "nasdaq": "us", "nyse": "us", "etats-unis": "us", "états-unis": "us",
    "euronext": "euronext_paris", "paris": "euronext_paris", "france": "euronext_paris",
    "amsterdam": "euronext_ams", "bruxelles": "euronext_bru", "brussels": "euronext_bru",
    "lisbonne": "euronext_lis", "milan": "euronext_mil", "italie": "euronext_mil",
    "francfort": "xetra", "allemagne": "xetra", "frankfurt": "xetra",
    "espagne": "madrid", "london": "londres", "royaume-uni": "londres",
    "zurich": "suisse", "switzerland": "suisse",
}

DEFAULT_FEES = {
    "euronext": {"threshold": 500,  "flat": 1.99, "rate": 0.006,  "min": 1.99},
    "us":       {"threshold": 6000, "flat": 6.95, "rate": 0.0012, "min": 6.95},
}


# =============================================================================
# COURTIERS
# =============================================================================

def charger_courtiers() -> dict:
    """Catalogue des courtiers et de leurs grilles de frais."""
    try:
        return json.loads(BROKERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"autre": {"label": "Autre / personnalisé", "fees": DEFAULT_FEES}}


def resoudre_frais(settings: dict) -> tuple:
    """Retourne (code_courtier, libellé, grille_de_frais).

    Une grille saisie à la main dans le profil (`custom_fees`) l'emporte sur le
    catalogue : c'est le cas d'un courtier absent de la liste.
    """
    courtiers = charger_courtiers()
    code      = str(settings.get("broker") or "autre").strip().lower()

    perso = settings.get("custom_fees")
    if isinstance(perso, dict) and perso:
        grille = {}
        for marche in ("euronext", "us"):
            base = dict(DEFAULT_FEES[marche])
            base.update({k: v for k, v in (perso.get(marche) or {}).items()
                         if isinstance(v, (int, float))})
            grille[marche] = base
        libelle = settings.get("broker_label") or "Grille personnalisée"
        return code, libelle, grille

    fiche  = courtiers.get(code) or courtiers.get("autre") or {}
    grille = fiche.get("fees") or DEFAULT_FEES
    complete = {}
    for marche in ("euronext", "us"):
        base = dict(DEFAULT_FEES[marche])
        base.update(grille.get(marche) or {})
        complete[marche] = base
    return code, fiche.get("label", code), complete


# =============================================================================
# TICKERS
# =============================================================================

def detecter_marche(ticker: str, marche_saisi: str = None) -> str:
    """Détermine la place de cotation, en priorité depuis la saisie."""
    if marche_saisi:
        cle = str(marche_saisi).strip().lower().replace(" ", "_")
        if cle in MARCHES:
            return cle
        if cle in ALIAS_MARCHES:
            return ALIAS_MARCHES[cle]

    t = str(ticker or "").strip().upper()
    if "." in t:
        suffixe = t.rsplit(".", 1)[1]
        if suffixe in SUFFIXE_VERS_MARCHE:
            return SUFFIXE_VERS_MARCHE[suffixe]

    # Un ticker nu, sans suffixe, est américain dans l'immense majorité des cas.
    return "us"


def deriver_tickers(ticker: str, place: str) -> dict:
    """Construit les cinq variantes de ticker attendues par l'analyseur."""
    fiche  = MARCHES.get(place, MARCHES["us"])
    brut   = str(ticker or "").strip().upper()
    racine = brut.rsplit(".", 1)[0] if "." in brut else brut

    if fiche["marche"] == "us":
        # Finnhub, TwelveData, AlphaVantage et Yahoo attendent le ticker nu ;
        # EODHD veut le suffixe .US.
        return {
            "ticker_fh":  racine,
            "ticker_eod": f"{racine}.US",
            "ticker_td":  racine,
            "ticker_av":  racine,
            "ticker_yf":  racine,
        }

    # Hors États-Unis : TwelveData et AlphaVantage ne couvrent pas ces places
    # dans leur offre gratuite. On les laisse à None pour éviter des appels
    # voués à l'échec qui consommeraient du quota pour rien.
    complet = f"{racine}{fiche['suffixe']}"
    return {
        "ticker_fh":  complet,
        "ticker_eod": complet,
        "ticker_td":  None,
        "ticker_av":  None,
        "ticker_yf":  complet,
    }


# =============================================================================
# NORMALISATION
# =============================================================================

def normaliser_ligne(ligne: dict, index: int = 0) -> dict:
    """Convertit une ligne saisie dans l'interface vers le format analyseur."""
    nom = str(ligne.get("name") or ligne.get("nom") or "").strip()
    if not nom:
        raise ValueError(f"Ligne {index + 1} : nom manquant")

    ticker = (ligne.get("ticker") or ligne.get("ticker_eodhd")
              or ligne.get("ticker_finnhub") or ligne.get("symbole") or "")
    ticker = str(ticker).strip()
    if not ticker:
        raise ValueError(f"Ligne {index + 1} ({nom}) : ticker manquant")

    place = detecter_marche(ticker, ligne.get("market") or ligne.get("marche"))
    fiche = MARCHES.get(place, MARCHES["us"])

    try:
        qty = float(ligne.get("quantity", ligne.get("qty", 0)))
    except (TypeError, ValueError):
        raise ValueError(f"Ligne {index + 1} ({nom}) : quantité invalide")

    try:
        cout = float(ligne.get("buy_price", ligne.get("cost_eur", 0)))
    except (TypeError, ValueError):
        raise ValueError(f"Ligne {index + 1} ({nom}) : prix de revient invalide")

    if qty <= 0:
        raise ValueError(f"Ligne {index + 1} ({nom}) : la quantité doit être > 0")
    if cout <= 0:
        raise ValueError(f"Ligne {index + 1} ({nom}) : le prix de revient doit être > 0")

    sortie = {
        "name":       nom,
        "isin":       str(ligne.get("isin", "")).strip(),
        "qty":        qty,
        "cost_eur":   cout,
        "marche":     fiche["marche"],
        "place":      place,
        "devise":     str(ligne.get("currency") or fiche["devise"]).upper(),
        "asset_type": str(ligne.get("asset_type", "action")).strip(),
    }
    sortie.update(deriver_tickers(ticker, place))
    return sortie


def normaliser_watchlist(items) -> list:
    """La watchlist suit le même schéma mais sans quantité ni prix."""
    sortie = []
    for it in (items or []):
        nom = str(it.get("name") or "").strip()
        tck = str(it.get("ticker") or it.get("ticker_eod") or "").strip()
        if not nom or not tck:
            continue
        place = detecter_marche(tck, it.get("market") or it.get("marche"))
        fiche = MARCHES.get(place, MARCHES["us"])
        entree = {
            "name":   nom,
            "marche": fiche["marche"],
            "place":  place,
            "sector": str(it.get("sector", "")).strip(),
        }
        entree.update(deriver_tickers(tck, place))
        sortie.append(entree)
    return sortie


def normalize_profile(raw: dict, username: str = None) -> dict:
    """Point d'entrée principal — appelé par portfolio_analyzer.py."""
    raw       = raw or {}
    settings  = dict(raw.get("settings") or {})
    lignes_in = raw.get("lines") or raw.get("lignes") or []

    lignes, erreurs = [], []
    for i, ligne in enumerate(lignes_in):
        try:
            lignes.append(normaliser_ligne(ligne, i))
        except ValueError as e:
            erreurs.append(str(e))

    code, libelle, frais = resoudre_frais(settings)
    settings["broker"]       = code
    settings["broker_label"] = libelle
    settings["fees"]         = frais
    settings["watchlist"]    = normaliser_watchlist(settings.get("watchlist"))

    return {
        "username": str(username or raw.get("username") or "default").strip().lower(),
        "lines":    lignes,
        "settings": settings,
        "erreurs":  erreurs,
    }


def load_profile(path=None, username: str = None) -> dict:
    """Charge et normalise un profil depuis un fichier JSON."""
    src = Path(path) if path else DEFAULT_INPUT
    if not src.exists():
        raise FileNotFoundError(f"Profil introuvable : {src}")
    return normalize_profile(json.loads(src.read_text(encoding="utf-8")), username)


def load_portfolio(path=None) -> list:
    """Compatibilité ascendante : retourne uniquement la liste des lignes."""
    profil = load_profile(path)
    if not profil["lines"]:
        raise ValueError(f"Aucune ligne exploitable. {'; '.join(profil['erreurs'])}")
    return profil["lines"]


if __name__ == "__main__":
    import sys
    chemin = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        p = load_profile(chemin)
    except (FileNotFoundError, ValueError) as err:
        print(f"❌ {err}")
        sys.exit(1)

    print(f"Profil : {p['username']} — courtier : {p['settings']['broker_label']}")
    for l in p["lines"]:
        print(f"  {l['name']:<24} {l['ticker_eod']:<10} {l['marche']:<9} "
              f"{l['qty']}× {l['cost_eur']} {l['devise']}")
    for e in p["erreurs"]:
        print(f"  ⚠️  {e}")


# =============================================================================
# LIENS DE RAPPORT
# =============================================================================
# Chaque utilisateur reçoit une adresse Cloudflare personnelle, construite
# autour d'un jeton aléatoire plutôt que de son nom. Deux raisons :
#   - un identifiant deviné (« /bob/ ») donnerait accès au portefeuille d'un
#     autre utilisateur, puisque Cloudflare Pages sert des fichiers statiques
#     sans authentification ;
#   - le jeton peut être révoqué et regénéré sans renommer le compte.

import secrets

LIENS_PATH = ROOT / "data" / "report_links.json"


def charger_liens() -> dict:
    """Table {utilisateur: jeton}."""
    try:
        return json.loads(LIENS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def enregistrer_liens(table: dict):
    LIENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIENS_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def jeton_rapport(username: str, creer: bool = True, rotation: bool = False) -> str:
    """Jeton du rapport d'un utilisateur, créé à la volée si besoin."""
    user  = str(username or "default").strip().lower()
    table = charger_liens()

    if rotation or (creer and not table.get(user)):
        table[user] = secrets.token_hex(8)
        enregistrer_liens(table)

    return table.get(user, "")


def dossier_rapport(username: str, creer: bool = True) -> str:
    """Chemin de publication du rapport, relatif à la racine du dépôt."""
    jeton = jeton_rapport(username, creer=creer)
    return f"docs/r/{jeton}" if jeton else f"docs/{str(username).strip().lower()}"


def lien_rapport(username: str, base: str = None, creer: bool = True) -> str:
    """URL publique complète du rapport."""
    import os as _os
    base  = (base or _os.getenv("CLOUDFLARE_PAGES_URL", "https://projectone.pages.dev")).rstrip("/")
    jeton = jeton_rapport(username, creer=creer)
    return f"{base}/r/{jeton}/" if jeton else f"{base}/"
