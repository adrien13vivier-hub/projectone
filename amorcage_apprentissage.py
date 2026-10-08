#!/usr/bin/env python3
"""
amorcage_apprentissage.py -- Rejoue les notes PASSEES des actions americaines
de l'univers d'apprentissage, pour que le moteur de fiabilite serve tout de
suite au lieu d'attendre un an (08/10/2026).
================================================================================

LE PRINCIPE
--------------------------------------------------------------------------------
Pour chaque action US de data/univers_apprentissage.json et chaque date passee
(toutes les 4 semaines sur ~3 ans), on recalcule la note EXACTEMENT comme le
programme l'aurait fait ce jour-la -- memes fonctions score_*, meme
note_titre(), meme version de formule -- puis on regarde ce que l'action a
fait 20, 60, 120 et 252 seances plus tard (learning_engine.compute_outcome,
la meme cloture que pour les vraies notes).

ZERO FUITE DU FUTUR (le point qui rend l'exercice honnete)
--------------------------------------------------------------------------------
* Cours : seules les seances jusqu'a la date t entrent dans la note.
* Comptes : chaque chiffre vient de la SEC avec sa DATE DE PUBLICATION ; la
  note du jour t n'utilise que ce qui etait publie AVANT t, dans sa version
  d'origine (une correction publiee plus tard n'est pas vue).
* Capitalisation : cours NON ajuste du jour t x nombre d'actions publie a
  l'epoque (sinon un split posterieur fausserait le PER d'un facteur 4 ou 10).
* Biais de selection : l'univers a ete choisi AUJOURD'HUI parmi les plus
  grosses entreprises -- donc parmi celles qui ont reussi. Leur surperformance
  passee moyenne est gonflee d'avance. On la retire : a chaque date, la
  surperformance moyenne de l'univers est ramenee a zero. Reste ce qui compte
  pour calibrer la note : l'ecart ENTRE une bonne et une mauvaise note.

CE QUI N'EST PAS RECONSTITUE (et le reste donc absent, pas invente)
--------------------------------------------------------------------------------
* L'avis des analystes (aucun historique gratuit) : critere manquant.
* PER anticipe, PEG, EV/EBITDA : demandent des previsions ou des flux de
  tresorerie trimestriels ; seuls le PER, le cours/ventes et le cours/actif
  net sont recalcules.
* L'Europe : pas de comptes dates gratuits ni plus d'un an de cours (offre
  gratuite EODHD). Une note reduite a la tendance et au risque n'aurait pas
  ete la meme note : elle aurait fausse l'etalonnage. L'Europe apprend donc
  uniquement avec les vraies notes, chaque nuit.

OU VONT LES DONNEES
--------------------------------------------------------------------------------
reports/@pool/learning/amorcage/{predictions,outcomes}.jsonl + bilan.json,
REMPLACES a chaque lancement (relancer ne cree pas de doublon). A part du
journal vivant : le moteur les lit (learning_engine.load_store(...,
avec_amorcage=True)) tant que les vraies observations ne suffisent pas, puis
les laisse de cote (RELAIS_RECONSTITUE_N). Supprimer le dossier = revenir aux
seules vraies notes ; APPRENTISSAGE_AMORCAGE=0 = les ignorer sans rien
supprimer.

SOURCES GRATUITES
--------------------------------------------------------------------------------
* TwelveData (cle TWELVEDATA_API_KEY, offre gratuite, actions US) : 2 series
  par titre (ajustee dividendes + splits, et brute) + 12 ETF de reference.
  ~265 credits sur 800/jour, a 8 par minute : ~35 minutes.
* SEC EDGAR (sans cle) : la SEC exige un User-Agent qui identifie
  l'utilisateur, idealement avec un e-mail : secret ou variable
  SEC_USER_AGENT, ex. « projectone prenom.nom@exemple.fr ».

Lancement : workflow « Amorcage de l'apprentissage » (onglet Actions), ou
    python amorcage_apprentissage.py [--annees 3] [--max-titres 5]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

import learning_engine as le
import portfolio_analyzer as pa

ANNEES_DEFAUT = 3
# Espacement des dates rejouees : l'ecart mini entre deux observations
# independantes a 20 seances (learning_engine.thin). Plus serre n'apporterait
# aucune observation independante de plus, seulement du volume.
PAS_JOURS = int(math.ceil(20 * le.CAL_DAYS_PER_SESSION))      # 28
RECUL_FIN_JOURS = 35          # derniere date rejouee : assez ancienne pour 20 seances
RECUL_DONNEES_JOURS = 380     # cours avant la 1re date : 52 semaines + beta
FENETRE_NOTE_JOURS = pa.HISTORY_DAYS                           # 180, comme en vrai
DELAI_PUBLICATION_JOURS = 1   # un compte publie le jour t n'est vu qu'a t+1
MIN_SEANCES_NOTE = 20         # meme seuil que l'univers vivant
MIN_SEANCES_BETA = 120
MIN_TITRES_CORRECTION = 10    # en dessous, pas de correction du biais a cette date
SOURCE = "reconstitue"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_PAUSE = 0.15              # la SEC tolere 10 requetes/s ; on reste tres en dessous
SEC_UA_DEFAUT = "projectone-apprentissage/1.0 (+https://github.com/adrien13vivier-hub/projectone)"
TD_REESSAIS = 3

# Concepts XBRL, du plus au moins prioritaire. Les entreprises changent de
# balise au fil des ans (Revenues -> RevenueFromContractWithCustomer... en
# 2018) : les periodes manquantes d'un concept sont completees par les autres.
CONCEPTS = {
    "revenus": ("RevenuesNetOfInterestExpense", "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet", "Revenue"),
    "resultat_net": ("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic",
                     "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"),
    "resultat_ope": ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities"),
    "actions": ("WeightedAverageNumberOfDilutedSharesOutstanding",
                "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
                "WeightedAverageNumberOfSharesOutstandingBasic",
                "AdjustedWeightedAverageShares", "WeightedAverageShares"),
    "capitaux": ("StockholdersEquity",
                 "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                 "EquityAttributableToOwnersOfParent", "Equity"),
    "actifs": ("Assets",),
}
TAXONOMIES = ("us-gaap", "ifrs-full")


class QuotaJourEpuise(Exception):
    """TwelveData a refuse pour la journee : inutile d'insister."""


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


