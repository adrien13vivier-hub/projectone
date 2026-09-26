#!/usr/bin/env python3
"""
generate_html.py  v3.8
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Convertit reports/daily_report.md  →  docs/index.html
• KPIs animés (compteurs au chargement)
• Graphique combiné normalisé base 100 (section Tendances)
• Tableaux positions + synthèse extraits du Markdown
• Synthèse IA par position (bloc > blockquote dans le Markdown)  ← v3.2
  - v3.3 : capture multi-lignes (toutes les lignes ">") concaténées
  - v3.4 : regex synth_src tolère les parenthèses dans le nom de source
            (ex: "RSS Yahoo Finance (brut)" capturé correctement)
  - v3.5 : suppression des print() finaux (cron-silent) + version v6.1
  - v3.6 : regex synth_src rendue robuste face au format ")* en fin de
            ligne produit par portfolio_analyzer (source : RSS Yahoo Finance)*
            → le \)? final et le \*? sont désormais optionnels et bien ordonnés
  - v3.7 : synchronisation numéro de version affiché → v6.2
  - v3.8 : fix extract_kpi() → cible la ligne TOTAL en gras dans le tableau
            synthèse ; fix extract_positions() → regex m_row tolère ^ et
            tous les formats de variation actuels
  - v3.9 (21/09/2026) : badges de recommandation resynchronisés sur le
            vocabulaire actuel de portfolio_analyzer.recommend() ; momentum
            1M/3M/6M réparé (regex bloquée par le gras markdown "**") ;
            distinction "Sans objet" / "Attendu mais non obtenu" réintroduite ;
            réaffichage de la justification, du consensus analystes, des
            avertissements macro et du motif d'indisponibilité des stops ;
            échappement HTML de tout texte externe (actualités RSS, noms
            saisis) via esc() ; sanitisation de la watchlist (motif de la
            troncature au "|" traité côté portfolio_analyzer.py)
• Historique des 30 derniers rapports (archive.json)
• Mode sombre / clair
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import base64, html, json, logging, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("generate_html")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

# ── Chemins ───────────────────────────────────────────────────
# --- Chemins : resolus par utilisateur via --user ----------------------------
import argparse as _argparse
import re as _re

_ap = _argparse.ArgumentParser(description="Rapport Markdown -> page HTML.")
_ap.add_argument("--user",   default=None, help="Utilisateur (reports/<user>/ -> docs/<user>/).")
_ap.add_argument("--output", default=None, help="Dossier de sortie HTML.")
_ap.add_argument("--input",  default=None, help="Chemin explicite du daily_report.md.")
_args, _ = _ap.parse_known_args()

def _slug(v):
    return _re.sub(r"[^a-zA-Z0-9_-]+", "-", str(v or "default").strip().lower()).strip("-") or "default"

USER = _slug(_args.user) if _args.user else None

if _args.input:
    MD_PATH = Path(_args.input)
elif USER:
    MD_PATH = Path(f"reports/{USER}/daily_report.md")
else:
    MD_PATH = Path("reports/daily_report.md")

if _args.output:
    OUT_DIR = Path(_args.output)
elif USER:
    # Publication sous un jeton aleatoire et non sous le nom d'utilisateur :
    # les fichiers servis par Cloudflare Pages sont publics, un chemin
    # devinable exposerait le portefeuille des autres utilisateurs.
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from api.load_portfolio import dossier_rapport
        OUT_DIR = Path(dossier_rapport(USER))
    except Exception as _e:
        _log.warning("Jeton de rapport indisponible (%s) -- repli sur docs/%s", _e, USER)
        OUT_DIR = Path(f"docs/{USER}")
else:
    OUT_DIR = Path("docs")

OUT_DIR.mkdir(parents=True, exist_ok=True)
HTML_PATH    = OUT_DIR / "index.html"
ARCHIVE_PATH = OUT_DIR / "archive.json"
CHARTS_DIR   = Path(f"reports/{USER}/charts") if USER else Path("reports/charts")
COMBINED_PNG = CHARTS_DIR / "portfolio_combined.png"

# ── Lecture Markdown ──────────────────────────────────────────
if not MD_PATH.exists():
    _log.warning("reports/daily_report.md introuvable — page vide générée.")
    md_content = "# Rapport indisponible\n\nAucun rapport généré ce jour."
else:
    md_content = MD_PATH.read_text(encoding="utf-8")

# ── Date du rapport ───────────────────────────────────────────
date_match  = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", md_content)
report_date = date_match.group(1) if date_match else \
              datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

# ── Graphique combiné → base64 ──────────────────────────────────
combined_b64 = ""
if COMBINED_PNG.exists():
    combined_b64 = base64.b64encode(COMBINED_PNG.read_bytes()).decode()

# ══════════════════════════════════════════════════════
# EXTRACTION KPI
# Cible la ligne TOTAL (en gras) dans le tableau Synthèse :
#   | **TOTAL** | — | **VM** | **pnl_brut (pct%)** | **pnl_net (pct%)** | — | — |
# ══════════════════════════════════════════════════════
def extract_kpi(md: str) -> dict:
    kpi = {"pnl_net": "0", "pnl_pct": "0", "valeur_marche": "0",
           "cout_total": "0", "pnl_brut": "0", "pnl_brut_pct": "0"}

    # ── Ligne TOTAL du tableau synthèse ───────────────────────────────────
    # Format réel :
    #   | **TOTAL** | — | **633.60** | **-35.28 (-5.3%)** | **-75.02 (-11.2%)** | — | — |
    m_total = re.search(
        r"\|\s*\*{0,2}TOTAL\*{0,2}\s*\|[^|]*\|\s*\*{0,2}([\d\s,.]+)\*{0,2}\s*\|"   # VM
        r"\s*\*{0,2}([+-][\d\s,.]+)\s*\(([-+]?[\d,.]+)%\)\*{0,2}\s*\|"              # pnl_brut (pct)
        r"\s*\*{0,2}([+-][\d\s,.]+)\s*\(([-+]?[\d,.]+)%\)\*{0,2}\s*\|",             # pnl_net (pct)
        md)
    if m_total:
        kpi["valeur_marche"] = m_total.group(1).strip().replace(" ", "").replace(",", ".")
        kpi["pnl_brut"]      = m_total.group(2).strip().replace(" ", "")
        kpi["pnl_brut_pct"]  = m_total.group(3).strip()
        kpi["pnl_net"]       = m_total.group(4).strip().replace(" ", "")
        kpi["pnl_pct"]       = m_total.group(5).strip()
        # Coût total = VM - pnl_brut
        try:
            vm_f  = float(kpi["valeur_marche"].replace(",", "."))
            pb_f  = float(kpi["pnl_brut"].replace(",", "."))
            kpi["cout_total"] = f"{vm_f - pb_f:.2f}"
        except Exception:
            kpi["cout_total"] = "0"
        return kpi

    # ── Fallback : ancienne regex (tableau avec coût total explicite) ──────
    m = re.search(
        r"\|\s*([\d\s,.]+)\s*EUR\s*\|\s*([\d\s,.]+)\s*EUR\s*"
        r"\|[^|]*?([+-][\d\s,.]+)\s*EUR[^|]*?([-+]?[\d,.]+)%[^|]*"
        r"\|[^|]*?([+-][\d\s,.]+)\s*EUR[^|]*?([-+]?[\d,.]+)%",
        md)
    if m:
        kpi["cout_total"]    = m.group(1).strip().replace(" ", "")
        kpi["valeur_marche"] = m.group(2).strip().replace(" ", "")
        kpi["pnl_brut"]      = m.group(3).strip().replace(" ", "")
        kpi["pnl_brut_pct"]  = m.group(4).strip()
        kpi["pnl_net"]       = m.group(5).strip().replace(" ", "")
        kpi["pnl_pct"]       = m.group(6).strip()
    return kpi

kpi = extract_kpi(md_content)

def fmt_num(s: str, decimals: int = 2) -> str:
    try:
        v = float(s.replace(",", ".").replace(" ", ""))
        if v >= 0:
            return f"+{v:,.{decimals}f}".replace(",", " ").replace(".", ",")
        return f"{v:,.{decimals}f}".replace(",", " ").replace(".", ",")
    except Exception:
        return s

def raw_abs(s: str) -> str:
    return s.lstrip("+-").replace(",", ".").replace(" ", "")

pnl_positive    = not kpi["pnl_net"].startswith("-")
pnl_class       = "kpi-positive" if pnl_positive else "kpi-negative"
brut_positive   = not kpi["pnl_brut"].startswith("-")
brut_class      = "kpi-positive" if brut_positive else "kpi-negative"

# ══════════════════════════════════════════════════════
# EXTRACTION POSITIONS (blocs ### Valeur)
# ══════════════════════════════════════════════════════
def extract_positions(md: str) -> list[dict]:
    positions = []
    blocks = re.split(r"(?=^### .+`)", md, flags=re.MULTILINE)
    for block in blocks:
        m_head = re.match(r"^### (.+?)\s*`([^`]+)`", block)
        if not m_head:
            continue
        name   = m_head.group(1).strip()
        ticker = m_head.group(2).strip()

        # ── Ligne de données du tableau de position ────────────────────────
        # Format réel (exemple) :
        #   | 90.41 EUR | ^ +0.00% | 180.82 EUR | - -7.00 EUR (-3.7%) | - -20.90 EUR (-11.1%) | **6.43/10** | ACHAT MODERE |
        # Groupe 1 : cours (ex: 90.41)
        # Groupe 2 : variation complète (ex: ^ +0.00%)
        # Groupe 3 : VM (ex: 180.82)
        # Groupe 4 : pnl_brut complet (ex: - -7.00 EUR (-3.7%))
        # Groupe 5 : pnl_net complet (ex: - -20.90 EUR (-11.1%))
        # Groupe 6 : score (ex: 6.43/10)
        # Groupe 7 : recommandation (ex: ACHAT MODERE)
        # La cellule de note vaut soit "**6.33/10**" (format v7.1), soit
        # "**6.33/10** (100%)" depuis la v7.2 qui y accole l'indice de
        # confiance, soit "n/d" quand aucune note n'a pu etre calculee.
        # Les trois doivent passer : un rapport genere par une version
        # anterieure reste lisible.
        m_row = re.search(
            r"\|\s*([\d,.]+)\s*EUR\s*\|"              # cours EUR
            r"\s*([^|]+?)\s*\|"                        # variation (^ +0.00% etc.)
            r"\s*([\d,.]+)\s*EUR\s*\|"                 # VM EUR
            r"\s*([^|]*?EUR[^|]*?)\s*\|"               # pnl_brut
            r"\s*([^|]*?EUR[^|]*?)\s*\|"               # pnl_net
            r"\s*\*{0,2}([\d.]+/10|n/d)\*{0,2}"        # note
            r"\s*(?:\(\s*([\d.]+)\s*%\s*\))?\s*\|"     # confiance, facultative
            r"\s*([^|]+?)\s*\|",                       # recommandation
            block)
        if not m_row:
            continue
        prix      = m_row.group(1).strip()
        variation = m_row.group(2).strip()
        vm        = m_row.group(3).strip()
        pnl_brut  = m_row.group(4).strip()
        pnl_net   = m_row.group(5).strip()
        score     = m_row.group(6).strip()
        confiance = (m_row.group(7) or "").strip()
        rec       = m_row.group(8).strip()

        # Momentum : extrait depuis la ligne "Perf. historique :"
        # Format reel emis par portfolio_analyzer.py :
        #   **Perf. historique :** 1M -0.3% | 3M +39.9% | 6M +52.2% -- HAUSSIER *(source : ...)*
        # BUG CORRIGE (21/09/2026) : la regex ne sautait pas les "**" de mise
        # en gras markdown entourant "Perf. historique :", donc apres le
        # ":" elle ne trouvait jamais directement "1M" (bloque par "**") et
        # ne matchait plus jamais -- le momentum retombait systematiquement
        # sur le fallback "—" / ancienne regex "Momentum" (elle-meme
        # obsolete, plus emise par le generateur actuel).
        m_perf = re.search(
            r"\*{0,2}Perf\. historique\*{0,2}[^:]*:\*{0,2}\s*1M\s*([^\s|]+)\s*\|\s*3M\s*([^\s|]+)\s*\|\s*6M\s*([^\s|]+)\s*--\s*(\w+)",
            block)
        if m_perf:
            ret_1m    = m_perf.group(1).strip()
            ret_3m    = m_perf.group(2).strip()
            ret_6m    = m_perf.group(3).strip()
            mom_label = m_perf.group(4).strip()
        else:
            # Fallback ancienne regex Momentum
            m_mom = re.search(
                r"Momentum[^:]*:\s*(\w+)\s*\(1M:\s*([^/]+)/\s*3M:\s*([^/]+)/\s*6M:\s*([^)]+)\)",
                block)
            mom_label = m_mom.group(1) if m_mom else "—"
            ret_1m    = m_mom.group(2).strip() if m_mom else "—"
            ret_3m    = m_mom.group(3).strip() if m_mom else "—"
            ret_6m    = m_mom.group(4).strip() if m_mom else "—"

        synthesis = ""
        synth_src = ""

        m_synth_src = re.search(
            r"\*\*Actualite[^*]*\*\*[^(]*\(source\s*:\s*([^)]+?)\s*\)?[\s*]*(?:\n|$)",
            block)
        if m_synth_src:
            synth_src = m_synth_src.group(1).strip().rstrip(")*").strip()

        synth_block = block
        m_actualite_pos = re.search(r"\*\*Actualite[^*]*\*\*", block)
        if m_actualite_pos:
            synth_block = block[m_actualite_pos.start():]
        synth_lines = re.findall(r"^>\s*(.+)", synth_block, flags=re.MULTILINE)
        if synth_lines:
            synthesis = " ".join(line.strip() for line in synth_lines).strip()

        # Detail de la note : le tableau "| Composante | Note | Poids |"
        composantes = re.findall(
            r"^\|\s*([A-Za-zÀ-ÿ' ]+?)\s*\|\s*([\d.]+)/10\s*\|\s*([\d.]+)\s*%\s*\|",
            block, flags=re.MULTILINE)

        m_fonda = re.search(r"\*\*Fondamentaux\s*:\*\*\s*(.+?)\s*(?:\*\(source|$)",
                            block, flags=re.MULTILINE)
        fondamentaux = m_fonda.group(1).strip() if m_fonda else ""

        # BUG CORRIGE (21/09/2026) : cette regex cherchait l'ancienne phrase
        # "Non disponible : ..." qui melangeait deux sens differents. Depuis
        # la v14, portfolio_analyzer.py emet DEUX phrases distinctes (voir
        # son commentaire "DEUX PHRASES, DEUX SENS") : l'ancienne regex ne
        # matchait plus rien du tout, donc cette information disparaissait
        # completement du rapport HTML.
        #   - "Sans objet" : critere qui n'existe pas pour ce type d'actif
        #     (ex. valorisation pour un ETF) -- normal, ne baisse PAS la
        #     confiance.
        #   - "Attendu mais non obtenu" : critere qui aurait du etre
        #     disponible mais que la donnee source n'a pas fourni -- c'est
        #     ce qui baisse reellement la confiance.
        m_sans_objet = re.search(
            r"\*Sans objet pour un actif de type[^:]*:\s*([^.]+?)\.\s*Ces crit[eè]res",
            block)
        sans_objet = m_sans_objet.group(1).strip() if m_sans_objet else ""

        m_manquants = re.search(
            r"\*Attendu mais non obtenu\s*:\s*([^-]+?)\s*--", block)
        manquants = m_manquants.group(1).strip() if m_manquants else ""

        # AJOUT (21/09/2026) : justification et consensus analystes, emis
        # par portfolio_analyzer.py mais jamais captures jusqu'ici -- ils
        # n'apparaissaient donc nulle part sur le rapport HTML.
        m_just = re.search(r"\*\*Justification\s*:\*\*\s*(.+?)\s*(?:\n\n|---|$)",
                            block, flags=re.DOTALL)
        justification = m_just.group(1).strip() if m_just else ""

        m_cons = re.search(
            r"\*\*Consensus analystes\s*:\*\*\s*(.+?)\s*\*\(source\s*:\s*([^)]+?)\)?\*?\s*(?:\n|$)",
            block)
        consensus     = m_cons.group(1).strip() if m_cons else ""
        consensus_src = m_cons.group(2).strip() if m_cons else ""

        positions.append({
            "name": name, "ticker": ticker,
            "prix": prix, "variation": variation, "vm": vm,
            "pnl_brut": pnl_brut, "pnl_net": pnl_net,
            "score": score, "confiance": confiance, "rec": rec,
            "composantes": composantes, "fondamentaux": fondamentaux,
            "sans_objet": sans_objet, "manquants": manquants,
            "justification": justification,
            "consensus": consensus, "consensus_src": consensus_src,
            "mom_label": mom_label,
            "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_6m": ret_6m,
            "synthesis": synthesis, "synth_src": synth_src,
        })
    return positions

positions = extract_positions(md_content)

# ══════════════════════════════════════════════════════
# EXTRACTION SYNTHÈSE / CLASSEMENT
# ══════════════════════════════════════════════════════
def extract_synthese(md: str) -> list[dict]:
    """Lignes du tableau de synthese, indexees PAR NOM DE COLONNE.

    L'ancienne version lisait les cellules par position (cells[1], cells[3]...).
    Le nombre de colonnes du rapport ayant change entre versions, les valeurs
    se retrouvaient decalees sous les mauvais en-tetes. On s'appuie desormais
    sur la ligne d'en-tete du tableau, ce qui reste correct quel que soit
    l'ordre ou le nombre de colonnes.
    """
    rows, entete, in_class = [], None, False

    for line in md.split("\n"):
        if "Synthese Portefeuille" in line or "Classement par Score" in line:
            in_class, entete = True, None
            continue
        if not in_class:
            continue

        # Une ligne vide ou un titre termine le tableau : sans cela on
        # aspirait aussi les lignes des tableaux suivants.
        if not line.strip() or line.startswith("#"):
            if entete is not None:
                in_class = False
            continue
        if not line.lstrip().startswith("|"):
            continue
        if re.match(r"^\s*\|[-| :]+\|", line):
            continue

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if entete is None:
            entete = [re.sub(r"[*]+", "", c).strip().lower() for c in cells]
            continue

        nom = re.sub(r"[*]+", "", cells[0]).strip()
        if not nom or nom.upper() in ("VALEUR", "COUT TOTAL"):
            continue
        rows.append({entete[i]: cells[i] for i in range(min(len(entete), len(cells)))})

    return rows

synthese_rows = extract_synthese(md_content)


def extract_closes(md: str) -> tuple:
    """Lignes du tableau des plus-values realisees + total."""
    m = re.search(r"## Plus-values realisees(.*?)(?:\n## |\Z)", md, re.S)
    if not m:
        return [], None

    ops, total, entete = [], None, None
    for line in m.group(1).split("\n"):
        if not line.lstrip().startswith("|"):
            continue
        if re.match(r"^\s*\|[-| :]+\|", line):
            continue
        cells = [re.sub(r"[*]+", "", c).strip()
                 for c in line.strip().strip("|").split("|")]
        if entete is None:
            entete = cells
            continue
        if cells[0].upper() == "TOTAL":
            total = cells
        else:
            ops.append(cells)

    # Dates de vente, listees sous le tableau
    dates = dict(re.findall(r"^-\s*(.+?)\s*:\s*vendu le\s*(.+?)\s*$",
                            m.group(1), flags=re.MULTILINE))
    for o in ops:
        o.append(dates.get(o[0], ""))
    return ops, total


closes_rows, closes_total = extract_closes(md_content)

# ══════════════════════════════════════════════════════
# EXTRACTION INDICES MACRO
# ══════════════════════════════════════════════════════
def extract_indices(md: str) -> list[dict]:
    indices = []
    in_idx = False
    for line in md.split("\n"):
        if "Indice" in line and "Variation" in line:
            in_idx = True
            continue
        if in_idx and re.match(r"^\|[-| :]+\|", line):
            continue
        if in_idx and re.match(r"^\|", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0]:
                indices.append({"name": cells[0], "variation": cells[1], "cours": cells[2]})
        elif in_idx and line.strip() == "":
            in_idx = False
    return indices

indices = extract_indices(md_content)

# ══════════════════════════════════════════════════════
# ARCHIVE JSON
# ══════════════════════════════════════════════════════
Path("docs").mkdir(exist_ok=True)
archive = []
if ARCHIVE_PATH.exists():
    try:
        archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        archive = []

pnl_archive = f"{fmt_num(kpi['pnl_net'])} € ({fmt_num(kpi['pnl_pct'], 1)}%)"
archive = [e for e in archive if e.get("date") != report_date]
archive.insert(0, {
    "date":    report_date,
    "pnl":     pnl_archive,
    "vm":      kpi["valeur_marche"],
    "nb_pos":  str(len(positions)),
})
# AJOUT (26/09/2026) : le graphique "Trajectoire du portefeuille" (page
# Portefeuille) affiche la valeur nette depuis le debut du suivi. Il lit
# ce meme fichier archive.json cote client. La retention etait plafonnee
# a 30 entrees -- suffisant pour le tableau "Historique des rapports" mais
# pas pour une vraie trajectoire "depuis le debut". Le fichier conserve
# desormais jusqu'a ARCHIVE_MAX entrees (~10 ans de rapports quotidiens) ;
# le tableau Historique continue lui de n'afficher que les 30 plus
# recentes (tronque cote JavaScript, voir loadArchive()).
ARCHIVE_MAX = 3650
archive = archive[:ARCHIVE_MAX]
ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

# ══════════════════════════════════════════════════════
# HELPERS HTML
# ══════════════════════════════════════════════════════
def esc(txt) -> str:
    """Echappe le HTML dans tout texte d'origine externe (actualites RSS,
    noms/tickers saisis par l'utilisateur) avant interpolation dans une
    f-string HTML. BUG CORRIGE (21/09/2026) : aucune fonction de ce genre
    n'existait dans ce fichier -- tout texte, y compris les synthèses
    d'actualités tirées du flux RSS (donc non maîtrisées), était injecté
    tel quel dans le HTML final. Un simple caractère "<" dans une dépêche
    suffisait à casser la mise en page ; un contenu construit exprès y
    aurait pu inserer du HTML/JS."""
    if txt is None:
        return ""
    return html.escape(str(txt), quote=True)

def expl(contenu_html: str, label: str = "Voir l'explication") -> str:
    """AJOUT (22/09/2026), a la demande de Gaby : le rapport contenait trop
    de texte explicatif fixe (paragraphes pedagogiques qui ne changent pas
    d'un jour a l'autre, ex. "comment lire ce chiffre") affiche en
    permanence, ce qui l'alourdissait. On reprend le meme principe deja en
    place pour "Comment cette note est calculee" (un <details> repliable) :
    seuls les chiffres et le contenu propre au jour restent visibles direct;
    les explications generales passent derriere un petit bouton a ouvrir
    si on le souhaite."""
    return f'<details class="expl-toggle"><summary>{label}</summary>{contenu_html}</details>'

def rec_badge(rec: str) -> str:
    # BUG CORRIGE (21/09/2026) : ce test reconnaissait un vocabulaire
    # (ACHAT FORT / ACHAT / GARDER / EVITER / VENDRE) que
    # portfolio_analyzer.recommend() n'emet plus depuis la refonte des
    # recommandations. Toute position tombait donc dans le "else" et
    # affichait un badge "hold" gris identique quel que soit l'avis reel.
    # Vocabulaire actuel de recommend() : RENFORCER / CONSERVER /
    # SURVEILLER (+ variante "en moins-value") / ALLEGER / SORTIR, plus les
    # etats "on ne peut pas conclure" (A EXAMINER x2 / DONNEES
    # INSUFFISANTES) et NON COTE (actif non cote, hors echelle d'avis).
    rec_u = rec.upper()
    if "RENFORCER"    in rec_u: cls = "buy-strong"
    elif "CONSERVER"  in rec_u: cls = "buy-mod"
    elif "SURVEILLER" in rec_u: cls = "hold"
    elif "ALLEGER"    in rec_u or "ALLÉGER" in rec_u: cls = "avoid"
    elif "SORTIR"     in rec_u: cls = "sell"
    elif "A EXAMINER" in rec_u or "À EXAMINER" in rec_u or "DONNEES INSUFFISANTES" in rec_u \
        or "DONNÉES INSUFFISANTES" in rec_u or "NON COTE" in rec_u or "NON COTÉ" in rec_u:
        cls = "unknown"
    else:                       cls = "unknown"
    return f'<span class="badge {cls}">{esc(rec)}</span>'

def score_bar(score_str: str) -> str:
    try:
        val = float(score_str.split("/")[0])
        pct = val / 10 * 100
        cls = "bar-green" if val >= 6.5 else "bar-red" if val <= 3.5 else "bar-yellow"
        return (f'<div class="score-wrap">'
                f'<span class="score-num">{score_str}</span>'
                f'<div class="score-bar"><div class="score-fill {cls}" style="width:{pct:.0f}%"></div></div>'
                f'</div>')
    except Exception:
        return score_str

def pnl_cell(txt: str) -> str:
    t = txt.strip()
    cls = ""
    if "+" in t: cls = "cell-pos"
    elif "-" in t and any(c.isdigit() for c in t): cls = "cell-neg"
    return f'<td class="{cls}">{t}</td>' if cls else f'<td class="cell-num">{t}</td>'

def mom_badge(label: str) -> str:
    l = label.upper()
    if "HAUSSE" in l or "HAUSSIER" in l: return f'<span class="badge buy-strong">↗ {esc(label)}</span>'
    if "BAISSE" in l or "BAISSIER" in l: return f'<span class="badge sell">↘ {esc(label)}</span>'
    return f'<span class="badge hold">→ {esc(label)}</span>'

def var_span(txt: str) -> str:
    t = txt.strip()
    # Supprime le préfixe ^ ou v produit par portfolio_analyzer
    clean = re.sub(r"^[\^v]\s*", "", t)
    if clean.startswith("+") or (re.search(r"\+\d", clean)):
        return f'<span class="up">▲ {clean}</span>'
    if clean.startswith("-") or (re.search(r"-\d", clean)):
        return f'<span class="dn">▼ {clean}</span>'
    return clean

# ══════════════════════════════════════════════════════
# BLOCS HTML
# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# EXTRACTION TAUX 10 ANS
# ══════════════════════════════════════════════════════
def extract_bonds(md: str) -> list[dict]:
    """Lignes du tableau des taux souverains.

    Tolere 3 ou 4 colonnes : la colonne "Sur 1 mois" n'existe pas dans les
    rapports anterieurs a la v7.4.
    """
    bonds, in_bnd = [], False
    for line in md.split("\n"):
        if "Taux" in line and "Variation" in line and "Niveau" in line:
            in_bnd = True
            continue
        if not in_bnd:
            continue
        if re.match(r"^\|[-| :]+\|", line):
            continue
        if line.strip() == "" or not line.lstrip().startswith("|"):
            in_bnd = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0]:
            bonds.append({
                "name":      re.sub(r"[*]+", "", cells[0]).strip(),
                "variation": cells[1],
                "niveau":    cells[2],
                "tendance":  cells[3] if len(cells) > 3 else "",
            })
    return bonds

bonds = extract_bonds(md_content)


# ══════════════════════════════════════════════════════
# EXTRACTION — STOPS, DIMENSIONNEMENT, RÉPARTITION
# ══════════════════════════════════════════════════════
# Ces trois blocs sont apparus avec la v8. Un rapport plus ancien ne les
# contient pas : chaque extracteur renvoie alors une liste vide et la section
# correspondante n'est tout simplement pas rendue. La page reste valide.

def _section_md(md: str, titre: str) -> str:
    """Texte compris entre « ## titre » et le titre de niveau 2 suivant."""
    debut = md.find(f"## {titre}")
    if debut < 0:
        return ""
    suite = md.find("\n## ", debut + 3)
    return md[debut:suite if suite > 0 else len(md)]


