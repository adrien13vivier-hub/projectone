"""Tests pytest pour risk_engine.py.

risk_engine.py a deja sa propre batterie (`python risk_engine.py` ->
_autotest()) : ces tests-ci ne la remplacent pas, ils la complementent avec
un format que CI/pytest sait rapporter test par test, et servent de filet
pour tout retouche future du fichier.

Aucun reseau, aucune cle API : uniquement des donnees synthetiques.
"""
import random
from datetime import date, timedelta

import risk_engine as re_


# ─────────────────────────────────────────────────────────────────────────
# Volatilite
# ─────────────────────────────────────────────────────────────────────────

def _serie_stable(n=40, base=100.0, pas=0.001):
    """Serie qui alterne +pas/-pas : volatilite faible mais non nulle."""
    out, v = [base], base
    for i in range(n - 1):
        v *= (1 + pas) if i % 2 == 0 else (1 - pas)
        out.append(v)
    return out


def test_volatilite_serie_trop_courte_est_indisponible():
    res = re_.volatilite([100, 101, 99])
    assert res["vol_ann_pct"] is None
    assert res["fiable"] is False


def test_volatilite_serie_suffisante_est_publiee():
    res = re_.volatilite(_serie_stable(40))
    assert res["vol_ann_pct"] is not None
    assert res["vol_ann_pct"] >= 0
    assert res["vq_pct"] is not None
    assert re_.VQ_MIN <= res["vq_pct"] <= re_.VQ_MAX


def test_volatilite_ignore_valeurs_invalides():
    # Zeros, negatifs et None ne doivent pas faire planter le calcul.
    serie = _serie_stable(40) + [0, -5, None, "NA"]
    res = re_.volatilite(serie)
    assert res["n_obs"] == 40   # les valeurs invalides sont filtrees, pas comptees


# ─────────────────────────────────────────────────────────────────────────
# evaluer_stop -- les quatre types
# ─────────────────────────────────────────────────────────────────────────

def test_stop_percent_sous_le_prix_de_revient():
    res = re_.evaluer_stop(
        ligne={"stop": {"type": "percent", "value": 20}},
        cours=85, cout=100, closes=None)
    assert res["niveau"] == 80.0
    assert res["statut"] == re_.STATUT_OK


def test_stop_percent_franchi_declenche_une_alerte():
    res = re_.evaluer_stop(
        ligne={"stop": {"type": "percent", "value": 20}},
        cours=75, cout=100, closes=None)
    assert res["statut"] == re_.STATUT_FRANCHI
    assert res["alerte"] is True
    # Le declencheur se desarme : un second calcul sans etat exterieur qui
    # simule "deja alerte hier" ne doit pas re-alerter.
    res2 = re_.evaluer_stop(
        ligne={"stop": {"type": "percent", "value": 20}},
        cours=70, cout=100, closes=None, etat_ligne=res["etat"])
    assert res2["statut"] == re_.STATUT_FRANCHI
    assert res2["alerte"] is False


def test_stop_franchi_se_reamorce_au_retour_au_dessus():
    cfg = {"stop": {"type": "percent", "value": 20}}
    sous = re_.evaluer_stop(ligne=cfg, cours=70, cout=100, closes=None)
    assert sous["alerte"] is True
    dessus = re_.evaluer_stop(ligne=cfg, cours=90, cout=100, closes=None,
                              etat_ligne=sous["etat"])
    assert dessus["statut"] == re_.STATUT_OK
    re_franchi = re_.evaluer_stop(ligne=cfg, cours=70, cout=100, closes=None,
                                  etat_ligne=dessus["etat"])
    assert re_franchi["alerte"] is True   # nouvelle alerte, nouveau franchissement


def test_stop_absolute_en_devise_etrangere_est_converti():
    res = re_.evaluer_stop(
        ligne={"stop": {"type": "absolute", "value": 180, "devise": "USD"}},
        cours=150, cout=100, closes=None, eur_par_devise=0.9)
    assert res["niveau"] == 162.0   # 180 USD * 0.9 = 162 EUR


