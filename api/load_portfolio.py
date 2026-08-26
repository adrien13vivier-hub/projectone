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
    "risque_pct": 1.0,                       // budget de risque par idée
    "poids_max_pct": 15.0,                   // plafond de poids par ligne
    "stop_defaut": {"type": "vq"},           // stop appliqué aux lignes muettes
    "watchlist": [{"name": "NVIDIA", "ticker": "NVDA", "market": "us",
                   "sector": "Semi-conducteurs"}]
  },
  "lines": [
    {"name": "Air Liquide", "ticker": "AI.PA", "isin": "FR0000120073",
     "market": "euronext_paris", "quantity": 2, "buy_price": 159.50,
     "asset_class": "action", "account": "PEA Bourso",
     "tags": ["dividende", "industrie"],
     "stop": {"type": "trailing", "value": 15}},

    {"name": "Bitcoin", "ticker": "BTC-USD", "market": "crypto",
     "quantity": 0.25, "buy_price": 41000, "asset_class": "crypto",
     "account": "Ledger", "stop": {"type": "vq"}},

    {"name": "Livret A", "asset_class": "cash", "account": "Livret A",
     "value": 22800}
  ]
}

CE QUI A CHANGÉ EN v8 -- MULTI-ACTIFS
--------------------------------------
Le modèle ne connaissait qu'un seul objet : l'action cotée. Il en connaît
désormais neuf (voir CLASSES_ACTIFS), réparties en deux familles :

  COTÉES    action, etf, crypto, obligation, metal
            -> ont un ticker, un cours interrogé par API, un historique.

  MANUELLES cash, immobilier, collection, autre
            -> n'ont pas de marché. L'utilisateur saisit une VALEUR (`value`)
               et éventuellement un prix d'acquisition (`buy_value`). Aucune
               API n'est appelée pour elles : c'est ce qui permet de faire
               figurer un livret ou un appartement dans la vue d'ensemble sans
               consommer un seul crédit de quota.

Trois champs libres s'ajoutent sur toutes les lignes :
  account   le compte ou le courtier qui détient la ligne (regroupement)
  tags      étiquettes personnelles, en liste (thème, stratégie, risque…)
  stop      configuration de stop, transmise telle quelle à risk_engine.py

Format de sortie (ce que consomme portfolio_analyzer.py)
--------------------------------------------------------
{
  "username": "alice",
  "settings": {"broker": ..., "broker_label": ..., "fees": {...},
               "indices": {...}, "watchlist": [...],
               "risque_pct": 1.0, "poids_max_pct": 15.0, "stop_defaut": {...}},
  "lines": [
    {"name": "Air Liquide", "isin": "FR0000120073",
     "ticker_fh": "AI.PA", "ticker_eod": "AI.PA", "ticker_td": None,
     "ticker_av": None, "ticker_yf": "AI.PA",
     "qty": 2, "cost_eur": 159.50, "marche": "euronext", "devise": "EUR",
     "asset_class": "action", "classe_label": "Action", "manuel": False,
     "account": "PEA Bourso", "tags": ["dividende", "industrie"],
     "stop": {"type": "trailing", "value": 15}}
  ]
}

RÉTROCOMPATIBILITÉ
------------------
Un profil écrit pour la v7 passe sans modification : les champs absents
prennent leurs valeurs par défaut (asset_class="action", account="",
tags=[], stop=None). Aucune migration de fichier n'est nécessaire.
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

    # Crypto-actifs : EODHD les publie sous la forme BTC-USD.CC, toujours
    # cotés en dollar. Le marché interne "crypto" les route vers ce chemin et
    # applique la conversion USD -> EUR comme pour une action américaine.
    "crypto":         {"suffixe": ".CC",    "marche": "crypto",   "devise": "USD", "label": "Crypto-actifs"},
}

SUFFIXE_VERS_MARCHE = {v["suffixe"].lstrip("."): k for k, v in MARCHES.items()}

# Place fictive des lignes sans marché (livret, immobilier, collection…).
# Elle n'apparaît pas dans MARCHES : aucune API ne doit pouvoir la router.
PLACE_MANUELLE = "manuel"