# ─────────────────────────────────────────────────────────────────────────────
# 1. COMPTES SEC, DATES PAR PUBLICATION
# ─────────────────────────────────────────────────────────────────────────────

def extraire_faits(facts_json: dict, concepts: tuple) -> dict:
    """{"unite", "faits": [{"start", "end", "val", "filed"}]} pour un groupe de
    concepts synonymes.

    Une meme periode est republiee dans les comptes suivants (colonne de
    comparaison), parfois corrigee. On garde la PREMIERE publication : c'est
    le chiffre que le marche connaissait a l'epoque. Le concept le plus a jour
    sert de base ; les autres ne comblent que ses trous.
    """
    racine = (facts_json or {}).get("facts") or {}
    candidats = []
    for rang, nom in enumerate(concepts):
        for taxo in TAXONOMIES:
            fiche = (racine.get(taxo) or {}).get(nom)
            if not fiche:
                continue
            unites = fiche.get("units") or {}
            unite = ("USD" if "USD" in unites else "shares" if "shares" in unites
                     else next(iter(unites), None))
            par_periode = {}
            for r in unites.get(unite) or []:
                try:
                    fin, publie, val = _d(r["end"]), _d(r["filed"]), float(r["val"])
                    debut = _d(r["start"]) if r.get("start") else None
                except (KeyError, TypeError, ValueError):
                    continue
                cle = (debut, fin)
                if cle not in par_periode or publie < par_periode[cle]["filed"]:
                    par_periode[cle] = {"start": debut, "end": fin, "val": val, "filed": publie}
            if par_periode:
                candidats.append((max(f["end"] for f in par_periode.values()), -rang,
                                  unite, par_periode))
            break
    if not candidats:
        return {"unite": None, "faits": []}
    candidats.sort(key=lambda c: (c[0], c[1]), reverse=True)
    unite = candidats[0][2]
    fusion = {}
    for _, _, u, par_periode in candidats:
        if u != unite:
            continue
        for cle, f in par_periode.items():
            fusion.setdefault(cle, f)
    return {"unite": unite,
            "faits": sorted(fusion.values(), key=lambda f: (f["end"], f["filed"]))}


def _duree(f) -> int:
    return (f["end"] - f["start"]).days if f.get("start") else 0


