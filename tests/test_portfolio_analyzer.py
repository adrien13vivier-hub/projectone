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
#
# Signature depuis la v14 (indice de confiance) :
#   note_titre(composantes, classe="action") ->
#       (note, confiance, detail, non_applicables, manquants)
# Avec classe="action" (le defaut), NON_APPLICABLES n'exclut rien : le
# comportement couvert ici est inchange par rapport a la version d'origine,
# seule la forme du tuple retourne s'est enrichie.
# ─────────────────────────────────────────────────────────────────────────

def test_note_titre_toutes_composantes_disponibles():
    composantes = {k: 8.0 for k in pa.POIDS_NOTE}
    note, confiance, detail, non_appl, manquants = pa.note_titre(composantes)
    assert note == 8.0
    assert confiance == 100.0
    assert set(detail) == set(pa.POIDS_NOTE)
    assert non_appl == []      # aucune exclusion pour la classe "action"
    assert manquants == []


def test_note_titre_composante_absente_est_exclue_et_renormalisee():
    composantes = {k: 8.0 for k in pa.POIDS_NOTE}
    composantes["risque"] = None   # absente : ne doit PAS etre traitee comme 0
    note, confiance, detail, non_appl, manquants = pa.note_titre(composantes)
    assert note == 8.0             # toutes les composantes restantes valent 8
    assert confiance < 100.0
    assert "risque" not in detail
    assert manquants == ["risque"]


def test_note_titre_aucune_composante_disponible():
    note, confiance, detail, non_appl, manquants = pa.note_titre({})
    assert note is None
    assert confiance == 0.0
    assert detail == {}
    assert set(manquants) == set(pa.POIDS_NOTE)   # tout manque


def test_note_titre_confiance_reflete_le_poids_couvert():
    # Ne fournir que "valorisation" (poids 0.24 sur un total de 1.0) doit
    # donner une confiance proche de 24%, pas un chiffre arbitraire.
    note, confiance, *_ = pa.note_titre({"valorisation": 9.0})
    assert note == 9.0
    assert abs(confiance - pa.POIDS_NOTE["valorisation"] * 100) < 0.5


def test_note_titre_exclut_les_criteres_non_applicables_a_la_classe():
    # Un ETF n'a pas de "sante financiere d'entreprise" -- la confiance ne
    # doit pas etre penalisee par l'absence d'un critere qui ne s'applique
    # pas a sa classe d'actif.
    criteres_etf = pa.criteres_applicables("etf")
    composantes = {k: 8.0 for k in criteres_etf}
    note, confiance, detail, non_appl, manquants = pa.note_titre(
        composantes, classe="etf")
    assert note == 8.0
    assert confiance == 100.0      # tout ce qui s'applique a l'ETF est fourni
    assert manquants == []
    assert set(non_appl) == (set(pa.POIDS_NOTE) - criteres_etf)


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


def test_bloc_md_exposition_correlee_avec_indice():
    indice = {"indice_pct": 42.3, "n_paires": 6, "n_lignes": 4,
             "min_pct": -10.0, "max_pct": 91.0}
    texte = "\n".join(pa.bloc_md_exposition_correlee([], indice))
    assert "Corrélation moyenne du portefeuille : +42.3 %" in texte
    assert "Modérée" in texte
    assert "6 paire(s)" in texte
    assert "4 ligne(s)" in texte


def test_bloc_md_exposition_correlee_sans_indice_disponible():
    # indice_pct absent ou None -- le paragraphe d'indice ne doit pas
    # apparaitre du tout, pas apparaitre avec des valeurs vides.
    texte = "\n".join(pa.bloc_md_exposition_correlee(
        [], {"indice_pct": None, "n_paires": 0, "n_lignes": 1}))
    assert "Corrélation moyenne du portefeuille" not in texte
    assert "Aucun regroupement" in texte


# ─────────────────────────────────────────────────────────────────────────
# append_correlation_history -- fichier dedie, une ligne par jour
# ─────────────────────────────────────────────────────────────────────────

def test_append_correlation_history_ecrit_une_ligne(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "CORR_HISTORY_PATH", str(tmp_path / "correlation_history.csv"))
    from datetime import datetime
    pa.append_correlation_history(datetime(2026, 9, 19), {
        "indice_pct": 42.3, "n_paires": 6, "n_lignes": 4,
        "min_pct": -10.0, "max_pct": 91.0,
    })
    contenu = (tmp_path / "correlation_history.csv").read_text(encoding="utf-8")
    assert "date,indice_pct,n_paires,n_lignes,min_pct,max_pct,classe" in contenu
    assert "2026-09-19,42.3,6,4,-10.0,91.0,Modérée" in contenu


def test_append_correlation_history_indice_indisponible_necrit_rien(tmp_path, monkeypatch):
    chemin = tmp_path / "correlation_history.csv"
    monkeypatch.setattr(pa, "CORR_HISTORY_PATH", str(chemin))
    from datetime import datetime
    pa.append_correlation_history(datetime(2026, 9, 19), {"indice_pct": None})
    assert not chemin.exists()
    pa.append_correlation_history(datetime(2026, 9, 19), None)
    assert not chemin.exists()


