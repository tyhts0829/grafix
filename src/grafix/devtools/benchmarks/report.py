"""schema v3 run を network 不要の HTML table にまとめる。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from grafix.core.atomic_write import atomic_write_text
from grafix.devtools.benchmarks.schema import (
    BenchmarkRun,
    BenchmarkSchemaError,
    read_benchmark_run,
)


@dataclass(frozen=True, slots=True)
class LoadedRuns:
    """有効 run と、黙って捨てない load warning。"""

    runs: tuple[BenchmarkRun, ...]
    warnings: tuple[str, ...]


def load_runs(runs_dir: str | Path) -> LoadedRuns:
    """directory 内の全 JSON を読み、壊れた run を warning として保持する。"""

    directory = Path(runs_dir)
    runs: list[BenchmarkRun] = []
    warnings: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            run = read_benchmark_run(path)
            runs.append(run)
            warnings.extend(
                f"{path}: {warning}"
                for warning in run.warnings
            )
        except BenchmarkSchemaError as exc:
            warnings.append(str(exc))
    runs.sort(key=lambda run: (run.meta.created_at, run.meta.run_id))
    return LoadedRuns(runs=tuple(runs), warnings=tuple(warnings))


def write_report(out_root: str | Path) -> tuple[Path, Path, LoadedRuns]:
    """report.html と warnings.json を atomic に生成する。"""

    root = Path(out_root).expanduser().resolve()
    loaded = load_runs(root / "runs")
    report_path = root / "report.html"
    warnings_path = root / "warnings.json"
    atomic_write_text(report_path, render_report_html(loaded))
    atomic_write_text(
        warnings_path,
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "valid_runs": len(loaded.runs),
                "warning_count": len(loaded.warnings),
                "warnings": list(loaded.warnings),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return report_path, warnings_path, loaded


def render_report_html(loaded: LoadedRuns) -> str:
    """JavaScript/CDN を使わない自己完結 HTML を返す。"""

    rows: list[str] = []
    for run in loaded.runs:
        source = run.source.commit or "unavailable"
        for result in run.cases:
            median_ms = (
                ""
                if result.stats is None
                else f"{result.stats.median_ns / 1_000_000.0:.6f}"
            )
            mad_ms = (
                ""
                if result.stats is None
                else f"{result.stats.mad_ns / 1_000_000.0:.6f}"
            )
            p95_ms = (
                ""
                if result.stats is None or result.stats.p95_ns is None
                else f"{result.stats.p95_ns / 1_000_000.0:.6f}"
            )
            rss_mib = (
                ""
                if result.peak_rss_delta_bytes is None
                else f"{result.peak_rss_delta_bytes / (1024.0 * 1024.0):.2f}"
            )
            rows.append(
                "<tr>"
                f"<td>{escape(run.meta.run_id)}</td>"
                f"<td>{escape(source[:12])}</td>"
                f"<td><code>{escape(result.spec.case_id)}</code><br>"
                f"<small>{escape(result.spec.label)}</small></td>"
                f"<td>{escape(result.spec.category)}</td>"
                f"<td>{escape(result.status)}</td>"
                f"<td>{median_ms}</td>"
                f"<td>{mad_ms}</td>"
                f"<td>{p95_ms}</td>"
                f"<td>{rss_mib}</td>"
                f"<td class=\"hash\">{escape(result.checksum or '')}</td>"
                "</tr>"
            )

    warning_items = "".join(
        f"<li>{escape(warning)}</li>" for warning in loaded.warnings
    )
    if not warning_items:
        warning_items = "<li>none</li>"
    table_body = "\n".join(rows) or (
        '<tr><td colspan="10">有効な schema v3 run がありません。</td></tr>'
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Grafix benchmark schema v3</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 24px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d8deea; padding: 7px; text-align: left; }}
    th {{ position: sticky; top: 0; background: #f3f6fb; }}
    .hash {{ max-width: 12rem; overflow: hidden; text-overflow: ellipsis; }}
    .warnings {{ border: 1px solid #e6b95c; background: #fff8e8; padding: 8px 16px; }}
    code {{ font-family: ui-monospace, monospace; }}
  </style>
</head>
<body>
  <h1>Grafix benchmark schema v3</h1>
  <p>valid runs: {len(loaded.runs)} / warnings: {len(loaded.warnings)}</p>
  <section class="warnings"><strong>Load warnings</strong><ul>{warning_items}</ul></section>
  <table>
    <thead><tr>
      <th>run</th><th>source</th><th>case</th><th>category</th><th>status</th>
      <th>median ms</th><th>MAD ms</th><th>p95 ms</th><th>RSS delta MiB</th>
      <th>checksum</th>
    </tr></thead>
    <tbody>{table_body}</tbody>
  </table>
</body>
</html>
"""


__all__ = ["LoadedRuns", "load_runs", "render_report_html", "write_report"]
