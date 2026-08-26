#!/usr/bin/env python3
"""
risk_engine.py -- Moteur de risque : volatilite, stops, dimensionnement.
================================================================================

CE QUE FAIT CE MODULE, ET CE QU'IL NE FAIT PAS
----------------------------------------------

Il repond a trois questions, et uniquement a celles-la :

  1. « Combien cette valeur bouge-t-elle ? »        -> volatilite()
  2. « A quel niveau je sors ? »                    -> evaluer_stop()
  3. « Combien j'en achete pour risquer 1% ? »      -> dimensionner()

Il ne note aucun titre, ne recommande aucun achat, n'appelle aucune API et
n'ecrit dans aucun fichier de l'analyseur. Il ne depend que de la bibliotheque
standard. C'est deliberé : ce fichier doit pouvoir etre lu, teste et corrige
isolement, sans cle API ni reseau.

--------------------------------------------------------------------------------
1. VOLATILITE
--------------------------------------------------------------------------------

Trois mesures, calculees sur les cloture journalieres disponibles :

  vol_ann_pct : ecart-type des rendements quotidiens, annualise (x sqrt(252)).
                C'est la mesure academique standard du risque de marche.
  atr_pct     : moyenne des amplitudes journalieres absolues sur 14 seances.
                Plus intuitive : « ce titre bouge de 2,1% par jour en moyenne ».
                NOTE : ce n'est PAS l'ATR de Wilder, qui exige haut/bas/cloture.
                Nous n'avons que les clotures -> c'est un ATR de cloture a
                cloture, systematiquement un peu plus bas que le vrai ATR.
  vq_pct      : distance de stop proposee par la volatilite (voir plus bas).

--------------------------------------------------------------------------------
2. LE VQ -- ce que c'est, et ce que ce n'est pas
--------------------------------------------------------------------------------

« VQ » (Volatility Quotient) est a l'origine un indicateur PROPRIETAIRE de
VectorVest. Sa formule exacte n'est pas publique. Ce qui est reproduit ici est
une transposition transparente, dont voici la totalite :

    VQ% = borne( K_VQ x vol_ann_pct , VQ_MIN , VQ_MAX )
    avec K_VQ = 0.65, VQ_MIN = 8%, VQ_MAX = 40%

L'idee est celle du VQ original : une valeur calme merite un stop serre, une
valeur nerveuse a besoin d'air, sans quoi on se fait sortir par le bruit
ordinaire du marche. Les bornes evitent les deux absurdites : un stop a 2% sur
une action (on serait sorti a la premiere seance) et un stop a 90% sur une
crypto (ce n'est plus un stop, c'est une esperance).

Ce chiffre N'EST PAS le VQ de VectorVest et ne doit pas etre presente comme
tel. Il s'en approche empiriquement : une action tres volatile ressort autour
de 30%, le bitcoin autour de 38%, une grande capitalisation stable autour de
12-15%.

--------------------------------------------------------------------------------
3. LES QUATRE TYPES DE STOP
--------------------------------------------------------------------------------

  percent   : X% sous le PRIX DE REVIENT. Fixe. Repond a « combien j'accepte
              de perdre sur cette ligne ». Ne monte jamais.
  absolute  : un prix ecrit en dur. Utile quand on vise un niveau technique
              precis (un support, un plus-bas de consolidation).
  trailing  : X% sous le PLUS HAUT DE CLOTURE atteint depuis l'activation.
              Monte avec le cours, ne redescend JAMAIS (cliquet).
  vq        : identique au trailing, mais X est calcule automatiquement par la
              volatilite (voir ci-dessus) au lieu d'etre choisi a la main.

Le cliquet (« ratchet ») est le point qui fait toute la difference entre un
trailing stop et un stop en pourcentage : le niveau de sortie remonte quand le
cours monte, ce qui verrouille progressivement le gain, et il reste fige quand
le cours baisse.

--------------------------------------------------------------------------------
4. REGLE DE FRANCHISSEMENT
--------------------------------------------------------------------------------

Un stop est franchi quand la CLOTURE du jour passe sous le niveau. Pas le cours
en seance : un mouvement intra-journalier qui se retourne avant la cloture est
du bruit, et declencher dessus produit des sorties inutiles.

Une alerte, une seule, par franchissement. Tant que la valeur reste sous son
stop, on ne repete pas l'alerte tous les jours. Le declencheur se re-arme des
que la cloture repasse au-dessus du niveau.

--------------------------------------------------------------------------------
5. DIMENSIONNEMENT
--------------------------------------------------------------------------------

Le principe tient en une ligne :

    montant a engager = (capital x risque par idee) / distance au stop

Exemple : 100 000 EUR de capital, 1% de risque par idee (soit 1 000 EUR), stop
a 20% sous le prix d'entree -> 1 000 / 0.20 = 5 000 EUR de position. Si le stop
part, on perd 20% de 5 000 = 1 000 EUR, soit exactement le budget de risque.

C'est ce qui rend une position volatile et une position calme COMPARABLES : on
n'achete pas le meme montant, on achete le meme risque.

Deux garde-fous s'appliquent ensuite :
  - un plafond de poids (defaut 15% du capital) : sans lui, un stop tres serre
    sur une valeur calme justifierait d'y mettre la moitie du portefeuille ;
  - un plafond de liquidite : on ne propose jamais plus que le cash disponible
    quand celui-ci est connu.

LIMITE ASSUMEE : cette formule suppose que le stop est effectivement execute
au niveau prevu. En cas de trou de cotation (gap d'ouverture, suspension), la
perte reelle depasse le budget. Le dimensionnement borne le risque ordinaire,
pas le risque extreme.
================================================================================
"""

