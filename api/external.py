"""
external.py — Passerelle vers les deux services externes.

Le site n'appelle jamais directement les APIs des bots : il passe par ici.
Trois raisons, dans l'ordre d'importance.

1. La cle de lecture ne quitte jamais ce serveur. Si le navigateur appelait
   les bots lui-meme, la cle serait dans le code source de la page, lisible
   par n'importe qui ouvre les outils de developpement.
2. Une panne d'un bot ne casse pas la page. Chaque route repond toujours en
   JSON, meme quand le service d'en face est eteint : le site affiche
   « indisponible » au lieu d'une page blanche.
3. Un cache court evite de marteler les deux services. Cinq utilisateurs qui
   rafraichissent la page du bot ne declenchent pas cinq appels.

Toutes les routes exigent une session ouverte (Depends(current_user)).
Aucun visiteur non connecte n'atteint quoi que ce soit ici.

Quatre reglages sont necessaires :

    ANALYSE_API_URL        adresse du service Analyse      (ex. https://xxx.up.railway.app)
    ANALYSE_API_KEY        sa cle de lecture
    SWINGHUNTER_API_URL    adresse du service swing-hunter
    SWINGHUNTER_API_KEY    sa cle de lecture

Ils peuvent etre poses de deux facons, au choix :

1. Un fichier `config_externe.json` place a cote de ce dossier `api/`,
   c'est-a-dire dans /opt/portfolio/. C'est la methode la plus simple : elle
   ne demande aucune manipulation de systemd, juste une copie de fichier —
   le meme geste que pour deployer backend.py.

       {
         "ANALYSE_API_URL": "https://analyse-production-8156.up.railway.app",
         "ANALYSE_API_KEY": "...",
         "SWINGHUNTER_API_URL": "https://impartial-flow-production-dc00.up.railway.app",
         "SWINGHUNTER_API_KEY": "..."
       }

   CE FICHIER CONTIENT DES SECRETS. Il ne doit jamais partir sur GitHub :
   ajoute `config_externe.json` a ton .gitignore.

2. Des variables d'environnement du meme nom. Elles ont la priorite sur le
   fichier, ce qui permet de surcharger un reglage sans y toucher.

Le chemin du fichier peut etre change par la variable EXTERNAL_CONFIG.

Aucune n'est obligatoire au demarrage : un service non configure est
simplement declare « non configure » par /api/external/sante, et ses routes
repondent 503 avec une explication. Le reste de projectone tourne
normalement. C'est deliberé : une variable oubliee ne doit pas empecher le
rapport quotidien de sortir.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

# ─────────────────────────────────────────────────────────────────────────────
# Reglages
# ─────────────────────────────────────────────────────────────────────────────

CHEMIN_CONFIG = Path(os.getenv("EXTERNAL_CONFIG")
                     or (Path(__file__).resolve().parent.parent / "config_externe.json"))

CLES_CONFIG = ("ANALYSE_API_URL", "ANALYSE_API_KEY",
               "SWINGHUNTER_API_URL", "SWINGHUNTER_API_KEY")


def _charger_config() -> Dict[str, str]:
    """Lit config_externe.json s'il existe. N'echoue jamais bruyamment.

    Un fichier absent est normal (les variables d'environnement peuvent
    suffire). Un fichier illisible est signale dans le journal mais n'empeche
    pas le demarrage : le rapport quotidien doit continuer a sortir meme si
    cette passerelle est mal configuree.
    """
    try:
        if not CHEMIN_CONFIG.is_file():
            return {}
        brut = json.loads(CHEMIN_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(brut, dict):
            print(f"[externe] {CHEMIN_CONFIG} : attendu un objet JSON, ignore.")
            return {}
        return {k: str(v).strip() for k, v in brut.items()
                if k in CLES_CONFIG and v not in (None, "")}
    except json.JSONDecodeError as e:
        print(f"[externe] {CHEMIN_CONFIG} illisible (JSON invalide ligne {e.lineno}). "
              f"Les routes /api/external resteront fermees.")
    except OSError as e:
        print(f"[externe] {CHEMIN_CONFIG} illisible ({e.strerror}).")
    return {}


_CONF = _charger_config()


def _reglage(nom: str) -> str:
    """Variable d'environnement d'abord, fichier ensuite."""
    return (os.getenv(nom) or _CONF.get(nom) or "").strip()


ANALYSE_URL = _reglage("ANALYSE_API_URL").rstrip("/")
ANALYSE_KEY = _reglage("ANALYSE_API_KEY")
SWING_URL = _reglage("SWINGHUNTER_API_URL").rstrip("/")
SWING_KEY = _reglage("SWINGHUNTER_API_KEY")

if not (ANALYSE_URL and ANALYSE_KEY and SWING_URL and SWING_KEY):
    manquants = [n for n in CLES_CONFIG if not _reglage(n)]
    print(f"[externe] Reglages manquants : {', '.join(manquants)}. "
          f"Cherche dans l'environnement puis dans {CHEMIN_CONFIG}. "
          f"Les onglets Bot et Analyse afficheront « non configure ».")

# Delais d'attente. Le premier chiffre est le temps pour etablir la connexion,
# le second le temps pour recevoir la reponse. Une analyse ne bloque jamais
# longtemps : la route POST rend la main tout de suite avec un identifiant.
DELAI_COURT: Tuple[float, float] = (3.0, 8.0)
DELAI_LONG: Tuple[float, float] = (3.0, 20.0)

# Duree de vie du cache de lecture, en secondes. Les positions du bot ne
# changent pas plus vite que ca.
CACHE_LECTURE_S = int(os.getenv("EXTERNAL_CACHE_S", "30"))

# Intervalle minimum entre deux demandes d'analyse d'un meme utilisateur.
# Ce n'est pas un quota : c'est un garde-fou contre une page bloquee dans une
# boucle de rafraichissement.
DELAI_MINI_ANALYSE_S = int(os.getenv("EXTERNAL_DELAI_ANALYSE_S", "5"))

TICKER_MAX = 12
TICKER_AUTORISE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=")

router = APIRouter(prefix="/api/external", tags=["externe"])


# ─────────────────────────────────────────────────────────────────────────────
# Cache et anti-rafale, en memoire, proteges par un verrou
# ─────────────────────────────────────────────────────────────────────────────

_verrou = threading.Lock()
_cache: Dict[str, Tuple[float, Any]] = {}
_derniere_analyse: Dict[str, float] = {}


def _cache_lire(cle: str) -> Optional[Any]:
    with _verrou:
        entree = _cache.get(cle)
        if not entree:
            return None
        pose_a, valeur = entree
        if time.time() - pose_a > CACHE_LECTURE_S:
            _cache.pop(cle, None)
            return None
        return valeur


def _cache_ecrire(cle: str, valeur: Any) -> None:
    with _verrou:
        _cache[cle] = (time.time(), valeur)
        # Le cache est minuscule par nature (une dizaine de cles). On le purge
        # quand meme, pour qu'un ticker rare ne s'y accumule pas indefiniment.
        if len(_cache) > 200:
            limite = time.time() - CACHE_LECTURE_S
            for k in [k for k, (t, _) in _cache.items() if t < limite]:
                _cache.pop(k, None)


def vider_cache() -> None:
    """Utilise par les bancs d'essai. Sans effet en production."""
    with _verrou:
        _cache.clear()
        _derniere_analyse.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Appel HTTP vers un service externe
