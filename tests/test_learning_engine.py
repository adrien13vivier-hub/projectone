"""Tests de learning_engine.py -- dates, rendements, ABSENCE DE FUITE, petits
echantillons, immuabilite du journal et activation conditionnelle du modele.

Aucun reseau : les cours sont synthetiques et injectes par une fausse
fonction `fetch`. Les series sont deterministes (graine fixe).
"""
import json
import os
import random
from datetime import date, timedelta

import pytest

import learning_engine as le


# ─────────────────────────────────────────────────────────────────────────
# Outils de test
# ─────────────────────────────────────────────────────────────────────────

def seances(debut="2026-01-05", n=300):
    """n jours ouvres (lun-ven) a partir de `debut`."""
    d = date.fromisoformat(debut)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def serie_lineaire(debut="2026-01-05", n=300, p0=100.0, pas=1.0):
    ds = seances(debut, n)
    return ds, [round(p0 + pas * i, 4) for i in range(n)]


def snap(ticker="AAA.US", as_of="2026-01-12", score=8.0, version="v1",
         sector="Technology", sub=None, user="u"):
    cfg = le.load_config("inexistant.json")
    return le.build_snapshot(user, ticker, ticker, as_of, score, 90.0,
                             sub if sub is not None else {"momentum": 8.0},
                             version, "action", sector, "", cfg, price=100.0)


@pytest.fixture
def ldir(tmp_path):
    return str(tmp_path / "learning")


# ─────────────────────────────────────────────────────────────────────────
# Journal immuable
# ─────────────────────────────────────────────────────────────────────────

def test_id_est_deterministe_et_depend_de_la_version():
    a = le.prediction_id("u", "AAA.US", "2026-01-12", "v1")
    assert a == le.prediction_id("u", "AAA.US", "2026-01-12", "v1")
    assert a != le.prediction_id("u", "AAA.US", "2026-01-12", "v2")
    assert a != le.prediction_id("u", "AAA.US", "2026-01-13", "v1")


def test_relancer_le_meme_soir_ne_cree_rien(ldir):
    assert le.record_snapshots(ldir, [snap()])["nouveaux"] == 1
    bilan = le.record_snapshots(ldir, [snap()])
    assert bilan == {"nouveaux": 0, "ignores": 1}
    assert len(le.load_store(ldir)["snapshots"]) == 1


def test_un_snapshot_existant_ne_peut_pas_etre_reecrit(ldir):
    le.record_snapshots(ldir, [snap(score=8.0)])
    le.record_snapshots(ldir, [snap(score=2.0)])     # meme id, autre note
    assert le.load_store(ldir)["snapshots"][0]["score"] == 8.0


