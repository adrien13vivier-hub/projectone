#!/usr/bin/env python3
"""
learning_engine.py -- La note d'hier avait-elle raison ? Le moteur qui l'apprend.
================================================================================

CE QUE FAIT CE MODULE, ET CE QU'IL NE FAIT PAS
--------------------------------------------------------------------------------
portfolio_analyzer.py sort chaque jour une note sur 10. Ce module ne la
modifie JAMAIS. Il la traite comme une PREVISION HORODATEE :

  1. SNAPSHOT   la note, ses sous-notes, le secteur, les references et la
                version de la formule sont figes le jour t (journal immuable).
  2. ATTENTE    rien n'est conclu avant l'echeance (H seances de bourse).
  3. CLOTURE    a t + H : rendement du titre, du secteur, du marche, et
                SURPERFORMANCE = rendement du titre - rendement de la reference.
  4. STATISTIQUE  par tranche de note, horizon et secteur : moyenne, mediane,
                taux de surperformance, dispersion, intervalle de confiance.
  5. CALIBRATION  ce que « 8/10 » a historiquement produit -> une esperance
                RETRECIE vers la moyenne quand l'echantillon est mince.
  6. MODELE     un Ridge regularise, active SEULEMENT s'il bat la statistique
                simple en validation walk-forward, hors echantillon.

La note reste l'analyse economique. Cette couche mesure sa validite et la
calibre ; elle n'a aucun moyen de la reecrire (voir « garde-fous »).

CE QUI AMELIORE LE CAHIER DES CHARGES INITIAL
--------------------------------------------------------------------------------
* Un snapshot par (titre, seance) ; les horizons sont des SORTIES, pas des
  lignes de stockage. Ajouter un horizon personnalise s'applique aussitot a
  tout le passe, sans re-noter quoi que ce soit.
* Amorcage depuis reports/<user>/history.csv : le moteur est utile des le
  premier jour au lieu d'attendre 60 a 252 seances (cohorte « heritee »,
  signalee comme telle et plafonnee en confiance).
* Fichiers JSONL en ajout seul (predictions + outcomes) : diffs minuscules
  dans git, pas de binaire, deja couverts par « git add reports/ ».
* Intervalles de confiance sur echantillon THINNE (fenetres non chevauchantes
  par titre) : 250 lignes quotidiennes d'un meme titre ne valent pas 250
  observations independantes, et le rapport ne le pretend pas.
* Retrecissement hierarchique (global -> tranche -> secteur) plutot qu'un
  seuil brutal « assez / pas assez ».
* Le ML ne s'active pas parce qu'on l'a decide : il doit gagner sa place
  (walk-forward avec purge/embargo, IC de rang, MSE contre la moyenne).
* Rendements AJUSTES (dividendes + splits) en devise locale : ni effet de
  change, ni serie AlphaVantage non ajustee.
* Un titre disparu de la cote est cloture sur son dernier cours (marque
  « delisted_proxy ») au lieu d'etre oublie : pas de biais de survivance.

MUTUALISATION (v9.1)
--------------------------------------------------------------------------------
La note d'un titre ne depend pas de celui qui le detient : « CoreWeave a 6,8 »
est vrai pour tous les profils. Les profils qui l'acceptent (reglage
`apprentissage.mutualiser`, actif par defaut) alimentent donc UN journal commun,
reports/@pool/learning/, sur lequel tout le monde calibre ses notes.

* Le pool est ANONYME : identifiant = (titre, seance, version de la note), sans
  utilisateur, sans quantite, sans prix de revient, sans compte. Il ne contient
  que ce qui est deja public (cours, note calculee, resultat).
* DEDOUBLONNE : dix profils qui detiennent le meme titre le meme jour n'ajoutent
  qu'UN snapshot. La confiance ne se gonfle pas parce qu'un titre est populaire ;
  c'est la diversite des titres qui apporte de l'information.
* Un profil qui refuse (`mutualiser: false`) garde un journal PRIVE, isole : il
  ne contribue pas au pool et ne l'utilise pas.

ZERO DEPENDANCE : bibliotheque standard uniquement (le workflow n'installe que
requests et matplotlib). Aucun appel reseau ici : les cours arrivent par une
fonction `fetch(symbole, debut, fin)` injectee par l'appelant.
================================================================================
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

MODULE_VERSION = "1.1"

# Identite du pool commun : jamais un vrai utilisateur (les noms commencant par
# « _ » sont d'ailleurs refuses par l'appelant comme contributeurs).
POOL_USER = "_pool"
POOL_DIRNAME = "@pool"   # « @ » : aucun nom d'utilisateur (slug) ne peut l'egaler

# ─────────────────────────────────────────────────────────────────────────────
# REGLAGES
# ─────────────────────────────────────────────────────────────────────────────

# Horizons en SEANCES de bourse (pas en jours calendaires).
STANDARD_HORIZONS = (20, 60, 120, 252)
DEFAULT_HORIZON = 60
HORIZON_MIN, HORIZON_MAX = 5, 504

# Classes d'actifs qui ont un sens face a un indice actions. Une crypto, un
# metal ou une obligation n'ont pas de « secteur » ni d'indice actions honnete.
LEARNABLE_CLASSES = ("action", "etf")

# Tranches de note : memes seuils que recommend() -> le tableau se lit avec
# les libelles ACHAT FORT / ACHAT MODERE / GARDER / A EVITER / VENDRE.
BANDS = (
    (0.0, 3.0, "< 3", "VENDRE"),
    (3.0, 4.5, "3 - 4,5", "A EVITER"),
    (4.5, 6.0, "4,5 - 6", "GARDER"),
    (6.0, 7.5, "6 - 7,5", "ACHAT MODERE"),
    (7.5, 10.01, ">= 7,5", "ACHAT FORT"),
)

SHRINK_MEAN_K = 15        # « poids » de la moyenne globale dans le retrecissement
SHRINK_PROB_K = 10
MIN_BAND_N = 8            # observations INDEPENDANTES mini pour publier une esperance
MIN_CI_N = 8              # ... pour publier un intervalle de confiance
MIN_PROB_N = 30           # ... pour publier une probabilite
MIN_SECTOR_N = 12         # ... pour utiliser une cohorte sectorielle
LEGACY_MIN_N = 30         # sous ce seuil (version courante), on ajoute la cohorte heritee

CAL_DAYS_PER_SESSION = 1.4     # jours calendaires par seance (borne basse ~1,4)
BENCH_GAP_DAYS = 5             # ecart tolere entre une date et un cours de reference
STALE_DAYS = 45                # serie arretee depuis plus de N jours -> titre disparu
BENCH_GRACE_DAYS = 30          # attente d'une reference indisponible avant de s'en passer

# ML : conditionnel, jamais force.
ML_FEATURES = ("score", "valorisation", "sante", "croissance",
               "momentum", "consensus", "risque")
ML_MIN_OBS = 250
ML_MIN_DATES = 60
ML_MIN_FOLDS = 3
ML_MIN_IC = 0.05
ML_MAX_MSE_RATIO = 0.98
ML_LAMBDA = 30.0
ML_RETRAIN_EVERY_N = 25

# ── Secteurs -> ETF de reference ────────────────────────────────────────────
# Classification GICS pour l'US comme pour l'Europe (et non un melange GICS/ICB) :
# les intitules ci-dessous sont les noms GICS stricts, ceux que portent aussi
# bien les ETF sectoriels US (SPDR Select Sector) que la gamme iShares MSCI
# Europe Sector UCITS ETF -- comparer un secteur GICS a un secteur GICS, jamais
# a un supersecteur ICB (le STOXX Europe 600 en compte 20, pas 11).
SECTOR_ALIASES = {
    "technology": "Information Technology", "tech": "Information Technology",
    "information technology": "Information Technology",
    "semi-conducteurs": "Information Technology",
    "semiconducteurs": "Information Technology", "logiciels": "Information Technology",
    "healthcare": "Health Care", "health care": "Health Care",
    "sante": "Health Care", "santé": "Health Care", "pharma": "Health Care",
    "financial services": "Financials", "financials": "Financials",
    "financial": "Financials", "finance": "Financials", "banques": "Financials",
    "banque": "Financials",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples", "consumer staples": "Consumer Staples",
    "industrials": "Industrials", "industrie": "Industrials",
    "energy": "Energy", "energie": "Energy", "énergie": "Energy",
    "basic materials": "Materials", "materials": "Materials",
    "utilities": "Utilities", "services publics": "Utilities",
    "real estate": "Real Estate", "immobilier": "Real Estate",
    "communication services": "Communication Services",
    "communications": "Communication Services",
}

# ── Regions ──────────────────────────────────────────────────────────────────
# Limite aux places que le portefeuille propose reellement (api/load_portfolio
# .MARCHES) : inutile d'anticiper des places qu'aucun utilisateur ne peut
# selectionner. US et EUROPE sont les seules regions "outillees" (references
# sectorielles connues) ; tout le reste (crypto, place non reconnue) reste
# UNKNOWN et n'a droit qu'a la reference marche par defaut, jamais a un secteur
# invente.
US_PLACES = frozenset({"US"})
EUROPEAN_PLACES = frozenset({"PA", "AS", "BR", "LS", "MI", "XETRA", "MC", "LSE", "SW"})


def region_of(place: str) -> str:
    """Region d'apprentissage d'une place de cotation (suffixe EODHD)."""
    p = str(place or "").upper()
    if p in US_PLACES:
        return "US"
    if p in EUROPEAN_PLACES:
        return "EUROPE"
    return "UNKNOWN"


# ── References ──────────────────────────────────────────────────────────────
# Chaque reference porte sa propre devise : c'est ce qui permet de detecter
# (et de corriger, cf. compute_outcome) une comparaison entre deux devises
# differentes -- le piege releve pour une action britannique (GBP) jugee
# contre un ETF sectoriel europeen libelle en EUR.
#
# market_refs reste indexe par PLACE (suffixe EODHD) : un indice national reste
# la meilleure reference de "marche local" pour une place qui en a un vrai
# (France, Allemagne, Royaume-Uni, Suisse). Les places europeennes plus etroites
# (Amsterdam, Bruxelles, Lisbonne, Milan, Madrid) n'ont PLUS un CAC 40 invente
# comme reference (bogue signale : « le simple fallback sur le CAC 40 n'est pas
# suffisant », et il etait meme faux pour ces places-la, qui ne sont pas
# francaises) -- elles pointent vers un proxy pan-europeen reel, le STOXX
# Europe 600 (iShares STOXX Europe 600 UCITS ETF (DE), EXSA, ISIN DE0002635307,
# coefficient de couverture ~90% du marche investissable europeen).
#
# sector_refs est desormais indexe par REGION (US / EUROPE), pas par place : le
# secteur Financials europeen est le meme ETF quel que soit le pays de cotation
# du titre -- le dupliquer par place aurait ete une invitation a l'incoherence.
# Familles utilisees : SPDR Select Sector (US, USD) et iShares MSCI Europe
# Sector UCITS ETF (Europe, EUR) -- toutes deux classees GICS.
#
# IMPORTANT -- non verifie en direct : ce module n'a aucun acces reseau (voir
# l'entete du fichier) et n'a donc pas pu interroger l'EODHD Search API pour
# confirmer ces codes sur LE COMPTE EODHD de Gaby (couverture par abonnement
# variable). Les tickers ci-dessous sont corrobores par plusieurs sources
# publiques independantes (ishares.com, justetf.com, Yahoo Finance) au moment
# de la redaction, avec le suffixe ".XETRA" deja utilise ailleurs dans ce
# depot pour les instruments cotes a Francfort -- mais PAS verifies contre
# l'EODHD Search API elle-meme. A verifier une bonne fois avant mise en
# production (voir README / note de livraison) ; en attendant, un symbole
# invalide echoue proprement (voir `mature()`) sans jamais fabriquer de valeur.
# Quatre secteurs GICS n'ont pas de correspondance confirmee a ce jour
# (Materials, Utilities, Real Estate, Communication Services) : laisses
# absents plutot que devines -- la hierarchie de repli (secteur -> marche
# pan-europeen -> rien) s'applique proprement dans ce cas, exactement comme
# pour un secteur inconnu.
DEFAULT_CONFIG = {
    "market_refs": {
        "US":     {"symbol": "SPY.US",     "devise": "USD"},
        "PA":     {"symbol": "FCHI.INDX",  "devise": "EUR"},
        "XETRA":  {"symbol": "GDAXI.INDX", "devise": "EUR"},
        "LSE":    {"symbol": "FTSE.INDX",  "devise": "GBP"},
        "SW":     {"symbol": "SSMI.INDX",  "devise": "CHF"},
        # Places europeennes sans indice national distinct utilise ici :
        # proxy pan-europeen plutot qu'un indice etranger invente.
        "AS":     {"symbol": "EXSA.XETRA", "devise": "EUR"},
        "BR":     {"symbol": "EXSA.XETRA", "devise": "EUR"},
        "LS":     {"symbol": "EXSA.XETRA", "devise": "EUR"},
        "MI":     {"symbol": "EXSA.XETRA", "devise": "EUR"},
        "MC":     {"symbol": "EXSA.XETRA", "devise": "EUR"},
        "default": {"symbol": "SPY.US", "devise": "USD"},
    },
    "sector_refs": {
        "US": {
            "Information Technology": {"symbol": "XLK.US", "devise": "USD"},
            "Health Care":            {"symbol": "XLV.US", "devise": "USD"},
            "Financials":             {"symbol": "XLF.US", "devise": "USD"},
            "Consumer Discretionary": {"symbol": "XLY.US", "devise": "USD"},
            "Consumer Staples":       {"symbol": "XLP.US", "devise": "USD"},
            "Industrials":            {"symbol": "XLI.US", "devise": "USD"},
            "Energy":                 {"symbol": "XLE.US", "devise": "USD"},
            "Materials":              {"symbol": "XLB.US", "devise": "USD"},
            "Utilities":              {"symbol": "XLU.US", "devise": "USD"},
            "Real Estate":            {"symbol": "XLRE.US", "devise": "USD"},
            "Communication Services": {"symbol": "XLC.US", "devise": "USD"},
        },
        "EUROPE": {
            # iShares MSCI Europe *** Sector UCITS ETF, ligne Xetra (EUR).
            "Information Technology": {"symbol": "ESIT.XETRA", "devise": "EUR"},
            "Health Care":            {"symbol": "ESIH.XETRA", "devise": "EUR"},
            "Financials":             {"symbol": "ESIF.XETRA", "devise": "EUR"},
            "Consumer Discretionary": {"symbol": "ESIC.XETRA", "devise": "EUR"},
            "Consumer Staples":       {"symbol": "ESIS.XETRA", "devise": "EUR"},
            "Industrials":            {"symbol": "ESIN.XETRA", "devise": "EUR"},
            "Energy":                 {"symbol": "ESIE.XETRA", "devise": "EUR"},
            # Materials / Utilities / Real Estate / Communication Services :
            # pas de ticker confirme -- absents intentionnellement (voir note
            # ci-dessus), repli automatique sur le marche pan-europeen.
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# OUTILS DE BASE
# ─────────────────────────────────────────────────────────────────────────────

def _d(valeur) -> date:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()


def _iso(d) -> str:
    return _d(d).strftime("%Y-%m-%d")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _r(v, n=4):
    return None if v is None else round(v, n)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def median(xs):
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def stdev(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _tcrit(df: int) -> float:
    """Quantile bilateral 95 % de Student (developpement de Cornish-Fisher)."""
    if df <= 0:
        return float("inf")
    z = 1.959964
    return (z + (z ** 3 + z) / (4 * df)
            + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2))


def mean_ci95(xs):
    """(bas, haut) de l'intervalle de confiance a 95 % de la moyenne, ou None."""
    n = len(xs)
    if n < MIN_CI_N:
        return None
    m, s = mean(xs), stdev(xs)
    if s is None:
        return None
    marge = _tcrit(n - 1) * s / math.sqrt(n)
    return (m - marge, m + marge)


