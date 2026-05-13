#!/usr/bin/env python3
"""
generate_html.py  v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Convertit reports/daily_report.md → docs/index.html
Intègre les graphiques PNG en base64 (aucune dépendance réseau)
Met à jour docs/archive.json (30 derniers rapports)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Chemins ────────────────────────────────────────────────────────────────────
MD_PATH      = Path("reports/daily_report.md")
HTML_PATH    = Path("docs/index.html")
ARCHIVE_PATH = Path("docs/archive.json")
CHARTS_DIR   = Path("reports/charts")

# ── Lecture du Markdown ────────────────────────────────────────────────────────
if not MD_PATH.exists():
    print("[WARN] reports/daily_report.md introuvable — page vide générée.")
    md_content = "# Rapport indisponible\n\nAucun rapport généré ce jour."
else:
    md_content = MD_PATH.read_text(encoding="utf-8")

# ── Extraction date ────────────────────────────────────────────────────────────
date_match  = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", md_content)
report_date = date_match.group(1) if date_match else \
              datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

# ── Graphiques PNG → base64 ────────────────────────────────────────────────────
charts_b64: dict[str, str] = {}
if CHARTS_DIR.exists():
    for png in sorted(CHARTS_DIR.glob("*.png")):
        raw = png.read_bytes()
        charts_b64[png.stem] = base64.b64encode(raw).decode()


# ══════════════════════════════════════════════════════════════════════════════
# PARSER MARKDOWN → HTML
# ══════════════════════════════════════════════════════════════════════════════

def inline(text: str) -> str:
    """Formatage inline : badges, gras, italique, code, liens, flèches."""
    badges = [
        (r"🟢 ACHAT FORT",   "buy-strong", "🟢 ACHAT FORT"),
        (r"🔵 ACHAT MODÉRÉ", "buy-mod",    "🔵 ACHAT MODÉRÉ"),
        (r"🟡 GARDER",       "hold",       "🟡 GARDER"),
        (r"🟠 À ÉVITER",     "avoid",      "🟠 À ÉVITER"),
        (r"🔴 VENDRE",       "sell",       "🔴 VENDRE"),
    ]
    for pattern, cls, label in badges:
        text = text.replace(pattern, f'<span class="badge {cls}">{label}</span>')

    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*",     r"<strong>\1</strong>",          text)
    text = re.sub(r"\*(.+?)\*",         r"<em>\1</em>",                  text)
    text = re.sub(r"_(.+?)_",           r"<em>\1</em>",                  text)
    text = re.sub(r"`([^`]+)`",         r"<code>\1</code>",              text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    text = text.replace("▲", '<span class="up">▲</span>')
    text = text.replace("▼", '<span class="dn">▼</span>')
    return text


def md_to_html(md: str) -> str:
    """Convertit un texte Markdown en HTML structuré."""
    lines       = md.split("\n")
    html        = []
    in_table    = False
    in_ul       = False
    in_ol       = False
    in_blockq   = False
    in_code     = False
    code_buf    = []
    th_done     = False
    para_buf    = []

    def flush_para():
        if para_buf:
            joined = " ".join(para_buf)
            html.append(f'<p>{inline(joined)}</p>')
            para_buf.clear()

    def close_list():
        nonlocal in_ul, in_ol
        if in_ul:
            html.append("</ul>")
            in_ul = False
        if in_ol:
            html.append("</ol>")
            in_ol = False

    def close_blockq():
        nonlocal in_blockq
        if in_blockq:
            html.append("</blockquote>")
            in_blockq = False

    def close_table():
        nonlocal in_table, th_done
        if in_table:
            html.append("</tbody></table></div>")
            in_table = False
            th_done  = False

    for raw in lines:
        line = raw

        # ── Blocs de code ```
        if line.strip().startswith("```"):
            flush_para(); close_list(); close_blockq(); close_table()
            if not in_code:
                in_code  = True
                code_buf = []
            else:
                in_code = False
                code_text = "\n".join(code_buf)
                html.append(f'<pre><code>{code_text}</code></pre>')
                code_buf = []
            continue
        if in_code:
            code_buf.append(raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue

        # ── Tableau Markdown
        if re.match(r"^\|", line):
            flush_para(); close_list(); close_blockq()
            if not in_table:
                html.append('<div class="table-wrap"><table><thead>')
                in_table = True
                th_done  = False
            if re.match(r"^\|[-| :]+\|", line):
                html.append("</thead><tbody>")
                th_done = True
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            tag   = "td" if th_done else "th"
            row   = "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells)
            html.append(f"<tr>{row}</tr>")
            continue
        else:
            close_table()

        # ── Blockquote
        if line.startswith("> "):
            flush_para(); close_list()
            if not in_blockq:
                html.append('<blockquote>')
                in_blockq = True
            html.append(f'<p>{inline(line[2:])}</p>')
            continue
        else:
            close_blockq()

        # ── Listes ordonnées
        m_ol = re.match(r"^(\d+)\. (.+)", line)
        if m_ol:
            flush_para()
            if not in_ol:
                if in_ul:
                    html.append("</ul>"); in_ul = False
                html.append("<ol>"); in_ol = True
            html.append(f"<li>{inline(m_ol.group(2))}</li>")
            continue

        # ── Listes non-ordonnées
        if re.match(r"^[-*] ", line):
            flush_para()
            if not in_ul:
                if in_ol:
                    html.append("</ol>"); in_ol = False
                html.append("<ul>"); in_ul = True
            html.append(f"<li>{inline(line[2:])}</li>")
            continue
        else:
            close_list()

        # ── Titres
        m_h = re.match(r"^(#{1,4}) (.+)", line)
        if m_h:
            flush_para()
            lvl  = len(m_h.group(1))
            text = m_h.group(2)
            # Ancre ID basée sur le texte
            anchor = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            html.append(f'<h{lvl} id="{anchor}">{inline(text)}</h{lvl}>')
            continue

        # ── Séparateurs
        if re.match(r"^---+$", line.strip()):
            flush_para()
            html.append("<hr>")
            continue

        # ── Lignes vides → flush paragraphe
        if not line.strip():
            flush_para()
            continue

        # ── Accumulation paragraphe
        para_buf.append(line)

    # Flush final
    flush_para()
    close_list()
    close_blockq()
    close_table()

    return "\n".join(html)


body_html = md_to_html(md_content)

# ── Injection des graphiques sous chaque section de valeur ─────────────────────
# Les graphiques sont nommés d'après le ticker EOD (ex: PLTR_US.png → stem = PLTR_US)
# On insère l'image après le h3 correspondant
def inject_charts(html_str: str) -> str:
    if not charts_b64:
        return html_str
    for stem, b64 in charts_b64.items():
        ticker_raw = stem.replace("_", ".").upper()
        # Cherche un <h3> contenant le nom ou ticker
        pattern = re.compile(
            rf'(<h3[^>]*>[^<]*{re.escape(stem.split("_")[0])}[^<]*</h3>)',
            re.IGNORECASE,
        )
        img_tag = (
            f'<div class="chart-wrap">'
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="Graphique {ticker_raw}" loading="lazy" '
            f'class="chart-img">'
            f'</div>'
        )
        html_str, n = pattern.subn(rf"\1\n{img_tag}", html_str, count=1)
        if n == 0 and b64:
            # Ajout en fin de body si non trouvé
            html_str += f"\n{img_tag}"
    return html_str


body_html = inject_charts(body_html)

# ── Extraction KPI globaux ──────────────────────────────────────────────────────
def extract_kpi(md: str) -> dict:
    kpi = {"pnl_net": "N/D", "pnl_pct": "N/D", "valeur_marche": "N/D", "nb_actifs": "6"}
    # PnL net estimé
    m = re.search(r"PnL net estim[ée][^\d]*([+-]?\d[\d\s,.]+)\s*€[^\d]*([+-]?\d[\d,.]+)\s*%", md)
    if m:
        kpi["pnl_net"] = m.group(1).strip().replace(" ", "")
        kpi["pnl_pct"] = m.group(2).strip()
    # Valeur de marché totale
    m2 = re.search(r"Valeur[^\d]*march[ée][^\d]*([\d\s,.]+)\s*€", md, re.IGNORECASE)
    if m2:
        kpi["valeur_marche"] = m2.group(1).strip().replace(" ", "")
    return kpi


kpi = extract_kpi(md_content)
pnl_sign_class = "kpi-positive" if not kpi["pnl_net"].startswith("-") else "kpi-negative"
pnl_display    = (
    f"+{kpi['pnl_net']} €" if kpi["pnl_net"] not in ("N/D", "")
    and not kpi["pnl_net"].startswith("-")
    else f"{kpi['pnl_net']} €"
)

# ── Archive JSON ────────────────────────────────────────────────────────────────
Path("docs").mkdir(exist_ok=True)
archive = []
if ARCHIVE_PATH.exists():
    try:
        archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        archive = []

pnl_for_archive = f"{kpi['pnl_net']} € ({kpi['pnl_pct']}%)"
safe_date       = report_date.replace("/", "-").replace(" ", "_").replace(":", "h")

archive = [e for e in archive if e.get("date") != report_date]
archive.insert(0, {"date": report_date, "pnl": pnl_for_archive})
archive = archive[:30]
ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# CSS  (hors f-string → accolades normales)
# ══════════════════════════════════════════════════════════════════════════════

CSS = """
:root {
  --bg:          #0f1117;
  --surface:     #161b27;
  --surface-2:   #1d2336;
  --border:      #252d42;
  --text:        #e2e8f0;
  --muted:       #8892a4;
  --faint:       #3d4a60;
  --accent:      #4f98a3;
  --accent-dim:  rgba(79,152,163,.15);
  --green:       #10b981;
  --green-dim:   rgba(16,185,129,.15);
  --red:         #ef4444;
  --red-dim:     rgba(239,68,68,.15);
  --yellow:      #f59e0b;
  --orange:      #f97316;
  --blue:        #60a5fa;
  --radius:      10px;
  --shadow:      0 4px 20px rgba(0,0,0,.3);
  --font-body:   'Inter', system-ui, sans-serif;
  --font-mono:   'JetBrains Mono', 'Fira Code', monospace;
}
[data-theme="light"] {
  --bg:          #f7f6f2;
  --surface:     #ffffff;
  --surface-2:   #f1f0ec;
  --border:      #dcd9d5;
  --text:        #1e293b;
  --muted:       #64748b;
  --faint:       #cbd5e1;
  --accent:      #01696f;
  --accent-dim:  rgba(1,105,111,.1);
  --green-dim:   rgba(16,185,129,.1);
  --red-dim:     rgba(239,68,68,.1);
  --shadow:      0 4px 20px rgba(0,0,0,.08);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; scroll-padding-top: 72px; }
