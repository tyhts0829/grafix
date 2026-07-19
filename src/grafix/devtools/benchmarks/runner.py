"""Case registry と fresh-process benchmark runner。"""

from __future__ import annotations

import dataclasses
import gc
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

import numpy as np

from grafix.core.atomic_write import atomic_write_text
from grafix.core.geometry import Geometry
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.resource_budget import ResourceLimitError
from grafix.devtools.benchmarks.environment import make_case_spec
from grafix.devtools.benchmarks.schema import (
    CaseResult,
    CaseSpec,
    ContractResult,
    Distribution,
    Metric,
    Sample,
    case_result_from_dict,
    case_result_to_dict,
    evaluate_contract,
    summarize_distribution,
    summarize_samples,
)

_DEFAULT_TIMEOUT_SECONDS = 120.0
_MAX_CALIBRATION_ITERATIONS = 1 << 20
_CASES_SOURCE_FILE = Path(__file__).with_name("cases.py")
_SYSTEM_SOURCE_FILE = Path(__file__).with_name("system_benchmark.py")
_MP_SOURCE_FILE = Path(__file__).with_name("mp_draw_benchmark.py")
_INTERACTIVE_SCENARIO_SOURCE_FILE = Path(__file__).with_name(
    "interactive_scenario_benchmark.py"
)
_PARAMETER_EDIT_SOURCE_FILE = Path(__file__).with_name(
    "parameter_edit_benchmark.py"
)
_PARAMETER_HOTPATH_SOURCE_FILE = Path(__file__).with_name(
    "parameter_hotpath_benchmark.py"
)
_PERF_HOTPATH_SOURCE_FILE = Path(__file__).with_name(
    "perf_hotpath_benchmark.py"
)
_PRIMITIVE_SOURCE_FILE = Path(__file__).with_name("primitive_benchmark.py")
_REMAINING_EFFECT_SOURCE_FILE = Path(__file__).with_name(
    "remaining_effect_benchmark.py"
)
_HEAVY_EFFECT_FINAL_CHECKSUMS = {
    "growth": "88db2188d515eb8320998e5613ca66f5ce773842ae0318ba834ff3c1f2d7db35",
    "metaball": "1df0d8425ddd1f520de5a984eba822ee063fb080a4ae04f7b95a9317610177fd",
    "reaction_diffusion": (
        "b012b5cdb123b635ce475180ba7b12099f7c761c4d0833f4e499044c9d142d40"
    ),
}
_HEAVY_EFFECT_DRAFT_CHECKSUMS = {
    "growth": "74f2b9d7186860a848bc2df2eecb99049f805926b5760da6a2ff81275e77850f",
    "metaball": "06ef8acbe6cc943a3d7e0dce65cc783ca3febecc7e83a805c7399711fdadf8ae",
    "reaction_diffusion": (
        "1d04f1417005b3409b8bc35a1e3fdcd689aa04b3433afa6d4c5ed0c85d509f3b"
    ),
}


@dataclass(frozen=True, slots=True)
class CaseDefinition:
    """Process 間で case ID から再構築できる静的定義。"""

    case_id: str
    version: int
    label: str
    category: str
    suite: str
    fixture: str
    parameters: dict[str, Any]
    tags: tuple[str, ...]
    selectable_suites: tuple[str, ...]
    setup: Callable[[dict[str, Any], int], object]
    workload: Callable[[object], object]
    postprocess: Callable[[object, object], "_CaseOutput"] | None = None
    measurement_context: (
        Callable[[object], AbstractContextManager[object]] | None
    ) = None
    support_source_files: tuple[Path, ...] = ()
    support_implementations: tuple[Callable[..., object], ...] = ()
    checksum_policy: str = "exact"
    self_sampling: bool = False

    def spec(self, *, seed: int) -> CaseSpec:
        implementations: tuple[Callable[..., object], ...] = (
            self.setup,
            self.workload,
            *((self.postprocess,) if self.postprocess is not None else ()),
            *(
                (self.measurement_context,)
                if self.measurement_context is not None
                else ()
            ),
            *self.support_implementations,
        )
        return make_case_spec(
            case_id=self.case_id,
            version=self.version,
            label=self.label,
            category=self.category,
            suite=self.suite,
            fixture=self.fixture,
            parameters=self.parameters,
            seed=seed,
            implementation=implementations,
            support_source_files=self.support_source_files,
            tags=self.tags,
            checksum_policy=self.checksum_policy,
            self_sampling=self.self_sampling,
        )


@dataclass(frozen=True, slots=True)
class _CaseOutput:
    value: object
    metrics: dict[str, Any] | tuple[Metric, ...] = field(default_factory=dict)
    contracts: tuple[ContractResult, ...] = ()


