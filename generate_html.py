#!/usr/bin/env python3
"""
generate_html.py
Convertit reports/daily_report.md → docs/index.html (page Cloudflare Pages).
Met aussi à jour docs/archive.json pour l'historique des rapports.
"""
import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MD_PATH      = Path("reports/daily_report.md")
HTML_PATH    = Path("docs/index.html")
ARCHIVE_PATH = Path("docs/archive.json")

# ── Lecture du Markdown ────────────────────────────────────────────────────────
if not MD_PATH.exists():
    print("[WARN] reports/daily_report.md introuvable — page vide générée.")
    md_content = "# Rapport indisponible\n\nAucun rapport généré ce jour."
else:
    md_content = MD_PATH.read_text(encoding="utf-8")

# ── Conversion Markdown → HTML (sans dépendance externe) ──────────────────────
def md_to_html(md: str) -> str:
    lines = md.split("\n")
    html  = []
    in_table = False
    in_ul    = False
    table_header_done = False

    for raw in lines:
        line = raw

        # Tables Markdown
        if re.match(r'^\|', line):
            if not in_table:
                html.append('<div class="table-wrap"><table>')
                in_table = True
                table_header_done = False
            if re.match(r'^\|[-| :]+\|', line):  # séparateur
                table_header_done = True
                continue
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            tag   = 'th' if not table_header_done else 'td'
            row   = ''.join(f'<{tag}>{inline(c)}</{tag}>' for c in cells)
            html.append(f'<tr>{row}</tr>')
            continue
        else:
            if in_table:
                html.append('</table></div>')
                in_table = False
                table_header_done = False

        # Listes
        if re.match(r'^- ', line):
            if not in_ul:
                html.append('<ul>')
                in_ul = True
            html.append(f'<li>{inline(line[2:])}</li>')
            continue
        else:
            if in_ul:
                html.append('</ul>')
                in_ul = False

        # Titres
        m = re.match(r'^(#{1,4}) (.+)', line)
        if m:
            level = len(m.group(1))
            html.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            continue

        # Séparateurs
        if re.match(r'^---+$', line.strip()):
            html.append('<hr>')
            continue

        # Lignes vides
        if not line.strip():
            html.append('')
            continue

        # Paragraphe
        html.append(f'<p>{inline(line)}</p>')

    if in_table: html.append('</table></div>')
    if in_ul:    html.append('</ul>')
    return '\n'.join(html)


def inline(text: str) -> str:
    """Applique le formatage inline Markdown : gras, italique, code, liens."""
    # Badges emoji recommendation → spans colorés
    text = re.sub(r'🟢 ACHAT FORT',     '<span class="badge buy-strong">🟢 ACHAT FORT</span>',     text)
    text = re.sub(r'🔵 ACHAT MODÉRÉ',   '<span class="badge buy-mod">🔵 ACHAT MODÉRÉ</span>',     text)
    text = re.sub(r'🟡 GARDER',         '<span class="badge hold">🟡 GARDER</span>',               text)
    text = re.sub(r'🟠 À ÉVITER',       '<span class="badge avoid">🟠 À ÉVITER</span>',            text)
    text = re.sub(r'🔴 VENDRE',         '<span class="badge sell">🔴 VENDRE</span>',               text)
    # Gras + italique
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<strong>\1</strong>',          text)
    text = re.sub(r'\*(.+?)\*',         r'<em>\1</em>',                  text)
    text = re.sub(r'_(.+?)_',           r'<em>\1</em>',                  text)
    # Code inline
    text = re.sub(r'`([^`]+)`',         r'<code>\1</code>',              text)
    # Liens Markdown
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
    # Flèches unicode → spans
    text = text.replace('▲', '<span class="up">▲</span>')
    text = text.replace('▼', '<span class="dn">▼</span>')
    return text


body_html = md_to_html(md_content)

# ── Extraction de la date du rapport depuis le contenu ────────────────────────
date_match = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2})', md_content)
report_date = date_match.group(1) if date_match else datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')

# ── Mise à jour de l'archive JSON ─────────────────────────────────────────────
docs_dir = Path("docs")
docs_dir.mkdir(exist_ok=True)

archive = []
if ARCHIVE_PATH.exists():
    try:
        archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        archive = []

# Extrait PnL global depuis le markdown pour l'archive
pnl_match = re.search(r'PnL net estimé.*?([+-]\d+[.,]\d+)\s*€.*?([+-]\d+[.,]\d+)%', md_content)
pnl_str = f"{pnl_match.group(1)} € ({pnl_match.group(2)}%)" if pnl_match else "N/D"

new_entry = {
    "date":     report_date,
    "filename": f"archive/report_{report_date.replace('/', '-').replace(' ', '_').replace(':', 'h')}.md",
    "pnl":      pnl_str,
}
# Évite les doublons sur la même date
archive = [e for e in archive if e["date"] != report_date]
archive.insert(0, new_entry)
archive = archive[:30]  # Garde les 30 derniers
ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

