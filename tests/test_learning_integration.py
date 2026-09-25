"""Integration du moteur d'apprentissage dans portfolio_analyzer : isolation,
secteurs, amorcage, idempotence, reglages de profil. Aucun reseau (tout est
injecte), aucune ecriture hors du repertoire temporaire du test.
"""
import json
import os
from datetime import date, timedelta

import learning_engine as le
import portfolio_analyzer as pa


def seances(debut="2026-01-05", n=300):
    d = date.fromisoformat(debut)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _resultat(ticker="CRWV.US", nom="CoreWeave", score=6.8, classe="action"):
    return {"asset": {"ticker_eod": ticker, "name": nom, "asset_class": classe,
                      "manuel": False, "ticker_yf": ticker.split(".")[0]},
            "score": score, "confiance": 85.0, "price_eur": 100.0,
            "detail": {"momentum": 7.0, "valorisation": 5.0}}


def test_la_version_de_la_note_suit_les_poids():
    a = pa.calcul_score_version(pa.POIDS_NOTE)
    assert a == pa.SCORE_VERSION and a.startswith(pa.NOTE_FORMULE + "-")
    change = dict(pa.POIDS_NOTE, momentum=pa.POIDS_NOTE["momentum"] + 0.01)
    assert pa.calcul_score_version(change) != a         # nouvelle cohorte automatique


def test_secteurs_manuel_puis_cache_puis_yahoo_avec_plafond(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    appels = []

    def faux_yahoo(sym, modules=None):
        appels.append(sym)
        return {"sector": "Energy", "industry": "Oil"}, ""
    monkeypatch.setattr(pa, "_yahoo_summary", faux_yahoo)
    jour = date(2026, 9, 23)

    manuel = dict(_resultat("AAA.US")["asset"], sector="Healthcare")
    etf = dict(_resultat("EEE.PA", classe="etf")["asset"])
    inconnu = dict(_resultat("BBB.US")["asset"])
    out = pa._resoudre_secteurs([manuel, etf, inconnu], jour)
    assert out["AAA.US"]["sector"] == "Healthcare"       # la saisie l'emporte
    assert out["EEE.PA"]["sector"] == ""                 # un ETF n'a pas de secteur
    assert out["BBB.US"]["sector"] == "Energy" and appels == ["BBB"]

    appels.clear()
    pa._resoudre_secteurs([inconnu], jour)               # deuxieme fois : cache
    assert appels == []

    lots = [dict(_resultat(f"Z{i}.US")["asset"]) for i in range(pa.SECTEURS_MAX_REQUETES + 5)]
    pa._resoudre_secteurs(lots, jour)                    # plafond de requetes par run
    assert len(appels) == pa.SECTEURS_MAX_REQUETES


def test_secteur_introuvable_n_est_pas_retente_avant_le_delai(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    appels = []
    monkeypatch.setattr(pa, "_yahoo_summary",
                        lambda s, m=None: (appels.append(s), ({}, "429"))[1])
    a = _resultat("QQQ.US")["asset"]
    pa._resoudre_secteurs([a], date(2026, 9, 23))
    pa._resoudre_secteurs([a], date(2026, 9, 24))         # lendemain : pas de nouvel appel
    assert len(appels) == 1
    pa._resoudre_secteurs([a], date(2026, 10, 5))         # apres 7 jours : on retente
    assert len(appels) == 2


def test_apprentissage_de_bout_en_bout_et_idempotence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports" / "u").mkdir(parents=True)
    lignes = "".join(
        f"2026-0{m}-{d:02d},22:40,CRWV.US,CoreWeave,{100 + m + d / 10},1,1,1,1,1,1,1,"
        f"{5 + (d % 4)},,GARDER\n" for m in (3, 4) for d in range(1, 26))
    (tmp_path / "reports" / "u" / "history.csv").write_text(
        "date,time,ticker,name,price_eur,cost_eur,qty,vm,pnl_brut,pnl_brut_pct,"
        "pnl_net,pnl_net_pct,score,confiance,rec\n" + lignes, encoding="utf-8")
    monkeypatch.setattr(pa, "USER", "u")
    monkeypatch.setattr(pa, "HISTORY_PATH", "reports/u/history.csv")
    monkeypatch.setattr(pa, "PROFILE", {"settings": {"apprentissage": {"horizon": 20}}})
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, m=None: ({"sector": "Technology"}, ""))

    ds = seances("2026-01-05", 320)

    def cours(sym, debut, fin):
        pente = {"SPY.US": 0.1, "XLK.US": 0.2}.get(sym, 0.5)
        return ds, [100 + pente * i for i in range(len(ds))]
    monkeypatch.setattr(pa, "_apprentissage_cours", cours)

    md, synthese = pa.executer_apprentissage([_resultat()], "2026-09-23")
    texte = "\n".join(md)
    assert "## Fiabilite des Notes" in texte and synthese is not None
    ldir = le.pool_dir()                       # mutualise par defaut
    udir = os.path.join("reports", "u", "learning")
    st = le.load_store(ldir)
    assert any(s["source"] == "live" and s["score_version"] == pa.SCORE_VERSION
               for s in st["snapshots"])
    assert any(s["source"] == "backfill_history_csv" for s in st["snapshots"])
    assert os.path.exists(os.path.join(udir, "backfill_pool.done"))
    assert st["outcomes"], "les observations arrivees a echeance doivent etre cloturees"
    n_snap, n_out = len(st["snapshots"]), len(st["outcomes"])

    pa.executer_apprentissage([_resultat()], "2026-09-23")          # relance le meme soir
    st2 = le.load_store(ldir)
    assert (len(st2["snapshots"]), len(st2["outcomes"])) == (n_snap, n_out)
    resume = json.load(open(os.path.join(udir, "summary.json"), encoding="utf-8"))
    assert resume["user"] == "u" and resume["score_version"] == pa.SCORE_VERSION
    assert resume["mutualise"] is True


def test_un_bug_du_moteur_ne_casse_jamais_le_rapport(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pa, "USER", "u")
    monkeypatch.setattr(pa, "PROFILE", {})
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, m=None: ({}, ""))

    def boom(*a, **k):
        raise RuntimeError("panne simulee")
    monkeypatch.setattr(pa.learning_engine, "record_snapshots", boom)
    md, synthese = pa.executer_apprentissage([_resultat()], "2026-09-23")
    assert synthese is None
    assert "Section indisponible" in "\n".join(md) and "panne simulee" in "\n".join(md)


