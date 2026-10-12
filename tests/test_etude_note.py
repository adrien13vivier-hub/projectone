"""Etude hors ligne des criteres de la note (11/10/2026)."""

import random

import etude_note as e


def test_rangs_ex_aequo():
    assert e.rangs([10, 20, 20, 30]) == [0.0, 1.5, 1.5, 3.0]


def test_spearman_monotone():
    assert abs(e.spearman([1, 2, 3, 4], [10, 40, 90, 160]) - 1.0) < 1e-12
    assert abs(e.spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-12


def _donnees(n_dates=12, n_titres=30, graine=1, lien=1.0):
    """La croissance annonce la surperformance (lien > 0), le reste est du bruit."""
    rng = random.Random(graine)
    snaps, outs = [], []
    for d in range(n_dates):
        jour = f"2024-{(d % 12) + 1:02d}-0{(d // 12) + 1}"
        for t in range(n_titres):
            sid = f"{d}-{t}"
            c = rng.uniform(0, 10)
            snaps.append({"id": sid, "as_of": jour, "score": 5.0,
                          "sector": "A" if t % 2 else "B",
                          "subscores": {"croissance": c, "sante": rng.uniform(0, 10),
                                        "valorisation": rng.uniform(0, 10),
                                        "momentum": rng.uniform(0, 10),
                                        "risque": rng.uniform(0, 10)}})
            outs.append({"id": sid, "horizon": 20, "status": "matured",
                         "sector_excess_pct": lien * c + rng.gauss(0, 3)})
    return snaps, outs


def test_le_critere_qui_annonce_la_suite_ressort():
    snaps, outs = _donnees()
    r = e.etudier(snaps, outs, horizons=(20,))[20]
    assert r["criteres"]["croissance"]["ic"] > 0.5
    assert abs(r["criteres"]["sante"]["ic"]) < 0.2
    appris = r["variantes"]["Poids appris (1re moitie)"]
    assert "croissance" in appris["poids"] and appris["test"]["ic"] > 0.5


def test_relatif_secteur_classe_dans_le_secteur():
    coupe = [({"sector": "A", "subscores": {"croissance": v}}, 0.0) for v in (1, 2, 3)] + \
            [({"sector": "B", "subscores": {"croissance": v}}, 0.0) for v in (100, 200, 300)]
    rel = e.transformer(coupe, "croissance", True)
    assert rel[:3] == rel[3:] == [-0.5, 0.0, 0.5]
