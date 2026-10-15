"""Niveaux de note (15/10/2026) : le rapport decrit le titre, il ne conseille pas.

Les anciens avis (RENFORCER / CONSERVER / SURVEILLER / ALLEGER / SORTIR /
A EXAMINER) disaient quoi faire et dependaient en partie de la situation du
detenteur (« en moins-value ») : une recommandation personnalisee, c'est-a-dire
du conseil en investissement. Ces tests verrouillent le nouveau vocabulaire.
"""

import learning_engine as le
import portfolio_analyzer as pa

MOTS_PRESCRIPTIFS = ("RENFORCER", "CONSERVER", "SURVEILLER", "ALLEGER", "ALLÉGER",
                     "SORTIR", "EXAMINER", "ACHAT", "VENDRE", "GARDER", "EVITER")


def test_seuils_inchanges():
    assert pa.recommend(9.0) == "NOTE ÉLEVÉE"
    assert pa.recommend(7.5) == "NOTE ÉLEVÉE"
    assert pa.recommend(7.49) == "NOTE SOLIDE"
    assert pa.recommend(6.0) == "NOTE SOLIDE"
    assert pa.recommend(5.0) == "NOTE MOYENNE"
    assert pa.recommend(4.5) == "NOTE MOYENNE"
    assert pa.recommend(3.0) == "NOTE FAIBLE"
    assert pa.recommend(2.9) == "NOTE TRÈS FAIBLE"
    assert pa.recommend(0.0) == "NOTE TRÈS FAIBLE"


def test_garde_fous():
    assert pa.recommend(None) == "DONNÉES INSUFFISANTES"
    assert pa.recommend(8.0, confiance=30) == "NOTE INCOMPLÈTE (données partielles)"
    assert pa.recommend(8.0, nb_criteres=2) == "NOTE INCOMPLÈTE (peu de critères)"


def test_le_niveau_ne_depend_pas_de_la_situation_du_detenteur():
    """Meme titre, meme note -> meme niveau, en gain comme en perte."""
    for note in (2.0, 3.5, 5.0, 6.5, 8.0):
        assert pa.recommend(note, pnl_net_pct=-40.0) == pa.recommend(note, pnl_net_pct=40.0)


def test_aucun_mot_prescriptif():
    sorties = {pa.recommend(n / 10, c, p, k)
               for n in range(0, 101, 5) for c in (20, 100)
               for p in (-30.0, 30.0) for k in (2, 6)}
    sorties.add(pa.recommend(None))
    for s in sorties:
        assert not any(m in s.upper() for m in MOTS_PRESCRIPTIFS), s


def test_tranches_du_moteur_d_apprentissage_alignees():
    """Le tableau « Fiabilite des notes » parle le meme langage que le rapport."""
    niveaux = {lib for _, lib in pa.NIVEAUX_NOTE}
    assert {b[3] for b in le.BANDS} == niveaux
    for lo, hi, _, lib in le.BANDS:
        assert pa.recommend(lo) == lib