# ── Template HTML complet ──────────────────────────────────────────────────────
html_template = f"""<!DOCTYPE html>
<html lang="fr" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rapport Portfolio — {report_date}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:          #0f1117;
      --surface:     #161b27;
      --surface-2:   #1e2535;
      --border:      #2a3347;
      --text:        #e2e8f0;
      --muted:       #8892a4;
      --faint:       #4a5568;
      --accent:      #3b82f6;
      --accent-glow: rgba(59,130,246,0.15);
      --green:       #10b981;
      --red:         #ef4444;
      --yellow:      #f59e0b;
      --orange:      #f97316;
      --radius:      10px;
      --font-body:   'Inter', sans-serif;
      --font-mono:   'JetBrains Mono', monospace;
    }}
    [data-theme="light"] {{
      --bg:          #f8fafc;
      --surface:     #ffffff;
      --surface-2:   #f1f5f9;
      --border:      #e2e8f0;
      --text:        #1e293b;
      --muted:       #64748b;
      --faint:       #cbd5e1;
      --accent-glow: rgba(59,130,246,0.08);
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: var(--font-body);
      background: var(--bg);
      color: var(--text);
      line-height: 1.7;
      font-size: 15px;
      min-height: 100dvh;
    }}
    /* ── HEADER ── */
    header {{
      position: sticky; top: 0; z-index: 100;
      background: rgba(15,17,23,0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px;
    }}
    [data-theme="light"] header {{ background: rgba(248,250,252,0.9); }}
    .logo {{ font-size: 15px; font-weight: 700; letter-spacing: -.3px; color: var(--text); }}
    .logo span {{ color: var(--accent); }}
    .header-meta {{ font-size: 12px; color: var(--muted); font-family: var(--font-mono); }}
    .header-actions {{ display: flex; gap: 8px; align-items: center; }}
    .btn-icon {{
      background: var(--surface-2); border: 1px solid var(--border);
      color: var(--text); border-radius: 8px; padding: 6px 10px;
      font-size: 13px; cursor: pointer; transition: all .18s;
    }}
    .btn-icon:hover {{ background: var(--border); }}
    /* ── LAYOUT ── */
    .container {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 80px; }}
    /* ── TYPOGRAPHY ── */
    h1 {{ font-size: clamp(1.4rem,3vw,2rem); font-weight: 700; line-height: 1.2;
          margin-bottom: 8px; letter-spacing: -.5px; }}
    h2 {{ font-size: 1.2rem; font-weight: 700; margin: 40px 0 16px;
          padding-bottom: 8px; border-bottom: 1px solid var(--border);
          color: var(--text); }}
    h3 {{ font-size: 1rem; font-weight: 700; margin: 28px 0 12px; color: var(--text); }}
    h4 {{ font-size: .9rem; font-weight: 600; margin: 16px 0 8px; color: var(--muted); }}
    p  {{ color: var(--muted); margin-bottom: 10px; max-width: 72ch; }}
    hr {{ border: none; border-top: 1px solid var(--border); margin: 32px 0; }}
    strong {{ color: var(--text); font-weight: 600; }}
    em     {{ color: var(--muted); font-style: normal; }}
    code   {{ font-family: var(--font-mono); font-size: .82em;
               background: var(--surface-2); border: 1px solid var(--border);
               padding: 1px 5px; border-radius: 4px; color: var(--accent); }}
    ul {{ list-style: none; padding: 0; margin-bottom: 12px; }}
    li {{ padding: 4px 0 4px 16px; color: var(--muted); font-size: .9rem;
           position: relative; }}
    li::before {{ content: '·'; position: absolute; left: 4px; color: var(--faint); }}
    /* ── TABLES ── */
    .table-wrap {{ overflow-x: auto; margin: 16px 0; border-radius: var(--radius);
                   border: 1px solid var(--border); }}
    table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
    th {{ background: var(--surface-2); color: var(--muted);
           font-weight: 600; font-size: .78rem; text-transform: uppercase;
           letter-spacing: .5px; padding: 10px 14px; text-align: left;
           border-bottom: 1px solid var(--border); }}
    td {{ padding: 10px 14px; border-bottom: 1px solid var(--border);
           vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: var(--accent-glow); }}
    /* ── BADGES ── */
    .badge {{ display: inline-flex; align-items: center; gap: 4px;
               font-size: .78rem; font-weight: 700; padding: 3px 10px;
               border-radius: 20px; white-space: nowrap; }}
    .buy-strong {{ background: rgba(16,185,129,.15); color: #10b981;
                   border: 1px solid rgba(16,185,129,.3); }}
    .buy-mod    {{ background: rgba(59,130,246,.15); color: #60a5fa;
                   border: 1px solid rgba(59,130,246,.3); }}
    .hold       {{ background: rgba(245,158,11,.12); color: #f59e0b;
                   border: 1px solid rgba(245,158,11,.3); }}
    .avoid      {{ background: rgba(249,115,22,.12); color: #fb923c;
                   border: 1px solid rgba(249,115,22,.3); }}
    .sell       {{ background: rgba(239,68,68,.12); color: #f87171;
                   border: 1px solid rgba(239,68,68,.3); }}
    /* ── PnL COLORS ── */
    .up {{ color: var(--green); font-weight: 600; }}
    .dn {{ color: var(--red);   font-weight: 600; }}
    /* ── ARCHIVE PANEL ── */
    .archive-toggle {{ font-size: 12px; color: var(--accent); cursor: pointer;
                        background: none; border: none; padding: 0;
                        text-decoration: underline; margin-bottom: 16px; }}
    #archive-panel {{
      display: none; background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 16px; margin-bottom: 24px;
    }}
    #archive-panel.open {{ display: block; }}
    .archive-list {{ list-style: none; padding: 0; }}
    .archive-list li {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px 0; border-bottom: 1px solid var(--border);
      font-size: .85rem;
    }}
    .archive-list li:last-child {{ border: none; }}
    .archive-date {{ color: var(--text); font-family: var(--font-mono); font-size: .8rem; }}
    .archive-pnl  {{ color: var(--muted); }}
    /* ── LAST UPDATE BADGE ── */
    .update-badge {{
      display: inline-flex; align-items: center; gap: 6px;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 20px; padding: 4px 12px; font-size: .78rem;
      color: var(--muted); margin-bottom: 24px;
    }}
    .update-dot {{
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 6px var(--green);
    }}
    /* ── PRINT ── */
    @media print {{
      header, .header-actions, .archive-toggle, #archive-panel {{ display: none; }}
      body {{ background: white; color: black; }}
      .badge {{ border: 1px solid #ccc; }}
    }}
    /* ── MOBILE ── */
    @media (max-width: 640px) {{
      header {{ padding: 10px 14px; }}
      .container {{ padding: 20px 14px 60px; }}
      h2 {{ font-size: 1.05rem; }}
      td, th {{ padding: 8px 10px; font-size: .8rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <div style="display:flex;align-items:center;gap:12px">
      <div class="logo">📊 <span>Portfolio</span> Analyzer</div>
      <div class="header-meta">v3.2 · {report_date}</div>
    </div>
    <div class="header-actions">
      <button class="btn-icon" onclick="window.print()" title="Imprimer / PDF">🖨️</button>
      <button class="btn-icon" data-theme-toggle aria-label="Changer de thème">☀️</button>
    </div>
  </header>

  <div class="container">
    <div class="update-badge">
      <span class="update-dot"></span>
      Dernière mise à jour : <strong>{report_date}</strong>
    </div>

    <button class="archive-toggle" onclick="toggleArchive()">📂 Historique des rapports</button>
    <div id="archive-panel">
      <strong style="font-size:.85rem;">30 derniers rapports</strong>
      <ul class="archive-list" id="archive-list">
        <li><span style="color:var(--faint);font-size:.8rem">Chargement…</span></li>
      </ul>
    </div>

    <div id="report-body">
{body_html}
    </div>
  </div>

  <script>
    // ── Thème clair/sombre ──
    const root = document.documentElement;
    const btn  = document.querySelector('[data-theme-toggle]');
    let theme  = localStorage.getItem('theme') ||
                 (matchMedia('(prefers-color-scheme:light)').matches ? 'light' : 'dark');
    root.setAttribute('data-theme', theme);
    btn.textContent = theme === 'dark' ? '☀️' : '🌙';
    btn.addEventListener('click', () => {{
      theme = theme === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', theme);
      localStorage.setItem('theme', theme);
      btn.textContent = theme === 'dark' ? '☀️' : '🌙';
    }});

    // ── Colorisation des valeurs PnL dans les cellules ──
    document.querySelectorAll('td').forEach(td => {{
      const t = td.textContent.trim();
      if (/^[+]\d/.test(t) && t.includes('€')) td.style.color = 'var(--green)';
      if (/^[-]\d/.test(t) && t.includes('€')) td.style.color = 'var(--red)';
      if (/^[+]\d/.test(t) && t.includes('%')) td.style.color = 'var(--green)';
      if (/^[-]\d/.test(t) && t.includes('%')) td.style.color = 'var(--red)';
    }});

    // ── Archive ──
    function toggleArchive() {{
      const panel = document.getElementById('archive-panel');
      panel.classList.toggle('open');
      if (panel.classList.contains('open')) loadArchive();
    }}
    async function loadArchive() {{
      try {{
        const r = await fetch('./archive.json');
        const data = await r.json();
        const ul = document.getElementById('archive-list');
        ul.innerHTML = data.map(e =>
          `<li>
            <span class="archive-date">📅 ${{e.date}}</span>
            <span class="archive-pnl">${{e.pnl}}</span>
          </li>`
        ).join('');
      }} catch(e) {{
        document.getElementById('archive-list').innerHTML =
          '<li><span style="color:var(--faint)">Historique non disponible.</span></li>';
      }}
    }}
  </script>
</body>
</html>
"""

HTML_PATH.write_text(html_template, encoding="utf-8")
print(f"✅ docs/index.html généré ({HTML_PATH.stat().st_size // 1024} Ko)")
print(f"✅ docs/archive.json mis à jour ({len(archive)} entrées)")