def case_definitions() -> tuple[CaseDefinition, ...]:
    """組み込み benchmark case を安定順で返す。"""

    definitions = [
        _definition(
            "effect.translate.line_small",
            "translate / 2 vertices",
            category="effect",
            suite="micro",
            fixture="line_small",
            parameters={"effect": "translate", "delta": [12.0, 5.0, 0.0]},
            tags=("unary", "small", "exact-checksum"),
            selectable_suites=("smoke", "micro", "effects"),
            setup=_setup_effect,
            workload=_workload_effect,
            support_source_files=(_CASES_SOURCE_FILE,),
            support_implementations=(
                _effect_metrics,
                _diagnostic_effective_value,
            ),
        ),
        _definition(
            "effect.rotate.polyline_long",
            "rotate / 50k vertices",
            category="effect",
            suite="micro",
            fixture="polyline_long",
            parameters={"effect": "rotate", "rotation": [10.0, 20.0, 5.0]},
            tags=("unary", "large", "exact-checksum"),
            selectable_suites=("micro", "effects"),
            setup=_setup_effect,
            workload=_workload_effect,
            support_source_files=(_CASES_SOURCE_FILE,),
            support_implementations=(
                _effect_metrics,
                _diagnostic_effective_value,
            ),
        ),
        *_effect_definitions(),
        *_target_effect_speedup_definitions(),
        *_remaining_effect_definitions(),
        *_primitive_definitions(),
        *_scaled_definitions(
            prefix="runtime.provenance",
            label="stable parameter provenance",
            values=(100, 1_000, 5_000),
            parameter_name="rows",
            category="runtime",
            suite="pipeline",
            fixture="parameter_store",
            setup=_setup_provenance,
            workload=_workload_provenance,
            suites=(("smoke", "pipeline"), ("pipeline",), ("soak",)),
            support_source_files=(_SYSTEM_SOURCE_FILE,),
            support_implementations=(_benchmark_draw,),
        ),
        _definition(
            "runtime.provenance_changed.rows_1000",
            "changed parameter provenance (1,000)",
            category="runtime",
            suite="pipeline",
            fixture="parameter_store",
            parameters={"rows": 1_000, "changes_per_iteration": 2},
            tags=("changed", "exact-checksum"),
            selectable_suites=("pipeline",),
            setup=_setup_provenance_changed,
            workload=_workload_provenance_changed,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
            support_implementations=(_benchmark_draw,),
        ),
        *_scaled_definitions(
            prefix="gui.parameter_table",
            label="parameter table steady view",
            values=(100, 1_000, 10_000),
            parameter_name="rows",
            category="gui",
            suite="gui",
            fixture="parameter_store",
            setup=_setup_parameter_gui,
            workload=_workload_parameter_gui,
            suites=(("smoke", "gui"), ("gui",), ("soak",)),
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        *_parameter_edit_definitions(),
        *_parameter_hotpath_definitions(),
        *_perf_hotpath_definitions(),
        *_scaled_definitions(
            prefix="core.concat_recipe",
            label="repeated Geometry +",
            values=(10, 1_000, 10_000),
            parameter_name="parts",
            category="core",
            suite="micro",
            fixture="line_recipe_sequence",
            setup=_setup_concat_recipe,
            workload=_workload_concat_recipe,
            suites=(("smoke", "micro"), ("micro",), ("soak",)),
        ),
        _definition(
            "core.deep_dag.depth_5000",
            "deep translate DAG realize",
            category="core",
            suite="pipeline",
            fixture="translate_chain",
            parameters={"depth": 5_000},
            tags=("deep-dag", "cache-disabled", "exact-checksum"),
            selectable_suites=("soak",),
            setup=_setup_deep_dag,
            workload=_workload_deep_dag,
        ),
        _definition(
            "pipeline.draw_realize_indices.small",
            "draw → realize → indices",
            category="pipeline",
            suite="pipeline",
            fixture="grid_24",
            parameters={"grid_size": 24},
            tags=("end-to-end", "cpu"),
            selectable_suites=("pipeline",),
            setup=_setup_passthrough,
            workload=_workload_draw_realize_indices,
        ),
        _definition(
            "interactive.slider.input_to_present.rows_32.workers_0",
            "UX-01 hosted slider input-to-present / sync",
            category="interactive",
            suite="interactive",
            fixture="parameter_store_light_scale_slider",
            parameters={
                "rows": 32,
                "workers": 0,
                "warmup_frames": 3,
                "drag_frames": 12,
                "settle_frames": 4,
                "frame_interval_s": 0.0,
                "settle_timeout_s": 1.0,
                "latency_guardrail_ms": 16.667,
            },
            tags=(
                "UX-01",
                "input-to-present",
                "fake-gui",
                "fake-gl",
                "sync",
            ),
            selectable_suites=("smoke", "interactive"),
            setup=_setup_interactive_slider_scenario,
            workload=_workload_interactive_slider_scenario,
            support_source_files=(
                _INTERACTIVE_SCENARIO_SOURCE_FILE,
                _SYSTEM_SOURCE_FILE,
            ),
            self_sampling=True,
        ),
        _definition(
            "interactive.slider.input_to_present.rows_1000.workers_0",
            "UX-01 hosted slider input-to-present / 1,000 rows",
            category="interactive",
            suite="interactive",
            fixture="parameter_store_light_scale_slider",
            parameters={
                "rows": 1_000,
                "workers": 0,
                "warmup_frames": 2,
                "drag_frames": 8,
                "settle_frames": 3,
                "frame_interval_s": 0.0,
                "settle_timeout_s": 1.0,
                "latency_guardrail_ms": 16.667,
            },
            tags=(
                "UX-01",
                "input-to-present",
                "fake-gui",
                "fake-gl",
                "large-parameter-table",
                "sync",
            ),
            selectable_suites=("interactive",),
            setup=_setup_interactive_slider_scenario,
            workload=_workload_interactive_slider_scenario,
            support_source_files=(
                _INTERACTIVE_SCENARIO_SOURCE_FILE,
                _SYSTEM_SOURCE_FILE,
            ),
            self_sampling=True,
        ),
        _definition(
            "interactive.slider.input_to_present.rows_32.workers_1",
            "UX-01 hosted slider input-to-present / 1 worker",
            category="interactive",
            suite="interactive",
            fixture="parameter_store_light_scale_slider",
            parameters={
                "rows": 32,
                "workers": 1,
                "warmup_frames": 4,
                "drag_frames": 12,
                "settle_frames": 6,
                "frame_interval_s": 1.0 / 60.0,
                "settle_timeout_s": 2.0,
                "latency_guardrail_ms": 50.0,
            },
            tags=(
                "UX-01",
                "input-to-present",
                "fake-gui",
                "fake-gl",
                "multiprocessing",
            ),
            selectable_suites=("interactive",),
            setup=_setup_interactive_slider_scenario,
            workload=_workload_interactive_slider_scenario,
            support_source_files=(
                _INTERACTIVE_SCENARIO_SOURCE_FILE,
                _SYSTEM_SOURCE_FILE,
            ),
            self_sampling=True,
        ),
        _definition(
            "interactive.renderer.static_100k",
            "renderer static topology cache",
            category="interactive",
            suite="interactive",
            fixture="100k_two_point_lines",
            parameters={"polylines": 100_000, "frames": 8},
            tags=("renderer", "static", "fake-gl"),
            selectable_suites=("interactive",),
            setup=_setup_renderer,
            workload=_workload_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        _definition(
            "interactive.renderer.animated_coords_static_offsets_100k",
            "renderer animated coordinates / static offsets",
            category="interactive",
            suite="interactive",
            fixture="100k_two_point_lines",
            parameters={"polylines": 100_000, "frames": 12, "topology": "static"},
            tags=("renderer", "animated-coordinates", "static-topology", "fake-gl"),
            selectable_suites=("interactive",),
            setup=_setup_animated_renderer,
            workload=_workload_animated_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        _definition(
            "interactive.renderer.animated_topology_100k",
            "renderer animated topology",
            category="interactive",
            suite="interactive",
            fixture="100k_two_point_lines",
            parameters={"polylines": 100_000, "frames": 12, "topology": "animated"},
            tags=("renderer", "animated-topology", "fake-gl"),
            selectable_suites=("interactive",),
            setup=_setup_animated_renderer,
            workload=_workload_animated_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        _definition(
            "interactive.renderer.static_1m",
            "renderer static topology cache / 1M lines",
            category="interactive",
            suite="interactive",
            fixture="1m_two_point_lines",
            parameters={"polylines": 1_000_000, "frames": 3},
            tags=("renderer", "static", "fake-gl", "large"),
            selectable_suites=("soak",),
            setup=_setup_renderer,
            workload=_workload_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        _definition(
            "interactive.renderer.animated_coords_static_offsets_1m",
            "renderer animated coordinates / static offsets / 1M lines",
            category="interactive",
            suite="interactive",
            fixture="1m_two_point_lines",
            parameters={"polylines": 1_000_000, "frames": 3, "topology": "static"},
            tags=(
                "renderer",
                "animated-coordinates",
                "static-topology",
                "fake-gl",
                "large",
            ),
            selectable_suites=("soak",),
            setup=_setup_animated_renderer,
            workload=_workload_animated_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        _definition(
            "interactive.renderer.animated_topology_1m",
            "renderer animated topology / 1M lines",
            category="interactive",
            suite="interactive",
            fixture="1m_two_point_lines",
            parameters={"polylines": 1_000_000, "frames": 3, "topology": "animated"},
            tags=("renderer", "animated-topology", "fake-gl", "large"),
            selectable_suites=("soak",),
            setup=_setup_animated_renderer,
            workload=_workload_animated_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        ),
        *_multilayer_renderer_definitions(),
        _definition(
            "mp.draw.light",
            "MpDraw light sync / worker",
            category="mp",
            suite="mp",
            fixture="normalized_scene",
            parameters={"repeats": 1, "steady_frames": 8, "heavy_iterations": 1_000},
            tags=("multiprocessing", "draw-normalize"),
            selectable_suites=("mp",),
            setup=_setup_passthrough,
            workload=_workload_mp_draw,
            support_source_files=(_MP_SOURCE_FILE,),
            self_sampling=True,
        ),
        _definition(
            "mp.draw.slider_churn",
            "MpDraw 1-worker slider revision churn",
            category="mp",
            suite="mp",
            fixture="light_translate_scale_slider",
            parameters={"frames": 120, "frame_interval_s": 1.0 / 60.0},
            tags=(
                "multiprocessing",
                "slider",
                "revision-churn",
                "input-to-result",
            ),
            selectable_suites=("mp",),
            setup=_setup_passthrough,
            workload=_workload_mp_slider_churn,
            support_source_files=(_MP_SOURCE_FILE,),
            self_sampling=True,
        ),
        *_legacy_system_definitions(),
    ]
    return tuple(sorted(definitions, key=lambda definition: definition.case_id))


def select_case_definitions(
    *,
    suites: tuple[str, ...],
    case_ids: tuple[str, ...] = (),
) -> tuple[CaseDefinition, ...]:
    """suite または明示 ID で case を選ぶ。未知 ID/suite は拒否する。"""

    definitions = case_definitions()
    by_id = {definition.case_id: definition for definition in definitions}
    if case_ids:
        duplicate_ids = sorted(
            case_id
            for case_id in set(case_ids)
            if case_ids.count(case_id) > 1
        )
        if duplicate_ids:
            raise ValueError(
                "duplicate benchmark case: " + ", ".join(duplicate_ids)
            )
        unknown_ids = sorted(set(case_ids) - set(by_id))
        if unknown_ids:
            raise ValueError(f"unknown benchmark case: {', '.join(unknown_ids)}")
        return tuple(by_id[case_id] for case_id in case_ids)

    available_suites = {
        suite
        for definition in definitions
        for suite in definition.selectable_suites
    } | {"all"}
    unknown_suites = sorted(set(suites) - available_suites)
    if unknown_suites:
        raise ValueError(f"unknown benchmark suite: {', '.join(unknown_suites)}")
    if "all" in suites:
        return definitions
    selected = [
        definition
        for definition in definitions
        if set(suites) & set(definition.selectable_suites)
    ]
    return tuple(selected)


def run_case_isolated(
    definition: CaseDefinition,
    *,
    seed: int,
    mode: str,
    samples: int,
    warmup: int,
    target_ns: int,
    disable_gc: bool,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> CaseResult:
    """1 case を fresh child process で実行する。cold は sample ごとに隔離する。"""

    if mode not in {"warm", "process-cold", "compile-cold"}:
        raise ValueError(f"unknown benchmark mode: {mode}")
    # Scenario workload は内部 frame の raw distribution と全 contract を
    # 1 output に集約する。外側で再実行して最後の output だけを採ると、
    # 先行 run の tail/failure が失われるため常に 1 semantic sample とする。
    sample_count = 1 if definition.self_sampling else max(1, int(samples))
    spec = definition.spec(seed=int(seed))
    if mode == "warm":
        return _run_child(
            definition=definition,
            spec=spec,
            seed=seed,
            mode=mode,
            samples=sample_count,
            warmup=max(0, int(warmup)),
            target_ns=max(0, int(target_ns)),
            disable_gc=disable_gc,
            timeout_seconds=timeout_seconds,
        )

    results = [
        _run_child(
            definition=definition,
            spec=spec,
            seed=seed,
            mode=mode,
            samples=1,
            warmup=0,
            target_ns=0,
            disable_gc=disable_gc,
            timeout_seconds=timeout_seconds,
        )
        for _ in range(sample_count)
    ]
    return _merge_cold_results(spec=spec, results=results)


def geometry_checksum(geometry: RealizedGeometry) -> str:
    """Geometry arrays を dtype・shape・bytes 込みで SHA-256 化する。"""

    digest = hashlib.sha256()
    digest.update(b"grafix.realized-geometry.checksum.v1\0")
    _hash_array(digest, geometry.coords)
    _hash_array(digest, geometry.offsets)
    return digest.hexdigest()


def canonical_checksum(value: object) -> tuple[str, str]:
    """benchmark output を exact checksum 化する。"""

    if isinstance(value, RealizedGeometry):
        return geometry_checksum(value), "realized_geometry_exact_v1"
    if isinstance(value, Geometry):
        digest = hashlib.sha256(b"grafix.geometry.concat-semantics.v1\0")
        stack = [value]
        leaf_count = 0
        while stack:
            geometry = stack.pop()
            if geometry.op == "concat" and not geometry.args:
                stack.extend(reversed(geometry.inputs))
                continue
            digest.update(geometry.id.encode("ascii"))
            leaf_count += 1
        digest.update(leaf_count.to_bytes(8, "big"))
        return digest.hexdigest(), "geometry_concat_leaf_order_v1"
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], np.ndarray)
        and isinstance(value[1], np.ndarray)
    ):
        realized = RealizedGeometry(coords=value[0], offsets=value[1])
        return geometry_checksum(realized), "realized_geometry_exact_v1"
    normalized = _json_value(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), "canonical_json_sha256_v1"


def normalize_metrics(
    metrics: dict[str, Any] | tuple[Metric, ...],
) -> tuple[Metric, ...]:
    """旧 workload の mapping を schema v4 の typed metric へ正規化する。

    workload は段階的に Metric を直接返せる。mapping を返す既存 case は runner
    境界で再帰的に平坦化し、統計 summary は distribution として認識する。
    """

    if isinstance(metrics, tuple):
        if not all(isinstance(metric, Metric) for metric in metrics):
            raise TypeError("typed metrics tuple must contain Metric values")
        return metrics
    normalized = _json_value(metrics)
    if not isinstance(normalized, dict):
        raise TypeError("benchmark metrics must be a mapping or Metric tuple")
    output: list[Metric] = []

    def visit(name: str, value: object) -> None:
        if isinstance(value, dict):
            distribution = _distribution_from_summary(value)
            if distribution is not None:
                output.append(
                    Metric(
                        name=name,
                        kind="distribution",
                        unit=_infer_metric_unit(name, value=None),
                        phase=_infer_metric_phase(name),
                        scope=_infer_metric_scope(name),
                        distribution=distribution,
                    )
                )
                return
            if not value:
                output.append(_gauge_metric(name, value))
                return
            for child_name, child_value in sorted(value.items()):
                visit(
                    f"{name}.{child_name}" if name else str(child_name),
                    child_value,
                )
            return
        if isinstance(value, list) and value and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value
        ):
            output.append(
                Metric(
                    name=name,
                    kind="distribution",
                    unit=_infer_metric_unit(name, value=None),
                    phase=_infer_metric_phase(name),
                    scope=_infer_metric_scope(name),
                    distribution=summarize_distribution(
                        [float(item) for item in value]
                    ),
                )
            )
            return
        if _is_counter(name, value):
            output.append(
                Metric(
                    name=name,
                    kind="counter",
                    unit=_infer_metric_unit(name, value=value),
                    phase=_infer_metric_phase(name),
                    scope=_infer_metric_scope(name),
                    value=value,
                )
            )
            return
        output.append(_gauge_metric(name, value))

    for metric_name, metric_value in sorted(normalized.items()):
        visit(str(metric_name), metric_value)
    return tuple(output)


def _distribution_from_summary(value: dict[str, Any]) -> Distribution | None:
    count_value = value.get("count", value.get("n"))
    has_summary = any(
        key in value
        for key in ("min", "max", "median", "mad", "p95", "p99", "mean")
    )
    if (
        not isinstance(count_value, int)
        or isinstance(count_value, bool)
        or count_value < 0
        or not has_summary
    ):
        return None
    raw = value.get("raw_samples", value.get("samples", ()))
    if isinstance(raw, list) and raw and all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        for item in raw
    ):
        return summarize_distribution([float(item) for item in raw])
    if count_value == 0:
        return Distribution(
            count=0,
            min=None,
            max=None,
            median=None,
            mad=None,
            p95=None,
            p99=None,
            mean=None,
        )

    def optional_stat(name: str) -> float | None:
        candidate = value.get(name)
        if (
            candidate is None
            or not isinstance(candidate, (int, float))
            or isinstance(candidate, bool)
        ):
            return None
        return float(candidate)

    return Distribution(
        count=count_value,
        min=optional_stat("min"),
        max=optional_stat("max"),
        median=optional_stat("median"),
        mad=optional_stat("mad"),
        p95=optional_stat("p95"),
        p99=optional_stat("p99"),
        mean=optional_stat("mean"),
    )


def _gauge_metric(name: str, value: object) -> Metric:
    scalar = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if value is None or isinstance(value, (dict, list))
        else value
    )
    return Metric(
        name=name,
        kind="gauge",
        unit=_infer_metric_unit(name, value=scalar),
        phase=_infer_metric_phase(name),
        scope=_infer_metric_scope(name),
        value=scalar,
    )


def _infer_metric_phase(name: str) -> str:
    lowered = f".{name.lower()}."
    if ".changing." in lowered or ".drag." in lowered:
        return "drag"
    if ".stable." in lowered or ".settle." in lowered:
        return "settle"
    if ".warmup." in lowered:
        return "warmup"
    return "measure"


def _infer_metric_scope(name: str) -> str:
    return "scenario" if name.startswith("cases.") else "case"


def _infer_metric_unit(name: str, *, value: object) -> str:
    lowered = name.lower()
    leaf = lowered.rsplit(".", 1)[-1]
    if leaf.endswith("_ns") or "_ns_" in leaf:
        return "ns"
    if leaf.endswith("_ms") or "_ms_" in leaf:
        return "ms"
    if "fps" in leaf:
        return "frames_per_second"
    if "byte" in leaf:
        return "bytes"
    if "ratio" in leaf:
        return "ratio"
    if "revision_lag" in leaf:
        return "revisions"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "text"
    if _is_counter(name, value):
        return "count"
    return "unitless"


def _is_counter(name: str, value: object) -> bool:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not np.isfinite(float(value))
        or float(value) < 0.0
    ):
        return False
    leaf = name.lower().rsplit(".", 1)[-1]
    return (
        leaf == "n"
        or leaf.startswith("n_")
        or any(
            token in leaf
            for token in (
                "bytes",
                "count",
                "entries",
                "evictions",
                "frames",
                "hits",
                "misses",
                "results",
                "tasks",
                "uploads",
                "vertices",
                "lines",
                "workers",
                "builds",
                "calls",
                "iterations",
                "parts",
                "rows",
            )
        )
    )


