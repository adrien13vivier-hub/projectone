"""Graphique « base 100 = prix de revient » depuis la date d'achat (07/10/2026)."""

from datetime import date, timedelta

import portfolio_analyzer as pa
from api.load_portfolio import normaliser_date_achat, normaliser_ligne


def _serie(debut, prix):
    """Jours ouvres a partir de `debut`, un cours par jour."""
    ds, d = [], debut
    while len(ds) < len(prix):
        if d.weekday() < 5:
            ds.append(d.isoformat())
        d += timedelta(days=1)
    return ds, list(prix)


def _pos(nom, ds, cs, pru, cal, cours=None):
    return {"nom": nom, "dates": ds, "closes": cs, "pru": pru,
            "cours": cours, "calendrier": cal}


# --- La reference ne glisse plus -------------------------------------------

def test_valeur_ne_depend_que_du_cours_et_du_prix_de_revient():
    ds, cs = _serie(date(2026, 6, 1), [50 + i for i in range(60)])
    p = [_pos("A", ds, cs, 50.0, [(None, 3)])]
    j1 = pa.donnees_base100(p, ds[-2])
    j2 = pa.donnees_base100(p, ds[-1])
    v1 = dict(zip(j1["dates"], j1["lignes"]["A"]))
    v2 = dict(zip(j2["dates"], j2["lignes"]["A"]))
    communs = set(v1) & set(v2)
    assert len(communs) > 50
    assert all(v1[d] == v2[d] for d in communs)       # rien ne bouge d'un soir a l'autre
    assert v2[date.fromisoformat(ds[-1])] == round(cs[-1] / 50 * 100, 2)


def test_la_courbe_part_de_la_date_d_achat():
    ds, cs = _serie(date(2026, 6, 1), [100.0] * 40)
    achat = date.fromisoformat(ds[10])
    autre = _pos("B", ds, cs, 100.0, [(date.fromisoformat(ds[0]), 1)])
    p = [_pos("A", ds, cs, 100.0, [(achat, 2)]), autre]
    d = pa.donnees_base100(p, ds[-1])
    vals = dict(zip(d["dates"], d["lignes"]["A"]))
    assert all(v is None for k, v in vals.items() if k < achat)
    assert vals[achat] == 100.0
    assert d["debut"] == date.fromisoformat(ds[0])   # le plus ancien achat


def test_cours_du_jour_ajoute_en_bout_de_serie():
    ds, cs = _serie(date(2026, 9, 1), [10.0] * 20)
    seance = date.fromisoformat(ds[-1]) + timedelta(days=1)
    while seance.weekday() >= 5:
        seance += timedelta(days=1)
    d = pa.donnees_base100([_pos("A", ds, cs, 10.0, [(None, 1)], cours=11.0)], seance)
    assert d["dates"][-1] == seance and d["lignes"]["A"][-1] == 110.0


def test_historique_limite_a_un_an_signale():
    ds, cs = _serie(date(2025, 8, 1), [10.0] * 300)
    d = pa.donnees_base100([_pos("A", ds, cs, 10.0, [(date(2024, 1, 2), 1)])],
                           ds[-1], profondeur_jours=200)
    assert d["tronque"] is True
    assert (date.fromisoformat(ds[-1]) - d["debut"]).days <= 200


# --- Courbe du portefeuille : rendement pondere dans le temps -----------------

def test_un_achat_ne_fait_pas_sauter_la_courbe_portefeuille():
    ds, cs = _serie(date(2026, 6, 1), [100.0] * 30)
    ds2, cs2 = ds, [40.0] * 30                      # cours plat, PRU tres different
    p = [_pos("A", ds, cs, 80.0, [(date.fromisoformat(ds[0]), 1)]),
         _pos("B", ds2, cs2, 40.0, [(date.fromisoformat(ds[15]), 10)])]
    pf = pa.donnees_base100(p, ds[-1])["portefeuille"]
    assert all(v == 100.0 for v in pf)                # aucun cours n'a bouge


def test_twr_suit_les_cours_ponderes_par_la_valeur():
    ds, _ = _serie(date(2026, 6, 1), [0] * 3)
    a = _pos("A", ds, [100.0, 110.0, 99.0], 100.0, [(None, 1)])
    b = _pos("B", ds, [100.0, 100.0, 100.0], 100.0, [(None, 1)])
    pf = pa.donnees_base100([a, b], ds[-1])["portefeuille"]
    assert pf[0] == 100.0
    assert pf[1] == 105.0                              # +10 % sur la moitie
    # Jour 3 : A pese 110/210 la veille et perd 10 %.
    assert abs(pf[2] - 105.0 * (1 + (99 - 110) / 210)) < 0.01


