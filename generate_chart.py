#!/usr/bin/env python3
"""
Génère docs/chart.html — graphique mensuel de l'évolution du PnL
à partir de reports/history.csv.
Appelé par le workflow après portfolio_analyzer.py.
"""
import csv
import os
import json
from datetime import datetime, date
from zoneinfo import ZoneInfo

HISTORY_PATH = "reports/history.csv"
OUT_PATH     = "docs/chart.html"
PARIS_TZ     = ZoneInfo("Europe/Paris")

def read_history():
    if not os.path.isfile(HISTORY_PATH):
        return []
    rows = []
    with open(HISTORY_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "date":        row["date"],
                    "time":        row["time"],
                    "ticker":      row["ticker"],
                    "name":        row["name"],
                    "pnl_net":     float(row["pnl_net"]),
                    "pnl_net_pct": float(row["pnl_net_pct"]),
                    "score":       float(row["score"]),
                    "rec":         row["rec"],
                })
            except Exception:
                continue
    return rows

def build_chart_html(rows):
    now = datetime.now(PARIS_TZ)

    # Agrège par date+heure : somme PnL net global
    sessions: dict = {}
    for r in rows:
        key = f"{r['date']} {r['time']}"
        sessions.setdefault(key, {"date": r["date"], "time": r["time"], "pnl_net": 0.0})
        sessions[key]["pnl_net"] += r["pnl_net"]

    sorted_sessions = sorted(sessions.values(), key=lambda x: (x["date"], x["time"]))

    # Garde les 60 dernières sessions (≈ 30 jours × 2 runs)
    recent = sorted_sessions[-60:]

    labels    = [f"{s['date']} {s['time']}" for s in recent]
    pnl_data  = [round(s["pnl_net"], 2) for s in recent]
    colors    = ["rgba(34,197,94,0.8)" if v >= 0 else "rgba(239,68,68,0.8)" for v in pnl_data]

    # PnL par valeur sur le dernier run
    if rows:
        last_date = max(r["date"] for r in rows)
        last_time = max(r["time"] for r in rows if r["date"] == last_date)
        last_rows = [r for r in rows if r["date"] == last_date and r["time"] == last_time]
    else:
        last_rows = []

    bar_labels = [r["name"] for r in last_rows]
    bar_data   = [round(r["pnl_net"], 2) for r in last_rows]
    bar_colors = ["rgba(34,197,94,0.8)" if v >= 0 else "rgba(239,68,68,0.8)" for v in bar_data]

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historique Portefeuille</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #f7f6f2; --surface: #ffffff; --text: #1a1a1a;
    --muted: #666; --border: #e0ddd8; --green: #16a34a; --red: #dc2626;
  }}
  [data-theme=dark] {{
    --bg: #171614; --surface: #1c1b19; --text: #cdccca;
    --muted: #888; --border: #393836; --green: #4ade80; --red: #f87171;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif;
          font-size: 15px; padding: 24px; }}
  h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-radius: 12px; padding: 20px; }}
  .card h2 {{ font-size: 15px; font-weight: 600; margin-bottom: 16px; color: var(--muted); }}
  canvas {{ max-height: 320px; }}
  .toggle {{ position: fixed; top: 16px; right: 16px; background: var(--surface);
             border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px;
             cursor: pointer; font-size: 13px; color: var(--text); }}
  .back {{ display: inline-block; margin-bottom: 16px; color: var(--muted);
           text-decoration: none; font-size: 13px; }}
  .back:hover {{ color: var(--text); }}
</style>
</head>
<body>
<button class="toggle" data-theme-toggle onclick="toggleTheme()">🌙 Sombre</button>
<a class="back" href="index.html">← Retour au rapport</a>
<h1>📈 Historique du Portefeuille</h1>
<p class="meta">Mis à jour le {now.strftime('%d/%m/%Y à %H:%M')} · {len(recent)} sessions · 30 derniers jours</p>

<div class="grid">
  <div class="card">
    <h2>PnL NET GLOBAL — 30 derniers jours (€)</h2>
    <canvas id="lineChart"></canvas>
  </div>
  <div class="card">
    <h2>PnL NET PAR VALEUR — dernier run</h2>
    <canvas id="barChart"></canvas>
  </div>
</div>

<script>
const labels   = {json.dumps(labels, ensure_ascii=False)};
const pnlData  = {json.dumps(pnl_data)};
const colors   = {json.dumps(colors)};
const bLabels  = {json.dumps(bar_labels, ensure_ascii=False)};
const bData    = {json.dumps(bar_data)};
const bColors  = {json.dumps(bar_colors)};

const isDark = () => document.documentElement.getAttribute('data-theme') === 'dark';
const gridColor = () => isDark() ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.07)';
const tickColor = () => isDark() ? '#888' : '#666';

function chartDefaults() {{
  return {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: tickColor(), maxTicksLimit: 8, font: {{ size: 11 }} }},
             grid: {{ color: gridColor() }} }},
      y: {{ ticks: {{ color: tickColor(), font: {{ size: 11 }} }},
             grid: {{ color: gridColor() }}, beginAtZero: false }},
    }},
    animation: {{ duration: 400 }},
  }};
}}

const lineCtx = document.getElementById('lineChart').getContext('2d');
const lineChart = new Chart(lineCtx, {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      data: pnlData,
      borderColor: '#01696f',
      backgroundColor: 'rgba(1,105,111,0.08)',
      borderWidth: 2,
      pointRadius: 3,
      fill: true,
      tension: 0.3,
    }}],
  }},
  options: {{ ...chartDefaults(), responsive: true, maintainAspectRatio: true }},
}});

const barCtx = document.getElementById('barChart').getContext('2d');
const barChart = new Chart(barCtx, {{
  type: 'bar',
  data: {{
    labels: bLabels,
    datasets: [{{
      data: bData,
      backgroundColor: bColors,
      borderRadius: 6,
    }}],
  }},
  options: {{ ...chartDefaults(), responsive: true, maintainAspectRatio: true }},
}});

function toggleTheme() {{
  const root = document.documentElement;
  const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  document.querySelector('.toggle').textContent = next === 'dark' ? '☀️ Clair' : '🌙 Sombre';
  [lineChart, barChart].forEach(c => {{
    c.options.scales.x.ticks.color = tickColor();
    c.options.scales.x.grid.color  = gridColor();
    c.options.scales.y.ticks.color = tickColor();
    c.options.scales.y.grid.color  = gridColor();
    c.update();
  }});
}}

// Init thème système
if (window.matchMedia('(prefers-color-scheme: dark)').matches) {{
  document.documentElement.setAttribute('data-theme','dark');
  document.querySelector('.toggle').textContent = '☀️ Clair';
}}
</script>
</body>
</html>
"""
    return html


if __name__ == "__main__":
    rows = read_history()
    html = build_chart_html(rows)
    os.makedirs("docs", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Graphique généré : {OUT_PATH} ({len(rows)} entrées historique)")
