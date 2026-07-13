"""
どこで: `generate_report.py`。
何を: `data/output/benchmarks/runs/*.json` を集約し、`data/output/benchmarks/report.html` を生成する。
なぜ: 最適化前後の改善度合いを、ケース別×effect 別の時系列グラフで把握するため。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from grafix.core.atomic_write import atomic_write_text
from grafix.devtools.benchmarks import BENCHMARK_SCHEMA_VERSION

_RUN_ID_FORMAT = "%Y%m%d_%H%M%S"
_CANVAS_HEIGHT = 600


@dataclass(frozen=True, slots=True)
class _Run:
    run_id: str
    dt: datetime
    meta: dict[str, Any]
    scenarios: dict[str, dict[str, Any]]
    effect_names: list[str]
    means_ms: dict[str, dict[str, float]]
    metrics: dict[str, dict[str, dict[str, Any]]]
    system_profile: str
    system_results: dict[str, dict[str, Any]]


def main(*, out: str | Path = "data/output/benchmarks") -> int:
    out_root = Path(out).expanduser().resolve()
    runs_dir = out_root / "runs"
    report_path = out_root / "report.html"

    report = build_timeseries_report(runs_dir=runs_dir)
    html = render_report_html(report)

    atomic_write_text(report_path, html)
    print(f"[grafix-bench] wrote: {report_path}")  # noqa: T201
    return 0


def build_timeseries_report(*, runs_dir: Path) -> dict[str, Any]:
    runs = _load_runs(runs_dir=runs_dir)
    if not runs:
        raise SystemExit(f"no runs found: {runs_dir}")

    effect_runs = [run for run in runs if run.scenarios or run.effect_names]
    latest_effect = effect_runs[-1] if effect_runs else runs[-1]
    scenario_list = list(latest_effect.scenarios.values())
    effect_names = list(latest_effect.effect_names)

    run_rows = [
        {
            "run_id": r.run_id,
            "created_at": r.meta.get("created_at", ""),
            "git_sha": r.meta.get("git_sha", ""),
        }
        for r in effect_runs
    ]

    chart_specs: list[dict[str, Any]] = []
    for scenario in scenario_list:
        scenario_id = str(scenario.get("id", ""))
        if not scenario_id:
            continue

        series: dict[str, list[float | None]] = {}
        for eff in effect_names:
            pts: list[float | None] = []
            for r in effect_runs:
                v = r.means_ms.get(scenario_id, {}).get(eff)
                pts.append(float(v) if v is not None else None)
            series[eff] = pts

        latest_means = latest_effect.means_ms.get(scenario_id, {})
        ordered_effects = sorted(
            effect_names,
            key=lambda e: float(latest_means.get(e, -1.0)),
            reverse=True,
        )

        datasets = []
        for eff in ordered_effects:
            color = _color_for_label(eff)
            datasets.append(
                {
                    "label": eff,
                    "data": series.get(eff, []),
                    "borderColor": color,
                    "backgroundColor": color,
                    "tension": 0.2,
                }
            )

        table_rows = []
        for eff in ordered_effects:
            pts = series.get(eff, [])
            first = next((v for v in pts if v is not None), None)
            last = next((v for v in reversed(pts) if v is not None), None)
            ratio = ""
            if first is not None and last is not None and float(first) > 0.0:
                ratio = f"{float(last) / float(first):.3f}x"
            latest_metrics = latest_effect.metrics.get(scenario_id, {}).get(eff, {})
            cold = latest_metrics.get("cold", {})
            output = latest_metrics.get("output", {})
            table_rows.append(
                {
                    "effect": eff,
                    "first_ms": first,
                    "last_ms": last,
                    "p95_ms": latest_metrics.get("p95_ms"),
                    "cold_ms": cold.get("median_ms"),
                    "peak_rss_bytes": cold.get("peak_rss_bytes"),
                    "output_vertices": output.get("n_vertices"),
                    "output_lines": output.get("n_lines"),
                    "output_bytes": output.get("bytes"),
                    "ratio": ratio,
                }
            )

        chart_specs.append(
            {
                "scenario_id": scenario_id,
                "scenario_label": str(scenario.get("label", scenario_id)),
                "scenario_description": str(scenario.get("description", "")),
                "tags": list(scenario.get("tags", [])),
                "inputs": list(scenario.get("inputs", [])),
                "datasets": datasets,
                "table": table_rows,
            }
        )

    system_run = next(
        (run for run in reversed(runs) if run.system_results),
        None,
    )
    system: dict[str, Any] = {}
    if system_run is not None:
        system = {
            "run_id": system_run.run_id,
            "profile": system_run.system_profile,
            "rows": list(system_run.system_results.values()),
        }

    meta = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runs": len(runs),
        "effect_runs": len(effect_runs),
        "system_runs": sum(bool(run.system_results) for run in runs),
        "first_run": runs[0].run_id,
        "last_run": runs[-1].run_id,
    }
    if system_run is not None:
        meta["last_system_run"] = system_run.run_id
        meta["system_profile"] = system_run.system_profile
    return {
        "meta": meta,
        "runs": run_rows,
        "scenarios": [
            {"id": scenario.get("id", ""), "label": scenario.get("label", "")}
            for scenario in scenario_list
        ],
        "charts": chart_specs,
        "system": system,
    }


def render_report_html(report: dict[str, Any]) -> str:
    meta: dict[str, Any] = dict(report.get("meta", {}))
    runs: list[dict[str, Any]] = list(report.get("runs", []))
    scenarios: list[dict[str, Any]] = list(report.get("scenarios", []))
    charts: list[dict[str, Any]] = list(report.get("charts", []))
    system: dict[str, Any] = dict(report.get("system", {}))

    payload_json = json.dumps(
        {
            "runs": runs,
            "charts": charts,
        },
        ensure_ascii=False,
    )

    head = _render_head(title="grafix effect benchmark (timeseries)")
    body = []
    body.append("<h1>grafix effect benchmark (timeseries)</h1>")
    body.append(_render_meta(meta))
    body.append(_render_scenario_index(scenarios))

    body.append('<div class="panel">')
    body.append('<div class="muted">Note</div>')
    body.append("<ul>")
    body.append("<li>グラフは Chart.js（CDN）で描画する。ネット接続が無いと表だけになる。</li>")
    body.append("<li>凡例クリックで effect の表示/非表示を切り替えできる。</li>")
    body.append("</ul>")
    body.append("</div>")

    if system.get("rows"):
        body.append(_render_system_section(system=system))

    for chart in charts:
        scenario_id = str(chart.get("scenario_id", ""))
        scenario_label = str(chart.get("scenario_label", scenario_id))
        scenario_desc = str(chart.get("scenario_description", ""))
        tags = ", ".join(str(tag) for tag in chart.get("tags", []))
        input_stats = _format_input_stats(list(chart.get("inputs", [])))

        body.append(
            f'<h2 id="scenario-{escape(scenario_id)}">Scenario: {escape(scenario_label)}</h2>'
        )
        parts = [
            f'<div class="muted">{escape(scenario_desc)}</div>' if scenario_desc else "",
            f'<div class="muted">tags: {escape(tags)}</div>' if tags else "",
            f'<div style="margin-top:6px" class="mono">{escape(input_stats)}</div>',
        ]
        body.append('<div class="panel">' + "\n".join(p for p in parts if p) + "</div>")

        body.append('<div class="panel">')
        body.append(f'<canvas id="chart-{escape(scenario_id)}" height="{_CANVAS_HEIGHT}"></canvas>')
        body.append("</div>")

        table_rows: list[dict[str, Any]] = list(chart.get("table", []))
        body.append(_render_improvement_table(rows=table_rows))

    body.append("<hr />")
    body.append('<p class="muted">generated by generate_report.py</p>')

    js = _render_scripts(payload_json=payload_json)
    return head + "\n<body>\n" + "\n".join(body) + "\n" + js + "\n</body>\n</html>\n"


def _render_head(*, title: str) -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #121a33;
      --text: #e7ecff;
      --muted: #aab3d6;
      --grid: rgba(255,255,255,0.08);
      --bar: #4aa3ff;
      --bar2: #7fdbca;
      --warn: #ffcc66;
      --err: #ff6b6b;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }}
    body {{
      margin: 0;
      padding: 28px;
      font-family: var(--sans);
      background: linear-gradient(180deg, var(--bg), #070a14);
      color: var(--text);
    }}
    a {{ color: var(--bar); }}
    h1 {{ margin: 0 0 8px 0; font-size: 24px; }}
    h2 {{ margin: 28px 0 10px 0; font-size: 18px; }}
    .muted {{ color: var(--muted); }}
    .panel {{
      background: rgba(18,26,51,0.9);
      border: 1px solid var(--grid);
      border-radius: 12px;
      padding: 12px 14px;
      margin: 10px 0;
      backdrop-filter: blur(10px);
    }}
    .mono {{ font-family: var(--mono); }}
    .case-index a {{ margin-right: 10px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-family: var(--mono);
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid var(--grid);
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
  </style>
</head>
"""