from __future__ import annotations

import json
import os
from datetime import datetime

# =============================================================================
# CONSTANTES
# =============================================================================

# -- VQ ----------------------------------------------------------------------
K_VQ   = 0.65      # facteur appliqué à la volatilité annualisée
VQ_MIN = 8.0       # plancher, en % : en deçà on sort sur du bruit
VQ_MAX = 40.0      # plafond, en % : au-delà ce n'est plus un stop

# -- Volatilité --------------------------------------------------------------
MIN_OBS_VOL   = 20    # nb minimal de clôtures pour publier une volatilité
ATR_PERIODE   = 14    # fenêtre de l'ATR de clôture
JOURS_BOURSE  = 252   # séances par an, pour l'annualisation

# -- Dimensionnement ---------------------------------------------------------
RISQUE_DEFAUT_PCT   = 1.0    # % du capital risqué par idée
POIDS_MAX_PCT       = 15.0   # % du capital maximum sur une seule ligne
DISTANCE_MIN_PCT    = 1.0    # garde-fou : une distance plus courte est ignorée
# Volatilité annuelle qu'une ligne SANS stop a le droit d'apporter au
# portefeuille, en % du capital. Sert de repli au dimensionnement.
VOL_CIBLE_DEFAUT_PCT = 2.0

# -- Types de stop reconnus --------------------------------------------------
TYPES_STOP = ("percent", "absolute", "trailing", "vq", "none")

# Libellés affichables, pour ne pas répéter la traduction partout.
LIBELLE_TYPE = {
    "percent":  "Pourcentage",
    "absolute": "Absolu",
    "trailing": "Suiveur",
    "vq":       "VQ (volatilité)",
    "none":     "Aucun",
}

# Statuts possibles d'une ligne surveillée.
STATUT_OK       = "ok"        # au-dessus du stop
STATUT_FRANCHI  = "franchi"   # clôture sous le stop
STATUT_AUCUN    = "aucun"     # pas de stop configuré
STATUT_INCALC   = "incalculable"  # stop configuré mais données manquantes


# =============================================================================
# OUTILS NUMÉRIQUES
# =============================================================================

def _nombre(valeur):
    """Convertit en float, ou None. Aucune exception ne sort d'ici.

    Tout ce module reçoit des données d'API : une chaîne vide, un "NA" ou un
    None peuvent arriver sur n'importe quel champ. On normalise une fois, ici.
    """
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):   # NaN / infini
        return None
    return v


def _series_propre(closes) -> list:
    """Liste de clôtures strictement positives, dans l'ordre reçu."""
    sortie = []
    for c in (closes or []):
        v = _nombre(c)
        if v is not None and v > 0:
            sortie.append(v)
    return sortie


def _borner(valeur: float, bas: float, haut: float) -> float:
    return max(bas, min(haut, valeur))


# =============================================================================
# VOLATILITÉ
# =============================================================================

def volatilite(closes) -> dict:
    """Mesures de volatilité à partir d'une série de clôtures.

    Retourne toujours un dict aux mêmes clés ; les valeurs sont None quand la
    série est trop courte. Jamais d'exception, jamais de zéro trompeur : un
    actif à 0% de volatilité n'existe pas, donc 0 ne doit pas pouvoir sortir
    d'ici par accident.
    """
    serie = _series_propre(closes)
    vide = {"vol_ann_pct": None, "atr_pct": None, "vq_pct": None,
            "n_obs": len(serie), "fiable": False}

    if len(serie) < MIN_OBS_VOL:
        return vide

    # Rendements arithmétiques journaliers.
    rends = [(serie[i] / serie[i - 1]) - 1.0
             for i in range(1, len(serie)) if serie[i - 1] > 0]
    if len(rends) < MIN_OBS_VOL - 1:
        return vide

    moy = sum(rends) / len(rends)
    var = sum((r - moy) ** 2 for r in rends) / len(rends)
    vol_ann_pct = (var ** 0.5) * (JOURS_BOURSE ** 0.5) * 100.0

    # ATR de clôture à clôture, sur les ATR_PERIODE dernières séances.
    fenetre = rends[-ATR_PERIODE:] if len(rends) >= ATR_PERIODE else rends
    atr_pct = sum(abs(r) for r in fenetre) / len(fenetre) * 100.0

    vq_pct = _borner(K_VQ * vol_ann_pct, VQ_MIN, VQ_MAX)

    return {
        "vol_ann_pct": round(vol_ann_pct, 2),
        "atr_pct":     round(atr_pct, 2),
        "vq_pct":      round(vq_pct, 2),
        "n_obs":       len(serie),
        # Une volatilité calculée sur 25 points n'a pas la robustesse d'une
        # volatilité sur 120. On le signale plutôt que de le taire.
        "fiable":      len(serie) >= 60,
    }


def classe_volatilite(vol_ann_pct) -> str:
    """Étiquette lisible : Faible / Modérée / Élevée / Extrême."""
    v = _nombre(vol_ann_pct)
    if v is None:
        return "N/D"
    if v < 18:
        return "Faible"
    if v < 32:
        return "Modérée"
    if v < 55:
        return "Élevée"
    return "Extrême"


# =============================================================================
# ÉTAT PERSISTANT DES STOPS
# =============================================================================
# Le high-water mark et l'armement de l'alerte doivent survivre d'un run à
# l'autre : sans mémoire, un trailing stop se recalculerait chaque jour depuis
# l'historique disponible et perdrait son cliquet.
#
# Le fichier vit dans reports/<utilisateur>/stops_state.json, donc dans un
# dossier que le workflow GitHub commite déjà. Aucune modification du YAML
# n'est nécessaire.