def _ranks(v):
    idx = sorted(range(len(v)), key=lambda i: v[i])
    rang = [0.0] * len(v)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[idx[j + 1]] == v[idx[i]]:
            j += 1
        moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rang[idx[k]] = moyen
        i = j + 1
    return rang


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def spearman(xs, ys):
    """Correlation de rang (IC, « information coefficient »)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return pearson(_ranks(xs), _ranks(ys))


def ols_slope(xs, ys):
    """Pente de la droite des moindres carres, avec son erreur-type."""
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    se = math.sqrt(res / (n - 2) / sxx) if n > 2 else None
    return {"pente": b, "ordonnee": a, "se": se,
            "t": (b / se) if se else None, "n": n}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & SECTEURS
# ─────────────────────────────────────────────────────────────────────────────

def _ref_entry(v):
    """Normalise une entree de reference fournie par l'utilisateur : soit
    {"symbol": "...", "devise": "..."}, soit une simple chaine -- acceptee
    pour rester simple a ecrire a la main, mais alors SANS devise connue,
    ce qui desactive le controle de change pour cette seule reference plutot
    que de deviner une devise fausse."""
    if isinstance(v, dict) and v.get("symbol"):
        return {"symbol": str(v["symbol"]),
                "devise": str(v["devise"]).upper() if v.get("devise") else None}
    if isinstance(v, str) and v:
        return {"symbol": v, "devise": None}
    return None


def load_config(path: str = "data/learning_config.json") -> dict:
    """Configuration par defaut, completee par data/learning_config.json.

    Le fichier ne PEUT PAS casser le moteur : illisible ou mal forme, il est
    ignore et les valeurs par defaut s'appliquent. `market_refs` reste
    indexe par PLACE (suffixe EODHD) ; `sector_refs` par REGION (US /
    EUROPE) -- voir DEFAULT_CONFIG plus haut pour la justification. Chaque
    reference se declare {"symbol": "...", "devise": "..."} (voir
    _ref_entry).
    """
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
    except (OSError, ValueError):
        return cfg
    if not isinstance(user, dict):
        return cfg
    if isinstance(user.get("market_refs"), dict):
        for place, v in user["market_refs"].items():
            entry = _ref_entry(v)
            if entry:
                cfg["market_refs"][str(place).upper()] = entry
    if isinstance(user.get("sector_refs"), dict):
        for region, table in user["sector_refs"].items():
            if isinstance(table, dict):
                dest = cfg["sector_refs"].setdefault(str(region).upper(), {})
                for sect, v in table.items():
                    entry = _ref_entry(v)
                    if entry:
                        dest[str(sect)] = entry
    return cfg


def normalize_settings(raw) -> dict:
    """Reglages `settings.apprentissage` d'un profil, bornes a l'entree."""
    raw = raw if isinstance(raw, dict) else {}
    horizons = set(STANDARD_HORIZONS)
    for h in (raw.get("horizons") or []):
        n = _num(h)
        if n is not None and HORIZON_MIN <= int(n) <= HORIZON_MAX:
            horizons.add(int(n))
    principal = _num(raw.get("horizon"))
    principal = int(principal) if principal and HORIZON_MIN <= principal <= HORIZON_MAX \
        else DEFAULT_HORIZON
    horizons.add(principal)
    classes = tuple(c for c in (raw.get("classes") or LEARNABLE_CLASSES)
                    if isinstance(c, str)) or LEARNABLE_CLASSES
    return {
        "actif": raw.get("actif", True) is not False,
        "mutualiser": raw.get("mutualiser", True) is not False,
        "horizon": principal,
        "horizons": sorted(horizons),
        "classes": classes,
    }


def normalize_sector(brut) -> str:
    txt = str(brut or "").strip()
    if not txt:
        return ""
    return SECTOR_ALIASES.get(txt.lower(), txt)


def place_suffix(symbol: str) -> str:
    """'ACA.PA' -> 'PA', 'CRWV.US' -> 'US', 'GSPC.INDX' -> 'INDX'."""
    return symbol.rsplit(".", 1)[1].upper() if "." in (symbol or "") else ""


# Devise de cotation par defaut d'une place -- utilisee seulement quand
# l'appelant ne connait pas deja la devise reelle de la position (ex : un
# titre de watchlist sans position associee). Une devise explicite fournie a
# build_snapshot() prime toujours sur cette table.
_PLACE_DEVISE = {
    "US": "USD", "PA": "EUR", "XETRA": "EUR", "AS": "EUR", "BR": "EUR",
    "LS": "EUR", "MI": "EUR", "MC": "EUR", "LSE": "GBP", "SW": "CHF",
}


def native_devise(symbol: str):
    """Devise de cotation par defaut de la place d'un symbole, ou None si la
    place n'est pas reconnue (crypto, indice...)."""
    return _PLACE_DEVISE.get(place_suffix(symbol))