# =============================================================================
# CLASSES D'ACTIFS
# =============================================================================
# `manuel`  : True  -> aucun appel API, la valeur est saisie par l'utilisateur
# `place`   : place de cotation IMPOSÉE, quand la classe n'en admet qu'une
# `ordre`   : ordre d'affichage dans les menus et les tableaux de répartition
#
# La grille de frais n'est PAS choisie ici : elle découle du marché (`marche`)
# calculé plus bas — "crypto" pour les crypto-actifs, "manuel" pour les lignes
# non cotées, "us" ou "euronext" pour le reste. Une seule source de vérité.

CLASSES_ACTIFS = {
    "action":     {"label": "Action",         "manuel": False, "ordre": 1},
    "etf":        {"label": "ETF / Fonds",    "manuel": False, "ordre": 2},
    "obligation": {"label": "Obligation",     "manuel": False, "ordre": 3},
    "crypto":     {"label": "Crypto",         "manuel": False, "ordre": 4,
                   "place": "crypto"},
    "metal":      {"label": "Metal precieux", "manuel": False, "ordre": 5},
    "cash":       {"label": "Liquidites",     "manuel": True,  "ordre": 6},
    "immobilier": {"label": "Immobilier",     "manuel": True,  "ordre": 7},
    "collection": {"label": "Collection",     "manuel": True,  "ordre": 8},
    "autre":      {"label": "Autre",          "manuel": True,  "ordre": 9},
}

ALIAS_CLASSES = {
    "actions": "action", "stock": "action", "equity": "action", "titre": "action",
    "fonds": "etf", "tracker": "etf", "sicav": "etf", "opcvm": "etf",
    "obligations": "obligation", "bond": "obligation", "oblig": "obligation",
    "cryptomonnaie": "crypto", "cryptos": "crypto", "bitcoin": "crypto",
    "or": "metal", "gold": "metal", "argent": "metal", "metaux": "metal",
    "liquidites": "cash", "liquidite": "cash", "especes": "cash",
    "livret": "cash", "compte": "cash", "monetaire": "cash",
    "immo": "immobilier", "real_estate": "immobilier", "scpi": "immobilier",
    "collectible": "collection", "collectibles": "collection", "montre": "collection",
    "other": "autre", "divers": "autre",
}


def normaliser_classe(valeur, defaut: str = "action") -> str:
    """Ramène une classe d'actif saisie librement vers une clé connue."""
    cle = str(valeur or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cle in CLASSES_ACTIFS:
        return cle
    if cle in ALIAS_CLASSES:
        return ALIAS_CLASSES[cle]
    return defaut


def est_manuel(asset_class: str) -> bool:
    """True si la classe n'a pas de cotation (aucun appel API pour elle)."""
    return bool(CLASSES_ACTIFS.get(asset_class, {}).get("manuel"))


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
    # Les plateformes crypto facturent un pourcentage, sans palier ni minimum
    # fixe. 0,50% est l'ordre de grandeur d'un courtier grand public ; un
    # profil peut l'écraser via custom_fees.
    "crypto":   {"threshold": 0,    "flat": 0.0,  "rate": 0.005,  "min": 0.0},
    # Un livret ou un appartement ne se vend pas via un carnet d'ordres :
    # aucune friction de courtage ne doit être imputée à ces lignes.
    "manuel":   {"threshold": 0,    "flat": 0.0,  "rate": 0.0,    "min": 0.0},
}

# Marchés pour lesquels une grille est toujours complétée, même si le
# catalogue de courtiers n'en dit rien.
MARCHES_FRAIS = ("euronext", "us", "crypto", "manuel")


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
        for marche in MARCHES_FRAIS:
            base = dict(DEFAULT_FEES[marche])
            base.update({k: v for k, v in (perso.get(marche) or {}).items()
                         if isinstance(v, (int, float))})
            grille[marche] = base
        libelle = settings.get("broker_label") or "Grille personnalisée"
        return code, libelle, grille

    fiche  = courtiers.get(code) or courtiers.get("autre") or {}
    grille = fiche.get("fees") or DEFAULT_FEES
    complete = {}
    for marche in MARCHES_FRAIS:
        base = dict(DEFAULT_FEES[marche])
        base.update(grille.get(marche) or {})
        complete[marche] = base
    return code, fiche.get("label", code), complete


