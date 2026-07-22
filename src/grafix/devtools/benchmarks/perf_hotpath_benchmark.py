"""PerfCollector の causal backlog 照合を分離して測る benchmark。"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grafix.devtools.benchmarks.definition import CaseDefinition, define_case
from grafix.devtools.benchmarks.schema import (
    BenchmarkOutput,
    ContractResult,
    Metric,
    evaluate_contract,
    summarize_distribution,
)
from grafix.interactive.runtime.perf import PerfCollector

_SCOPE = "runtime-perf-causal-backlog"


def case_definitions() -> tuple[CaseDefinition, ...]:
    """PerfCollector causal backlog の scaling cases を返す。"""

    return tuple(
        define_case(
            f"runtime.perf.causal_backlog.pending_{pending}",
            f"PerfCollector causal backlog ({pending:,} pending)",
            category="runtime",
            suite="parameters",
            fixture="ordered_causal_revisions",
            parameters={"pending": pending, "samples": 24},
            tags=("PERF-04", "causal-backlog", "exact-checksum"),
            selectable_suites=selectable_suites,
            setup=setup_perf_backlog_scenario,
            workload=workload_perf_backlog_scenario,
            support_source_files=(Path(__file__),),
            self_sampling=True,
        )
        for pending, selectable_suites in (
            (100, ("parameters",)),
            (1_000, ("parameters",)),
            (4_096, ("parameters", "soak")),
        )
    )


def setup_perf_backlog_scenario(
    parameters: dict[str, Any],
    _seed: int,
) -> object:
    """Perf backlog scenario を構築する。"""

    return make_perf_backlog_scenario(parameters)


def workload_perf_backlog_scenario(state: object) -> BenchmarkOutput:
    """Perf backlog scenario を一回実行する。"""

    if not isinstance(state, PerfBacklogScenario):
        raise TypeError("perf backlog scenario state is invalid")
    return run_perf_backlog_scenario(state)


@dataclass(frozen=True, slots=True)
class PerfBacklogScenario:
    """causal pending 件数と self-sampling 回数。"""

    pending: int
    samples: int


def make_perf_backlog_scenario(parameters: dict[str, Any]) -> PerfBacklogScenario:
    """JSON-compatible parameter から scenario を返す。"""

    pending = int(parameters["pending"])
    samples = int(parameters.get("samples", 24))
    if pending < 1:
        raise ValueError("pending は 1 以上である必要があります")
    if samples < 1:
        raise ValueError("samples は 1 以上である必要があります")
    return PerfBacklogScenario(pending=pending, samples=samples)


def run_perf_backlog_scenario(
    scenario: PerfBacklogScenario,
) -> BenchmarkOutput:
    """future/prefix/all の照合時間と pending semantic を返す。"""

    future_ms: list[float] = []
    prefix_ms: list[float] = []
    all_ms: list[float] = []
    future_remaining = -1
    prefix_remaining = -1
    all_remaining = -1
    prefix_count = max(1, scenario.pending // 10)

    for _ in range(scenario.samples):
        future = _collector_with_pending(scenario.pending)
        started = time.perf_counter_ns()
        future.record_event(
            "preview_presented",
            revision=0,
            timestamp_ns=scenario.pending + 10_000,
        )
        future_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        future_remaining = len(future._input_created_ns)

        prefix = _collector_with_pending(scenario.pending)
        started = time.perf_counter_ns()
        prefix.record_event(
            "preview_presented",
            revision=prefix_count,
            timestamp_ns=scenario.pending + 10_000,
        )
        prefix_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        prefix_remaining = len(prefix._input_created_ns)

        matched_all = _collector_with_pending(scenario.pending)
        started = time.perf_counter_ns()
        matched_all.record_event(
            "preview_presented",
            revision=scenario.pending,
            timestamp_ns=scenario.pending + 10_000,
        )
        all_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        all_remaining = len(matched_all._input_created_ns)

    future_distribution = summarize_distribution(future_ms)
    future_p95 = (
        future_distribution.p95 if future_distribution.p95 is not None else future_distribution.max
    )
    assert future_p95 is not None
    future_bounds = _revision_bounds(future._input_created_ns)
    prefix_bounds = _revision_bounds(prefix._input_created_ns)
    future_latency_count = len(future._input_to_present_ns)
    prefix_latency_count = len(prefix._input_to_present_ns)
    all_latency_count = len(matched_all._input_to_present_ns)
    latency_limit = int(matched_all._input_to_present_ns.maxlen or 0)
    drop_counts = (
        future._latency_sample_drop_count,
        prefix._latency_sample_drop_count,
        matched_all._latency_sample_drop_count,
    )
    semantic_digest = hashlib.sha256(
        repr(
            (
                future_bounds,
                prefix_bounds,
                future_latency_count,
                prefix_latency_count,
                all_latency_count,
                future._causal_input_drop_count,
                prefix._causal_input_drop_count,
                matched_all._causal_input_drop_count,
                drop_counts,
            )
        ).encode("utf-8")
    ).hexdigest()
    expected_semantic_digest = hashlib.sha256(
        repr(
            (
                (1, scenario.pending),
                (prefix_count + 1, scenario.pending),
                0,
                min(prefix_count, latency_limit),
                min(scenario.pending, latency_limit),
                0,
                0,
                0,
                (
                    0,
                    max(0, prefix_count - latency_limit),
                    max(0, scenario.pending - latency_limit),
                ),
            )
        ).encode("utf-8")
    ).hexdigest()
    return BenchmarkOutput(
        value={
            "pending": scenario.pending,
            "samples": scenario.samples,
            "prefix_count": prefix_count,
            "future_remaining": future_remaining,
            "prefix_remaining": prefix_remaining,
            "all_remaining": all_remaining,
            "future_bounds": (None if future_bounds is None else list(future_bounds)),
            "prefix_bounds": (None if prefix_bounds is None else list(prefix_bounds)),
            "latency_counts": [
                future_latency_count,
                prefix_latency_count,
                all_latency_count,
            ],
            "latency_drop_counts": list(drop_counts),
            "semantic_digest": semantic_digest,
        },
        metrics=(
            _distribution("perf.causal_backlog.future", future_ms),
            _distribution("perf.causal_backlog.prefix_10pct", prefix_ms),
            _distribution("perf.causal_backlog.all", all_ms),
            _gauge("perf.causal_backlog.pending", scenario.pending),
        ),
        contracts=(
            _contract(
                "perf.causal_backlog.future_preserved",
                "hard",
                future_remaining,
                "eq",
                scenario.pending,
                "future head must stop without consuming pending revisions",
            ),
            _contract(
                "perf.causal_backlog.prefix_exact",
                "hard",
                prefix_remaining,
                "eq",
                scenario.pending - prefix_count,
                "presented revision must consume exactly the ordered prefix",
            ),
            _contract(
                "perf.causal_backlog.all_exact",
                "hard",
                all_remaining,
                "eq",
                0,
                "latest presented revision must consume all pending inputs",
            ),
            _contract(
                "perf.causal_backlog.semantic_state_exact",
                "hard",
                semantic_digest,
                "eq",
                expected_semantic_digest,
                "revision bounds, latency order, and bounded drop counts must match",
            ),
            _contract(
                "perf.causal_backlog.future_reference_p95",
                "soft",
                float(future_p95),
                "le",
                0.02,
                "reference target for a future head is 0.02 ms p95",
            ),
        ),
    )


def _revision_bounds(
    pending: OrderedDict[int, int],
) -> tuple[int, int] | None:
    keys = pending.keys()
    if not keys:
        return None
    return int(next(iter(keys))), int(next(reversed(keys)))


def _collector_with_pending(count: int) -> PerfCollector:
    collector = PerfCollector(
        enabled=True,
        console_output=False,
        print_every=10_000,
    )
    for revision in range(1, int(count) + 1):
        collector.record_event(
            "parameter_revision_created",
            revision=revision,
            timestamp_ns=revision,
        )
    return collector


def _distribution(name: str, samples: list[float]) -> Metric:
    return Metric(
        name=name,
        kind="distribution",
        unit="ms",
        phase="measure",
        scope=_SCOPE,
        distribution=summarize_distribution(samples),
    )


def _gauge(name: str, value: int) -> Metric:
    return Metric(
        name=name,
        kind="gauge",
        unit="count",
        phase="measure",
        scope=_SCOPE,
        value=int(value),
    )


def _contract(
    contract_id: str,
    severity: str,
    actual: object,
    comparator: str,
    limit: object,
    reason: str,
) -> ContractResult:
    return evaluate_contract(
        contract_id=contract_id,
        severity=severity,
        actual=actual,
        comparator=comparator,
        limit=limit,
        reason=reason,
    )


__all__ = [
    "case_definitions",
    "PerfBacklogScenario",
    "make_perf_backlog_scenario",
    "run_perf_backlog_scenario",
]