# --- Calendrier de detention -----------------------------------------------

def test_calendrier_priorites_et_prorata():
    a = {"qty": 10, "achat_date": "2026-03-02",
         "achats": [{"qte": 8, "prix": 5, "date": ""},
                    {"qte": 12, "prix": 6, "date": "2026-05-04"}]}
    cal = pa.calendrier_detention(a, date(2026, 6, 1))
    # Date de l'achat > date de la ligne > debut du suivi ; somme = qty.
    assert cal == [(date(2026, 3, 2), 4.0), (date(2026, 5, 4), 6.0)]
    assert pa.calendrier_detention({"qty": 3}, date(2026, 6, 1)) == [(date(2026, 6, 1), 3.0)]
    assert pa.calendrier_detention({"qty": 3}) == [(None, 3.0)]
    assert pa.calendrier_detention({"qty": 0}) == []
    # Date future ou illisible : ignoree.
    assert pa.calendrier_detention({"qty": 1, "achat_date": "2099-01-01"}) == [(None, 1.0)]


def test_debut_du_suivi_repart_apres_une_revente(tmp_path):
    def jours(a, b):
        d, out = date.fromisoformat(a), []
        while d <= date.fromisoformat(b):
            if d.weekday() < 5:
                out.append(d.isoformat())
            d += timedelta(days=1)
        return out
    # Le programme ne tourne pas du 21 au 29 mai (panne generale).
    runs = [j for j in jours("2026-05-13", "2026-07-01") if not "2026-05-21" <= j <= "2026-05-29"]
    lignes = ["date,time,ticker,name"]
    for j in runs:
        lignes.append(f"{j},21:00,CCC.US,C")
        # AAA : detenue, revendue debut juin (absente de nombreux runs), rachetee fin juin.
        if j <= "2026-06-03" or j >= "2026-06-29":
            lignes.append(f"{j},21:00,AAA.US,A")
        # BBB : deux soirs sans cours (panne fournisseur) : detention continue.
        if j not in ("2026-06-10", "2026-06-11"):
            lignes.append(f"{j},21:00,BBB.PA,B")
    f = tmp_path / "history.csv"
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    debuts = pa.dates_debut_suivi(str(f))
    assert debuts["AAA.US"] == date(2026, 6, 29)
    assert debuts["BBB.PA"] == date(2026, 5, 13)   # ni la panne generale ni 2 soirs
    assert debuts["CCC.US"] == date(2026, 5, 13)
    assert pa.dates_debut_suivi(str(tmp_path / "absent.csv")) == {}


# --- Rendu -------------------------------------------------------------------

def test_png_genere(tmp_path):
    ds, cs = _serie(date(2026, 4, 1), [20 + (i % 7) for i in range(120)])
    ds2, cs2 = _serie(date(2026, 4, 1), [50 - (i % 5) for i in range(120)])
    p = [_pos("A", ds, cs, 21.0, [(date.fromisoformat(ds[5]), 4)]),
         _pos("B", ds2, cs2, 48.0, [(None, 2)])]
    chemin = tmp_path / "c.png"
    assert pa.generate_combined_chart(p, str(chemin), seance=ds[-1]) is True
    assert chemin.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert pa.generate_combined_chart([], str(tmp_path / "vide.png")) is False


# --- Saisie de la date d'achat ------------------------------------------------

def test_normaliser_date_achat():
    assert normaliser_date_achat("2026-03-14") == "2026-03-14"
    assert normaliser_date_achat("2026-03-14T10:00:00") == "2026-03-14"
    assert normaliser_date_achat("") == ""
    assert normaliser_date_achat(None) == ""
    assert normaliser_date_achat("14/03/2026") == ""
    assert normaliser_date_achat("2099-01-01") == ""


def test_la_ligne_transporte_sa_date_d_achat():
    base = {"name": "Air Liquide", "ticker": "AI.PA", "market": "euronext_paris",
            "quantity": 3, "buy_price": 150}
    assert normaliser_ligne({**base, "achat_date": "2026-02-10"})["achat_date"] == "2026-02-10"
    assert normaliser_ligne(base)["achat_date"] == ""
