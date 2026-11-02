"""Places de cotation (02/11/2026).

Deux causes de lignes SANS COURS, donc absentes du rapport :
- des actions etrangeres cotees a Francfort (BYD, Daikin, Xiaomi) saisies en
  « Xetra », place ou EODHD ne les publie pas ;
- un ticker a suffixe explicite (SAP.DE, RHM.DE) laisse sur la place « us »
  proposee par defaut, qui l'envoyait sur le mauvais titre ou sur rien.
"""

from api import load_portfolio as lp


def test_francfort_existe_avec_le_suffixe_eodhd():
    assert lp.MARCHES["francfort"]["suffixe"] == ".F"
    assert lp.MARCHES["francfort"]["devise"] == "EUR"
    t = lp.deriver_tickers("BY6", "francfort")
    assert t["ticker_eod"] == "BY6.F"
    assert t["ticker_yf"] == "BY6.F"


def test_suffixe_explicite_l_emporte_sur_la_place_us_par_defaut():
    assert lp.detecter_marche("SAP.DE", "us") == "xetra"
    assert lp.detecter_marche("RHM.DE", "us") == "xetra"
    assert lp.detecter_marche("BY6.F", "us") == "francfort"
    assert lp.detecter_marche("VOD.L", None) == "londres"


def test_une_place_choisie_expressement_reste_prioritaire():
    assert lp.detecter_marche("IFX", "xetra") == "xetra"
    assert lp.detecter_marche("AAPL", "us") == "us"
    assert lp.detecter_marche("ACA.PA", "euronext_paris") == "euronext_paris"
    assert lp.detecter_marche("BRK.B", "us") == "us"          # « B » n'est pas une place


def test_alias():
    assert lp.detecter_marche("BY6", "frankfurt") == "francfort"
    assert lp.detecter_marche("SAP", "allemagne") == "xetra"