def annuels(faits: list) -> list:
    return sorted((f for f in faits if 350 <= _duree(f) <= 380), key=lambda f: f["end"])


def trimestres(faits: list) -> list:
    """Trimestres d'un flux (chiffre d'affaires, resultat...), le 4e trimestre
    deduit des comptes annuels (le 10-K ne le publie presque jamais seul) :
    T4 = annee - (T1 + T2 + T3), connu le jour de publication du 10-K."""
    q = [f for f in faits if 80 <= _duree(f) <= 100]
    fins = [f["end"] for f in q]
    for an in annuels(faits):
        if any(abs((an["end"] - e).days) <= 5 for e in fins):
            continue
        dedans = sorted((f for f in q if f["start"] >= an["start"] - timedelta(days=5)
                         and f["end"] <= an["end"] - timedelta(days=60)),
                        key=lambda f: f["end"])
        par_fin = {}
        for f in dedans:
            par_fin.setdefault(f["end"], f)
        dedans = sorted(par_fin.values(), key=lambda f: f["end"])
        if len(dedans) != 3 or abs((dedans[0]["start"] - an["start"]).days) > 10:
            continue
        q.append({"start": dedans[-1]["end"] + timedelta(days=1), "end": an["end"],
                  "val": an["val"] - sum(f["val"] for f in dedans),
                  "filed": max([an["filed"]] + [f["filed"] for f in dedans]),
                  "deduit": True})
    par_fin = {}
    for f in sorted(q, key=lambda f: f["filed"]):
        par_fin.setdefault(f["end"], f)
    return sorted(par_fin.values(), key=lambda f: f["end"])


def cumul_12_mois(trims: list, ans: list, t: date):
    """Somme des 4 derniers trimestres CONNUS a t (consecutifs, recents), a
    defaut le dernier exercice annuel connu."""
    connus = [f for f in trims if f["filed"] <= t]
    if len(connus) >= 4:
        der = connus[-4:]
        if (t - der[-1]["end"]).days <= 200 and all(
                70 <= (b["end"] - a["end"]).days <= 110 for a, b in zip(der, der[1:])):
            return sum(f["val"] for f in der)
    an = [f for f in ans if f["filed"] <= t and (t - f["end"]).days <= 450]
    return an[-1]["val"] if an else None


def croissance_sur_un_an(trims: list, ans: list, t: date):
    """Dernier trimestre connu face au meme trimestre un an plus tot (comme
    revenueGrowth / earningsQuarterlyGrowth de Yahoo) ; a defaut, exercice
    contre exercice. None si la base est nulle ou negative."""
    connus = [f for f in trims if f["filed"] <= t]
    if connus and (t - connus[-1]["end"]).days <= 200:
        der = connus[-1]
        prec = [f for f in connus if abs((der["end"] - f["end"]).days - 365) <= 20]
        if prec:
            base = prec[-1]["val"]
            return der["val"] / base - 1 if base > 0 else None
    an = [f for f in ans if f["filed"] <= t]
    if len(an) >= 2 and (t - an[-1]["end"]).days <= 450 \
            and abs((an[-1]["end"] - an[-2]["end"]).days - 365) <= 20:
        base = an[-2]["val"]
        return an[-1]["val"] / base - 1 if base > 0 else None
    return None


def valeur_instant(faits: list, t: date, age_max: int = 450):
    """Derniere valeur de bilan (capitaux propres, actif) publiee avant t."""
    connus = [f for f in faits if f["start"] is None and f["filed"] <= t
              and (t - f["end"]).days <= age_max]
    return max(connus, key=lambda f: (f["end"], f["filed"]))["val"] if connus else None


def split_dans_comptes(comptes, depuis: date) -> bool:
    """Un split apparait-il dans les nombres d'actions publies depuis `depuis` ?
    (doublement ou division brutale d'une periode a l'autre)."""
    faits = sorted((f for f in comptes.g["actions"]["faits"] if f["end"] >= depuis),
                   key=lambda f: f["end"])
    vals = [f["val"] for f in faits if f["val"] > 0]
    return any(b / a >= 1.8 or b / a <= 0.55 for a, b in zip(vals, vals[1:]))


