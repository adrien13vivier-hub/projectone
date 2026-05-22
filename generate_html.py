#!/usr/bin/env python3
"""
generate_html.py  v3.5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Convertit reports/daily_report.md  →  docs/index.html
• KPIs animés (compteurs au chargement)
• Graphique combiné normalisé base 100 (section Tendances)
• Tableaux positions + synthèse extraits du Markdown
• Synthèse IA par position (bloc > blockquote dans le Markdown)  ← v3.2
  - v3.3 : capture multi-lignes (toutes les lignes ">") concaténées
  - v3.4 : regex synth_src tolère les parenthèses dans le nom de source
            (ex: "RSS Yahoo Finance (brut)" capturé correctement)
  - v3.5 : suppression des print() finaux (cron-silent) + version v5.5
• Historique des 30 derniers rapports (archive.json)
• Mode sombre / clair
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import base64, json, logging, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("generate_html")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

# ── Chemins ──────────────────────────────────────────────
MD_PATH      = Path("reports/daily_report.md")
HTML_PATH    = Path("docs/index.html")
ARCHIVE_PATH = Path("docs/archive.json")
CHARTS_DIR   = Path("reports/charts")
COMBINED_PNG = CHARTS_DIR / "portfolio_combined.png"

# ── Lecture Markdown ───────────────────────────────────────
if not MD_PATH.exists():
    _log.warning("reports/daily_report.md introuvable — page vide générée.")
    md_content = "# Rapport indisponible\n\nAucun rapport généré ce jour."
else:
    md_content = MD_PATH.read_text(encoding="utf-8")

# ── Date du rapport ───────────────────────────────────────
date_match  = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", md_content)
report_date = date_match.group(1) if date_match else \
              datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

# ── Graphique combiné → base64 ─────────────────────────────
combined_b64 = ""
if COMBINED_PNG.exists():
    combined_b64 = base64.b64encode(COMBINED_PNG.read_bytes()).decode()

# ══════════════════════════════════════════════════════════
# EXTRACTION KPI
# ══════════════════════════════════════════════════════════
def extract_kpi(md: str) -> dict:
    kpi = {"pnl_net": "0", "pnl_pct": "0", "valeur_marche": "0",
           "cout_total": "0", "pnl_brut": "0", "pnl_brut_pct": "0"}
    m = re.search(
        r"\|\s*([\d\s,.]+)\s*EUR\s*\|\s*([\d\s,.]+)\s*EUR\s*"
        r"\|[^|]*?([+-][\d\s,.]+)\s*EUR[^|]*?([+-][\d,.]+)%[^|]*"
        r"\|[^|]*?([+-][\d\s,.]+)\s*EUR[^|]*?([+-][\d,.]+)%",
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

# ══════════════════════════════════════════════════════════
# EXTRACTION POSITIONS (blocs ### Valeur)
# ══════════════════════════════════════════════════════════
def extract_positions(md: str) -> list[dict]:
    positions = []
    blocks = re.split(r"(?=^### .+`)", md, flags=re.MULTILINE)
    for block in blocks:
        m_head = re.match(r"^### (.+?)\s*`([^`]+)`", block)
        if not m_head:
            continue
        name   = m_head.group(1).strip()
        ticker = m_head.group(2).strip()
        m_row = re.search(
            r"\|\s*([\d,.]+)\s*EUR\s*\|"
            r"\s*([^|]+?)\s*\|"
            r"\s*([\d,.]+)\s*EUR\s*\|"
            r"\s*([^|]+?EUR[^|]+?)\s*\|"
            r"\s*([^|]+?EUR[^|]+?)\s*\|"
            r"\s*\*?\*?([\d.]+/10)\*?\*?\s*\|"
            r"\s*([^|]+?)\s*\|",
            block)
        if not m_row:
            continue
        prix      = m_row.group(1).strip()
        variation = m_row.group(2).strip()
        vm        = m_row.group(3).strip()
        pnl_brut  = m_row.group(4).strip()
        pnl_net   = m_row.group(5).strip()
        score     = m_row.group(6).strip()
        rec       = m_row.group(7).strip()
        m_sent = re.search(r"Sentiment[^:]*:\s*Bull\s*([\d.]+)%\s*/\s*Bear\s*([\d.]+)%", block)
        bull = m_sent.group(1) if m_sent else "—"
        bear = m_sent.group(2) if m_sent else "—"
        m_mom = re.search(r"Momentum[^:]*:\s*(\w+)\s*\(1M:\s*([^/]+)/\s*3M:\s*([^/]+)/\s*6M:\s*([^)]+)\)", block)
        mom_label = m_mom.group(1) if m_mom else "—"
        ret_1m    = m_mom.group(2).strip() if m_mom else "—"
        ret_3m    = m_mom.group(3).strip() if m_mom else "—"
        ret_6m    = m_mom.group(4).strip() if m_mom else "—"

        synthesis = ""
        synth_src = ""
        m_synth_src = re.search(
            r"\*\*Actualite[^*]*\*\*[^(]*\(source\s*:\s*(.+?)\)\s*\*?(?:\n|$)",
            block)
        if m_synth_src:
            synth_src = m_synth_src.group(1).strip()

        synth_block = block
        m_actualite_pos = re.search(r"\*\*Actualite[^*]*\*\*", block)
        if m_actualite_pos:
            synth_block = block[m_actualite_pos.start():]
        synth_lines = re.findall(r"^>\s*(.+)", synth_block, flags=re.MULTILINE)
        if synth_lines:
            synthesis = " ".join(line.strip() for line in synth_lines).strip()

        positions.append({
            "name": name, "ticker": ticker,
            "prix": prix, "variation": variation, "vm": vm,
            "pnl_brut": pnl_brut, "pnl_net": pnl_net,
            "score": score, "rec": rec,
            "bull": bull, "bear": bear,
            "mom_label": mom_label,
            "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_6m": ret_6m,
            "synthesis": synthesis, "synth_src": synth_src,
        })
    return positions

positions = extract_positions(md_content)

# ══════════════════════════════════════════════════════════
# EXTRACTION SYNTHÈSE / CLASSEMENT
# ══════════════════════════════════════════════════════════
def extract_synthese(md: str) -> list[dict]:
    rows = []
    in_class = False
    for line in md.split("\n"):
        if "Classement par Score" in line or "Synthese Portefeuille" in line:
            in_class = True
        if in_class and re.match(r"^\|", line) and not re.match(r"^\|[-| :]+\|", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 5 and cells[0] and cells[0] not in ("Valeur", "Cout total"):
                rows.append(cells)
    return rows

synthese_rows = extract_synthese(md_content)

# ══════════════════════════════════════════════════════════
# EXTRACTION INDICES MACRO
# ══════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════
# ARCHIVE JSON
# ══════════════════════════════════════════════════════════
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
archive = archive[:30]
ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

# ══════════════════════════════════════════════════════════
# HELPERS HTML
# ══════════════════════════════════════════════════════════
def rec_badge(rec: str) -> str:
    rec_u = rec.upper()
    if "ACHAT FORT"   in rec_u: cls, ico = "buy-strong", "🟢"
    elif "ACHAT"      in rec_u: cls, ico = "buy-mod",    "🔵"
    elif "GARDER"     in rec_u: cls, ico = "hold",       "🟡"
    elif "EVITER" in rec_u or "ÉVITER" in rec_u: cls, ico = "avoid", "🟠"
    elif "VENDRE"     in rec_u: cls, ico = "sell",       "🔴"
    else:                       cls, ico = "hold",       "⚪"
    label = rec.replace("ACHAT FORT", "ACHAT FORT").replace("ACHAT MODERE", "ACHAT MODÉRÉ") \
               .replace("A EVITER", "À ÉVITER")
    return f'<span class="badge {cls}">{ico} {label}</span>'

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
    if "HAUSSE" in l or "HAUSSIER" in l: return f'<span class="badge buy-strong">↗ {label}</span>'
    if "BAISSE" in l or "BAISSIER" in l: return f'<span class="badge sell">↘ {label}</span>'
    return f'<span class="badge hold">→ {label}</span>'

def var_span(txt: str) -> str:
    t = txt.strip()
    if t.startswith(("^", "+")) or ("+" in t and "%" in t):
        return f'<span class="up">▲ {t.lstrip("^")}</span>'
    if t.startswith(("v", "-")) or ("-" in t and "%" in t):
        return f'<span class="dn">▼ {t.lstrip("v")}</span>'
    return t

# ══════════════════════════════════════════════════════════
# BLOCS HTML
# ══════════════════════════════════════════════════════════

def build_indices_html() -> str:
    if not indices:
        return ""
    rows = ""
    for idx in indices:
        rows += (f"<tr><td><strong>{idx['name']}</strong></td>"
                 f"<td>{var_span(idx['variation'])}</td>"
                 f"<td class='cell-num'>{idx['cours']}</td></tr>\n")
    return f"""
