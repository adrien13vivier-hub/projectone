"""
bot_alertes.py — prévenir quand le bot de trading achète ou vend.

POURQUOI UNE SURVEILLANCE, ET PAS UN APPEL DU BOT
-------------------------------------------------
Le bot (swing-hunter, sur Railway) prévient Discord lui-même, par webhook, à
l'instant où il passe un ordre. Le site, lui, n'était jamais prévenu de rien :
il ne lisait les positions que quand quelqu'un ouvrait l'onglet.

Deux façons d'y remédier :
  1. modifier le bot pour qu'il appelle aussi le site ;
  2. que le site aille regarder, toutes les deux minutes, ce qui a changé.

La seconde est retenue. Elle ne touche pas au bot, n'exige aucune nouvelle
clé, et un site éteint ne fait rien perdre au bot. Le prix à payer : jusqu'à
deux minutes de décalage avec Discord. C'est dit dans le mode d'emploi.

CE QUI DÉCLENCHE UNE NOTIFICATION
---------------------------------
On compare l'état du bot à celui vu au passage précédent :
  - une position qui apparaît                  -> ACHAT
  - une position dont la quantité augmente     -> ACHAT (renfort)
  - une position dont la quantité diminue      -> VENTE partielle
  - un trade clôturé qui apparaît              -> VENTE (avec le résultat)

AU PREMIER PASSAGE, ON NE NOTIFIE RIEN. On photographie l'existant. Sans
cela, l'installation enverrait d'un coup une notification pour chaque
position déjà ouverte et chaque trade déjà clos.

L'état vu est écrit sur disque : un redémarrage du site ne fait pas
renvoyer ce qui a déjà été annoncé.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

# Au-delà, on résume au lieu d'envoyer une rafale. Un tel volume en deux
# minutes ne correspond pas au rythme du bot : c'est presque toujours une
# remise à zéro de sa base, ou une reprise après une longue coupure.
MAX_PAR_PASSAGE = 6

MOTIFS = {
    "tp": "objectif atteint", "target": "objectif atteint",
    "stop": "stop touché", "sl": "stop touché",
    "trail": "stop suiveur", "trailing": "stop suiveur",
    "time": "durée maximale", "timeout": "durée maximale",
    "manual": "clôture manuelle",
}


# ── Lecture tolérante des réponses du bot ──────────────────────────────────

def _liste_positions(brut) -> List[dict]:
    """Le bot renvoie ses positions groupées par stratégie ({source: [...]}),
    parfois une liste simple. On accepte les deux."""
    if isinstance(brut, dict):
        if isinstance(brut.get("positions"), list):
            return [p for p in brut["positions"] if isinstance(p, dict)]
        groupes = brut.get("by_source", brut)
        sortie = []
        if isinstance(groupes, dict):
            for source, liste in groupes.items():
                if isinstance(liste, list):
                    for p in liste:
                        if isinstance(p, dict):
                            sortie.append({"source": source, **p})
        return sortie
    if isinstance(brut, list):
        return [p for p in brut if isinstance(p, dict)]
    return []


def _liste_trades(brut) -> List[dict]:
    if isinstance(brut, dict):
        for cle in ("trades", "items", "data"):
            if isinstance(brut.get(cle), list):
                brut = brut[cle]
                break
    return [t for t in brut if isinstance(t, dict)] if isinstance(brut, list) else []


def _num(v, defaut=0.0) -> float:
    try:
        f = float(v)
        return f if f == f else defaut
    except (TypeError, ValueError):
        return defaut


def _cle_position(p: dict) -> str:
    # L'identifiant du bot d'abord ; à défaut, ticker + stratégie + ouverture.
    if p.get("id") is not None:
        return f"id:{p['id']}"
    return f"{p.get('ticker')}|{p.get('source')}|{p.get('opened_at')}"


def _cle_trade(t: dict) -> str:
    if t.get("id") is not None:
        return f"id:{t['id']}"
    return f"{t.get('ticker')}|{t.get('opened_at')}|{t.get('closed_at')}"


# ── Le cœur : comparer deux états ──────────────────────────────────────────

def detecter(etat: dict, positions_brutes, trades_bruts) -> Tuple[List[dict], dict]:
    """Retourne (événements, nouvel_état). Fonction pure : aucun effet de bord.

    `etat` vaut {} au tout premier passage : on photographie sans notifier.
    """
    positions = _liste_positions(positions_brutes)
    trades = _liste_trades(trades_bruts)

    photo_pos = {_cle_position(p): _num(p.get("qty")) for p in positions}
    photo_trd = sorted({_cle_trade(t) for t in trades})
    nouvel = {"init": True, "positions": photo_pos, "trades": photo_trd,
              "vu_le": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if not etat.get("init"):
        return [], nouvel

    evts: List[dict] = []
    avant_pos: Dict[str, float] = etat.get("positions") or {}
    avant_trd = set(etat.get("trades") or [])

    # BUG CORRIGE (22/09/2026) : le meme garde-fou existait deja plus bas
    # pour les trades, mais pas ici pour les positions -- alors que c'est
    # exactement le meme risque. Si /api/positions repond une liste VIDE
    # par erreur (bot en redemarrage, base en cours d'ouverture, panne
    # reseau ponctuelle), l'ancien code ecrivait quand meme `photo_pos={}`
    # comme nouvel etat de reference. Au passage suivant, des que le bot
    # repondait a nouveau normalement, TOUTES les positions reelles (deja
    # detenues depuis longtemps) semblaient nouvelles par rapport a cet
    # etat vide -- generant une notification "achat" en double pour
    # chacune d'elles. Meme logique que pour les trades juste en dessous :
    # une liste vide qui succede a une liste non vide n'est pas une
    # information, c'est un signe de reponse ratee. On garde l'etat
    # precedent tel quel.
    if avant_pos and not photo_pos:
        return [], etat

    # Un historique de trades VIDE alors qu'on en connaissait un n'est pas
    # une information : c'est une réponse ratée du bot (redémarrage, base en
    # cours d'ouverture). Un trade clos ne disparaît pas. On garde l'état
    # précédent tel quel, sinon le passage suivant prendrait tout
    # l'historique pour des ventes nouvelles.
    if avant_trd and not photo_trd:
        return [], etat

    for p in positions:
        cle, q = _cle_position(p), _num(p.get("qty"))
        if cle not in avant_pos:
            evts.append({"type": "achat", "sous_type": "ouverture", "p": p, "qte": q})
        elif q > avant_pos[cle] + 1e-9:
            evts.append({"type": "achat", "sous_type": "renfort", "p": p,
                         "qte": q - avant_pos[cle]})
        elif q < avant_pos[cle] - 1e-9:
            evts.append({"type": "vente", "sous_type": "partielle", "p": p,
                         "qte": avant_pos[cle] - q})

    for t in trades:
        if _cle_trade(t) not in avant_trd:
            evts.append({"type": "vente", "sous_type": "cloture", "p": t,
                         "qte": _num(t.get("qty"))})

    # Si les trades ont RÉTRÉCI de moitié, la base du bot a été remise à zéro.
    # Rien de ce qui suit ne serait une vraie opération : on repart de zéro.
    if avant_trd and len(photo_trd) < len(avant_trd) / 2:
        return [], nouvel

    return evts, nouvel


# ── Mise en mots ──────────────────────────────────────────────────────────

def _prix(v) -> str:
    x = _num(v, None)
    if x is None:
        return "?"
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def formuler(e: dict) -> Tuple[str, str, str]:
    """(titre, corps, étiquette de regroupement) d'un événement.

    Rien de personnel dans la notification : elle passe par les serveurs
    d'Apple. Le portefeuille du bot est fictif, mais le principe tient.
    """
    p, q = e["p"], e["qte"]
    tk = str(p.get("ticker") or "?")
    strat = str(p.get("source") or "").strip()
    qte = f"{q:g}"
    if e["type"] == "achat":
        titre = f"Bot · achat {tk}" if e["sous_type"] == "ouverture" else f"Bot · renfort {tk}"
        corps = f"{qte} titre(s) à {_prix(p.get('entry_price') or p.get('tranche_price'))}"
        if strat:
            corps += f" — stratégie {strat}"
        return titre, corps + ".", f"bot-{tk}"

    if e["sous_type"] == "partielle":
        return (f"Bot · vente partielle {tk}",
                f"{qte} titre(s) vendus, la position reste ouverte.",
                f"bot-{tk}")

    pnl, pct = _num(p.get("pnl"), None), _num(p.get("pnl_pct"), None)
    motif = MOTIFS.get(str(p.get("exit_reason") or "").lower(), p.get("exit_reason") or "")
    corps = f"{qte} titre(s) à {_prix(p.get('exit_price'))}"
    if pnl is not None:
        signe = "+" if pnl >= 0 else "−"
        corps += f" · {signe}{_prix(abs(pnl))}"
        if pct is not None:
            corps += f" ({'+' if pct >= 0 else '−'}{abs(pct):.1f} %)"
    if motif:
        corps += f" — {motif}"
    return f"Bot · vente {tk}", corps + ".", f"bot-{tk}"


# ── Un passage complet ────────────────────────────────────────────────────

def lire_etat(chemin: Path) -> dict:
    try:
        return json.loads(chemin.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def ecrire_etat(chemin: Path, etat: dict) -> None:
    # BUG CORRIGE (22/09/2026, ecriture non atomique) : meme correctif que
    # dans load_portfolio.ecrire_json_atomique() -- fichier temporaire
    # voisin puis os.replace(), pour qu'une coupure en cours d'ecriture ne
    # puisse jamais laisser un etat tronque (le bot relirait un JSON
    # invalide au passage suivant et perdrait la trace des alertes deja
    # envoyees, au risque de les renvoyer en double).
    try:
        import os
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_name(chemin.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(etat, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, chemin)
    except OSError as e:
        print(f"[bot-alertes] état non écrit : {e}")


def passage(lire_bot: Callable[[str], object],
            notifier: Callable[[str, str, str, str, str], dict],
            chemin_etat: Path) -> dict:
    """Lit le bot, compare, notifie. Ne lève jamais.

    `lire_bot(chemin)` renvoie la réponse JSON du bot.
    `notifier(categorie, titre, corps, url, tag)` envoie aux abonnés concernés.

    Si le bot ne répond pas, on ne touche PAS à l'état mémorisé : sinon la
    reprise ferait passer toutes les positions pour nouvelles.
    """
    try:
        positions = lire_bot("/api/positions")
        trades = lire_bot("/api/trades")
    except Exception as e:
        return {"ok": False, "motif": f"bot injoignable ({type(e).__name__})"}

    etat = lire_etat(chemin_etat)
    evts, nouvel = detecter(etat, positions, trades)
    ecrire_etat(chemin_etat, nouvel)

    if not etat.get("init"):
        return {"ok": True, "premier_passage": True,
                "positions": len(nouvel["positions"]), "trades": len(nouvel["trades"])}

    envoyes = 0
    if len(evts) > MAX_PAR_PASSAGE:
        achats = sum(1 for e in evts if e["type"] == "achat")
        ventes = len(evts) - achats
        r = notifier("bot_achat" if achats >= ventes else "bot_vente",
                     "Bot · activité inhabituelle",
                     f"{achats} achat(s) et {ventes} vente(s) détectés d'un coup. "
                     f"Ouvrez l'onglet Bot de trading pour le détail.",
                     "/#bot", "bot-resume")
        envoyes += r.get("envoyes", 0)
    else:
        for e in evts:
            titre, corps, tag = formuler(e)
            cat = "bot_achat" if e["type"] == "achat" else "bot_vente"
            r = notifier(cat, titre, corps, "/#bot", tag)
            envoyes += r.get("envoyes", 0)

    return {"ok": True, "evenements": len(evts), "envoyes": envoyes}