def _lignes_table(texte: str, cles: list) -> list:
    """Lignes de la première table dont l'en-tête contient toutes les `cles`.

    Retourne une liste de listes de cellules, déjà débarrassées des `|`.
    Volontairement tolérant : une colonne ajoutée plus tard ne casse rien,
    l'appelant lit les cellules par index et ignore le surplus.
    """
    lignes, dans_table = [], False
    for ligne in texte.split("\n"):
        brut = ligne.strip()
        if not dans_table:
            if brut.startswith("|") and all(c.lower() in brut.lower() for c in cles):
                dans_table = True
            continue
        if re.match(r"^\|[-| :]+\|$", brut):
            continue
        if not brut.startswith("|"):
            break
        cellules = [c.strip() for c in brut.strip("|").split("|")]
        if cellules and cellules[0]:
            lignes.append(cellules)
    return lignes


def extract_stops(md: str) -> dict:
    """Section « Stops et Alertes » → structure exploitable par le rendu."""
    sec = _section_md(md, "Stops et Alertes")
    if not sec:
        return {}

    # BUG CORRIGE (21/09/2026) : quand le calcul du risque echoue ou n'est
    # pas encore disponible, portfolio_analyzer.py (bloc_md_stops) n'ecrit
    # QUE une ligne "> Section indisponible : {motif}" -- pas de tableau de
    # stops. Cette information n'etait captee nulle part : build_stops_html
    # se contentait de masquer toute la section (stops vide), sans jamais
    # afficher le motif a l'utilisateur.
    m_motif = re.search(r">\s*Section indisponible\s*:\s*(.+)", sec)
    motif_indisponible = m_motif.group(1).strip() if m_motif else ""

    resume = {}
    m = re.search(r"Stops actifs\s*:\s*(\d+)\*\*.*?Franchis\s*:\s*(\d+)\*\*"
                  r".*?Sans stop\s*:\s*(\d+)\*\*.*?alertes du jour\s*:\s*(\d+)", sec)
    if m:
        resume = {"actifs": int(m.group(1)), "franchis": int(m.group(2)),
                  "sans_stop": int(m.group(3)), "alertes": int(m.group(4))}

    alertes = []
    if "ALERTES DU JOUR" in sec:
        zone = sec.split("ALERTES DU JOUR", 1)[1]
        for ligne in zone.split("\n"):
            ligne = ligne.strip()
            if ligne.startswith("- **"):
                alertes.append(re.sub(r"\*\*", "", ligne[2:]).strip())
            elif alertes and not ligne.startswith("-"):
                break

    stops = []
    for c in _lignes_table(sec, ["Valeur", "Niveau", "Statut"]):
        if len(c) < 8:
            continue
        stops.append({"nom": c[0], "compte": c[1], "type": c[2], "config": c[3],
                      "niveau": c[4], "cloture": c[5], "distance": c[6],
                      "statut": c[7]})

    tailles = []
    for c in _lignes_table(sec, ["Volatilit", "Taille sugg"]):
        if len(c) < 8:
            continue
        tailles.append({"nom": c[0], "vol": c[1], "atr": c[2], "vq": c[3],
                        "distance": c[4], "taille": c[5], "detenu": c[6],
                        "ecart": c[7]})

    entete = ""
    m = re.search(r"Capital de r[eé]f[eé]rence[^\n]*", sec)
    if m:
        entete = re.sub(r"\*\*", "", m.group(0)).strip()

    note = ""
    m = re.search(r"Premi[eè]re [eé]valuation pour[^\n]*", sec)
    if m:
        note = re.sub(r"[*]", "", m.group(0)).strip()

    # Exposition correlee : soit une table de groupes, soit un message
    # "aucun regroupement" -- jamais les deux.
    expo_groupes, expo_msg = [], ""
    for c in _lignes_table(sec, ["Groupe", "Poids"]):
        if len(c) < 3:
            continue
        expo_groupes.append({"groupe": c[0], "poids": c[1], "alerte": c[2]})
    if not expo_groupes:
        m = re.search(r"Aucun regroupement[^\n]*", sec)
        if m:
            expo_msg = re.sub(r"[*]", "", m.group(0)).strip()

    # Indice de correlation moyenne : un chiffre unique, absent si le
    # portefeuille a moins de deux lignes cotees avec un historique suffisant.
    expo_indice = {}
    m = re.search(r"Corr[eé]lation moyenne du portefeuille\s*:\s*"
                  r"([+-]?[\d.,]+)\s*%\*\*\s*\(([^)]+)\)", sec)
    if m:
        expo_indice["valeur"] = m.group(1).replace(",", ".")
        expo_indice["classe"] = m.group(2).strip()
        mp = re.search(r"calcul[ée]e? sur (\d+) paire", sec)
        expo_indice["n_paires"] = mp.group(1) if mp else "?"
        ml = re.search(r"(\d+) ligne\(s\) cot[ée]e", sec)
        expo_indice["n_lignes"] = ml.group(1) if ml else "?"
        me = re.search(r"[EÉ]tendue observ[ée]e\s*:\s*de\s*([+-]?[\d.,]+)\s*%\s*"
                       r"[àa]\s*([+-]?[\d.,]+)\s*%", sec)
        if me:
            expo_indice["min"] = me.group(1).replace(",", ".")
            expo_indice["max"] = me.group(2).replace(",", ".")

    return {"resume": resume, "alertes": alertes, "stops": stops,
            "tailles": tailles, "entete_sizing": entete, "amorcage": note,
            "expo_groupes": expo_groupes, "expo_msg": expo_msg,
            "expo_indice": expo_indice, "motif_indisponible": motif_indisponible}