def test_ligne_corrompue_ignoree_et_comptee(ldir):
    le.record_snapshots(ldir, [snap()])
    with open(os.path.join(ldir, "predictions.jsonl"), "a", encoding="utf-8") as f:
        f.write("{pas du json\n")
    st = le.load_store(ldir)
    assert len(st["snapshots"]) == 1 and st["corrompus"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Seances et echeances
# ─────────────────────────────────────────────────────────────────────────

def test_session_index_exact_avant_et_ecart_trop_grand():
    ds = ["2026-01-05", "2026-01-06", "2026-01-09"]
    assert le.session_index(ds, "2026-01-06") == 1
    assert le.session_index(ds, "2026-01-08") == 1      # samedi/jeudi ferie : veille
    assert le.session_index(ds, "2026-01-04") is None   # avant la serie
    assert le.session_index(ds, "2026-02-01") is None   # > 5 jours apres la derniere


def test_horizon_compte_en_seances_et_non_en_jours_calendaires():
    ds, cl = serie_lineaire(n=100)
    s = snap(as_of=ds[10])
    o = le.compute_outcome(s, 20, (ds, cl), None, None, "2027-01-01")
    assert o["session_t"] == ds[10] and o["session_t_h"] == ds[30]   # 20 seances


def test_rendement_brut_et_surperformance_vs_reference():
    ds, cl = serie_lineaire(n=100, p0=100, pas=1)              # 110 -> 130 : +18,18 %
    _, ref = serie_lineaire(n=100, p0=100, pas=0.5)            # 105 -> 115 : +9,52 %
    s = snap(as_of=ds[10])
    s["sector_ref"] = "XLK.US"
    s["market_ref"] = "SPY.US"
    o = le.compute_outcome(s, 20, (ds, cl), (ds, ref), (ds, ref), "2027-01-01")
    assert o["status"] == "matured"
    assert o["stock_return_pct"] == pytest.approx(18.1818, abs=1e-3)
    assert o["sector_excess_pct"] == pytest.approx(18.1818 - 9.5238, abs=1e-3)
    assert o["market_excess_pct"] == o["sector_excess_pct"]


def test_echeance_non_atteinte_reste_pending():
    ds, cl = serie_lineaire(n=25)
    s = snap(as_of=ds[10])
    assert le.compute_outcome(s, 20, (ds, cl), None, None, ds[-1]) is None


def test_ANTI_FUITE_le_cours_apres_lecheance_n_entre_pas_dans_le_calcul():
    ds, cl = serie_lineaire(n=100)
    s = snap(as_of=ds[10])
    ref = le.compute_outcome(s, 20, (ds, cl), None, None, "2027-01-01")
    cl2 = list(cl)
    for k in range(31, len(cl2)):           # on saccage TOUT ce qui suit t + H
        cl2[k] = 9999.0
    apres = le.compute_outcome(s, 20, (ds, cl2), None, None, "2027-01-01")
    assert apres["stock_return_pct"] == ref["stock_return_pct"]


def test_titre_disparu_cloture_sur_le_dernier_cours_sans_biais_de_survivance():
    ds, cl = serie_lineaire(n=20)                      # la serie s'arrete
    s = snap(as_of=ds[5])
    o = le.compute_outcome(s, 60, (ds, cl), None, None, "2027-06-01")
    assert o["status"] == "matured" and o["delisted_proxy"] is True
    assert o["session_t_h"] == ds[-1]


def test_reference_indisponible_attend_puis_se_passe_de_reference():
    ds, cl = serie_lineaire(n=100)
    s = snap(as_of=ds[10])
    s["sector_ref"] = "XLK.US"
    apres_echeance = date.fromisoformat(ds[30]) + timedelta(days=3)
    assert le.compute_outcome(s, 20, (ds, cl), None, None, apres_echeance) is None
    tard = date.fromisoformat(ds[30]) + timedelta(days=le.BENCH_GRACE_DAYS + 1)
    o = le.compute_outcome(s, 20, (ds, cl), None, None, tard)
    assert o["status"] == "matured" and o["sector_excess_pct"] is None


# ─────────────────────────────────────────────────────────────────────────
# Maturation de bout en bout
# ─────────────────────────────────────────────────────────────────────────

def fausse_source(appels):
    ds, cl = serie_lineaire(n=400)

    def raw(symbole, debut, fin):
        appels.append(symbole)
        pente = {"SPY.US": 0.3, "XLK.US": 0.4}.get(symbole, 1.0)
        return ds, [100 + pente * i for i in range(len(ds))]
    return ds, raw


def test_maturation_un_appel_par_symbole_et_idempotente(ldir):
    appels = []
    ds, raw = fausse_source(appels)
    snaps = [snap(ticker="AAA.US", as_of=ds[k]) for k in (5, 6, 7)]
    snaps += [snap(ticker="BBB.US", as_of=ds[k]) for k in (5, 6)]
    le.record_snapshots(ldir, snaps)

    bilan = le.mature(ldir, [20, 60], le.CachedFetcher(raw), "2027-06-30")
    assert bilan["clotures"] == 10 and bilan["en_attente"] == 0
    # AAA, BBB, XLK, SPY : quatre appels, quel que soit le nombre d'observations
    assert sorted(set(appels)) == ["AAA.US", "BBB.US", "SPY.US", "XLK.US"]
    assert len(appels) == 4

    bilan2 = le.mature(ldir, [20, 60], le.CachedFetcher(raw), "2027-06-30")
    assert bilan2["candidats"] == 0
    assert len(le.load_store(ldir)["outcomes"]) == 10


def test_echec_reseau_laisse_en_attente_sans_rien_inscrire(ldir):
    ds, _ = fausse_source([])
    le.record_snapshots(ldir, [snap(as_of=ds[5])])
    bilan = le.mature(ldir, [20], le.CachedFetcher(lambda *a: None), "2027-06-30")
    assert bilan["clotures"] == 0 and bilan["en_attente"] == 1
    assert le.load_store(ldir)["outcomes"] == []


def test_horizon_personnalise_s_applique_a_tout_le_passe(ldir):
    ds, raw = fausse_source([])
    le.record_snapshots(ldir, [snap(as_of=ds[5])])
    le.mature(ldir, [20], le.CachedFetcher(raw), "2027-06-30")
    le.mature(ldir, [20, 37], le.CachedFetcher(raw), "2027-06-30")   # nouvel horizon
    hs = sorted(o["horizon"] for o in le.load_store(ldir)["outcomes"])
    assert hs == [20, 37]


def test_rien_a_cloturer_avant_la_borne_minimale(ldir):
    ds, raw = fausse_source([])
    le.record_snapshots(ldir, [snap(as_of="2026-01-12")])
    appels = []
    bilan = le.mature(ldir, [60], le.CachedFetcher(lambda *a: appels.append(a)), "2026-02-01")
    assert bilan["candidats"] == 0 and appels == []       # zero appel reseau


# ─────────────────────────────────────────────────────────────────────────
# Statistiques
# ─────────────────────────────────────────────────────────────────────────

def test_spearman_parfait_inverse_et_ex_aequo():
    assert le.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert le.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert le.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
    assert le.spearman([1, 2], [1, 2]) is None


def test_intervalle_de_confiance_absent_sur_petit_echantillon():
    assert le.mean_ci95([1, 2, 3]) is None
    lo, hi = le.mean_ci95([1.0] * 5 + [3.0] * 5)
    assert lo < 2.0 < hi


def test_thin_ecarte_les_fenetres_qui_se_chevauchent():
    obs = [{"ticker": "A", "as_of": (date(2026, 1, 1) + timedelta(days=k)).isoformat()}
           for k in range(0, 100)]
    gardes = le.thin(obs, 20)
    ecarts = [(date.fromisoformat(b["as_of"]) - date.fromisoformat(a["as_of"])).days
              for a, b in zip(gardes, gardes[1:])]
    assert min(ecarts) >= 28                      # ceil(20 * 1,4)
    autre = obs + [{"ticker": "B", "as_of": "2026-01-01"}]
    assert len(le.thin(autre, 20)) == len(gardes) + 1     # un autre titre est independant


def store_synthetique(ldir, n_tickers=30, n_dates=40, beta=0.0, seed=1,
                      version="v1", sous_notes=True, bruit=4.0):
    """Ecrit snapshots + outcomes dont le rendement depend (ou non) de la note."""
    rnd = random.Random(seed)
    base = date(2025, 1, 6)
    snaps, outs = [], []
    for t in range(n_tickers):
        sec = ["Technology", "Healthcare", "Energy"][t % 3]
        for k in range(n_dates):
            d0 = base + timedelta(days=7 * k)
            sc = round(rnd.uniform(1, 10), 2)
            subs = {c: round(min(10, max(0, sc + rnd.gauss(0, 1.5))), 2)
                    for c in le.ML_FEATURES[1:]} if sous_notes else {}
            s = le.build_snapshot("u", f"T{t}.US", f"T{t}", d0, sc, 90, subs, version,
                                  "action", sec, "", le.load_config("x.json"), price=100)
            snaps.append(s)
            y = beta * (sc - 5.5) + rnd.gauss(0, bruit)
            outs.append({"id": s["id"], "horizon": 20, "status": "matured",
                         "as_of": s["as_of"], "session_t": s["as_of"],
                         "session_t_h": (d0 + timedelta(days=28)).isoformat(),
                         "stock_return_pct": y, "sector_return_pct": 0.0,
                         "market_return_pct": 0.0, "sector_excess_pct": y,
                         "market_excess_pct": y})
    le.append_jsonl(os.path.join(ldir, "predictions.jsonl"), snaps)
    le.append_jsonl(os.path.join(ldir, "outcomes.jsonl"), outs)


def test_notes_predictives_donnent_un_ic_positif_et_des_tranches_ordonnees(ldir):
    store_synthetique(ldir, beta=1.5, bruit=2.0)
    obs = le.build_observations(le.load_store(ldir))
    st = le.horizon_stats(obs, 20, "sector", "sector_y", "v1")
    assert st["ic"] > 0.3 and st["slope"]["pente"] > 1.0
    moyennes = [b["mean"] for b in st["bands"] if b["n"]]
    assert moyennes == sorted(moyennes)


def test_notes_sans_valeur_predictive_donnent_un_ic_proche_de_zero(ldir):
    store_synthetique(ldir, beta=0.0)
    obs = le.build_observations(le.load_store(ldir))
    st = le.horizon_stats(obs, 20, "sector", "sector_y", "v1")
    assert abs(st["ic"]) < 0.12


def test_retrecissement_l_esperance_de_tranche_se_rapproche_de_la_moyenne_globale(ldir):
    store_synthetique(ldir, beta=1.5, bruit=2.0)
    obs = le.build_observations(le.load_store(ldir))
    st = le.horizon_stats(obs, 20, "sector", "sector_y", "v1")
    haut = st["bands"][-1]
    glob = st["global"]["mean"]
    assert glob < haut["estimate"] < haut["mean"]       # entre les deux, jamais au-dela


def test_petit_echantillon_aucune_esperance_publiee():
    obs = [{"id": str(i), "horizon": 20, "ticker": f"T{i}", "as_of": "2026-01-05",
            "target_date": "2026-02-05", "score": 8.0, "subscores": {}, "version": "v1",
            "sector": "", "raw": 1.0, "sector_y": 1.0, "market_y": 1.0, "delisted": False}
           for i in range(4)]
    st = le.horizon_stats(obs, 20, "sector", "sector_y", "v1")
    haut = st["bands"][-1]
    assert haut["estimate"] is None and haut["p_outperf"] is None
    assert st["confidence"] == "insuffisante"
    pr = le.predict_position(8.5, "", st, obs, "sector_y", 20, "v1")
    assert pr["estimate"] is None and "insuffisant" in pr["reason"]


def test_cohorte_heritee_ajoutee_si_besoin_et_confiance_plafonnee(ldir):
    store_synthetique(ldir, beta=1.5, bruit=2.0, version="legacy", sous_notes=False)
    obs = le.build_observations(le.load_store(ldir))
    st = le.horizon_stats(obs, 20, "sector", "sector_y", "v14")   # version courante : 0 obs
    assert st["legacy_included"] is True
    assert all(b["confidence"] in ("faible", "insuffisante") for b in st["bands"])


def test_versions_non_melangees_quand_la_version_courante_suffit(ldir):
    store_synthetique(ldir, beta=1.5, bruit=2.0, version="v14", seed=3)
    obs = le.build_observations(le.load_store(ldir))
    obs += [dict(o, version="legacy", raw=-99, sector_y=-99, market_y=-99)
            for o in obs[:200]]
    st = le.horizon_stats(obs, 20, "sector", "sector_y", "v14")
    assert st["legacy_included"] is False
    assert st["global"]["mean"] > -5                          # la cohorte -99 est exclue


# ─────────────────────────────────────────────────────────────────────────
# Modele : conditionnel, walk-forward
# ─────────────────────────────────────────────────────────────────────────

def test_le_modele_ne_s_active_pas_sur_du_bruit(ldir):
    store_synthetique(ldir, beta=0.0, seed=7)
    obs = le.build_observations(le.load_store(ldir))
    v = le.evaluate_model(obs, "sector_y", 20, min_obs=250, min_dates=30)
    assert v["active"] is False


def test_le_modele_s_active_seulement_quand_le_signal_est_reel(ldir):
    store_synthetique(ldir, beta=2.0, bruit=2.0, seed=11)
    obs = le.build_observations(le.load_store(ldir))
    r = le.train_and_register(ldir, obs, "sector_y", "sector", 20, "v1",
                              "2026-06-01", min_obs=250, min_dates=30)
    assert r["active"] is True
    assert os.path.exists(os.path.join(ldir, "model_registry", "active.json"))
    pred = le.model_predict(ldir, 20, {"score": 9.5, "subscores": {c: 9.5 for c in le.ML_FEATURES[1:]}})
    bas = le.model_predict(ldir, 20, {"score": 1.5, "subscores": {c: 1.5 for c in le.ML_FEATURES[1:]}})
    assert pred["estimate"] > bas["estimate"]


def test_modele_jamais_active_sous_le_minimum_d_observations(ldir):
    store_synthetique(ldir, n_tickers=5, n_dates=10, beta=3.0, bruit=0.5)
    obs = le.build_observations(le.load_store(ldir))
    v = le.evaluate_model(obs, "sector_y", 20)          # seuils par defaut
    assert v["active"] is False and "insuffisant" in v["raison"]


def test_walk_forward_purge_pas_de_train_dont_l_echeance_depasse_le_test():
    """Si toutes les echeances tombent APRES le debut de chaque bloc de test,
    aucun exemple d'entrainement n'est admissible : aucun bloc valide."""
    obs = []
    for i in range(400):
        d = date(2025, 1, 1) + timedelta(days=i // 4)
        obs.append({"id": str(i), "horizon": 20, "ticker": f"T{i % 20}",
                    "as_of": d.isoformat(), "target_date": "2099-01-01",
                    "score": 5.0 + (i % 5), "subscores": {"momentum": 5.0},
                    "version": "v1", "sector": "", "sector_y": float(i % 7)})
    wf = le.walk_forward(obs, "sector_y", 20)
    assert wf["folds"] == []


def test_ridge_retrouve_une_relation_lineaire():
    rnd = random.Random(0)
    X = [[rnd.uniform(-1, 1), rnd.uniform(-1, 1)] for _ in range(300)]
    y = [3 * a - 2 * b + rnd.gauss(0, 0.1) for a, b in X]
    m = le.ridge_fit(X, y, lam=1.0)
    assert le.ridge_predict(m, [1.0, 0.0]) > le.ridge_predict(m, [-1.0, 0.0])
    assert le.ridge_predict(m, [0.0, 1.0]) < le.ridge_predict(m, [0.0, -1.0])


# ─────────────────────────────────────────────────────────────────────────
# Amorcage depuis history.csv, config, reglages
# ─────────────────────────────────────────────────────────────────────────

def test_backfill_une_ligne_par_jour_derniere_du_jour_ignore_les_anciens_exports(tmp_path):
    p = tmp_path / "history.csv"
    p.write_text(
        "date,time,ticker,name,price_eur,cost_eur,qty,vm,pnl_brut,pnl_brut_pct,"
        "pnl_net,pnl_net_pct,score,confiance,rec\n"
        "2026-05-13,21:03,PLTR.US,Palantir,110,1,1,1,1,1,1,1,5.85,,GARDER\n"
        "2026-05-13,21:47,PLTR.US,Palantir,111,1,1,1,1,1,1,1,5.88,,GARDER\n"
        "2026-05-13,21:47,PLTR,Palantir,111,1,1,1,1,1,1,1,5.88,,GARDER\n"
        "2026-05-14,21:47,PLTR.US,Palantir,112,1,1,1,1,1,1,1,,,GARDER\n",
        encoding="utf-8")
    snaps = le.backfill_from_history_csv(str(p), "u", le.load_config("x.json"),
                                         {"PLTR.US": {"sector": "tech"}})
    assert len(snaps) == 1                       # doublon du jour, suffixe absent, score vide
    s = snaps[0]
    assert s["score"] == 5.88 and s["price"] == 111.0
    assert s["score_version"] == "legacy" and s["source"] == "backfill_history_csv"
    assert s["sector"] == "Information Technology" and s["sector_ref"] == "XLK.US"


def test_references_selon_la_region_et_secteur_sans_reference_non_invente():
    """resolve_refs() renvoie desormais un dict (region + devises), et le
    secteur se cherche par REGION, pas par place : un titre francais ou
    europeen a droit a une vraie reference sectorielle (bogue corrige --
    avant, sector_refs n'avait qu'une cle "US" et tout le reste de la planete
    retombait sur None), sans qu'aucun ticker ne soit invente pour autant."""
    cfg = le.load_config("x.json")
    assert le.resolve_refs("CRWV.US", "Technology", cfg) == {
        "region": "US", "sector_ref": "XLK.US", "sector_ref_devise": "USD",
        "market_ref": "SPY.US", "market_ref_devise": "USD",
    }
    assert le.resolve_refs("ACA.PA", "Financial Services", cfg) == {
        "region": "EUROPE", "sector_ref": "ESIF.XETRA", "sector_ref_devise": "EUR",
        "market_ref": "FCHI.INDX", "market_ref_devise": "EUR",
    }
    # Place non reconnue (region UNKNOWN) : toujours rien d'invente, repli sur
    # le marche par defaut uniquement.
    r = le.resolve_refs("ZZZ.XX", "", cfg)
    assert r == {"region": "UNKNOWN", "sector_ref": None, "sector_ref_devise": None,
                "market_ref": "SPY.US", "market_ref_devise": "USD"}


def test_places_europeennes_etroites_ne_pointent_plus_sur_le_cac40():
    """Bogue corrige : Amsterdam/Bruxelles/Lisbonne/Milan/Madrid retombaient
    sur le CAC 40 francais comme « marche local » -- une reference fausse
    puisque ce ne sont pas des places francaises. Elles pointent desormais
    sur un proxy pan-europeen reel (STOXX Europe 600), et Milan/Madrid, qui
    manquaient purement et simplement (silencieusement remplaces par le
    S&P 500 americain via le fallback "default"), ont maintenant leur propre
    entree."""
    cfg = le.load_config("x.json")
    for place, ticker in (("AS", "AAA.AS"), ("BR", "AAA.BR"), ("LS", "AAA.LS"),
                          ("MI", "AAA.MI"), ("MC", "AAA.MC")):
        r = le.resolve_refs(ticker, "", cfg)
        assert r["market_ref"] == "EXSA.XETRA", place
        assert r["market_ref"] != "FCHI.INDX" and r["market_ref"] != "SPY.US", place


def test_config_illisible_ignoree(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{pas du json", encoding="utf-8")
    assert le.load_config(str(p)) == le.DEFAULT_CONFIG
    p.write_text(json.dumps({"sector_refs": {"europe":
                 {"Energy": {"symbol": "XYZ.PA", "devise": "EUR"}}}}), encoding="utf-8")
    cfg = le.load_config(str(p))
    assert cfg["sector_refs"]["EUROPE"]["Energy"] == {"symbol": "XYZ.PA", "devise": "EUR"}
    assert "US" in cfg["sector_refs"]


def test_reglages_bornes_a_l_entree():
    s = le.normalize_settings({"horizon": 9999, "horizons": [3, 45, "x", 300]})
    assert s["horizon"] == le.DEFAULT_HORIZON
    assert 45 in s["horizons"] and 300 in s["horizons"] and 3 not in s["horizons"]
    assert le.normalize_settings({"horizon": 90})["horizon"] == 90
    assert 90 in le.normalize_settings({"horizon": 90})["horizons"]
    assert le.normalize_settings(None)["actif"] is True


# ─────────────────────────────────────────────────────────────────────────
# Synthese et rapport
# ─────────────────────────────────────────────────────────────────────────

def test_synthese_et_markdown_de_bout_en_bout(ldir):
    store_synthetique(ldir, beta=1.5, bruit=2.0, version="v1")
    cfg = le.normalize_settings({"horizon": 20})
    positions = [{"ticker": "T1.US", "name": "T1", "score": 8.2, "sector": "Technology",
                  "subscores": {c: 8.0 for c in le.ML_FEATURES[1:]}}]
    s = le.build_summary("u", ldir, positions, "v1", "2026-06-01", cfg)
    le.write_summary(ldir, s)
    assert json.load(open(os.path.join(ldir, "summary.json"), encoding="utf-8"))["user"] == "u"
    md = "\n".join(le.render_markdown(s))
    assert "## Fiabilite des Notes" in md and "Fiabilite par position" in md
    assert "Quel horizon colle le mieux" in md
    assert "ne la modifie" in md                       # la note n'est jamais reecrite
    pr = s["positions"][0]["horizons"]["20"]
    assert pr["estimate"] is not None and pr["confidence"] in ("faible", "moyenne", "elevee")


def test_markdown_sans_aucune_observation_cloturee(ldir):
    le.record_snapshots(ldir, [snap()])
    s = le.build_summary("u", ldir, [], "v1", "2026-02-01", le.normalize_settings({}))
    md = "\n".join(le.render_markdown(s))
    assert "aucune observation cloturee" in md
    assert "Rien n'est conclu avant l'echeance" in md