body {
  font-family: var(--font-body);
  background: var(--bg);
  color: var(--text);
  line-height: 1.7;
  font-size: 15px;
  min-height: 100dvh;
  -webkit-font-smoothing: antialiased;
}
/* ── Header ── */
header {
  position: sticky; top: 0; z-index: 100;
  background: color-mix(in oklab, var(--bg) 85%, transparent);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  padding: 13px 24px;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
.logo { font-size: 15px; font-weight: 700; letter-spacing: -.3px; color: var(--text); }
.logo span { color: var(--accent); }
.header-meta { font-size: 11px; color: var(--muted); font-family: var(--font-mono); }
.header-actions { display: flex; gap: 8px; align-items: center; }
.btn-icon {
  background: var(--surface-2); border: 1px solid var(--border);
  color: var(--text); border-radius: 8px; padding: 6px 11px;
  font-size: 13px; cursor: pointer;
  transition: background .18s, border-color .18s;
}
.btn-icon:hover { background: var(--border); }
/* ── Layout ── */
.container { max-width: 960px; margin: 0 auto; padding: 28px 20px 80px; }
/* ── KPI bar ── */
.kpi-bar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px; margin-bottom: 32px;
}
.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 18px;
}
.kpi-card .kpi-val {
  font-size: 1.5rem; font-weight: 700; font-family: var(--font-mono);
  letter-spacing: -.5px; line-height: 1.1;
}
.kpi-card .kpi-lbl { font-size: .72rem; color: var(--muted); margin-top: 4px; text-transform: uppercase; letter-spacing: .5px; }
.kpi-positive { color: var(--green); }
.kpi-negative { color: var(--red); }
.kpi-neutral  { color: var(--accent); }
/* ── Update badge ── */
.update-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px; font-size: .78rem;
  color: var(--muted); margin-bottom: 20px;
}
.update-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green); box-shadow: 0 0 6px var(--green);
  animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