<section class="section-block" id="macro">
  <h2 class="section-title">🌍 Contexte Économique</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Indice</th><th>Variation</th><th>Cours</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>"""

def build_combined_chart_html() -> str:
    if not combined_b64:
        return ""
    return f"""
<section class="section-block" id="tendances">
  <h2 class="section-title">📉 Tendances — Performance Normalisée (Base 100)</h2>
  <div class="combined-chart-wrap">
    <img src="data:image/png;base64,{combined_b64}"
         alt="Performance normalisée base 100 de toutes les positions"
         loading="lazy" class="combined-chart-img"
         width="900" height="500">
    <p class="chart-caption">
      Chaque courbe représente la performance d'une valeur normalisée à 100 au premier jour disponible.
      La ligne pointillée à 100 est la référence (prix d'entrée).
    </p>
  </div>
</section>"""

def build_positions_html() -> str:
    if not positions:
        return "<p style='color:var(--muted)'>Aucune position disponible.</p>"

    cards = ""
    for p in positions:
        pnl_net_cls  = "kpi-positive" if "+" in p["pnl_net"]  else "kpi-negative"
        pnl_brut_cls = "kpi-positive" if "+" in p["pnl_brut"] else "kpi-negative"
        var_html = var_span(p["variation"])

        synthesis_html = ""
        synth_text = p.get("synthesis", "").strip()
        if synth_text and "Aucune actualite" not in synth_text:
            src_label = f'<span class="synth-src">{p["synth_src"]}</span>' if p.get("synth_src") else ""
            synthesis_html = f"""
    <div class="pos-synthesis">
      <div class="synth-header">💬 Actualité récente {src_label}</div>
      <p class="synth-text">{synth_text}</p>
    </div>"""

        cards += f"""
<div class="position-card" id="pos-{p['ticker'].replace('.','_')}">
  <div class="pos-header">
    <div class="pos-title">
      <span class="pos-name">{p['name']}</span>
      <code class="pos-ticker">{p['ticker']}</code>
    </div>
    <div class="pos-rec">{rec_badge(p['rec'])}</div>
  </div>

  <div class="pos-kpis">
    <div class="pos-kpi">
      <div class="pos-kpi-val cell-num">{p['prix']} EUR</div>
      <div class="pos-kpi-lbl">Cours {var_html}</div>
    </div>
    <div class="pos-kpi">
      <div class="pos-kpi-val cell-num">{p['vm']} EUR</div>
      <div class="pos-kpi-lbl">Valeur marché</div>
    </div>
    <div class="pos-kpi">
      <div class="pos-kpi-val {pnl_brut_cls}">{p['pnl_brut']}</div>
      <div class="pos-kpi-lbl">P&amp;L Brut</div>
    </div>
    <div class="pos-kpi">
      <div class="pos-kpi-val {pnl_net_cls}">{p['pnl_net']}</div>
      <div class="pos-kpi-lbl">P&amp;L Net</div>
    </div>
    <div class="pos-kpi">
      <div>{score_bar(p['score'])}</div>
      <div class="pos-kpi-lbl">Score global</div>
    </div>
  </div>

  <div class="pos-details">
    <div class="pos-detail-item">
      <span class="detail-lbl">Sentiment</span>
      <span>🐂 Bull <strong>{p['bull']}%</strong> / 🐻 Bear <strong>{p['bear']}%</strong></span>
    </div>
    <div class="pos-detail-item">
      <span class="detail-lbl">Momentum</span>
      <span>{mom_badge(p['mom_label'])}
        <span class="mom-rets">1M: {p['ret_1m']} · 3M: {p['ret_3m']} · 6M: {p['ret_6m']}</span>
      </span>
    </div>
  </div>
  {synthesis_html}
</div>"""
    return f"""
<section class="section-block" id="positions">
  <h2 class="section-title">📈 Positions Détenues</h2>
  <div class="positions-grid">{cards}</div>
</section>"""

def build_synthese_html() -> str:
    if not synthese_rows:
        return ""
    rows_html = ""
    for cells in synthese_rows:
        if len(cells) < 5:
            continue
        name_cell = f"<td><strong>{cells[0]}</strong></td>"
        vm_cell   = f"<td class='cell-num'>{cells[1]}</td>"
        pnl_cell_h = pnl_cell(cells[2])
        score_cell = f"<td>{score_bar(cells[3])}</td>" if "/" in cells[3] else f"<td class='cell-num'>{cells[3]}</td>"
        rec_cell  = f"<td>{rec_badge(cells[4])}</td>"
        rows_html += f"<tr>{name_cell}{vm_cell}{pnl_cell_h}{score_cell}{rec_cell}</tr>\n"

    return f"""
<section class="section-block" id="synthese">
  <h2 class="section-title">🏆 Synthèse &amp; Recommandations</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Valeur</th><th>Valeur Marché</th>
          <th>P&amp;L Net</th><th>Score</th><th>Recommandation</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</section>"""

def build_archive_html() -> str:
    return """
<section class="section-block" id="historique">
  <h2 class="section-title">📂 Historique des Rapports</h2>
  <button class="archive-toggle" onclick="toggleArchive()" id="archive-btn">
    ▼ Afficher les 30 derniers rapports
  </button>
  <div id="archive-panel">
    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>P&L Net</th><th>VM</th><th>Positions</th></tr></thead>
        <tbody id="archive-tbody">
          <tr><td colspan="4" style="text-align:center;color:var(--muted)">Chargement…</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>"""

# ══════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════
CSS = """
:root {
  --bg:          #0d1117;
  --surface:     #161b22;
  --surface-2:   #1c2130;
  --border:      #21262d;
  --text:        #e6edf3;
  --muted:       #7d8590;
  --faint:       #2d333b;
  --accent:      #4f98a3;
  --accent-dim:  rgba(79,152,163,.12);
  --green:       #3fb950;
  --green-dim:   rgba(63,185,80,.12);
  --red:         #f85149;
  --red-dim:     rgba(248,81,73,.12);
  --yellow:      #d29922;
  --yellow-dim:  rgba(210,153,34,.12);
  --radius:      12px;
  --radius-sm:   8px;
  --shadow:      0 4px 24px rgba(0,0,0,.4);
  --font-body:   'Inter', system-ui, sans-serif;
  --font-mono:   'JetBrains Mono', 'Fira Code', monospace;
}
[data-theme="light"] {
  --bg:          #f6f8fa;
  --surface:     #ffffff;
  --surface-2:   #f0f2f5;
  --border:      #d0d7de;
  --text:        #1f2328;
  --muted:       #57606a;
  --faint:       #d8dee4;
  --accent:      #0969da;
  --accent-dim:  rgba(9,105,218,.08);
  --green:       #1a7f37;
  --green-dim:   rgba(26,127,55,.08);
  --red:         #cf222e;
  --red-dim:     rgba(207,34,46,.08);
  --yellow:      #9a6700;
  --shadow:      0 4px 24px rgba(0,0,0,.08);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; scroll-padding-top: 68px; }
body {
  font-family: var(--font-body);
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
  font-size: 14px;
  min-height: 100dvh;
  -webkit-font-smoothing: antialiased;
}
header {
  position: sticky; top: 0; z-index: 200;
  background: color-mix(in oklab, var(--bg) 88%, transparent);
  backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  height: 56px;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
.logo { font-size: 14px; font-weight: 700; letter-spacing: -.3px; display: flex; align-items: center; gap: 8px; }
.logo-icon { font-size: 18px; }
.logo-name { color: var(--text); }
.logo-name span { color: var(--accent); }
.header-meta { font-size: 11px; color: var(--muted); font-family: var(--font-mono); }
.header-nav  { display: flex; gap: 2px; }
.header-nav a {
  font-size: 12px; color: var(--muted); text-decoration: none;
  padding: 5px 10px; border-radius: var(--radius-sm);
  transition: color .15s, background .15s;
}
.header-nav a:hover { color: var(--text); background: var(--surface-2); }
.header-actions { display: flex; gap: 6px; align-items: center; }
.btn-icon {
  background: var(--surface-2); border: 1px solid var(--border);
  color: var(--muted); border-radius: var(--radius-sm);
  padding: 5px 10px; font-size: 13px; cursor: pointer;
  transition: color .15s, background .15s;
}
.btn-icon:hover { color: var(--text); background: var(--faint); }
.container { max-width: 1040px; margin: 0 auto; padding: 28px 20px 100px; }
.update-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px; font-size: .76rem;
  color: var(--muted); margin-bottom: 24px;
}
.update-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green); box-shadow: 0 0 8px var(--green);
  flex-shrink: 0;
  animation: pulse 2.4s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(.85)} }