SCHEMA_ETAT = 1


def charger_etat(chemin: str) -> dict:
    """Lit l'état des stops. Un fichier absent ou corrompu = état vierge.

    On ne lève jamais : perdre l'historique des high-water marks dégrade le
    service (les stops suiveurs repartent du plus haut connu), ça ne doit pas
    faire échouer le rapport quotidien.
    """
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"schema": SCHEMA_ETAT, "lignes": {}}
        data.setdefault("schema", SCHEMA_ETAT)
        if not isinstance(data.get("lignes"), dict):
            data["lignes"] = {}
        return data
    except (OSError, ValueError):
        return {"schema": SCHEMA_ETAT, "lignes": {}}


def sauver_etat(chemin: str, etat: dict) -> bool:
    """Écrit l'état des stops. Retourne False en cas d'échec, sans lever."""
    try:
        dossier = os.path.dirname(chemin)
        if dossier:
            os.makedirs(dossier, exist_ok=True)
        etat = dict(etat or {})
        etat["schema"] = SCHEMA_ETAT
        etat["maj"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(etat, f, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except (OSError, TypeError, ValueError):
        return False


# =============================================================================
# CONFIGURATION D'UN STOP
# =============================================================================

def lire_config_stop(ligne: dict, defaut: dict = None) -> dict:
    """Extrait et valide la configuration de stop d'une ligne de portefeuille.

    Accepte trois écritures, par ordre de priorité :
        "stop": {"type": "trailing", "value": 15}
        "stop": "vq"                      (raccourci sans paramètre)
        rien                              -> stop par défaut du profil, sinon aucun

    Une configuration invalide (type inconnu, valeur absurde) est rejetée vers
    "none" plutôt que silencieusement corrigée : un stop mal compris est pire
    qu'un stop absent, parce qu'on croit être protégé.
    """
    brut = ligne.get("stop", None)
    if brut in (None, "", {}):
        brut = defaut

    if isinstance(brut, str):
        brut = {"type": brut}
    if not isinstance(brut, dict):
        return {"type": "none", "value": None, "devise": None, "erreur": None}

    typ = str(brut.get("type") or brut.get("mode") or "none").strip().lower()
    if typ in ("pourcentage", "pct", "%"):
        typ = "percent"
    elif typ in ("absolu", "fixe", "fixed"):
        typ = "absolute"
    elif typ in ("suiveur", "trail"):
        typ = "trailing"
    elif typ in ("volatilite", "volatility"):
        typ = "vq"

    if typ not in TYPES_STOP:
        return {"type": "none", "value": None, "devise": None,
                "erreur": f"type de stop inconnu : {typ}"}

    val = _nombre(brut.get("value", brut.get("valeur")))
    devise = str(brut.get("devise") or brut.get("currency") or "").strip().upper() or None

    if typ in ("percent", "trailing"):
        if val is None:
            return {"type": "none", "value": None, "devise": None,
                    "erreur": f"stop {typ} sans pourcentage"}
        if not (0 < val < 100):
            return {"type": "none", "value": None, "devise": None,
                    "erreur": f"pourcentage hors bornes : {val}"}
    elif typ == "absolute":
        if val is None or val <= 0:
            return {"type": "none", "value": None, "devise": None,
                    "erreur": "stop absolu sans prix valide"}
    else:
        val = None   # vq et none n'ont pas de paramètre

    return {"type": typ, "value": val, "devise": devise, "erreur": None}


# =============================================================================
# ÉVALUATION D'UN STOP
# =============================================================================

def evaluer_stop(ligne: dict,
                 cours: float,
                 cout: float,
                 closes=None,
                 etat_ligne: dict = None,
                 eur_par_devise: float = 1.0,
                 defaut: dict = None,
                 aujourdhui: str = None) -> dict:
    """Calcule le niveau de stop d'une ligne et son statut.

    Paramètres
    ----------
    ligne          : la ligne de portefeuille (dict normalisé)
    cours          : clôture du jour, dans la MÊME devise que `cout`
    cout           : prix de revient unitaire
    closes         : historique de clôtures, pour le high-water mark et le VQ
    etat_ligne     : état persistant précédent {hwm, armed, ...}
    eur_par_devise : taux de conversion pour un stop absolu libellé en devise
                     étrangère (ex. 0.86 pour convertir un stop en USD vers EUR)
    defaut         : configuration de stop par défaut du profil
    aujourdhui     : date ISO, injectable pour les tests

    Retour : dict complet, jamais None, jamais d'exception.
    """
    aujourdhui = aujourdhui or datetime.now().strftime("%Y-%m-%d")
    etat_ligne = dict(etat_ligne or {})
    cfg = lire_config_stop(ligne, defaut)

    base = {
        "type":          cfg["type"],
        "type_label":    LIBELLE_TYPE.get(cfg["type"], cfg["type"]),
        "config":        cfg["value"],
        "erreur":        cfg["erreur"],
        "niveau":        None,
        "distance_pct":  None,
        "statut":        STATUT_AUCUN,
        "hwm":           _nombre(etat_ligne.get("hwm")),
        "arme":          bool(etat_ligne.get("arme", True)),
        "alerte":        False,          # True SEULEMENT le jour du franchissement
        "amorcage":      False,          # True au tout premier calcul de la ligne
        "vq_pct":        None,
        "description":   "Aucun stop défini",
        "etat":          etat_ligne,
    }

    if cfg["type"] == "none":
        base["description"] = cfg["erreur"] or "Aucun stop défini"
        base["etat"] = {"hwm": base["hwm"], "arme": True}
        return base

    px = _nombre(cours)
    px_revient = _nombre(cout)
    serie = _series_propre(closes)

    if px is None or px <= 0:
        base["statut"] = STATUT_INCALC
        base["description"] = "Cours indisponible"
        return base

    # ── High-water mark ──────────────────────────────────────────────────────
    # Au premier passage il n'existe aucun état : on amorce sur le plus haut de
    # clôture connu de l'historique, à défaut sur le cours du jour. C'est la
    # seule hypothèse défendable — mais elle est signalée (`amorcage`), parce
    # qu'une valeur déjà très retracée peut ressortir « franchie » dès le
    # premier run sans que ce soit un événement du jour.
    hwm_precedent = _nombre(etat_ligne.get("hwm"))
    if hwm_precedent is None:
        base["amorcage"] = True
        hwm = max(serie) if serie else px
    else:
        hwm = hwm_precedent
    hwm = max(hwm, px)            # cliquet : ne redescend jamais
    base["hwm"] = round(hwm, 6)

    # ── Volatilité (nécessaire au type vq) ───────────────────────────────────
    vol = volatilite(serie)
    base["vq_pct"] = vol["vq_pct"]

    # ── Niveau du stop selon le type ─────────────────────────────────────────
    typ = cfg["type"]
    niveau = None

    if typ == "percent":
        if px_revient is None or px_revient <= 0:
            base["statut"] = STATUT_INCALC
            base["description"] = "Prix de revient indisponible"
            base["etat"] = {"hwm": base["hwm"], "arme": base["arme"]}
            return base
        niveau = px_revient * (1 - cfg["value"] / 100.0)
        base["description"] = f"{cfg['value']:.4g}\u202f% sous le prix de revient"

    elif typ == "absolute":
        taux = _nombre(eur_par_devise) or 1.0
        niveau = cfg["value"] * (taux if cfg["devise"] and cfg["devise"] != "EUR" else 1.0)
        if cfg["devise"] and cfg["devise"] != "EUR":
            base["description"] = f"Fixé à {cfg['value']:.4g}\u202f{cfg['devise']}"
        else:
            base["description"] = f"Fixé à {cfg['value']:.4g}"

    elif typ == "trailing":
        niveau = hwm * (1 - cfg["value"] / 100.0)
        base["description"] = f"{cfg['value']:.4g}\u202f% sous le plus haut {hwm:.2f}"

    elif typ == "vq":
        if vol["vq_pct"] is None:
            base["statut"] = STATUT_INCALC
            base["description"] = (f"Historique insuffisant pour le VQ "
                                   f"({vol['n_obs']} clôture(s), {MIN_OBS_VOL} requises)")
            base["etat"] = {"hwm": base["hwm"], "arme": base["arme"]}
            return base
        niveau = hwm * (1 - vol["vq_pct"] / 100.0)
        base["description"] = (f"VQ {vol['vq_pct']:.1f}\u202f% (auto) sous le plus haut "
                               f"{hwm:.2f}")

    if niveau is None or niveau <= 0:
        base["statut"] = STATUT_INCALC
        base["description"] = "Niveau de stop incalculable"
        base["etat"] = {"hwm": base["hwm"], "arme": base["arme"]}
        return base

    # ── Cliquet sur le niveau lui-même ───────────────────────────────────────
    # Le high-water mark suffit pour trailing, mais pas pour vq : si la
    # volatilité augmente, le VQ s'élargit et le niveau calculé REDESCEND, ce
    # qui reviendrait à desserrer un stop en cours de route. On l'interdit.
    #
    # SAUF si la configuration a changé depuis le dernier run : passer
    # volontairement un stop de 10% à 25% est une décision, pas une dérive, et
    # elle doit s'appliquer. On compare donc une signature de la config.
    signature = f"{typ}:{cfg['value']}:{cfg['devise'] or ''}"
    config_inchangee = etat_ligne.get("cfg") in (None, signature)
    niveau_precedent = _nombre(etat_ligne.get("niveau"))
    if typ in ("trailing", "vq") and niveau_precedent is not None and config_inchangee:
        niveau = max(niveau, niveau_precedent)

    base["niveau"] = round(niveau, 4)
    base["distance_pct"] = round((px - niveau) / niveau * 100.0, 2) if niveau else None

    # ── Statut + gestion de l'alerte ─────────────────────────────────────────
    sous_le_stop = px < niveau
    arme = bool(etat_ligne.get("arme", True))

    if sous_le_stop:
        base["statut"] = STATUT_FRANCHI
        # Une alerte, une seule, par franchissement.
        base["alerte"] = arme
        arme = False
    else:
        base["statut"] = STATUT_OK
        # Le retour au-dessus du niveau ré-arme le déclencheur.
        arme = True

    base["arme"] = arme
    base["etat"] = {
        "hwm":     base["hwm"],
        "niveau":  base["niveau"],
        "cfg":     signature,
        "arme":    arme,
        "statut":  base["statut"],
        "maj":     aujourdhui,
        "derniere_alerte": (aujourdhui if base["alerte"]
                            else etat_ligne.get("derniere_alerte")),
    }
    return base


# =============================================================================
# DIMENSIONNEMENT
# =============================================================================

def dimensionner(capital: float,
                 cours: float,
                 distance_pct: float,
                 risque_pct: float = RISQUE_DEFAUT_PCT,
                 poids_max_pct: float = POIDS_MAX_PCT,
                 liquidites: float = None) -> dict:
    """Taille de position pour un budget de risque donné.

    `distance_pct` est la distance entre le cours et le stop, en % du cours.
    C'est elle, et non la volatilité brute, qui pilote la taille : deux titres
    de volatilités différentes mais de stops équivalents méritent la même
    somme.

    Retourne toujours un dict ; `montant` vaut None quand le calcul n'a pas de
    sens (pas de stop, capital inconnu, distance aberrante).
    """
    vide = {"montant": None, "quantite": None, "risque_eur": None,
            "poids_pct": None, "bride": None, "distance_pct": None}

    cap  = _nombre(capital)
    px   = _nombre(cours)
    dist = _nombre(distance_pct)
    rsq  = _nombre(risque_pct)
    if rsq is None or rsq <= 0:
        rsq = RISQUE_DEFAUT_PCT
    pmax = _nombre(poids_max_pct)
    if pmax is None or pmax <= 0:
        pmax = POIDS_MAX_PCT

    if cap is None or cap <= 0 or px is None or px <= 0:
        return vide
    if dist is None or dist < DISTANCE_MIN_PCT or dist >= 100:
        # Une distance sous 1% donnerait une taille délirante ; au-dessus de
        # 100% le stop est sous zéro, ce qui n'existe pas.
        return {**vide, "distance_pct": dist}

    risque_eur = cap * rsq / 100.0
    montant    = risque_eur / (dist / 100.0)
    bride      = None

    plafond_poids = cap * pmax / 100.0
    if montant > plafond_poids:
        montant = plafond_poids
        bride   = f"plafonné à {pmax:.4g} % du capital"

    liq = _nombre(liquidites)
    if liq is not None and liq >= 0 and montant > liq:
        montant = liq
        bride   = "plafonné par les liquidités disponibles"

    quantite = montant / px

    return {
        "montant":      round(montant, 2),
        "quantite":     round(quantite, 4),
        # Risque réellement encouru APRÈS bridage : c'est ce chiffre qui compte,
        # pas le budget théorique.
        "risque_eur":   round(montant * dist / 100.0, 2),
        "poids_pct":    round(montant / cap * 100.0, 2),
        "bride":        bride,
        "distance_pct": round(dist, 2),
    }


def dimensionner_par_volatilite(capital: float,
                                cours: float,
                                vol_ann_pct: float,
                                vol_cible_pct: float = VOL_CIBLE_DEFAUT_PCT,
                                poids_max_pct: float = POIDS_MAX_PCT) -> dict:
    """Variante pour les lignes SANS stop : budget de volatilité.

    `vol_cible_pct` est la volatilité annuelle que la ligne a le droit
    d'APPORTER au portefeuille, exprimée en % du capital. Le poids suit :

        poids = budget de volatilite / volatilite de l'actif

    Avec un budget de 2% : un titre à 18% de volatilité pèse 11% du capital,
    un titre à 70% n'en pèse que 3%. C'est la même logique que le
    dimensionnement par le stop — égaliser le risque, pas le montant — mais
    elle s'applique quand aucun stop n'est défini.

    ATTENTION au choix du budget : le mettre au niveau d'une volatilité de
    marché (15%) reviendrait à autoriser presque n'importe quel poids, et le
    plafond de poids ferait seul le travail. Le défaut est donc bas.
    """
    cap = _nombre(capital)
    px  = _nombre(cours)
    vol = _nombre(vol_ann_pct)
    cible = _nombre(vol_cible_pct) or VOL_CIBLE_DEFAUT_PCT

    if cap is None or cap <= 0 or px is None or px <= 0 or vol is None or vol <= 0:
        return {"montant": None, "quantite": None, "poids_pct": None}

    poids_pct = min(cible / vol * 100.0, _nombre(poids_max_pct) or POIDS_MAX_PCT)
    montant   = cap * poids_pct / 100.0
    return {
        "montant":   round(montant, 2),
        "quantite":  round(montant / px, 4),
        "poids_pct": round(poids_pct, 2),
    }


# =============================================================================
# ORCHESTRATION
# =============================================================================

def evaluer_portefeuille(lignes: list,
                         etat: dict = None,
                         capital: float = None,
                         reglages: dict = None,
                         aujourdhui: str = None) -> dict:
    """Évalue stops et dimensionnement sur tout un portefeuille.

    `lignes` : liste de dicts contenant au minimum
        cle        identifiant stable de la ligne (ticker normalisé)
        nom        libellé affiché
        cours      clôture du jour
        cout       prix de revient unitaire
        closes     historique de clôtures (liste)
        ligne      la ligne de portefeuille brute (pour y lire "stop")
        compte     nom du compte / courtier (facultatif)
        eur_par_devise  taux de conversion (facultatif, défaut 1.0)

    Retourne {"lignes": [...], "etat": {...}, "resume": {...}}.
    Cette fonction ne lève jamais : une ligne qui plante est isolée et
    reportée dans son propre champ `erreur`.
    """
    reglages = reglages or {}
    etat_in  = (etat or {}).get("lignes") or {}
    etat_out = {}
    defaut   = reglages.get("stop_defaut")
    risque   = reglages.get("risque_pct", RISQUE_DEFAUT_PCT)
    poids_max = reglages.get("poids_max_pct", POIDS_MAX_PCT)

    sorties = []
    for item in (lignes or []):
        cle = str(item.get("cle") or item.get("nom") or "")
        try:
            res = evaluer_stop(
                ligne=item.get("ligne") or {},
                cours=item.get("cours"),
                cout=item.get("cout"),
                closes=item.get("closes"),
                etat_ligne=etat_in.get(cle),
                eur_par_devise=item.get("eur_par_devise", 1.0),
                defaut=defaut,
                aujourdhui=aujourdhui,
            )
            vol = volatilite(item.get("closes"))
            taille = dimensionner(
                capital=capital,
                cours=item.get("cours"),
                distance_pct=res.get("distance_pct"),
                risque_pct=risque,
                poids_max_pct=poids_max,
            )
            if res.get("statut") == STATUT_FRANCHI:
                # Une ligne SOUS son stop n'a pas de taille d'entrée : la
                # distance au stop est négative, la formule n'a plus de sens, et
                # suggérer un montant reviendrait à proposer de renforcer une
                # position que la règle vient de déclarer sortante.
                taille = {"montant": None, "quantite": None, "risque_eur": None,
                          "poids_pct": None, "bride": "stop franchi — pas de taille d'entrée",
                          "distance_pct": res.get("distance_pct")}
            elif taille["montant"] is None and vol["vol_ann_pct"]:
                # Pas de stop exploitable : on retombe sur la cible de
                # volatilité, qui reste une réponse défendable.
                alt = dimensionner_par_volatilite(
                    capital, item.get("cours"), vol["vol_ann_pct"],
                    reglages.get("vol_cible_pct", VOL_CIBLE_DEFAUT_PCT), poids_max)
                taille = {**taille, **alt, "bride": "dimensionné par la volatilité"}

            sorties.append({
                "cle":       cle,
                "nom":       item.get("nom") or cle,
                "compte":    item.get("compte") or "",
                "cours":     _nombre(item.get("cours")),
                "stop":      res,
                "vol":       vol,
                "taille":    taille,
                "erreur":    None,
            })
            etat_out[cle] = res["etat"]
        except Exception as e:      # filet : aucune ligne ne doit tuer le run
            sorties.append({
                "cle": cle, "nom": item.get("nom") or cle,
                "compte": item.get("compte") or "",
                "cours": _nombre(item.get("cours")),
                "stop": {"type": "none", "type_label": "Aucun", "niveau": None,
                         "distance_pct": None, "statut": STATUT_INCALC,
                         "alerte": False, "description": f"Erreur : {e}",
                         "config": None, "vq_pct": None, "hwm": None,
                         "amorcage": False, "erreur": str(e)},
                "vol": volatilite(None),
                "taille": {"montant": None, "quantite": None, "risque_eur": None,
                           "poids_pct": None, "bride": None, "distance_pct": None},
                "erreur": str(e),
            })
            if cle in etat_in:
                etat_out[cle] = etat_in[cle]   # on ne perd pas l'historique

    actifs   = [s for s in sorties if s["stop"]["statut"] in (STATUT_OK, STATUT_FRANCHI)]
    franchis = [s for s in sorties if s["stop"]["statut"] == STATUT_FRANCHI]
    alertes  = [s for s in sorties if s["stop"].get("alerte")]
    sans     = [s for s in sorties if s["stop"]["statut"] == STATUT_AUCUN]

    return {
        "lignes": sorties,
        "etat":   {"schema": SCHEMA_ETAT, "lignes": etat_out},
        "resume": {
            "actifs":    len(actifs),
            "franchis":  len(franchis),
            "alertes":   len(alertes),
            "sans_stop": len(sans),
            "total":     len(sorties),
        },
    }


# =============================================================================
# AUTOTEST
# =============================================================================
# `python risk_engine.py` exécute la batterie et affiche un compte rendu. Aucun
# réseau, aucune clé API : ce test doit passer partout, tout le temps.

def _autotest() -> int:
    ok, ko = 0, []

    def verifie(nom, condition, detail=""):
        nonlocal ok
        if condition:
            ok += 1
        else:
            ko.append(f"{nom} — {detail}")

    # -- Volatilité ----------------------------------------------------------
    plat = [100.0] * 40
    v = volatilite(plat)
    verifie("vol serie plate = 0", v["vol_ann_pct"] == 0.0, str(v))
    verifie("vq plancher sur serie plate", v["vq_pct"] == VQ_MIN, str(v))

    verifie("vol serie trop courte", volatilite([100, 101, 102])["vol_ann_pct"] is None)
    verifie("vol serie vide", volatilite(None)["vol_ann_pct"] is None)
    verifie("vol ignore les valeurs sales",
            volatilite(["", None, "NA", -5] + plat)["n_obs"] == 40)

    # Série alternée ±2% par jour : volatilité élevée, VQ plafonné.
    alt = []
    p = 100.0
    for i in range(80):
        p *= 1.02 if i % 2 == 0 else 1 / 1.02
        alt.append(p)
    va = volatilite(alt)
    verifie("vol alternee elevee", va["vol_ann_pct"] > 25, str(va))
    verifie("vq borne haute", va["vq_pct"] <= VQ_MAX, str(va))

    verifie("classe volatilite faible", classe_volatilite(12) == "Faible")
    verifie("classe volatilite moderee", classe_volatilite(25) == "Modérée")
    verifie("classe volatilite elevee", classe_volatilite(40) == "Élevée")
    verifie("classe volatilite extreme", classe_volatilite(80) == "Extrême")
    verifie("classe volatilite inconnue", classe_volatilite(None) == "N/D")

    # -- Configuration -------------------------------------------------------
    verifie("config vide -> none", lire_config_stop({})["type"] == "none")
    verifie("config raccourci vq", lire_config_stop({"stop": "vq"})["type"] == "vq")
    verifie("config alias francais",
            lire_config_stop({"stop": {"type": "suiveur", "value": 10}})["type"] == "trailing")
    verifie("config pct hors bornes rejetee",
            lire_config_stop({"stop": {"type": "percent", "value": 150}})["type"] == "none")
    verifie("config pct sans valeur rejetee",
            lire_config_stop({"stop": {"type": "trailing"}})["type"] == "none")
    verifie("config absolu negatif rejete",
            lire_config_stop({"stop": {"type": "absolute", "value": -3}})["type"] == "none")
    verifie("config type inconnu rejete",
            lire_config_stop({"stop": {"type": "magique", "value": 5}})["type"] == "none")
    verifie("config defaut applique",
            lire_config_stop({}, {"type": "vq"})["type"] == "vq")

    # -- Stop percent --------------------------------------------------------
    r = evaluer_stop({"stop": {"type": "percent", "value": 20}},
                     cours=90, cout=100, closes=plat)
    verifie("percent niveau", abs(r["niveau"] - 80) < 1e-6, str(r["niveau"]))
    verifie("percent statut ok", r["statut"] == STATUT_OK, r["statut"])
    verifie("percent distance", abs(r["distance_pct"] - 12.5) < 0.01, str(r["distance_pct"]))

    r = evaluer_stop({"stop": {"type": "percent", "value": 20}},
                     cours=70, cout=100, closes=plat)
    verifie("percent franchi", r["statut"] == STATUT_FRANCHI, r["statut"])
    verifie("percent alerte", r["alerte"] is True)

    # -- Stop absolu + devise ------------------------------------------------
    r = evaluer_stop({"stop": {"type": "absolute", "value": 180, "devise": "USD"}},
                     cours=200, cout=150, closes=plat, eur_par_devise=0.9)
    verifie("absolu converti", abs(r["niveau"] - 162.0) < 1e-6, str(r["niveau"]))
    r = evaluer_stop({"stop": {"type": "absolute", "value": 180}},
                     cours=200, cout=150, closes=plat)
    verifie("absolu EUR non converti", abs(r["niveau"] - 180.0) < 1e-6, str(r["niveau"]))

    # -- Trailing + cliquet --------------------------------------------------
    r1 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=100, cout=80, closes=[100.0] * 30)
    verifie("trailing niveau initial", abs(r1["niveau"] - 90) < 1e-6, str(r1["niveau"]))
    verifie("trailing amorcage signale", r1["amorcage"] is True)

    r2 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=120, cout=80, closes=[100.0] * 30,
                      etat_ligne=r1["etat"])
    verifie("trailing hwm monte", abs(r2["hwm"] - 120) < 1e-6, str(r2["hwm"]))
    verifie("trailing niveau monte", abs(r2["niveau"] - 108) < 1e-6, str(r2["niveau"]))

    r3 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=110, cout=80, closes=[100.0] * 30,
                      etat_ligne=r2["etat"])
    verifie("trailing cliquet : niveau ne redescend pas",
            abs(r3["niveau"] - 108) < 1e-6, str(r3["niveau"]))
    verifie("trailing pas d'amorcage au 2e run", r3["amorcage"] is False)

    # -- Une alerte, une seule, puis ré-armement -----------------------------
    a1 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=100, cout=80, closes=[100.0] * 30)
    a2 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=85, cout=80, closes=[100.0] * 30, etat_ligne=a1["etat"])
    verifie("1er franchissement alerte", a2["alerte"] is True and a2["statut"] == STATUT_FRANCHI)
    a3 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=84, cout=80, closes=[100.0] * 30, etat_ligne=a2["etat"])
    verifie("2e jour sous le stop : pas de nouvelle alerte", a3["alerte"] is False)
    a4 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=95, cout=80, closes=[100.0] * 30, etat_ligne=a3["etat"])
    verifie("retour au-dessus : re-arme", a4["arme"] is True and a4["alerte"] is False)
    a5 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=85, cout=80, closes=[100.0] * 30, etat_ligne=a4["etat"])
    verifie("nouveau franchissement : nouvelle alerte", a5["alerte"] is True)

    # -- VQ ------------------------------------------------------------------
    r = evaluer_stop({"stop": "vq"}, cours=100, cout=90, closes=alt)
    verifie("vq niveau calcule", r["niveau"] is not None and r["niveau"] < 100, str(r))
    verifie("vq pct expose", r["vq_pct"] is not None)
    r = evaluer_stop({"stop": "vq"}, cours=100, cout=90, closes=[100, 101, 99])
    verifie("vq sans historique -> incalculable", r["statut"] == STATUT_INCALC, r["statut"])

    # Le VQ ne doit pas se desserrer quand la volatilité augmente.
    v1 = evaluer_stop({"stop": "vq"}, cours=100, cout=90, closes=plat)
    v2 = evaluer_stop({"stop": "vq"}, cours=100, cout=90, closes=alt,
                      etat_ligne=v1["etat"])
    verifie("vq ne redescend pas", v2["niveau"] >= v1["niveau"] - 1e-9,
            f"{v1['niveau']} -> {v2['niveau']}")

    # Un changement volontaire de configuration doit s'appliquer, cliquet ou non.
    c1 = evaluer_stop({"stop": {"type": "trailing", "value": 10}},
                      cours=100, cout=80, closes=[100.0] * 30)
    c2 = evaluer_stop({"stop": {"type": "trailing", "value": 25}},
                      cours=100, cout=80, closes=[100.0] * 30, etat_ligne=c1["etat"])
    verifie("changement de config applique", abs(c2["niveau"] - 75) < 1e-6,
            f"{c1['niveau']} -> {c2['niveau']}")
    c3 = evaluer_stop({"stop": {"type": "trailing", "value": 25}},
                      cours=95, cout=80, closes=[100.0] * 30, etat_ligne=c2["etat"])
    verifie("cliquet reprend apres changement", abs(c3["niveau"] - 75) < 1e-6,
            str(c3["niveau"]))

    # -- Cas dégradés --------------------------------------------------------
    verifie("cours absent -> incalculable",
            evaluer_stop({"stop": "vq"}, cours=None, cout=90, closes=plat)["statut"] == STATUT_INCALC)
    verifie("percent sans prix de revient -> incalculable",
            evaluer_stop({"stop": {"type": "percent", "value": 10}},
                         cours=100, cout=None, closes=plat)["statut"] == STATUT_INCALC)
    verifie("aucun stop -> statut aucun",
            evaluer_stop({}, cours=100, cout=90, closes=plat)["statut"] == STATUT_AUCUN)

    # -- Dimensionnement -----------------------------------------------------
    d = dimensionner(capital=100000, cours=50, distance_pct=20, risque_pct=1)
    verifie("sizing montant", abs(d["montant"] - 5000) < 1e-6, str(d))
    verifie("sizing quantite", abs(d["quantite"] - 100) < 1e-6, str(d))
    verifie("sizing risque effectif", abs(d["risque_eur"] - 1000) < 1e-6, str(d))

    d = dimensionner(capital=100000, cours=50, distance_pct=2, risque_pct=1)
    verifie("sizing plafond de poids", d["montant"] == 15000 and d["bride"], str(d))

    d = dimensionner(capital=100000, cours=50, distance_pct=20, risque_pct=1,
                     liquidites=3000)
    verifie("sizing plafond liquidites", d["montant"] == 3000, str(d))

    verifie("sizing sans capital", dimensionner(None, 50, 20)["montant"] is None)
    verifie("sizing distance nulle", dimensionner(100000, 50, 0)["montant"] is None)
    verifie("sizing distance absurde", dimensionner(100000, 50, 150)["montant"] is None)

    dv = dimensionner_par_volatilite(100000, 50, 30, 2)
    verifie("sizing volatilite poids", abs(dv["poids_pct"] - (2 / 30 * 100)) < 0.01, str(dv))
    dv2 = dimensionner_par_volatilite(100000, 50, 70, 2)
    verifie("sizing volatilite differencie",
            dv2["poids_pct"] < dv["poids_pct"], f"{dv['poids_pct']} vs {dv2['poids_pct']}")
    dv3 = dimensionner_par_volatilite(100000, 50, 3, 2)
    verifie("sizing volatilite plafonne", dv3["poids_pct"] == POIDS_MAX_PCT, str(dv3))

    # -- Orchestration -------------------------------------------------------
    lignes = [
        {"cle": "AAA.US", "nom": "Alpha", "cours": 100, "cout": 80,
         "closes": plat, "ligne": {"stop": {"type": "trailing", "value": 10}}},
        {"cle": "BBB.PA", "nom": "Beta", "cours": 50, "cout": 60,
         "closes": alt, "ligne": {"stop": "vq"}},
        {"cle": "CCC.US", "nom": "Gamma", "cours": 10, "cout": 12,
         "closes": [], "ligne": {}},
    ]
    res = evaluer_portefeuille(lignes, capital=100000)
    verifie("orchestration 3 lignes", len(res["lignes"]) == 3)
    verifie("orchestration resume", res["resume"]["total"] == 3, str(res["resume"]))
    verifie("orchestration sans stop compte", res["resume"]["sans_stop"] == 1,
            str(res["resume"]))
    verifie("orchestration etat produit", len(res["etat"]["lignes"]) == 3)

    # Une ligne sous son stop ne reçoit aucune taille d'entrée.
    resf = evaluer_portefeuille([
        {"cle": "DDD", "nom": "Delta", "cours": 50, "cout": 100, "closes": alt,
         "ligne": {"stop": {"type": "percent", "value": 20}}}], capital=100000)
    lf = resf["lignes"][0]
    verifie("ligne franchie sans taille",
            lf["stop"]["statut"] == STATUT_FRANCHI and lf["taille"]["montant"] is None,
            str(lf["taille"]))

    # Deuxième passage avec l'état : le cliquet doit tenir.
    res2 = evaluer_portefeuille(lignes, etat=res["etat"], capital=100000)
    n1 = res["lignes"][0]["stop"]["niveau"]
    n2 = res2["lignes"][0]["stop"]["niveau"]
    verifie("orchestration cliquet conserve", n2 >= n1 - 1e-9, f"{n1} -> {n2}")

    # Une ligne malformée ne doit pas faire tomber le lot.
    res3 = evaluer_portefeuille([{"cle": "X", "cours": "abc", "ligne": {"stop": "vq"}}],
                                capital=100000)
    verifie("ligne malformee isolee", len(res3["lignes"]) == 1)

    # -- Persistance ---------------------------------------------------------
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        chemin = os.path.join(tmp, "sous", "stops_state.json")
        verifie("etat absent -> vierge", charger_etat(chemin)["lignes"] == {})
        verifie("sauvegarde ok", sauver_etat(chemin, res["etat"]) is True)
        relu = charger_etat(chemin)
        verifie("relecture fidele", len(relu["lignes"]) == 3, str(relu))
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("{ ceci n'est pas du json")
        verifie("fichier corrompu -> vierge", charger_etat(chemin)["lignes"] == {})

    print(f"\nrisk_engine : {ok} test(s) OK, {len(ko)} echec(s)")
    for m in ko:
        print("  ECHEC :", m)
    return 0 if not ko else 1


if __name__ == "__main__":
    import sys
    sys.exit(_autotest())