def _run_child(
    *,
    definition: CaseDefinition,
    spec: CaseSpec,
    seed: int,
    mode: str,
    samples: int,
    warmup: int,
    target_ns: int,
    disable_gc: bool,
    timeout_seconds: float,
) -> CaseResult:
    request = {
        "case_id": definition.case_id,
        "seed": int(seed),
        "mode": mode,
        "samples": int(samples),
        "warmup": int(warmup),
        "target_ns": int(target_ns),
        "disable_gc": bool(disable_gc),
    }
    with tempfile.TemporaryDirectory(prefix="grafix-benchmark-") as temp_name:
        temp = Path(temp_name)
        request_path = temp / "request.json"
        result_path = temp / "result.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = "0"
        environment["PYTHONPYCACHEPREFIX"] = str(temp / "pycache")
        if mode == "compile-cold":
            cache_dir = temp / "numba-cache"
            cache_dir.mkdir()
            environment["NUMBA_CACHE_DIR"] = str(cache_dir)
        try:
            completed = _run_isolated_process(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys;"
                        "from grafix.devtools.benchmarks.runner import _main;"
                        "raise SystemExit(_main(sys.argv[1:]))"
                    ),
                    "--child",
                    str(request_path),
                    str(result_path),
                ],
                timeout=float(timeout_seconds),
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return CaseResult(
                spec=spec,
                status="timeout",
                error=f"case exceeded {float(timeout_seconds):g}s",
            )
        if completed.returncode != 0 or not result_path.is_file():
            detail = completed.stderr.strip() or completed.stdout.strip()
            if len(detail) > 2_000:
                detail = detail[-2_000:]
            return CaseResult(
                spec=spec,
                status="error",
                error=(
                    f"child exited with code {completed.returncode}"
                    + (f": {detail}" if detail else "")
                ),
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            return _validated_child_result(payload, expected_spec=spec)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return CaseResult(
                spec=spec,
                status="error",
                error=f"invalid child result: {type(exc).__name__}: {exc}",
            )


def _validated_child_result(
    payload: object,
    *,
    expected_spec: CaseSpec,
) -> CaseResult:
    """child payload が request 時の case identity と完全一致することを確認する。"""

    result = case_result_from_dict(payload)
    if result.spec != expected_spec:
        raise ValueError("child result case spec differs from request")
    return result


def _run_isolated_process(
    command: list[str],
    *,
    timeout: float,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """新しい process group で実行し、timeout 時は子孫をまとめて終了する。"""

    process = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout,
        stderr,
    )


def _child_main(request_path: Path, result_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    case_id = str(request["case_id"])
    definitions = {definition.case_id: definition for definition in case_definitions()}
    if case_id not in definitions:
        raise ValueError(f"unknown benchmark case: {case_id}")
    definition = definitions[case_id]
    seed = int(request["seed"])
    spec = definition.spec(seed=seed)
    result = _measure_in_process(
        definition,
        spec=spec,
        seed=seed,
        mode=str(request["mode"]),
        samples=max(1, int(request["samples"])),
        warmup=max(0, int(request["warmup"])),
        target_ns=max(0, int(request["target_ns"])),
        disable_gc=bool(request["disable_gc"]),
    )
    atomic_write_text(
        result_path,
        json.dumps(
            case_result_to_dict(result),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
    )
    return 0


def _measure_in_process(
    definition: CaseDefinition,
    *,
    spec: CaseSpec,
    seed: int,
    mode: str,
    samples: int,
    warmup: int,
    target_ns: int,
    disable_gc: bool,
) -> CaseResult:
    context: AbstractContextManager[object] | None = None
    context_entered = False
    try:
        state = definition.setup(dict(definition.parameters), int(seed))
        if definition.measurement_context is not None:
            context = definition.measurement_context(state)
            context.__enter__()
            context_entered = True
        setup_rss = _peak_rss_bytes()
        if definition.self_sampling:
            iterations = 1
            samples = 1
        elif mode == "warm":
            for _ in range(warmup):
                definition.workload(state)
            iterations = _calibrate(
                definition.workload,
                state,
                target_ns=target_ns,
            )
        else:
            iterations = 1

        baseline_rss = _peak_rss_bytes()
        raw_samples: list[Sample] = []
        measured_outputs: list[_CaseOutput] = []
        semantic_checksum: tuple[str, str] | None = None
        output: _CaseOutput | None = None
        raw_output: object | None = None
        was_gc_enabled = gc.isenabled()
        if disable_gc and was_gc_enabled:
            gc.disable()
        try:
            for _ in range(samples):
                started = time.perf_counter_ns()
                for _iteration in range(iterations):
                    raw_output = definition.workload(state)
                raw_samples.append(
                    Sample(
                        elapsed_ns=time.perf_counter_ns() - started,
                        iterations=iterations,
                    )
                )
                if raw_output is None:
                    raise RuntimeError("benchmark workload returned no output")
                output = _postprocess_case_output(
                    definition,
                    state=state,
                    raw_output=raw_output,
                )
                measured_outputs.append(
                    _CaseOutput(
                        value=None,
                        metrics=(
                            output.metrics
                            if isinstance(output.metrics, tuple)
                            else {}
                        ),
                        contracts=output.contracts,
                    )
                )
                current_checksum = canonical_checksum(output.value)
                if semantic_checksum is None:
                    semantic_checksum = current_checksum
                elif current_checksum != semantic_checksum:
                    raise RuntimeError(
                        "warm samples produced different output checksums"
                    )
        finally:
            if disable_gc and was_gc_enabled:
                gc.enable()
        if output is None:
            raise RuntimeError("benchmark workload returned no output")
        output = _aggregate_measured_outputs(
            measured_outputs,
            last=output,
        )
        peak_rss = _peak_rss_bytes()
        assert semantic_checksum is not None
        checksum, checksum_kind = semantic_checksum
        metrics = normalize_metrics(output.metrics)
        failed_hard = tuple(
            contract
            for contract in output.contracts
            if contract.severity == "hard" and not contract.passed
        )
        status = "contract-failure" if failed_hard else "ok"
        contract_error = (
            "failed hard contracts: "
            + "; ".join(
                f"{contract.contract_id}: {contract.reason}"
                for contract in failed_hard
            )
            if failed_hard
            else None
        )
        return CaseResult(
            spec=spec,
            status=status,
            samples=tuple(raw_samples),
            stats=summarize_samples(raw_samples),
            checksum=checksum,
            checksum_kind=checksum_kind,
            setup_rss_bytes=setup_rss,
            baseline_rss_bytes=baseline_rss,
            peak_rss_bytes=peak_rss,
            peak_rss_delta_bytes=max(0, peak_rss - baseline_rss),
            metrics=metrics,
            contracts=output.contracts,
            error=contract_error,
        )
    except (ModuleNotFoundError, ImportError) as exc:
        return CaseResult(
            spec=spec,
            status="skipped",
            error=f"{type(exc).__name__}: {exc}",
        )
    except ResourceLimitError as exc:
        return CaseResult(
            spec=spec,
            status="resource-limit",
            error=f"{type(exc).__name__}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            spec=spec,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if context is not None and context_entered:
            context.__exit__(None, None, None)


def _aggregate_measured_outputs(
    outputs: list[_CaseOutput],
    *,
    last: _CaseOutput,
) -> _CaseOutput:
    """outer sample のtyped outputを検証し、失敗contractを保持する。"""

    if not outputs:
        raise RuntimeError("benchmark workload returned no measured output")
    typed_metrics = isinstance(last.metrics, tuple)
    if any(
        isinstance(output.metrics, tuple) != typed_metrics
        for output in outputs
    ):
        raise RuntimeError("benchmark metric representation changed across samples")
    metrics = last.metrics
    if typed_metrics:
        baseline_metrics = outputs[0].metrics
        assert isinstance(baseline_metrics, tuple)
        if any(output.metrics != baseline_metrics for output in outputs[1:]):
            raise RuntimeError("typed metrics changed across warm samples")
        metrics = baseline_metrics

    contract_ids = tuple(
        contract.contract_id for contract in outputs[0].contracts
    )
    if any(
        tuple(contract.contract_id for contract in output.contracts)
        != contract_ids
        for output in outputs[1:]
    ):
        raise RuntimeError("contract set changed across warm samples")

    contracts: list[ContractResult] = []
    for index, contract_id in enumerate(contract_ids):
        samples = [output.contracts[index] for output in outputs]
        reference = samples[0]
        identity = (
            reference.contract_id,
            reference.severity,
            reference.comparator,
            reference.limit,
            reference.reason,
        )
        if any(
            (
                sample.contract_id,
                sample.severity,
                sample.comparator,
                sample.limit,
                sample.reason,
            )
            != identity
            for sample in samples[1:]
        ):
            raise RuntimeError(
                f"contract definition changed across warm samples: {contract_id}"
            )
        contracts.append(
            next((sample for sample in samples if not sample.passed), samples[-1])
        )

    return _CaseOutput(
        value=last.value,
        metrics=metrics,
        contracts=tuple(contracts),
    )


def _postprocess_case_output(
    definition: CaseDefinition,
    *,
    state: object,
    raw_output: object,
) -> _CaseOutput:
    """timed workload の raw output を計測区間外で semantic output にする。"""

    output = (
        definition.postprocess(state, raw_output)
        if definition.postprocess is not None
        else raw_output
    )
    if not isinstance(output, _CaseOutput):
        raise TypeError("benchmark workload must produce _CaseOutput")
    return output


def _calibrate(
    workload: Callable[[object], object],
    state: object,
    *,
    target_ns: int,
) -> int:
    if target_ns <= 0:
        return 1
    iterations = 1
    while True:
        started = time.perf_counter_ns()
        for _ in range(iterations):
            workload(state)
        elapsed = time.perf_counter_ns() - started
        if elapsed >= target_ns or iterations >= _MAX_CALIBRATION_ITERATIONS:
            return iterations
        if elapsed <= 0:
            iterations *= 2
        else:
            estimate = max(iterations + 1, int(iterations * target_ns / elapsed))
            iterations = min(_MAX_CALIBRATION_ITERATIONS, estimate)


def _merge_cold_results(
    *,
    spec: CaseSpec,
    results: list[CaseResult],
) -> CaseResult:
    failures = [
        result
        for result in results
        if result.status not in {"ok", "contract-failure"}
    ]
    if failures:
        first = failures[0]
        return CaseResult(spec=spec, status=first.status, error=first.error)
    checksums = {result.checksum for result in results}
    checksum_kinds = {result.checksum_kind for result in results}
    if len(checksums) != 1 or len(checksum_kinds) != 1:
        return CaseResult(
            spec=spec,
            status="error",
            error="cold samples produced different output checksums",
        )
    samples = tuple(sample for result in results for sample in result.samples)
    rss_result = max(
        results,
        key=lambda result: result.peak_rss_delta_bytes or 0,
    )
    contract_result = next(
        (
            result
            for result in results
            if result.status == "contract-failure"
        ),
        results[-1],
    )
    return CaseResult(
        spec=spec,
        status=contract_result.status,
        samples=samples,
        stats=summarize_samples(samples),
        checksum=results[0].checksum,
        checksum_kind=results[0].checksum_kind,
        setup_rss_bytes=rss_result.setup_rss_bytes,
        baseline_rss_bytes=rss_result.baseline_rss_bytes,
        peak_rss_bytes=rss_result.peak_rss_bytes,
        peak_rss_delta_bytes=rss_result.peak_rss_delta_bytes,
        metrics=contract_result.metrics,
        contracts=contract_result.contracts,
        error=contract_result.error,
    )


def _definition(
    case_id: str,
    label: str,
    *,
    category: str,
    suite: str,
    fixture: str,
    parameters: dict[str, Any],
    tags: tuple[str, ...],
    selectable_suites: tuple[str, ...],
    setup: Callable[[dict[str, Any], int], object],
    workload: Callable[[object], object],
    postprocess: Callable[[object, object], _CaseOutput] | None = None,
    measurement_context: (
        Callable[[object], AbstractContextManager[object]] | None
    ) = None,
    support_source_files: tuple[Path, ...] = (),
    support_implementations: tuple[Callable[..., object], ...] = (),
    self_sampling: bool = False,
) -> CaseDefinition:
    return CaseDefinition(
        case_id=case_id,
        version=1,
        label=label,
        category=category,
        suite=suite,
        fixture=fixture,
        parameters=parameters,
        tags=tags,
        selectable_suites=selectable_suites,
        setup=setup,
        workload=workload,
        postprocess=postprocess,
        measurement_context=measurement_context,
        support_source_files=support_source_files,
        support_implementations=support_implementations,
        checksum_policy="exact",
        self_sampling=bool(self_sampling),
    )


def _scaled_definitions(
    *,
    prefix: str,
    label: str,
    values: tuple[int, ...],
    parameter_name: str,
    category: str,
    suite: str,
    fixture: str,
    setup: Callable[[dict[str, Any], int], object],
    workload: Callable[[object], _CaseOutput],
    suites: tuple[tuple[str, ...], ...],
    support_source_files: tuple[Path, ...] = (),
    support_implementations: tuple[Callable[..., object], ...] = (),
) -> list[CaseDefinition]:
    return [
        _definition(
            f"{prefix}.{parameter_name}_{value}",
            f"{label} ({value:,})",
            category=category,
            suite=suite,
            fixture=fixture,
            parameters={parameter_name: value},
            tags=("scaling", "exact-checksum"),
            selectable_suites=selectable,
            setup=setup,
            workload=workload,
            support_source_files=support_source_files,
            support_implementations=support_implementations,
        )
        for value, selectable in zip(values, suites, strict=True)
    ]


def _parameter_edit_definitions() -> list[CaseDefinition]:
    """PARAM-01 の 100/1,000/10,000-row formal cases を返す。"""

    return [
        _definition(
            f"gui.parameter_edit.rows_{rows}",
            f"single-key parameter changed-frame ({rows:,} rows)",
            category="gui",
            suite="gui",
            fixture="parameter_store_single_key_edit",
            parameters={
                "rows": rows,
                "changed_frames": changed_frames,
            },
            tags=(
                "PARAM-01",
                "single-key",
                "changed-frame",
                "no-imgui",
                "exact-checksum",
            ),
            selectable_suites=selectable_suites,
            setup=_setup_parameter_edit_scenario,
            workload=_workload_parameter_edit_scenario,
            support_source_files=(
                _PARAMETER_EDIT_SOURCE_FILE,
                _SYSTEM_SOURCE_FILE,
            ),
            self_sampling=True,
        )
        for rows, changed_frames, selectable_suites in (
            (100, 12, ("smoke", "gui")),
            (1_000, 12, ("gui",)),
            (10_000, 6, ("soak",)),
        )
    ]


def _parameter_hotpath_definitions() -> list[CaseDefinition]:
    """大規模 ParamStore の merge/snapshot/visibility cases を返す。"""

    definitions: list[CaseDefinition] = [
        _definition(
            "gui.parameter_layout.rows_10000",
            "stable parameter group layout (10,000 rows)",
            category="gui",
            suite="parameters",
            fixture="parameter_store_group_layout",
            parameters={
                "operation": "layout_reuse",
                "rows": 10_000,
                "samples": 24,
            },
            tags=(
                "PARAM-05",
                "group-layout",
                "no-imgui",
                "exact-checksum",
            ),
            selectable_suites=("parameters", "soak"),
            setup=_setup_parameter_hotpath_scenario,
            workload=_workload_parameter_hotpath_scenario,
            support_source_files=(_PARAMETER_HOTPATH_SOURCE_FILE,),
            self_sampling=True,
        )
    ]
    for rows, selectable_suites in (
        (1_000, ("parameters",)),
        (10_000, ("parameters", "soak")),
    ):
        definitions.extend(
            (
                _definition(
                    f"runtime.parameter_merge.rows_{rows}.change_steady",
                    f"stable parameter merge ({rows:,} rows)",
                    category="runtime",
                    suite="parameters",
                    fixture="parameter_store_stable_records",
                    parameters={
                        "operation": "merge_steady",
                        "rows": rows,
                        "samples": 24,
                    },
                    tags=(
                        "PARAM-06",
                        "stable-frame",
                        "no-imgui",
                        "exact-checksum",
                    ),
                    selectable_suites=selectable_suites,
                    setup=_setup_parameter_hotpath_scenario,
                    workload=_workload_parameter_hotpath_scenario,
                    support_source_files=(_PARAMETER_HOTPATH_SOURCE_FILE,),
                    self_sampling=True,
                ),
                _definition(
                    f"runtime.parameter_snapshot.rows_{rows}.change_one",
                    f"one-key parameter snapshot ({rows:,} rows)",
                    category="runtime",
                    suite="parameters",
                    fixture="parameter_store_single_key_snapshot",
                    parameters={
                        "operation": "snapshot_one",
                        "rows": rows,
                        "samples": 24,
                    },
                    tags=(
                        "PARAM-07",
                        "single-key",
                        "no-imgui",
                        "exact-checksum",
                    ),
                    selectable_suites=selectable_suites,
                    setup=_setup_parameter_hotpath_scenario,
                    workload=_workload_parameter_hotpath_scenario,
                    support_source_files=(_PARAMETER_HOTPATH_SOURCE_FILE,),
                    self_sampling=True,
                ),
                _definition(
                    f"gui.parameter_visibility.rows_{rows}.mode_default",
                    f"default parameter visibility ({rows:,} rows)",
                    category="gui",
                    suite="parameters",
                    fixture="parameter_store_visibility_default",
                    parameters={
                        "operation": "visibility_default",
                        "rows": rows,
                        "samples": 24,
                    },
                    tags=(
                        "PARAM-08",
                        "visibility",
                        "no-imgui",
                        "exact-checksum",
                    ),
                    selectable_suites=selectable_suites,
                    setup=_setup_parameter_hotpath_scenario,
                    workload=_workload_parameter_hotpath_scenario,
                    support_source_files=(_PARAMETER_HOTPATH_SOURCE_FILE,),
                    self_sampling=True,
                ),
            )
        )
    definitions.append(
        _definition(
            "gui.parameter_visibility.rows_10000.mode_search",
            "parameter search visibility (10,000 rows)",
            category="gui",
            suite="parameters",
            fixture="parameter_store_visibility_search",
            parameters={
                "operation": "visibility_search",
                "rows": 10_000,
                "samples": 24,
            },
            tags=(
                "PARAM-08",
                "search",
                "no-imgui",
                "exact-checksum",
            ),
            selectable_suites=("parameters", "soak"),
            setup=_setup_parameter_hotpath_scenario,
            workload=_workload_parameter_hotpath_scenario,
            support_source_files=(_PARAMETER_HOTPATH_SOURCE_FILE,),
            self_sampling=True,
        )
    )
    definitions.append(
        _definition(
            "gui.parameter_favorites.rows_10000",
            "stable parameter favorite view (10,000 rows)",
            category="gui",
            suite="parameters",
            fixture="parameter_store_favorite_view",
            parameters={
                "operation": "favorite_view",
                "rows": 10_000,
                "samples": 24,
            },
            tags=(
                "PARAM-09",
                "favorite",
                "no-imgui",
                "exact-checksum",
            ),
            selectable_suites=("parameters", "soak"),
            setup=_setup_parameter_hotpath_scenario,
            workload=_workload_parameter_hotpath_scenario,
            support_source_files=(_PARAMETER_HOTPATH_SOURCE_FILE,),
            self_sampling=True,
        )
    )
    return definitions


def _perf_hotpath_definitions() -> list[CaseDefinition]:
    """PerfCollector causal backlog の scaling cases を返す。"""

    return [
        _definition(
            f"runtime.perf.causal_backlog.pending_{pending}",
            f"PerfCollector causal backlog ({pending:,} pending)",
            category="runtime",
            suite="parameters",
            fixture="ordered_causal_revisions",
            parameters={"pending": pending, "samples": 24},
            tags=(
                "PERF-04",
                "causal-backlog",
                "exact-checksum",
            ),
            selectable_suites=selectable_suites,
            setup=_setup_perf_backlog_scenario,
            workload=_workload_perf_backlog_scenario,
            support_source_files=(_PERF_HOTPATH_SOURCE_FILE,),
            self_sampling=True,
        )
        for pending, selectable_suites in (
            (100, ("parameters",)),
            (1_000, ("parameters",)),
            (4_096, ("parameters", "soak")),
        )
    ]


def _multilayer_renderer_definitions() -> list[CaseDefinition]:
    """1/8/100 animated layer と changing-topology control を返す。"""

    definitions = [
        _definition(
            f"interactive.renderer.multilayer.stable_offsets.layers_{layers}",
            f"renderer multi-layer stable offsets / {layers} layers",
            category="interactive",
            suite="interactive",
            fixture="animated_multilayer_lines",
            parameters={
                "layers": layers,
                "frames": 12,
                "polylines": 128,
                "stable_topology": True,
            },
            tags=(
                "renderer",
                "multi-layer",
                "animated-coordinates",
                "static-topology",
                "fake-gl",
            ),
            selectable_suites=suites,
            setup=_setup_multilayer_renderer,
            workload=_workload_multilayer_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
            self_sampling=True,
        )
        for layers, suites in (
            (1, ("interactive",)),
            (8, ("interactive",)),
            (100, ("soak",)),
        )
    ]
    definitions.append(
        _definition(
            "interactive.renderer.multilayer.changing_topology.layers_8",
            "renderer multi-layer changing topology / 8 layers",
            category="interactive",
            suite="interactive",
            fixture="animated_multilayer_lines",
            parameters={
                "layers": 8,
                "frames": 12,
                "polylines": 128,
                "stable_topology": False,
            },
            tags=(
                "renderer",
                "multi-layer",
                "animated-coordinates",
                "animated-topology",
                "fake-gl",
                "control",
            ),
            selectable_suites=("interactive",),
            setup=_setup_multilayer_renderer,
            workload=_workload_multilayer_renderer,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
            self_sampling=True,
        )
    )
    return definitions


def _effect_definitions() -> list[CaseDefinition]:
    """effect と互換 fixture を明示対応させた代表 case を返す。"""

    fixtures: dict[str, tuple[str, dict[str, Any]]] = {
        "affine": ("polyline_long", {"scale": [1.05, 1.02, 1.0], "rotation": [5.0, 10.0, 0.0], "delta": [12.0, 5.0, 0.0]}),
        "bold": ("rings_2", {}),
        "buffer": ("rings_2", {"distance": 5.0, "quad_segs": 8, "join": "round"}),
        "clip": ("binary_mask", {}),
        "collapse": ("polyline_long", {}),
        "dash": ("polyline_long", {}),
        "displace": ("polyline_long", {}),
        "drop": ("many_lines", {}),
        "extrude": ("polyline_long", {}),
        "fill": ("rings_2", {}),
        "growth": ("rings_2", {}),
        "highpass": ("polyline_long", {}),
        "isocontour": ("rings_2", {}),
        "lowpass": ("polyline_long", {}),
        "metaball": ("rings_2", {}),
        "mirror": ("polyline_long", {"n_mirror": 3}),
        "mirror3d": ("polyline_long", {}),
        "partition": ("rings_2", {"site_count": 30, "seed": 0}),
        "pixelate": ("polyline_long", {}),
        "quantize": ("polyline_long", {}),
        "reaction_diffusion": ("rings_2", {}),
        "relax": ("rings_2", {}),
        "repeat": ("line_small", {"count": 5}),
        "scale": ("polyline_long", {"scale": [1.15, 0.9, 1.0]}),
        "subdivide": ("polyline_long", {"subdivisions": 2}),
        "trim": ("polyline_long", {}),
        "twist": ("polyline_long", {}),
        "warp": ("binary_mask", {}),
        "weave": ("many_lines", {}),
        "wobble": ("polyline_long", {}),
    }
    definitions: list[CaseDefinition] = []
    for effect_name, (fixture, overrides) in fixtures.items():
        if effect_name in _HEAVY_EFFECT_FINAL_CHECKSUMS:
            for quality in ("draft", "final"):
                parameters: dict[str, Any] = {
                    "effect": effect_name,
                    "fixture": fixture,
                    "quality": quality,
                    **overrides,
                }
                parameters["expected_checksum"] = (
                    _HEAVY_EFFECT_FINAL_CHECKSUMS[effect_name]
                    if quality == "final"
                    else _HEAVY_EFFECT_DRAFT_CHECKSUMS[effect_name]
                )
                definitions.append(
                    _definition(
                        f"effect.{effect_name}.{quality}.{fixture}",
                        f"{effect_name} / {fixture} / {quality}",
                        category="effect",
                        suite="effects",
                        fixture=fixture,
                        parameters=parameters,
                        tags=(
                            "explicit-fixture",
                            "exact-checksum",
                            f"quality-{quality}",
                            "heavy-effect",
                        ),
                        selectable_suites=("effects",),
                        setup=_setup_effect,
                        workload=_workload_effect,
                        support_source_files=(_CASES_SOURCE_FILE,),
                        support_implementations=(
                            _effect_metrics,
                            _diagnostic_effective_value,
                        ),
                    )
                )
            continue
        definitions.append(
            _definition(
                f"effect.{effect_name}.{fixture}",
                f"{effect_name} / {fixture}",
                category="effect",
                suite="effects",
                fixture=fixture,
                parameters={
                    "effect": effect_name,
                    "fixture": fixture,
                    **overrides,
                },
                tags=("explicit-fixture", "exact-checksum"),
                selectable_suites=("effects",),
                setup=_setup_effect,
                workload=_workload_effect,
                support_source_files=(_CASES_SOURCE_FILE,),
                support_implementations=(
                    _effect_metrics,
                    _diagnostic_effective_value,
                ),
            )
        )
    return definitions


def _target_effect_speedup_definitions() -> list[CaseDefinition]:
    """高速化対象 effect の actual-work と shape 別 case を返す。"""

    cases: tuple[
        tuple[str, str, str, str, dict[str, Any], tuple[str, ...]], ...
    ] = (
        (
            "effect.translate.polyline_long",
            "translate / 50k vertices",
            "polyline_long",
            "translate",
            {"delta": [12.0, 5.0, 3.5]},
            ("large", "coordinate-only"),
        ),
        (
            "effect.translate.many_lines",
            "translate / 5k lines",
            "many_lines",
            "translate",
            {"delta": [12.0, 5.0, 0.0]},
            ("many-short-lines", "coordinate-only"),
        ),
        (
            "effect.rotate.pivot.polyline_long",
            "rotate fixed pivot / 50k vertices",
            "polyline_long",
            "rotate",
            {
                "auto_center": False,
                "pivot": [12.0, -5.0, 3.0],
                "rotation": [10.0, 20.0, 5.0],
            },
            ("large", "coordinate-only", "fixed-pivot"),
        ),
        (
            "effect.scale.by_line.many_lines",
            "scale by line / 5k lines",
            "many_lines",
            "scale",
            {"mode": "by_line", "scale": [1.15, 0.9, 1.0]},
            ("many-short-lines", "coordinate-only"),
        ),
        (
            "effect.scale.by_face.many_rings",
            "scale by face / 512 rings",
            "many_rings",
            "scale",
            {"mode": "by_face", "scale": [1.15, 0.9, 1.0]},
            ("many-short-lines", "rings", "coordinate-only"),
        ),
        (
            "effect.subdivide.actual.polyline_spaced_long",
            "subdivide actual work / 50k vertices",
            "polyline_spaced_long",
            "subdivide",
            {"subdivisions": 2},
            ("large", "topology-changing"),
        ),
        (
            "effect.subdivide.actual.many_lines",
            "subdivide actual work / 5k lines",
            "many_lines",
            "subdivide",
            {"subdivisions": 2},
            ("many-short-lines", "topology-changing"),
        ),
        (
            "effect.fill.dense.rings_2",
            "fill dense cross hatch / outer and hole",
            "rings_2",
            "fill",
            {
                "angle_sets": 3,
                "angle": 17.0,
                "density": 1000.0,
                "remove_boundary": True,
            },
            ("rings", "dense", "topology-changing"),
        ),
        (
            "effect.fill.many_rings",
            "fill / 512 disjoint rings",
            "many_rings",
            "fill",
            {
                "angle_sets": 1,
                "angle": 0.0,
                "density": 20.0,
                "remove_boundary": True,
            },
            ("many-short-lines", "rings", "topology-changing"),
        ),
    )
    return [
        _definition(
            case_id,
            label,
            category="effect",
            suite="effects",
            fixture=fixture,
            parameters={"effect": effect_name, "fixture": fixture, **parameters},
            tags=("explicit-fixture", "exact-checksum", "actual-work", *tags),
            selectable_suites=("effects",),
            setup=_setup_effect,
            workload=_workload_effect,
            support_source_files=(_CASES_SOURCE_FILE,),
            support_implementations=(
                _effect_metrics,
                _diagnostic_effective_value,
            ),
        )
        for case_id, label, fixture, effect_name, parameters, tags in cases
    ]


def _primitive_definitions() -> list[CaseDefinition]:
    """全組み込み primitive の direct raw actual-work case を返す。"""

    from grafix.devtools.benchmarks.primitive_benchmark import (
        primitive_benchmark_cases,
        run_raw_primitive,
        setup_primitive_benchmark,
    )

    return [
        _definition(
            case.case_id,
            case.label,
            category="primitive",
            suite="primitives",
            fixture=case.fixture,
            parameters=case.parameters(),
            tags=case.tags,
            selectable_suites=case.selectable_suites,
            setup=setup_primitive_benchmark,
            workload=run_raw_primitive,
            postprocess=_postprocess_primitive,
            support_source_files=(_PRIMITIVE_SOURCE_FILE,),
        )
        for case in primitive_benchmark_cases()
    ]


def _remaining_effect_definitions() -> list[CaseDefinition]:
    """除外 5 件以外の effect direct-evaluator actual-work case を返す。"""

    from grafix.devtools.benchmarks.remaining_effect_benchmark import (
        remaining_effect_benchmark_cases,
        remaining_effect_measurement_context,
        run_remaining_effect,
        setup_remaining_effect_benchmark,
    )

    return [
        _definition(
            case.case_id,
            case.label,
            category="effect",
            suite="effects-remaining",
            fixture=case.fixture,
            parameters=case.parameters(),
            tags=case.tags,
            selectable_suites=case.selectable_suites,
            setup=setup_remaining_effect_benchmark,
            workload=run_remaining_effect,
            postprocess=_postprocess_remaining_effect,
            measurement_context=remaining_effect_measurement_context,
            support_source_files=(
                _REMAINING_EFFECT_SOURCE_FILE,
                _CASES_SOURCE_FILE,
            ),
        )
        for case in remaining_effect_benchmark_cases()
    ]


def _legacy_system_definitions() -> list[CaseDefinition]:
    """従来の system/micro 診断を schema v4 の個別 case として返す。"""

    cases = (
        (
            "system.animated_soak",
            "RealizeSession animated soak",
            "animated_soak",
            {"frames": 48, "sides": 48},
        ),
        (
            "micro.geometry_signature",
            "Geometry signature",
            "geometry_signature",
            {"iterations": 1_000},
        ),
        (
            "micro.rotate_scale_identity",
            "rotate/scale identity",
            "rotate_scale_identity",
            {"points": 50_000, "iterations": 1_000},
        ),
        (
            "micro.cached_site_id",
            "cached site ID",
            "cached_site_id",
            {"iterations": 10_000},
        ),
        (
            "system.parameter_snapshot_model",
            "parameter snapshot/model steady frames",
            "parameter_snapshot_model",
            {"rows": 1_000, "frames": 60},
        ),
        (
            "micro.realized_concat",
            "packed realized concat",
            "realized_concat",
            {"parts": 128, "vertices_per_part": 3},
        ),
        (
            "micro.asemic",
            "asemic cached glyph/layout",
            "asemic",
            {"text": "CACHE CACHE\nSYSTEM", "nodes": 24},
        ),
        (
            "micro.gcode_ordering",
            "G-code stroke ordering",
            "gcode_ordering",
            {"strokes": 200},
        ),
        (
            "system.cold_import",
            "cold import grafix",
            "cold_import",
            {"repeats": 1},
        ),
    )
    return [
        _definition(
            case_id,
            label,
            category="system" if case_id.startswith("system.") else "micro",
            suite="system",
            fixture=workload_id,
            parameters={"workload": workload_id, **parameters},
            tags=("legacy-system", "schema-v3"),
            selectable_suites=("system",),
            setup=_setup_legacy_system,
            workload=_workload_legacy_system,
            support_source_files=(_SYSTEM_SOURCE_FILE,),
        )
        for case_id, label, workload_id, parameters in cases
    ]


def _postprocess_primitive(state: object, output: object) -> _CaseOutput:
    """raw primitive output を共通metrics/contractsへ変換する。"""

    from grafix.devtools.benchmarks.primitive_benchmark import (
        observe_primitive_output,
    )

    observation = observe_primitive_output(state, output)
    return _CaseOutput(
        value=observation.geometry,
        metrics=observation.metrics,
        contracts=observation.contracts,
    )


def _postprocess_remaining_effect(state: object, output: object) -> _CaseOutput:
    """timed effect output を共通 metrics/contracts へ変換する。"""

    from grafix.devtools.benchmarks.remaining_effect_benchmark import (
        observe_remaining_effect_output,
    )

    observation = observe_remaining_effect_output(state, output)
    return _CaseOutput(
        value=observation.geometry,
        metrics=observation.metrics,
        contracts=observation.contracts,
    )


def _setup_effect(parameters: dict[str, Any], seed: int) -> object:
    from grafix.core.builtins import ensure_builtin_effect_registered
    from grafix.core.effect_registry import effect_registry
    from grafix.devtools.benchmarks.cases import build_default_cases

    effect_name = str(parameters["effect"])
    fixture = str(
        parameters.get(
            "fixture",
            "line_small" if effect_name == "translate" else "polyline_long",
        )
    )
    benchmark_case = next(
        case for case in build_default_cases(seed=seed) if case.case_id == fixture
    )
    ensure_builtin_effect_registered(effect_name)
    spec = effect_registry[effect_name]
    quality = str(parameters.get("quality", "final"))
    if quality not in {"draft", "final"}:
        raise ValueError(f"unknown effect benchmark quality: {quality!r}")
    expected_checksum = parameters.get("expected_checksum")
    if expected_checksum is not None and not isinstance(expected_checksum, str):
        raise TypeError("expected effect checksum must be a string")
    args = dict(spec.defaults)
    args.update(
        {
            key: value
            for key, value in parameters.items()
            if key not in {"effect", "fixture", "quality", "expected_checksum"}
        }
    )
    args_tuple = tuple(sorted(args.items()))
    return (
        spec.evaluator,
        benchmark_case.inputs,
        args_tuple,
        effect_name,
        quality,
        expected_checksum,
    )


def _setup_legacy_system(parameters: dict[str, Any], seed: int) -> object:
    from grafix.devtools.benchmarks import system_benchmark

    state = dict(parameters)
    workload = str(state["workload"])
    if workload == "rotate_scale_identity":
        state["geometry"] = system_benchmark._identity_geometry(
            points=int(state["points"])
        )
    elif workload == "parameter_snapshot_model":
        state["store"] = system_benchmark._parameter_store(rows=int(state["rows"]))
    elif workload == "realized_concat":
        state["inputs"] = system_benchmark._concat_inputs(
            parts=int(state["parts"]),
            vertices_per_part=int(state["vertices_per_part"]),
        )
    elif workload == "gcode_ordering":
        state["stroke_values"] = system_benchmark._random_strokes(
            count=int(state["strokes"]),
            seed=int(seed),
        )
    return state


def _workload_legacy_system(state: object) -> _CaseOutput:
    from grafix.core.realize import RealizeSession
    from grafix.core.realized_geometry import concat_realized_geometries
    from grafix.devtools.benchmarks import system_benchmark

    values = cast(dict[str, Any], state)
    workload = str(values["workload"])
    if workload == "animated_soak":
        frames = int(values["frames"])
        sides = int(values["sides"])
        estimated_bytes = (sides + 1) * 3 * np.dtype(np.float32).itemsize + 8
        cache_limit = max(1_024, 2 * estimated_bytes + 64)
        last: RealizedGeometry | None = None
        with RealizeSession(max_cache_bytes=cache_limit) as session:
            for frame in range(frames):
                last = session.realize(
                    system_benchmark._draw_geometry(frame=frame, sides=sides)
                )
            stats = session.stats()
        if last is None:
            raise RuntimeError("animated soak returned no geometry")
        return _CaseOutput(
            value=last,
            metrics={
                "frames": frames,
                "cache_hits": stats.hits,
                "cache_misses": stats.misses,
                "cache_evictions": stats.evictions,
                "cache_entries": stats.entries,
                "cache_bytes": stats.bytes,
                "cache_budget_bytes": cache_limit,
            },
        )
    if workload == "geometry_signature":
        payload = system_benchmark._geometry_signature_workload(
            iterations=int(values["iterations"])
        )
        return _CaseOutput(value=payload["output"], metrics=payload)
    if workload == "rotate_scale_identity":
        geometry = cast(RealizedGeometry, values["geometry"])
        payload = system_benchmark._rotate_scale_identity_workload(
            geometry,
            iterations=int(values["iterations"]),
            include_semantic_outputs=True,
        )
        semantic_outputs = payload.pop("_semantic_outputs")
        return _CaseOutput(value=semantic_outputs, metrics=payload)
    if workload == "cached_site_id":
        payload = system_benchmark._cached_site_id_workload(
            iterations=int(values["iterations"]),
            code=system_benchmark._cached_site_id_workload.__code__,
        )
        return _CaseOutput(value=payload["output"], metrics=payload)
    if workload == "parameter_snapshot_model":
        payload = system_benchmark._parameter_snapshot_model_workload(
            values["store"],
            frames=int(values["frames"]),
        )
        output = payload["output"]
        semantic = {
            key: output[key]
            for key in ("frames", "rows", "snapshot_entries", "render_calls")
        }
        return _CaseOutput(value=semantic, metrics=payload)
    if workload == "realized_concat":
        result = concat_realized_geometries(
            *cast(tuple[RealizedGeometry, ...], values["inputs"])
        )
        return _CaseOutput(
            value=result,
            metrics={
                "parts": int(values["parts"]),
                "n_vertices": int(result.coords.shape[0]),
                "n_lines": int(result.offsets.size - 1),
                "output_bytes": result.byte_size,
            },
        )
    if workload == "asemic":
        payload = system_benchmark._asemic_workload(
            text=str(values["text"]),
            nodes=int(values["nodes"]),
            include_semantic_geometry=True,
        )
        semantic_geometry = payload.pop("_semantic_geometry")
        return _CaseOutput(value=semantic_geometry, metrics=payload)
    if workload == "gcode_ordering":
        payload = system_benchmark._gcode_ordering_workload(
            values["stroke_values"]
        )
        return _CaseOutput(value=payload["output"], metrics=payload)
    if workload == "cold_import":
        payload = system_benchmark._cold_import_benchmark(
            repeats=int(values["repeats"])
        )
        if payload.get("status") != "ok":
            raise RuntimeError(str(payload.get("error", "cold import failed")))
        return _CaseOutput(value=payload["output"], metrics=payload)
    raise ValueError(f"unknown legacy system workload: {workload}")


def _diagnostic_effective_value(
    diagnostics: tuple[Any, ...],
    *,
    op: str,
    requested: int | float,
) -> int | float:
    effective: int | float = requested
    for diagnostic in diagnostics:
        if getattr(diagnostic, "op", None) != op:
            continue
        value = getattr(diagnostic, "effective_value", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            effective = value
    return effective


def _effect_metrics(
    *,
    effect_name: str,
    quality: str,
    args: dict[str, Any],
    inputs: tuple[RealizedGeometry, ...],
    geometry: RealizedGeometry,
    diagnostics: tuple[Any, ...],
) -> tuple[Metric, ...]:
    metrics = [
        Metric(
            name="quality",
            kind="gauge",
            unit="unitless",
            phase="measure",
            scope="effect",
            value=quality,
        ),
        Metric(
            name="n_vertices",
            kind="counter",
            unit="count",
            phase="measure",
            scope="effect",
            value=int(geometry.coords.shape[0]),
        ),
        Metric(
            name="n_lines",
            kind="counter",
            unit="count",
            phase="measure",
            scope="effect",
            value=int(geometry.offsets.size - 1),
        ),
        Metric(
            name="output_bytes",
            kind="counter",
            unit="bytes",
            phase="measure",
            scope="effect",
            value=int(geometry.coords.nbytes + geometry.offsets.nbytes),
        ),
        Metric(
            name="diagnostics",
            kind="counter",
            unit="count",
            phase="measure",
            scope="effect",
            value=len(diagnostics),
        ),
    ]

    def add_work_metric(name: str, value: int | float, *, unit: str) -> None:
        metrics.append(
            Metric(
                name=name,
                kind="gauge",
                unit=unit,
                phase="measure",
                scope="effect",
                value=value,
            )
        )

    if effect_name == "reaction_diffusion":
        requested_steps = int(args["steps"])
        requested_pitch = float(args["grid_pitch"])
        add_work_metric("work.steps.requested", requested_steps, unit="count")
        add_work_metric(
            "work.steps.effective",
            _diagnostic_effective_value(
                diagnostics,
                op="reaction_diffusion.steps",
                requested=requested_steps,
            ),
            unit="count",
        )
        add_work_metric(
            "work.grid_pitch.requested",
            requested_pitch,
            unit="geometry_units",
        )
        add_work_metric(
            "work.grid_pitch.effective",
            _diagnostic_effective_value(
                diagnostics,
                op="reaction_diffusion.grid_pitch",
                requested=requested_pitch,
            ),
            unit="geometry_units",
        )
    elif effect_name == "growth":
        requested_iterations = int(args["iters"])
        add_work_metric(
            "work.iterations.requested",
            requested_iterations,
            unit="count",
        )
        add_work_metric(
            "work.iterations.effective",
            _diagnostic_effective_value(
                diagnostics,
                op="growth.iters",
                requested=requested_iterations,
            ),
            unit="count",
        )
        point_budget = next(
            (
                diagnostic
                for diagnostic in reversed(diagnostics)
                if getattr(diagnostic, "op", None) == "growth.total_points"
            ),
            None,
        )
        if point_budget is not None:
            original = getattr(point_budget, "original_value", None)
            effective = getattr(point_budget, "effective_value", None)
            if isinstance(original, int) and isinstance(effective, int):
                add_work_metric(
                    "work.total_points.requested",
                    original,
                    unit="count",
                )
                add_work_metric(
                    "work.total_points.effective",
                    effective,
                    unit="count",
                )
    elif effect_name == "metaball":
        requested_pitch = float(args["grid_pitch"])
        requested_segments = sum(
            max(0, int(stop) - int(start) - 1)
            for geometry_input in inputs
            for start, stop in zip(
                geometry_input.offsets[:-1],
                geometry_input.offsets[1:],
                strict=True,
            )
        )
        add_work_metric(
            "work.grid_pitch.requested",
            requested_pitch,
            unit="geometry_units",
        )
        add_work_metric(
            "work.grid_pitch.effective",
            _diagnostic_effective_value(
                diagnostics,
                op="metaball.grid_pitch",
                requested=requested_pitch,
            ),
            unit="geometry_units",
        )
        add_work_metric(
            "work.segments.requested",
            requested_segments,
            unit="count",
        )
        add_work_metric(
            "work.segments.effective",
            _diagnostic_effective_value(
                diagnostics,
                op="metaball.ring_segments",
                requested=requested_segments,
            ),
            unit="count",
        )
    return tuple(metrics)


def _workload_effect(state: object) -> _CaseOutput:
    from grafix.core.operation_diagnostics import operation_diagnostic_context
    from grafix.core.preview_quality import preview_quality_context

    (
        evaluator,
        inputs,
        args_tuple,
        effect_name,
        quality,
        expected_checksum,
    ) = cast(tuple[Any, Any, Any, str, str, str | None], state)
    with operation_diagnostic_context() as diagnostic_buffer:
        with preview_quality_context(cast(Any, quality)):
            output = evaluator(inputs, args_tuple)
    geometry = (
        output
        if isinstance(output, RealizedGeometry)
        else RealizedGeometry(coords=output[0], offsets=output[1])
    )
    diagnostics = diagnostic_buffer.snapshot()
    args = dict(args_tuple)
    contracts = (
        (
            evaluate_contract(
                contract_id=f"effect.{effect_name}.{quality}_checksum",
                severity="hard",
                actual=geometry_checksum(geometry),
                comparator="eq",
                limit=expected_checksum,
                reason=f"{quality} quality geometry checksum remains exact",
            ),
        )
        if expected_checksum is not None
        else ()
    )
    return _CaseOutput(
        value=geometry,
        metrics=_effect_metrics(
            effect_name=effect_name,
            quality=quality,
            args=args,
            inputs=inputs,
            geometry=geometry,
            diagnostics=diagnostics,
        ),
        contracts=contracts,
    )


def _benchmark_draw(_t: float) -> tuple[()]:
    return ()


def _setup_provenance(parameters: dict[str, Any], _seed: int) -> object:
    from grafix.core.capture_provenance import CaptureProvenanceBuilder
    from grafix.core.runtime_config import runtime_config
    from grafix.devtools.benchmarks.system_benchmark import _parameter_store

    store = _parameter_store(rows=int(parameters["rows"]))
    builder = CaptureProvenanceBuilder(
        _benchmark_draw,
        config=runtime_config(),
        parameter_source="code",
        parameter_store_path=None,
        parameter_load_provenance=store.load_provenance,
    )
    return builder, store


def _workload_provenance(state: object) -> _CaseOutput:
    builder, store = cast(tuple[Any, Any], state)
    provenance = builder.frame(
        store,
        t=0.0,
        frame_index=0,
        quality="draft",
        origin="interactive",
    )
    parameters = provenance.frame.parameters
    return _CaseOutput(
        value={
            "revision": int(parameters.revision),
            "entry_count": int(parameters.entry_count),
            "sha256": parameters.sha256,
        },
        metrics={"entry_count": int(parameters.entry_count)},
    )


def _setup_provenance_changed(parameters: dict[str, Any], seed: int) -> object:
    from grafix.core.parameters.frame_params import FrameParamRecord

    builder, store = cast(
        tuple[Any, Any],
        _setup_provenance(parameters, seed),
    )
    runtime = store._runtime_ref()
    key = next(iter(runtime.last_effective_by_key))
    meta = store.get_meta(key)
    if meta is None:
        raise RuntimeError("provenance benchmark parameter metadata is missing")
    record = FrameParamRecord(
        key=key,
        base=runtime.last_effective_by_key[key],
        meta=meta,
        explicit=False,
        effective=runtime.last_effective_by_key[key],
        source="code",
    )
    return builder, store, record


def _workload_provenance_changed(state: object) -> _CaseOutput:
    from grafix.core.parameters.merge_ops import merge_frame_params

    builder, store, record = cast(tuple[Any, Any, Any], state)
    # 1 workload 内で A→B と2回変更し、各snapshotを具体化する。最終Bを固定
    # するため、warmup/calibration回数によらずsemantic checksumは一定になる。
    merge_frame_params(store, [dataclasses.replace(record, effective=-1.0)])
    builder.frame(
        store,
        t=0.0,
        frame_index=0,
        quality="draft",
        origin="interactive",
    )
    merge_frame_params(store, [dataclasses.replace(record, effective=-2.0)])
    provenance = builder.frame(
        store,
        t=0.0,
        frame_index=0,
        quality="draft",
        origin="interactive",
    )
    parameters = provenance.frame.parameters
    return _CaseOutput(
        value={
            "revision": int(parameters.revision),
            "entry_count": int(parameters.entry_count),
            "sha256": parameters.sha256,
        },
        metrics={
            "entry_count": int(parameters.entry_count),
            "changes_per_iteration": 2,
        },
    )


def _setup_parameter_gui(parameters: dict[str, Any], _seed: int) -> object:
    from grafix.devtools.benchmarks.system_benchmark import _parameter_store
    from grafix.interactive.parameter_gui.store_bridge import (
        clear_parameter_table_model_cache,
    )

    clear_parameter_table_model_cache()
    return _parameter_store(rows=int(parameters["rows"]))


def _workload_parameter_gui(state: object) -> _CaseOutput:
    from grafix.interactive.parameter_gui.store_bridge import (
        parameter_table_model_build_count,
        parameter_table_view_for_store,
    )

    view = parameter_table_view_for_store(
        state,  # type: ignore[arg-type]
        show_inactive_params=True,
    )
    value = {
        "total_count": int(view.total_count),
        "filtered_count": int(view.filtered_count),
        "visible_count": int(sum(view.visible_mask)),
    }
    return _CaseOutput(
        value=value,
        metrics={
            **value,
            "model_builds": int(parameter_table_model_build_count()),
        },
    )


def _setup_parameter_edit_scenario(
    parameters: dict[str, Any],
    _seed: int,
) -> object:
    from grafix.devtools.benchmarks.parameter_edit_benchmark import (
        make_parameter_edit_scenario,
    )

    return make_parameter_edit_scenario(parameters)


def _workload_parameter_edit_scenario(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.parameter_edit_benchmark import (
        ParameterEditScenario,
        run_parameter_edit_scenario,
    )

    if not isinstance(state, ParameterEditScenario):
        raise TypeError("parameter edit scenario state is invalid")
    result = run_parameter_edit_scenario(state)
    return _CaseOutput(
        value=result.value,
        metrics=result.metrics,
        contracts=result.contracts,
    )


def _setup_parameter_hotpath_scenario(
    parameters: dict[str, Any],
    _seed: int,
) -> object:
    from grafix.devtools.benchmarks.parameter_hotpath_benchmark import (
        make_parameter_hot_path_scenario,
    )

    return make_parameter_hot_path_scenario(parameters)


def _workload_parameter_hotpath_scenario(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.parameter_hotpath_benchmark import (
        ParameterHotPathScenario,
        run_parameter_hot_path_scenario,
    )

    if not isinstance(state, ParameterHotPathScenario):
        raise TypeError("parameter hot-path scenario state is invalid")
    result = run_parameter_hot_path_scenario(state)
    return _CaseOutput(
        value=result.value,
        metrics=result.metrics,
        contracts=result.contracts,
    )


def _setup_perf_backlog_scenario(
    parameters: dict[str, Any],
    _seed: int,
) -> object:
    from grafix.devtools.benchmarks.perf_hotpath_benchmark import (
        make_perf_backlog_scenario,
    )

    return make_perf_backlog_scenario(parameters)


def _workload_perf_backlog_scenario(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.perf_hotpath_benchmark import (
        PerfBacklogScenario,
        run_perf_backlog_scenario,
    )

    if not isinstance(state, PerfBacklogScenario):
        raise TypeError("perf backlog scenario state is invalid")
    result = run_perf_backlog_scenario(state)
    return _CaseOutput(
        value=result.value,
        metrics=result.metrics,
        contracts=result.contracts,
    )


def _setup_concat_recipe(parameters: dict[str, Any], _seed: int) -> object:
    count = max(1, int(parameters["parts"]))
    return tuple(
        Geometry.create(
            "__benchmark_leaf__",
            params={"index": index},
        )
        for index in range(count)
    )


def _workload_concat_recipe(state: object) -> _CaseOutput:
    geometries = cast(tuple[Geometry, ...], state)
    result = geometries[0]
    for geometry in geometries[1:]:
        result = cast(Geometry, result + geometry)
    return _CaseOutput(
        value=result,
        metrics={
            "parts": len(geometries),
            "root_inputs": len(result.inputs),
            "recipe_id": result.id,
        },
    )


def _setup_deep_dag(parameters: dict[str, Any], _seed: int) -> object:
    from grafix import G
    from grafix.core.builtins import ensure_builtin_effect_registered

    ensure_builtin_effect_registered("translate")
    node = G.line(length=1.0)
    for _ in range(max(1, int(parameters["depth"]))):
        node = Geometry.create(
            "translate",
            inputs=(node,),
            params={"delta": (0.001, 0.0, 0.0)},
        )
    return node


def _workload_deep_dag(state: object) -> _CaseOutput:
    from grafix.core.realize import RealizeSession

    geometry = RealizeSession(max_cache_bytes=0).realize(state)  # type: ignore[arg-type]
    return _CaseOutput(value=geometry, metrics={"depth": 5_000})


def _setup_passthrough(parameters: dict[str, Any], _seed: int) -> object:
    return parameters


def _workload_draw_realize_indices(state: object) -> _CaseOutput:
    from grafix.core.layer import LayerStyleDefaults
    from grafix.core.pipeline import realize_scene
    from grafix.core.realize import RealizeSession
    from grafix.interactive.gl.index_buffer import build_line_indices_and_stats

    size = int(state["grid_size"])  # type: ignore[index]

    def draw(_t: float) -> Geometry:
        base = Geometry.create(
            "grid",
            params={"nx": size, "ny": size, "scale": 100.0},
        )
        return Geometry.create(
            "rotate",
            inputs=(base,),
            params={"rotation": (0.0, 0.0, 17.0)},
        )

    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    with RealizeSession() as session:
        layers = realize_scene(draw, 0.0, defaults, session=session)
        cache = session.stats()
    realized = layers[0].realized
    indices, draw_stats = build_line_indices_and_stats(realized.offsets)
    metrics = {
        "layers": len(layers),
        "n_vertices": int(realized.coords.shape[0]),
        "n_lines": int(realized.offsets.size - 1),
        "geometry_bytes": int(realized.byte_size),
        "index_count": int(indices.size),
        "index_bytes": int(indices.nbytes),
        "draw_vertices": int(draw_stats.draw_vertices),
        "draw_lines": int(draw_stats.draw_lines),
        "cache_hits": cache.hits,
        "cache_misses": cache.misses,
        "cache_evictions": cache.evictions,
        "cache_entries": cache.entries,
        "cache_bytes": cache.bytes,
    }
    return _CaseOutput(
        value={
            "coords": realized.coords,
            "offsets": realized.offsets,
            "indices": indices,
        },
        metrics=metrics,
    )


def _setup_interactive_slider_scenario(
    parameters: dict[str, Any],
    _seed: int,
) -> object:
    from grafix.devtools.benchmarks.interactive_scenario_benchmark import (
        make_interactive_slider_scenario,
    )

    return make_interactive_slider_scenario(parameters)


def _workload_interactive_slider_scenario(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.interactive_scenario_benchmark import (
        InteractiveSliderScenario,
        run_interactive_slider_scenario,
    )

    if not isinstance(state, InteractiveSliderScenario):
        raise TypeError("interactive slider scenario state is invalid")
    result = run_interactive_slider_scenario(state)
    return _CaseOutput(
        value=result.value,
        metrics=result.metrics,
        contracts=result.contracts,
    )


def _setup_renderer(parameters: dict[str, Any], _seed: int) -> object:
    from grafix.devtools.benchmarks.system_benchmark import _renderer_geometry

    return (
        _renderer_geometry(polylines=int(parameters["polylines"])),
        int(parameters["frames"]),
    )


def _workload_renderer(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.system_benchmark import _renderer_cache_workload

    geometry, frames = cast(tuple[RealizedGeometry, int], state)
    payload = _renderer_cache_workload(
        geometry,
        frames=frames,
        include_semantic_frames=True,
    )
    semantic_frames = payload.pop("_semantic_frames")
    return _CaseOutput(value=semantic_frames, metrics=payload)


def _setup_animated_renderer(parameters: dict[str, Any], _seed: int) -> object:
    from grafix.devtools.benchmarks.system_benchmark import _renderer_geometry

    base = _renderer_geometry(polylines=int(parameters["polylines"]))
    geometries: list[RealizedGeometry] = []
    static_topology = str(parameters["topology"]) == "static"
    for frame in range(int(parameters["frames"])):
        coords = base.coords.copy()
        coords[:, 1] = np.float32(frame) * np.float32(0.001)
        offsets = base.offsets if static_topology else base.offsets.copy()
        geometries.append(RealizedGeometry(coords=coords, offsets=offsets))
    return tuple(geometries)


def _workload_animated_renderer(state: object) -> _CaseOutput:
    from unittest.mock import patch

    from grafix.devtools.benchmarks import system_benchmark
    from grafix.interactive.gl import draw_renderer as renderer_module

    geometries = cast(tuple[RealizedGeometry, ...], state)
    system_benchmark._BenchmarkFakeMesh.instances.clear()
    renderer = system_benchmark._fake_renderer()
    original_build = renderer_module.build_line_indices_and_stats
    index_builds = 0
    semantic_frames: list[tuple[np.ndarray, np.ndarray]] = []

    def counted_build(offsets: np.ndarray) -> Any:
        nonlocal index_builds
        index_builds += 1
        return original_build(offsets)

    with (
        patch.object(
            renderer_module,
            "LineMesh",
            system_benchmark._BenchmarkFakeMesh,
        ),
        patch.object(
            renderer_module,
            "build_line_indices_and_stats",
            counted_build,
        ),
    ):
        for frame, geometry in enumerate(geometries):
            mesh, _stats = renderer.prepare_layer_mesh(
                geometry,
                cache_key=("renderer-animated", (frame, 1)),
            )
            if mesh is None:
                raise RuntimeError("renderer benchmark returned an empty mesh")
            if mesh.last_vertices is None or mesh.last_indices is None:
                raise RuntimeError("renderer benchmark mesh upload state is missing")
            semantic_frames.append((mesh.last_vertices, mesh.last_indices))

    meshes = system_benchmark._BenchmarkFakeMesh.instances
    output = {
        "frames": len(geometries),
        "n_lines": int(geometries[0].offsets.size - 1),
        "index_builds": index_builds,
        "full_uploads": sum(mesh.upload_count for mesh in meshes),
        "vertex_only_uploads": sum(mesh.vertex_upload_count for mesh in meshes),
        "full_vertex_upload_bytes": sum(
            mesh.full_vertex_upload_bytes for mesh in meshes
        ),
        "full_index_upload_bytes": sum(
            mesh.full_index_upload_bytes for mesh in meshes
        ),
        "vertex_only_upload_bytes": sum(
            mesh.vertex_only_upload_bytes for mesh in meshes
        ),
        "candidate_entries": len(renderer._mesh_candidates),
    }
    return _CaseOutput(value=tuple(semantic_frames), metrics=output)


def _setup_multilayer_renderer(
    parameters: dict[str, Any],
    _seed: int,
) -> object:
    return dict(parameters)


def _workload_multilayer_renderer(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.system_benchmark import (
        _renderer_multilayer_dynamic_workload,
    )

    parameters = cast(dict[str, Any], state)
    layers = int(parameters["layers"])
    frames = int(parameters["frames"])
    stable_topology = bool(parameters["stable_topology"])
    payload = _renderer_multilayer_dynamic_workload(
        layers=layers,
        frames=frames,
        polylines=int(parameters["polylines"]),
        stable_topology=stable_topology,
        include_semantic_frames=True,
    )
    semantic_frames = payload.pop("_semantic_frames")
    output = cast(dict[str, Any], payload["output"])
    expected_rebuilds = layers if stable_topology else layers * frames
    expected_vertex_updates = layers * (frames - 1) if stable_topology else 0
    contracts = (
        evaluate_contract(
            contract_id="renderer.multilayer.index_builds",
            severity="hard",
            actual=int(output["index_builds"]),
            comparator="eq",
            limit=expected_rebuilds,
            reason="stable topology は layer ごとの warmup 後に再構築しない",
        ),
        evaluate_contract(
            contract_id="renderer.multilayer.vertex_only_updates",
            severity="hard",
            actual=int(output["vertex_only_uploads"]),
            comparator="eq",
            limit=expected_vertex_updates,
            reason="stable topology の後続 frame は VBO だけを更新する",
        ),
        evaluate_contract(
            contract_id="renderer.multilayer.dynamic_entry_bound",
            severity="hard",
            actual=int(output["dynamic_entries"]),
            comparator="le",
            limit=int(output["dynamic_entry_limit"]),
            reason="animated mesh pool の GL object 数を entry 上限内に保つ",
        ),
        evaluate_contract(
            contract_id="renderer.multilayer.dynamic_byte_bound",
            severity="hard",
            actual=int(output["dynamic_bytes"]),
            comparator="le",
            limit=int(output["dynamic_byte_limit"]),
            reason="animated mesh pool を byte 上限内に保つ",
        ),
    )
    return _CaseOutput(
        value=semantic_frames,
        metrics=payload,
        contracts=contracts,
    )


def _workload_mp_draw(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.mp_draw_benchmark import run_mp_draw_benchmarks

    payload = run_mp_draw_benchmarks(
        repeats=int(state["repeats"]),  # type: ignore[index]
        steady_frames=int(state["steady_frames"]),  # type: ignore[index]
        heavy_iterations=int(state["heavy_iterations"]),  # type: ignore[index]
        n_worker=2,
    )
    return _CaseOutput(value=payload["output"], metrics=payload)


def _workload_mp_slider_churn(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.mp_draw_benchmark import (
        run_mp_slider_churn_benchmarks,
    )

    parameters = cast(dict[str, Any], state)
    payload = run_mp_slider_churn_benchmarks(
        frames=int(parameters["frames"]),
        frame_interval_s=float(parameters["frame_interval_s"]),
    )
    contracts: list[ContractResult] = []
    for case_id, modes in cast(dict[str, Any], payload["cases"]).items():
        for mode_name, mode in cast(dict[str, Any], modes).items():
            prefix = f"{case_id}.{mode_name}"
            contracts.append(
                evaluate_contract(
                    contract_id=f"mp.slider.{prefix}.progress",
                    severity="hard",
                    actual=bool(mode["progress_contract_met"]),
                    comparator="eq",
                    limit=True,
                    reason=(
                        "revision、checksum、queue progress の invariant を満たす"
                    ),
                )
            )
            contracts.append(
                evaluate_contract(
                    contract_id=f"mp.slider.{prefix}.interactive_target",
                    severity="hard",
                    actual=bool(mode["interactive_target_met"]),
                    comparator="eq",
                    limit=True,
                    reason="slider の interactive latency target を満たす",
                )
            )
    return _CaseOutput(
        value=payload["output"],
        metrics=payload,
        contracts=tuple(contracts),
    )


def _hash_array(digest: Any, array: np.ndarray) -> None:
    contiguous = np.ascontiguousarray(array)
    digest.update(contiguous.dtype.str.encode("ascii"))
    digest.update(json.dumps(list(contiguous.shape), separators=(",", ":")).encode("ascii"))
    if contiguous.nbytes:
        digest.update(memoryview(contiguous).cast("B"))


def _json_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_value(dataclasses.asdict(value))
    if isinstance(value, Geometry):
        return {"geometry_id": str(value.id), "op": value.op}
    if isinstance(value, np.ndarray):
        digest = hashlib.sha256()
        _hash_array(digest, value)
        return {
            "dtype": value.dtype.str,
            "shape": list(value.shape),
            "sha256": digest.hexdigest(),
        }
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _peak_rss_bytes() -> int:
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return rss if sys.platform == "darwin" else rss * 1024


def _main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "--child":
        raise SystemExit("runner is an internal child entry point")
    return _child_main(Path(argv[1]), Path(argv[2]))


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))


__all__ = [
    "CaseDefinition",
    "canonical_checksum",
    "case_definitions",
    "geometry_checksum",
    "normalize_metrics",
    "run_case_isolated",
    "select_case_definitions",
]