def _render_meta(meta: dict[str, Any]) -> str:
    items: list[str] = []
    for key in (
        "schema_version",
        "generated_at",
        "runs",
        "effect_runs",
        "system_runs",
        "first_run",
        "last_run",
        "last_system_run",
        "system_profile",
    ):
        if key in meta:
            items.append(
                f'<div><span class="muted">{escape(key)}</span>: <span class="mono">{escape(str(meta[key]))}</span></div>'
            )
    if not items:
        return ""
    return '<div class="panel">' + "\n".join(items) + "</div>"


def _render_scenario_index(scenarios: list[dict[str, Any]]) -> str:
    links: list[str] = []
    for scenario in scenarios:
        scenario_id = str(scenario.get("id", ""))
        label = str(scenario.get("label", scenario_id))
        if not scenario_id:
            continue
        links.append(f'<a href="#scenario-{escape(scenario_id)}">{escape(label)}</a>')
    if not links:
        return ""
    return (
        '<div class="panel case-index"><div class="muted">Scenarios</div>'
        + " ".join(links)
        + "</div>"
    )


def _format_input_stats(inputs: list[dict[str, Any]]) -> str:
    """scenario の全入力規模を1行の表示文字列へ整形する。"""

    parts: list[str] = []
    for index, stats in enumerate(inputs):
        parts.append(
            f"input[{index}]: verts={stats.get('n_vertices', '')} "
            f"lines={stats.get('n_lines', '')} closed_lines={stats.get('closed_lines', '')}"
        )
    return " | ".join(parts)