# =============================================================================
# TICKERS
# =============================================================================

def detecter_marche(ticker: str, marche_saisi: str = None,
                    asset_class: str = None) -> str:
    """Détermine la place de cotation, en priorité depuis la saisie.

    L'ordre de priorité est : la place IMPOSÉE par la classe d'actif, puis ce
    que l'utilisateur a écrit dans `market`, puis le suffixe du ticker, puis
    les États-Unis.

    Pourquoi la classe passe en premier : une ligne déclarée « crypto » avec un
    marché « us » est incohérente — les crypto-actifs ne sont publiés que sous
    le chemin .CC. Suivre la saisie enverrait la requête sur le Nasdaq et la
    ligne ressortirait sans cours. Seule la classe crypto impose sa place ;
    toutes les autres laissent l'utilisateur décider.
    """
    place_imposee = (CLASSES_ACTIFS.get(asset_class or "", {}) or {}).get("place")
    if place_imposee in MARCHES:
        return place_imposee

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

    if fiche["marche"] == "crypto":
        # EODHD attend une PAIRE : BTC-USD.CC. Un utilisateur qui saisit « BTC »
        # veut dire « BTC en dollar » : on complète plutôt que de rejeter.
        paire = racine if "-" in racine else f"{racine}-USD"
        return {
            "ticker_fh":  racine,
            "ticker_eod": f"{paire}.CC",
            # TwelveData couvre la crypto, mais son format (« BTC/USD ») et sa
            # devise de cotation diffèrent du chemin actions déjà en place. On
            # s'en tient volontairement à EODHD : une seule source, un seul
            # comportement à vérifier.
            "ticker_td":  None,
            "ticker_av":  None,
            "ticker_yf":  paire,
        }

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

def _nombre(valeur, defaut=None):
    """float(valeur) tolérant : renvoie `defaut` au lieu de lever."""
    if valeur is None or isinstance(valeur, bool):
        return defaut
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return defaut
    return defaut if v != v else v


def normaliser_tags(valeur) -> list:
    """Étiquettes libres, dédoublonnées, ordre de saisie conservé.

    Accepte une liste ou une chaîne séparée par des virgules — l'interface
    envoie l'une ou l'autre selon le champ utilisé.
    """
    if isinstance(valeur, str):
        brut = [m for m in valeur.replace(";", ",").split(",")]
    elif isinstance(valeur, (list, tuple, set)):
        brut = list(valeur)
    else:
        return []

    vus, sortie = set(), []
    for t in brut:
        t = str(t).strip()
        if not t:
            continue
        cle = t.lower()
        if cle in vus:
            continue
        vus.add(cle)
        sortie.append(t)
    return sortie[:12]      # au-delà l'étiquetage ne classe plus rien


def normaliser_stop(valeur):
    """Recopie la configuration de stop sans la valider.

    La validation appartient à risk_engine.lire_config_stop() : la dupliquer
    ici créerait deux vérités sur la même règle. On se contente de laisser
    passer une forme exploitable et de renvoyer None sinon.
    """
    if valeur in (None, "", {}, []):
        return None
    if isinstance(valeur, str):
        return {"type": valeur.strip().lower()}
    if isinstance(valeur, dict):
        return {k: v for k, v in valeur.items() if v not in (None, "")}
    return None


