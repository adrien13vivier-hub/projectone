"""Progression de l'apprentissage et donnees du graphique interactif (02/11/2026)."""

import json
import math
import random
from datetime import date, timedelta

import learning_engine as le
import portfolio_analyzer as pa


# -- Progression -----------------------------------------------------------------

def test_ajouter_seances_saute_week_end_et_jours_feries():
    assert le.ajouter_seances(date(2026, 10, 30), 1) == date(2026, 11, 2)      # vendredi -> lundi
    assert le.ajouter_seances(date(2026, 12, 24), 1) == date(2026, 12, 28)    # 25/12 ferme
    assert le.ajouter_seances(date(2026, 9, 25), 20) == date(2026, 10, 23)


def _jeu(n_jours=40, titres=12):
    snaps, obs = [], []
    d = date(2026, 9, 25)
    for k in range(n_jours):
        for t in range(titres):
            snaps.append({"ticker": f"T{t}", "as_of": d.isoformat(), "score_version": "v1",
                          "source": "live"})
        d = le.ajouter_seances(d, 1)
    # 20 seances plus tard, les 10 premiers jours sont clos
    for s in snaps[: 10 * titres]:
        obs.append({"horizon": 20, "ticker": s["ticker"], "as_of": s["as_of"],
                    "version": "v1", "reconstitue": False})
    return snaps, obs


def test_etapes_avancement_et_dates():
    snaps, obs = _jeu()
    pr = le.progression_apprentissage(obs, snaps, "v1", 20, date(2026, 11, 20))
    etapes = {e["cle"]: e for e in pr["etapes"]}
    assert {e["cle"] for e in pr["etapes"]} == {"premiers", "relais", "moyenne", "elevee", "modele"}
    # etapes franchies d'abord, puis les autres dans l'ordre chronologique
    restantes = [e["date_estimee"] for e in pr["etapes"] if not e["fait"] and e["date_estimee"]]
    assert restantes == sorted(restantes)
    assert pr["etapes"][0]["cle"] == "premiers"
    assert etapes["premiers"]["fait"] and etapes["premiers"]["date_estimee"] is None
    assert not etapes["relais"]["fait"]
    assert 0 < etapes["relais"]["avancement"] < 1
    assert pr["prochaine"] == next(e["cle"] for e in pr["etapes"] if not e["fait"])
    # dates estimees dans l'ordre logique
    d = {k: e["date_estimee"] for k, e in etapes.items() if e["date_estimee"]}
    assert d["moyenne"] <= d["elevee"]
    assert all(0 <= e["avancement"] <= 1 for e in pr["etapes"])


def test_notes_reconstituees_et_autres_versions_ignorees():
    snaps, obs = _jeu()
    obs_rec = [dict(o, reconstitue=True) for o in obs]
    pr = le.progression_apprentissage(obs_rec, snaps, "v1", 20, date(2026, 11, 20))
    premiers = next(e for e in pr["etapes"] if e["cle"] == "premiers")
    assert not premiers["fait"] and "séances écoulées" in premiers["detail"]
    pr2 = le.progression_apprentissage(obs, snaps, "v2", 20, date(2026, 11, 20))
    assert pr2["premiere_note"] is None and not pr2["etapes"][0]["fait"]


# -- Graphique interactif ----------------------------------------------------------

def _positions(n=4):
    random.seed(1)
    jours, d = [], date(2026, 1, 2)
    while len(jours) < 160:
        if d.weekday() < 5:
            jours.append(d)
        d += timedelta(days=1)
    pos = []
    for i in range(n):
        lvl, closes = 0.0, []
        for _ in jours:
            lvl += random.gauss(0, 0.015)
            closes.append(round(40 * math.exp(lvl), 3))
        pos.append({"nom": f"Titre {i}", "dates": [str(j) for j in jours], "closes": closes,
                    "pru": closes[60], "cours": closes[-1],
                    "calendrier": [(jours[60], 10)], "poids_pct": 10 * (i + 1)})
    return pos, jours[-1]


def test_export_json_ordre_par_poids_et_matrice_symetrique(tmp_path):
    pos, fin = _positions()
    chemin = tmp_path / "base100.json"
    assert pa.export_base100_json(pos, str(chemin), seance=fin)
    d = json.loads(chemin.read_text(encoding="utf-8"))
    assert [l["nom"] for l in d["lignes"]] == ["Titre 3", "Titre 2", "Titre 1", "Titre 0"]
    m = d["correlation"]["valeurs"]
    assert d["correlation"]["noms"] == [l["nom"] for l in d["lignes"]]
    for a in range(4):
        assert m[a][a] == 1.0
        for b in range(4):
            assert m[a][b] == m[b][a]
    assert len(d["portefeuille"]) == len(d["dates"])