def extract_repartition(md: str) -> list:
    """Section « Repartition » → liste d'axes [{titre, entrees}]."""
    sec = _section_md(md, "Repartition")
    if not sec:
        return []

    axes, courant = [], None
    dans_table = False
    for ligne in sec.split("\n"):
        brut = ligne.strip()
        m = re.match(r"^\*\*(Par [^*]+)\*\*$", brut)
        if m:
            courant = {"titre": m.group(1).strip(), "entrees": []}
            axes.append(courant)
            dans_table = False
            continue
        if courant is None:
            continue
        if brut.startswith("| Poste"):
            dans_table = True
            continue
        if re.match(r"^\|[-| :]+\|$", brut):
            continue
        if dans_table and brut.startswith("|"):
            c = [x.strip() for x in brut.strip("|").split("|")]
            if len(c) >= 3:
                part = 0.0
                mp = re.search(r"([\d.,]+)", c[2])
                if mp:
                    try:
                        part = float(mp.group(1).replace(",", "."))
                    except ValueError:
                        part = 0.0
                courant["entrees"].append({"libelle": c[0], "montant": c[1],
                                           "part": part, "part_txt": c[2]})
        elif dans_table:
            dans_table = False
    return [a for a in axes if a["entrees"]]


def extract_watchlist(md: str) -> list:
    """Section « Watchlist » → liste de titres suivis, non détenus.

    Absente de generate_html.py jusqu'ici : portfolio_analyzer.py génère
    bien la section « ## Watchlist » dans le markdown, mais rien ne
    l'extrayait ni ne la rendait côté HTML — elle disparaissait donc
    silencieusement du rapport que Gaby consulte, alors même que la
    watchlist contenait des titres.
    """
    sec = _section_md(md, "Watchlist")
    if not sec:
        return []
    watchlist = []
    for c in _lignes_table(sec, ["Valeur", "Secteur", "Cours"]):
        if len(c) < 5:
            continue
        watchlist.append({"nom": c[0], "secteur": c[1], "cours": c[2],
                          "variation": c[3], "actualite": c[4]})
    return watchlist


def extract_avertissements(md: str) -> list:
    """Section « ## Avertissements Donnees » + la ligne EUR/USD isolee.

    AJOUT (21/09/2026) : portfolio_analyzer.py écrit ces avertissements
    (ex. donnée jugée périmée, taux de change suspect...) dans le markdown,
    mais rien ne les récupérait côté HTML — Gaby ne les voyait jamais alors
    qu'ils signalent une donnée potentiellement fausse dans le rapport.
    """
    sec = _section_md(md, "Avertissements Donnees")
    avertissements = re.findall(r"^-\s*⚠️?\s*(.+)", sec, flags=re.MULTILINE) if sec else []
    m_eur = re.search(r"^>\s*⚠️?\s*(.+)", md, flags=re.MULTILINE)
    if m_eur and ("EUR" in m_eur.group(1) or "USD" in m_eur.group(1) or "change" in m_eur.group(1).lower()):
        avertissements.append(m_eur.group(1).strip())
    return [a.strip() for a in avertissements if a.strip()]


stops_data  = extract_stops(md_content)
repartition = extract_repartition(md_content)
watchlist   = extract_watchlist(md_content)
avertissements_donnees = extract_avertissements(md_content)


# ══════════════════════════════════════════════════════
# RENDU — STOPS ET ALERTES
# ══════════════════════════════════════════════════════

_CLASSE_STATUT = {
    "OK":            ("stop-ok",     "OK"),
    "FRANCHI":       ("stop-ko",     "Franchi"),
    "Aucun":         ("stop-none",   "Aucun"),
    "Incalculable":  ("stop-warn",   "Incalculable"),
}


def _barre_distance(txt: str) -> str:
    """Jauge de distance au stop, calquée sur le tableau du rapport.

    La distance est bornée à 60% pour l'affichage : au-delà, la position est
    tellement au-dessus de son stop que la longueur exacte de la barre
    n'apprend plus rien, alors que l'écraser rendrait les petites distances
    illisibles.
    """
    m = re.search(r"([+-]?[\d.,]+)", txt or "")
    if not m:
        return '<span class="dist-txt">—</span>'
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return '<span class="dist-txt">—</span>'

    if val < 0:
        return (f'<span class="dist-wrap"><span class="dist-rail">'
                f'<span class="dist-fill dist-neg" style="width:6%"></span></span>'
                f'<span class="dist-txt cell-neg">sous le stop</span></span>')
    pct = min(val / 60.0 * 100.0, 100.0)
    teinte = "dist-tight" if val < 8 else "dist-ok"
    return (f'<span class="dist-wrap"><span class="dist-rail">'
            f'<span class="dist-fill {teinte}" style="width:{pct:.0f}%"></span></span>'
            f'<span class="dist-txt">{val:.1f}% au-dessus</span></span>')



# ══════════════════════════════════════════════════════
# RENDU — STOPS ET ALERTES  (page Technique)
# ══════════════════════════════════════════════════════

def build_stops_html() -> str:
    if not stops_data:
        return ""
    if not stops_data.get("stops"):
        # BUG CORRIGE (21/09/2026) : auparavant, l'absence de tableau de
        # stops faisait disparaitre TOUTE la section, y compris le motif
        # explicatif ("donnees insuffisantes", "premiere evaluation", etc.)
        if stops_data.get("motif_indisponible"):
            return f"""
<article class="card section" id="stops">
  <div class="section-title"><h2>Stops &amp; alertes</h2></div>
  <p class="macro-note">Section indisponible : {esc(stops_data["motif_indisponible"])}</p>
</article>"""
        return ""

    res  = stops_data.get("resume") or {}
    cartes = ""
    for cle, libelle, classe in (("actifs", "Stops actifs", ""),
                                 ("franchis", "Franchis", "alert"),
                                 ("sans_stop", "Sans stop", ""),
                                 ("alertes", "Alertes du jour", "alert")):
        if cle not in res:
            continue
        val = res[cle]
        cl = classe if (classe and val) else ""
        cartes += (f'<div class="mini-card {cl}"><div class="mini-val">{val}</div>'
                   f'<div class="mini-lbl">{libelle}</div></div>')

    banniere = ""
    if stops_data.get("alertes"):
        items = "".join(f"<li>{esc(a)}</li>" for a in stops_data["alertes"])
        banniere = (f'<div class="callout danger" style="margin-bottom:16px">'
                    f'<strong>Alertes du jour</strong><ul>{items}</ul></div>')

    amorce = ""
    if stops_data.get("amorcage"):
        amorce = f'<p class="macro-note">{esc(stops_data["amorcage"])}</p>'

    rows = ""
    for st in stops_data["stops"]:
        cls, lib = _CLASSE_STATUT.get(st["statut"], ("stop-none", st["statut"]))
        compte = st["compte"] if st["compte"] not in ("--", "—", "") else "—"
        rows += (f'<tr><td><strong>{esc(st["nom"])}</strong>'
                 f'<div class="sub-lbl">{esc(compte)}</div></td>'
                 f'<td><span class="type-tag">{esc(st["type"])}</span></td>'
                 f'<td class="cfg-cell">{esc(st["config"])}</td>'
                 f'<td class="cell-num">{esc(st["niveau"])}</td>'
                 f'<td class="cell-num">{esc(st["cloture"])}</td>'
                 f'<td>{_barre_distance(st["distance"])}</td>'
                 f'<td><span class="badge {cls}">{esc(lib)}</span></td></tr>\n')

    return f"""
<article class="card section" id="stops">
  <div class="section-title"><h2>Stops &amp; alertes</h2></div>
  {banniere}
  <div class="mini-bar">{cartes}</div>
  {amorce}
  <div class="table-wrap">
    <table>
      <thead><tr><th>Position</th><th>Type</th><th>Configuration</th>
        <th>Niveau</th><th>Clôture</th><th>Distance</th><th>Statut</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  {expl('''
  <p class="macro-note">
    Un stop est franchi quand la <strong>clôture</strong> du jour passe sous le
    niveau — pas le cours en séance, dont les à-coups produisent des sorties
    inutiles. Une seule alerte par franchissement&nbsp;; le déclencheur se
    ré-arme quand le cours repasse au-dessus. Les stops suiveurs et VQ montent
    avec le cours et ne redescendent jamais.
  </p>''')}
</article>"""


def build_dimensionnement_html() -> str:
    if not stops_data or not stops_data.get("tailles"):
        return ""
    trows = ""
    for t in stops_data["tailles"]:
        # La mention de bridage (« plafonné à 15 % du capital ») est
        # une precision, pas une valeur : elle passe en seconde ligne pour
        # ne pas etirer la colonne et pousser le tableau hors de l'ecran.
        taille, _, precision = t["taille"].partition(" (")
        cell_taille = taille
        if precision:
            cell_taille += f'<div class="sub-lbl">{precision.rstrip(")")}</div>'
        trows += (f'<tr><td><strong>{t["nom"]}</strong></td>'
                  f'<td>{t["vol"]}</td>'
                  f'<td class="cell-num">{t["atr"]}</td>'
                  f'<td class="cell-num">{t["vq"]}</td>'
                  f'<td class="cell-num">{t["distance"]}</td>'
                  f'<td class="cell-num">{cell_taille}</td>'
                  f'<td class="cell-num">{t["detenu"]}</td>'
                  f'<td class="cell-num">{t["ecart"]}</td></tr>\n')
    return f"""
<article class="card section" id="dimensionnement">
  <div class="section-title"><h2>Dimensionnement des positions</h2></div>
  <p class="macro-note">{stops_data.get('entete_sizing', '')}</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Valeur</th><th>Volatilité an.</th><th>Amplitude/jour</th><th>VQ</th>
        <th>Distance stop</th><th>Taille suggérée</th><th>Détenu</th><th>Écart</th></tr></thead>
      <tbody>{trows}</tbody>
    </table>
  </div>
  {expl('''
  <p class="macro-note">
    «&nbsp;Amplitude/jour&nbsp;» : de combien la valeur bouge en moyenne d'une
    clôture à l'autre — la lecture concrète de la volatilité.<br>
    Montant&nbsp;= (capital&nbsp;×&nbsp;risque par idée)&nbsp;÷&nbsp;distance au stop.
    Deux volatilités différentes reçoivent ainsi le même risque, pas
    le même montant. «&nbsp;Écart&nbsp;» = ce qui est détenu moins ce que le
    budget de risque justifierait : positif, la ligne est plus grosse que le
    risque accepté. Ce n'est pas un ordre de vente, c'est un écart à expliquer.
  </p>''')}
</article>"""


def build_correlation_html() -> str:
    if not stops_data:
        return ""
    expo_indice = stops_data.get("expo_indice") or {}
    expo_groupes = stops_data.get("expo_groupes")
    expo_msg = stops_data.get("expo_msg")
    if expo_indice.get("valeur") is None and not expo_groupes and not expo_msg:
        return ""

    ring_html = ""
    if expo_indice.get("valeur") is not None:
        try:
            val = float(expo_indice["valeur"])
        except (TypeError, ValueError):
            val = None
        # < 20% (ou negatif) : lignes independantes, plutot rassurant.
        # >= 70% : le portefeuille bouge comme un bloc, plutot un signal.
        couleur = ("var(--success)" if val is not None and val < 20 else
                  "var(--danger)" if val is not None and val >= 70 else "var(--warn)")
        pct_ring = max(0.0, min(val, 100.0)) if val is not None else 0.0
        etendue = (f", étendue observée de {expo_indice['min']}&nbsp;% à {expo_indice['max']}&nbsp;%"
                   if "min" in expo_indice else "")
        ring_html = f"""
  <div class="corr-row">
    <div class="ring" style="background:conic-gradient({couleur} 0 {pct_ring:.1f}%, var(--surface2) {pct_ring:.1f}% 100%)">
      <div><b>{esc(expo_indice['valeur'])}&nbsp;%</b><small>corrélation moy.</small></div>
    </div>
    <p class="corr-txt">
      Calculée sur {expo_indice.get('n_paires', '?')} paire(s) de lignes
      ({expo_indice.get('n_lignes', '?')} ligne(s) cotée(s) avec un historique
      suffisant){etendue}.
    </p>
  </div>"""

    groupes_html = ""
    if expo_groupes:
        erows = ""
        for g in expo_groupes:
            cls = "sortir" if "Oui" in g["alerte"] else "renforcer"
            erows += (f'<tr><td>{esc(g["groupe"])}</td>'
                      f'<td class="cell-num">{esc(g["poids"])}</td>'
                      f'<td><span class="badge {cls}">{esc(g["alerte"])}</span></td></tr>\n')
        groupes_html = f"""
  <div class="table-wrap">
    <table>
      <thead><tr><th>Groupe</th><th>Poids cumulé</th><th>Alerte</th></tr></thead>
      <tbody>{erows}</tbody>
    </table>
  </div>"""
    elif expo_msg:
        groupes_html = f'<p class="macro-note">{esc(expo_msg)}</p>'

    return f"""
<article class="card section" id="correlation">
  <div class="section-title"><h2>Exposition corrélée</h2></div>
  {ring_html}
  {groupes_html}
  {expl('''
  <p class="macro-note">
    Lignes dont les mouvements quotidiens sont fortement corrélés entre eux —
    prises ensemble, elles pèsent plus qu'un plafond de poids par ligne ne le
    laisse penser. Un signal d'attention basé sur le passé récent, pas une
    prévision.
  </p>''')}
</article>"""


