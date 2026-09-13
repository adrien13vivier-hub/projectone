#!/usr/bin/env python3
"""
backtest_score.py -- Le score du jour a-t-il predit la performance a venir ?
================================================================================

CE QUE CE SCRIPT REPOND, ET POURQUOI IL MANQUAIT
--------------------------------------------------------------------------------
Le rapport quotidien sort une note sur 10 et une recommandation (ACHAT FORT,
GARDER, VENDRE...) pour chaque ligne. Jusqu'ici, rien ne verifiait si cette
note avait raison : une valeur notee "ACHAT FORT" performe-t-elle vraiment
mieux, dans les semaines qui suivent, qu'une valeur notee "VENDRE" ? Sans
reponse a cette question, le reste de l'edifice (dimensionnement, stops...)
s'appuie sur un signal dont la valeur predictive n'est jamais mesuree.

Ce script ne change rien a l'analyseur : il relit `reports/<user>/history.csv`,
que portfolio_analyzer.py alimente deja chaque jour, et compare le score
publie a la date D au rendement du prix entre D et D + horizon jours.

CE QU'IL NE FAIT PAS
--------------------------------------------------------------------------------
Il ne corrige rien, ne recommande rien, n'appelle aucune API. Un historique
trop court (le projet est recent) donne peu ou pas de paires exploitables --
le script le signale explicitement plutot que de sortir un chiffre instable
sur trois points de mesure.

USAGE
--------------------------------------------------------------------------------
    python backtest_score.py --user adrien
    python backtest_score.py --user adrien --horizon 14
    python backtest_score.py --all-users
================================================================================
"""

import argparse
import csv
import glob
from collections import defaultdict
from datetime import datetime, timedelta

# Mêmes seuils que recommend() dans portfolio_analyzer.py -- dupliqués ici
# volontairement : ce script doit pouvoir tourner seul, sans dépendre du
# reste de l'analyseur, sur un simple export CSV.
SEUILS_RECOMMANDATION = [
    (7.5, "ACHAT FORT"),
    (6.0, "ACHAT MODÉRÉ"),
    (4.5, "GARDER"),
    (3.0, "À ÉVITER"),
    (-float("inf"), "VENDRE"),
]


def _float(valeur):
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return None
    if v != v:   # NaN
        return None
    return v