def nombre_actions(faits: list, t: date):
    """(nombre d'actions dilue publie avant t, date de fin de la periode)."""
    connus = [f for f in faits if f["filed"] <= t and (t - f["end"]).days <= 450]
    if not connus:
        return None, None
    f = max(connus, key=lambda f: (f["end"], -_duree(f)))
    return f["val"], f["end"]


class Comptes:
    """Comptes d'une entreprise prets a etre lus « a la date t »."""

    def __init__(self, facts_json: dict):
        self.g = {cle: extraire_faits(facts_json, c) for cle, c in CONCEPTS.items()}
        self.flux = {cle: (trimestres(self.g[cle]["faits"]), annuels(self.g[cle]["faits"]))
                     for cle in ("revenus", "resultat_net", "resultat_ope")}

    def vide(self) -> bool:
        return not any(self.g[k]["faits"] for k in ("revenus", "resultat_net", "capitaux"))

    def en_dollars(self, *cles) -> bool:
        return all(self.g[k]["unite"] in (None, "USD") for k in cles) and \
            any(self.g[k]["unite"] == "USD" for k in cles)

    def a_la_date(self, t: date, capitalisation=None) -> dict:
        """Ratios au format de get_fundamentals(), connus a la date t."""
        vu = t - timedelta(days=DELAI_PUBLICATION_JOURS)
        rev = cumul_12_mois(*self.flux["revenus"], vu)
        rn = cumul_12_mois(*self.flux["resultat_net"], vu)
        rop = cumul_12_mois(*self.flux["resultat_ope"], vu)
        cp = valeur_instant(self.g["capitaux"]["faits"], vu)
        act = valeur_instant(self.g["actifs"]["faits"], vu)
        f = {}
        if rev and rev > 0:
            if rn is not None:
                f["marge_nette"] = rn / rev
            if rop is not None:
                f["marge_ope"] = rop / rev
        if rn is not None and cp and cp > 0:
            f["roe"] = rn / cp
        if rn is not None and act and act > 0:
            f["roa"] = rn / act
        f["croiss_ca"] = croissance_sur_un_an(*self.flux["revenus"], vu)
        f["croiss_ben"] = croissance_sur_un_an(*self.flux["resultat_net"], vu)
        if capitalisation and capitalisation > 0 and self.en_dollars("revenus", "resultat_net"):
            if rn is not None and rn != 0:
                f["per"] = capitalisation / rn          # negatif = deficitaire, comme en vrai
            if rev and rev > 0:
                f["p_sales"] = capitalisation / rev
            if cp and cp > 0 and self.en_dollars("capitaux"):
                f["p_book"] = capitalisation / cp
        return {k: v for k, v in f.items() if v is not None}


# ─────────────────────────────────────────────────────────────────────────────
# 2. COURS : CE QUE LA SERIE DISAIT A LA DATE t
# ─────────────────────────────────────────────────────────────────────────────

def jusqu_a(serie, t: date, jours: int):
    """(dates, closes) de la fenetre ]t - jours ; t] -- rien d'apres t."""
    dates, closes = serie
    t_iso, d_iso = t.isoformat(), (t - timedelta(days=jours)).isoformat()
    paires = [(d, c) for d, c in zip(dates, closes) if d_iso <= d <= t_iso and c]
    return [d for d, _ in paires], [c for _, c in paires]


def beta_sur_un_an(serie, marche, t: date):
    """Beta quotidien sur un an contre le S&P 500 (SPY), connu a t."""
    if not marche:
        return None
    a = dict(zip(*jusqu_a(serie, t, 365)))
    b = dict(zip(*jusqu_a(marche, t, 365)))
    jours = sorted(set(a) & set(b))
    ra, rb = [], []
    for p, q in zip(jours, jours[1:]):
        if a[p] > 0 and b[p] > 0:
            ra.append(a[q] / a[p] - 1)
            rb.append(b[q] / b[p] - 1)
    if len(rb) < MIN_SEANCES_BETA:
        return None
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    var = sum((x - mb) ** 2 for x in rb)
    if var <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / var