def test_append_correlation_history_accumule_plusieurs_jours(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "CORR_HISTORY_PATH", str(tmp_path / "correlation_history.csv"))
    from datetime import datetime
    for jour, val in ((18, 30.0), (19, 42.3)):
        pa.append_correlation_history(datetime(2026, 9, jour), {
            "indice_pct": val, "n_paires": 1, "n_lignes": 2,
            "min_pct": val, "max_pct": val,
        })
    lignes = (tmp_path / "correlation_history.csv").read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 3   # en-tete + 2 jours
    assert lignes[0].startswith("date,")


# ─────────────────────────────────────────────────────────────────────────
# get_price_yahoo -- cours de la watchlist, exclusivement Yahoo Finance
#
# La watchlist ne doit plus jamais consommer TwelveData/EODHD (quota reserve
# au portefeuille reellement detenu) : chaque test monkeypatch
# `_yahoo_summary` pour verifier le comportement sans reseau, comme le fait
# deja `_fonda_yahoo` ailleurs dans le code.
# ─────────────────────────────────────────────────────────────────────────

EUR_USD = 0.92   # 1 USD = 0.92 EUR -- convention de get_eur_usd()/get_fx()


def test_get_price_yahoo_sans_ticker_yf_est_indisponible():
    prix, chg, src, from_cache, note = pa.get_price_yahoo(
        {"ticker_eod": "FOO.US"}, EUR_USD, {})
    assert prix is None
    assert "ticker absent" in src


def test_get_price_yahoo_demande_le_module_price_uniquement(monkeypatch):
    # La watchlist n'a besoin que du cours : demander les modules fondamentaux
    # (plus lourds) gaspillerait un appel et rapprocherait de la limitation
    # de debit Yahoo pour rien.
    vu = {}
    def fake(symbole, modules=None):
        vu["modules"] = modules
        return {"regularMarketPrice": 10.0, "regularMarketPreviousClose": 10.0,
                "currency": "USD"}, ""
    monkeypatch.setattr(pa, "_yahoo_summary", fake)
    pa.get_price_yahoo({"ticker_yf": "SNAP", "ticker_eod": "SNAP.US"}, EUR_USD, {})
    assert vu["modules"] == "price"


def test_get_price_yahoo_convertit_usd_en_euro(monkeypatch):
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, modules=None: (
        {"regularMarketPrice": 10.0, "regularMarketPreviousClose": 9.5,
         "currency": "USD"}, ""))
    prix, chg, src, from_cache, note = pa.get_price_yahoo(
        {"ticker_yf": "SNAP", "ticker_eod": "SNAP.US"}, EUR_USD, {})
    assert prix == round(10.0 * EUR_USD, 4)
    assert chg == round((10.0 - 9.5) / 9.5 * 100, 2)
    assert src == "Yahoo Finance"
    assert from_cache is False
    assert "USD" in note


def test_get_price_yahoo_titre_deja_en_euro_ne_mentionne_aucune_conversion(monkeypatch):
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, modules=None: (
        {"regularMarketPrice": 50.0, "regularMarketPreviousClose": 51.0,
         "currency": "EUR"}, ""))
    prix, chg, src, from_cache, note = pa.get_price_yahoo(
        {"ticker_yf": "AI.PA", "ticker_eod": "AI.PA"}, EUR_USD, {})
    assert prix == 50.0
    assert note is None


def test_get_price_yahoo_gbp_pence_divise_par_cent(monkeypatch):
    # REGRESSION -- Yahoo publie le penny sterling sous le code "GBp" (p
    # minuscule). Mettre ce code en majuscule AVANT de le comparer donne
    # "GBP" (la livre entiere) et fait ressortir un cours cent fois trop
    # haut -- exactement le bogue deja documente pour taux_ligne(). Ce test
    # verifie que get_price_yahoo distingue bien les deux.
    monkeypatch.setattr(pa, "_yahoo_summary", lambda s, modules=None: (
        {"regularMarketPrice": 1000.0, "regularMarketPreviousClose": 990.0,
         "currency": "GBp"}, ""))
    prix, chg, src, from_cache, note = pa.get_price_yahoo(
        {"ticker_yf": "VOD.L", "ticker_eod": "VOD.LSE"}, EUR_USD,
        {"fx_GBP": 1.15})
    assert prix == round(1000.0 * 1.15 / 100.0, 4)
    assert "GBX" in note


def test_get_price_yahoo_echec_retombe_sur_le_cache(monkeypatch):
    monkeypatch.setattr(pa, "_yahoo_summary",
                        lambda s, modules=None: ({}, "429 (limite de debit Yahoo)"))
    cache = {"price_yahoo_SNAP": 12.34, "saved_at": "2026-09-18"}
    prix, chg, src, from_cache, note = pa.get_price_yahoo(
        {"ticker_yf": "SNAP", "ticker_eod": "SNAP.US"}, EUR_USD, cache)
    assert prix == 12.34
    assert from_cache is True
    assert "429" in note


def test_get_price_yahoo_echec_sans_cache_est_indisponible(monkeypatch):
    monkeypatch.setattr(pa, "_yahoo_summary",
                        lambda s, modules=None: ({}, "429 (limite de debit Yahoo)"))
    prix, chg, src, from_cache, note = pa.get_price_yahoo(
        {"ticker_yf": "SNAP", "ticker_eod": "SNAP.US"}, EUR_USD, {})
    assert prix is None
    assert from_cache is False