# ══════════════════════════════════════════════════════
# RENDU — RÉPARTITION MULTI-ACTIFS  (page Portefeuille)
# ══════════════════════════════════════════════════════

def build_repartition_html() -> str:
    if not repartition:
        return ""
    blocs = ""
    for axe in repartition:
        lignes = ""
        for e in axe["entrees"]:
            lignes += (f'<div class="alloc-row">'
                       f'<div class="alloc-head">'
                       f'<span class="alloc-lbl" title="{e["libelle"]}">{e["libelle"]}</span>'
                       f'<span class="alloc-chiffres">'
                       f'<span class="alloc-part">{e["part_txt"]}</span>'
                       f'<span class="alloc-val">{e["montant"]}</span>'
                       f'</span></div>'
                       f'<div class="alloc-rail">'
                       f'<span class="alloc-fill" style="width:{min(e["part"],100):.1f}%"></span>'
                       f'</div></div>')
        blocs += (f'<div class="alloc-card"><h3 class="alloc-title">{axe["titre"]}</h3>'
                  f'{lignes}</div>')
    return f"""
<article class="card section" id="repartition">
  <div class="section-title"><h2>Répartition par axe</h2></div>
  <div class="alloc-grid">{blocs}</div>
  {expl('''
  <p class="macro-note">
    Un actif peut porter plusieurs étiquettes : la somme des parts par étiquette
    peut dépasser 100&nbsp;%. Les autres axes forment bien une partition.
  </p>''')}
</article>"""


# ══════════════════════════════════════════════════════
# RENDU — CONCENTRATION PAR POSITION (page Portefeuille, à côté
# de la trajectoire) et TRAJECTOIRE DU PORTEFEUILLE
# ══════════════════════════════════════════════════════

def build_concentration_html() -> str:
    """Poids de chaque position dans la valeur de marché totale. Calculé ici
    (et non dans portfolio_analyzer.py) car il ne demande aucune donnée
    nouvelle : seule la liste `positions` deja extraite est necessaire."""
    if not positions:
        return ""
    parsed = []
    total = 0.0
    for p in positions:
        try:
            v = float(str(p["vm"]).replace(" ", "").replace(",", "."))
        except (TypeError, ValueError):
            continue
        parsed.append((p["name"], v))
        total += v
    if total <= 0 or not parsed:
        return ""
    parsed.sort(key=lambda x: x[1], reverse=True)
    rows = ""
    for name, v in parsed:
        part = v / total * 100
        rows += (f'<div class="alloc-row"><div class="alloc-head">'
                  f'<span class="alloc-lbl">{esc(name)}</span><b>{part:.1f}&nbsp;%</b></div>'
                  f'<div class="alloc-rail"><span class="alloc-fill" '
                  f'style="width:{min(part,100):.1f}%"></span></div></div>')

    # Reprend, si disponible, le groupe le plus fortement corrélé (calculé
    # dans stops_data pour la page Technique) pour donner tout de suite le
    # contexte, sans recalculer une seconde fois la corrélation ici.
    alerte_html = ""
    if stops_data and stops_data.get("expo_groupes"):
        alertants = [g for g in stops_data["expo_groupes"] if "Oui" in g.get("alerte", "")]
        if alertants:
            g = alertants[0]
            alerte_html = (f'<div class="callout warn" style="margin-top:16px">'
                            f'<strong>Concentration à examiner</strong>'
                            f'{esc(g["groupe"])} — détail dans l\'onglet Technique.</div>')

    return f"""
<aside class="card">
  <div class="section-title"><h2>Concentration</h2><p>Poids par position</p></div>
  {rows}
  {alerte_html}
</aside>"""


def build_trajectoire_html() -> str:
    """Le contenu (points, echelle) est dessine cote client par drawTrajectoire()
    a partir d'archive.json : c'est le seul endroit qui connait l'historique
    complet (voir ARCHIVE_MAX plus haut)."""
    return """
<article class="card chart-card">
  <div class="section-title"><h2>Trajectoire du portefeuille</h2><p>Valeur nette depuis le début du suivi</p></div>
  <div class="chart-wrap">
    <svg id="trajectoire-svg" viewBox="0 0 720 250" preserveAspectRatio="none" role="img"
         aria-label="Valeur du portefeuille depuis le début du suivi"></svg>
    <p class="chart-empty" id="trajectoire-empty" style="display:none">
      Historique pas encore suffisant pour tracer une trajectoire — reviens dans quelques jours.
    </p>
  </div>
  <p class="chart-caption" id="trajectoire-caption">Chargement de l'historique…</p>
</article>"""


# ══════════════════════════════════════════════════════
# RENDU — FIABILITÉ DES NOTES (moteur d'apprentissage)
#   - un résumé en jauge, en aside de la page Technique
#   - le détail complet, inchangé, plus bas sur la même page
# ══════════════════════════════════════════════════════

def build_fiabilite_ring_html() -> str:
    if not learning:
        return ""
    c = learning["counts"]
    snap = c.get("snapshots", 0) or 0
    mat  = c.get("matured", 0) or 0
    pct  = (mat / snap * 100) if snap else 0.0

    h  = str(learning.get("horizon"))
    hs = learning.get("horizons_stats") or {}
    bloc = hs.get(h)
    titre = "Historique insuffisant"
    if bloc:
        kind = bloc.get("headline")
        st = (bloc.get("kinds") or {}).get(kind) or {}
        bandes = st.get("bands") or []
        haut = bandes[-1] if bandes else None
        if haut and haut.get("n"):
            titre = f"Confiance {_LIB_LVL.get(haut['confidence'], haut['confidence'])}"

    couleur = "var(--success)" if pct >= 50 else "var(--warn)" if pct >= 20 else "var(--danger)"
    detail = (f"{mat} observation(s) clôturée(s) sur {snap} note(s) enregistrée(s) "
              f"(horizon {h} séances).")

    return f"""
<aside class="card ring-card section sticky" id="fiabilite-ring">
  <div class="ring" style="background:conic-gradient({couleur} 0 {pct:.1f}%, var(--surface2) {pct:.1f}% 100%)">
    <div><b>{pct:.0f}&nbsp;%</b><small>observations évaluées</small></div>
  </div>
  <h3>{esc(titre)}</h3>
  <p>{esc(detail)}</p>
  <a class="ring-link" data-goto="technique" data-anchor="fiabilite" href="#fiabilite">Voir le détail complet</a>
</aside>"""


def load_learning_summary() -> dict:
    """Synthese du moteur d'apprentissage (learning_engine.write_summary).

    Lue depuis le JSON plutot que re-extraite du Markdown : les chiffres
    arrivent tels que calcules, sans passer par un formatage puis un parsing.
    Absent ou illisible -> {} et la section n'est simplement pas rendue.
    """
    chemin = Path(f"reports/{USER or 'default'}/learning/summary.json")
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("counts") else {}


learning = load_learning_summary()

_LIB_KIND = {"sector": "surperformance sectorielle", "market": "surperformance vs marché",
             "raw": "rendement brut"}
_LIB_LVL = {"elevee": "élevée", "moyenne": "moyenne", "faible": "faible",
            "insuffisante": "insuffisante"}


def _l_pct(v, dec=1) -> str:
    if v is None:
        return '<span class="sub-lbl">—</span>'
    cls = "cell-pos" if v > 0 else "cell-neg" if v < 0 else ""
    return f'<span class="{cls}">{v:+.{dec}f}&nbsp;%</span>'


def _l_ci(ci) -> str:
    return "—" if not ci else f"[{ci[0]:+.1f} ; {ci[1]:+.1f}]"


def _l_lvl(niveau: str) -> str:
    return f'<span class="badge lvl-{niveau}">{_LIB_LVL.get(niveau, niveau)}</span>'


def _l_table_bandes(stat: dict) -> str:
    rows = ""
    for b in stat["bands"]:
        if not b["n"]:
            continue
        hit = "—" if b["hit"] is None else f'{b["hit"] * 100:.0f}&nbsp;%'
        rows += (f'<tr><td><strong>{b["label"]}</strong>'
                 f'<div class="sub-lbl">{b["reco"].title()}</div></td>'
                 f'<td class="cell-num">{b["n"]}</td><td class="cell-num">{b["n_indep"]}</td>'
                 f'<td class="cell-num">{_l_pct(b["mean"])}</td>'
                 f'<td class="cell-num">{_l_pct(b["median"])}</td>'
                 f'<td class="cell-num">{hit}</td>'
                 f'<td class="cell-num">{_l_ci(b["ci95"])}</td>'
                 f'<td class="cell-num">{_l_pct(b["estimate"])}</td>'
                 f'<td>{_l_lvl(b["confidence"])}</td></tr>\n')
    return f"""
  <div class="table-wrap">
    <table>
      <thead><tr><th>Tranche de note</th><th>N</th><th>N indép.</th>
        <th>Surperf. moyenne</th><th>Médiane</th><th>% positifs</th>
        <th>IC 95 %</th><th>Espérance calibrée</th><th>Confiance</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>"""


def build_learning_html() -> str:
    if not learning:
        return ""
    c = learning["counts"]
    h = str(learning.get("horizon"))
    hs = learning.get("horizons_stats") or {}

    en_attente = c["par_horizon"].get(h, {}).get("en_attente", 0)
    cartes = "".join(
        f'<div class="mini-card"><div class="mini-val">{v}</div>'
        f'<div class="mini-lbl">{l}</div></div>'
        for v, l in ((c["snapshots"], "Notes enregistrées"),
                     (c["matured"], "Observations clôturées"),
                     (en_attente, f"En attente ({h} séances)"),
                     (learning.get("score_version", ""), "Version de la note")))

    mutu = ""
    if learning.get("mutualise"):
        mutu = (f'<div class="learn-note"><b>Apprentissage mutualisé</b> : calibré sur '
                f'{c.get("n_tickers", "?")} titre(s) suivis par l&#39;ensemble des profils '
                f'participants. Seuls le titre, la date, la note et le résultat sont '
                f'partagés — jamais l&#39;identité, les quantités ni les prix de revient.</div>')

    corps = ""
    bloc = hs.get(h)
    if not bloc:
        corps = (f'<p class="macro-note">Aucune observation clôturée à {h} séances pour '
                 f'l\'instant : les {c["snapshots"]} notes enregistrées attendent leur '
                 f'échéance. Rien n\'est conclu avant.</p>')
    else:
        kind = bloc["headline"]
        st = bloc["kinds"][kind]
        heritee = ('<div class="learn-note">Cet échantillon inclut la cohorte '
                   '<b>héritée</b> (formules antérieures, reconstituée depuis '
                   'l\'historique) : la confiance est plafonnée à «&nbsp;faible&nbsp;».</div>'
                   if st["legacy_included"] else "")
        sl = st.get("slope")
        ic = "—" if st["ic"] is None else f'{st["ic"]:+.2f}'
        ici = "—" if st["ic_indep"] is None else f'{st["ic_indep"]:+.2f}'
        lien = (f'<p class="macro-note"><strong>Lien note → surperformance :</strong> '
                f'IC de rang {ic} (échantillon indépendant : {ici})'
                + (f' · pente {sl["pente"]:+.2f} pt par point de note' if sl else "")
                + f' · {st["n_tickers"]} titre(s) sur {st["n_dates"]} séance(s).</p>')
        regions_html = ""
        if len(st.get("regions") or []) > 1:
            rrows = "".join(
                f'<tr><td>{r["region"]}</td><td class="cell-num">{r["n"]}</td>'
                f'<td class="cell-num">{r["n_indep"]}</td>'
                f'<td class="cell-num">{_l_pct(r["mean"])}</td></tr>\n'
                for r in st["regions"])
            regions_html = (f'<div class="table-wrap"><table>'
                            f'<thead><tr><th>Région</th><th>N</th><th>N indép.</th>'
                            f'<th>Surperf. moyenne</th></tr></thead>'
                            f'<tbody>{rrows}</tbody></table></div>'
                            f'<p class="sub-lbl">Ventilation par région, à titre indicatif — '
                            f'n\'entre pas dans le calcul de l\'espérance calibrée.</p>')
        corps = (f'<h3 class="macro-sub">Notes par tranche — horizon {h} séances '
                 f'· cible : {_LIB_KIND.get(kind, kind)}</h3>'
                 f'{heritee}{_l_table_bandes(st)}{lien}{regions_html}')

    # Comparaison d'horizons : « quel horizon colle le mieux à la note ? »
    lignes = ""
    for hh in learning.get("horizons", []):
        b = hs.get(str(hh))
        if not b:
            continue
        st = b["kinds"][b["headline"]]
        haut = st["bands"][-1]
        bas = [x["mean"] for x in st["bands"][:2] if x["n"]]
        ic = "—" if st["ic"] is None else f'{st["ic"]:+.2f}'
        lignes += (f'<tr><td><strong>{hh}</strong> séances</td>'
                   f'<td class="cell-num">{st["global"]["n_indep"]}</td>'
                   f'<td class="cell-num">{ic}</td>'
                   f'<td class="cell-num">{_l_pct(haut["mean"]) if haut["n"] else "—"}</td>'
                   f'<td class="cell-num">{_l_pct(sum(bas) / len(bas)) if bas else "—"}</td>'
                   f'<td class="cfg-cell">{_LIB_KIND.get(b["headline"], "")}</td></tr>\n')
    horizons_html = ""
    if lignes:
        horizons_html = f"""
  <h3 class="macro-sub">Quel horizon colle le mieux à la note&nbsp;?</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>Horizon</th><th>N indép.</th><th>IC de rang</th>
      <th>Notes ≥ 7,5</th><th>Notes &lt; 4,5</th><th>Cible</th></tr></thead>
    <tbody>{lignes}</tbody></table></div>"""

    # Fiabilité par position
    pos_html = ""
    if learning.get("positions"):
        prow = ""
        for p in learning["positions"]:
            pr = (p.get("horizons") or {}).get(h)
            if not pr:
                prow += (f'<tr><td><strong>{p["name"]}</strong></td>'
                         f'<td class="cell-num">{p["score"]}/10</td>'
                         f'<td colspan="4" class="cfg-cell">En attente d\'échéance</td></tr>\n')
                continue
            proba = "—" if pr["p_outperf"] is None else f'{pr["p_outperf"] * 100:.0f}&nbsp;%'
            att = (_l_pct(pr["estimate"]) if pr["estimate"] is not None
                   else f'<span class="sub-lbl">{pr.get("reason", "n/d")}</span>')
            ml = ""
            if pr.get("modele"):
                ml = (f'<div class="sub-lbl">Modèle validé : '
                      f'{pr["modele"]["estimate"]:+.1f}&nbsp;%</div>')
            prow += (f'<tr><td><strong>{p["name"]}</strong>'
                     f'<div class="sub-lbl">{p.get("sector") or "secteur inconnu"}</div></td>'
                     f'<td class="cell-num">{p["score"]}/10'
                     f'<div class="sub-lbl">tranche {pr["band"]}</div></td>'
                     f'<td class="cell-num">{att}{ml}</td>'
                     f'<td class="cell-num">{_l_ci(pr["ci95"])}</td>'
                     f'<td class="cell-num">{proba}</td>'
                     f'<td>{_l_lvl(pr["confidence"])}'
                     f'<div class="sub-lbl">{pr["n_indep"]} obs. indép. · '
                     f'{pr["scope"]}{" + héritée" if pr["legacy_included"] else ""}</div></td></tr>\n')
        pos_html = f"""
  <h3 class="macro-sub">Fiabilité par position — horizon {h} séances</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>Valeur</th><th>Note</th><th>Surperf. attendue</th>
      <th>IC 95 %</th><th>P(surperf.)</th><th>Confiance</th></tr></thead>
    <tbody>{prow}</tbody></table></div>"""

    modele = (bloc or {}).get("modele")
    if modele and modele.get("active"):
        modele_html = (f'<p class="learn-model"><b>Modèle : actif</b> '
                       f'(<code>{modele.get("model_id", "")}</code>, Ridge, validé hors '
                       f'échantillon). Il complète la calibration ; il ne remplace jamais la note.</p>')
    else:
        raison = (modele or {}).get("raison", "historique insuffisant")
        modele_html = (f'<p class="learn-model"><b>Modèle : non activé</b> — {raison}. '
                       f'La calibration statistique reste la seule prévision affichée.</p>')

    return f"""
<article class="card section" id="fiabilite">
  <div class="section-title"><h2>Fiabilité des notes</h2></div>
  <div class="mini-bar">{cartes}</div>
  <div class="learn-note">Cette section mesure ce que les notes ont valu <b>dans le passé</b>,
    relativement au secteur ou au marché. Elle ne modifie jamais la note et ne
    prédit rien : une espérance historique n'est pas une promesse.</div>
  {mutu}
  {corps}
  {horizons_html}
  {pos_html}
  {modele_html}
  {expl('''
  <p class="macro-note">
    Chaque note est enregistrée avec sa date, ses sous-notes et la version de la formule.
    À l'échéance (20, 60, 120 ou 252 séances de bourse), on mesure la surperformance du
    titre par rapport à son secteur (ou au marché à défaut). «&nbsp;N indép.&nbsp;» ne compte
    que des fenêtres qui ne se chevauchent pas : c'est lui qui fonde les intervalles de
    confiance et les seuils de publication. L'espérance calibrée est rapprochée de la
    moyenne globale quand l'échantillon est mince. Le modèle d'apprentissage ne s'active
    que s'il bat la statistique simple sur des périodes postérieures à son entraînement.
  </p>''')}
</article>"""


