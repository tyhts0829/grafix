"""schema v4 run を network 不要の HTML report にまとめる。"""

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
    CaseResult,
    Metric,
    read_benchmark_run,
)


@dataclass(frozen=True, slots=True)
class LoadedRuns:
    """有効 run と、黙って捨てない load warning。"""

    runs: tuple[BenchmarkRun, ...]
    warnings: tuple[str, ...]


def load_runs(runs_dir: str | Path) -> LoadedRuns:
    """directory 内の全 JSON を読み、壊れた run と contract を warning にする。"""

    directory = Path(runs_dir)
    runs: list[BenchmarkRun] = []
    warnings: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            run = read_benchmark_run(path)
            runs.append(run)
            warnings.extend(f"{path}: {warning}" for warning in run.warnings)
            for result in run.cases:
                warnings.extend(
                    (
                        f"{path}: {result.spec.case_id}: "
                        f"{contract.severity} contract failed: "
                        f"{contract.contract_id}: {contract.reason}"
                    )
                    for contract in result.contracts
                    if not contract.passed
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
    previous: dict[
        tuple[str, str],
        tuple[BenchmarkRun, CaseResult],
    ] = {}
    for run in loaded.runs:
        source = run.source.commit or "unavailable"
        for result in run.cases:
            stats = result.stats
            median_ms = "" if stats is None else _milliseconds(stats.median_ns)
            mad_ms = "" if stats is None else _milliseconds(stats.mad_ns)
            p95_ms = (
                ""
                if stats is None or stats.p95_ns is None
                else _milliseconds(stats.p95_ns)
            )
            p99_ms = (
                ""
                if stats is None or stats.p99_ns is None
                else _milliseconds(stats.p99_ns)
            )
            rss_mib = (
                ""
                if result.peak_rss_delta_bytes is None
                else f"{result.peak_rss_delta_bytes / (1024.0 * 1024.0):.2f}"
            )
            previous_key = (
                run.environment.compatibility_key,
                result.spec.case_id,
            )
            previous_item = previous.get(previous_key)
            delta = ""
            if previous_item is not None:
                previous_run, previous_result = previous_item
                if (
                    previous_result.spec.compatibility_key
                    == result.spec.compatibility_key
                    and _measurement_compatible(
                        previous_run,
                        previous_result,
                        run,
                        result,
                    )
                    and previous_result.stats is not None
                    and stats is not None
                    and previous_result.stats.median_ns > 0.0
                ):
                    delta_percent = (
                        stats.median_ns / previous_result.stats.median_ns - 1.0
                    ) * 100.0
                    delta = (
                        f'<span title="base run: {escape(previous_run.meta.run_id)}">'
                        f"{delta_percent:+.1f}%</span>"
                    )
            previous[previous_key] = (run, result)

            hard_contracts = [
                contract
                for contract in result.contracts
                if contract.severity == "hard"
            ]
            soft_contracts = [
                contract
                for contract in result.contracts
                if contract.severity == "soft"
            ]
            contract_html = _contract_summary(hard_contracts, soft_contracts)
            checksum_html = (
                ""
                if result.checksum is None
                else (
                    f'<span class="pass">present</span><br>'
                    f'<small class="hash">{escape(result.checksum)}</small>'
                )
            )
            rows.append(
                "<tr>"
                f"<td>{escape(run.meta.run_id)}</td>"
                f"<td>{escape(source[:12])}</td>"
                f"<td><code>{escape(result.spec.case_id)}</code><br>"
                f"<small>{escape(result.spec.label)}</small></td>"
                f"<td>{escape(result.spec.category)}</td>"
                f'<td class="{_status_class(result.status)}">'
                f"{escape(result.status)}</td>"
                f"<td>{checksum_html}</td>"
                f"<td>{contract_html}</td>"
                f"<td>{median_ms}</td>"
                f"<td>{delta}</td>"
                f"<td>{mad_ms}</td>"
                f"<td>{p95_ms}</td>"
                f"<td>{p99_ms}</td>"
                f"<td>{rss_mib}</td>"
                f"<td>{_metrics_summary(result.metrics)}</td>"
                "</tr>"
            )

    warning_items = "".join(
        f"<li>{escape(warning)}</li>" for warning in loaded.warnings
    )
    if not warning_items:
        warning_items = "<li>none</li>"
    table_body = "\n".join(rows) or (
        '<tr><td colspan="14">有効な schema v4 run がありません。</td></tr>'
    )
    scaling_body = _scaling_rows(loaded.runs)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Grafix benchmark schema v4</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 24px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 28px; }}
    th, td {{ border-bottom: 1px solid #d8deea; padding: 7px; text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #f3f6fb; }}
    .hash {{ display: inline-block; max-width: 10rem; overflow: hidden; text-overflow: ellipsis; }}
    .warnings {{ border: 1px solid #e6b95c; background: #fff8e8; padding: 8px 16px; }}
    .pass, .status-ok {{ color: #176b3a; font-weight: 600; }}
    .fail, .status-fail {{ color: #a32929; font-weight: 700; }}
    .soft-fail {{ color: #9a6500; font-weight: 600; }}
    code {{ font-family: ui-monospace, monospace; }}
    small {{ color: #526075; }}
  </style>
</head>
<body>
  <h1>Grafix benchmark schema v4</h1>
  <p>valid runs: {len(loaded.runs)} / warnings: {len(loaded.warnings)}</p>
  <section class="warnings"><strong>Warnings</strong><ul>{warning_items}</ul></section>
  <h2>Runs</h2>
  <table>
    <thead><tr>
      <th>run</th><th>source</th><th>case</th><th>category</th>
      <th>status</th><th>checksum</th><th>contracts</th>
      <th>median ms</th><th>base/head Δ</th><th>MAD ms</th>
      <th>p95 ms</th><th>p99 ms</th><th>RSS delta MiB</th><th>metrics</th>
    </tr></thead>
    <tbody>{table_body}</tbody>
  </table>
  <h2>Scaling curves</h2>
  <table>
    <thead><tr><th>run</th><th>case</th><th>parameters</th><th>median ms</th></tr></thead>
    <tbody>{scaling_body}</tbody>
  </table>
</body>
</html>
"""


def _milliseconds(value: float) -> str:
    return f"{value / 1_000_000.0:.6f}"


def _status_class(status: str) -> str:
    return "status-ok" if status == "ok" else "status-fail"


def _contract_summary(hard: list, soft: list) -> str:
    parts: list[str] = []
    for severity, contracts in (("hard", hard), ("soft", soft)):
        if not contracts:
            parts.append(f"{severity}: none")
            continue
        failed = [contract for contract in contracts if not contract.passed]
        css_class = (
            "pass"
            if not failed
            else ("fail" if severity == "hard" else "soft-fail")
        )
        label = "PASS" if not failed else "FAIL"
        title = "; ".join(
            f"{contract.contract_id}: {contract.reason}"
            for contract in failed
        )
        parts.append(
            f'{severity}: <span class="{css_class}" title="{escape(title)}">'
            f"{label} ({len(contracts) - len(failed)}/{len(contracts)})</span>"
        )
        parts.extend(
            (
                f"<small><code>{escape(contract.contract_id)}</code>: "
                f"actual={escape(str(contract.actual))} "
                f"{escape(contract.comparator)} "
                f"limit={escape(str(contract.limit))}</small>"
            )
            for contract in contracts
        )
    return "<br>".join(parts)


def _metrics_summary(metrics: tuple[Metric, ...]) -> str:
    rendered: list[str] = []
    ordered = sorted(
        enumerate(metrics),
        key=lambda item: (_metric_summary_priority(item[1]), item[0]),
    )
    for _, metric in ordered[:8]:
        if metric.distribution is not None:
            value = metric.distribution.median
            label = "median"
        else:
            value = metric.value
            label = "value"
        rendered.append(
            f"<code>{escape(metric.name)}</code> "
            f"{label}={escape(str(value))} {escape(metric.unit)} "
            f"<small>[{escape(metric.phase)}/{escape(metric.scope)}]</small>"
        )
    if len(metrics) > 8:
        rendered.append(f"<small>+{len(metrics) - 8} metrics</small>")
    return "<br>".join(rendered)


def _measurement_compatible(
    base_run: BenchmarkRun,
    base_result: CaseResult,
    head_run: BenchmarkRun,
    head_result: CaseResult,
) -> bool:
    """HTML の delta に必要な計測 mode/settings の互換性を判定する。"""

    if base_run.meta.mode != head_run.meta.mode:
        return False
    fields = (
        ("disable_gc", "timeout_seconds")
        if base_result.spec.self_sampling and head_result.spec.self_sampling
        else (
            "samples",
            "warmup",
            "target_ns",
            "disable_gc",
            "timeout_seconds",
        )
    )
    return all(
        getattr(base_run.meta, field) == getattr(head_run.meta, field)
        for field in fields
    )


def _metric_summary_priority(metric: Metric) -> int:
    """操作感を直接表す主要 UX metric を先頭へ寄せる。"""

    normalized = metric.name.lower().replace("_", ".")
    priorities = (
        "input.to.present",
        "fresh.ratio",
        "revision.lag",
        "changed.frame.total",
    )
    for priority, marker in enumerate(priorities):
        if marker in normalized:
            return priority
    return len(priorities)


def _scaling_rows(runs: tuple[BenchmarkRun, ...]) -> str:
    rows: list[str] = []
    for run in runs:
        for result in run.cases:
            if "scaling" not in result.spec.tags:
                continue
            median_ms = (
                ""
                if result.stats is None
                else _milliseconds(result.stats.median_ns)
            )
            rows.append(
                "<tr>"
                f"<td>{escape(run.meta.run_id)}</td>"
                f"<td><code>{escape(result.spec.case_id)}</code></td>"
                f"<td><code>{escape(json.dumps(result.spec.parameters, sort_keys=True))}</code></td>"
                f"<td>{median_ms}</td>"
                "</tr>"
            )
    return "\n".join(rows) or '<tr><td colspan="4">scaling case はありません。</td></tr>'


__all__ = ["LoadedRuns", "load_runs", "render_report_html", "write_report"]
