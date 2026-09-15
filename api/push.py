"""
push.py — Notifications Web Push, sans dependance exotique.

POURQUOI CE FICHIER EXISTE
--------------------------
La bibliotheque habituelle pour ce travail est `pywebpush`. Elle tire
`http-ece`, qui doit etre COMPILE a l'installation et echoue regulierement.
Or ce serveur tourne sur une machine personnelle : une installation qui
echoue, c'est une fonctionnalite qui n'existe pas.

Tout est donc ecrit ici avec la seule bibliotheque `cryptography`, qui
s'installe partout en binaire precompile. Le chiffrement suit la RFC 8291
(aes128gcm) et l'authentification la RFC 8292 (VAPID). L'implementation est
verifiee contre le vecteur de test officiel de la RFC 8291, section 5.

CE QU'APPLE IMPOSE
------------------
Sur iPhone, les notifications web ne fonctionnent QUE si le site a ete
ajoute a l'ecran d'accueil. Depuis un onglet Safari, la demande
d'autorisation est refusee immediatement, sans message. Ce n'est pas un
reglage : c'est une regle d'Apple, et aucun code ne la contourne.

Autre regle iOS : toute notification envoyee doit etre VISIBLE. Une
notification silencieuse fait revoquer l'abonnement par le systeme.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

DISPONIBLE = True
MOTIF_INDISPO = ""

try:
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
    from cryptography.hazmat.primitives.hmac import HMAC
except Exception as _e:                                    # pragma: no cover
    DISPONIBLE = False
    MOTIF_INDISPO = f"{type(_e).__name__}: {_e}"


# ─────────────────────────────────────────────────────────────────────────────
# Encodage base64url sans remplissage, celui qu'emploient toutes ces normes
# ─────────────────────────────────────────────────────────────────────────────

def b64e(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).rstrip(b"=").decode("ascii")


def b64d(texte: str) -> bytes:
    t = str(texte or "").strip()
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


# ─────────────────────────────────────────────────────────────────────────────
# Cles VAPID : l'identite du serveur aupres du service de notification
# ─────────────────────────────────────────────────────────────────────────────

class ClesVapid:
    """Paire de cles P-256 du serveur.

    Elles sont fabriquees une fois, au premier demarrage, et conservees dans
    data/vapid.json. Il n'y a donc rien a generer a la main.

    ATTENTION : changer ces cles invalide tous les abonnements existants.
    Le fichier ne doit jamais partir sur GitHub.
    """

    def __init__(self, prive: ec.EllipticCurvePrivateKey):
        self.prive = prive
        nombres = prive.public_key().public_numbers()
        self.public_brut = (b"\x04"
                            + nombres.x.to_bytes(32, "big")
                            + nombres.y.to_bytes(32, "big"))

    @property
    def publique_b64(self) -> str:
        return b64e(self.public_brut)

    @classmethod
    def charger_ou_creer(cls, chemin: Path) -> "ClesVapid":
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
            prive = serialization.load_pem_private_key(
                brut["prive_pem"].encode("ascii"), password=None)
            return cls(prive)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[push] {chemin} illisible ({type(e).__name__}) : "
                  f"de nouvelles cles sont generees, les abonnements "
                  f"existants devront etre refaits.")

        prive = ec.generate_private_key(ec.SECP256R1())
        pem = prive.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()).decode("ascii")
        obj = cls(prive)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(
            {"prive_pem": pem, "publique": obj.publique_b64,
             "cree_le": time.strftime("%Y-%m-%dT%H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(chemin, 0o600)
        except OSError:
            pass
        print(f"[push] Cles VAPID creees dans {chemin}.")
        return obj

    def entete_autorisation(self, endpoint: str, sujet: str) -> str:
        """En-tete Authorization au format VAPID (RFC 8292)."""
        u = urlparse(endpoint)
        revendications = {
            "aud": f"{u.scheme}://{u.netloc}",
            "exp": int(time.time()) + 12 * 3600,
            "sub": sujet,
        }
        entete = {"typ": "JWT", "alg": "ES256"}
        base = (b64e(json.dumps(entete, separators=(",", ":")).encode())
                + "." + b64e(json.dumps(revendications, separators=(",", ":")).encode()))
        der = self.prive.sign(base.encode("ascii"), ec.ECDSA(hashes.SHA256()))
        # La signature DER doit etre convertie en (r||s) sur 64 octets.
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        jeton = base + "." + b64e(signature)
        return f"vapid t={jeton}, k={self.publique_b64}"


# ─────────────────────────────────────────────────────────────────────────────
# Chiffrement du message (RFC 8291 / RFC 8188, aes128gcm)
# ─────────────────────────────────────────────────────────────────────────────

def _hmac(cle: bytes, donnees: bytes) -> bytes:
    h = HMAC(cle, hashes.SHA256())
    h.update(donnees)
    return h.finalize()


def _hkdf(sel: bytes, ikm: bytes, info: bytes, longueur: int) -> bytes:
    prk = _hmac(sel, ikm)
    return HKDFExpand(algorithm=hashes.SHA256(), length=longueur,
                      info=info).derive(prk)


def chiffrer(charge: bytes, ua_public: bytes, auth_secret: bytes,
             sel: Optional[bytes] = None,
             as_prive: Optional[ec.EllipticCurvePrivateKey] = None) -> bytes:
    """Chiffre une charge utile pour un abonne donne.

    `sel` et `as_prive` ne sont fournis que par le banc d'essai, pour rejouer
    le vecteur de la RFC. En service, ils sont tires au hasard a chaque envoi.
    """
    sel = sel or os.urandom(16)
    as_prive = as_prive or ec.generate_private_key(ec.SECP256R1())

    n = as_prive.public_key().public_numbers()
    as_public = b"\x04" + n.x.to_bytes(32, "big") + n.y.to_bytes(32, "big")

    partagee = as_prive.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))

    # Deux derivations successives : la premiere melange le secret
    # d'authentification propre a l'abonnement, la seconde le sel du message.
    info_auth = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hkdf(auth_secret, partagee, info_auth, 32)

    cle = _hkdf(sel, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(sel, ikm, b"Content-Encoding: nonce\x00", 12)

    # 0x02 marque la fin du dernier enregistrement (RFC 8188).
    chiffre = AESGCM(cle).encrypt(nonce, charge + b"\x02", None)

    return (sel
            + (4096).to_bytes(4, "big")      # taille d'enregistrement
            + len(as_public).to_bytes(1, "big")
            + as_public
            + chiffre)


# ─────────────────────────────────────────────────────────────────────────────
# Envoi
# ─────────────────────────────────────────────────────────────────────────────

class Resultat:
    def __init__(self, ok: bool, code: int = 0, detail: str = "",
                 perime: bool = False):
        self.ok, self.code, self.detail, self.perime = ok, code, detail, perime

    def __repr__(self):
        return f"<Resultat ok={self.ok} code={self.code} {self.detail[:60]}>"


def envoyer(abonnement: dict, message: dict, cles: ClesVapid, sujet: str,
            delai: Tuple[float, float] = (4.0, 10.0)) -> Resultat:
    """Envoie une notification a UN abonnement.

    Ne leve jamais : un telephone eteint ou un abonnement perime ne doit pas
    interrompre ce qui se passait autour. `perime` vaut True quand le service
    repond que l'abonnement n'existe plus — l'appelant doit alors le supprimer
    de sa base, sinon on reessaiera indefiniment.
    """
    if not DISPONIBLE:
        return Resultat(False, 0, f"cryptography indisponible ({MOTIF_INDISPO})")

    endpoint = abonnement.get("endpoint") or ""
    if not endpoint:
        return Resultat(False, 0, "abonnement sans adresse")

    try:
        corps = chiffrer(json.dumps(message, ensure_ascii=False).encode("utf-8"),
                         b64d(abonnement["p256dh"]), b64d(abonnement["auth"]))
        entetes = {
            "Authorization": cles.entete_autorisation(endpoint, sujet),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": "86400",
            # iOS revoque un abonnement qui recoit une notification invisible.
            "Urgency": "normal",
        }
        rep = requests.post(endpoint, data=corps, headers=entetes, timeout=delai)
    except Exception as e:
        return Resultat(False, 0, f"{type(e).__name__}: {e}")

    if rep.status_code in (404, 410):
        return Resultat(False, rep.status_code,
                        "abonnement expire ou revoque", perime=True)
    if 200 <= rep.status_code < 300:
        return Resultat(True, rep.status_code, "envoye")
    return Resultat(False, rep.status_code, (rep.text or "")[:200])