def resolve_refs(symbol: str, sector: str, config: dict) -> dict:
    """References de calibration d'un titre, avec leur devise.

    Renvoie un dict {"region", "sector_ref", "sector_ref_devise",
    "market_ref", "market_ref_devise"}. Le secteur se cherche par REGION
    (US / EUROPE) : le meme ETF sectoriel sert toute la zone couverte, alors
    que le marche reste cherche par PLACE (un indice national reste la
    meilleure reference locale quand il en existe un). Porter la devise de
    chaque reference est ce qui permet a compute_outcome(), via mature(), de
    comparer deux rendements exprimes dans la MEME devise plutot que deux
    pourcentages qui ne veulent rien dire cote a cote (ex : un titre en GBP
    face a un ETF sectoriel europeen libelle en EUR)."""
    place = place_suffix(symbol)
    region = region_of(place)
    m = config["market_refs"].get(place) or config["market_refs"].get("default") or {}
    s = (config["sector_refs"].get(region) or {}).get(normalize_sector(sector)) or {}
    return {
        "region": region,
        "sector_ref": s.get("symbol"),
        "sector_ref_devise": s.get("devise"),
        "market_ref": m.get("symbol"),
        "market_ref_devise": m.get("devise"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# STOCKAGE : JSONL EN AJOUT SEUL
# ─────────────────────────────────────────────────────────────────────────────

def learning_dir(user: str, base: str = "reports") -> str:
    return os.path.join(base, user, "learning")


def pool_dir(base: str = "reports") -> str:
    """Dossier du journal commun (tous profils confondus, anonyme)."""
    return os.path.join(base, POOL_DIRNAME, "learning")


def _paths(ldir: str) -> dict:
    return {
        "predictions": os.path.join(ldir, "predictions.jsonl"),
        "outcomes": os.path.join(ldir, "outcomes.jsonl"),
        "summary": os.path.join(ldir, "summary.json"),
        "backfill": os.path.join(ldir, "backfill.done"),
        "registry": os.path.join(ldir, "model_registry"),
    }


def read_jsonl(path: str) -> tuple:
    """(lignes, nombre de lignes illisibles). Une ligne corrompue est ignoree,
    jamais fatale : un journal partiellement ecrit ne doit pas tuer le rapport."""
    rows, bad = [], 0
    try:
        with open(path, encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    obj = json.loads(ligne)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    bad += 1
    except OSError:
        pass
    return rows, bad


def append_jsonl(path: str, rows: list) -> int:
    if not rows:
        return 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n")
    return len(rows)


def prediction_id(user: str, ticker: str, as_of, score_version: str) -> str:
    brut = f"{user}|{ticker}|{_iso(as_of)}|{score_version}"
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:16]


def load_store(ldir: str) -> dict:
    p = _paths(ldir)
    snaps, bad_s = read_jsonl(p["predictions"])
    outs, bad_o = read_jsonl(p["outcomes"])
    # Premier arrive, premier servi : un doublon ne peut pas reecrire l'histoire.
    vus, uniques = set(), []
    for s in snaps:
        if s.get("id") and s["id"] not in vus:
            vus.add(s["id"])
            uniques.append(s)
    cles, outs_u = set(), []
    for o in outs:
        k = (o.get("id"), o.get("horizon"))
        if k not in cles:
            cles.add(k)
            outs_u.append(o)
    return {"snapshots": uniques, "outcomes": outs_u, "corrompus": bad_s + bad_o}


# ─────────────────────────────────────────────────────────────────────────────
# 1. SNAPSHOTS
# ─────────────────────────────────────────────────────────────────────────────

def build_snapshot(user, symbol, name, as_of, score, confidence, subscores,
                   score_version, asset_class, sector, industry, config,
                   price=None, source="live", devise=None) -> dict:
    """`devise` : devise de cotation REELLE du titre si l'appelant la connait
    deja (ex : celle de la position dans le portefeuille -- deja normalisee
    GBP, pas GBp, comme le reste du programme). A defaut, on retombe sur la
    devise habituelle de la place de cotation (native_devise) plutot que de
    laisser le controle de change desactive en silence."""
    sector = normalize_sector(sector)
    refs = resolve_refs(symbol, sector, config)
    devise = str(devise).upper() if devise else native_devise(symbol)
    return {
        "id": prediction_id(user, symbol, as_of, score_version),
        "user": user,
        "ticker": symbol,
        "symbol": symbol,
        "name": name,
        "as_of": _iso(as_of),
        "score": round(float(score), 2),
        "confiance": _num(confidence),
        "subscores": {k: round(float(v), 2) for k, v in (subscores or {}).items()
                      if _num(v) is not None},
        "score_version": score_version,
        "asset_class": asset_class,
        "sector": sector,
        "industry": str(industry or ""),
        "region": refs["region"],
        "devise": devise,
        "sector_ref": refs["sector_ref"],
        "sector_ref_devise": refs["sector_ref_devise"],
        "market_ref": refs["market_ref"],
        "market_ref_devise": refs["market_ref_devise"],
        "price": _r(_num(price), 4),
        "source": source,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def record_snapshots(ldir: str, snapshots: list) -> dict:
    """Ajoute les snapshots NOUVEAUX ; ceux qui existent deja sont ignores.

    Immuabilite : (utilisateur, titre, seance, version) identifie un snapshot.
    Relancer l'analyse le meme soir ne cree rien et ne modifie rien.
    """
    existants = {s["id"] for s in load_store(ldir)["snapshots"]}
    nouveaux, vus = [], set(existants)
    for s in snapshots:
        if s["id"] in vus:
            continue
        vus.add(s["id"])
        nouveaux.append(s)
    append_jsonl(_paths(ldir)["predictions"], nouveaux)
    return {"nouveaux": len(nouveaux), "ignores": len(snapshots) - len(nouveaux)}


def backfill_from_history_csv(history_path: str, user: str, config: dict,
                              sectors: dict = None, legacy_version: str = "legacy",
                              before=None) -> list:
    """Snapshots reconstruits depuis history.csv (score publie + cours du jour).

    * Une ligne par (titre, seance) : la DERNIERE du jour (analyse de cloture).
    * Version « legacy » : la formule a change au fil des versions et l'export
      ne dit pas laquelle. Ces snapshots forment une cohorte a part.
    * Aucune fuite : la note est celle publiee ce jour-la, le cours celui du
      jour. Seul le SECTEUR est l'attribut actuel du titre (quasi stable).
    * `before` : seances >= cette date ignorees (elles sont deja des snapshots
      vivants ; les reconstituer les compterait deux fois).
    """
    sectors = sectors or {}
    try:
        with open(history_path, newline="", encoding="utf-8") as f:
            lignes = list(csv.DictReader(f))
    except OSError:
        return []
    par_jour = {}
    for l in lignes:
        tk = (l.get("ticker") or "").strip()
        sc = _num(l.get("score"))
        if "." not in tk or sc is None:      # anciens exports sans suffixe de place
            continue
        try:
            jour = _iso(l.get("date"))
        except ValueError:
            continue
        if before is not None and jour >= _iso(before):
            continue                         # les seances vivantes ne sont pas reconstituees
        par_jour[(tk, jour)] = l             # la derniere ligne du jour l'emporte
    snaps = []
    for (tk, jour), l in sorted(par_jour.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        info = sectors.get(tk) or {}
        snaps.append(build_snapshot(
            user, tk, l.get("name") or tk, jour, _num(l.get("score")),
            _num(l.get("confiance")), {}, legacy_version, "action",
            info.get("sector", ""), info.get("industry", ""), config,
            price=_num(l.get("price_eur")), source="backfill_history_csv"))
    return snaps


# ─────────────────────────────────────────────────────────────────────────────
# 2-3. MATURATION : cours ajustes, echeance en seances, references
# ─────────────────────────────────────────────────────────────────────────────

class CachedFetcher:
    """Enveloppe une fonction `raw(symbole, debut, fin) -> (dates, closes) | None`
    et ne rappelle jamais deux fois le meme symbole dans un run.

    Contrat de `raw` : None = echec transitoire (quota, reseau) ; ([], []) =
    reponse vide ; sinon deux listes triees par date croissante, en cours
    AJUSTES et en devise locale.
    """

    def __init__(self, raw):
        self.raw = raw
        self.cache = {}      # symbole -> (debut_demande, resultat)
        self.appels = 0

    def __call__(self, symbol, debut, fin):
        deja = self.cache.get(symbol)
        if deja and deja[0] <= debut:
            return deja[1]
        self.appels += 1
        try:
            res = self.raw(symbol, _iso(debut), _iso(fin))
        except Exception:
            res = None
        self.cache[symbol] = (debut, res)
        return res


def session_index(dates: list, as_of, max_gap: int = BENCH_GAP_DAYS):
    """Indice de la derniere seance <= as_of, a moins de `max_gap` jours."""
    cible = _iso(as_of)
    lo, hi, res = 0, len(dates) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] <= cible:
            res, lo = mid, mid + 1
        else:
            hi = mid - 1
    if res is None:
        return None
    if (_d(cible) - _d(dates[res])).days > max_gap:
        return None
    return res


def value_on_or_before(dates: list, closes: list, jour, max_gap: int = BENCH_GAP_DAYS):
    i = session_index(dates, jour, max_gap)
    return closes[i] if i is not None else None


def bench_return_pct(serie, d0, d1):
    """Rendement d'une reference entre deux dates, ou None."""
    if not serie or not serie[0]:
        return None
    dates, closes = serie
    a = value_on_or_before(dates, closes, d0)
    b = value_on_or_before(dates, closes, d1)
    if not a or not b or a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _min_maturity_date(as_of, horizon: int) -> date:
    """Date avant laquelle H seances ne PEUVENT pas etre ecoulees (borne sure :
    une place ouvre au plus 5 jours sur 7, soit >= 1,4 jour calendaire/seance)."""
    return _d(as_of) + timedelta(days=int(math.ceil(horizon * 1.35)))


def compute_outcome(snap: dict, horizon: int, stock, sector_series, market_series,
                    today) -> dict | None:
    """Cloture UNE observation, ou None si elle reste ouverte (« pending »).

    ANTI-FUITE : seules les seances jusqu'a t + H sont lues. Le cours d'apres
    l'echeance n'entre jamais dans le calcul.
    """
    today = _d(today)
    if not stock or not stock[0]:
        return None
    dates, closes = stock
    i = session_index(dates, snap["as_of"])
    if i is None:
        return None                               # pas (encore) de cours a t
    j = i + horizon
    delisted = False
    if j >= len(dates):
        derniere = _d(dates[-1])
        attendu = _d(snap["as_of"]) + timedelta(days=int(horizon * CAL_DAYS_PER_SESSION))
        if (today - derniere).days > STALE_DAYS and (today - attendu).days > STALE_DAYS \
                and len(dates) - 1 > i:
            j, delisted = len(dates) - 1, True    # titre disparu : dernier cours
        else:
            return None                           # l'echeance n'est pas atteinte
    p0, p1 = closes[i], closes[j]
    if not p0 or p0 <= 0 or not p1 or p1 <= 0:
        return {"id": snap["id"], "horizon": horizon, "status": "invalid",
                "reason": "prix_nul", "as_of": snap["as_of"],
                "computed_at": _iso(today)}
    d0, d1 = dates[i], dates[j]
    stock_ret = (p1 / p0 - 1.0) * 100.0

    attendu_sect = bool(snap.get("sector_ref"))
    attendu_marche = bool(snap.get("market_ref"))
    r_sect = bench_return_pct(sector_series, d0, d1) if attendu_sect else None
    r_marche = bench_return_pct(market_series, d0, d1) if attendu_marche else None

    # Une reference ATTENDUE mais indisponible (quota, panne) ne fige pas une
    # observation degradee : on attend, puis on s'en passe apres le delai.
    en_retard = (today - _d(d1)).days >= BENCH_GRACE_DAYS
    if not en_retard and ((attendu_sect and r_sect is None)
                          or (attendu_marche and r_marche is None)):
        return None

    return {
        "id": snap["id"], "horizon": horizon, "status": "matured",
        "as_of": snap["as_of"], "session_t": d0, "session_t_h": d1,
        "stock_return_pct": _r(stock_ret),
        "sector_return_pct": _r(r_sect),
        "market_return_pct": _r(r_marche),
        "sector_excess_pct": _r(stock_ret - r_sect) if r_sect is not None else None,
        "market_excess_pct": _r(stock_ret - r_marche) if r_marche is not None else None,
        "sector_ref": snap.get("sector_ref"), "market_ref": snap.get("market_ref"),
        "delisted_proxy": delisted,
        "computed_at": _iso(today),
    }


def mature(ldir: str, horizons, fetch, today) -> dict:
    """Cloture toutes les observations arrivees a echeance. Retourne un bilan.

    `fetch` = CachedFetcher (ou toute fonction (symbole, debut, fin) -> serie).
    Un seul appel par symbole, sur la plage necessaire, quel que soit le
    nombre d'observations a cloturer : cout reseau independant de l'historique.
    """
    today = _d(today)
    store = load_store(ldir)
    faits = {(o["id"], o["horizon"]) for o in store["outcomes"]}
    ouverts = []
    for s in store["snapshots"]:
        for h in horizons:
            if (s["id"], h) in faits:
                continue
            if _min_maturity_date(s["as_of"], h) <= today:
                ouverts.append((s, h))
    bilan = {"candidats": len(ouverts), "clotures": 0, "invalides": 0,
             "en_attente": 0, "appels": 0}
    if not ouverts:
        return bilan

    debut = min(_d(s["as_of"]) for s, _ in ouverts) - timedelta(days=12)
    series, echecs, convertis = {}, set(), {}

    def serie(symbole):
        if not symbole:
            return None
        if symbole not in series:
            res = fetch(symbole, debut, today)
            if res is None:
                echecs.add(symbole)
            series[symbole] = res
        return series[symbole]

    def fx_to_eur(devise, jour):
        """Taux devise -> EUR a une date (1.0 si deja EUR). Reutilise le
        symbole FOREX deja etabli ailleurs dans le programme
        (`f"{devise}EUR.FOREX"`, cf. get_fx() dans portfolio_analyzer.py) :
        le `fetch` fourni a mature() doit donc savoir resoudre ces symboles
        comme n'importe quel autre (memes credentials EODHD)."""
        d = str(devise or "").upper()
        if not d or d == "EUR":
            return 1.0
        s = serie(f"{d}EUR.FOREX")
        if not s or not s[0]:
            return None
        return value_on_or_before(s[0], s[1], jour)

    def serie_en_devise(symbole, devise_native, devise_cible):
        """Serie d'un symbole convertie dans `devise_cible`, si sa devise
        native differe. Change-sur : un rendement stock/reference ne se
        compare qu'entre deux series exprimees dans la MEME devise (sinon la
        seule variation du taux de change entre t et t+H fausse l'ecart
        mesure). Sans devise connue des deux cotes, la serie est renvoyee
        telle quelle (comportement historique, inchange). Un taux manquant
        renvoie None sur ce point plutot qu'une valeur inventee -- c'est
        `compute_outcome` qui decidera d'attendre ou d'abandonner la
        reference, exactement comme pour une serie indisponible."""
        base = serie(symbole)
        if not base or not base[0] or not devise_native or not devise_cible \
                or devise_native == devise_cible:
            return base
        cle = (symbole, devise_cible)
        if cle in convertis:
            return convertis[cle]
        dates, closes = base
        out = []
        for d, c in zip(dates, closes):
            f_from = fx_to_eur(devise_native, d)
            f_to = fx_to_eur(devise_cible, d)
            if c is None or f_from is None or f_to in (None, 0):
                out.append(None)
            else:
                out.append(c * f_from / f_to)
        res = (dates, out) if any(v is not None for v in out) else None
        convertis[cle] = res
        return res

    nouveaux = []
    for s, h in ouverts:
        devise_titre = s.get("devise")
        res = compute_outcome(
            s, h, serie(s["symbol"]),
            serie_en_devise(s.get("sector_ref"), s.get("sector_ref_devise"), devise_titre),
            serie_en_devise(s.get("market_ref"), s.get("market_ref_devise"), devise_titre),
            today)
        if res is None:
            bilan["en_attente"] += 1
            continue
        nouveaux.append(res)
        bilan["invalides" if res["status"] == "invalid" else "clotures"] += 1
    append_jsonl(_paths(ldir)["outcomes"], nouveaux)
    bilan["appels"] = getattr(fetch, "appels", len(series))
    bilan["symboles_en_echec"] = sorted(echecs)
    return bilan


# ─────────────────────────────────────────────────────────────────────────────
# 4-5. STATISTIQUES ET CALIBRATION
# ─────────────────────────────────────────────────────────────────────────────

def band_of(score: float) -> int:
    for i, (lo, hi, _, _) in enumerate(BANDS):
        if lo <= score < hi:
            return i
    return len(BANDS) - 1


def build_observations(store: dict) -> list:
    """Jointure snapshot x resultat cloture (une ligne par snapshot et horizon)."""
    snaps = {s["id"]: s for s in store["snapshots"]}
    obs = []
    for o in store["outcomes"]:
        if o.get("status") != "matured":
            continue
        s = snaps.get(o["id"])
        if not s:
            continue
        obs.append({
            "id": o["id"], "horizon": o["horizon"], "ticker": s["ticker"],
            "as_of": s["as_of"], "target_date": o["session_t_h"],
            "score": s["score"], "subscores": s.get("subscores") or {},
            "version": s["score_version"], "sector": s.get("sector") or "",
            "region": s.get("region") or "UNKNOWN",
            "raw": o["stock_return_pct"],
            "sector_y": o.get("sector_excess_pct"),
            "market_y": o.get("market_excess_pct"),
            "delisted": bool(o.get("delisted_proxy")),
        })
    return obs


KINDS = (("sector", "sector_y", "surperformance sectorielle"),
         ("market", "market_y", "surperformance vs marche"),
         ("raw", "raw", "rendement brut"))


def thin(obs: list, horizon: int) -> list:
    """Observations NON chevauchantes : par titre, au moins H seances d'ecart.

    Deux lignes quotidiennes d'un meme titre partagent presque toute leur
    fenetre future : les compter deux fois gonfle artificiellement la
    confiance. Les estimations ponctuelles utilisent tout, les intervalles et
    les seuils de publication utilisent ce sous-ensemble.
    """
    pas = timedelta(days=int(math.ceil(horizon * CAL_DAYS_PER_SESSION)))
    garde, dernier = [], {}
    for o in sorted(obs, key=lambda o: (o["ticker"], o["as_of"])):
        d = _d(o["as_of"])
        prec = dernier.get(o["ticker"])
        if prec is None or d - prec >= pas:
            garde.append(o)
            dernier[o["ticker"]] = d
    return garde


def confidence_level(n_indep: int, n_tickers: int, legacy: bool = False) -> str:
    if n_indep >= 60 and n_tickers >= 15:
        niveau = "elevee"
    elif n_indep >= 30 and n_tickers >= 8:
        niveau = "moyenne"
    elif n_indep >= MIN_BAND_N:
        niveau = "faible"
    else:
        return "insuffisante"
    return "faible" if legacy and niveau != "insuffisante" else niveau


def _describe(vals: list, vals_indep: list) -> dict:
    ci = mean_ci95(vals_indep)
    return {
        "n": len(vals), "n_indep": len(vals_indep),
        "mean": _r(mean(vals)), "median": _r(median(vals)),
        "std": _r(stdev(vals)),
        "hit": _r(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else None,
        "hit_indep": _r(sum(1 for v in vals_indep if v > 0) / len(vals_indep), 4)
        if vals_indep else None,
        "ci95": [_r(ci[0]), _r(ci[1])] if ci else None,
    }


def select_cohort(obs: list, current_version: str, horizon: int) -> tuple:
    """(observations, heritee ?) : version courante ; si l'echantillon
    independant est trop mince, on y ajoute la cohorte heritee -- et on le dit."""
    de_h = [o for o in obs if o["horizon"] == horizon]
    courante = [o for o in de_h if o["version"] == current_version]
    if len(thin(courante, horizon)) >= LEGACY_MIN_N:
        return courante, False
    if any(o["version"] != current_version for o in de_h):
        return de_h, True
    return courante, False


def horizon_stats(obs: list, horizon: int, kind: str, key: str,
                  current_version: str) -> dict | None:
    cohorte, legacy = select_cohort(obs, current_version, horizon)
    cohorte = [o for o in cohorte if o.get(key) is not None]
    if not cohorte:
        return None
    ind = thin(cohorte, horizon)
    ys = [o[key] for o in cohorte]
    ys_i = [o[key] for o in ind]
    n_tk = len({o["ticker"] for o in ind})
    glob = _describe(ys, ys_i)
    mu0 = mean(ys_i) if ys_i else mean(ys)
    p0 = (sum(1 for v in ys_i if v > 0) / len(ys_i)) if ys_i else 0.5

    bands = []
    for bi, (lo, hi, label, reco) in enumerate(BANDS):
        b_all = [o for o in cohorte if band_of(o["score"]) == bi]
        b_ind = thin(b_all, horizon)      # independance jugee DANS la tranche
        d = _describe([o[key] for o in b_all], [o[key] for o in b_ind])
        n_i = d["n_indep"]
        est = p_est = None
        if b_all and n_i >= MIN_BAND_N:
            est = (n_i * d["mean"] + SHRINK_MEAN_K * mu0) / (n_i + SHRINK_MEAN_K)
        if n_i >= MIN_PROB_N:
            p_est = (d["hit_indep"] * n_i + SHRINK_PROB_K * p0) / (n_i + SHRINK_PROB_K)
        bands.append({
            "label": label, "reco": reco, "lo": lo, "hi": min(hi, 10.0), **d,
            "estimate": _r(est), "p_outperf": _r(p_est, 3),
            "confidence": confidence_level(n_i, len({o["ticker"] for o in b_ind}), legacy),
        })

    sectors = []
    for sec in sorted({o["sector"] for o in cohorte if o["sector"]}):
        s_all = [o for o in cohorte if o["sector"] == sec]
        s_ind = thin(s_all, horizon)
        d = _describe([o[key] for o in s_all], [o[key] for o in s_ind])
        d.update({"sector": sec,
                  "ic": _r(spearman([o["score"] for o in s_all],
                                    [o[key] for o in s_all]), 3)
                  if len(s_all) >= 10 else None})
        sectors.append(d)

    # Ventilation par region, a titre d'INFORMATION (transparence sur le
    # melange US/Europe de l'echantillon) : n'entre pas dans le retrecissement
    # de predict_position, qui reste global -> tranche -> secteur. Une vraie
    # hierarchie region -> secteur demanderait une validation walk-forward
    # dediee avant de peser sur les estimations publiees ; en attendant, ce
    # detail permet au moins de VOIR si un ecart US/Europe existe.
    regions = []
    for reg in sorted({o.get("region") or "UNKNOWN" for o in cohorte}):
        r_all = [o for o in cohorte if (o.get("region") or "UNKNOWN") == reg]
        r_ind = thin(r_all, horizon)
        d = _describe([o[key] for o in r_all], [o[key] for o in r_ind])
        d["region"] = reg
        regions.append(d)

    sl = ols_slope([o["score"] for o in ind], ys_i)
    return {
        "kind": kind, "horizon": horizon, "legacy_included": legacy,
        "n_tickers": n_tk, "n_dates": len({o["as_of"] for o in cohorte}),
        "global": glob,
        "ic": _r(spearman([o["score"] for o in cohorte], ys), 3),
        "ic_indep": _r(spearman([o["score"] for o in ind], ys_i), 3),
        "slope": {k: _r(v, 4) for k, v in sl.items()} if sl else None,
        "bands": bands, "sectors": sectors, "regions": regions,
        "confidence": confidence_level(len(ind), n_tk, legacy),
    }


def headline_kind(per_kind: dict) -> str | None:
    """Cible mise en avant : sectorielle si l'echantillon la permet, sinon marche,
    sinon rendement brut."""
    for kind in ("sector", "market", "raw"):
        st = per_kind.get(kind)
        if st and st["global"]["n_indep"] >= MIN_BAND_N:
            return kind
    # Aucune cible n'atteint le seuil : on met en avant la mieux fournie.
    dispo = [(per_kind[k]["global"]["n_indep"], -i, k)
             for i, k in enumerate(("sector", "market", "raw")) if per_kind.get(k)]
    return max(dispo)[2] if dispo else None


def predict_position(score: float, sector: str, stats: dict, obs: list,
                     key: str, horizon: int, current_version: str) -> dict:
    """Esperance calibree pour une note, retrecie global -> tranche -> secteur."""
    bi = band_of(score)
    b = stats["bands"][bi]
    out = {"band": b["label"], "reco": b["reco"], "estimate": b["estimate"],
           "ci95": b["ci95"], "p_outperf": b["p_outperf"], "n_indep": b["n_indep"],
           "confidence": b["confidence"], "scope": "global",
           "legacy_included": stats["legacy_included"]}
    if b["estimate"] is None:
        out["reason"] = (f"echantillon insuffisant ({b['n_indep']} observation(s) "
                         f"independante(s) dans cette tranche, {MIN_BAND_N} requises)")
        return out
    if sector:
        cohorte, _ = select_cohort(obs, current_version, horizon)
        s_ind = thin([o for o in cohorte if o.get(key) is not None
                      and o["sector"] == sector and band_of(o["score"]) == bi], horizon)
        if len(s_ind) >= MIN_SECTOR_N:
            ms = mean([o[key] for o in s_ind])
            n = len(s_ind)
            out["estimate"] = _r((n * ms + SHRINK_MEAN_K * b["estimate"]) / (n + SHRINK_MEAN_K))
            out["scope"] = f"secteur {sector}"
            out["n_indep"] = n
            out["ci95"] = None
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 6. MODELE : Ridge conditionnel, validation walk-forward
# ─────────────────────────────────────────────────────────────────────────────

def _solve(a: list, b: list) -> list | None:
    """Systeme lineaire a x = b par elimination de Gauss avec pivot partiel."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][k] * x[k] for k in range(i + 1, n))) / m[i][i]
    return x


def _features(o: dict) -> list | None:
    """Vecteur d'entree : UNIQUEMENT ce que le snapshot contenait a la date t."""
    subs = o.get("subscores") or {}
    if not subs:
        return None                          # cohorte heritee : pas de sous-notes
    return [float(o["score"])] + [float(subs.get(k, 5.0)) for k in ML_FEATURES[1:]]


def ridge_fit(X: list, y: list, lam: float = ML_LAMBDA) -> dict | None:
    n, p = len(X), len(X[0]) if X else 0
    if n < p + 2:
        return None
    mu = [mean([r[j] for r in X]) for j in range(p)]
    sd = [stdev([r[j] for r in X]) or 1.0 for j in range(p)]
    sd = [s if s > 1e-9 else 1.0 for s in sd]
    Z = [[(r[j] - mu[j]) / sd[j] for j in range(p)] for r in X]
    ym = mean(y)
    a = [[sum(Z[k][i] * Z[k][j] for k in range(n)) + (lam if i == j else 0.0)
          for j in range(p)] for i in range(p)]
    b = [sum(Z[k][i] * (y[k] - ym) for k in range(n)) for i in range(p)]
    w = _solve(a, b)
    if w is None:
        return None
    return {"coef": w, "intercept": ym, "mu": mu, "sd": sd, "lambda": lam}


def ridge_predict(model: dict, x: list) -> float:
    return model["intercept"] + sum(
        w * (v - m) / s for w, v, m, s in zip(model["coef"], x, model["mu"], model["sd"]))


def _winsor(ys: list, q: float = 0.02) -> list:
    if len(ys) < 20:
        return ys
    s = sorted(ys)
    lo, hi = s[int(q * len(s))], s[min(len(s) - 1, int((1 - q) * len(s)))]
    return [min(max(v, lo), hi) for v in ys]


def walk_forward(obs: list, key: str, horizon: int, min_train: int = 80,
                 min_test: int = 20, n_folds: int = 4) -> dict:
    """Validation chronologique avec PURGE : un exemple d'entrainement n'est
    retenu que si son echeance est ANTERIEURE au debut du bloc de test. Jamais
    de decoupage aleatoire (il fuiterait le futur dans le passe)."""
    data = [(o, _features(o)) for o in obs if o.get(key) is not None]
    data = [(o, x) for o, x in data if x is not None]
    dates = sorted({o["as_of"] for o, _ in data})
    res = {"folds": [], "n": len(data), "n_dates": len(dates)}
    if len(dates) < 8:
        return {**res, "ic_moyen": None, "part_ic_positifs": None, "mse_ratio": None}
    debut = int(len(dates) * 0.4)
    bornes = [dates[debut + k * (len(dates) - debut) // n_folds] for k in range(n_folds)]
    bornes.append("9999-12-31")
    se_m = se_b = 0.0
    for k in range(n_folds):
        t0, t1 = bornes[k], bornes[k + 1]
        train = [(o, x) for o, x in data if o["target_date"] <= t0]
        test = [(o, x) for o, x in data if t0 <= o["as_of"] < t1]
        if len(train) < min_train or len(test) < min_test:
            continue
        ytr = _winsor([o[key] for o, _ in train])
        m = ridge_fit([x for _, x in train], ytr)
        if not m:
            continue
        pred = [ridge_predict(m, x) for _, x in test]
        real = [o[key] for o, _ in test]
        base = mean(ytr)
        ic = spearman(pred, real)
        mse_m = mean([(p - r) ** 2 for p, r in zip(pred, real)])
        mse_b = mean([(base - r) ** 2 for r in real])
        se_m += mse_m * len(test)
        se_b += mse_b * len(test)
        res["folds"].append({"debut": t0, "n_train": len(train), "n_test": len(test),
                             "ic": _r(ic, 3), "mse_model": _r(mse_m, 3),
                             "mse_base": _r(mse_b, 3)})
    ics = [f["ic"] for f in res["folds"] if f["ic"] is not None]
    res["ic_moyen"] = _r(mean(ics), 3) if ics else None
    res["part_ic_positifs"] = _r(sum(1 for i in ics if i > 0) / len(ics), 3) if ics else None
    res["mse_ratio"] = _r(se_m / se_b, 4) if se_b > 0 else None
    return res


def evaluate_model(obs: list, key: str, horizon: int, min_obs: int = ML_MIN_OBS,
                   min_dates: int = ML_MIN_DATES) -> dict:
    """Decide si un modele merite d'etre active. Retourne le verdict complet."""
    exploitables = [o for o in obs if o.get(key) is not None and _features(o)]
    verdict = {"active": False, "n_obs": len(exploitables), "min_obs": min_obs,
               "walk_forward": None}
    if len(exploitables) < min_obs:
        verdict["raison"] = (f"historique insuffisant : {len(exploitables)}/{min_obs} "
                             f"observations closes avec sous-notes")
        return verdict
    wf = walk_forward(exploitables, key, horizon)
    verdict["walk_forward"] = wf
    if wf["n_dates"] < min_dates:
        verdict["raison"] = f"{wf['n_dates']}/{min_dates} seances distinctes"
        return verdict
    if len(wf["folds"]) < ML_MIN_FOLDS:
        verdict["raison"] = f"{len(wf['folds'])}/{ML_MIN_FOLDS} blocs de test valides"
        return verdict
    ok = (wf["ic_moyen"] is not None and wf["ic_moyen"] >= ML_MIN_IC
          and (wf["part_ic_positifs"] or 0) >= 2 / 3
          and wf["mse_ratio"] is not None and wf["mse_ratio"] <= ML_MAX_MSE_RATIO)
    verdict["active"] = bool(ok)
    verdict["raison"] = ("bat la moyenne hors echantillon" if ok else
                         f"ne bat pas la statistique simple hors echantillon "
                         f"(IC {wf['ic_moyen']}, MSE/base {wf['mse_ratio']})")
    return verdict


def train_and_register(ldir: str, obs: list, key: str, kind: str, horizon: int,
                       score_version: str, today, min_obs: int = ML_MIN_OBS,
                       min_dates: int = ML_MIN_DATES) -> dict:
    """Evalue ; si le verdict est positif, entraine sur tout et versionne le modele.

    Re-entrainement seulement si de nouvelles observations le justifient, pour
    que le modele actif soit stable d'un jour a l'autre (auditable).
    """
    reg_dir = _paths(ldir)["registry"]
    active_path = os.path.join(reg_dir, "active.json")
    try:
        with open(active_path, encoding="utf-8") as f:
            active = json.load(f)
    except (OSError, ValueError):
        active = {}
    cle = f"h{horizon}"
    exploitables = [o for o in obs if o.get(key) is not None and _features(o)]
    courant = active.get(cle)
    if courant and courant.get("kind") == kind and courant.get("score_version") == score_version \
            and len(exploitables) < courant.get("n_train", 0) + ML_RETRAIN_EVERY_N:
        return {"active": True, "reutilise": True, **courant}

    verdict = evaluate_model(obs, key, horizon, min_obs, min_dates)
    if not verdict["active"]:
        if courant:                          # un modele qui ne passe plus est retire
            active.pop(cle, None)
            os.makedirs(reg_dir, exist_ok=True)
            with open(active_path, "w", encoding="utf-8") as f:
                json.dump(active, f, ensure_ascii=False, indent=1, sort_keys=True)
        return verdict

    m = ridge_fit([_features(o) for o in exploitables],
                  _winsor([o[key] for o in exploitables]))
    if not m:
        return {**verdict, "active": False, "raison": "ajustement impossible"}
    ident = f"h{horizon}_{kind}_{_iso(today).replace('-', '')}"
    empreinte = hashlib.sha1("|".join(sorted(o["id"] for o in exploitables)).encode()).hexdigest()[:12]
    fiche = {
        "model_id": ident, "type": "ridge", "kind": kind, "horizon": horizon,
        "features": list(ML_FEATURES), "score_version": score_version,
        "trained_on": _iso(today), "n_train": len(exploitables),
        "data_hash": empreinte, "metrics": verdict["walk_forward"], **m,
    }
    os.makedirs(reg_dir, exist_ok=True)
    with open(os.path.join(reg_dir, ident + ".json"), "w", encoding="utf-8") as f:
        json.dump(fiche, f, ensure_ascii=False, indent=1, sort_keys=True)
    active[cle] = {"model_id": ident, "kind": kind, "score_version": score_version,
                   "n_train": len(exploitables), "trained_on": _iso(today),
                   "data_hash": empreinte}
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(active, f, ensure_ascii=False, indent=1, sort_keys=True)
    return {"active": True, "reutilise": False, **active[cle],
            "raison": verdict["raison"], "walk_forward": verdict["walk_forward"]}


def model_predict(ldir: str, horizon: int, snapshot_like: dict) -> dict | None:
    """Prevision du modele ACTIF pour une note du jour, ou None."""
    reg = _paths(ldir)["registry"]
    try:
        with open(os.path.join(reg, "active.json"), encoding="utf-8") as f:
            info = json.load(f).get(f"h{horizon}")
        if not info:
            return None
        with open(os.path.join(reg, info["model_id"] + ".json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError, KeyError):
        return None
    x = _features(snapshot_like)
    if x is None or len(x) != len(m["coef"]):
        return None
    return {"estimate": _r(ridge_predict(m, x), 3), "model_id": m["model_id"],
            "kind": m["kind"]}


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHESE
# ─────────────────────────────────────────────────────────────────────────────

def build_summary(user: str, ldir: str, positions: list, score_version: str,
                  today, settings: dict, maturation: dict = None,
                  train_models: bool = True, mutualise: bool = False) -> dict:
    """Tout ce que le rapport affiche, dans un dictionnaire serialisable."""
    store = load_store(ldir)
    obs = build_observations(store)
    horizons = settings["horizons"]
    main_h = settings["horizon"]

    par_statut = defaultdict(int)
    for o in store["outcomes"]:
        par_statut[o.get("status", "?")] += 1
    par_horizon = {}
    for h in horizons:
        closes = sum(1 for o in store["outcomes"]
                     if o.get("horizon") == h and o.get("status") == "matured")
        invalides = sum(1 for o in store["outcomes"]
                        if o.get("horizon") == h and o.get("status") == "invalid")
        par_horizon[str(h)] = {
            "closes": closes, "invalides": invalides,
            "en_attente": max(0, len(store["snapshots"]) - closes - invalides),
        }

    hs = {}
    for h in horizons:
        per_kind = {}
        for kind, key, _ in KINDS:
            st = horizon_stats(obs, h, kind, key, score_version)
            if st:
                per_kind[kind] = st
        if not per_kind:
            continue
        head = headline_kind(per_kind)
        modele = None
        if train_models and head in ("sector", "market"):
            key = dict((k, kk) for k, kk, _ in KINDS)[head]
            cohorte, _l = select_cohort(obs, score_version, h)
            try:
                modele = train_and_register(ldir, cohorte, key, head, h,
                                            score_version, today)
            except Exception as e:                       # jamais fatal
                modele = {"active": False, "raison": f"erreur : {type(e).__name__}"}
        hs[str(h)] = {"headline": head, "kinds": per_kind, "modele": modele}

    pos_out = []
    for p in positions:
        entree = {"ticker": p["ticker"], "name": p.get("name", p["ticker"]),
                  "score": p["score"], "sector": normalize_sector(p.get("sector")),
                  "horizons": {}}
        for h in horizons:
            bloc = hs.get(str(h))
            if not bloc or not bloc["headline"]:
                continue
            kind = bloc["headline"]
            key = dict((k, kk) for k, kk, _ in KINDS)[kind]
            pr = predict_position(p["score"], entree["sector"], bloc["kinds"][kind],
                                  obs, key, h, score_version)
            pr["kind"] = kind
            ml = model_predict(ldir, h, {"score": p["score"],
                                         "subscores": p.get("subscores") or {}})
            if ml and ml["kind"] == kind:
                pr["modele"] = ml
            entree["horizons"][str(h)] = pr
        pos_out.append(entree)

    return {
        "version": MODULE_VERSION, "user": user, "score_version": score_version,
        "mutualise": bool(mutualise),
        "generated_for": _iso(today), "horizon": main_h, "horizons": horizons,
        "counts": {"snapshots": len(store["snapshots"]),
                   "n_tickers": len({s["ticker"] for s in store["snapshots"]}),
                   "matured": par_statut.get("matured", 0),
                   "invalid": par_statut.get("invalid", 0),
                   "corrompus": store["corrompus"],
                   "legacy": sum(1 for s in store["snapshots"]
                                 if s.get("source") == "backfill_history_csv"),
                   "par_horizon": par_horizon},
        "maturation": maturation or {},
        "horizons_stats": hs,
        "positions": pos_out,
    }


def write_summary(ldir: str, summary: dict) -> str:
    chemin = _paths(ldir)["summary"]
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, chemin)
    return chemin


# ─────────────────────────────────────────────────────────────────────────────
# BLOC MARKDOWN DU RAPPORT
# ─────────────────────────────────────────────────────────────────────────────

_KIND_LABEL = {k: lbl for k, _, lbl in KINDS}


def _pct(v, dec=1, signe=True):
    if v is None:
        return "--"
    return f"{v:+.{dec}f}%" if signe else f"{v:.{dec}f}%"


def _ci(ci):
    return "--" if not ci else f"[{ci[0]:+.1f} ; {ci[1]:+.1f}]"


def render_markdown(summary: dict) -> list:
    """Section « Fiabilite des Notes », distincte de la note actuelle."""
    out = ["", "---", "", "## Fiabilite des Notes", ""]
    if not summary or not summary.get("counts"):
        return out + ["> Section indisponible : aucune donnee d'apprentissage.", ""]
    c = summary["counts"]
    h = str(summary["horizon"])
    out += [
        "*Cette section mesure la valeur PASSEE de la note ; elle ne la modifie "
        "pas et ne predit rien. Une esperance historique n'est pas une promesse.*",
        "",
    ]
    if summary.get("mutualise"):
        out += [f"**Apprentissage mutualise** : calibre sur {c.get('n_tickers', '?')} "
                f"titre(s) suivis par l'ensemble des profils participants. Seuls le "
                f"titre, la date, la note et le resultat sont partages -- jamais "
                f"l'identite, les quantites ni les prix de revient.", ""]
    out += [
        f"**Snapshots : {c['snapshots']}** (dont {c['legacy']} herites de "
        f"history.csv) | **Clotures : {c['matured']}** | **Invalides : {c['invalid']}** "
        f"| Version de la note : `{summary['score_version']}`",
        "",
    ]
    bloc = summary["horizons_stats"].get(h)
    if not bloc:
        ph = c["par_horizon"].get(h, {})
        out += [f"**Horizon {h} seances : aucune observation cloturee pour l'instant.** "
                f"Les {c['snapshots']} snapshot(s) sont en attente d'echeance "
                f"({ph.get('en_attente', c['snapshots'])} en attente). "
                f"Rien n'est conclu avant l'echeance.", ""]
    else:
        kind = bloc["headline"]
        st = bloc["kinds"][kind]
        out += [f"### Notes par tranche -- horizon {h} seances, cible : "
                f"{_KIND_LABEL[kind]}", ""]
        if st["legacy_included"]:
            out += ["*Echantillon inclut la cohorte HERITEE (formules anterieures, "
                    "reconstituee depuis history.csv) : confiance plafonnee a \"faible\".*", ""]
        out += ["| Tranche | N | N indep. | Surperf. moyenne | Mediane | % positifs "
                "| IC 95 % | Esperance calibree | Confiance |",
                "|---------|---|----------|------------------|---------|------------"
                "|---------|--------------------|-----------|"]
        for b in st["bands"]:
            if b["n"] == 0:
                continue
            hit = "--" if b["hit"] is None else f"{b['hit'] * 100:.0f}%"
            out.append(f"| {b['label']} ({b['reco']}) | {b['n']} | {b['n_indep']} "
                       f"| {_pct(b['mean'])} | {_pct(b['median'])} | {hit} "
                       f"| {_ci(b['ci95'])} | {_pct(b['estimate'])} | {b['confidence']} |")
        sl = st["slope"]
        ic_txt = "--" if st["ic"] is None else f"{st['ic']:+.2f}"
        ici_txt = "--" if st["ic_indep"] is None else f"{st['ic_indep']:+.2f}"
        out += ["", f"**Lien note -> surperformance :** IC de rang {ic_txt} "
                f"(echantillon independant : {ici_txt}) | "
                + (f"pente {sl['pente']:+.2f} pt par point de note" if sl else "pente n/d")
                + f" | {st['n_tickers']} titre(s) sur {st['n_dates']} seance(s).", ""]
        if st["sectors"]:
            out += ["| Secteur | N | N indep. | Surperf. moyenne | % positifs | IC de rang |",
                    "|---------|---|----------|------------------|------------|------------|"]
            for s in st["sectors"]:
                hit = "--" if s["hit"] is None else f"{s['hit'] * 100:.0f}%"
                ic = "--" if s["ic"] is None else f"{s['ic']:+.2f}"
                out.append(f"| {s['sector']} | {s['n']} | {s['n_indep']} "
                           f"| {_pct(s['mean'])} | {hit} | {ic} |")
            out.append("")
        if len(st.get("regions") or []) > 1:
            out += ["*Ventilation par region, a titre indicatif (n'entre pas dans le "
                    "calcul de l'esperance calibree) :*", "",
                    "| Region | N | N indep. | Surperf. moyenne | % positifs |",
                    "|--------|---|----------|------------------|------------|"]
            for r in st["regions"]:
                hit = "--" if r["hit"] is None else f"{r['hit'] * 100:.0f}%"
                out.append(f"| {r['region']} | {r['n']} | {r['n_indep']} "
                           f"| {_pct(r['mean'])} | {hit} |")
            out.append("")

    # Quel horizon colle le mieux a la note ?
    lignes = []
    for hh in summary["horizons"]:
        b = summary["horizons_stats"].get(str(hh))
        if not b:
            continue
        st = b["kinds"][b["headline"]]
        haut = st["bands"][-1]
        bas = [x for x in st["bands"][:2] if x["n"]]
        bas_m = mean([x["mean"] for x in bas]) if bas else None
        lignes.append(f"| {hh} | {st['global']['n_indep']} | "
                      f"{'--' if st['ic'] is None else format(st['ic'], '+.2f')} | "
                      f"{_pct(haut['mean']) if haut['n'] else '--'} | {_pct(bas_m)} "
                      f"| {_KIND_LABEL[b['headline']]} |")
    if lignes:
        out += ["### Quel horizon colle le mieux a la note ?", "",
                "| Horizon (seances) | N indep. | IC de rang | Notes >= 7,5 | Notes < 4,5 | Cible |",
                "|-------------------|----------|------------|--------------|-------------|-------|"] \
               + lignes + [""]

    # Fiabilite par position
    if summary["positions"]:
        out += [f"### Fiabilite par position (horizon {h} seances)", "",
                "| Valeur | Note | Surperf. attendue | IC 95 % | P(surperf.) "
                "| Confiance | Echantillon | Cohorte |",
                "|--------|------|-------------------|---------|-------------"
                "|-----------|-------------|---------|"]
        for p in summary["positions"]:
            pr = p["horizons"].get(h)
            if not pr:
                out.append(f"| {p['name']} | {p['score']}/10 | -- | -- | -- "
                           f"| insuffisante | 0 | en attente d'echeance |")
                continue
            proba = "--" if pr["p_outperf"] is None else f"{pr['p_outperf'] * 100:.0f}%"
            cohorte = pr["scope"] + (" + heritee" if pr["legacy_included"] else "")
            att = _pct(pr["estimate"]) if pr["estimate"] is not None else "n/d"
            out.append(f"| {p['name']} | {p['score']}/10 | {att} | {_ci(pr['ci95'])} "
                       f"| {proba} | {pr['confidence']} | {pr['n_indep']} | {cohorte} |")
        out.append("")

    # Modele
    m = (summary["horizons_stats"].get(h) or {}).get("modele")
    if m:
        if m.get("active"):
            out.append(f"**Modele : ACTIF** (`{m.get('model_id')}`, Ridge, valide hors "
                       f"echantillon) -- il complete la calibration, il ne remplace pas la note.")
        else:
            out.append(f"**Modele : non active** -- {m.get('raison', 'historique insuffisant')}. "
                       f"La calibration statistique ci-dessus reste la seule prevision affichee.")
        out.append("")
    if c.get("corrompus"):
        out += [f"> {c['corrompus']} ligne(s) illisible(s) ignoree(s) dans le journal.", ""]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CLI : relit le journal et regenere la synthese, sans reseau
# ─────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Moteur d'apprentissage des notes.")
    ap.add_argument("--user", required=True)
    ap.add_argument("--base", default="reports")
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    ap.add_argument("--score-version", default="legacy")
    ap.add_argument("--pool", action="store_true",
                    help="Lit le journal COMMUN (reports/@pool/learning).")
    ap.add_argument("--backfill", action="store_true",
                    help="Amorce le journal depuis history.csv (une seule fois).")
    args = ap.parse_args()

    ldir = pool_dir(args.base) if args.pool else learning_dir(args.user, args.base)
    cfg = load_config()
    if args.backfill:
        snaps = backfill_from_history_csv(
            os.path.join(args.base, args.user, "history.csv"),
            POOL_USER if args.pool else args.user, cfg)
        print("Amorcage :", record_snapshots(ldir, snaps))
    settings = normalize_settings({"horizon": args.horizon})
    resume = build_summary(args.user, ldir, [], args.score_version,
                           datetime.now().date(), settings, mutualise=args.pool)
    if not args.pool:
        write_summary(ldir, resume)
    print("\n".join(render_markdown(resume)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