def normaliser_ligne(ligne: dict, index: int = 0) -> dict:
    """Convertit une ligne saisie dans l'interface vers le format analyseur.

    Deux chemins, décidés par la classe d'actif :
      - classe COTÉE   : ticker obligatoire, quantité et prix de revient > 0
      - classe MANUELLE: aucun ticker, une valeur `value` > 0 suffit

    Toute erreur est levée en ValueError avec le numéro de ligne : c'est ce
    message qui remonte à l'utilisateur dans `erreurs`, il doit donc être
    compréhensible sans lire le code.
    """
    nom = str(ligne.get("name") or ligne.get("nom") or "").strip()
    if not nom:
        raise ValueError(f"Ligne {index + 1} : nom manquant")

    classe = normaliser_classe(ligne.get("asset_class")
                               or ligne.get("classe")
                               or ligne.get("asset_type"))
    fiche_classe = CLASSES_ACTIFS[classe]

    commun = {
        "name":        nom,
        "asset_class": classe,
        "classe_label": fiche_classe["label"],
        "account":     str(ligne.get("account") or ligne.get("compte") or "").strip(),
        "tags":        normaliser_tags(ligne.get("tags") or ligne.get("etiquettes")),
        "stop":        normaliser_stop(ligne.get("stop")),
        "isin":        str(ligne.get("isin", "")).strip(),
    }

    # ── Chemin MANUEL : livret, immobilier, collection, autre ───────────────
    if est_manuel(classe):
        valeur = _nombre(ligne.get("value", ligne.get("valeur",
                          ligne.get("manual_value"))))
        if valeur is None:
            # Tolérance : une ligne manuelle saisie comme une ligne cotée
            # (quantité × prix) reste exploitable.
            q = _nombre(ligne.get("quantity", ligne.get("qty")))
            p = _nombre(ligne.get("buy_price", ligne.get("cost_eur")))
            if q is not None and p is not None:
                valeur = q * p
        if valeur is None or valeur <= 0:
            raise ValueError(f"Ligne {index + 1} ({nom}) : valeur manquante ou nulle "
                             f"(champ 'value' attendu pour un actif "
                             f"{fiche_classe['label'].lower()})")

        # Prix d'acquisition : sans lui, la plus-value latente n'a pas de sens.
        # On retient alors la valeur courante -> plus-value nulle, ce qui est la
        # seule affirmation honnête possible.
        acquisition = _nombre(ligne.get("buy_value", ligne.get("cout",
                              ligne.get("acquisition"))), valeur)
        if acquisition <= 0:
            acquisition = valeur

        return {
            **commun,
            "qty":       1.0,
            "cost_eur":  round(acquisition, 4),
            "valeur_manuelle": round(valeur, 4),
            "marche":    PLACE_MANUELLE,
            "place":     PLACE_MANUELLE,
            "devise":    str(ligne.get("currency") or "EUR").upper(),
            "manuel":    True,
            "asset_type": classe,
            "ticker_fh": None, "ticker_eod": f"MANUEL:{nom}",
            "ticker_td": None, "ticker_av": None, "ticker_yf": None,
        }

    # ── Chemin COTÉ : action, ETF, obligation, crypto, métal ────────────────
    ticker = (ligne.get("ticker") or ligne.get("ticker_eodhd")
              or ligne.get("ticker_finnhub") or ligne.get("symbole") or "")
    ticker = str(ticker).strip()
    if not ticker:
        raise ValueError(f"Ligne {index + 1} ({nom}) : ticker manquant")

    place = detecter_marche(ticker, ligne.get("market") or ligne.get("marche"),
                            asset_class=classe)
    fiche = MARCHES.get(place, MARCHES["us"])

    qty = _nombre(ligne.get("quantity", ligne.get("qty", 0)))
    if qty is None:
        raise ValueError(f"Ligne {index + 1} ({nom}) : quantité invalide")

    cout = _nombre(ligne.get("buy_price", ligne.get("cost_eur", 0)))
    if cout is None:
        raise ValueError(f"Ligne {index + 1} ({nom}) : prix de revient invalide")

    if qty <= 0:
        raise ValueError(f"Ligne {index + 1} ({nom}) : la quantité doit être > 0")
    if cout <= 0:
        raise ValueError(f"Ligne {index + 1} ({nom}) : le prix de revient doit être > 0")

    sortie = {
        **commun,
        "qty":        qty,
        "cost_eur":   cout,
        "marche":     fiche["marche"],
        "place":      place,
        "devise":     str(ligne.get("currency") or fiche["devise"]).upper(),
        "manuel":     False,
        "asset_type": classe,
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


def normaliser_cloture(op: dict, index: int = 0) -> dict:
    """Normalise une opération close (position vendue).

    Une vente peut être libellée dans une autre devise que l'euro. Le taux
    appliqué au moment de l'opération est donc figé dans la ligne : le
    reconstituer plus tard avec un taux du jour donnerait un résultat faux,
    puisque le change fait partie du gain réalisé.
    """
    nom = str(op.get("name") or "").strip()
    if not nom:
        raise ValueError(f"Vente {index + 1} : nom manquant")

    ticker = str(op.get("ticker") or "").strip()
    if not ticker:
        raise ValueError(f"Vente {index + 1} ({nom}) : ticker manquant")

    place = detecter_marche(ticker, op.get("market") or op.get("marche"))
    fiche = MARCHES.get(place, MARCHES["us"])

    try:
        qty   = float(op.get("quantity", op.get("qty", 0)))
        achat = float(op.get("buy_price", op.get("cost_eur", 0)))
        vente = float(op.get("sell_price", 0))
    except (TypeError, ValueError):
        raise ValueError(f"Vente {index + 1} ({nom}) : montant invalide")

    if qty <= 0 or achat <= 0 or vente <= 0:
        raise ValueError(f"Vente {index + 1} ({nom}) : quantité et prix doivent être > 0")

    devise = str(op.get("sell_currency") or fiche["devise"]).upper()
    try:
        taux = float(op.get("fx_at_sale", 1.0))
    except (TypeError, ValueError):
        taux = 1.0
    if devise == "EUR":
        taux = 1.0
    if taux <= 0:
        raise ValueError(f"Vente {index + 1} ({nom}) : taux de change invalide")

    return {
        "name":          nom,
        "ticker":        ticker.upper(),
        "marche":        fiche["marche"],
        "qty":           qty,
        "buy_price_eur": achat,
        "sell_price":    vente,
        "sell_currency": devise,
        "fx_at_sale":    taux,
        "sell_date":     str(op.get("sell_date", "")).strip(),
        "note":          str(op.get("note", "")).strip(),
    }


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

    # Identifiants uniques. Les lignes cotées sont distinguées par leur ticker ;
    # les lignes manuelles n'en ont pas et sont identifiées par leur nom. Deux
    # « Autre » homonymes partageraient alors la même clé et se confondraient
    # dans l'historique et les totaux. On suffixe les doublons.
    vus = {}
    for l in lignes:
        cle = l.get("ticker_eod") or ""
        if cle in vus:
            vus[cle] += 1
            if l.get("manuel"):
                l["ticker_eod"] = f"{cle}#{vus[cle]}"
        else:
            vus[cle] = 1

    code, libelle, frais = resoudre_frais(settings)
    settings["broker"]       = code
    settings["broker_label"] = libelle
    settings["fees"]         = frais
    settings["watchlist"]    = normaliser_watchlist(settings.get("watchlist"))

    # ── Réglages de risque ─────────────────────────────────────────────────
    # Bornés ici plutôt que dans risk_engine : une valeur aberrante saisie dans
    # l'interface doit être corrigée à l'entrée, pas propagée jusqu'au calcul.
    def _borne(cle, defaut, mini, maxi):
        v = _nombre(settings.get(cle), defaut)
        return round(min(max(v, mini), maxi), 4)

    settings["risque_pct"]    = _borne("risque_pct",    1.0,  0.05, 10.0)
    settings["poids_max_pct"] = _borne("poids_max_pct", 15.0, 1.0,  100.0)
    # Volatilité annuelle qu'une ligne sans stop a le droit d'apporter au
    # portefeuille, en % du capital. Volontairement basse : voir
    # risk_engine.dimensionner_par_volatilite().
    settings["vol_cible_pct"] = _borne("vol_cible_pct", 2.0,  0.1,  50.0)

    liq = _nombre(settings.get("liquidites"))
    settings["liquidites"] = round(liq, 2) if liq is not None and liq >= 0 else None

    settings["stop_defaut"] = normaliser_stop(settings.get("stop_defaut"))

    closes, err_closes = [], []
    for i, op in enumerate(raw.get("closed") or []):
        try:
            closes.append(normaliser_cloture(op, i))
        except ValueError as e:
            err_closes.append(str(e))
    erreurs += err_closes

    return {
        "username": str(username or raw.get("username") or "default").strip().lower(),
        "lines":    lignes,
        "closed":   closes,
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
        tck = "--" if l.get("manuel") else str(l.get("ticker_eod") or "--")
        tags = (" #" + " #".join(l["tags"])) if l.get("tags") else ""
        print(f"  {l['name']:<24} {tck:<14} {l['classe_label']:<14} "
              f"{l['marche']:<9} {l['qty']}× {l['cost_eur']} {l['devise']}{tags}")
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