def test_stop_trailing_monte_avec_le_cours_et_ne_redescend_jamais():
    cfg = {"stop": {"type": "trailing", "value": 15}}
    etat = None
    niveaux = []
    for cours in (100, 120, 110, 90):   # monte, monte, retrace, retrace encore
        r = re_.evaluer_stop(ligne=cfg, cours=cours, cout=80, closes=None,
                             etat_ligne=etat)
        etat = r["etat"]
        niveaux.append(r["niveau"])
    # Le niveau ne doit jamais baisser d'un pas au suivant (cliquet).
    assert all(niveaux[i] <= niveaux[i + 1] for i in range(len(niveaux) - 1))
    assert niveaux[-1] == round(120 * 0.85, 4)   # fige sur le plus haut (120)


def test_stop_vq_indisponible_sans_historique_suffisant():
    res = re_.evaluer_stop(
        ligne={"stop": "vq"}, cours=100, cout=80, closes=[100, 101, 99])
    assert res["statut"] == re_.STATUT_INCALC


def test_stop_type_inconnu_retombe_sur_aucun():
    res = re_.evaluer_stop(
        ligne={"stop": {"type": "n_importe_quoi", "value": 10}},
        cours=100, cout=80, closes=None)
    assert res["type"] == "none"
    assert res["erreur"] is not None


def test_stop_percent_hors_bornes_est_rejete():
    res = re_.evaluer_stop(
        ligne={"stop": {"type": "percent", "value": 150}},
        cours=100, cout=80, closes=None)
    assert res["type"] == "none"


# ─────────────────────────────────────────────────────────────────────────
# Dimensionnement
# ─────────────────────────────────────────────────────────────────────────

def test_dimensionner_cas_nominal():
    # 100000 capital, 1% risque = 1000 EUR, stop a 20% -> 5000 EUR de position.
    res = re_.dimensionner(capital=100_000, cours=50, distance_pct=20,
                           risque_pct=1.0, poids_max_pct=15.0)
    assert res["montant"] == 5000.0
    assert res["risque_eur"] == 1000.0
    assert res["bride"] is None


def test_dimensionner_plafonne_par_le_poids_max():
    # Stop tres serre (2%) sur un gros capital : sans plafond, le montant
    # exploserait (1% / 2% x capital = 50% du capital).
    res = re_.dimensionner(capital=100_000, cours=50, distance_pct=2,
                           risque_pct=1.0, poids_max_pct=15.0)
    assert res["montant"] == 15_000.0
    assert "plafonné" in res["bride"]


def test_dimensionner_plafonne_par_les_liquidites():
    res = re_.dimensionner(capital=100_000, cours=50, distance_pct=20,
                           risque_pct=1.0, liquidites=2_000)
    assert res["montant"] == 2_000.0
    assert "liquidités" in res["bride"]


def test_dimensionner_distance_trop_faible_est_ignoree():
    res = re_.dimensionner(capital=100_000, cours=50, distance_pct=0.3)
    assert res["montant"] is None


def test_dimensionner_par_volatilite_egalise_le_risque():
    # A volatilite egale au budget cible, le poids doit valoir 100% (borne
    # ensuite par poids_max_pct) ; une volatilite double doit donner un poids
    # moitie moindre.
    calme = re_.dimensionner_par_volatilite(capital=100_000, cours=10,
                                            vol_ann_pct=20, vol_cible_pct=2.0,
                                            poids_max_pct=50.0)
    nerveux = re_.dimensionner_par_volatilite(capital=100_000, cours=10,
                                              vol_ann_pct=40, vol_cible_pct=2.0,
                                              poids_max_pct=50.0)
    assert calme["poids_pct"] == 2 * nerveux["poids_pct"]


# ─────────────────────────────────────────────────────────────────────────
# Correlation et exposition croisee
# ─────────────────────────────────────────────────────────────────────────

def _base_correlee_inverse():
    """Trois series de clotures pour tester la correlation sur variations a
    3 mois (CORRELATION_FENETRE_JOURS = 63 seances). Il faut au moins
    CORRELATION_MIN_OBS + CORRELATION_FENETRE_JOURS (83) clotures pour obtenir
    une seule paire exploitable -- on en genere 120, via un generateur
    pseudo-aleatoire a graine fixe (reproductible) plutot qu'un motif
    periodique : un motif dont la periode divise la fenetre de 63 seances
    ferait retomber toutes les variations glissantes sur la meme valeur
    (ecart-type nul -> correlation indefinie).
    """
    rng = random.Random(7)
    base = [100.0]
    for _ in range(120):
        base.append(base[-1] * (1 + rng.uniform(-0.015, 0.015)))
    correlee = [v * 2.5 for v in base]        # proportionnelle -> correlation = 1
    inverse = [base[0] ** 2 / v for v in base]  # inverse -> correlation ~ -1
    return base, correlee, inverse