# ─────────────────────────────────────────────────────────────────────────────

class ServiceIndisponible(Exception):
    """Le service d'en face n'a pas pu etre joint, ou a mal repondu."""

    def __init__(self, message: str, code: int = 503, detail_amont: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail_amont = detail_amont


def _appeler(base: str, cle: str, chemin: str, *, methode: str = "GET",
             params: Optional[dict] = None,
             delai: Tuple[float, float] = DELAI_COURT,
             nom_service: str = "service") -> Any:
    """Appelle un service externe et retourne son JSON.

    Toute erreur devient une ServiceIndisponible portant un message lisible
    par un humain. Rien de ce qui sort d'ici ne contient la cle.
    """
    if not base or not cle:
        raise ServiceIndisponible(
            f"{nom_service} n'est pas configure sur ce serveur "
            f"(adresse ou cle manquante).")

    url = f"{base}{chemin}"
    entetes = {"X-API-Key": cle, "Accept": "application/json"}

    try:
        rep = requests.request(methode, url, headers=entetes, params=params,
                               timeout=delai)
    except requests.exceptions.ConnectTimeout:
        raise ServiceIndisponible(f"{nom_service} ne repond pas (connexion).")
    except requests.exceptions.ReadTimeout:
        raise ServiceIndisponible(f"{nom_service} met trop de temps a repondre.")
    except requests.exceptions.RequestException as e:
        raise ServiceIndisponible(f"{nom_service} injoignable ({type(e).__name__}).")

    if rep.status_code == 401:
        # La cle posee ici ne correspond pas a celle du service. C'est une
        # erreur de configuration de ce serveur, pas une erreur du visiteur.
        raise ServiceIndisponible(
            f"{nom_service} a refuse la cle de ce serveur. "
            f"Verifie que ANALYSE_API_KEY / SWINGHUNTER_API_KEY correspondent "
            f"aux API_SECRET_KEY poses sur Railway.")

    if rep.status_code == 503:
        raise ServiceIndisponible(
            f"{nom_service} n'a pas ses variables d'environnement "
            f"(il repond « API non configuree »).")

    if rep.status_code == 429:
        raise ServiceIndisponible(
            f"{nom_service} a recu trop de demandes. Reessaie dans une minute.",
            code=429)

    if rep.status_code == 404:
        raise ServiceIndisponible("Introuvable.", code=404)

    if rep.status_code >= 400:
        raise ServiceIndisponible(
            f"{nom_service} a renvoye une erreur {rep.status_code}.",
            code=502)

    try:
        return rep.json()
    except ValueError:
        raise ServiceIndisponible(
            f"{nom_service} n'a pas renvoye du JSON.", code=502)


def _erreur(e: ServiceIndisponible) -> HTTPException:
    return HTTPException(status_code=e.code, detail=e.message)


def _valider_ticker(brut: str) -> str:
    t = (brut or "").strip().upper()
    if not t or len(t) > TICKER_MAX or not set(t).issubset(TICKER_AUTORISE):
        raise HTTPException(status_code=400, detail="Ticker invalide.")
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Fabrique du routeur
# ─────────────────────────────────────────────────────────────────────────────

def construire_routeur(current_user) -> APIRouter:
    """Retourne le routeur, verrouille derriere la dependance de connexion.

    `current_user` est passe depuis backend.py plutot qu'importe ici : ca
    evite un import circulaire, et ca rend le module testable seul.
    """

    # ── Etat des deux services ───────────────────────────────────────────────

    @router.get("/sante")
    def sante(user: dict = Depends(current_user)):
        """Dit lequel des deux services repond, pour que la page l'annonce.

        Ne leve jamais d'erreur : c'est precisement la route qu'on appelle
        quand on soupconne une panne.
        """
        out: Dict[str, Any] = {}

        for nom, base, cle, chemin in (
            ("analyse", ANALYSE_URL, ANALYSE_KEY, "/api/health"),
            ("bot", SWING_URL, SWING_KEY, "/api/health"),
        ):
            if not base or not cle:
                out[nom] = {"ok": False, "etat": "non configure",
                            "detail": "adresse ou cle absente de ce serveur"}
                continue
            debut = time.time()
            try:
                _appeler(base, cle, chemin, delai=(2.0, 5.0), nom_service=nom)
                out[nom] = {"ok": True, "etat": "en ligne",
                            "ms": int((time.time() - debut) * 1000)}
            except ServiceIndisponible as e:
                out[nom] = {"ok": False, "etat": "injoignable",
                            "detail": e.message,
                            "ms": int((time.time() - debut) * 1000)}

        out["tout_ok"] = all(v.get("ok") for k, v in out.items() if k != "tout_ok")
        return out

    # ── Analyse d'action ─────────────────────────────────────────────────────

    @router.post("/analyse/{ticker}")
    def demander_analyse(ticker: str, user: dict = Depends(current_user)):
        """Met une analyse en file chez le service Analyse.

        Rend la main immediatement avec un identifiant de tache. Une analyse
        complete prend 10 a 60 secondes : la page interroge ensuite
        /analyse/tache/{id} jusqu'a ce que l'etat passe a « fini ».
        """
        t = _valider_ticker(ticker)
        qui = str(user.get("sub") or "?")

        with _verrou:
            precedent = _derniere_analyse.get(qui, 0.0)
            reste = DELAI_MINI_ANALYSE_S - (time.time() - precedent)
            if reste > 0:
                raise HTTPException(
                    status_code=429,
                    detail=f"Attends {int(reste) + 1} s avant la demande suivante.")
            _derniere_analyse[qui] = time.time()

        try:
            return _appeler(ANALYSE_URL, ANALYSE_KEY, f"/api/analyse/{t}",
                            methode="POST", delai=DELAI_LONG,
                            nom_service="Le service d'analyse")
        except ServiceIndisponible as e:
            raise _erreur(e)

    @router.get("/analyse/tache/{tache_id}")
    def suivre_analyse(tache_id: str, user: dict = Depends(current_user)):
        """Ou en est une analyse demandee juste avant."""
        ident = (tache_id or "").strip()
        if not ident or len(ident) > 64:
            raise HTTPException(status_code=400, detail="Identifiant invalide.")
        try:
            return _appeler(ANALYSE_URL, ANALYSE_KEY,
                            f"/api/analyse/tache/{ident}",
                            nom_service="Le service d'analyse")
        except ServiceIndisponible as e:
            raise _erreur(e)

    @router.get("/analyse/{ticker}")
    def analyse_en_cache(ticker: str, user: dict = Depends(current_user)):
        """Derniere analyse connue pour ce ticker, sans en relancer une.

        404 si rien n'est en cache — c'est le signal, pour la page, qu'il faut
        proposer le bouton « lancer l'analyse ».
        """
        t = _valider_ticker(ticker)
        try:
            return _appeler(ANALYSE_URL, ANALYSE_KEY, f"/api/analyse/{t}",
                            delai=DELAI_LONG,
                            nom_service="Le service d'analyse")
        except ServiceIndisponible as e:
            raise _erreur(e)

    # ── Portefeuille du bot, en lecture seule ────────────────────────────────

    def _lire_bot(chemin: str, cle_cache: str, params: Optional[dict] = None):
        en_cache = _cache_lire(cle_cache)
        if en_cache is not None:
            return en_cache
        donnees = _appeler(SWING_URL, SWING_KEY, chemin, params=params,
                           nom_service="Le bot de trading")
        _cache_ecrire(cle_cache, donnees)
        return donnees

    @router.get("/bot/positions")
    def bot_positions(user: dict = Depends(current_user)):
        try:
            return _lire_bot("/api/positions", "bot:positions")
        except ServiceIndisponible as e:
            raise _erreur(e)

    @router.get("/bot/trades")
    def bot_trades(limite: int = Query(50, ge=1, le=500),
                   user: dict = Depends(current_user)):
        try:
            return _lire_bot("/api/trades", f"bot:trades:{limite}",
                             params={"limite": limite})
        except ServiceIndisponible as e:
            raise _erreur(e)

    @router.get("/bot/stats")
    def bot_stats(user: dict = Depends(current_user)):
        try:
            return _lire_bot("/api/stats", "bot:stats")
        except ServiceIndisponible as e:
            raise _erreur(e)

    @router.get("/bot/performance")
    def bot_performance(user: dict = Depends(current_user)):
        try:
            return _lire_bot("/api/performance", "bot:performance")
        except ServiceIndisponible as e:
            raise _erreur(e)

    @router.get("/bot/macro")
    def bot_macro(user: dict = Depends(current_user)):
        """Tableau de bord macro du bot.

        Sa structure n'est pas figee par le contrat d'en face : elle suit la
        logique macro du bot et peut changer. La page doit donc l'afficher
        sans supposer la presence d'un champ precis.
        """
        try:
            return _lire_bot("/api/macro", "bot:macro")
        except ServiceIndisponible as e:
            raise _erreur(e)

    return router