def capitalisation_a(ajustee, brute, t: date, actions, fin_periode):
    """Capitalisation a t = cours AJUSTE de t x actions publiees x (cours brut /
    cours ajuste) a la fin de la periode de ces actions.

    Exact face a un split survenu n'importe quand : le facteur brut/ajuste a
    la date des actions remet le cours ajuste de t dans la meme « unite »
    d'action que le nombre publie. (Le seul ecart residuel est le dividende
    verse entre ces deux dates : moins de 1 %.)
    """
    if not actions or actions <= 0 or not brute or not brute[0] or not fin_periode:
        return None
    p_t = le.value_on_or_before(ajustee[0], ajustee[1], t)
    b_f = le.value_on_or_before(brute[0], brute[1], fin_periode, max_gap=7)
    a_f = le.value_on_or_before(ajustee[0], ajustee[1], fin_periode, max_gap=7)
    if not p_t or not b_f or not a_f or a_f <= 0:
        return None
    return p_t * actions * (b_f / a_f)


def fondamentaux_a(comptes, ajustee, brute, marche, t: date) -> dict:
    f = {}
    if comptes is not None and not comptes.vide():
        n, fin = nombre_actions(comptes.g["actions"]["faits"],
                                t - timedelta(days=DELAI_PUBLICATION_JOURS))
        f.update(comptes.a_la_date(t, capitalisation_a(ajustee, brute, t, n, fin)))
    d_an, c_an = jusqu_a(ajustee, t, 365)
    if len(c_an) >= 200:                  # un canal 52 semaines sur moins d'un an n'en est pas un
        f["haut_52s"], f["bas_52s"] = max(c_an), min(c_an)
    b = beta_sur_un_an(ajustee, marche, t)
    if b is not None:
        f["beta"] = b
    return f


def noter_a(ajustee, brute, marche, comptes, t: date):
    """(note, confiance, detail, motif) -- meme calcul que main() / l'univers."""
    h_dates, h_closes = jusqu_a(ajustee, t, FENETRE_NOTE_JOURS)
    if len(h_closes) < MIN_SEANCES_NOTE:
        return None, None, None, "historique trop court"
    fonda = fondamentaux_a(comptes, ajustee, brute, marche, t)
    sc_hist = pa.score_history(h_dates, h_closes)[0]
    composantes = {
        "valorisation": pa.score_valorisation(fonda),
        "sante":        pa.score_sante(fonda),
        "croissance":   pa.score_croissance(fonda),
        "momentum":     sc_hist,
        "consensus":    None,          # aucun historique gratuit des avis d'analystes
        "risque":       pa.score_risque(fonda, h_dates, h_closes, 1.0),
    }
    if all(composantes[k] is None for k in ("valorisation", "sante", "croissance")):
        return None, None, None, "comptes indisponibles a cette date"
    note, confiance, detail, _na, _manq = pa.note_titre(composantes, "action")
    if note is None:
        return None, None, None, "note incalculable"
    return note, confiance, detail, None


# ─────────────────────────────────────────────────────────────────────────────
# 3. RECONSTITUTION D'UN TITRE, PUIS DE L'UNIVERS
# ─────────────────────────────────────────────────────────────────────────────

def dates_a_rejouer(seance: date, annees: int) -> list:
    """Une date toutes les PAS_JOURS, de la plus ancienne a la plus recente,
    toutes un jour ouvre (28 jours = 4 semaines : le jour de semaine ne change pas)."""
    fin = seance - timedelta(days=RECUL_FIN_JOURS)
    while fin.weekday() >= 5:
        fin -= timedelta(days=1)
    debut = seance - timedelta(days=int(annees * 365.25))
    dates, d = [], fin
    while d >= debut:
        dates.append(d)
        d -= timedelta(days=PAS_JOURS)
    return sorted(dates)


def reconstituer_titre(asset: dict, ajustee, brute, refs: dict, comptes, dates: list,
                       config: dict, aujourdhui: date, horizons) -> tuple:
    """(snapshots, outcomes, motifs) pour un titre. `refs` : {symbole EODHD:
    serie ajustee} (SPY.US, XLK.US...)."""
    snaps, outs, motifs = [], [], {}
    marche = refs.get("SPY.US")
    for t in dates:
        if le.session_index(ajustee[0], t) is None:
            motifs["pas de cotation a cette date"] = motifs.get("pas de cotation a cette date", 0) + 1
            continue
        note, confiance, detail, motif = noter_a(ajustee, brute, marche, comptes, t)
        if motif:
            motifs[motif] = motifs.get(motif, 0) + 1
            continue
        snap = le.build_snapshot(
            le.POOL_USER, asset["ticker_eod"], asset["name"], t, note, confiance, detail,
            pa.SCORE_VERSION, "action", asset.get("sector", ""), "", config,
            price=le.value_on_or_before(ajustee[0], ajustee[1], t), source=SOURCE,
            devise="USD")
        clos = []
        for h in horizons:
            res = le.compute_outcome(snap, h, ajustee, refs.get(snap.get("sector_ref")),
                                     refs.get(snap.get("market_ref")), aujourdhui)
            if res is not None:
                clos.append(res)
        if any(o["status"] == "matured" for o in clos):
            snaps.append(snap)
            outs.extend(clos)
    return snaps, outs, motifs