def test_apprentissage_desactivable_par_le_profil(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pa, "PROFILE", {"settings": {"apprentissage": {"actif": False}}})
    assert pa.executer_apprentissage([_resultat()], "2026-09-23") == ([], None)


def test_les_classes_sans_indice_actions_ne_sont_pas_apprises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pa, "USER", "u")
    monkeypatch.setattr(pa, "HISTORY_PATH", "reports/u/history.csv")
    monkeypatch.setattr(pa, "PROFILE", {})
    monkeypatch.setattr(pa, "_apprentissage_cours", lambda *a: None)
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, m=None: ({}, ""))
    pa.executer_apprentissage([_resultat("BTC-USD.CC", "Bitcoin", classe="crypto")],
                              "2026-09-23")
    assert le.load_store(le.pool_dir())["snapshots"] == []


def test_ligne_de_fiabilite_par_valeur():
    assert pa.ligne_fiabilite_md(None, "X") == ""
    syn = {"horizon": 60, "positions": [
        {"ticker": "X.US", "horizons": {"60": {
            "band": "6 - 7,5", "estimate": 2.4, "ci95": [-1.0, 5.8], "p_outperf": 0.58,
            "confidence": "moyenne", "n_indep": 34, "kind": "sector"}}},
        {"ticker": "Y.US", "horizons": {"60": {
            "band": ">= 7,5", "estimate": None, "n_indep": 2,
            "confidence": "insuffisante"}}}]}
    ok = pa.ligne_fiabilite_md(syn, "X.US")
    assert "+2.4%" in ok and "58%" in ok and "moyenne" in ok and "pas une prevision" in ok
    assert "insuffisant" in pa.ligne_fiabilite_md(syn, "Y.US")
    assert pa.ligne_fiabilite_md(syn, "INCONNU") == ""


def test_profil_secteur_saisi_et_reglage_borne():
    from api.load_portfolio import normalize_profile
    prof = normalize_profile(
        {"lines": [{"name": "A", "ticker": "AAPL", "quantity": 1, "buy_price": 10,
                    "market": "us", "sector": "Technology"}],
         "settings": {"apprentissage": {"horizon": 9999, "horizons": [45, -3]}}}, "u")
    assert prof["lines"][0]["sector"] == "Technology"
    app = prof["settings"]["apprentissage"]
    assert app["horizon"] == le.DEFAULT_HORIZON and 45 in app["horizons"]
    json.dumps(app)                     # serialisable tel quel (pas de tuple)
