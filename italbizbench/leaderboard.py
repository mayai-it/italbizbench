"""Generatore di leaderboard statica (HTML self-contained, pronta per GitHub Pages).

Legge N report JSON prodotti da ``python -m italbizbench.runner tasks --json --save DIR``
(uno per agente) e produce UNA pagina HTML: tabella pass-rate con IC (bootstrap e
Wilson), i 4 assi, breakdown per difficolta e reliability curve per agente.

Vincoli deliberati:
- **Deterministico e offline**: stesso input -> stesso output, byte per byte. Nessun
  timestamp, nessun font/script/CSS esterno, nessuna dipendenza runtime (le curve
  sono SVG inline generati qui, niente JavaScript).
- **Accessibile e leggibile** in light e dark (prefers-color-scheme), tabelle
  semantiche con scope/caption, SVG con role="img" e aria-label.

Uso:
    python -m italbizbench.leaderboard runs/claude/report.json runs/gpt/report.json \
        -o leaderboard.html
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    """Carica un report del runner e ne verifica la forma minima."""
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "agent" not in data or "scorecard" not in data:
        raise ValueError(f"{path}: non e un report del runner (attesi 'agent' e 'scorecard')")
    return data


def _fmt(value: Any, digits: int = 3) -> str:
    """Numero formattato per la tabella; None -> em dash (dato non disponibile)."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") or "0"
    return escape(str(value))


def _fmt_ci(ci: Any) -> str:
    if not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return "—"
    return f"({_fmt(ci[0])}, {_fmt(ci[1])})"


def _reliability_svg(agent: str, bins: list[dict[str, Any]]) -> str:
    """Reliability curve come SVG inline: diagonale ideale + un punto per bin.

    L'area del punto cresce con il numero di predizioni nel bin; i bin vuoti
    non sono disegnati. Nessun JavaScript: il grafico e' testo statico.
    """
    size, m = 240, 34  # lato e margine
    plot = size - 2 * m
    parts: list[str] = [
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
        f'aria-label="Reliability curve di {escape(agent, quote=True)}: confidenza media '
        f'contro accuratezza per bin">',
        f'<line class="axis" x1="{m}" y1="{size - m}" x2="{size - m}" y2="{size - m}"/>',
        f'<line class="axis" x1="{m}" y1="{m}" x2="{m}" y2="{size - m}"/>',
        f'<line class="diag" x1="{m}" y1="{size - m}" x2="{size - m}" y2="{m}"/>',
        f'<text class="lbl" x="{size // 2}" y="{size - 6}" text-anchor="middle">'
        "confidenza media</text>",
        f'<text class="lbl" x="10" y="{size // 2}" text-anchor="middle" '
        f'transform="rotate(-90 10 {size // 2})">accuratezza</text>',
        f'<text class="tick" x="{m}" y="{size - m + 14}" text-anchor="middle">0</text>',
        f'<text class="tick" x="{size - m}" y="{size - m + 14}" text-anchor="middle">1</text>',
    ]
    for b in bins:
        n = b.get("n", 0)
        conf, acc = b.get("mean_confidence"), b.get("accuracy")
        if not isinstance(n, int) or n <= 0:
            continue
        if not isinstance(conf, (int, float)) or not isinstance(acc, (int, float)):
            continue
        x = m + float(conf) * plot
        y = m + (1.0 - float(acc)) * plot
        r = 3.0 + min(6.0, n ** 0.5)
        parts.append(
            f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}">'
            f"<title>bin [{_fmt(b.get('lo'))}, {_fmt(b.get('hi'))}]: n={n}, "
            f"conf={_fmt(conf)}, acc={_fmt(acc)}</title></circle>"
        )
    parts.append("</svg>")
    return "".join(parts)


_CSS = """
:root { color-scheme: light dark;
  --bg: #ffffff; --fg: #1a1a24; --muted: #5a5a6e; --line: #d8d8e2;
  --accent: #2244aa; --card: #f5f5fa; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #14141c; --fg: #ececf2; --muted: #a0a0b4; --line: #3a3a4a;
    --accent: #8ab4ff; --card: #1e1e2a; } }
* { box-sizing: border-box; }
body { margin: 2rem auto; max-width: 72rem; padding: 0 1rem;
  background: var(--bg); color: var(--fg);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 1.6rem; } h2 { font-size: 1.2rem; margin-top: 2rem; }
p.note { color: var(--muted); max-width: 60rem; }
.muted { color: var(--muted); font-weight: 400; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
caption { text-align: left; color: var(--muted); padding: .25rem 0; caption-side: top; }
th, td { border: 1px solid var(--line); padding: .45rem .6rem; text-align: right; }
th[scope=row], td:first-child, th:first-child { text-align: left; }
thead th { background: var(--card); }
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--card) 55%, var(--bg)); }
.grid { display: flex; flex-wrap: wrap; gap: 1.5rem; }
figure { margin: 0; background: var(--card); border: 1px solid var(--line);
  border-radius: 8px; padding: .75rem; }
figcaption { font-weight: 600; margin-bottom: .25rem; }
svg .axis { stroke: var(--muted); stroke-width: 1; }
svg .diag { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 4 4; }
svg .pt { fill: var(--accent); fill-opacity: .75; }
svg .lbl, svg .tick { fill: var(--muted); font-size: 11px; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: .85rem; }
"""


def _difficulties(reports: list[dict[str, Any]]) -> list[str]:
    """Unione ordinata delle difficolta presenti nei report (colonne stabili)."""
    diffs: set[str] = set()
    for r in reports:
        by_diff = r["scorecard"].get("by_difficulty") or {}
        diffs.update(str(k) for k in by_diff)
    return sorted(diffs)