def _render_improvement_table(*, rows: list[dict[str, Any]]) -> str:
    out = []
    out.append('<div class="panel">')
    out.append('<div class="muted">Improvement (first → last)</div>')
    out.append("<table>")
    out.append(
        "<tr>"
        "<th>effect</th>"
        "<th>first median_ms</th>"
        "<th>last median_ms</th>"
        "<th>p95_ms</th>"
        "<th>cold median_ms</th>"
        "<th>peak RSS MiB</th>"
        "<th>output (verts / lines / KiB)</th>"
        "<th>ratio</th>"
        "</tr>"
    )

    for r in rows:
        name = escape(str(r.get("effect", "")))
        first_ms = _fmt_num(r.get("first_ms"))
        last_ms = _fmt_num(r.get("last_ms"))
        p95_ms = _fmt_num(r.get("p95_ms"))
        cold_ms = _fmt_num(r.get("cold_ms"))
        peak_rss = _fmt_bytes_mib(r.get("peak_rss_bytes"))
        output = _fmt_output(r)
        ratio = escape(str(r.get("ratio", "")))
        out.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>{first_ms}</td>"
            f"<td>{last_ms}</td>"
            f"<td>{p95_ms}</td>"
            f"<td>{cold_ms}</td>"
            f"<td>{peak_rss}</td>"
            f"<td>{output}</td>"
            f"<td>{ratio}</td>"
            "</tr>"
        )

    out.append("</table></div>")
    return "\n".join(out)


