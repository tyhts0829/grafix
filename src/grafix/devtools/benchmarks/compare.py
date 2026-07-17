"""schema v3 benchmark run の互換性検査と比較。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grafix.devtools.benchmarks.schema import BenchmarkRun, read_benchmark_run


class IncompatibleBenchmarkError(ValueError):
    """既定では比較してはいけない run/case の組を表す。"""


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    """機械可読な benchmark 比較結果。"""

    base_run_id: str
    head_run_id: str
    environment_compatible: bool
    rows: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


def compare_run_files(
    base_path: str | Path,
    head_path: str | Path,
    *,
    allow_incompatible: bool = False,
) -> BenchmarkComparison:
    """2 run を読み、source identity を無視して同一環境・case を比較する。"""

    base = read_benchmark_run(base_path)
    head = read_benchmark_run(head_path)
    return compare_runs(base, head, allow_incompatible=allow_incompatible)


def compare_runs(
    base: BenchmarkRun,
    head: BenchmarkRun,
    *,
    allow_incompatible: bool = False,
) -> BenchmarkComparison:
    """2 run の中央値比と checksum 一致を返す。"""

    warnings: list[str] = []
    environment_compatible = (
        base.environment.compatibility_key
        == head.environment.compatibility_key
    )
    if not environment_compatible:
        warnings.append("environment compatibility key differs")
    if base.meta.mode != head.meta.mode:
        warnings.append(
            f"measurement mode differs: {base.meta.mode} != {head.meta.mode}"
        )
        environment_compatible = False
    measurement_fields = (
        "samples",
        "warmup",
        "target_ns",
        "disable_gc",
        "timeout_seconds",
    )
    differing_measurements = [
        name
        for name in measurement_fields
        if getattr(base.meta, name) != getattr(head.meta, name)
    ]
    if differing_measurements:
        warnings.append(
            "measurement settings differ: "
            + ", ".join(differing_measurements)
        )
        environment_compatible = False
    if not environment_compatible and not allow_incompatible:
        raise IncompatibleBenchmarkError("; ".join(warnings))

    base_cases = {result.spec.case_id: result for result in base.cases}
    head_cases = {result.spec.case_id: result for result in head.cases}
    missing_head = sorted(set(base_cases) - set(head_cases))
    missing_base = sorted(set(head_cases) - set(base_cases))
    if missing_head:
        warnings.append(f"head is missing cases: {', '.join(missing_head)}")
    if missing_base:
        warnings.append(f"base is missing cases: {', '.join(missing_base)}")
    if (missing_head or missing_base) and not allow_incompatible:
        raise IncompatibleBenchmarkError("; ".join(warnings))

    rows: list[dict[str, Any]] = []
    incompatible_cases: list[str] = []
    for case_id in sorted(set(base_cases) & set(head_cases)):
        base_result = base_cases[case_id]
        head_result = head_cases[case_id]
        case_compatible = (
            base_result.spec.compatibility_key
            == head_result.spec.compatibility_key
        )
        if not case_compatible:
            incompatible_cases.append(case_id)
            if not allow_incompatible:
                continue
        base_ns = (
            None if base_result.stats is None else base_result.stats.median_ns
        )
        head_ns = (
            None if head_result.stats is None else head_result.stats.median_ns
        )
        ratio = (
            None
            if base_ns is None or head_ns is None or base_ns <= 0.0
            else head_ns / base_ns
        )
        checksum_kind_equal = (
            base_result.checksum_kind is not None
            and base_result.checksum_kind == head_result.checksum_kind
        )
        rows.append(
            {
                "case_id": case_id,
                "label": head_result.spec.label,
                "compatible": case_compatible,
                "base_status": base_result.status,
                "head_status": head_result.status,
                "base_median_ns": base_ns,
                "head_median_ns": head_ns,
                "ratio": ratio,
                "checksum_equal": (
                    checksum_kind_equal
                    and
                    base_result.checksum is not None
                    and base_result.checksum == head_result.checksum
                ),
                "checksum_kind_equal": checksum_kind_equal,
                "base_checksum_kind": base_result.checksum_kind,
                "head_checksum_kind": head_result.checksum_kind,
                "base_peak_rss_delta_bytes": base_result.peak_rss_delta_bytes,
                "head_peak_rss_delta_bytes": head_result.peak_rss_delta_bytes,
            }
        )
    if incompatible_cases:
        warnings.append(
            "case compatibility key differs: "
            + ", ".join(incompatible_cases)
        )
        if not allow_incompatible:
            raise IncompatibleBenchmarkError("; ".join(warnings))

    return BenchmarkComparison(
        base_run_id=base.meta.run_id,
        head_run_id=head.meta.run_id,
        environment_compatible=environment_compatible,
        rows=tuple(rows),
        warnings=tuple(warnings),
    )


__all__ = [
    "BenchmarkComparison",
    "IncompatibleBenchmarkError",
    "compare_run_files",
    "compare_runs",
]
