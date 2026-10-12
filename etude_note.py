#!/usr/bin/env python3
"""
etude_note.py -- Quels criteres de la note annoncent vraiment la suite ?
================================================================================

Etude HORS LIGNE (aucun appel reseau) sur les notes reconstituees par
amorcage_apprentissage.py (reports/@pool/learning/amorcage/). Elle ne modifie
rien : elle mesure, puis imprime un rapport.

LA MESURE : L'IC PAR DATE
--------------------------------------------------------------------------------
A chaque date, on classe les titres selon un critere et selon leur
surperformance future face a leur secteur, puis on calcule la correlation de
rang entre les deux classements (IC de Spearman). Un IC de +0,05 tenu dans la
duree est deja un bon signal en gestion quantitative ; 0 = aucun pouvoir de
classement. On compare les titres A LA MEME DATE : le climat de marche et le
biais de selection de l'univers (constants a une date donnee) ne comptent pas.

  * t de Student : calcule sur des dates NON chevauchantes (une date toutes
    les ~H seances), sinon on compterait plusieurs fois la meme periode.
  * Ecart Q5-Q1 : surperformance moyenne du meilleur cinquieme moins celle du
    plus mauvais, en points de pourcentage.

LE TEST HORS ECHANTILLON
--------------------------------------------------------------------------------
Les dates sont coupees en deux, dans l'ordre chronologique. Les ponderations
« apprises » ne voient QUE la premiere moitie ; elles sont jugees sur la
seconde, qu'elles n'ont jamais vue. Seul ce chiffre-la compte.

LIMITES (a garder en tete en lisant les resultats)
--------------------------------------------------------------------------------
* Notes reconstituees : sans avis des analystes, sans PER anticipe, PEG ni
  EV/EBITDA ; actions americaines seulement ; 3 ans = peu de climats de marche.
* Un critere « relatif au secteur » est ici le RANG du critere parmi les
  titres du meme secteur a la meme date (approximation de ratios relatifs).

Usage : python etude_note.py [--dossier reports/@pool/learning/amorcage]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict

CRITERES = ("valorisation", "sante", "croissance", "momentum", "risque")
# Poids actuels de POIDS_NOTE, sans l'avis des analystes (absent des notes
# reconstituees) -- renormalises comme le fait note_titre().
POIDS_ACTUELS = {"valorisation": 0.24, "sante": 0.19, "croissance": 0.16,
                 "momentum": 0.21, "risque": 0.05}
HORIZONS = (20, 60, 120)
JOURS_PAR_SEANCE = 1.4
PAS_DATES_JOURS = 28


# ─────────────────────────────────────────────────────────────────────────────
# OUTILS
# ─────────────────────────────────────────────────────────────────────────────

def lire_jsonl(chemin: str) -> list:
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def rangs(valeurs: list) -> list:
    """Rangs moyens (les ex aequo partagent le meme rang)."""
    ordre = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    r = [0.0] * len(valeurs)
    i = 0
    while i < len(ordre):
        j = i
        while j + 1 < len(ordre) and valeurs[ordre[j + 1]] == valeurs[ordre[i]]:
            j += 1
        moyen = (i + j) / 2.0
        for k in range(i, j + 1):
            r[ordre[k]] = moyen
        i = j + 1
    return r


def pearson(x: list, y: list):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def spearman(x: list, y: list):
    return pearson(rangs(x), rangs(y))


def moyenne(v: list):
    return sum(v) / len(v) if v else None


def ecart_type(v: list):
    if len(v) < 2:
        return None
    m = moyenne(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))


# ─────────────────────────────────────────────────────────────────────────────
# DONNEES
# ─────────────────────────────────────────────────────────────────────────────

def coupes_par_date(snaps: list, outs: list, horizon: int,
                    cible: str = "sector_excess_pct") -> dict:
    """{date: [(snapshot, surperformance)]} pour un horizon."""
    par_id = {s["id"]: s for s in snaps}
    coupes = defaultdict(list)
    for o in outs:
        if o.get("horizon") != horizon or o.get("status") != "matured":
            continue
        s = par_id.get(o["id"])
        y = o.get(cible)
        if s is None or y is None:
            continue
        coupes[s["as_of"]].append((s, float(y)))
    return dict(sorted(coupes.items()))


def valeur_brute(s: dict, nom: str):
    if nom == "note":
        return s.get("score")
    return (s.get("subscores") or {}).get(nom)


def transformer(coupe: list, nom: str, relatif_secteur: bool) -> list:
    """Valeur du critere pour chaque titre de la coupe, en rang centre
    (-0,5 .. +0,5) sur toute la date ou a l'interieur du secteur. None si
    absent."""
    sortie = [None] * len(coupe)
    groupes = defaultdict(list)
    for i, (s, _y) in enumerate(coupe):
        v = valeur_brute(s, nom)
        if v is None:
            continue
        cle = s.get("sector") if relatif_secteur else "_tous"
        groupes[cle].append((i, float(v)))
    for membres in groupes.values():
        if len(membres) < 3:
            continue
        r = rangs([v for _, v in membres])
        n = len(membres)
        for (i, _v), rang in zip(membres, r):
            sortie[i] = rang / (n - 1) - 0.5
    return sortie


def score_composite(coupe: list, poids: dict, relatif_secteur: bool) -> list:
    """Somme ponderee des criteres (en rangs centres) ; un critere absent
    sort du calcul de la ligne, comme dans note_titre()."""
    par_critere = {k: transformer(coupe, k, relatif_secteur) for k in poids}
    sortie = []
    for i in range(len(coupe)):
        num = den = 0.0
        for k, w in poids.items():
            v = par_critere[k][i]
            if v is None or w == 0:
                continue
            num += w * v
            den += abs(w)
        sortie.append(num / den if den > 0 else None)
    return sortie


# ─────────────────────────────────────────────────────────────────────────────
# MESURES
# ─────────────────────────────────────────────────────────────────────────────

def ic_par_date(coupes: dict, fabrique) -> list:
    """[(date, IC, ecart Q5-Q1)] -- `fabrique(coupe)` rend une valeur par titre."""
    sortie = []
    for jour, coupe in coupes.items():
        x = fabrique(coupe)
        paires = [(a, y) for a, (_s, y) in zip(x, coupe) if a is not None]
        if len(paires) < 15:
            continue
        ic = spearman([a for a, _ in paires], [y for _, y in paires])
        tri = sorted(paires)
        q = max(1, len(tri) // 5)
        ecart = moyenne([y for _, y in tri[-q:]]) - moyenne([y for _, y in tri[:q]])
        if ic is not None:
            sortie.append((jour, ic, ecart))
    return sortie


def resume(serie: list, horizon: int) -> dict:
    """IC moyen, t sur dates non chevauchantes, % de dates positives, Q5-Q1."""
    if not serie:
        return {"n": 0}
    pas = max(1, math.ceil(horizon * JOURS_PAR_SEANCE / PAS_DATES_JOURS))
    indep = [ic for k, (_j, ic, _e) in enumerate(serie) if k % pas == 0]
    m_ind, sd = moyenne(indep), ecart_type(indep)
    t = (m_ind / (sd / math.sqrt(len(indep)))) if sd else None
    return {"n": len(serie), "n_indep": len(indep),
            "ic": moyenne([ic for _j, ic, _e in serie]),
            "t": t,
            "pos": sum(1 for _j, ic, _e in serie if ic > 0) / len(serie),
            "q5q1": moyenne([e for _j, _ic, e in serie])}


def poids_appris(coupes_train: dict, relatif_secteur: bool, horizon: int) -> dict:
    """Poids proportionnels a l'IC moyen de chaque critere SUR LA SEULE
    periode d'apprentissage (signe compris : un critere qui a joue a
    l'envers est retourne). Les criteres dont le t est inferieur a 1 en
    valeur absolue sont ecartes -- trop proches du bruit."""
    poids = {}
    for k in CRITERES:
        r = resume(ic_par_date(coupes_train,
                               lambda c, k=k: transformer(c, k, relatif_secteur)), horizon)
        if r.get("t") is not None and abs(r["t"]) >= 1.0:
            poids[k] = r["ic"]
    return poids


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT
# ─────────────────────────────────────────────────────────────────────────────

def _f(v, fmt="{:+.3f}"):
    return "—" if v is None else fmt.format(v)


def etudier(snaps: list, outs: list, horizons=HORIZONS) -> dict:
    resultats = {}
    for h in horizons:
        coupes = coupes_par_date(snaps, outs, h)
        dates = list(coupes)
        moitie = len(dates) // 2
        train = {d: coupes[d] for d in dates[:moitie]}
        test = {d: coupes[d] for d in dates[moitie:]}
        bloc = {"dates": len(dates), "coupure": dates[moitie] if dates else None,
                "criteres": {}, "variantes": {}}
        for nom in ("note",) + CRITERES:
            for rel in (False, True):
                if nom == "note" and rel:
                    continue
                cle = nom + (" (relatif secteur)" if rel else "")
                bloc["criteres"][cle] = resume(ic_par_date(
                    coupes, lambda c, n=nom, r=rel: transformer(c, n, r)), h)
        variantes = {
            "Poids actuels": (POIDS_ACTUELS, False),
            "Poids actuels, relatif secteur": (POIDS_ACTUELS, True),
            "Poids appris (1re moitie)": (poids_appris(train, False, h), False),
            "Poids appris, relatif secteur": (poids_appris(train, True, h), True),
        }
        for nom, (poids, rel) in variantes.items():
            if not poids:
                bloc["variantes"][nom] = {"poids": {}, "train": {"n": 0}, "test": {"n": 0}}
                continue
            fab = lambda c, p=poids, r=rel: score_composite(c, p, r)
            bloc["variantes"][nom] = {
                "poids": {k: round(v, 4) for k, v in poids.items()},
                "train": resume(ic_par_date(train, fab), h),
                "test": resume(ic_par_date(test, fab), h),
            }
        resultats[h] = bloc
    return resultats


def imprimer(resultats: dict, n_snaps: int) -> str:
    lignes = [f"# Etude de la note -- {n_snaps} notes reconstituees", ""]
    for h, b in resultats.items():
        lignes += [f"## Horizon {h} seances ({b['dates']} dates, coupure test : {b['coupure']})",
                   "", "| Critere | IC moyen | t (dates indep.) | % dates IC>0 | Q5-Q1 (pts) |",
                   "|---|---|---|---|---|"]
        for nom, r in b["criteres"].items():
            lignes.append(f"| {nom} | {_f(r.get('ic'))} | {_f(r.get('t'), '{:+.1f}')} "
                          f"| {_f(r.get('pos'), '{:.0%}')} | {_f(r.get('q5q1'), '{:+.2f}')} |")
        lignes += ["", "| Variante | Poids | IC 1re moitie | IC 2nde moitie (hors echantillon) "
                   "| t 2nde moitie | Q5-Q1 2nde moitie |", "|---|---|---|---|---|---|"]
        for nom, v in b["variantes"].items():
            p = ", ".join(f"{k} {w:+.3f}" for k, w in v["poids"].items()) or "aucun critere retenu"
            lignes.append(f"| {nom} | {p} | {_f(v['train'].get('ic'))} | {_f(v['test'].get('ic'))} "
                          f"| {_f(v['test'].get('t'), '{:+.1f}')} | {_f(v['test'].get('q5q1'), '{:+.2f}')} |")
        lignes.append("")
    return "\n".join(lignes)


def main() -> int:
    ap = argparse.ArgumentParser(description="Etude hors ligne des criteres de la note.")
    ap.add_argument("--dossier", default=os.path.join("reports", "@pool", "learning", "amorcage"))
    args = ap.parse_args()
    snaps = lire_jsonl(os.path.join(args.dossier, "predictions.jsonl"))
    outs = lire_jsonl(os.path.join(args.dossier, "outcomes.jsonl"))
    print(imprimer(etudier(snaps, outs), len(snaps)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