/* ── Typographie ── */
h1 { font-size: clamp(1.4rem,3vw,2rem); font-weight: 700; line-height: 1.2; margin-bottom: 6px; letter-spacing: -.5px; }
h2 { font-size: 1.1rem; font-weight: 700; margin: 36px 0 14px; padding-bottom: 8px; border-bottom: 1px solid var(--border); color: var(--text); }
h3 { font-size: 1rem; font-weight: 700; margin: 24px 0 10px; color: var(--text); }
h4 { font-size: .88rem; font-weight: 600; margin: 14px 0 6px; color: var(--muted); }
p  { color: var(--muted); margin-bottom: 8px; max-width: 72ch; }
hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
strong { color: var(--text); font-weight: 600; }
em     { color: var(--muted); font-style: normal; }
code {
  font-family: var(--font-mono); font-size: .82em;
  background: var(--surface-2); border: 1px solid var(--border);
  padding: 1px 5px; border-radius: 4px; color: var(--accent);
}
pre {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px; overflow-x: auto;
  margin: 12px 0;
}
pre code { background: none; border: none; padding: 0; font-size: .83rem; }
blockquote {
  border-left: 3px solid var(--accent);
  background: var(--accent-dim);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 10px 16px; margin: 12px 0;
}
blockquote p { color: var(--text); margin: 0; }
ul, ol { padding-left: 18px; margin-bottom: 10px; }
li { color: var(--muted); font-size: .9rem; padding: 2px 0; }
li::marker { color: var(--faint); }
/* ── Tables ── */
.table-wrap {
  overflow-x: auto; margin: 14px 0;
  border-radius: var(--radius); border: 1px solid var(--border);
  box-shadow: var(--shadow);
}
table { width: 100%; border-collapse: collapse; font-size: .86rem; }
thead { position: sticky; top: 0; }
th {
  background: var(--surface-2); color: var(--muted); font-weight: 600;
  font-size: .74rem; text-transform: uppercase; letter-spacing: .5px;
  padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
td {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--accent-dim); transition: background .15s; }
/* Colorisation PnL */
td.cell-pos { color: var(--green); font-weight: 600; font-family: var(--font-mono); }
td.cell-neg { color: var(--red);   font-weight: 600; font-family: var(--font-mono); }
td.cell-num { font-family: var(--font-mono); }
/* ── Badges ── */
.badge {
  display: inline-flex; align-items: center; gap: 4px; font-size: .75rem;
  font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap;
}
.buy-strong { background: var(--green-dim); color: #10b981; border: 1px solid rgba(16,185,129,.35); }
.buy-mod    { background: var(--accent-dim); color: var(--accent); border: 1px solid rgba(79,152,163,.35); }
.hold       { background: rgba(245,158,11,.12); color: #f59e0b; border: 1px solid rgba(245,158,11,.3); }
.avoid      { background: rgba(249,115,22,.12); color: #fb923c; border: 1px solid rgba(249,115,22,.3); }
.sell       { background: var(--red-dim); color: #f87171; border: 1px solid rgba(239,68,68,.3); }
.up { color: var(--green); font-weight: 600; }
.dn { color: var(--red);   font-weight: 600; }
/* ── Graphiques ── */
.chart-wrap {
  margin: 14px 0 24px;
  border-radius: var(--radius); overflow: hidden;
  border: 1px solid var(--border); box-shadow: var(--shadow);
}
.chart-img { width: 100%; display: block; max-height: 280px; object-fit: cover; }
/* ── Archive ── */
.archive-toggle {
  font-size: .8rem; color: var(--accent); cursor: pointer;
  background: none; border: none; padding: 0;
  text-decoration: underline; margin-bottom: 14px; display: block;
}
#archive-panel {
  display: none; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px; margin-bottom: 20px;
}
#archive-panel.open { display: block; }
#archive-list { list-style: none; padding: 0; }
#archive-list li {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 0; border-bottom: 1px solid var(--border); font-size: .82rem;
}
#archive-list li:last-child { border: none; }
.archive-date { color: var(--text); font-family: var(--font-mono); font-size: .78rem; }
.archive-pnl  { color: var(--muted); }
/* ── Impression ── */
@media print {
  header, .header-actions, .archive-toggle, #archive-panel,
  .update-badge, .kpi-bar { display: none !important; }
  body { background: #fff; color: #000; font-size: 13px; }
  .badge { border: 1px solid #ccc; color: #000 !important; background: none !important; }
  .table-wrap { box-shadow: none; border: 1px solid #ccc; }
  .chart-img { max-height: none; }
}
/* ── Mobile ── */
@media (max-width: 640px) {
  header { padding: 10px 14px; }
  .container { padding: 18px 14px 60px; }
  h1 { font-size: 1.3rem; }
  h2 { font-size: 1rem; }
  td, th { padding: 8px 10px; font-size: .78rem; }
  .kpi-card .kpi-val { font-size: 1.25rem; }
}
"""

# ══════════════════════════════════════════════════════════════════════════════
# JAVASCRIPT  (hors f-string)
# ══════════════════════════════════════════════════════════════════════════════

JS = r"""
// ── Thème clair / sombre ───────────────────────────────────────
(function () {
  var root = document.documentElement;
  var btn  = document.querySelector('[data-theme-toggle]');
  function safeGet(k) { try { return localStorage.getItem(k); } catch(e) { return null; } }
  function safeSet(k, v) { try { localStorage.setItem(k, v); } catch(e) {} }
  var theme = safeGet('theme') ||
    (window.matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');
  root.setAttribute('data-theme', theme);
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  if (btn) btn.addEventListener('click', function () {
    theme = theme === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', theme);
    safeSet('theme', theme);
    btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  });
})();

// ── Colorisation PnL dans les cellules de tableau ─────────────
document.querySelectorAll('td').forEach(function (td) {
  var t = td.textContent.trim();
  var isNum = /^[+-]?\d/.test(t);
  if (!isNum) return;
  if ((t.includes('€') || t.includes('%')) && t.startsWith('+')) {
    td.classList.add('cell-pos');
  } else if ((t.includes('€') || t.includes('%')) && t.startsWith('-')) {
    td.classList.add('cell-neg');
  } else if (/^\d[\d\s,.]*[€%]/.test(t)) {
    td.classList.add('cell-num');
  }
});

// ── Compteur animé pour les KPI ───────────────────────────────
function animateCounter(el) {
  var raw = el.getAttribute('data-val');
  if (!raw) return;
  var num = parseFloat(raw.replace(',', '.').replace(/\s/g, ''));
  if (isNaN(num)) return;
  var suffix = el.getAttribute('data-suffix') || '';
  var prefix = el.getAttribute('data-prefix') || '';
  var dec    = (raw.includes('.') || raw.includes(',')) ? 2 : 0;
  var start  = 0; var duration = 900; var startTime = null;
  function step(ts) {
    if (!startTime) startTime = ts;
    var progress = Math.min((ts - startTime) / duration, 1);
    var ease     = 1 - Math.pow(1 - progress, 3);
    var current  = start + (num - start) * ease;
    el.textContent = prefix + current.toFixed(dec).replace('.', ',') + suffix;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
document.querySelectorAll('[data-counter]').forEach(animateCounter);

// ── Archive ──────────────────────────────────────────────────
function toggleArchive() {
  var panel = document.getElementById('archive-panel');
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) loadArchive();
}
function loadArchive() {
  fetch('./archive.json').then(function (r) { return r.json(); }).then(function (data) {
    var ul = document.getElementById('archive-list');
    ul.innerHTML = data.map(function (e) {
      return '<li><span class="archive-date">📅 ' + e.date + '</span>' +
             '<span class="archive-pnl">' + (e.pnl || '') + '</span></li>';
    }).join('');
  }).catch(function () {
    document.getElementById('archive-list').innerHTML =
      '<li><span style="color:var(--faint)">Historique non disponible.</span></li>';
  });
}
"""

# ══════════════════════════════════════════════════════════════════════════════
# ASSEMBLAGE HTML  (f-string minimal : seulement les valeurs dynamiques)
# ══════════════════════════════════════════════════════════════════════════════

pnl_class   = pnl_sign_class
vm_display  = f"{kpi['valeur_marche']} €" if kpi["valeur_marche"] != "N/D" else "N/D"
pct_display = f"{kpi['pnl_pct']} %" if kpi["pnl_pct"] != "N/D" else "N/D"
pnl_raw_val = kpi["pnl_net"].replace("+", "").replace("-", "").replace("€", "").replace(" ", "")
pct_raw_val = kpi["pnl_pct"].replace("+", "").replace("-", "").replace("%", "").replace(" ", "")

html_out = (
    "<!DOCTYPE html>\n"
    '<html lang="fr" data-theme="dark">\n'
    "<head>\n"
    '  <meta charset="UTF-8">\n'
    '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    f'  <title>Rapport Portfolio — {report_date}</title>\n'
    '  <link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700'
    '&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">\n'
    f"  <style>\n{CSS}\n  </style>\n"
    "</head>\n"
    "<body>\n"
    "\n"
    "  <!-- HEADER -->\n"
    "  <header>\n"
    '    <div style="display:flex;align-items:center;gap:12px">\n'
    '      <div class="logo">📊 <span>Portfolio</span> Analyzer</div>\n'
    f'      <div class="header-meta">v5.1 · {report_date}</div>\n'
    "    </div>\n"
    '    <div class="header-actions">\n'
    '      <button class="btn-icon" onclick="window.print()" title="Imprimer / PDF">🖨️</button>\n'
    '      <button class="btn-icon" data-theme-toggle aria-label="Changer de thème">☀️</button>\n'
    "    </div>\n"
    "  </header>\n"
    "\n"
    '  <div class="container">\n'
    "\n"
    "    <!-- BADGE MAJ -->\n"
    '    <div class="update-badge">\n'
    '      <span class="update-dot"></span>\n'
    f"      Dernière mise à jour : <strong>{report_date}</strong>\n"
    "    </div>\n"
    "\n"
    "    <!-- KPI BAR -->\n"
    '    <div class="kpi-bar">\n'
    '      <div class="kpi-card">\n'
    f'        <div class="kpi-val {pnl_class}" data-counter data-val="{pnl_raw_val}" '
    f'data-suffix=" €" data-prefix="{"+" if pnl_class == "kpi-positive" else "-"}">'
    f'{pnl_display}</div>\n'
    '        <div class="kpi-lbl">PnL net estimé</div>\n'
    "      </div>\n"
    '      <div class="kpi-card">\n'
    f'        <div class="kpi-val {pnl_class}" data-counter data-val="{pct_raw_val}" '
    f'data-suffix=" %" data-prefix="{"+" if pnl_class == "kpi-positive" else "-"}">'
    f'{pct_display}</div>\n'
    '        <div class="kpi-lbl">Performance nette</div>\n'
    "      </div>\n"
    '      <div class="kpi-card">\n'
    f'        <div class="kpi-val kpi-neutral">{vm_display}</div>\n'
    '        <div class="kpi-lbl">Valeur de marché</div>\n'
    "      </div>\n"
    '      <div class="kpi-card">\n'
    '        <div class="kpi-val kpi-neutral">6</div>\n'
    '        <div class="kpi-lbl">Positions actives</div>\n'
    "      </div>\n"
    "    </div>\n"
    "\n"
    "    <!-- ARCHIVE -->\n"
    '    <button class="archive-toggle" onclick="toggleArchive()">📂 Historique des rapports</button>\n'
    '    <div id="archive-panel">\n'
    '      <strong style="font-size:.82rem;">30 derniers rapports</strong>\n'
    '      <ul id="archive-list">\n'
    '        <li><span style="color:var(--faint);font-size:.78rem">Chargement…</span></li>\n'
    "      </ul>\n"
    "    </div>\n"
    "\n"
    "    <!-- CORPS DU RAPPORT -->\n"
    '    <div id="report-body">\n'
    f"{body_html}\n"
    "    </div>\n"
    "\n"
    "  </div><!-- .container -->\n"
    "\n"
    f"  <script>\n{JS}\n  </script>\n"
    "</body>\n"
    "</html>\n"
)

# ── Écriture ───────────────────────────────────────────────────────────────────
Path("docs").mkdir(exist_ok=True)
HTML_PATH.write_text(html_out, encoding="utf-8")

size_kb = HTML_PATH.stat().st_size // 1024
print(f"✅ docs/index.html généré ({size_kb} Ko, {len(charts_b64)} graphique(s) intégré(s))")
print(f"✅ docs/archive.json mis à jour ({len(archive)} entrée(s))")
sys.exit(0)