def test_correlation_parfaite_positive_et_negative():
    base, correlee, inverse = _base_correlee_inverse()
    assert re_.correlation(base, correlee) > 0.999
    # Sur des variations a 3 mois (composees), l'inverse exact d'une serie
    # n'est plus une symetrie parfaitement lineaire (contrairement a des
    # rendements a 1 jour) : la correlation reste tres fortement negative,
    # mais pas necessairement au-dela de -0.999.
    assert re_.correlation(base, inverse) < -0.99


def test_correlation_insuffisance_de_donnees_est_none():
    base, correlee, _ = _base_correlee_inverse()
    assert re_.correlation(base[:70], correlee[:70]) is None


def test_correlation_serie_constante_est_none():
    base, _, _ = _base_correlee_inverse()
    assert re_.correlation(base, [42.0] * len(base)) is None


def test_correlation_par_date_tolere_des_calendriers_differents():
    """BUG CORRIGE le 19/09/2026 : deux places (ex. US/FR) n'ont pas le meme
    calendrier de jours feries -- `dates_a`/`dates_b` doivent aligner sur les
    dates COMMUNES plutot que sur les N derniers points de chaque serie.
    Peu de feries non-communs entre deux grandes places sur 200 jours (2 ici)
    -- on reste realiste plutot que de retirer une seance sur 17, ce qui
    decalerait artificiellement la fenetre de 63 seances (comptee par
    POSITION dans chaque serie) bien plus qu'un vrai desaccord de calendrier.
    """
    base, correlee, _ = _base_correlee_inverse()
    debut = date(2026, 1, 2)
    toutes_dates = [(debut + timedelta(days=i)).isoformat() for i in range(200)]
    dates_a = toutes_dates[:]
    dates_b = [d for i, d in enumerate(toutes_dates) if i % 80 != 0]
    base_pad = (base + [base[-1]] * (len(toutes_dates) - len(base)))[:len(toutes_dates)]
    correlee_pad = (correlee + [correlee[-1]] * (len(toutes_dates) - len(correlee)))[:len(toutes_dates)]
    closes_b = [v for i, v in enumerate(correlee_pad) if i % 80 != 0]

    c = re_.correlation(base_pad, closes_b, dates_a=dates_a, dates_b=dates_b)
    assert c is not None and c > 0.9

    assert re_.correlation(base_pad[:70], closes_b[:70],
                           dates_a=dates_a[:70], dates_b=dates_b[:70]) is None


def test_exposition_correlee_regroupe_et_exclut_le_non_correle():
    base, correlee, inverse = _base_correlee_inverse()
    groupes = re_.exposition_correlee([
        {"nom": "A", "closes": base,     "poids_pct": 15.0},
        {"nom": "B", "closes": correlee, "poids_pct": 14.0},
        {"nom": "C", "closes": inverse,  "poids_pct": 20.0},
    ])
    assert len(groupes) == 1
    assert set(groupes[0]["lignes"]) == {"A", "B"}
    assert groupes[0]["poids_pct"] == 29.0
    assert groupes[0]["alerte"] is True


def test_exposition_correlee_ligne_sans_poids_est_ecartee():
    base, correlee, _ = _base_correlee_inverse()
    groupes = re_.exposition_correlee([
        {"nom": "A", "closes": base,     "poids_pct": 15.0},
        {"nom": "B", "closes": correlee, "poids_pct": None},
    ])
    assert groupes == []


def test_exposition_correlee_portefeuille_vide_ou_solo():
    assert re_.exposition_correlee([]) == []
    base, _, _ = _base_correlee_inverse()
    assert re_.exposition_correlee([{"nom": "Seul", "closes": base,
                                    "poids_pct": 10.0}]) == []


# ─────────────────────────────────────────────────────────────────────────
# Indice de correlation moyenne -- resume le portefeuille en un chiffre
# ─────────────────────────────────────────────────────────────────────────

def test_indice_correlation_moyenne_deux_lignes_parfaitement_correlees():
    base, correlee, _ = _base_correlee_inverse()
    idx = re_.indice_correlation_moyenne([{"closes": base}, {"closes": correlee}])
    assert idx["indice_pct"] > 99.0
    assert idx["n_paires"] == 1
    assert idx["n_lignes"] == 2


