"""Converts reports/daily_report.md into a styled docs/index.html for GitHub Pages."""
import os
import markdown
from datetime import datetime
import pytz

os.makedirs("docs", exist_ok=True)

# Read markdown report
try:
    with open("reports/daily_report.md", "r", encoding="utf-8") as f:
        md_content = f.read()
except FileNotFoundError:
    md_content = "# Rapport non disponible\n\nLe rapport sera g\u00e9n\u00e9r\u00e9 lors de la prochaine ex\u00e9cution quotidienne."

# Convert to HTML
body_html = markdown.markdown(md_content, extensions=["tables", "nl2br"])

paris_tz = pytz.timezone("Europe/Paris")
now = datetime.now(paris_tz).strftime("%d/%m/%Y \u00e0 %H:%M")

html = f"""<!DOCTYPE html>
<html lang="fr" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Portfolio Report</title>
  <style>
    :root {{
      --bg: #0d1117;
      --surface: #161b22;
      --surface2: #21262d;
      --border: #30363d;
      --text: #e6edf3;
      --muted: #8b949e;
      --green: #3fb950;
      --red: #f85149;
      --yellow: #d29922;
      --blue: #58a6ff;
      --accent: #1f6feb;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 15px;
      line-height: 1.6;
      padding: 0 1rem 4rem;
    }}
    .header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 1rem 2rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .header svg {{ flex-shrink: 0; }}
    .header-title {{ font-size: 1rem; font-weight: 600; color: var(--text); }}
    .header-sub {{ font-size: 0.8rem; color: var(--muted); margin-left: auto; }}
    .container {{
      max-width: 900px;
      margin: 2rem auto;
    }}
    h1 {{
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--text);
      margin: 2rem 0 0.5rem;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid var(--border);
    }}
    h2 {{
      font-size: 1.15rem;
      font-weight: 600;
      color: var(--blue);
      margin: 2rem 0 0.75rem;
    }}
    h3 {{
      font-size: 1rem;
      font-weight: 600;
      color: var(--text);
      margin: 2rem 0 0.75rem;
      background: var(--surface);
      padding: 0.6rem 1rem;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    p {{
      margin: 0.5rem 0;
      color: var(--text);
    }}
    blockquote {{
      border-left: 3px solid var(--accent);
      margin: 0.75rem 0;
      padding: 0.5rem 1rem;
      background: var(--surface);
      border-radius: 0 6px 6px 0;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0;
      font-size: 0.875rem;
      background: var(--surface);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    th {{
      background: var(--surface2);
      color: var(--muted);
      font-weight: 600;
      text-align: left;
      padding: 0.6rem 0.9rem;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid var(--border);
    }}
    td {{
      padding: 0.6rem 0.9rem;
      border-bottom: 1px solid var(--border);
      color: var(--text);
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: var(--surface2); }}
    /* Color positive/negative values */
    td:last-child {{ font-weight: 500; }}
    strong {{ color: var(--text); font-weight: 600; }}
    em {{ color: var(--muted); font-size: 0.8rem; }}
    hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 1.5rem 0;
    }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .footer {{
      text-align: center;
      color: var(--muted);
      font-size: 0.78rem;
      margin-top: 3rem;
      padding-top: 1rem;
      border-top: 1px solid var(--border);
    }}
  </style>
</head>
<body>

<div class="header">
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#58a6ff" stroke-width="2">
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
  </svg>
  <span class="header-title">Portfolio Analyzer</span>
  <span class="header-sub">Page mise \u00e0 jour automatiquement chaque jour \u00e0 16h</span>
</div>

<div class="container">
{body_html}
<div class="footer">
  Page g\u00e9n\u00e9r\u00e9e le {now} &mdash; 
  <a href="https://github.com/adrien13vivier-hub/portfolio-analyzer" target="_blank">Voir le repo GitHub</a>
</div>
</div>

</body>
</html>
"""

with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("[OK] docs/index.html generated.")