def corriger_biais_selection(outs: list) -> dict:
    """Ramene a zero, date par date et horizon par horizon, la surperformance
    MOYENNE de l'univers rejoue (voir l'en-tete). Les valeurs d'origine restent
    lisibles dans *_brut_pct. Renvoie la correction moyenne par horizon."""
    groupes = {}
    for o in outs:
        if o.get("status") == "matured":
            groupes.setdefault((o["horizon"], o["as_of"]), []).append(o)
    corrections = {}
    for (h, _jour), grp in groupes.items():
        for cle in ("sector_excess_pct", "market_excess_pct"):
            vals = [o[cle] for o in grp if o.get(cle) is not None]
            if len(vals) < MIN_TITRES_CORRECTION:
                continue
            m = sum(vals) / len(vals)
            for o in grp:
                if o.get(cle) is not None:
                    o[cle.replace("_pct", "_brut_pct")] = o[cle]
                    o[cle] = round(o[cle] - m, 4)
            corrections.setdefault(f"{h}:{cle}", []).append(m)
    return {k: round(sum(v) / len(v), 2) for k, v in sorted(corrections.items())}


def ecrire_amorcage(dossier: str, snaps: list, outs: list, bilan: dict) -> None:
    """Remplace le contenu du dossier (ecriture atomique, fichier par fichier)."""
    os.makedirs(dossier, exist_ok=True)
    for nom, lignes in (("predictions.jsonl", snaps), ("outcomes.jsonl", outs)):
        chemin = os.path.join(dossier, nom)
        with open(chemin + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            for r in lignes:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")) + "\n")
        os.replace(chemin + ".tmp", chemin)
    with open(os.path.join(dossier, "bilan.json.tmp"), "w", encoding="utf-8") as f:
        json.dump(bilan, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(os.path.join(dossier, "bilan.json.tmp"), os.path.join(dossier, "bilan.json"))


# ─────────────────────────────────────────────────────────────────────────────
# 4. TELECHARGEMENTS
# ─────────────────────────────────────────────────────────────────────────────

def td_serie(symbole: str, debut: date, ajustement: str, cle: str, compteur: dict):
    """((dates, closes) croissants, None) ou (None, motif). Ajustement :
    'all' (dividendes + splits, pour les rendements) ou 'none' (brut)."""
    params = {"symbol": symbole, "interval": "1day", "start_date": debut.isoformat(),
              "outputsize": 5000, "adjust": ajustement, "apikey": cle}
    motif = "echec"
    for _ in range(TD_REESSAIS):
        pa._attendre_debit("twelvedata")
        compteur["twelvedata"] = compteur.get("twelvedata", 0) + 1
        try:
            r = requests.get(f"{pa.TD_BASE}/time_series", params=params, timeout=40)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            motif = type(e).__name__
            time.sleep(5)
            continue
        if r.status_code == 429 or str(data.get("code")) == "429":
            message = str(data.get("message") or "").lower()
            if "day" in message or "daily" in message:
                raise QuotaJourEpuise(data.get("message"))
            motif = "limite par minute"
            time.sleep(65)
            continue
        if data.get("status") != "ok":
            return None, str(data.get("message") or data.get("code") or f"HTTP {r.status_code}")[:140]
        paires = []
        for v in data.get("values") or []:
            try:
                c = float(v["close"])
            except (KeyError, TypeError, ValueError):
                continue
            if c > 0:
                paires.append((str(v["datetime"])[:10], c))
        paires.sort()
        if len(paires) < 2:
            return None, "serie vide"
        return ([d for d, _ in paires], [c for _, c in paires]), None
    return None, motif


def sec_get(url: str, ua: str, compteur: dict):
    time.sleep(SEC_PAUSE)
    compteur["sec"] = compteur.get("sec", 0) + 1
    try:
        r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
                         timeout=90)
    except requests.RequestException as e:
        return None, type(e).__name__
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        return r.json(), None
    except ValueError:
        return None, "reponse illisible"


def table_cik(ua: str, compteur: dict) -> tuple:
    data, err = sec_get(SEC_TICKERS_URL, ua, compteur)
    if not isinstance(data, dict):
        return {}, err or "vide"
    table = {}
    for v in data.values():
        try:
            table[str(v["ticker"]).upper()] = int(v["cik_str"])
        except (KeyError, TypeError, ValueError):
            continue
    return table, None


# ─────────────────────────────────────────────────────────────────────────────
# 5. ORCHESTRATION
# ─────────────────────────────────────────────────────────────────────────────

def lancer(annees: int = ANNEES_DEFAUT, max_titres: int = 0, dossier: str = None,
           telecharger_cours=None, telecharger_comptes=None, aujourdhui: date = None) -> dict:
    """Reconstitue et ecrit. Les deux fonctions de telechargement sont
    injectables (tests) : telecharger_cours(symbole, debut, ajustement) ->
    (serie|None, motif) ; telecharger_comptes(ticker) -> (facts_json|None, motif)."""
    aujourdhui = aujourdhui or date.fromisoformat(pa.date_seance(datetime.now(pa.PARIS_TZ)))
    dossier = dossier or os.path.join(le.pool_dir(), le.AMORCAGE_DIRNAME)
    compteur = {}
    bilan = {"genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "seance": aujourdhui.isoformat(), "score_version": pa.SCORE_VERSION,
             "annees": annees, "ecartes": [], "sans_comptes": [], "motifs_dates": {}}

    if telecharger_cours is None:
        cle = os.getenv("TWELVEDATA_API_KEY", "")
        if not cle:
            raise SystemExit("TWELVEDATA_API_KEY absente : rien a telecharger.")

        def telecharger_cours(symbole, debut, ajustement):
            return td_serie(symbole, debut, ajustement, cle, compteur)
    if telecharger_comptes is None:
        ua = (os.getenv("SEC_USER_AGENT") or "").strip() or SEC_UA_DEFAUT
        table, err = table_cik(ua, compteur)
        bilan["sec_user_agent_defaut"] = ua == SEC_UA_DEFAUT
        if not table:
            # Sans comptes, aucune note ne peut etre rejouee : on s'arrete AVANT
            # de depenser le moindre credit TwelveData.
            bilan["interrompu"] = (f"SEC injoignable ({err}) : renseigne le secret "
                                   f"SEC_USER_AGENT (ex. « projectone ton.email@exemple.fr ») "
                                   f"puis relance")
            print(f"⛔ {bilan['interrompu']}")
            bilan.update({"snapshots": 0, "appels": compteur})
            return bilan

        def telecharger_comptes(ticker):
            cik = table.get(ticker.upper().replace(".", "-"))
            if not cik:
                return None, "absent de la table SEC"
            return sec_get(SEC_FACTS_URL.format(cik=cik), ua, compteur)

    titres, _pas = pa.charger_univers()
    us = [a for a in titres if a["ticker_eod"].endswith(".US")]
    if max_titres:
        us = us[:max_titres]
    dates = dates_a_rejouer(aujourdhui, annees)
    debut_donnees = dates[0] - timedelta(days=RECUL_DONNEES_JOURS)
    config = le.load_config()
    horizons = le.normalize_settings(None)["horizons"]
    bilan.update({"periode": [dates[0].isoformat(), dates[-1].isoformat()],
                  "dates_rejouees": len(dates), "titres_us": len(us),
                  "horizons": horizons})

    def cours_ajustes(symbole):
        """Dividendes + splits ; si l'offre refuse l'option, splits seuls (le
        reglage par defaut de TwelveData) plutot que rien."""
        serie, err = telecharger_cours(symbole, debut_donnees, "all")
        if not serie:
            serie, err2 = telecharger_cours(symbole, debut_donnees, "splits")
            err = err if serie is None else None
            if serie:
                bilan.setdefault("sans_dividendes", []).append(symbole)
        return serie, err

    refs = {}
    besoins = {"SPY.US"} | {le.resolve_refs(a["ticker_eod"], a.get("sector", ""), config)
                             .get("sector_ref") for a in us}
    tous_snaps, tous_outs, notes_ok = [], [], 0
    try:
        for sym in sorted(s for s in besoins if s):
            serie, err = cours_ajustes(sym.split(".")[0])
            if serie:
                refs[sym] = serie
            else:
                bilan["ecartes"].append([sym, f"reference indisponible : {err}"])
        for i, a in enumerate(us, 1):
            ajustee, err = cours_ajustes(a["ticker_td"])
            if not ajustee:
                bilan["ecartes"].append([a["ticker_eod"], f"cours : {err}"])
                continue
            brute, err_b = telecharger_cours(a["ticker_td"], debut_donnees, "none")
            facts, err_c = telecharger_comptes(a["ticker_td"])
            comptes = Comptes(facts) if isinstance(facts, dict) else None
            # Garde-fou : si le cours « brut » est identique au cours ajuste
            # alors que les comptes montrent un split, l'option d'ajustement
            # n'a pas ete appliquee -- la capitalisation serait fausse d'un
            # facteur 2 a 20. On renonce alors au PER plutot que de le fausser.
            if brute and comptes and brute[1] == ajustee[1] \
                    and split_dans_comptes(comptes, debut_donnees):
                brute, err_b = None, "cours brut non fourni (split detecte)"
            if comptes is None or comptes.vide():
                bilan["sans_comptes"].append([a["ticker_eod"], err_c or "aucun compte exploitable"])
            snaps, outs, motifs = reconstituer_titre(a, ajustee, brute, refs, comptes, dates,
                                                     config, aujourdhui, horizons)
            for m, n in motifs.items():
                bilan["motifs_dates"][m] = bilan["motifs_dates"].get(m, 0) + n
            if not snaps:
                bilan["ecartes"].append([a["ticker_eod"], "aucune note rejouable"])
            tous_snaps += snaps
            tous_outs += outs
            notes_ok += bool(snaps)
            print(f"[{i}/{len(us)}] {a['ticker_eod']:<9} {len(snaps):>3} note(s)"
                  + ("" if brute else f"  (cours brut : {err_b} -> sans PER)")
                  + ("" if comptes and not comptes.vide() else f"  (comptes : {err_c})"),
                  flush=True)
    except QuotaJourEpuise as e:
        bilan["interrompu"] = f"quota TwelveData du jour epuise : {e}"
        print(f"⛔ {bilan['interrompu']} -- ce qui est fait est garde ; relancer demain "
              f"refait tout proprement.")

    bilan["correction_selection_moyenne_pct"] = corriger_biais_selection(tous_outs)
    par_h = {}
    for o in tous_outs:
        if o.get("status") == "matured":
            par_h[str(o["horizon"])] = par_h.get(str(o["horizon"]), 0) + 1
    bilan.update({"titres_notes": notes_ok, "snapshots": len(tous_snaps),
                  "observations_par_horizon": par_h, "appels": compteur})
    ecrire_amorcage(dossier, tous_snaps, tous_outs, bilan)
    return bilan


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Rejoue les notes passees de l'univers US.")
    ap.add_argument("--annees", type=int, default=ANNEES_DEFAUT)
    ap.add_argument("--max-titres", type=int, default=0,
                    help="Limiter a N titres (essai rapide). 0 = tous.")
    args = ap.parse_args()
    bilan = lancer(annees=max(1, args.annees), max_titres=max(0, args.max_titres))
    print(json.dumps({k: bilan[k] for k in ("periode", "titres_us", "titres_notes",
                                             "snapshots", "observations_par_horizon",
                                             "correction_selection_moyenne_pct", "appels")
                      if k in bilan}, ensure_ascii=False, indent=1))
    if bilan.get("ecartes"):
        print(f"Ecartes ({len(bilan['ecartes'])}) :")
        for t, m in bilan["ecartes"]:
            print(f"  - {t} : {m}")
    if bilan.get("sans_comptes"):
        print(f"Sans comptes SEC ({len(bilan['sans_comptes'])}) :")
        for t, m in bilan["sans_comptes"]:
            print(f"  - {t} : {m}")
    return 0 if bilan["snapshots"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