def build_watchlist_html() -> str:
    if not watchlist:
        return ""
    rows = ""
    for w in watchlist:
        # BUG CORRIGE (21/09/2026) : "actualite" vient du flux RSS (source
        # externe non maitrisee) et etait inseree telle quelle dans le HTML.
        rows += (f"<tr><td><strong>{esc(w['nom'])}</strong></td>"
                 f"<td>{esc(w['secteur']) or '—'}</td>"
                 f"<td class='cell-num'>{esc(w['cours'])}</td>"
                 f"<td>{var_span(w['variation'])}</td>"
                 f"<td>{esc(w['actualite'])}</td></tr>\n")
    return f"""
<article class="card section" id="watchlist">
  <div class="section-title"><h2>Watchlist</h2><p>Valeurs observées, non détenues</p></div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Valeur</th><th>Secteur</th><th>Cours</th><th>Variation</th><th>Actualité</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  {expl('''
  <p class="macro-note">
    Titres suivis sans être détenus : ni coût de revient, ni note, ni stop —
    seulement le cours et l'actualité. Cours et actualités proviennent
    exclusivement de Yahoo Finance (cours) et de son flux RSS (actualités),
    sans consommer le quota EODHD/TwelveData réservé au portefeuille réel.
  </p>''')}
</article>"""


def build_avertissements_html() -> str:
    """AJOUT (21/09/2026) : voir extract_avertissements() — ces mises en
    garde (donnée jugée périmée, taux de change suspect, etc.) existaient
    dans le rapport Markdown mais n'apparaissaient jusqu'ici nulle part
    dans la page HTML consultée par Gaby."""
    if not avertissements_donnees:
        return ""
    items = "".join(f"<li>{esc(a)}</li>" for a in avertissements_donnees)
    return f"""
<div class="section" id="avertissements">
  <div class="callout danger">
    <strong>Avertissements sur les données</strong>
    <ul>{items}</ul>
  </div>
</div>"""


def build_indices_html() -> str:
    if not indices and not bonds:
        return ""
    tiles = ""
    for idx in indices:
        tiles += (f'<div class="market"><div class="l">{esc(idx["name"])}</div>'
                  f'<div class="v">{esc(idx["cours"])}</div><small>{var_span(idx["variation"])}</small></div>')
    for b in bonds:
        tiles += (f'<div class="market"><div class="l">{esc(b["name"])}</div>'
                  f'<div class="v">{esc(b["niveau"])}</div><small>{var_span(b["variation"])}</small></div>')

    # La colonne "tendance sur 1 mois" n'existe que depuis la v7.4 : on ne
    # l'affiche que si au moins un taux la renseigne, pour ne pas
    # promettre une donnee absente d'un ancien rapport.
    tendance_lignes = "".join(
        f'<li>{esc(b["name"])} — {var_span(b["tendance"])} sur 1 mois</li>'
        for b in bonds if b.get("tendance") and b["tendance"] not in ("—", "--", ""))
    tendance_html = f'<ul class="macro-list">{tendance_lignes}</ul>' if tendance_lignes else ""

    return f"""
<article class="card section" id="macro">
  <div class="section-title"><h2>Contexte économique</h2><p>Clôture de la veille</p></div>
  <div class="macro-grid">{tiles}</div>
  {tendance_html}
  {expl('''
  <p class="macro-note">
    Le taux long souverain est le prix de l'argent sans risque : c'est la barre
    que toute action doit franchir. Quand il monte, le rendement exigé sur les
    actions monte avec lui et pèse sur les valorisations — d'autant plus fort
    que les bénéfices attendus sont lointains. L'écart OAT&nbsp;-&nbsp;UST
    mesure la prime que le marché demande à la France face aux États-Unis.
  </p>''') if bonds else ''}
</article>"""


def build_combined_chart_html() -> str:
    if not combined_b64:
        return ""
    return f"""
<article class="card chart-card section" id="tendances">
  <div class="section-title"><h2>Tendances — performance normalisée (base 100)</h2><p>Graphique généré, par position</p></div>
  <div class="combined-chart-wrap">
    <img src="data:image/png;base64,{combined_b64}"
         alt="Performance normalisée base 100 de toutes les positions"
         loading="lazy" class="combined-chart-img"
         width="900" height="500">
  </div>
  <p class="chart-caption">
    Chaque courbe représente la performance d'une valeur normalisée à 100 au premier jour disponible.
    La ligne pointillée à 100 est la référence (prix d'entrée).
  </p>
</article>"""


def build_positions_html() -> str:
    if not positions:
        return '<article class="card section" id="positions"><p class="macro-note">Aucune position disponible.</p></article>'

    cards = ""
    for p in positions:
        pnl_net_cls  = "cell-pos" if "+" in p["pnl_net"]  else "cell-neg"
        pnl_brut_cls = "cell-pos" if "+" in p["pnl_brut"] else "cell-neg"

        # Un indice de confiance bas signale une note etablie sur peu de
        # criteres : il doit rester visible a cote de la note, jamais separe.
        conf = p.get("confiance", "")
        conf_html = ""
        if conf:
            try:
                cls_conf = "conf-basse" if float(conf) < 60 else "conf-ok"
            except ValueError:
                cls_conf = "conf-ok"
            conf_html = f'<span class="conf-badge {cls_conf}">confiance {conf}%</span>'

        # Detail des composantes de la note
        comp_html = ""
        if p.get("composantes"):
            barres = ""
            for nom, note, poids in p["composantes"]:
                try:
                    pct = float(note) * 10
                except ValueError:
                    continue
                teinte = ("var(--danger)" if pct < 35 else
                          "var(--warn)" if pct < 60 else "var(--success)")
                barres += (
                    f'<div class="comp-row">'
                    f'<span class="comp-name">{esc(nom)}</span>'
                    f'<span class="comp-track"><span class="comp-fill" '
                    f'style="width:{pct:.0f}%;background:{teinte}"></span></span>'
                    f'<span class="comp-val">{esc(note)}</span>'
                    f'<span class="comp-w">{esc(poids)}%</span>'
                    f'</div>')
            # BUG CORRIGE (21/09/2026) : voir le commentaire dans
            # extract_positions() -- deux phrases distinctes, deux sens
            # distincts, ne plus les fusionner en une seule ligne.
            note_sans_objet = (f'<p class="comp-na">Sans objet pour ce type d\'actif : '
                               f'{esc(p["sans_objet"])} — exclu du calcul, '
                               f'sans impact sur la confiance.</p>'
                               if p.get("sans_objet") else "")
            note_manquants = (f'<p class="comp-missing">Attendu mais non obtenu : '
                              f'{esc(p["manquants"])} — poids redistribués, '
                              f'fait baisser la confiance.</p>'
                              if p.get("manquants") else "")
            fonda_line = (f'<p class="comp-fonda">{esc(p["fondamentaux"])}</p>'
                          if p.get("fondamentaux") else "")
            comp_html = f'<div class="comp-list">{barres}</div>{fonda_line}{note_sans_objet}{note_manquants}'

        consensus_html = ""
        if p.get("consensus"):
            src = f' <span class="mom-rets">({esc(p["consensus_src"])})</span>' if p.get("consensus_src") else ""
            consensus_html = (f'<div class="pos-detail-item"><span class="detail-lbl">Consensus</span>'
                              f'<span>{esc(p["consensus"])}{src}</span></div>')

        note_extra = f"""
    <div class="note-extra">
      <div class="pos-detail-item"><span class="detail-lbl">Momentum</span>
        <span>{mom_badge(p['mom_label'])}
          <span class="mom-rets">1M: {esc(p['ret_1m'])} · 3M: {esc(p['ret_3m'])} · 6M: {esc(p['ret_6m'])}</span>
        </span>
      </div>{consensus_html}
    </div>"""

        synthesis_html = ""
        synth_text = p.get("synthesis", "").strip()
        if synth_text and "Aucune actualite" not in synth_text:
            src_label = f'<span class="synth-src">{esc(p["synth_src"])}</span>' if p.get("synth_src") else ""
            synthesis_html = (f'<div class="synth-header">Actualité récente {src_label}</div>'
                              f'<p class="synth-text">{esc(synth_text)}</p>')
        else:
            synthesis_html = '<p class="synth-text sub-lbl">Aucune actualité marquante ces derniers jours.</p>'

        justif_html = (f'<p class="pos-justif"><strong>Justification —</strong> {esc(p["justification"])}</p>'
                       if p.get("justification") else "")

        ticker_court = esc(p["ticker"].split(".")[0][:4].upper()) or "?"

        cards += f"""
<article class="pos-card" id="pos-{esc(p['ticker']).replace('.','_')}">
  <details class="pos-toggle-news">
    <summary>
      <div class="pos-id"><span class="ticker-chip">{ticker_court}</span>
        <div><strong>{esc(p['name'])}</strong><small>{esc(p['ticker'])}</small></div></div>
      <div class="pos-quick">
        <span class="cell-num">{esc(p['prix'])}&nbsp;EUR {var_span(p['variation'])}</span>
        <span class="{pnl_net_cls}">{esc(p['pnl_net'])}</span>
        {rec_badge(p['rec'])}
      </div>
    </summary>
    <div class="pos-news">
      {synthesis_html}
      {justif_html}
    </div>
  </details>
  <div class="pos-body">
    <div class="pos-kpi"><div class="l">Valeur marché</div><div class="v">{esc(p['vm'])}&nbsp;EUR</div></div>
    <div class="pos-kpi"><div class="l">P&amp;L brut</div><div class="v {pnl_brut_cls}">{esc(p['pnl_brut'])}</div></div>
    <div class="pos-kpi"><div class="l">P&amp;L net</div><div class="v {pnl_net_cls}">{esc(p['pnl_net'])}</div></div>
  </div>
  <details class="pos-note">
    <summary>
      <span class="note-label">Note du titre</span>
      {score_bar(p['score'])}
      {conf_html}
    </summary>
    <div class="note-detail">
      {comp_html}
      {note_extra}
    </div>
  </details>
</article>"""
    return f"""
<article class="card section" id="positions">
  <div class="table-top">
    <div class="section-title" style="margin-bottom:0"><h2>Positions détenues</h2>
      <p>Touche une position pour son actualité, touche la note pour son détail</p></div>
    <span class="badge-count">{len(positions)} ligne(s)</span>
  </div>
  <div class="positions-grid">{cards}</div>
</article>"""


def build_closes_html() -> str:
    """Section des plus-values realisees. Masquee si aucune vente."""
    if not closes_rows:
        return ""

    lignes = ""
    for c in closes_rows:
        # Colonnes : nom, qte, achat, vente, produit, frais, +/- value, [date]
        pv   = c[6] if len(c) > 6 else "—"
        date = c[7] if len(c) > 7 else ""
        cls  = "cell-pos" if pv.startswith("+") else "cell-neg"
        lignes += (f"<tr><td><strong>{esc(c[0])}</strong>"
                   f"{f'<div class=vente-date>vendu le {esc(date)}</div>' if date else ''}</td>"
                   f"<td class='cell-num'>{c[1]}</td>"
                   f"<td class='cell-num'>{c[2]}</td>"
                   f"<td class='cell-num'>{c[3]}</td>"
                   f"<td class='cell-num'>{c[5]}</td>"
                   f"<td class='cell-num {cls}'>{pv}</td></tr>\n")

    pied = ""
    if closes_total and len(closes_total) > 6:
        tot = closes_total[6]
        cls = "cell-pos" if tot.startswith("+") else "cell-neg"
        pied = (f"<tr class='ligne-total'><td><strong>TOTAL</strong></td>"
                f"<td class='cell-num'>—</td>"
                f"<td class='cell-num'><strong>{closes_total[2]}</strong></td>"
                f"<td class='cell-num'>—</td><td class='cell-num'>—</td>"
                f"<td class='cell-num {cls}'><strong>{tot}</strong></td></tr>")

    return f"""
<article class="card section" id="realise">
  <div class="section-title"><h2>Plus-values réalisées</h2></div>
  {expl('''
  <p class="section-note">
    Positions vendues. Elles ne figurent plus dans le portefeuille et n'entrent
    pas dans la valorisation. Frais aller-retour déduits.
  </p>''')}
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Valeur</th><th>Qté</th><th>Prix d'achat</th>
            <th>Prix de vente</th><th>Frais A/R</th><th>+/- value nette</th></tr>
      </thead>
      <tbody>{lignes}{pied}</tbody>
    </table>
  </div>
</article>"""


