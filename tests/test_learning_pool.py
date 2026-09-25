"""MUTUALISATION du moteur d'apprentissage : un journal commun, anonyme et
dedoublonne, alimente par tous les profils qui l'acceptent.
"""
import json
import os
from datetime import date, timedelta

import learning_engine as le
import portfolio_analyzer as pa

ENTETE = ("date,time,ticker,name,price_eur,cost_eur,qty,vm,pnl_brut,pnl_brut_pct,"
          "pnl_net,pnl_net_pct,score,confiance,rec\n")


def seances(debut="2026-01-05", n=320):
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


def _environnement(monkeypatch, tmp_path, appels=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, m=None: ({"sector": "Technology"}, ""))
    ds = seances()

    def cours(sym, debut, fin):
        if appels is not None:
            appels.append(sym)
        pente = {"SPY.US": 0.1, "XLK.US": 0.2}.get(sym, 0.5)
        return ds, [100 + pente * i for i in range(len(ds))]
    monkeypatch.setattr(pa, "_apprentissage_cours", cours)


def _profil(monkeypatch, user, settings=None):
    monkeypatch.setattr(pa, "USER", user)
    monkeypatch.setattr(pa, "HISTORY_PATH", f"reports/{user}/history.csv")
    monkeypatch.setattr(pa, "PROFILE", {"settings": {"apprentissage": settings or {}}})


def test_deux_profils_meme_titre_meme_jour_un_seul_snapshot(tmp_path, monkeypatch):
    _environnement(monkeypatch, tmp_path)
    for user in ("alice", "bob"):
        _profil(monkeypatch, user)
        pa.executer_apprentissage([_resultat("CRWV.US")], "2026-09-23")
    snaps = le.load_store(le.pool_dir())["snapshots"]
    assert len([s for s in snaps if s["as_of"] == "2026-09-23"]) == 1   # pas de double compte
    for user in ("alice", "bob"):                     # chacun a SA synthese, SES positions
        syn = json.load(open(f"reports/{user}/learning/summary.json", encoding="utf-8"))
        assert [p["ticker"] for p in syn["positions"]] == ["CRWV.US"] and syn["mutualise"]


def test_le_pool_est_l_union_des_titres_de_tous_les_profils(tmp_path, monkeypatch):
    _environnement(monkeypatch, tmp_path)
    _profil(monkeypatch, "alice")
    pa.executer_apprentissage([_resultat("AAA.US", "A"), _resultat("BBB.US", "B")], "2026-09-23")
    _profil(monkeypatch, "bob")
    pa.executer_apprentissage([_resultat("BBB.US", "B"), _resultat("CCC.PA", "C")], "2026-09-23")
    tickers = {s["ticker"] for s in le.load_store(le.pool_dir())["snapshots"]}
    assert tickers == {"AAA.US", "BBB.US", "CCC.PA"}
    syn = json.load(open("reports/bob/learning/summary.json", encoding="utf-8"))
    assert syn["counts"]["n_tickers"] == 3            # Bob profite des titres d'Alice
    assert {p["ticker"] for p in syn["positions"]} == {"BBB.US", "CCC.PA"}


def test_le_pool_est_anonyme_aucune_donnee_personnelle(tmp_path, monkeypatch):
    _environnement(monkeypatch, tmp_path)
    (tmp_path / "reports" / "alice").mkdir(parents=True)
    (tmp_path / "reports" / "alice" / "history.csv").write_text(
        ENTETE + "2026-03-02,22:40,AAA.US,Aaa,100,777.77,4242,1,1,1,1,1,6.5,,GARDER\n",
        encoding="utf-8")
    _profil(monkeypatch, "alice")
    r = _resultat("AAA.US")
    r["asset"]["account"] = "PEA-secret"
    pa.executer_apprentissage([r], "2026-09-23")
    contenu = ""
    for racine, _, fichiers in os.walk(le.pool_dir()):
        for f in fichiers:
            contenu += open(os.path.join(racine, f), encoding="utf-8").read()
    assert contenu
    for secret in ("alice", "777.77", "4242", "PEA-secret"):
        assert secret not in contenu, f"« {secret} » a fuite dans le pool"
    assert all(s["user"] == le.POOL_USER for s in le.load_store(le.pool_dir())["snapshots"])


def test_refus_de_mutualiser_journal_prive_isole(tmp_path, monkeypatch):
    _environnement(monkeypatch, tmp_path)
    _profil(monkeypatch, "prive", {"mutualiser": False})
    pa.executer_apprentissage([_resultat("AAA.US")], "2026-09-23")
    assert not os.path.exists(le.pool_dir())                  # rien n'est partage
    priv = le.load_store(os.path.join("reports", "prive", "learning"))["snapshots"]
    assert [s["user"] for s in priv] == ["prive"]
    syn = json.load(open("reports/prive/learning/summary.json", encoding="utf-8"))
    assert syn["mutualise"] is False

    _profil(monkeypatch, "alice")                             # un autre profil mutualise
    pa.executer_apprentissage([_resultat("ZZZ.US")], "2026-09-23")
    pool = le.load_store(le.pool_dir())["snapshots"]
    assert {s["ticker"] for s in pool} == {"ZZZ.US"}          # rien du profil prive


def test_un_nom_reserve_ne_contribue_jamais_au_pool(tmp_path, monkeypatch):
    _environnement(monkeypatch, tmp_path)
    _profil(monkeypatch, "_pool")
    pa.executer_apprentissage([_resultat("AAA.US")], "2026-09-23")
    assert not os.path.exists(le.pool_dir())


def test_un_seul_telechargement_par_symbole_pour_tous_les_profils(tmp_path, monkeypatch):
    appels = []
    _environnement(monkeypatch, tmp_path, appels)
    for user in ("alice", "bob", "carol"):
        d = tmp_path / "reports" / user
        d.mkdir(parents=True)
        (d / "history.csv").write_text(
            ENTETE + "2026-02-02,22:40,AAA.US,Aaa,100,1,1,1,1,1,1,1,6.5,,GARDER\n",
            encoding="utf-8")
    for user in ("alice", "bob", "carol"):
        _profil(monkeypatch, user)
        pa.executer_apprentissage([_resultat("AAA.US")], "2026-09-23")
    assert appels.count("SPY.US") == 1 and appels.count("AAA.US") == 1
    herites = [s for s in le.load_store(le.pool_dir())["snapshots"]
               if s["source"] == "backfill_history_csv"]
    assert len(herites) == 1                  # trois historiques identiques, un snapshot


def test_reglage_mutualiser_par_defaut_et_desactivation():
    assert le.normalize_settings({})["mutualiser"] is True
    assert le.normalize_settings({"mutualiser": False})["mutualiser"] is False


def test_le_markdown_annonce_la_mutualisation(tmp_path, monkeypatch):
    _environnement(monkeypatch, tmp_path)
    _profil(monkeypatch, "alice")
    md, _ = pa.executer_apprentissage([_resultat("AAA.US")], "2026-09-23")
    assert "Apprentissage mutualise" in "\n".join(md)
    assert "jamais l'identite" in "\n".join(md)