.kpi-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px; margin-bottom: 36px;
}
.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 18px 20px;
  transition: border-color .2s, box-shadow .2s;
  position: relative; overflow: hidden;
}
.kpi-card::before {
  content: ""; position: absolute; inset: 0;
  border-radius: var(--radius);
  background: linear-gradient(135deg, var(--accent-dim), transparent 60%);
  opacity: 0; transition: opacity .3s;
}
.kpi-card:hover::before { opacity: 1; }
.kpi-card:hover { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent), var(--shadow); }
.kpi-val {
  font-size: 1.6rem; font-weight: 700; font-family: var(--font-mono);
  letter-spacing: -.5px; line-height: 1.1; position: relative; z-index: 1;
}
.kpi-lbl {
  font-size: .7rem; color: var(--muted); margin-top: 6px;
  text-transform: uppercase; letter-spacing: .6px; position: relative; z-index: 1;
}
.kpi-positive { color: var(--green); }
.kpi-negative { color: var(--red); }
.kpi-neutral  { color: var(--accent); }
.kpi-card.main-card { border-color: var(--accent); background: color-mix(in oklab, var(--accent) 6%, var(--surface)); }
.section-block { margin-bottom: 48px; }
.section-title {
  font-size: .88rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .8px; color: var(--muted); margin-bottom: 16px;
  padding-bottom: 10px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
}
.combined-chart-wrap {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow);
}
.combined-chart-img { width: 100%; display: block; max-height: 520px; object-fit: contain; }
.chart-caption {
  font-size: .75rem; color: var(--muted);
  padding: 10px 16px 14px; border-top: 1px solid var(--border);
  font-style: italic; line-height: 1.5;
}
.positions-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(440px, 1fr)); gap: 16px; }
.position-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px;
  transition: border-color .2s, box-shadow .2s;
}
.position-card:hover { border-color: var(--accent); box-shadow: var(--shadow); }
.pos-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; gap: 8px; }
.pos-title  { display: flex; flex-direction: column; gap: 4px; }
.pos-name   { font-size: .95rem; font-weight: 700; color: var(--text); }
.pos-ticker {
  font-family: var(--font-mono); font-size: .75rem;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 4px; padding: 1px 6px; color: var(--accent);
  display: inline-block; width: fit-content;
}
.pos-kpis {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
  gap: 10px; margin-bottom: 14px;
}
.pos-kpi { background: var(--surface-2); border-radius: var(--radius-sm); padding: 10px 12px; }
.pos-kpi-val { font-size: .88rem; font-weight: 700; font-family: var(--font-mono); }
.pos-kpi-lbl { font-size: .68rem; color: var(--muted); margin-top: 3px; }
.pos-details { border-top: 1px solid var(--border); padding-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.pos-detail-item { display: flex; gap: 10px; align-items: baseline; font-size: .82rem; }
.detail-lbl { font-size: .7rem; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; min-width: 72px; flex-shrink: 0; }
.mom-rets { font-size: .74rem; color: var(--muted); font-family: var(--font-mono); margin-left: 6px; }
.pos-synthesis {
  margin-top: 12px;
  background: color-mix(in oklab, var(--accent) 6%, var(--surface-2));
  border: 1px solid color-mix(in oklab, var(--accent) 20%, var(--border));
  border-radius: var(--radius-sm);
  padding: 10px 14px;
}
.synth-header {
  font-size: .7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .5px; color: var(--accent); margin-bottom: 6px;
  display: flex; align-items: center; gap: 6px;
}
.synth-src {
  font-size: .68rem; font-weight: 400; color: var(--muted);
  text-transform: none; letter-spacing: 0;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 4px; padding: 1px 6px;
}
.synth-text {
  font-size: .8rem; color: var(--text); line-height: 1.6;
  font-style: italic; max-width: none;
}
.score-wrap { display: flex; flex-direction: column; gap: 4px; }
.score-num  { font-size: .88rem; font-weight: 700; font-family: var(--font-mono); color: var(--text); }
.score-bar  { height: 4px; background: var(--faint); border-radius: 2px; overflow: hidden; }
.score-fill { height: 100%; border-radius: 2px; transition: width 1s cubic-bezier(.16,1,.3,1); }
.bar-green  { background: var(--green); }
.bar-yellow { background: var(--yellow); }
.bar-red    { background: var(--red); }
.table-wrap {
  overflow-x: auto; border-radius: var(--radius);
  border: 1px solid var(--border); box-shadow: var(--shadow); margin: 0;
}
table { width: 100%; border-collapse: collapse; font-size: .83rem; }
th {
  background: var(--surface-2); color: var(--muted); font-weight: 600;
  font-size: .7rem; text-transform: uppercase; letter-spacing: .5px;
  padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
td {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  vertical-align: middle; color: var(--text);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--accent-dim); transition: background .12s; }
.cell-pos { color: var(--green) !important; font-weight: 600; font-family: var(--font-mono); }
.cell-neg { color: var(--red)   !important; font-weight: 600; font-family: var(--font-mono); }
.cell-num { font-family: var(--font-mono); }
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: .73rem; font-weight: 700; padding: 3px 10px;
  border-radius: 20px; white-space: nowrap;
}
.buy-strong { background: var(--green-dim);  color: var(--green);  border: 1px solid rgba(63,185,80,.3); }
.buy-mod    { background: var(--accent-dim); color: var(--accent); border: 1px solid rgba(79,152,163,.3); }
.hold       { background: var(--yellow-dim); color: var(--yellow); border: 1px solid rgba(210,153,34,.3); }
.avoid      { background: rgba(249,115,22,.1); color: #fb923c; border: 1px solid rgba(249,115,22,.3); }
.sell       { background: var(--red-dim);    color: var(--red);    border: 1px solid rgba(248,81,73,.3); }
.up { color: var(--green); font-weight: 700; }
.dn { color: var(--red);   font-weight: 700; }
.archive-toggle {
  font-size: .8rem; color: var(--accent); cursor: pointer;
  background: none; border: none; padding: 4px 0;
  transition: color .15s; margin-bottom: 12px; display: block;
}
.archive-toggle:hover { color: var(--text); }
#archive-panel { display: none; margin-bottom: 8px; }
#archive-panel.open { display: block; }
hr { border: none; border-top: 1px solid var(--border); margin: 32px 0; }
@media print {
  header, .header-actions, .archive-toggle, #archive-panel,
  .update-badge { display: none !important; }
  body { background: #fff; color: #000; font-size: 13px; }
  .position-card { break-inside: avoid; border: 1px solid #ccc; }
  .badge { border: 1px solid #ccc !important; color: #000 !important; background: none !important; }
  .combined-chart-img { max-height: none; }
  .pos-synthesis { border: 1px solid #ccc !important; background: #f9f9f9 !important; }
}
@media (max-width: 700px) {
  header { padding: 0 14px; }
  .header-nav { display: none; }
  .container { padding: 16px 12px 80px; }
  .kpi-bar { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .kpi-val { font-size: 1.25rem; }
  .positions-grid { grid-template-columns: 1fr; }
  .pos-kpis { grid-template-columns: repeat(3, 1fr); }
  td, th { padding: 8px 10px; font-size: .76rem; }
}
@keyframes fadeUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
.kpi-card       { animation: fadeUp .45s cubic-bezier(.16,1,.3,1) both; }
.kpi-card:nth-child(1) { animation-delay: .05s; }
.kpi-card:nth-child(2) { animation-delay: .1s;  }
.kpi-card:nth-child(3) { animation-delay: .15s; }
.kpi-card:nth-child(4) { animation-delay: .2s;  }
.kpi-card:nth-child(5) { animation-delay: .25s; }
.position-card  { animation: fadeUp .5s cubic-bezier(.16,1,.3,1) both; }
"""

# ══════════════════════════════════════════════════════════
# JS
# ══════════════════════════════════════════════════════════
JS = r"""
(function(){
  var root = document.documentElement;
  var btn  = document.querySelector('[data-theme-toggle]');
  function sg(k){try{return localStorage.getItem(k);}catch(e){return null;}}
  function ss(k,v){try{localStorage.setItem(k,v);}catch(e){}}
  var theme = sg('theme') || (matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');
  root.setAttribute('data-theme', theme);
  if(btn) btn.textContent = theme==='dark' ? '☀️' : '🌙';
  if(btn) btn.addEventListener('click', function(){
    theme = theme==='dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', theme);
    ss('theme', theme);
    btn.textContent = theme==='dark' ? '☀️' : '🌙';
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
    if(entries[0].isIntersecting){ animateCounter(el); o.disconnect(); }
  }, {threshold: 0.3});
  obs.observe(el);
});

document.querySelectorAll('td').forEach(function(td){
  var t = td.textContent.trim();
  if (/^[+][\d\s].*[€%]/.test(t)) td.classList.add('cell-pos');
  else if (/^[-][\d\s].*[€%]/.test(t)) td.classList.add('cell-neg');
});

document.querySelectorAll('.score-fill').forEach(function(bar){
  var w = bar.style.width;
  bar.style.width = '0%';
  setTimeout(function(){
    bar.style.width = w;
  }, 400);
});

function toggleArchive() {
  var panel = document.getElementById('archive-panel');
  var btn   = document.getElementById('archive-btn');
  var open  = panel.classList.toggle('open');
  btn.textContent = open ? '\u25b2 Masquer l\'historique' : '\u25bc Afficher les 30 derniers rapports';
  if (open) loadArchive();
}
var _archiveLoaded = false;
function loadArchive() {
  if (_archiveLoaded) return;
  _archiveLoaded = true;
  fetch('./archive.json')
    .then(function(r){ return r.json(); })
    .then(function(data){
      var tbody = document.getElementById('archive-tbody');
      tbody.innerHTML = data.map(function(e, i){
        var cls = i === 0 ? 'style="background:var(--accent-dim)"' : '';
        var pnl = e.pnl || '\u2014';
        var pnlCls = pnl.includes('+') ? 'cell-pos' : pnl.includes('-') ? 'cell-neg' : '';
        return '<tr ' + cls + '>'
          + '<td class="cell-num" style="white-space:nowrap">📅 ' + e.date + '</td>'
          + '<td class="' + pnlCls + '">' + pnl + '</td>'
          + '<td class="cell-num">' + (e.vm ? e.vm + ' \u20ac' : '\u2014') + '</td>'
          + '<td class="cell-num">' + (e.nb_pos || '\u2014') + '</td>'
          + '</tr>';
      }).join('');
    })
    .catch(function(){
      document.getElementById('archive-tbody').innerHTML =
        '<tr><td colspan="4" style="text-align:center;color:var(--muted)">Historique non disponible.</td></tr>';
    });
}
"""

# ══════════════════════════════════════════════════════════
# ASSEMBLAGE HTML FINAL
# ══════════════════════════════════════════════════════════
pnl_prefix  = "+" if pnl_positive    else "-"
brut_prefix = "+" if brut_positive   else "-"
pnl_abs     = raw_abs(kpi["pnl_net"])
pct_abs     = raw_abs(kpi["pnl_pct"])
brut_abs    = raw_abs(kpi["pnl_brut"])
brut_pct_abs= raw_abs(kpi["pnl_brut_pct"])
vm_val      = kpi["valeur_marche"]
cout_val    = kpi["cout_total"]
nb_pos      = str(len(positions))

html_out = f"""<!DOCTYPE html>
<html lang="fr" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Portfolio Analyzer — {report_date}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>

  <!-- HEADER -->
  <header>
    <div style="display:flex;align-items:center;gap:16px">
      <div class="logo">
        <span class="logo-icon">📊</span>
        <span class="logo-name"><span>Portfolio</span> Analyzer</span>
      </div>
      <div class="header-meta">v5.5 · {report_date}</div>
    </div>
    <nav class="header-nav">
      <a href="#macro">Macro</a>
      <a href="#tendances">Tendances</a>
      <a href="#positions">Positions</a>
      <a href="#synthese">Synthèse</a>
      <a href="#historique">Historique</a>
    </nav>
    <div class="header-actions">
      <button class="btn-icon" onclick="window.print()" title="Imprimer / PDF">🖨️</button>
      <button class="btn-icon" data-theme-toggle aria-label="Changer de thème">☀️</button>
    </div>
  </header>

  <div class="container">

    <div class="update-badge">
      <span class="update-dot"></span>
      Dernière mise à jour :&nbsp;<strong>{report_date}</strong>
    </div>

    <div class="kpi-bar">
      <div class="kpi-card main-card">
        <div class="kpi-val {pnl_class}"
             data-counter data-val="{pnl_abs}"
             data-suffix=" €" data-prefix="{pnl_prefix}">
          {pnl_prefix}{pnl_abs} €
        </div>
        <div class="kpi-lbl">PnL Net estimé</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val {pnl_class}"
             data-counter data-val="{pct_abs}"
             data-suffix=" %" data-prefix="{pnl_prefix}">
          {pnl_prefix}{pct_abs} %
        </div>
        <div class="kpi-lbl">Performance nette</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val {brut_class}"
             data-counter data-val="{brut_abs}"
             data-suffix=" €" data-prefix="{brut_prefix}">
          {brut_prefix}{brut_abs} €
        </div>
        <div class="kpi-lbl">P&amp;L Brut</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val kpi-neutral"
             data-counter data-val="{vm_val}">
          {vm_val} €
        </div>
        <div class="kpi-lbl">Valeur de Marché</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val kpi-neutral"
             data-counter data-val="{cout_val}">
          {cout_val} €
        </div>
        <div class="kpi-lbl">Coût Total Investi</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-val kpi-neutral">{nb_pos}</div>
        <div class="kpi-lbl">Positions actives</div>
      </div>
    </div>

    {build_indices_html()}
    {build_combined_chart_html()}
    {build_positions_html()}
    {build_synthese_html()}
    {build_archive_html()}

  </div>

  <script>{JS}</script>
</body>
</html>
"""

Path("docs").mkdir(exist_ok=True)
HTML_PATH.write_text(html_out, encoding="utf-8")
sys.exit(0)
