"""Amorcage du moteur d'apprentissage sur le passe (08/10/2026)."""

import json
import math
import os
import random
from datetime import date, timedelta

import pytest

import amorcage_apprentissage as am
import learning_engine as le
import portfolio_analyzer as pa

AUJ = date(2026, 10, 5)
SPLIT = date(2025, 7, 1)          # split 2 pour 1


# --- Donnees synthetiques au format SEC / TwelveData -------------------------

def _fin_trimestre(annee, q):
    mois = 3 * q
    prochain = date(annee + (mois == 12), (mois % 12) + 1, 1)
    return prochain - timedelta(days=1)


def faits_sec(croissance=0.02, marge=0.10, base=100.0):
    """Entreprise a exercice calendaire : 10-Q a T+40 j, 10-K a T+59 j.
    Chaque trimestre est republie un an plus tard CORRIGE de +5 % (le
    programme ne doit voir que la premiere publication)."""
    rev, ni, op, sh, eq, ac = [], [], [], [], [], []
    k = 0
    for an in range(2021, 2027):
        vals_an = []
        for q in (1, 2, 3, 4):
            debut = date(an, 3 * (q - 1) + 1, 1)
            fin = _fin_trimestre(an, q)
            v = base * (1 + croissance) ** k
            k += 1
            vals_an.append(v)
            actions = 2000 if fin > SPLIT else 1000
            if q < 4:
                publie = fin + timedelta(days=40)
                if publie <= AUJ:
                    for liste, val in ((rev, v), (ni, v * marge), (op, v * marge * 1.5)):
                        liste.append({"start": str(debut), "end": str(fin), "val": val,
                                      "filed": str(publie), "form": "10-Q"})
                        liste.append({"start": str(debut), "end": str(fin), "val": val * 1.05,
                                      "filed": str(publie + timedelta(days=365)), "form": "10-Q"})
                    sh.append({"start": str(debut), "end": str(fin), "val": actions,
                               "filed": str(publie), "form": "10-Q"})
                    eq.append({"end": str(fin), "val": 1000 + 10 * k, "filed": str(publie)})
                    ac.append({"end": str(fin), "val": 3000.0, "filed": str(publie)})
        fin_an, publie_an = date(an, 12, 31), date(an + 1, 2, 28)
        if publie_an <= AUJ:
            tot = sum(vals_an)
            for liste, val in ((rev, tot), (ni, tot * marge), (op, tot * marge * 1.5)):
                liste.append({"start": f"{an}-01-01", "end": str(fin_an), "val": val,
                              "filed": str(publie_an), "form": "10-K"})
            sh.append({"start": f"{an}-01-01", "end": str(fin_an),
                       "val": 2000 if fin_an > SPLIT else 1000,
                       "filed": str(publie_an), "form": "10-K"})
            # Le 10-K suivant republie l'exercice precedent APRES le split (x2).
            if an == 2024:
                sh.append({"start": "2024-01-01", "end": "2024-12-31", "val": 2000,
                           "filed": "2026-02-28", "form": "10-K"})
            eq.append({"end": str(fin_an), "val": 1000 + 10 * k, "filed": str(publie_an)})
            ac.append({"end": str(fin_an), "val": 3000.0, "filed": str(publie_an)})
    gaap = {
        "Revenues": {"units": {"USD": rev}},
        "NetIncomeLoss": {"units": {"USD": ni}},
        "OperatingIncomeLoss": {"units": {"USD": op}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": sh}},
        "StockholdersEquity": {"units": {"USD": eq}},
        "Assets": {"units": {"USD": ac}},
    }
    return {"cik": 1, "entityName": "AAA", "facts": {"us-gaap": gaap}}


def serie_prix(graine, debut=date(2022, 6, 1), fin=AUJ, p0=50.0, vol=0.015, derive=0.0003):
    rng = random.Random(graine)
    ds, cs, d, p = [], [], debut, p0
    while d <= fin:
        if d.weekday() < 5:
            p *= 1 + rng.gauss(derive, vol)
            ds.append(d.isoformat())
            cs.append(round(p, 4))
        d += timedelta(days=1)
    return ds, cs


def brute_de(ajustee):
    """Cours brut : x2 avant le split (le cours ajuste divise le passe par 2)."""
    ds, cs = ajustee
    return ds, [c * 2 if d < SPLIT.isoformat() else c for d, c in zip(ds, cs)]


# --- 1. Comptes SEC ----------------------------------------------------------

def test_premiere_publication_seulement():
    c = am.Comptes(faits_sec())
    t1 = c.flux["revenus"][0]
    assert all(abs(f["val"] - 100 * 1.02 ** i) < 1e-6 for i, f in enumerate(t1[:3]))


def test_t4_deduit_des_comptes_annuels():
    trims, ans = am.Comptes(faits_sec()).flux["revenus"]
    t4 = [f for f in trims if f.get("deduit")]
    assert t4 and all(f["filed"].month == 2 and f["filed"].day == 28 for f in t4)
    # T4 2023 = 4e trimestre de la serie (k = 11)
    q = next(f for f in t4 if f["end"] == date(2023, 12, 31))
    assert abs(q["val"] - 100 * 1.02 ** 11) < 1e-6


def test_cumul_12_mois_au_point_dans_le_temps():
    trims, ans = am.Comptes(faits_sec()).flux["revenus"]
    avant = am.cumul_12_mois(trims, ans, date(2024, 2, 27))   # 10-K 2023 pas encore publie
    apres = am.cumul_12_mois(trims, ans, date(2024, 3, 1))
    attendu_apres = sum(100 * 1.02 ** k for k in range(8, 12))
    attendu_avant = sum(100 * 1.02 ** k for k in range(7, 11))   # T4 2022 .. T3 2023
    assert abs(apres - attendu_apres) < 1e-6
    assert abs(avant - attendu_avant) < 1e-6


def test_croissance_sur_un_an():
    trims, ans = am.Comptes(faits_sec(croissance=0.02)).flux["revenus"]
    g = am.croissance_sur_un_an(trims, ans, date(2025, 6, 1))
    assert abs(g - (1.02 ** 4 - 1)) < 1e-9


def test_valeur_de_bilan_et_actions_avant_publication():
    c = am.Comptes(faits_sec())
    # Actions de l'exercice 2024 : 1000 (publie en 2025), la version x2 de
    # 2026 n'est pas encore connue au 1er mars 2025.
    n, fin = am.nombre_actions(c.g["actions"]["faits"], date(2025, 3, 1))
    assert (n, fin) == (1000, date(2024, 12, 31))
    assert am.valeur_instant(c.g["capitaux"]["faits"], date(2025, 3, 1)) is not None


# --- 2. Capitalisation exacte malgre le split -------------------------------

def test_capitalisation_avant_et_apres_split():
    aj = serie_prix(1)
    br = brute_de(aj)
    t = date(2025, 3, 3)
    p_brut = le.value_on_or_before(br[0], br[1], t)
    cap = am.capitalisation_a(aj, br, t, 1000, date(2024, 12, 31))
    assert abs(cap - p_brut * 1000) / cap < 1e-9
    t2 = date(2025, 12, 1)
    cap2 = am.capitalisation_a(aj, br, t2, 2000, date(2025, 9, 30))
    assert abs(cap2 - le.value_on_or_before(br[0], br[1], t2) * 2000) / cap2 < 1e-9


def test_split_detecte_dans_les_comptes():
    c = am.Comptes(faits_sec())
    assert am.split_dans_comptes(c, date(2024, 1, 1)) is True
    assert am.split_dans_comptes(c, date(2025, 10, 1)) is False


# --- 3. La note ne voit jamais le futur -------------------------------------

def test_note_insensible_au_futur():
    aj = serie_prix(2)
    br = brute_de(aj)
    spy = serie_prix(3, vol=0.01)
    c = am.Comptes(faits_sec())
    t = date(2024, 9, 16)
    n1 = am.noter_a(aj, br, spy, c, t)
    # On falsifie tout ce qui suit t : cours et comptes publies apres t.
    futur = [(d, x * 3 if d > t.isoformat() else x) for d, x in zip(*aj)]
    aj2 = ([d for d, _ in futur], [x for _, x in futur])
    f2 = faits_sec()
    for concept in f2["facts"]["us-gaap"].values():
        for unite in concept["units"].values():
            for r in unite:
                if r["filed"] >= t.isoformat():
                    r["val"] *= 7
    n2 = am.noter_a(aj2, brute_de(aj2), spy, am.Comptes(f2), t)
    assert n1[0] is not None and n1[:3] == n2[:3]
    assert "consensus" not in n1[2]                   # aucun avis d'analystes invente


def test_sans_comptes_pas_de_note():
    aj = serie_prix(4)
    assert am.noter_a(aj, None, None, None, date(2024, 9, 16))[3] == \
        "comptes indisponibles a cette date"


# --- 4. Reconstitution et correction du biais de selection ------------------

def _refs(cfg, assets):
    refs = {"SPY.US": serie_prix(99, vol=0.01)}
    for a in assets:
        s = le.resolve_refs(a["ticker_eod"], a["sector"], cfg)["sector_ref"]
        refs.setdefault(s, serie_prix(hash(s) % 1000, vol=0.012))
    return refs


def test_reconstituer_un_titre():
    cfg = le.load_config()
    a = {"ticker_eod": "AAA.US", "name": "AAA", "sector": "Information Technology"}
    aj = serie_prix(5)
    dates = am.dates_a_rejouer(AUJ, 3)
    snaps, outs, motifs = am.reconstituer_titre(a, aj, brute_de(aj), _refs(cfg, [a]),
                                                am.Comptes(faits_sec()), dates, cfg, AUJ,
                                                (20, 60, 120, 252))
    assert snaps and all(s["source"] == "reconstitue" for s in snaps)
    assert all(s["score_version"] == pa.SCORE_VERSION for s in snaps)
    # Ecart de 28 jours entre deux dates : toutes independantes a 20 seances.
    assert all((le._d(b["as_of"]) - le._d(a_["as_of"])).days == 28
               for a_, b in zip(snaps, snaps[1:]))
    par_h = {h: sum(1 for o in outs if o["horizon"] == h and o["status"] == "matured")
             for h in (20, 60, 120, 252)}
    assert par_h[20] == len(snaps) and par_h[20] > par_h[60] > par_h[120] > par_h[252] > 0
    # Une echeance non atteinte n'est jamais inventee.
    for o in outs:
        assert o["session_t_h"] <= AUJ.isoformat()


def test_correction_du_biais_de_selection():
    outs = [{"status": "matured", "horizon": 20, "as_of": "2025-01-06",
             "sector_excess_pct": float(i), "market_excess_pct": 2.0 * i} for i in range(12)]
    corr = am.corriger_biais_selection(outs)
    assert abs(sum(o["sector_excess_pct"] for o in outs)) < 1e-6
    assert outs[0]["sector_excess_brut_pct"] == 0.0
    assert corr["20:sector_excess_pct"] == 5.5
    # Trop peu de titres a une date : rien n'est corrige.
    peu = [{"status": "matured", "horizon": 20, "as_of": "2025-02-03",
            "sector_excess_pct": 3.0, "market_excess_pct": None}]
    am.corriger_biais_selection(peu)
    assert peu[0]["sector_excess_pct"] == 3.0


def _faux_telechargements(appels):
    def cours(symbole, debut, ajustement):
        appels.append((symbole, ajustement))
        aj = serie_prix(sum(map(ord, symbole)), debut=debut)
        return (brute_de(aj) if ajustement == "none" else aj), None

    def comptes(ticker):
        return faits_sec(croissance=0.005 + (sum(map(ord, ticker)) % 7) / 200), None
    return cours, comptes


def test_lancer_de_bout_en_bout(tmp_path):
    appels = []
    cours, comptes = _faux_telechargements(appels)
    dossier = str(tmp_path / "amorcage")
    bilan = am.lancer(annees=3, max_titres=12, dossier=dossier, telecharger_cours=cours,
                      telecharger_comptes=comptes, aujourdhui=AUJ)
    assert bilan["titres_notes"] == 12 and bilan["snapshots"] > 12 * 30
    assert set(bilan["observations_par_horizon"]) == {"20", "60", "120", "252"}
    store = le.load_store(dossier)
    assert len(store["snapshots"]) == bilan["snapshots"]
    # 2 series par titre (ajustee + brute) + les references, rien d'autre.
    assert sum(1 for _, adj in appels if adj == "none") == 12
    # Relancer remplace sans doublon.
    am.lancer(annees=3, max_titres=12, dossier=dossier, telecharger_cours=cours,
              telecharger_comptes=comptes, aujourdhui=AUJ)
    assert len(le.load_store(dossier)["snapshots"]) == bilan["snapshots"]
    with open(os.path.join(dossier, "bilan.json"), encoding="utf-8") as f:
        assert json.load(f)["score_version"] == pa.SCORE_VERSION


def test_sec_injoignable_aucun_credit_twelvedata(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setenv("TWELVEDATA_API_KEY", "x")
    monkeypatch.setattr(am, "table_cik", lambda ua, c: ({}, "HTTP 403"))
    monkeypatch.setattr(am, "td_serie", lambda *a, **k: appels.append(a) or (None, "x"))
    bilan = am.lancer(dossier=str(tmp_path / "a"), aujourdhui=AUJ)
    assert bilan["snapshots"] == 0 and "SEC_USER_AGENT" in bilan["interrompu"]
    assert appels == []


# --- 5. Le moteur s'en sert, puis passe la main ------------------------------

def _obs(ticker, jour, h, y, reconstitue, version=None):
    return {"id": f"{ticker}{jour}{h}{reconstitue}", "horizon": h, "ticker": ticker,
            "as_of": jour, "target_date": jour, "score": 6.0, "subscores": {},
            "version": version or pa.SCORE_VERSION, "sector": "Energy", "region": "US",
            "raw": y, "sector_y": y, "market_y": y, "delisted": False,
            "reconstitue": reconstitue}


def test_relais_vers_les_vraies_notes():
    debut = date(2023, 1, 2)
    recon = [_obs(f"R{i}", (debut + timedelta(days=28 * k)).isoformat(), 20, 1.0, True)
             for i in range(5) for k in range(20)]
    vraies = [_obs(f"V{i}", (debut + timedelta(days=28 * k)).isoformat(), 20, -1.0, False)
              for i in range(3) for k in range(10)]
    cohorte, _ = le.select_cohort(recon + vraies, pa.SCORE_VERSION, 20)
    assert any(o["reconstitue"] for o in cohorte)          # 30 vraies < 60 : amorcage utilise
    vraies += [_obs(f"W{i}", (debut + timedelta(days=28 * k)).isoformat(), 20, -1.0, False)
               for i in range(3) for k in range(10)]
    cohorte, _ = le.select_cohort(recon + vraies, pa.SCORE_VERSION, 20)
    assert not any(o["reconstitue"] for o in cohorte)      # 60 vraies : relais pris


def test_moteur_lit_l_amorcage_sans_le_cloturer(tmp_path, monkeypatch):
    ldir = str(tmp_path)
    cfg = le.load_config()
    vivant = le.build_snapshot("_pool", "AAA.US", "A", "2026-09-01", 6.0, 100, {"momentum": 6},
                               pa.SCORE_VERSION, "action", "Energy", "", cfg)
    le.record_snapshots(ldir, [vivant])
    rec = le.build_snapshot("_pool", "BBB.US", "B", "2025-01-06", 7.0, 85, {"momentum": 7},
                            pa.SCORE_VERSION, "action", "Energy", "", cfg, source="reconstitue")
    double = dict(vivant, source="reconstitue", score=1.0)          # meme id que le vivant
    out = {"id": rec["id"], "horizon": 20, "status": "matured", "as_of": "2025-01-06",
           "session_t": "2025-01-06", "session_t_h": "2025-02-04", "stock_return_pct": 3.0,
           "sector_excess_pct": 1.0, "market_excess_pct": 2.0}
    am.ecrire_amorcage(le.amorcage_dir(ldir), [rec, double], [out], {})

    assert len(le.load_store(ldir)["snapshots"]) == 1                 # nightly : intact
    complet = le.load_store(ldir, avec_amorcage=True)
    assert len(complet["snapshots"]) == 2                            # doublon : le vivant gagne
    assert next(s for s in complet["snapshots"] if s["id"] == vivant["id"])["score"] == 6.0
    obs = le.build_observations(complet)
    assert len(obs) == 1 and obs[0]["reconstitue"] is True

    # mature() ne voit pas les snapshots reconstitues.
    vus = []
    le.mature(ldir, [20], lambda s, d0, d1: vus.append(s) or None, "2026-10-05")
    assert "BBB.US" not in vus

    synth = le.build_summary("_pool", ldir, [], pa.SCORE_VERSION, date(2026, 10, 5),
                             le.normalize_settings(None), train_models=True)
    assert synth["counts"]["reconstitues"] == 1 and synth["counts"]["snapshots"] == 1
    monkeypatch.setenv("APPRENTISSAGE_AMORCAGE", "0")
    assert len(le.load_store(ldir, avec_amorcage=True)["snapshots"]) == 1


# --- 6. Lecture des reponses reelles (format TwelveData / SEC) ---------------

class _Rep:
    def __init__(self, code, data):
        self.status_code, self._data = code, data

    def json(self):
        return self._data


def test_td_serie_format_reel_et_limite_minute(monkeypatch):
    reponses = [
        _Rep(200, {"code": 429, "status": "error",
                   "message": "You have run out of API credits for the current minute."}),
        _Rep(200, {"status": "ok", "meta": {"symbol": "AAPL"}, "values": [
            {"datetime": "2026-10-06", "close": "251.2"},
            {"datetime": "2026-10-05", "close": "250.0"},
            {"datetime": "2026-10-02", "close": "n/a"}]}),
    ]
    vus = []
    monkeypatch.setattr(am.requests, "get", lambda url, params, timeout: (
        vus.append(params), reponses.pop(0))[1])
    monkeypatch.setattr(am.time, "sleep", lambda s: None)
    monkeypatch.setattr(am.pa, "_attendre_debit", lambda *a, **k: None)
    c = {}
    serie, err = am.td_serie("AAPL", date(2023, 1, 2), "none", "cle", c)
    assert err is None and serie == (["2026-10-05", "2026-10-06"], [250.0, 251.2])
    assert vus[0]["adjust"] == "none" and c["twelvedata"] == 2


def test_td_serie_quota_du_jour(monkeypatch):
    monkeypatch.setattr(am.requests, "get", lambda url, params, timeout: _Rep(
        429, {"code": 429, "message": "You have run out of API credits for the day."}))
    monkeypatch.setattr(am.pa, "_attendre_debit", lambda *a, **k: None)
    with pytest.raises(am.QuotaJourEpuise):
        am.td_serie("AAPL", date(2023, 1, 2), "all", "cle", {})


def test_table_cik(monkeypatch):
    monkeypatch.setattr(am, "sec_get", lambda url, ua, c: (
        {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
         "1": {"cik_str": 1754301, "ticker": "FOXA", "title": "Fox Corp"}}, None))
    table, err = am.table_cik("ua", {})
    assert table == {"AAPL": 320193, "FOXA": 1754301} and err is None
