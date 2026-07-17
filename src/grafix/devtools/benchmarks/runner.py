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
    Sample,
    case_result_from_dict,
    case_result_to_dict,
    summarize_samples,
)

_DEFAULT_TIMEOUT_SECONDS = 120.0
_MAX_CALIBRATION_ITERATIONS = 1 << 20
_CASES_SOURCE_FILE = Path(__file__).with_name("cases.py")
_SYSTEM_SOURCE_FILE = Path(__file__).with_name("system_benchmark.py")
_MP_SOURCE_FILE = Path(__file__).with_name("mp_draw_benchmark.py")


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
    workload: Callable[[object], "_CaseOutput"]
    support_source_files: tuple[Path, ...] = ()
    support_implementations: tuple[Callable[..., object], ...] = ()
    checksum_policy: str = "exact"

    def spec(self, *, seed: int) -> CaseSpec:
        return make_case_spec(
            case_id=self.case_id,
            version=self.version,
            label=self.label,
            category=self.category,
            suite=self.suite,
            fixture=self.fixture,
            parameters=self.parameters,
            seed=seed,
            implementation=(
                self.setup,
                self.workload,
                *self.support_implementations,
            ),
            support_source_files=self.support_source_files,
            tags=self.tags,
            checksum_policy=self.checksum_policy,
        )


@dataclass(frozen=True, slots=True)
class _CaseOutput:
    value: object
    metrics: dict[str, Any] = field(default_factory=dict)


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
        ),
        *_effect_definitions(),
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
    sample_count = max(1, int(samples))
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
    try:
        state = definition.setup(dict(definition.parameters), int(seed))
        setup_rss = _peak_rss_bytes()
        if mode == "warm":
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
        output: _CaseOutput | None = None
        was_gc_enabled = gc.isenabled()
        if disable_gc and was_gc_enabled:
            gc.disable()
        try:
            for _ in range(samples):
                started = time.perf_counter_ns()
                for _iteration in range(iterations):
                    output = definition.workload(state)
                raw_samples.append(
                    Sample(
                        elapsed_ns=time.perf_counter_ns() - started,
                        iterations=iterations,
                    )
                )
        finally:
            if disable_gc and was_gc_enabled:
                gc.enable()
        if output is None:
            raise RuntimeError("benchmark workload returned no output")
        peak_rss = _peak_rss_bytes()
        checksum, checksum_kind = canonical_checksum(output.value)
        return CaseResult(
            spec=spec,
            status="ok",
            samples=tuple(raw_samples),
            stats=summarize_samples(raw_samples),
            checksum=checksum,
            checksum_kind=checksum_kind,
            setup_rss_bytes=setup_rss,
            baseline_rss_bytes=baseline_rss,
            peak_rss_bytes=peak_rss,
            peak_rss_delta_bytes=max(0, peak_rss - baseline_rss),
            metrics=output.metrics,
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


def _calibrate(
    workload: Callable[[object], _CaseOutput],
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
    failures = [result for result in results if result.status != "ok"]
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
    return CaseResult(
        spec=spec,
        status="ok",
        samples=samples,
        stats=summarize_samples(samples),
        checksum=results[0].checksum,
        checksum_kind=results[0].checksum_kind,
        setup_rss_bytes=rss_result.setup_rss_bytes,
        baseline_rss_bytes=rss_result.baseline_rss_bytes,
        peak_rss_bytes=rss_result.peak_rss_bytes,
        peak_rss_delta_bytes=rss_result.peak_rss_delta_bytes,
        metrics=results[-1].metrics,
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
    workload: Callable[[object], _CaseOutput],
    support_source_files: tuple[Path, ...] = (),
    support_implementations: tuple[Callable[..., object], ...] = (),
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
        support_source_files=support_source_files,
        support_implementations=support_implementations,
        checksum_policy="exact",
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
            )
        )
    return definitions


def _legacy_system_definitions() -> list[CaseDefinition]:
    """従来の system/micro 診断を schema v3 の個別 case として返す。"""

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
    args = dict(spec.defaults)
    args.update(
        {
            key: value
            for key, value in parameters.items()
            if key not in {"effect", "fixture"}
        }
    )
    args_tuple = tuple(sorted(args.items()))
    return spec.evaluator, benchmark_case.inputs, args_tuple


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


def _workload_effect(state: object) -> _CaseOutput:
    evaluator, inputs, args_tuple = cast(tuple[Any, Any, Any], state)
    output = evaluator(inputs, args_tuple)
    geometry = (
        output
        if isinstance(output, RealizedGeometry)
        else RealizedGeometry(coords=output[0], offsets=output[1])
    )
    return _CaseOutput(
        value=geometry,
        metrics={
            "n_vertices": int(geometry.coords.shape[0]),
            "n_lines": int(geometry.offsets.size - 1),
            "output_bytes": int(geometry.coords.nbytes + geometry.offsets.nbytes),
        },
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


def _workload_mp_draw(state: object) -> _CaseOutput:
    from grafix.devtools.benchmarks.mp_draw_benchmark import run_mp_draw_benchmarks

    payload = run_mp_draw_benchmarks(
        repeats=int(state["repeats"]),  # type: ignore[index]
        steady_frames=int(state["steady_frames"]),  # type: ignore[index]
        heavy_iterations=int(state["heavy_iterations"]),  # type: ignore[index]
        n_worker=2,
    )
    return _CaseOutput(value=payload["output"], metrics=payload)


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
    "run_case_isolated",
    "select_case_definitions",
]
