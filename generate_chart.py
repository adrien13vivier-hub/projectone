#!/usr/bin/env python3
"""
Génère docs/chart.html — graphique de l'évolution du PnL sur 1 mois
à partir de reports/history.csv.
Appelé par le workflow après portfolio_analyzer.py.
"""
import csv
import os
import json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

HISTORY_PATH = "reports/history.csv"
OUT_PATH     = "docs/chart.html"
PARIS_TZ     = ZoneInfo("Europe/Paris")
# Fenêtre stricte : 1 mois
WINDOW_DAYS  = 30

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
    now      = datetime.now(PARIS_TZ)
    cutoff   = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()

    # ── 1. Filtrer strictement sur 1 mois ────────────────────────────────────
    rows_1m = [r for r in rows if r["date"] >= cutoff]

    # ── 2. Graphique PnL global — agréger par session (date+heure) ───────────
    sessions: dict = {}
    for r in rows_1m:
        key = f"{r['date']} {r['time']}"
        sessions.setdefault(key, {"date": r["date"], "time": r["time"], "pnl_net": 0.0})
        sessions[key]["pnl_net"] += r["pnl_net"]

    sorted_sessions = sorted(sessions.values(), key=lambda x: (x["date"], x["time"]))
    labels    = [f"{s['date']} {s['time']}" for s in sorted_sessions]
    pnl_data  = [round(s["pnl_net"], 2) for s in sorted_sessions]
    colors    = ["rgba(34,197,94,0.8)" if v >= 0 else "rgba(239,68,68,0.8)" for v in pnl_data]

    # ── 3. Graphique PnL par valeur — dernier run (dans la fenêtre 1 mois) ───
    if rows_1m:
        last_date = max(r["date"] for r in rows_1m)
        last_time = max(r["time"] for r in rows_1m if r["date"] == last_date)
        last_rows = [r for r in rows_1m if r["date"] == last_date and r["time"] == last_time]
    else:
        last_rows = []

    bar_labels = [r["name"] for r in last_rows]
    bar_data   = [round(r["pnl_net"], 2) for r in last_rows]
    bar_colors = ["rgba(34,197,94,0.8)" if v >= 0 else "rgba(239,68,68,0.8)" for v in bar_data]

    # ── 4. Graphique PnL par action sur 1 mois ────────────────────────────────
    # Pour que TOUTES les actions couvrent l'intégralité de l'axe X commun,
    # on construit la liste complète des labels (toutes sessions confondues)
    # et on remplit chaque action sur tous les points (null si absent).
    all_labels = labels  # déjà triés

    # Collecte PnL par (name, session_key)
    by_name: dict = {}
    for r in rows_1m:
        key = f"{r['date']} {r['time']}"
        by_name.setdefault(r["name"], {})
        by_name[r["name"]][key] = round(r["pnl_net"], 2)

    # Pour chaque action : tableau aligné sur all_labels (None = null en JSON)
    ASSET_COLORS = [
        "#2563eb", "#16a34a", "#dc2626", "#d97706",
        "#7c3aed", "#0891b2", "#db2777", "#65a30d",
    ]
    line_datasets = []
    for idx, (name, session_pnl) in enumerate(sorted(by_name.items())):
        color = ASSET_COLORS[idx % len(ASSET_COLORS)]
        data_aligned = [session_pnl.get(lbl, None) for lbl in all_labels]
        line_datasets.append({
            "label":           name,
            "data":            data_aligned,
            "borderColor":     color,
            "backgroundColor": color.replace(")", ", 0.08)").replace("#", "rgba(") if "#" in color else color,
            "borderWidth":     2,
            "pointRadius":     3,
            "fill":            False,
            "tension":         0.3,
            "spanGaps":        True,   # ← relie les points même si null intermédiaire
        })

    # Correction backgroundColor pour hex → rgba propre
    def hex_to_rgba(h, alpha=0.08):
        h = h.lstrip("#")
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        return f"rgba({r},{g},{b},{alpha})"

    for ds in line_datasets:
        c = ds["borderColor"]
        if c.startswith("#"):
            ds["backgroundColor"] = hex_to_rgba(c)

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
  .grid-full {{ margin-top: 20px; }}
  @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-radius: 12px; padding: 20px; }}
  .card h2 {{ font-size: 15px; font-weight: 600; margin-bottom: 16px; color: var(--muted); }}
  canvas {{ max-height: 320px; }}
  #assetLineChart {{ max-height: 360px; }}
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
<p class="meta">Mis à jour le {now.strftime('%d/%m/%Y à %H:%M')} · {len(sorted_sessions)} sessions · 30 derniers jours</p>

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

<div class="grid-full">
  <div class="card">
    <h2>PnL NET PAR ACTION — 30 derniers jours (€) — toutes les valeurs sur l'axe complet</h2>
    <canvas id="assetLineChart"></canvas>
  </div>
</div>

<script>
const labels      = {json.dumps(labels, ensure_ascii=False)};
const pnlData     = {json.dumps(pnl_data)};
const colors      = {json.dumps(colors)};
const bLabels     = {json.dumps(bar_labels, ensure_ascii=False)};
const bData       = {json.dumps(bar_data)};
const bColors     = {json.dumps(bar_colors)};
const lineDatasets = {json.dumps(line_datasets, ensure_ascii=False)};

const isDark    = () => document.documentElement.getAttribute('data-theme') === 'dark';
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

// Graphique PnL global
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
      spanGaps: true,
    }}],
  }},
  options: {{ ...chartDefaults(), responsive: true, maintainAspectRatio: true }},
}});

// Graphique barres dernier run
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

// Graphique par action — TOUTES sur l'axe X commun (spanGaps: true)
const assetCtx = document.getElementById('assetLineChart').getContext('2d');
const assetLineChart = new Chart(assetCtx, {{
  type: 'line',
  data: {{
    labels,
    datasets: lineDatasets,
  }},
  options: {{
    ...chartDefaults(),
    responsive: true,
    maintainAspectRatio: true,
    plugins: {{
      legend: {{
        display: true,
        position: 'top',
        labels: {{ color: tickColor(), font: {{ size: 11 }}, boxWidth: 14 }},
      }},
    }},
    scales: {{
      x: {{
        ticks: {{ color: tickColor(), maxTicksLimit: 8, font: {{ size: 11 }} }},
        grid:  {{ color: gridColor() }},
      }},
      y: {{
        ticks: {{ color: tickColor(), font: {{ size: 11 }} }},
        grid:  {{ color: gridColor() }},
        beginAtZero: false,
      }},
    }},
  }},
}});

function toggleTheme() {{
  const root = document.documentElement;
  const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  document.querySelector('.toggle').textContent = next === 'dark' ? '☀️ Clair' : '🌙 Sombre';
  const updateColors = (c) => {{
    if (c.options.scales?.x) {{
      c.options.scales.x.ticks.color = tickColor();
      c.options.scales.x.grid.color  = gridColor();
      c.options.scales.y.ticks.color = tickColor();
      c.options.scales.y.grid.color  = gridColor();
    }}
    if (c.options.plugins?.legend?.labels) {{
      c.options.plugins.legend.labels.color = tickColor();
    }}
    c.update();
  }};
  [lineChart, barChart, assetLineChart].forEach(updateColors);
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