def _render_system_section(*, system: dict[str, Any]) -> str:
    """最新のsystem/micro計測を独立した表として描画する。"""

    run_id = escape(str(system.get("run_id", "")))
    profile = escape(str(system.get("profile", "")))
    rows = list(system.get("rows", []))
    out = [
        '<h2 id="system-benchmarks">System / micro benchmarks</h2>',
        '<div class="panel">',
        f'<div class="muted">run: <span class="mono">{run_id}</span> '
        f'profile: <span class="mono">{profile}</span></div>',
        "<table>",
        "<tr>"
        "<th>benchmark</th>"
        "<th>category</th>"
        "<th>status</th>"
        "<th>median_ms</th>"
        "<th>p95_ms</th>"
        "<th>peak RSS MiB</th>"
        "<th>output</th>"
        "<th>cache</th>"
        "<th>error</th>"
        "</tr>",
    ]
    for row in rows:
        out.append(
            "<tr>"
            f"<td>{escape(str(row.get('label', row.get('id', ''))))}</td>"
            f"<td>{escape(str(row.get('category', '')))}</td>"
            f"<td>{escape(str(row.get('status', '')))}</td>"
            f"<td>{_fmt_num(row.get('median_ms'))}</td>"
            f"<td>{_fmt_num(row.get('p95_ms'))}</td>"
            f"<td>{_fmt_bytes_mib(row.get('peak_rss_bytes'))}</td>"
            f"<td>{_fmt_mapping(row.get('output'))}</td>"
            f"<td>{_fmt_mapping(row.get('cache'))}</td>"
            f"<td>{escape(str(row.get('error', '')))}</td>"
            "</tr>"
        )
    out.append("</table></div>")
    return "\n".join(out)


