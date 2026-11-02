"""Plus-value latente et frais (02/11/2026).

Les courtiers (BoursoBank, Bourse Direct, Fortuneo...) affichent un prix de
revient FRAIS D'ACHAT INCLUS. Recopie dans le programme, ce PRU faisait
deduire les frais d'achat une seconde fois : la plus-value nette du rapport
etait plus pessimiste que la realite (ex. Credit Agricole : -23,08 EUR au
rapport contre -19,06 EUR chez le courtier, dont 1,99 EUR de vente a venir).
"""

import pytest

import portfolio_analyzer as pa

BOURSOBANK = {
    "euronext": {"threshold": 500, "flat": 1.99, "rate": 0.006, "min": 1.99},
    "us": {"threshold": 6000, "flat": 6.95, "rate": 0.0012, "min": 6.95, "change": 0.0021},
}


@pytest.fixture(autouse=True)
def grille_boursobank():
    avant = (pa.BROKERAGE, pa.PRU_FRAIS_INCLUS)
    pa.BROKERAGE = {k: dict(v) for k, v in BOURSOBANK.items()}
    yield
    pa.BROKERAGE, pa.PRU_FRAIS_INCLUS = avant


def test_pru_du_courtier_ne_deduit_que_les_frais_de_vente():
    r = pa.pnl_position(14.99, 16.90, 10, "euronext", frais_inclus=True)
    assert r["brut"] == -19.10                     # = la « +/- value latente » du courtier
    assert r["frais_achat"] == 0.0
    assert r["frais_vente"] == 1.99
    assert r["net"] == -21.09


def test_prix_d_execution_sans_frais_deduit_achat_et_vente():
    r = pa.pnl_position(14.99, 16.90, 10, "euronext", frais_inclus=False)
    assert r["frais_achat"] == 1.99
    assert r["net"] == -23.08                      # ancien comportement, conserve


def test_plafond_pea_sur_la_vente():
    r = pa.pnl_position(7.10, 7.26, 25, "euronext", pea=True, frais_inclus=True)
    assert r["brut"] == -4.0
    assert r["frais_vente"] == round(177.5 * 0.005, 2)
    assert r["net"] == round(-4.0 - 0.89, 2)


def test_titre_us_avec_le_bon_pru_en_euros():
    """SM Energy : PRU courtier 33,88 EUR -> +22,50 EUR, comme l'application."""
    r = pa.pnl_position(36.13, 33.88, 10, "us", frais_inclus=True)
    assert r["brut"] == 22.5
    assert r["net"] < r["brut"]


def test_reglage_lu_dans_le_profil():
    pa.apply_profile({"settings": {"broker": "boursobank", "fees": BOURSOBANK}, "lines": []})
    assert pa.PRU_FRAIS_INCLUS is True             # defaut : PRU de courtier
    pa.apply_profile({"settings": {"fees": BOURSOBANK, "pru_frais_inclus": False}, "lines": []})
    assert pa.PRU_FRAIS_INCLUS is False


def test_ventes_realisees_meme_convention():
    vente = [{"name": "X", "qty": 10, "buy_price_eur": 16.90, "sell_price": 18.0,
              "fx_at_sale": 1.0, "marche": "euronext"}]
    pa.PRU_FRAIS_INCLUS = True
    ops, _ = pa.compute_closed_trades(vente)
    assert ops[0]["frais"] == 1.99                 # vente seulement
    pa.PRU_FRAIS_INCLUS = False
    ops, _ = pa.compute_closed_trades(vente)
    assert ops[0]["frais"] == 3.98                 # achat + vente