def build_synthese_html() -> str:
    if not synthese_rows:
        return ""
    def champ(ligne: dict, *candidats, defaut="—") -> str:
        """Premiere colonne dont l'en-tete contient l'un des mots cherches."""
        for c in candidats:
            for cle, val in ligne.items():
                if c in cle:
                    return re.sub(r"[*]+", "", val).strip() or defaut
        return defaut

    rows_html = ""
    for ligne in synthese_rows:
        if not isinstance(ligne, dict) or not ligne:
            continue
        nom = re.sub(r"[*]+", "", list(ligne.values())[0]).strip()
        if not nom or nom.upper() in ("VALEUR", "COUT TOTAL", "TOTAL"):
            continue

        vm_raw    = champ(ligne, "vm", "valeur march")
        pnl_raw   = champ(ligne, "p&l net", "pnl net")
        score_raw = champ(ligne, "note", "score")
        conf_raw  = champ(ligne, "conf", defaut="")
        rec_raw   = champ(ligne, "recomm")

        score_cell = (f"<td>{score_bar(score_raw)}</td>" if "/" in score_raw
                      else f"<td class='cell-num'>{score_raw}</td>")
        conf_cell  = f"<td class='cell-num'>{conf_raw or '—'}</td>"

        rows_html += (f"<tr><td><strong>{esc(nom)}</strong></td>"
                      f"<td class='cell-num'>{esc(vm_raw)}</td>"
                      f"{pnl_cell(pnl_raw)}{score_cell}{conf_cell}"
                      f"<td>{rec_badge(rec_raw)}</td></tr>\n")

    return f"""
<article class="card section" id="synthese">
  <div class="section-title"><h2>Synthèse &amp; recommandations</h2></div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Valeur</th><th>Valeur Marché</th>
          <th>P&amp;L Net</th><th>Note</th><th>Confiance</th><th>Recommandation</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</article>"""


def build_archive_html() -> str:
    return """
<article class="card section" id="historique">
  <div class="section-title"><h2>Historique des rapports</h2></div>
  <button class="archive-toggle" onclick="toggleArchive()" id="archive-btn">Afficher les 30 derniers rapports</button>
  <div id="archive-panel">
    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>P&amp;L Net</th><th>VM</th><th>Positions</th></tr></thead>
        <tbody id="archive-tbody">
          <tr><td colspan="4" style="text-align:center;color:var(--muted)">Chargement…</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</article>"""


def build_explications_html() -> str:
    """Page statique (n'affiche aucune donnee du jour) : un glossaire des
    termes utilises ailleurs dans le rapport. AJOUT (26/09/2026)."""
    return """
<div class="page-head" id="guide">
  <div>
    <div class="eyebrow">Lire le rapport</div>
    <h1>Ce que chaque section veut dire</h1>
    <p>Le même rapport, expliqué terme par terme — à consulter chaque fois qu'un mot n'est pas clair.</p>
  </div>
</div>

<div class="expl-grid">

  <article class="expl-item" id="expl-reco">
    <h3>Les recommandations</h3>
    <p>Chaque position reçoit un avis, du plus favorable au plus défavorable :</p>
    <div class="badges">
      <span class="badge buy-strong">RENFORCER</span>
      <span class="badge buy-mod">CONSERVER</span>
      <span class="badge hold">SURVEILLER</span>
      <span class="badge avoid">ALLÉGER</span>
      <span class="badge sell">SORTIR</span>
      <span class="badge unknown">À EXAMINER</span>
    </div>
    <p>« À examiner » (ou « données insuffisantes ») signifie que le système ne peut pas conclure faute d'informations — ce n'est ni bon ni mauvais signe, juste une note à prendre avec prudence.</p>
  </article>

  <article class="expl-item" id="expl-note">
    <h3>La note et sa confiance</h3>
    <p>Chaque titre reçoit une note sur 10, construite à partir de plusieurs composantes pondérées (valorisation, momentum, qualité du bilan, sentiment, contexte macro selon le type d'actif). La confiance indique la part de ces critères réellement calculés : un critère non disponible fait baisser la confiance, pas la note elle-même. « Sans objet » (un critère qui n'existe pas pour ce type d'actif) est normal et n'y touche pas.</p>
  </article>

  <article class="expl-item" id="expl-momentum">
    <h3>Le momentum</h3>
    <p>Trois rendements glissants (1 mois, 3 mois, 6 mois) résumés par une étiquette : <span class="badge buy-strong">↗ HAUSSIER</span>, <span class="badge sell">↘ BAISSIER</span>, ou neutre si aucune tendance nette ne se dégage.</p>
  </article>

  <article class="expl-item" id="expl-stops">
    <h3>Les types de stop</h3>
    <p><strong>Suiveur</strong> — monte avec le cours, ne redescend jamais. <strong>Pourcentage</strong> — niveau fixe sous le prix d'achat. <strong>Absolu</strong> — un montant précis choisi à l'avance. <strong>VQ</strong> (volatility quantile) — s'adapte à la volatilité propre du titre. Un stop est déclaré franchi à la clôture, jamais en cours de séance.</p>
  </article>

  <article class="expl-item" id="expl-dimensionnement">
    <h3>Le dimensionnement</h3>
    <p>La taille suggérée d'une ligne = (capital × risque accepté par idée) ÷ distance jusqu'au stop. Deux titres de volatilité différente reçoivent ainsi le même risque en euros, pas le même montant investi. L'« écart » compare ce qui est détenu à ce que ce calcul recommande — un signal à interpréter, jamais un ordre automatique.</p>
  </article>

  <article class="expl-item" id="expl-correlation">
    <h3>La corrélation</h3>
    <p>Mesure si les lignes du portefeuille bougent ensemble ou indépendamment. Un indice proche de 0&nbsp;% signifie une vraie diversification ; proche de 100&nbsp;%, le portefeuille réagit comme un seul actif. Les « groupes » regroupent les lignes les plus corrélées entre elles pour repérer une concentration cachée derrière plusieurs tickers différents.</p>
  </article>

  <article class="expl-item" id="expl-macro">
    <h3>Le contexte économique</h3>
    <p>Les grands indices et les taux souverains à 10 ans (UST pour les États-Unis, OAT pour la France) donnent le climat du jour. Le taux long est le prix de l'argent sans risque : quand il monte, le rendement exigé sur les actions monte avec lui et pèse sur les valorisations.</p>
  </article>

  <article class="expl-item" id="expl-fiabilite">
    <h3>La fiabilité des notes</h3>
    <p>Un suivi indépendant vérifie, avec le recul, si les notes élevées ont vraiment précédé une surperformance. Le niveau de confiance de cette calibration (élevée, moyenne, faible, insuffisante) dépend du nombre d'observations closes disponibles — plus il y en a, plus le chiffre est fiable. Rien n'est conclu tant que l'échantillon est trop mince.</p>
  </article>

  <article class="expl-item" id="expl-avertissements">
    <h3>Les avertissements</h3>
    <p>Bandeau en haut du rapport : un événement demande une décision avant l'ouverture des marchés (stop franchi, alerte de concentration, donnée jugée périmée). Il disparaît dès que la situation qui l'a déclenché n'est plus d'actualité.</p>
  </article>

  <article class="expl-item" id="expl-historique">
    <h3>L'historique des rapports</h3>
    <p>Les 30 derniers rapports quotidiens, consultables en un clic en bas de la page Portefeuille, pour suivre l'évolution de la valeur et du nombre de positions dans le temps. Le graphique de trajectoire, lui, utilise tout l'historique conservé — pas seulement les 30 derniers jours.</p>
  </article>

</div>"""


