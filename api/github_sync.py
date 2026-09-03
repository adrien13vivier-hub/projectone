#!/usr/bin/env python3
"""
Synchronisation du backend vers GitHub.
================================================================================

LE PROBLÈME QUE CE MODULE RÉSOUT
--------------------------------
Le backend écrit les profils sur le disque de la machine qui l'héberge.
L'analyse quotidienne, elle, tourne dans GitHub Actions et ne lit que le
contenu du dépôt. Les deux moitiés ne se parlaient pas : un stop posé depuis
l'interface n'apparaissait jamais dans le rapport du lendemain.

Après chaque enregistrement, le profil est donc poussé dans le dépôt via
l'API Contents de GitHub.

POURQUOI L'API PLUTÔT QUE LA COMMANDE GIT
-----------------------------------------
Pas de dépôt cloné sur le serveur, pas de clé SSH, pas de fusion à gérer.
L'API travaille fichier par fichier avec un `sha` : si quelqu'un a modifié le
fichier entre-temps, l'écriture est refusée au lieu d'écraser en silence. On
relit alors le `sha` et on réessaie une fois.

CONFIGURATION
-------------
    GITHUB_TOKEN   jeton à portée limitée (voir plus bas)
    GITHUB_REPO    "adrien13vivier-hub/projectone"
    GITHUB_BRANCH  "main" par défaut

Le jeton doit être un **jeton d'accès personnel affiné** (fine-grained),
restreint à CE SEUL dépôt, avec deux permissions et pas une de plus :

    Contents : Read and write   → pousser les profils et la table des jetons
    Actions  : Read and write   → déclencher l'analyse de 22h37

Un jeton classique donnant accès à tous tes dépôts n'a pas sa place sur une
machine exposée. Si « Actions » manque, tout le reste continue de marcher :
seul le déclenchement à l'heure est perdu, et les crons GitHub prennent le
relais (à l'heure qu'ils veulent bien).

SANS CONFIGURATION, RIEN NE CASSE
---------------------------------
Si les variables sont absentes, l'enregistrement local se fait normalement et
la synchronisation est signalée comme « non configurée ». Le backend reste
utilisable hors ligne.
"""

import base64
import json
import os
import time

import requests

API = "https://api.github.com"
TIMEOUT = 20


def _config() -> dict:
    return {
        "token":  os.getenv("GITHUB_TOKEN", "").strip(),
        "repo":   os.getenv("GITHUB_REPO", "").strip(),
        "branch": os.getenv("GITHUB_BRANCH", "main").strip() or "main",
    }


def est_configure() -> bool:
    c = _config()
    return bool(c["token"] and c["repo"])