def test_indice_correlation_moyenne_melange_positif_et_negatif():
    base, correlee, inverse = _base_correlee_inverse()
    idx = re_.indice_correlation_moyenne([
        {"closes": base}, {"closes": correlee}, {"closes": inverse},
    ])
    # 3 paires : +1 (base/correlee), -1 (base/inverse), -1 (correlee/inverse)
    # -> moyenne = -1/3
    assert idx["n_paires"] == 3
    assert -34.0 < idx["indice_pct"] < -32.0
    assert idx["min_pct"] < -99.0
    assert idx["max_pct"] > 99.0


def test_indice_correlation_moyenne_ignore_le_poids():
    # Contrairement a exposition_correlee, aucun poids n'est requis : une
    # ligne avec un historique suffisant compte, point.
    base, correlee, _ = _base_correlee_inverse()
    idx = re_.indice_correlation_moyenne([{"closes": base}, {"closes": correlee}])
    assert idx["indice_pct"] is not None


def test_indice_correlation_moyenne_indisponible_sous_deux_lignes():
    base, _, _ = _base_correlee_inverse()
    assert re_.indice_correlation_moyenne([])["indice_pct"] is None
    assert re_.indice_correlation_moyenne([{"closes": base}])["indice_pct"] is None


def test_classe_correlation_seuils():
    assert re_.classe_correlation(None) == "Indisponible"
    assert re_.classe_correlation(10) == "Faible"
    assert re_.classe_correlation(30) == "Modérée"
    assert re_.classe_correlation(60) == "Élevée"
    assert "bloc" in re_.classe_correlation(85)
    assert "amortissent" in re_.classe_correlation(-20)


# ─────────────────────────────────────────────────────────────────────────
# Etat persistant : robustesse aux fichiers absents / corrompus
# ─────────────────────────────────────────────────────────────────────────

def test_charger_etat_fichier_absent_retourne_etat_vierge(tmp_path):
    etat = re_.charger_etat(str(tmp_path / "n_existe_pas.json"))
    assert etat["lignes"] == {}


def test_charger_etat_fichier_corrompu_retourne_etat_vierge(tmp_path):
    chemin = tmp_path / "stops_state.json"
    chemin.write_text("{ ceci n'est pas du json", encoding="utf-8")
    etat = re_.charger_etat(str(chemin))
    assert etat["lignes"] == {}


def test_sauver_puis_recharger_etat_est_fidele(tmp_path):
    chemin = str(tmp_path / "sous_dossier" / "stops_state.json")
    etat = {"schema": re_.SCHEMA_ETAT, "lignes": {"AAA": {"hwm": 123.45}}}
    assert re_.sauver_etat(chemin, etat) is True
    relu = re_.charger_etat(chemin)
    assert relu["lignes"]["AAA"]["hwm"] == 123.45


# ─────────────────────────────────────────────────────────────────────────
# Orchestration : une ligne qui plante ne doit pas casser les autres
# ─────────────────────────────────────────────────────────────────────────

def test_evaluer_portefeuille_isole_une_ligne_malformee():
    res = re_.evaluer_portefeuille([
        {"cle": "OK",  "nom": "Bonne ligne", "cours": 100, "cout": 80,
         "closes": _serie_stable(40), "ligne": {"stop": {"type": "percent", "value": 20}}},
        {"cle": "BAD", "nom": "Ligne cassee", "cours": "pas un nombre",
         "ligne": {"stop": "vq"}},
    ])
    assert len(res["lignes"]) == 2
    bad = next(l for l in res["lignes"] if l["cle"] == "BAD")
    assert bad["erreur"] is None or bad["stop"]["statut"] == re_.STATUT_INCALC


def test_evaluer_portefeuille_franchi_ne_recoit_pas_de_taille():
    res = re_.evaluer_portefeuille([
        {"cle": "X", "nom": "X", "cours": 50, "cout": 100,
         "closes": _serie_stable(40),
         "ligne": {"stop": {"type": "percent", "value": 20}}},
    ], capital=100_000)
    ligne = res["lignes"][0]
    assert ligne["stop"]["statut"] == re_.STATUT_FRANCHI
    assert ligne["taille"]["montant"] is None