def _fmt_mapping(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return escape(", ".join(f"{key}={item}" for key, item in value.items()))


def _fmt_num(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except Exception:
        return escape(str(value))


def _fmt_bytes_mib(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value) / (1024.0 * 1024.0):.1f}"
    except Exception:
        return escape(str(value))


def _fmt_output(row: dict[str, Any]) -> str:
    vertices = row.get("output_vertices")
    lines = row.get("output_lines")
    size = row.get("output_bytes")
    if vertices is None or lines is None or size is None:
        return ""
    try:
        return f"{int(vertices)} / {int(lines)} / {int(size) / 1024.0:.1f}"
    except Exception:
        return escape(f"{vertices} / {lines} / {size}")


def _render_scripts(*, payload_json: str) -> str:
    template = """
<script>
  const REPORT = __GRAFIX_BENCH_PAYLOAD__;
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
  function tooltipTitle(items) {
    if (!items || items.length === 0) return '';
    const idx = items[0].dataIndex;
    const r = REPORT.runs[idx] || {};
    const sha = (r.git_sha || '').slice(0, 10);
    const created = r.created_at ? ` (${r.created_at})` : '';
    return `${r.run_id || idx}${created}${sha ? ' ' + sha : ''}`;
  }

  function tooltipLabel(ctx) {
    const label = ctx.dataset.label || '';
    const v = ctx.raw;
    if (v === null || v === undefined) return `${label}: (missing)`;
    return `${label}: ${Number(v).toFixed(3)} ms`;
  }

  function buildChart(scenarioId, spec) {
    const canvas = document.getElementById(`chart-${scenarioId}`);
    if (!canvas) return;

    const labels = REPORT.runs.map(r => r.run_id);
    const datasets = (spec.datasets || []).map(ds => {
      const data = (ds.data || []).map(v => {
        if (v === null || v === undefined) return null;
        const n = Number(v);
        return Number.isFinite(n) && n > 0 ? n : null;
      });
      return { ...ds, data };
    });

    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'nearest',
          intersect: false,
        },
        scales: {
          x: {
            ticks: {
              maxRotation: 60,
              minRotation: 45,
              autoSkip: true,
              maxTicksLimit: 12,
            },
            grid: { color: 'rgba(255,255,255,0.06)' },
          },
          y: {
            type: 'logarithmic',
            title: { display: true, text: 'median_ms (log10)' },
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: {
              callback: (value) => {
                const v = Number(value);
                if (!Number.isFinite(v)) return '';
                if (v >= 10) return `${v.toFixed(0)} ms`;
                if (v >= 1) return `${v.toFixed(1)} ms`;
                if (v >= 0.1) return `${v.toFixed(2)} ms`;
                return `${v.toFixed(3)} ms`;
              },
            },
          },
        },
        plugins: {
          legend: {
            labels: {
              boxWidth: 12,
            },
          },
          tooltip: {
            callbacks: {
              title: tooltipTitle,
              label: tooltipLabel,
            },
          },
        },
        elements: {
          point: {
            radius: 2,
            hoverRadius: 4,
          },
          line: {
            borderWidth: 2,
          },
        },
      },
    });
    return chart;
  }

  function main() {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js not loaded. Showing tables only.');
      return;
    }

    Chart.defaults.color = '#e7ecff';
    Chart.defaults.borderColor = 'rgba(255,255,255,0.12)';

    for (const spec of REPORT.charts) {
      buildChart(spec.scenario_id, spec);
    }
  }
  main();
</script>
"""
    return template.replace("__GRAFIX_BENCH_PAYLOAD__", payload_json)


def _parse_run_id(run_id: str) -> datetime | None:
    try:
        return datetime.strptime(run_id, _RUN_ID_FORMAT)
    except ValueError:
        return None


def _load_runs(*, runs_dir: Path) -> list[_Run]:
    runs: list[_Run] = []
    for fp in sorted(runs_dir.glob("*.json")):
        dt = _parse_run_id(fp.stem)
        if dt is None:
            continue
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue

        if raw.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
            continue

        meta = dict(raw.get("meta", {}))
        scenarios = {
            str(scenario.get("id", "")): dict(scenario)
            for scenario in raw.get("scenarios", [])
            if str(scenario.get("id", ""))
        }

        effect_names: list[str] = []
        seen_effects: set[str] = set()
        means_ms: dict[str, dict[str, float]] = {}
        metrics: dict[str, dict[str, dict[str, Any]]] = {}
        for eff in raw.get("effects", []):
            name = str(eff.get("name", ""))
            if not name:
                continue
            if name not in seen_effects:
                seen_effects.add(name)
                effect_names.append(name)
            for scenario_id, res in dict(eff.get("results", {})).items():
                if str(res.get("status", "")) != "ok":
                    continue
                try:
                    median_ms = float(res.get("median_ms", res.get("mean_ms", 0.0)))
                except Exception:
                    continue
                scenario_key = str(scenario_id)
                means_ms.setdefault(scenario_key, {})[name] = median_ms
                metrics.setdefault(scenario_key, {})[name] = dict(res)

        system_raw = raw.get("system", {})
        if not isinstance(system_raw, dict):
            system_raw = {}
        results_raw = system_raw.get("results", {})
        if not isinstance(results_raw, dict):
            results_raw = {}
        system_results = {
            str(case_id): dict(result)
            for case_id, result in results_raw.items()
            if isinstance(result, dict)
        }

        runs.append(
            _Run(
                run_id=fp.stem,
                dt=dt,
                meta=meta,
                scenarios=scenarios,
                effect_names=effect_names,
                means_ms=means_ms,
                metrics=metrics,
                system_profile=str(system_raw.get("profile", "")),
                system_results=system_results,
            )
        )

    runs.sort(key=lambda r: r.dt)
    return runs


def _color_for_label(label: str) -> str:
    h = 0
    for ch in label:
        h = (h * 131 + ord(ch)) % 360
    return f"hsl({h}, 70%, 60%)"


if __name__ == "__main__":
    raise SystemExit(main())