# ══════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════
CSS = """
:root, [data-theme="dark"] {
  --bg:#0B0E0F; --surface:#141B1D; --surface2:#1B2426; --surface3:#212B2E;
  --border:rgba(237,241,240,.10); --border-strong:rgba(237,241,240,.18);
  --text:#EDF1F0; --muted:#93A0A2; --faint:#3A4547;
  --accent:#49D3C4; --accent-h:#7BE6DA; --on-accent:#07211C; --halo:rgba(73,211,196,.18);
  --success:#58D68D; --danger:#EF6F5B; --warn:#F0B95C; --info:#63B3E8;
  --radius:14px; --shadow:none;
  --font:'Bricolage Grotesque',system-ui,sans-serif; --mono:'DM Mono',ui-monospace,monospace;
  color-scheme: dark;
}
[data-theme="light"] {
  --bg:#F4F7F7; --surface:#FFFFFF; --surface2:#EDF2F1; --surface3:#E2E9E8;
  --border:rgba(15,30,28,.10); --border-strong:rgba(15,30,28,.18);
  --text:#0F1E1C; --muted:#5B6D6A; --faint:#9AACA9;
  --accent:#1B8F82; --accent-h:#177266; --on-accent:#FFFFFF; --halo:rgba(27,143,130,.14);
  --success:#1F9D63; --danger:#C6493B; --warn:#B9791F; --info:#2A6FA8;
  --shadow:0 2px 12px rgba(15,30,28,.06);
  color-scheme: light;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: var(--font); background: var(--bg); color: var(--text);
  line-height: 1.6; font-size: 15px; min-height: 100dvh; -webkit-font-smoothing: antialiased;
}
button { font: inherit; color: inherit; cursor: pointer; background: none; border: 0; }
a { color: inherit; text-decoration: none; }
.num, .mono, code { font-family: var(--mono); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; } }

.shell { max-width: 1180px; margin: 0 auto; padding: 0 20px 90px; }

/* ── entete / onglets ─────────────────────────────────────────── */
.topbar { display:flex; align-items:center; gap:18px; padding:22px 0 10px; flex-wrap:wrap;
  position: sticky; top:0; z-index:50; background:var(--bg); }
.brand strong { font-weight:700; font-size:16px; letter-spacing:-.01em; }
.tabs { display:flex; gap:4px; background:var(--surface); border:1px solid var(--border); border-radius:999px; padding:4px; }
.tab { padding:9px 18px; border-radius:999px; font-weight:600; font-size:13.5px; color:var(--muted); transition:background .2s ease,color .2s ease; }
.tab[aria-selected="true"] { background:var(--accent); color:var(--on-accent); }
.tab:hover:not([aria-selected="true"]) { color:var(--text); background:var(--surface2); }
.topbar-actions { display:flex; align-items:center; gap:14px; margin-left:auto; }
.text-btn { color:var(--muted); font-size:12.5px; font-weight:600; }
.text-btn:hover { color:var(--accent); }
.hdr-alert { color:var(--danger); font-size:12.5px; font-weight:700; background:rgba(239,111,91,.12);
  padding:5px 11px; border-radius:999px; }
.hdr-alert:hover { background:rgba(239,111,91,.2); }
.fresh { display:flex; align-items:center; gap:7px; color:var(--muted); font-size:12.5px; font-family:var(--mono);
  width:100%; padding:6px 0 16px; }
.dot { width:6px; height:6px; border-radius:50%; background:var(--success); box-shadow:0 0 8px var(--success); }

.subnav { display:flex; gap:2px; overflow-x:auto; padding:4px 0 18px; border-bottom:1px solid var(--border);
  margin-bottom:26px; scrollbar-width:none; }
.subnav::-webkit-scrollbar { display:none; }
.subnav a { white-space:nowrap; color:var(--muted); font-size:13px; padding:7px 12px; border-radius:8px; font-weight:500; }
.subnav a:hover { color:var(--text); background:var(--surface); }

.view { display:none; }
.view.active { display:block; animation: enter .35s cubic-bezier(.19,1,.22,1) both; }
@keyframes enter { from{opacity:0;translate:0 8px} to{opacity:1;translate:0 0} }

.page-head { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin-bottom:22px; flex-wrap:wrap; }
.eyebrow { font-size:11.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); font-weight:700; font-family:var(--mono); }
.page-head h1 { font-size:clamp(1.5rem,2.6vw,1.9rem); font-weight:700; letter-spacing:-.03em; margin:5px 0 4px; }
.page-head p { color:var(--muted); max-width:56ch; font-size:14px; }

/* ── cartes ────────────────────────────────────────────────────── */
.card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:20px; box-shadow:var(--shadow); }
.section { margin-bottom:18px; scroll-margin-top:96px; }
.section-title { display:flex; align-items:baseline; justify-content:space-between; gap:14px; margin-bottom:16px; flex-wrap:wrap; }
.section-title h2 { font-size:17px; font-weight:700; letter-spacing:-.02em; }
.section-title p { color:var(--muted); font-size:12.5px; }
.badge-count { background:var(--surface2); color:var(--muted); font-size:11.5px; font-family:var(--mono); padding:4px 9px; border-radius:999px; }

/* ── kpis ──────────────────────────────────────────────────────── */
.kpis { display:grid; grid-template-columns:1.2fr repeat(4,1fr); gap:10px; margin-bottom:14px; }
.kpi { min-height:96px; display:flex; flex-direction:column; justify-content:space-between; }
.kpi.featured { background:linear-gradient(155deg,var(--surface3),var(--surface)); border-color:var(--border-strong); position:relative; overflow:hidden; }
.kpi.featured::after { content:""; position:absolute; width:150px; height:150px; right:-56px; top:-70px; border-radius:50%;
  background:radial-gradient(closest-side,var(--halo),transparent); }
.kpi .label { color:var(--muted); font-size:12px; }
.kpi .value { font-family:var(--mono); font-size:clamp(1.05rem,1.7vw,1.4rem); letter-spacing:-.01em; font-variant-numeric:tabular-nums; margin-top:6px; }
.kpi .delta { font-size:12px; color:var(--muted); font-family:var(--mono); margin-top:4px; }
.cell-pos { color:var(--success); font-family:var(--mono); }
.cell-neg { color:var(--danger); font-family:var(--mono); }
.cell-num { font-family:var(--mono); white-space:nowrap; }

/* ── callouts ──────────────────────────────────────────────────── */
.callout { border-radius:10px; padding:13px 15px; font-size:13px; border:1px solid var(--border); background:var(--surface2); color:var(--muted); }
.callout.warn { background:rgba(240,185,92,.08); border-color:rgba(240,185,92,.28); color:var(--warn); }
.callout.danger { background:rgba(239,111,91,.08); border-color:rgba(239,111,91,.3); color:var(--danger); }
.callout strong { display:block; color:inherit; margin-bottom:2px; font-size:13px; }
.callout ul { margin:6px 0 0 18px; }
.callout li { color:var(--text); margin:2px 0; }

/* ── layouts 2 colonnes ────────────────────────────────────────── */
.layout { display:grid; grid-template-columns:1.6fr 1fr; gap:14px; }
.analysis-grid { display:grid; grid-template-columns:1.55fr .95fr; gap:14px; align-items:start; }
@media (max-width:900px) { .layout, .analysis-grid { grid-template-columns:1fr; } }
@media (max-width:880px) { .kpis { grid-template-columns:repeat(2,1fr); } .kpi.featured { grid-column:1/-1; } }
.stack { display:grid; gap:14px; }
.sticky { position:sticky; top:96px; }

/* ── graphiques ────────────────────────────────────────────────── */
.chart-wrap { position:relative; }
.chart-wrap svg { width:100%; height:auto; display:block; }
.chart-caption { color:var(--muted); font-size:12px; margin-top:10px; }
.chart-empty { color:var(--faint); font-size:13px; padding:40px 0; text-align:center; }
.combined-chart-wrap { background:var(--surface2); border:1px solid var(--border); border-radius:10px; overflow:hidden; }
.combined-chart-img { width:100%; display:block; max-height:520px; object-fit:contain; }

/* ── répartition / concentration ──────────────────────────────── */
.alloc-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }
.alloc-card { background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:14px 16px; }
.alloc-title { font-size:12.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; font-family:var(--mono); margin-bottom:10px; }
.alloc-row { margin-bottom:11px; }
.alloc-row:last-child { margin-bottom:0; }
.alloc-head { display:flex; justify-content:space-between; gap:10px; font-size:13px; margin-bottom:5px; }
.alloc-lbl { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.alloc-chiffres { display:flex; align-items:baseline; gap:8px; white-space:nowrap; }
.alloc-part { font-family:var(--mono); font-weight:600; }
.alloc-val { font-family:var(--mono); font-size:11px; color:var(--muted); }
.alloc-rail { height:5px; background:var(--surface3); border-radius:99px; overflow:hidden; }
.alloc-fill { display:block; height:100%; background:var(--accent); border-radius:99px; }
@media (max-width:560px) { .alloc-val { display:none; } }

/* ── positions ─────────────────────────────────────────────────── */
.positions-grid { display:grid; gap:10px; }
.pos-card { border:1px solid var(--border); border-radius:12px; background:var(--surface2); overflow:hidden; transition:border-color .2s ease; }
.pos-card:hover { border-color:var(--border-strong); }
.pos-toggle-news > summary { list-style:none; cursor:pointer; display:flex; align-items:center; gap:14px; padding:14px 16px; flex-wrap:wrap; }
.pos-toggle-news > summary::-webkit-details-marker { display:none; }
.pos-toggle-news > summary::after { content:"actualité"; margin-left:auto; font-size:11.5px; color:var(--faint); font-family:var(--mono); white-space:nowrap; transition:color .2s ease; }
.pos-toggle-news[open] > summary::after { color:var(--accent); }
.pos-toggle-news[open] > summary { border-bottom:1px solid var(--border); }
.pos-id { display:flex; align-items:center; gap:10px; min-width:180px; }
.ticker-chip { width:38px; height:38px; border-radius:9px; background:var(--surface3); display:grid; place-items:center;
  font-family:var(--mono); font-weight:600; font-size:10.5px; color:var(--accent); flex-shrink:0; }
.pos-id strong { display:block; font-size:14px; }
.pos-id small { color:var(--faint); font-size:11.5px; }
.pos-quick { display:flex; align-items:center; gap:16px; flex-wrap:wrap; font-size:13px; }
.pos-news { padding:14px 16px; font-size:13px; }
.pos-body { display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding:0 16px 14px; }
.pos-kpi { min-width:78px; }
.pos-kpi .l { font-size:10.5px; color:var(--faint); text-transform:uppercase; letter-spacing:.05em; font-family:var(--mono); }
.pos-kpi .v { font-family:var(--mono); font-size:13px; margin-top:2px; }
.pos-note { border-top:1px solid var(--border); }
.pos-note > summary { list-style:none; cursor:pointer; display:flex; align-items:center; gap:12px; padding:12px 16px; flex-wrap:wrap; }
.pos-note > summary::-webkit-details-marker { display:none; }
.pos-note > summary::after { content:"détail"; margin-left:auto; font-size:11.5px; color:var(--faint); font-family:var(--mono); }
.pos-note[open] > summary::after { color:var(--accent); }
.note-label { font-size:11.5px; color:var(--muted); font-family:var(--mono); white-space:nowrap; }
.note-detail { padding:4px 16px 16px; }
.note-extra { margin-top:10px; padding-top:10px; border-top:1px solid var(--border); display:flex; flex-wrap:wrap; gap:10px 22px; font-size:12.5px; }

/* ── note : composantes, score, confiance ─────────────────────── */
.score-wrap { display:flex; align-items:center; gap:9px; flex:1; min-width:140px; }
.score-num { font-family:var(--mono); font-size:13.5px; min-width:34px; }
.score-bar { flex:1; height:6px; background:var(--surface3); border-radius:99px; overflow:hidden; max-width:220px; }
.score-fill { height:100%; border-radius:99px; transition:width 1s cubic-bezier(.16,1,.3,1); }
.bar-green { background:var(--success); } .bar-yellow { background:var(--warn); } .bar-red { background:var(--danger); }
.conf-badge { font-size:11px; font-family:var(--mono); padding:3px 8px; border-radius:999px; background:var(--surface3); color:var(--muted); white-space:nowrap; }
.conf-ok { background:var(--surface3); color:var(--muted); }
.conf-basse { color:var(--warn); background:rgba(240,185,92,.13); }
.comp-list { display:flex; flex-direction:column; gap:5px; }
.comp-row { display:grid; grid-template-columns:9rem 1fr 2.2rem 2.4rem; align-items:center; gap:9px; font-size:12px; }
.comp-name { color:var(--muted); }
.comp-track { height:5px; background:var(--surface3); border-radius:99px; overflow:hidden; }
.comp-fill { display:block; height:100%; border-radius:99px; }
.comp-val { font-family:var(--mono); text-align:right; }
.comp-w { font-family:var(--mono); color:var(--faint); text-align:right; font-size:11px; }
.comp-fonda { margin:10px 0 0; padding-top:10px; border-top:1px solid var(--border); font-family:var(--mono); font-size:11.5px; color:var(--muted); }
.comp-missing { margin:8px 0 0; font-size:11.5px; color:var(--warn); }
.comp-na { margin:8px 0 0; font-size:11.5px; color:var(--muted); }
@media (max-width:560px) { .comp-row { grid-template-columns:6.5rem 1fr 2rem 2.2rem; font-size:11px; } }
.pos-detail-item { display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }
.detail-lbl { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; min-width:72px; flex-shrink:0; font-family:var(--mono); }
.mom-rets { font-size:12px; color:var(--muted); font-family:var(--mono); margin-left:4px; }
.synth-header { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:var(--accent); margin-bottom:6px; display:flex; align-items:center; gap:8px; }
.synth-src { font-size:11px; font-weight:400; color:var(--faint); text-transform:none; letter-spacing:0; background:var(--surface3); border-radius:4px; padding:1px 6px; }
.synth-text { font-size:13px; color:var(--text); line-height:1.6; }
.synth-text.sub-lbl { color:var(--faint); font-style:italic; }
.pos-justif { margin:10px 0 0; padding-top:10px; border-top:1px solid var(--border); font-size:12.5px; color:var(--muted); line-height:1.6; }
.pos-justif strong { color:var(--text); }

/* ── badges recommandation / statut ───────────────────────────── */
.badge { display:inline-flex; align-items:center; gap:6px; font-size:11.5px; font-weight:700; padding:5px 10px 5px 8px; border-radius:999px; white-space:nowrap; }
.badge::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; flex-shrink:0; }
.buy-strong { background:rgba(88,214,141,.13); color:var(--success); }
.buy-mod { background:rgba(99,179,232,.13); color:var(--info); }
.hold { background:rgba(240,185,92,.13); color:var(--warn); }
.avoid { background:rgba(232,147,90,.13); color:#E8935B; }
.sell { background:rgba(239,111,91,.13); color:var(--danger); }
.unknown { background:var(--surface3); color:var(--muted); }
.up { color:var(--success); font-weight:700; } .dn { color:var(--danger); font-weight:700; }

/* ── tables ────────────────────────────────────────────────────── */
.table-top { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; flex-wrap:wrap; }
.table-wrap { overflow-x:auto; border-radius:10px; border:1px solid var(--border); }
table { width:100%; border-collapse:collapse; font-size:13px; min-width:520px; }
th { text-align:left; font-size:11px; color:var(--faint); text-transform:uppercase; letter-spacing:.06em; font-weight:600;
  padding:10px 14px; background:var(--surface2); border-bottom:1px solid var(--border); font-family:var(--mono); white-space:nowrap; }
td { padding:11px 14px; border-bottom:1px solid var(--border); vertical-align:middle; }
tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:var(--surface2); }
.sub-lbl { display:block; color:var(--faint); font-size:11px; font-weight:400; margin-top:2px; }
.cfg-cell { color:var(--muted); font-size:12px; }
.type-tag { display:inline-block; padding:3px 8px; border-radius:999px; background:var(--surface3); border:1px solid var(--border); color:var(--muted); font-size:11px; white-space:nowrap; }
.vente-date { font-size:11px; color:var(--muted); margin-top:2px; font-weight:400; }
.ligne-total td { border-top:2px solid var(--border-strong); }
.section-note { margin:-4px 0 12px; font-size:12.5px; color:var(--muted); line-height:1.6; }
.hors-note { font-size:10.5px; color:var(--muted); border:1px solid var(--border); border-radius:999px; padding:0 5px; margin-left:3px; white-space:nowrap; }

/* ── watchlist ─────────────────────────────────────────────────── */
.watch-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }
@media (max-width:720px) { .watch-grid { grid-template-columns:1fr; } }

/* ── historique ────────────────────────────────────────────────── */
.archive-toggle { width:100%; text-align:left; padding:11px 14px; border:1px dashed var(--border-strong); border-radius:10px;
  color:var(--accent); font-size:13px; font-weight:600; background:var(--surface2); margin-bottom:12px; }
.archive-toggle:hover { background:var(--surface3); }
#archive-panel { display:none; }
#archive-panel.open { display:block; }

/* ── stops / technique ────────────────────────────────────────── */
.mini-bar { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:16px; }
.mini-card { background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:14px; }
.mini-card.alert { border-color:rgba(239,111,91,.35); background:rgba(239,111,91,.07); }
.mini-val { font-family:var(--mono); font-size:19px; font-weight:600; }
.mini-card.alert .mini-val { color:var(--danger); }
.mini-lbl { color:var(--muted); font-size:11.5px; margin-top:3px; text-transform:uppercase; letter-spacing:.04em; }
.market { background:var(--surface2); border:1px solid var(--border); border-radius:10px; padding:14px; }
.market .l { color:var(--muted); font-size:12px; }
.market .v { font-family:var(--mono); font-size:18px; margin:6px 0 3px; }
.macro-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }
@media (max-width:560px) { .macro-grid { grid-template-columns:1fr; } }
.macro-list { list-style:none; margin-top:10px; font-size:12.5px; color:var(--muted); display:grid; gap:4px; }
.macro-sub { font-size:13px; font-weight:700; letter-spacing:-.005em; margin:20px 0 10px; }
.macro-note { font-size:12.5px; color:var(--muted); line-height:1.6; margin-top:8px; }

.dist-wrap { display:block; min-width:120px; }
.dist-rail { display:block; height:5px; background:var(--surface3); border-radius:999px; overflow:hidden; }
.dist-fill { display:block; height:100%; border-radius:999px; }
.dist-ok { background:var(--success); } .dist-tight { background:var(--warn); } .dist-neg { background:var(--danger); }
.dist-txt { display:block; color:var(--muted); font-size:11px; margin-top:3px; }

.stop-ok { background:rgba(88,214,141,.13); color:var(--success); }
.stop-ko { background:rgba(239,111,91,.13); color:var(--danger); }
.stop-none { background:var(--surface3); color:var(--muted); }
.stop-warn { background:rgba(240,185,92,.13); color:var(--warn); }

.corr-row { display:flex; align-items:center; gap:22px; flex-wrap:wrap; margin-bottom:16px; }
.corr-txt { color:var(--muted); font-size:13px; max-width:44ch; }

/* ── jauges rondes (fiabilité / corrélation) ──────────────────── */
.ring-card { text-align:center; }
.ring { width:112px; height:112px; border-radius:50%; display:grid; place-items:center; position:relative; flex-shrink:0; }
.ring::before { content:""; position:absolute; inset:11px; border-radius:50%; background:var(--surface); }
.ring div { position:relative; display:flex; flex-direction:column; align-items:center; }
.ring b { font-family:var(--mono); font-size:21px; letter-spacing:-.01em; }
.ring small { font-size:10px; color:var(--muted); margin-top:2px; font-family:var(--mono); text-transform:uppercase; letter-spacing:.04em; }
.ring-card .ring { margin:4px auto 16px; }
.ring-card h3 { font-size:15px; margin-bottom:7px; }
.ring-card p { color:var(--muted); font-size:12.5px; line-height:1.6; }
.ring-link { display:inline-block; margin-top:14px; color:var(--accent); font-size:12.5px; font-weight:600; }
.ring-link:hover { color:var(--accent-h); }

/* ── fiabilité (moteur d'apprentissage) ───────────────────────── */
.lvl-elevee, .lvl-moyenne { background:rgba(88,214,141,.13); color:var(--success); }
.lvl-faible { background:rgba(240,185,92,.13); color:var(--warn); }
.lvl-insuffisante { background:var(--surface3); color:var(--muted); }
.learn-note { border-left:3px solid var(--border-strong); padding:8px 12px; margin:0 0 14px; color:var(--muted); font-size:12px;
  background:var(--surface2); border-radius:0 8px 8px 0; }
.learn-model { margin:12px 0 0; font-size:12px; color:var(--muted); }
.learn-model b { color:var(--text); }

/* ── explications ──────────────────────────────────────────────── */
.expl-grid { display:grid; gap:12px; }
.expl-item { border:1px solid var(--border); border-radius:12px; padding:16px; background:var(--surface2); }
.expl-item h3 { font-size:14.5px; margin-bottom:7px; }
.expl-item p { color:var(--muted); font-size:13px; line-height:1.65; }
.expl-item .badges { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }

/* ── details generiques ("voir l'explication") ────────────────── */
.expl-toggle { margin:12px 0 0; }
.expl-toggle summary { cursor:pointer; font-size:12.5px; color:var(--accent); font-weight:600; list-style:none; }
.expl-toggle summary::-webkit-details-marker { display:none; }
.expl-toggle[open] summary { margin-bottom:8px; color:var(--muted); }
.expl-toggle .macro-note, .expl-toggle .section-note { margin-top:0; }

.footer-note { color:var(--faint); font-size:11.5px; text-align:center; margin:36px 0 0; }

@media print {
  .topbar, .subnav, .archive-toggle, #archive-panel { display:none !important; }
  .view { display:block !important; margin-bottom:40px; }
  body { background:#fff; color:#000; }
  .card { break-inside:avoid; border:1px solid #ccc; box-shadow:none; }
}
@media (max-width:640px) {
  .shell { padding:0 14px 90px; }
  .topbar { padding:16px 0 8px; gap:10px; }
  .tabs { width:100%; }
  .tab { flex:1; text-align:center; padding:9px 6px; }
  .page-head { flex-direction:column; align-items:flex-start; }
}
"""