def build_html(reports: list[dict[str, Any]], title: str = "ItalBizBench — Leaderboard") -> str:
    """Costruisce la pagina HTML. Pura e deterministica: niente orologio, niente rete."""
    # Ordinamento deterministico: pass-rate decrescente, poi nome agente.
    ranked = sorted(reports, key=lambda r: (-(r["scorecard"].get("pass_rate") or 0.0),
                                            str(r.get("agent", ""))))
    diffs = _difficulties(ranked)

    rows: list[str] = []
    for i, r in enumerate(ranked, start=1):
        s = r["scorecard"]
        cost = s.get("cost_eur_total")
        rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f'<th scope="row">{escape(str(r.get("agent", "?")))}</th>'
            f"<td>{_fmt(s.get('n_tasks'))}</td>"
            f"<td><strong>{_fmt(s.get('pass_rate'))}</strong></td>"
            f"<td>{_fmt_ci(s.get('correctness_ci95'))}</td>"
            f"<td>{_fmt_ci(s.get('correctness_wilson_ci95'))}</td>"
            f"<td>{_fmt(s.get('efficiency_mean'))}</td>"
            f"<td>{_fmt(s.get('safety_mean'))}</td>"
            f"<td>{_fmt(s.get('brier'), 4)}</td>"
            f"<td>{_fmt(s.get('ece'), 4)}</td>"
            f"<td>{_fmt(s.get('abstention_accuracy'))}</td>"
            f"<td>{_fmt(s.get('tokens_input_total'))} / {_fmt(s.get('tokens_output_total'))}</td>"
            f"<td>{'—' if cost is None else '€' + _fmt(cost, 4)}</td>"
            "</tr>"
        )

    diff_rows: list[str] = []
    for r in ranked:
        s = r["scorecard"]
        by_diff = s.get("by_difficulty") or {}
        cells = "".join(f"<td>{_fmt(by_diff.get(d))}</td>" for d in diffs)
        diff_rows.append(
            f'<tr><th scope="row">{escape(str(r.get("agent", "?")))}</th>{cells}</tr>')

    figures = []
    for r in ranked:
        agent = str(r.get("agent", "?"))
        bins = r["scorecard"].get("reliability_bins") or []
        n_pred = r["scorecard"].get("n_predictions")
        figures.append(
            f"<figure><figcaption>{escape(agent)} "
            f'<span class="muted">({_fmt(n_pred)} predizioni)</span></figcaption>'
            f"{_reliability_svg(agent, bins)}</figure>"
        )

    diff_head = "".join(f'<th scope="col">{escape(d)}</th>' for d in diffs)
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<h1>{escape(title)}</h1>
<p class="note">Benchmark di agenti AI su compiti fiscali/amministrativi di una PMI
italiana. Nessun numero e un giudizio soggettivo: ogni task ha un oracolo
deterministico. Due agenti sono &laquo;diversi&raquo; solo se gli intervalli di
confidenza non si sovrappongono. Regole fiscali verificate su fonti, non ancora
asseverate da un commercialista.</p>
</header>
<main>
<h2>Classifica</h2>
<table>
<caption>Pass-rate con IC al 95% (bootstrap percentile e Wilson), assi di efficienza,
sicurezza e calibrazione (Brier / ECE, astensioni escluse dal pool), token e costo.</caption>
<thead><tr>
<th scope="col">#</th><th scope="col">Agente</th><th scope="col">Task</th>
<th scope="col">Pass-rate</th><th scope="col">IC95% bootstrap</th>
<th scope="col">IC95% Wilson</th><th scope="col">Efficienza</th>
<th scope="col">Sicurezza</th><th scope="col">Brier</th><th scope="col">ECE</th>
<th scope="col">Acc. astensioni</th><th scope="col">Token in/out</th>
<th scope="col">Costo</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
<h2>Pass-rate per difficolt&agrave;</h2>
<table>
<caption>base = caso pulito; tricky = eccezione fiscale; adversarial = dato
ambiguo/sporco dove l'agente dovrebbe fermarsi e chiedere conferma.</caption>
<thead><tr><th scope="col">Agente</th>{diff_head}</tr></thead>
<tbody>
{chr(10).join(diff_rows)}
</tbody>
</table>
<h2>Reliability curve</h2>
<p class="note">Confidenza media vs accuratezza osservata per bin (10 bin di uguale
ampiezza; area del punto proporzionale al numero di predizioni). La diagonale
tratteggiata &egrave; la calibrazione perfetta: punti sotto la diagonale =
sovraconfidenza.</p>
<div class="grid">
{chr(10).join(figures)}
</div>
</main>
<footer>
<p>Generato da <code>italbizbench.leaderboard</code> — pagina statica, nessuna
dipendenza esterna. Progetto <a href="https://github.com/mayai-it/italbizbench">
mayai-it/italbizbench</a> (MIT).</p>
</footer>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Genera la leaderboard HTML statica")
    p.add_argument("reports", nargs="+", type=Path,
                   help="report JSON del runner (uno per agente)")
    p.add_argument("-o", "--output", type=Path, default=Path("leaderboard.html"),
                   help="file HTML di destinazione (default: leaderboard.html)")
    p.add_argument("--title", default="ItalBizBench — Leaderboard")
    args = p.parse_args(argv)

    html = build_html([load_report(path) for path in args.reports], title=args.title)
    args.output.write_text(html, encoding="utf-8")
    print(f"Leaderboard scritta in {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