def _entetes(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _sha_actuel(cfg: dict, chemin: str):
    """`sha` du fichier distant, ou None s'il n'existe pas encore."""
    r = requests.get(f"{API}/repos/{cfg['repo']}/contents/{chemin}",
                     headers=_entetes(cfg["token"]),
                     params={"ref": cfg["branch"]}, timeout=TIMEOUT)
    if r.status_code == 200:
        return r.json().get("sha")
    if r.status_code == 404:
        return None
    r.raise_for_status()


def pousser_fichier(chemin: str, contenu: str, message: str) -> dict:
    """Écrit un fichier dans le dépôt. Retourne un état lisible par l'interface.

    Ne lève jamais : une panne de synchronisation ne doit pas faire échouer
    l'enregistrement local, qui a déjà réussi au moment de l'appel.
    """
    cfg = _config()
    if not est_configure():
        return {"ok": False, "etat": "non configure",
                "detail": "GITHUB_TOKEN et GITHUB_REPO ne sont pas definis."}

    charge = {
        "message": message,
        "content": base64.b64encode(contenu.encode("utf-8")).decode("ascii"),
        "branch":  cfg["branch"],
    }

    # Deux tentatives : la seconde couvre le cas où le fichier a changé entre
    # la lecture du sha et l'écriture (le workflow commite lui aussi).
    for tentative in (1, 2):
        try:
            sha = _sha_actuel(cfg, chemin)
            if sha:
                charge["sha"] = sha
            else:
                charge.pop("sha", None)

            r = requests.put(f"{API}/repos/{cfg['repo']}/contents/{chemin}",
                             headers=_entetes(cfg["token"]),
                             data=json.dumps(charge), timeout=TIMEOUT)

            if r.status_code in (200, 201):
                commit = (r.json().get("commit") or {}).get("sha", "")[:7]
                return {"ok": True, "etat": "synchronise",
                        "detail": f"commit {commit}", "chemin": chemin}

            if r.status_code == 409 and tentative == 1:
                time.sleep(1.5)          # conflit de sha : on relit et on réessaie
                continue

            if r.status_code == 401:
                return {"ok": False, "etat": "jeton refuse",
                        "detail": "GITHUB_TOKEN invalide ou expire."}
            if r.status_code == 403:
                return {"ok": False, "etat": "droits insuffisants",
                        "detail": "Le jeton n'a pas la permission Contents: write "
                                  "sur ce depot."}
            if r.status_code == 404:
                return {"ok": False, "etat": "depot introuvable",
                        "detail": f"{cfg['repo']} inaccessible avec ce jeton."}

            return {"ok": False, "etat": "echec",
                    "detail": f"HTTP {r.status_code} : {r.text[:180]}"}

        except requests.RequestException as e:
            if tentative == 2:
                return {"ok": False, "etat": "reseau",
                        "detail": f"{type(e).__name__}: {e}"}
            time.sleep(1.5)

    return {"ok": False, "etat": "echec", "detail": "Deux tentatives infructueuses."}


def pousser_profil(username: str, profil: dict) -> dict:
    """Pousse data/portfolios/portfolio_<user>.json."""
    user = str(username).strip().lower()
    contenu = json.dumps(profil, ensure_ascii=False, indent=2) + "\n"
    return pousser_fichier(
        f"data/portfolios/portfolio_{user}.json",
        contenu,
        f"Profil {user} mis a jour depuis l'interface",
    )


def etat() -> dict:
    """Diagnostic affichable dans l'interface."""
    cfg = _config()
    if not est_configure():
        return {"configure": False,
                "message": "Synchronisation GitHub inactive : les modifications "
                           "restent locales et n'atteindront pas le rapport "
                           "quotidien."}
    try:
        r = requests.get(f"{API}/repos/{cfg['repo']}",
                         headers=_entetes(cfg["token"]), timeout=TIMEOUT)
        if r.status_code == 200:
            d = r.json()
            return {"configure": True, "repo": cfg["repo"], "branche": cfg["branch"],
                    "prive": d.get("private"),
                    "message": "Synchronisation GitHub active."}
        return {"configure": True, "repo": cfg["repo"],
                "message": f"Depot inaccessible (HTTP {r.status_code})."}
    except requests.RequestException as e:
        return {"configure": True, "repo": cfg["repo"],
                "message": f"Depot injoignable : {type(e).__name__}"}


if __name__ == "__main__":
    print(json.dumps(etat(), ensure_ascii=False, indent=2))


def supprimer_fichier(chemin: str, message: str) -> dict:
    """Retire un fichier du depot.

    Utilise apres un changement de nom d'utilisateur : sans cela, l'ancien
    profil resterait dans data/portfolios/ et l'analyse quotidienne
    continuerait de produire un rapport pour un compte qui n'existe plus.
    """
    cfg = _config()
    if not est_configure():
        return {"ok": False, "etat": "non configure"}
    try:
        sha = _sha_actuel(cfg, chemin)
        if not sha:
            return {"ok": True, "etat": "deja absent"}
        r = requests.delete(f"{API}/repos/{cfg['repo']}/contents/{chemin}",
                            headers=_entetes(cfg["token"]),
                            data=json.dumps({"message": message, "sha": sha,
                                             "branch": cfg["branch"]}),
                            timeout=TIMEOUT)
        if r.status_code == 200:
            return {"ok": True, "etat": "supprime"}
        return {"ok": False, "etat": "echec", "detail": f"HTTP {r.status_code}"}
    except requests.RequestException as e:
        return {"ok": False, "etat": "reseau", "detail": f"{type(e).__name__}"}


def declencher_analyse(workflow: str = "daily_analysis.yml",
                       branche: str = None) -> dict:
    """Demande a GitHub de lancer l'analyse MAINTENANT (workflow_dispatch).

    POURQUOI CE DETOUR
    ------------------
    Les crons de GitHub Actions ne sont pas ponctuels. Sur ce depot, les
    declenchements de 20h37 UTC sont arrives entre 22h48 et 23h32 UTC, soit
    plus de deux heures de retard, tous les jours. Aucun reglage cote GitHub
    ne corrige cela : la file d'attente des taches planifiees est partagee et
    sans garantie de delai.

    Cette machine, elle, est allumee en permanence et son horloge est juste.
    Elle appelle donc GitHub a 22h37 pile. L'analyse continue de tourner chez
    GitHub, ou vivent les cles API : seul le TOP DEPART change de camp.

    Les crons restent declares dans le workflow comme filet de securite, au
    cas ou cette machine serait eteinte. Le garde-fou anti-doublon du workflow
    empeche les deux chemins de produire deux rapports le meme jour.
    """
    cfg = _config()
    if not est_configure():
        return {"ok": False, "etat": "non configure",
                "detail": "GITHUB_TOKEN et GITHUB_REPO ne sont pas definis."}
    ref = (branche or cfg["branch"])
    try:
        r = requests.post(
            f"{API}/repos/{cfg['repo']}/actions/workflows/{workflow}/dispatches",
            headers=_entetes(cfg["token"]),
            data=json.dumps({"ref": ref}), timeout=TIMEOUT)
        if r.status_code == 204:
            return {"ok": True, "etat": "declenche",
                    "detail": f"{workflow} lance sur {ref}"}
        if r.status_code == 403:
            return {"ok": False, "etat": "droits insuffisants",
                    "detail": "Le jeton n'a pas la permission « Actions : "
                              "Read and write » sur ce depot."}
        if r.status_code == 404:
            return {"ok": False, "etat": "introuvable",
                    "detail": f"Workflow {workflow} absent, ou jeton sans acces "
                              f"a {cfg['repo']}."}
        if r.status_code == 422:
            return {"ok": False, "etat": "refuse",
                    "detail": "GitHub refuse le declenchement : le workflow doit "
                              "declarer « workflow_dispatch » et exister sur la "
                              "branche par defaut."}
        return {"ok": False, "etat": "echec",
                "detail": f"HTTP {r.status_code} : {r.text[:180]}"}
    except requests.RequestException as e:
        return {"ok": False, "etat": "reseau", "detail": f"{type(e).__name__}: {e}"}


def pousser_liens(table: dict) -> dict:
    """Publie la table des jetons de rapport dans le depot.

    Sans cela, le jeton genere ici reste local. GitHub Actions, ne le
    trouvant pas, en fabrique un AUTRE au moment de publier le rapport :
    l'adresse remise a l'utilisateur a l'inscription ne correspond alors a
    aucune page. C'est la cause des liens qui ne donnent rien.
    """
    contenu = json.dumps(table, ensure_ascii=False, indent=2) + "\n"
    return pousser_fichier("data/report_links.json", contenu,
                           "Mise a jour des liens de rapport")