# ══════════════════════════════════════════════════════
# JS
# ══════════════════════════════════════════════════════
JS = r"""
(function(){
  var root = document.documentElement;
  var btn  = document.querySelector('[data-theme-toggle]');
  function sg(k){try{return localStorage.getItem(k);}catch(e){return null;}}
  function ss(k,v){try{localStorage.setItem(k,v);}catch(e){}}
  // Theme sombre par defaut, comme le reste du site. Le bouton reste
  // disponible et le choix explicite de l'utilisateur est memorise.
  var theme = sg('theme') || 'dark';
  root.setAttribute('data-theme', theme);
  function label(){ return theme === 'dark' ? 'Mode clair' : 'Mode sombre'; }
  if (btn) btn.textContent = label();
  if (btn) btn.addEventListener('click', function(){
    theme = theme === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', theme);
    ss('theme', theme);
    btn.textContent = label();
  });
})();

function animateCounter(el) {
  var raw = el.getAttribute('data-val');
  if (!raw) return;
  var num = parseFloat(raw.replace(',','.').replace(/\s/g,''));
  if (isNaN(num)) return;
  var suffix   = el.getAttribute('data-suffix') || '';
  var prefix   = el.getAttribute('data-prefix') || '';
  var decimals = (raw.includes('.') || raw.includes(',')) ? 2 : 0;
  var duration = 1200;
  var startTime = null;
  function step(ts) {
    if (!startTime) startTime = ts;
    var p    = Math.min((ts - startTime) / duration, 1);
    var ease = 1 - Math.pow(1 - p, 4);
    var cur  = num * ease;
    var disp = Math.abs(cur).toFixed(decimals).replace('.',',');
    disp = disp.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    el.textContent = prefix + (num < 0 ? '-' : '') + disp + suffix;
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
document.querySelectorAll('[data-counter]').forEach(function(el){
  var obs = new IntersectionObserver(function(entries, o){
    if (entries[0].isIntersecting) { animateCounter(el); o.disconnect(); }
  }, {threshold: 0.3});
  obs.observe(el);
});

document.querySelectorAll('.score-fill').forEach(function(bar){
  var w = bar.style.width;
  bar.style.width = '0%';
  setTimeout(function(){ bar.style.width = w; }, 400);
});

/* ── Onglets et sous-navigation ──────────────────────────────── */
var NAV_CONFIG = __NAV_CONFIG__;
var subnav = document.getElementById('subnav');
function go(id, push) {
  document.querySelectorAll('.view').forEach(function(v){ v.classList.toggle('active', v.id === 'view-' + id); });
  document.querySelectorAll('.tab').forEach(function(b){
    var on = b.dataset.view === id;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  var items = NAV_CONFIG[id] || [];
  if (subnav) subnav.innerHTML = items.map(function(x){ return '<a href="' + x[0] + '">' + x[1] + '</a>'; }).join('');
  if (push !== false) { try { history.replaceState(null, '', '#' + id); } catch(e){} }
}
document.querySelectorAll('.tab').forEach(function(b){
  b.addEventListener('click', function(){ go(b.dataset.view); window.scrollTo({top:0, behavior:'smooth'}); });
});
document.querySelectorAll('[data-goto]').forEach(function(b){
  b.addEventListener('click', function(e){
    e.preventDefault();
    go(b.dataset.goto);
    var anchor = b.dataset.anchor;
    if (anchor) {
      setTimeout(function(){
        var el = document.getElementById(anchor);
        if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
      }, 60);
    }
  });
});
var _start = 'portefeuille';
try { var h0 = location.hash.replace('#',''); if (NAV_CONFIG[h0]) _start = h0; } catch(e){}
go(_start, false);

/* ── Archive (fetch partage entre l'historique et la trajectoire) ── */
var _archiveData = null;
function fetchArchive() {
  if (_archiveData) return Promise.resolve(_archiveData);
  return fetch('./archive.json').then(function(r){ return r.json(); }).then(function(data){ _archiveData = data; return data; });
}

function toggleArchive() {
  var panel = document.getElementById('archive-panel');
  var btnA  = document.getElementById('archive-btn');
  var open  = panel.classList.toggle('open');
  btnA.textContent = open ? "Masquer l'historique" : 'Afficher les 30 derniers rapports';
  if (open) loadArchive();
}
var _archiveLoaded = false;
function loadArchive() {
  if (_archiveLoaded) return;
  _archiveLoaded = true;
  fetchArchive().then(function(data){
    var tbody = document.getElementById('archive-tbody');
    var recent = data.slice(0, 30);
    tbody.innerHTML = recent.map(function(e, i){
      var cls = i === 0 ? 'style="background:var(--surface3)"' : '';
      var pnl = e.pnl || '—';
      var pnlCls = pnl.indexOf('+') !== -1 ? 'cell-pos' : pnl.indexOf('-') !== -1 ? 'cell-neg' : '';
      return '<tr ' + cls + '>'
        + '<td class="cell-num" style="white-space:nowrap">' + e.date + '</td>'
        + '<td class="' + pnlCls + '">' + pnl + '</td>'
        + '<td class="cell-num">' + (e.vm ? e.vm + ' €' : '—') + '</td>'
        + '<td class="cell-num">' + (e.nb_pos || '—') + '</td>'
        + '</tr>';
    }).join('');
  }).catch(function(){
    document.getElementById('archive-tbody').innerHTML =
      '<tr><td colspan="4" style="text-align:center;color:var(--muted)">Historique non disponible.</td></tr>';
  });
}

/* ── Trajectoire du portefeuille (page Portefeuille) ──────────── */
function parseFrDate(s) {
  var m = /(\d{2})\/(\d{2})\/(\d{4})\s+(\d{2}):(\d{2})/.exec(s || '');
  if (!m) return null;
  return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]);
}
function parseNum(s) {
  if (s === undefined || s === null) return NaN;
  return parseFloat(String(s).replace(/\s/g, '').replace(',', '.'));
}
function drawTrajectoire() {
  var svg = document.getElementById('trajectoire-svg');
  if (!svg) return;
  var caption = document.getElementById('trajectoire-caption');
  var empty   = document.getElementById('trajectoire-empty');
  fetchArchive().then(function(data){
    var pts = data.map(function(e){ return { d: parseFrDate(e.date), v: parseNum(e.vm) }; })
                   .filter(function(p){ return p.d && !isNaN(p.v); });
    pts.sort(function(a, b){ return a.d - b.d; });
    if (pts.length < 2) {
      svg.style.display = 'none';
      if (empty) empty.style.display = 'block';
      if (caption) caption.textContent = "L'historique s'allonge chaque jour : la courbe apparaîtra avec quelques rapports de plus.";
      return;
    }
    var W = 720, H = 250, padL = 8, padR = 8, padT = 14, padB = 14;
    var vals = pts.map(function(p){ return p.v; });
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    if (min === max) { min -= 1; max += 1; }
    var n = pts.length;
    function x(i){ return padL + (W - padL - padR) * (i / (n - 1)); }
    function y(v){ return padT + (H - padT - padB) * (1 - (v - min) / (max - min)); }
    var line = pts.map(function(p, i){ return (i === 0 ? 'M' : 'L') + x(i).toFixed(1) + ' ' + y(p.v).toFixed(1); }).join(' ');
    var area = 'M' + x(0).toFixed(1) + ' ' + H + ' L' + line.slice(1) + ' L' + x(n - 1).toFixed(1) + ' ' + H + ' Z';
    svg.innerHTML =
      '<defs><linearGradient id="fillTraj" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#49D3C4" stop-opacity=".28"/>' +
      '<stop offset="1" stop-color="#49D3C4" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="' + area + '" fill="url(#fillTraj)"/>' +
      '<path d="' + line + '" fill="none" stroke="#49D3C4" stroke-width="3" vector-effect="non-scaling-stroke"/>';
    if (caption) {
      var premier = pts[0].d.toLocaleDateString('fr-FR');
      caption.textContent = 'Valeur nette du portefeuille depuis la première clôture suivie disponible, le ' + premier + '.';
    }
  }).catch(function(){
    if (caption) caption.textContent = 'Historique indisponible pour le moment.';
  });
}
drawTrajectoire();
"""

# ══════════════════════════════════════════════════════
# ASSEMBLAGE HTML FINAL
# ══════════════════════════════════════════════════════
pnl_prefix  = "+" if pnl_positive    else "-"
brut_prefix = "+" if brut_positive   else "-"
pnl_abs     = raw_abs(kpi["pnl_net"])
pct_abs     = raw_abs(kpi["pnl_pct"])
brut_abs    = raw_abs(kpi["pnl_brut"])
brut_pct_abs= raw_abs(kpi["pnl_brut_pct"])
vm_val      = kpi["valeur_marche"]
cout_val    = kpi["cout_total"]
nb_pos      = str(len(positions))
pnl_class   = "cell-pos" if pnl_positive  else "cell-neg"
brut_class  = "cell-pos" if brut_positive else "cell-neg"

# Pastille d'alerte dans l'en-tete : le nombre de stops franchis. C'est
# l'information qu'on veut voir sans faire defiler la page, meme si on
# n'est pas sur l'onglet Technique.
_franchis = (stops_data.get("resume") or {}).get("franchis", 0) if stops_data else 0
badge_alertes = (f'<button class="hdr-alert" data-goto="technique" data-anchor="stops">'
                 f'{_franchis} alerte(s)</button>') if _franchis else ""

# Les entrees de sous-navigation n'apparaissent que si la section
# correspondante existe : un rapport plus ancien, ou un profil sans
# donnee sur tel axe, ne doit pas afficher un lien vers une ancre absente.
_a_correlation = bool(stops_data and (
    (stops_data.get("expo_indice") or {}).get("valeur") is not None
    or stops_data.get("expo_groupes")))

nav_portefeuille = [x for x in [
    ["#vue", "Vue générale"],
    (["#avertissements", "Avertissements"] if avertissements_donnees else None),
    ["#trajectoire", "Trajectoire"],
    ["#positions", "Positions"],
    (["#repartition", "Répartition"] if repartition else None),
    (["#synthese", "Synthèse"] if synthese_rows else None),
    (["#watchlist", "Watchlist"] if watchlist else None),
    (["#realise", "Plus-values"] if closes_rows else None),
    ["#historique", "Historique"],
] if x is not None]

nav_technique = [x for x in [
    (["#macro", "Contexte"] if (indices or bonds) else None),
    (["#stops", "Stops"] if stops_data and stops_data.get("stops") else None),
    (["#dimensionnement", "Dimensionnement"] if stops_data and stops_data.get("tailles") else None),
    (["#tendances", "Tendances"] if combined_b64 else None),
    (["#correlation", "Corrélation"] if _a_correlation else None),
    (["#fiabilite", "Fiabilité"] if learning else None),
] if x is not None]

nav_explications = [
    ["#guide", "Sommaire"], ["#expl-reco", "Recommandations"], ["#expl-note", "Note & confiance"],
    ["#expl-stops", "Stops"], ["#expl-correlation", "Corrélation"], ["#expl-macro", "Macro"],
]

NAV_CONFIG_JSON = json.dumps(
    {"portefeuille": nav_portefeuille, "technique": nav_technique, "explications": nav_explications},
    ensure_ascii=False)
JS = JS.replace("__NAV_CONFIG__", NAV_CONFIG_JSON)

_concentration = build_concentration_html()
if _concentration:
    bloc_trajectoire = f'<div class="layout section" id="trajectoire">{build_trajectoire_html()}{_concentration}</div>'
else:
    bloc_trajectoire = f'<div class="section" id="trajectoire">{build_trajectoire_html()}</div>'

html_out = f"""<!DOCTYPE html>
<html lang="fr" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rapport ProjectOne — {report_date}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>
<div class="shell">

  <header class="topbar" role="tablist" aria-label="Navigation du rapport">
    <div class="brand"><strong>Rapport ProjectOne</strong></div>
    <div class="tabs">
      <button class="tab" id="tab-portefeuille" role="tab" aria-selected="true" data-view="portefeuille">Portefeuille</button>
      <button class="tab" id="tab-technique" role="tab" aria-selected="false" data-view="technique">Technique</button>
      <button class="tab" id="tab-explications" role="tab" aria-selected="false" data-view="explications">Explications</button>
    </div>
    <div class="topbar-actions">
      {badge_alertes}
      <button class="text-btn" data-theme-toggle>Mode clair</button>
      <button class="text-btn" onclick="window.print()">Imprimer</button>
    </div>
    <div class="fresh"><span class="dot"></span>Dernière mise à jour&nbsp;: {report_date}</div>
  </header>

  <nav class="subnav" id="subnav"></nav>

  <main>
  <section class="view active" id="view-portefeuille" role="tabpanel" aria-labelledby="tab-portefeuille">

    <div class="page-head" id="vue">
      <div>
        <div class="eyebrow">Décider avec contexte</div>
        <h1>Ton portefeuille, en un regard</h1>
        <p>Performance, positions qui demandent ton attention, et ce qu'il faut surveiller autour d'elles.</p>
      </div>
    </div>

    <div class="kpis">
      <article class="card kpi featured">
        <span class="label">PnL net estimé</span>
        <div class="value {pnl_class}" data-counter data-val="{pnl_abs}" data-suffix=" €" data-prefix="{pnl_prefix}">{pnl_prefix}{pnl_abs} €</div>
        <div class="delta {pnl_class}">Performance nette {pnl_prefix}{pct_abs} %</div>
      </article>
      <article class="card kpi">
        <span class="label">P&amp;L brut</span>
        <div class="value {brut_class}" data-counter data-val="{brut_abs}" data-suffix=" €" data-prefix="{brut_prefix}">{brut_prefix}{brut_abs} €</div>
      </article>
      <article class="card kpi">
        <span class="label">Valeur de marché</span>
        <div class="value" data-counter data-val="{vm_val}">{vm_val} €</div>
      </article>
      <article class="card kpi">
        <span class="label">Coût total investi</span>
        <div class="value" data-counter data-val="{cout_val}">{cout_val} €</div>
      </article>
      <article class="card kpi">
        <span class="label">Positions actives</span>
        <div class="value">{nb_pos}</div>
      </article>
    </div>

    {build_avertissements_html()}

    {bloc_trajectoire}

    {build_positions_html()}
    {build_repartition_html()}
    {build_synthese_html()}
    {build_watchlist_html()}
    {build_closes_html()}
    {build_archive_html()}

  </section>

  <section class="view" id="view-technique" role="tabpanel" aria-labelledby="tab-technique">

    <div class="page-head" id="analyse-tete">
      <div>
        <div class="eyebrow">Comprendre avant d'agir</div>
        <h1>Technique &amp; risque</h1>
        <p>Le contexte de marché, ce qui protège le portefeuille, et la fiabilité du système qui note tes positions.</p>
      </div>
    </div>

    <div class="analysis-grid">
      <div class="stack">
        {build_indices_html()}
        {build_stops_html()}
        {build_dimensionnement_html()}
        {build_combined_chart_html()}
        {build_correlation_html()}
        {build_learning_html()}
      </div>
      {build_fiabilite_ring_html()}
    </div>

  </section>

  <section class="view" id="view-explications" role="tabpanel" aria-labelledby="tab-explications">
    {build_explications_html()}
  </section>
  </main>

  <p class="footer-note">ProjectOne est une aide à la décision, pas un conseil en investissement.</p>
</div>

<script>{JS}</script>
</body>
</html>
"""

Path("docs").mkdir(exist_ok=True)
HTML_PATH.write_text(html_out, encoding="utf-8")
