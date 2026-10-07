"""Univers d'apprentissage (07/10/2026)."""

import collections
import json
import random
from datetime import date, timedelta

import learning_engine as le
import portfolio_analyzer as pa

GICS = {"Information Technology", "Health Care", "Financials", "Consumer Discretionary",
        "Consumer Staples", "Industrials", "Energy", "Materials", "Utilities",
        "Real Estate", "Communication Services"}


def test_fichier_univers_220_titres_11_secteurs():
    titres, pas = pa.charger_univers()
    assert pas == 5
    assert len(titres) == 220
    secteurs = collections.Counter(le.normalize_sector(a["sector"]) for a in titres)
    assert set(secteurs) == GICS
    assert all(n == 20 for n in secteurs.values())
    # Pas de doublon, uniquement des places en euro ou en dollar.
    assert len({a["ticker_eod"] for a in titres}) == 220
    assert {a["devise"] for a in titres} <= {"EUR", "USD"}
    # Chaque titre trouve une reference de marche ; les secteurs couverts en
    # Europe trouvent aussi leur reference sectorielle.
    cfg = le.load_config()
    for a in titres:
        refs = le.resolve_refs(a["ticker_eod"], a["sector"], cfg)
        assert refs["market_ref"], a["ticker_eod"]
        if refs["region"] == "US":
            assert refs["sector_ref"], a["ticker_eod"]


def test_univers_sans_place_ni_titre_ecarte_a_la_verification():
    # Verification du 07/10/2026 sur EODHD : la Borsa Italiana (.MI) n'est pas
    # couverte (fiches 404) ; Dominion (rachat NextEra) et Akzo Nobel (fusion
    # Axalta) vont disparaitre de la cote ; Corteva et DuPont ont une scission
    # dans leur historique d'un an.
    titres, _ = pa.charger_univers()
    assert not [a for a in titres if a["ticker_eod"].endswith(".MI")]
    ecartes = {"D.US", "AKZA.AS", "CTVA.US", "DD.US"}
    assert not ecartes & {a["ticker_eod"] for a in titres}


def test_rotation_chaque_titre_une_fois_par_semaine():
    titres, pas = pa.charger_univers()
    vus = collections.Counter()
    d = date(2026, 10, 5)                       # un lundi
    for i in range(7):                          # lundi -> dimanche
        jour = d + timedelta(days=i)
        if jour.weekday() < 5:
            for a in pa.univers_du_jour(titres, pas, jour):
                vus[a["ticker_eod"]] += 1
    assert len(vus) == 220 and set(vus.values()) == {1}
    # Environ 44 titres par soir, tous les secteurs representes chaque soir.
    du_jour = pa.univers_du_jour(titres, pas, d)
    assert 40 <= len(du_jour) <= 48
    assert {a["sector"] for a in du_jour} == GICS


def test_ignorer_epargne_les_titres_du_jour_et_ceux_detenus():
    titres, pas = pa.charger_univers()
    jour = date(2026, 10, 7)
    du_jour = {a["ticker_eod"] for a in pa.univers_du_jour(titres, pas, jour)}
    hors_jour = next(a["ticker_eod"] for a in titres if a["ticker_eod"] not in du_jour)
    ign = pa._univers_ignorer(jour, {hors_jour})
    assert not (ign & du_jour)
    assert hors_jour not in ign
    assert len(ign) == 220 - len(du_jour) - 1


def test_mature_ignorer_laisse_ouvert_sans_perdre(tmp_path):
    ldir = str(tmp_path)
    ds = [(date(2027, 1, 4) + timedelta(days=i)) for i in range(120)]
    ds = [d.isoformat() for d in ds if d.weekday() < 5]
    cl = [100 + i for i in range(len(ds))]
    snap = le.build_snapshot("_pool", "AAA.US", "A", ds[0], 7.0, 100, {}, "v", "action",
                             "", "", le.DEFAULT_CONFIG, devise="USD")
    snap["sector_ref"] = snap["market_ref"] = None
    le.record_snapshots(ldir, [snap])
    raw = lambda sym, d0, d1: (ds, cl)
    b1 = le.mature(ldir, [20], le.CachedFetcher(raw), ds[-1], ignorer={"AAA.US"})
    assert b1["candidats"] == 0
    b2 = le.mature(ldir, [20], le.CachedFetcher(raw), ds[-1])
    assert b2["clotures"] == 1


def test_apprendre_univers_note_et_verse_au_journal(tmp_path, monkeypatch):
    titres, pas = pa.charger_univers()
    jour = date(2026, 10, 7)
    du_jour = pa.univers_du_jour(titres, pas, jour)
    ds = [(jour - timedelta(days=i)) for i in range(400, -1, -1)]
    ds = [d.isoformat() for d in ds if d.weekday() < 5]
    rng = random.Random(1)
    cl = [100.0]
    for _ in ds[1:]:
        cl.append(cl[-1] * (1 + rng.gauss(0, 0.01)))
    appels = []

    def raw(sym, d0, d1):
        appels.append(sym)
        return ds, cl

    fetcher = le.CachedFetcher(raw)
    monkeypatch.setattr(pa, "_fetcher_apprentissage", lambda j: fetcher)
    monkeypatch.setattr(pa, "get_fundamentals",
                        lambda a: ({"per": 15.0, "marge_nette": 0.12, "croiss_ca": 0.06,
                                    "roe": 0.15, "beta": 1.0}, "test"))
    monkeypatch.setattr(pa, "get_consensus", lambda a: (6.5, "test", "test"))
    monkeypatch.setattr(pa, "UNIVERS_PAUSE_YAHOO", 0)
    monkeypatch.setattr(le, "pool_dir", lambda base="reports": str(tmp_path))
    monkeypatch.setattr(pa, "_fenetre_courte",
                        lambda d, c, days=pa.HISTORY_DAYS: (d[-125:], c[-125:]))
    pa._MEMO["fx:eur_usd"] = (0.9, "test", False, None)
    deja = du_jour[0]["ticker_eod"]
    bilan = pa.apprendre_univers(jour.isoformat(), detenus={deja})
    assert bilan["motif"] is None, bilan
    assert bilan["deja_suivis"] == 1
    assert bilan["notes"] == len(du_jour) - 1
    store = le.load_store(str(tmp_path))
    assert len(store["snapshots"]) == len(du_jour) - 1
    assert all(s["source"] == "univers" and s["user"] == le.POOL_USER
               for s in store["snapshots"])
    # Un seul chargement par titre, aucun pour le titre deja suivi.
    assert deja not in appels
    assert len(set(appels)) == len(appels)
    # Relancer le meme soir ne cree rien.
    pa.apprendre_univers(jour.isoformat(), detenus={deja})
    assert len(le.load_store(str(tmp_path))["snapshots"]) == len(du_jour) - 1


def test_univers_desactivable(monkeypatch):
    monkeypatch.setenv("UNIVERS_APPRENTISSAGE", "0")
    assert pa.apprendre_univers("2026-10-07")["motif"].startswith("desactive")
    assert pa._univers_ignorer(date(2026, 10, 7)) == set()
