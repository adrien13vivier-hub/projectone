"""Tests pytest pour les fonctions pures de portfolio_analyzer.py.

Volontairement limite aux fonctions qui ne font ni reseau ni I/O : le but
est de proteger la logique de notation et de gestion de risque contre une
regression silencieuse, pas de retester les integrations API (deja couvertes
par le fallback cache et les protocoles de validation croisee decrits dans
le README).

L'import de portfolio_analyzer imprime des avertissements "cle API absente" :
c'est attendu hors GitHub Actions, ce n'est pas un echec de test.
"""
import portfolio_analyzer as pa


# ─────────────────────────────────────────────────────────────────────────
# slugify -- identifiants de dossier
# ─────────────────────────────────────────────────────────────────────────

def test_slugify_normalise_casse_et_espaces():
    assert pa.slugify("Pete33") == "pete33"
    assert pa.slugify("  Jean Dupont  ") == "jean-dupont"


def test_slugify_vide_ou_none_retombe_sur_default():
    assert pa.slugify("") == "default"
    assert pa.slugify(None) == "default"


def test_slugify_est_idempotent():
    # Propriete utile pour le bug corrige en v8.1 (connexion avec son propre
    # identifiant) : re-slugifier un slug ne doit rien changer.
    s = pa.slugify("Pete 33 !!")
    assert pa.slugify(s) == s


# ─────────────────────────────────────────────────────────────────────────
# Paliers -- briques de tous les scores
# ─────────────────────────────────────────────────────────────────────────

PALIERS_CROISSANTS = [(40, 10), (25, 9), (15, 7.5), (5, 6), (0, 4.5),
                      (-20, 2.5), (-float("inf"), 1)]


def test_palier_croissant_prend_le_meilleur_seuil_atteint():
    assert pa._palier(50, PALIERS_CROISSANTS) == 10       # au-dessus du plus haut seuil
    assert pa._palier(10, PALIERS_CROISSANTS) == 6         # entre 5 et 15
    assert pa._palier(-100, PALIERS_CROISSANTS) == 1        # sous tous les seuils


def test_palier_inverse_recompense_la_valeur_basse():
    paliers = [(10, 10), (20, 7), (30, 4), (float("inf"), 1)]
    assert pa._palier_inverse(5, paliers) == 10   # PER bas -> bonne note
    assert pa._palier_inverse(25, paliers) == 4
    assert pa._palier_inverse(1000, paliers) == 1  # PER delirant -> pire note


# ─────────────────────────────────────────────────────────────────────────
# note_titre -- ponderation avec exclusion des composantes manquantes
# ─────────────────────────────────────────────────────────────────────────

def test_note_titre_toutes_composantes_disponibles():
    composantes = {k: 8.0 for k in pa.POIDS_NOTE}
    note, confiance, detail = pa.note_titre(composantes)
    assert note == 8.0
    assert confiance == 100.0
    assert set(detail) == set(pa.POIDS_NOTE)


def test_note_titre_composante_absente_est_exclue_et_renormalisee():
    composantes = {k: 8.0 for k in pa.POIDS_NOTE}
    composantes["risque"] = None   # absente : ne doit PAS etre traitee comme 0
    note, confiance, detail = pa.note_titre(composantes)
    assert note == 8.0             # toutes les composantes restantes valent 8
    assert confiance < 100.0
    assert "risque" not in detail


def test_note_titre_aucune_composante_disponible():
    note, confiance, detail = pa.note_titre({})
    assert note is None
    assert confiance == 0.0
    assert detail == {}


def test_note_titre_confiance_reflete_le_poids_couvert():
    # Ne fournir que "valorisation" (poids 0.24 sur un total de 1.0) doit
    # donner une confiance proche de 24%, pas un chiffre arbitraire.
    note, confiance, _ = pa.note_titre({"valorisation": 9.0})
    assert note == 9.0
    assert abs(confiance - pa.POIDS_NOTE["valorisation"] * 100) < 0.5


# ─────────────────────────────────────────────────────────────────────────
# _parse_serie -- desormais definie une seule fois dans le fichier
# ─────────────────────────────────────────────────────────────────────────

def test_parse_serie_nest_plus_dupliquee_dans_le_fichier():
    import inspect
    source = inspect.getsource(pa)
    assert source.count("def _parse_serie(") == 1


def test_parse_serie_trie_et_tolere_le_format_annee_mois():
    dates = ["2026-03", "2026-01-15", "2026-02-01"]
    closes = [110, 100, 105]
    serie = pa._parse_serie(dates, closes)
    assert [px for _, px in serie] == [100, 105, 110]   # remis dans l'ordre chronologique


def test_parse_serie_ignore_les_points_invalides():
    dates = ["2026-01-01", "date-invalide", "2026-01-03"]
    closes = [100, 999, -5]   # -5 est un prix invalide, "date-invalide" aussi
    serie = pa._parse_serie(dates, closes)
    assert len(serie) == 1


# ─────────────────────────────────────────────────────────────────────────
# score_history -- momentum avec penalite de surchauffe
# ─────────────────────────────────────────────────────────────────────────

def _serie_perf(pct_6m, jours=181, base=100.0):
    """Deux points : aujourd'hui et il y a `jours` jours, avec une
    performance de `pct_6m` % entre les deux. Suffisant pour score_history,
    qui ne regarde que le point le plus proche de chaque horizon."""
    from datetime import datetime, timedelta
    fin = datetime(2026, 6, 1)
    debut = fin - timedelta(days=jours)
    return ([debut.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")],
            [base, base * (1 + pct_6m / 100.0)])


def test_score_history_hausse_moderee_est_haussier():
    dates, closes = _serie_perf(20)
    note, label, *_ = pa.score_history(dates, closes)
    assert label == "HAUSSIER"
    assert note > 5.0


def test_score_history_baisse_est_baissier():
    dates, closes = _serie_perf(-30)
    note, label, *_ = pa.score_history(dates, closes)
    assert label == "BAISSIER"
    assert note < 5.0


def test_score_history_surchauffe_penalise_une_hausse_extreme():
    # Deux hausses fortes sur 6 mois ; au-dela de 100%, une penalite
    # supplementaire s'applique. La note ne doit pas continuer a grimper avec
    # la performance passe un certain point.
    _, closes_forte = _serie_perf(70)
    _, closes_extreme = _serie_perf(150)
    dates, _ = _serie_perf(70)
    note_forte, *_ = pa.score_history(dates, closes_forte)
    note_extreme, *_ = pa.score_history(dates, closes_extreme)
    assert note_extreme <= note_forte


def test_score_history_serie_trop_courte_est_indisponible():
    note, label, *_ = pa.score_history(["2026-01-01"], [100])
    assert note is None
    assert label == "INDISPONIBLE"


# ─────────────────────────────────────────────────────────────────────────
# bloc_md_exposition_correlee -- rendu markdown de la nouvelle section
# ─────────────────────────────────────────────────────────────────────────

def test_bloc_md_exposition_correlee_sans_groupe():
    lignes = pa.bloc_md_exposition_correlee([])
    texte = "\n".join(lignes)
    assert "### Exposition corrélée" in texte
    assert "Aucun regroupement" in texte


def test_bloc_md_exposition_correlee_avec_groupe_en_alerte():
    groupes = [{"lignes": ["A", "B"], "poids_pct": 30.0, "alerte": True}]
    lignes = pa.bloc_md_exposition_correlee(groupes)
    texte = "\n".join(lignes)
    assert "A, B" in texte
    assert "⚠️ Oui" in texte
    assert "30" in texte