def _date(brut):
    try:
        return datetime.strptime((brut or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None


def classer(score: float) -> str:
    for seuil, label in SEUILS_RECOMMANDATION:
        if score >= seuil:
            return label
    return SEUILS_RECOMMANDATION[-1][1]


def lire_historique(chemin: str) -> list:
    try:
        with open(chemin, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def paires_score_performance(lignes: list, horizon_jours: int = 30) -> list:
    """Pour chaque (ticker, date) avec un score publié, cherche la première
    ligne du même ticker au moins `horizon_jours` plus tard et calcule le
    rendement de prix entre les deux.

    Une seule paire par (ticker, date de départ) : on prend la PREMIÈRE
    observation qui atteint l'horizon, pas la plus proche ni la plus
    éloignée -- sinon un ticker suivi plus souvent pèserait plus lourd dans
    le résultat sans raison.
    """
    par_ticker = defaultdict(list)
    for l in lignes:
        d  = _date(l.get("date"))
        px = _float(l.get("price_eur"))
        sc = _float(l.get("score"))
        if d and px and px > 0:
            par_ticker[l.get("ticker") or l.get("name")].append((d, px, sc))

    for serie in par_ticker.values():
        serie.sort(key=lambda x: x[0])

    paires = []
    for ticker, serie in par_ticker.items():
        for i, (d0, px0, score0) in enumerate(serie):
            if score0 is None:
                continue
            cible = d0 + timedelta(days=horizon_jours)
            futur = next((px for d, px, _ in serie[i + 1:] if d >= cible), None)
            if futur is None:
                continue
            paires.append({
                "ticker":        ticker,
                "date":          d0.strftime("%Y-%m-%d"),
                "score":         score0,
                "rendement_pct": round((futur / px0 - 1) * 100.0, 2),
            })
    return paires


def correlation_pearson(xs: list, ys: list):
    """Coefficient de Pearson pur Python -- pas de dépendance à numpy pour
    un script qui doit pouvoir tourner sur un simple export CSV."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    vx  = sum((x - mx) ** 2 for x in xs) / n
    vy  = sum((y - my) ** 2 for y in ys) / n
    if vx <= 0 or vy <= 0:
        return None
    return cov / ((vx ** 0.5) * (vy ** 0.5))


def resume_par_recommandation(paires: list) -> list:
    """Rendement moyen et médian futur, groupé par la recommandation que le
    score aurait donnée ce jour-là. Si le score est prédictif, ACHAT FORT
    doit ressortir devant VENDRE -- pas l'inverse."""
    groupes = defaultdict(list)
    for p in paires:
        groupes[classer(p["score"])].append(p["rendement_pct"])

    out = []
    for _, label in SEUILS_RECOMMANDATION:
        vals = groupes.get(label, [])
        if not vals:
            continue
        vals_tries = sorted(vals)
        out.append({
            "label":       label,
            "n":           len(vals),
            "moyenne_pct": round(sum(vals) / len(vals), 2),
            "mediane_pct": round(vals_tries[len(vals_tries) // 2], 2),
        })
    return out


def rapport(user: str, chemin: str, horizon_jours: int) -> None:
    lignes = lire_historique(chemin)
    print(f"\n{'=' * 70}\n{user} -- {chemin}\n{'=' * 70}")
    if not lignes:
        print("  (aucun historique lisible)")
        return

    paires = paires_score_performance(lignes, horizon_jours)
    if len(paires) < 5:
        print(f"  Historique trop court pour un horizon de {horizon_jours} "
             f"jours : seulement {len(paires)} paire(s) score/performance "
             f"exploitable(s). Rien de fiable à publier -- relancer plus "
             f"tard, quand l'historique aura grandi.")
        return

    scores      = [p["score"] for p in paires]
    rendements  = [p["rendement_pct"] for p in paires]
    corr        = correlation_pearson(scores, rendements)

    print(f"  {len(paires)} paires (score, performance à +{horizon_jours}j) "
         f"trouvées.")
    if corr is None:
        print("  Corrélation non calculable (échantillon trop homogène).")
    else:
        lecture = ("le score et la performance future bougent ensemble" if corr > 0.15 else
                  "le score et la performance future bougent en sens opposé" if corr < -0.15 else
                  "pas de lien net entre le score et la performance future")
        print(f"  Corrélation score -> rendement à +{horizon_jours}j : "
             f"{corr:+.2f}  ({lecture})")

    print(f"\n  Rendement moyen à +{horizon_jours}j, par recommandation du jour :")
    print(f"  {'Recommandation':<16} {'N':>4}  {'Moyenne':>9}  {'Médiane':>9}")
    for r in resume_par_recommandation(paires):
        print(f"  {r['label']:<16} {r['n']:>4}  {r['moyenne_pct']:>+8.2f}% "
             f" {r['mediane_pct']:>+8.2f}%")

    print(
        "\n  Lecture : si le score est utile, ACHAT FORT doit en moyenne "
        "afficher un meilleur rendement futur que VENDRE. Une seule mesure "
        "ne prouve rien -- ce script vaut surtout suivi dans le temps, à "
        "mesure que l'historique s'allonge, et par petits échantillons il "
        "reste sensible au hasard."
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Corrèle le score publié par portfolio_analyzer.py à la "
                    "performance réellement observée ensuite.")
    ap.add_argument("--user", default=None,
                    help="Utilisateur (reports/<user>/history.csv).")
    ap.add_argument("--all-users", action="store_true",
                    help="Traite tous les profils sous reports/*/history.csv.")
    ap.add_argument("--horizon", type=int, default=30,
                    help="Horizon de performance future, en jours (défaut 30).")
    args = ap.parse_args()

    if args.all_users or not args.user:
        chemins = sorted(glob.glob("reports/*/history.csv"))
        if not chemins:
            print("Aucun reports/*/history.csv trouvé.")
            return 1
        for chemin in chemins:
            user = chemin.split("/")[1]
            rapport(user, chemin, args.horizon)
    else:
        rapport(args.user, f"reports/{args.user}/history.csv", args.horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
