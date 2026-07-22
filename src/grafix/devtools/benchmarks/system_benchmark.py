"""CPU system/micro benchmark を小さな共通 schema で計測する。"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
from pathlib import Path
from types import CodeType
from typing import Any, cast

import numpy as np

from grafix.core.builtins import builtin_operation_catalog
from grafix.core.geometry import Geometry
from grafix.core.parameters.key import _automatic_site_id
from grafix.core.primitives.asemic import _generate_asemic_glyph, asemic
from grafix.core.realize import RealizeSession
from grafix.core.realized_geometry import RealizedGeometry, concat_realized_geometries
from grafix.core.runtime_limits import RuntimeLimits
from grafix.devtools.benchmarks.definition import (
    CaseDefinition,
    define_case,
    scaled_case_definitions,
)
from grafix.devtools.benchmarks.metrics import (
    cache_metrics,
    counter_metric,
    gauge_metric,
    summarize_nanoseconds,
)
from grafix.devtools.benchmarks.schema import BenchmarkOutput
from grafix.export.gcode import _Stroke, _order_strokes_in_layer


def case_definitions() -> tuple[CaseDefinition, ...]:
    """System/micro benchmark cases を返す。"""

    cases = (
        (
            "micro.geometry_signature",
            "Geometry signature",
            "geometry_signature",
            {"iterations": 1_000},
            setup_passthrough,
            workload_geometry_signature,
            False,
        ),
        (
            "micro.rotate_scale_identity",
            "rotate/scale identity",
            "rotate_scale_identity",
            {"points": 50_000, "iterations": 1_000},
            setup_rotate_scale_identity,
            workload_rotate_scale_identity,
            False,
        ),
        (
            "micro.cached_site_id",
            "cached site ID",
            "cached_site_id",
            {"iterations": 10_000},
            setup_passthrough,
            workload_cached_site_id,
            False,
        ),
        (
            "micro.realized_concat",
            "packed realized concat",
            "realized_concat",
            {"parts": 128, "vertices_per_part": 3},
            setup_realized_concat,
            workload_realized_concat,
            False,
        ),
        (
            "micro.asemic",
            "asemic cached glyph/layout",
            "asemic",
            {"text": "CACHE CACHE\nSYSTEM", "nodes": 24},
            setup_passthrough,
            workload_asemic,
            True,
        ),
        (
            "micro.gcode_ordering",
            "G-code stroke ordering",
            "gcode_ordering",
            {"strokes": 200},
            setup_gcode_ordering,
            workload_gcode_ordering,
            False,
        ),
        (
            "system.cold_import",
            "cold import grafix",
            "cold_import",
            {"repeats": 1},
            setup_passthrough,
            workload_cold_import,
            True,
        ),
    )
    definitions = [
        define_case(
            case_id,
            label,
            category="system" if case_id.startswith("system.") else "micro",
            suite="system",
            fixture=fixture,
            parameters={"workload": fixture, **parameters},
            tags=("system-diagnostic",),
            selectable_suites=("system",),
            setup=setup,
            workload=workload,
            support_source_files=(Path(__file__),),
            self_sampling=self_sampling,
        )
        for case_id, label, fixture, parameters, setup, workload, self_sampling in cases
    ]
    definitions.extend(
        scaled_case_definitions(
            prefix="core.concat_recipe",
            label="repeated Geometry +",
            values=(10, 1_000, 10_000),
            parameter_name="parts",
            category="core",
            suite="micro",
            fixture="line_recipe_sequence",
            setup=setup_concat_recipe,
            workload=workload_concat_recipe,
            suites=(("smoke", "micro"), ("micro",), ("soak",)),
        )
    )
    definitions.append(
        define_case(
            "core.deep_dag.depth_5000",
            "deep translate DAG realize",
            category="core",
            suite="pipeline",
            fixture="translate_chain",
            parameters={"depth": 5_000},
            tags=("deep-dag", "cache-disabled", "exact-checksum"),
            selectable_suites=("soak",),
            setup=setup_deep_dag,
            workload=workload_deep_dag,
        )
    )
    return tuple(definitions)


def _geometry_signature_workload(*, iterations: int) -> dict[str, Any]:
    base = Geometry.create("signature_base", params={"seed": 7, "scale": 2.5})
    digest = hashlib.blake2b(digest_size=8)
    count = max(1, int(iterations))
    for index in range(count):
        geometry = Geometry.create(
            "signature_effect",
            inputs=(base,),
            params={
                "frame": index % 97,
                "vector": (index % 3, float(index % 11) / 10.0, -0.0),
            },
        )
        digest.update(geometry.id.encode("ascii"))
    return {"output": {"signatures": count, "checksum": digest.hexdigest()}}


def _identity_geometry(*, points: int) -> RealizedGeometry:
    point_count = max(1, int(points))
    coords = np.zeros((point_count, 3), dtype=np.float32)
    coords[:, 0] = np.arange(point_count, dtype=np.float32)
    offsets = np.asarray([0, point_count], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _rotate_scale_identity_workload(
    geometry: RealizedGeometry,
    *,
    iterations: int,
    include_semantic_outputs: bool = False,
) -> dict[str, Any]:
    catalog = builtin_operation_catalog()
    rotate = catalog.resolve("effect", "rotate").evaluator
    scale = catalog.resolve("effect", "scale").evaluator
    inputs = (geometry,)
    rotate_args = (("activate", True), ("rotation", (0.0, 0.0, 0.0)))
    scale_args = (("activate", True), ("scale", (1.0, 1.0, 1.0)))

    count = max(1, int(iterations))
    reused = 0
    rotate_output: object = geometry
    scale_output: object = geometry
    for _ in range(count):
        rotate_output = rotate(inputs, rotate_args)
        scale_output = scale(inputs, scale_args)
        reused += int(rotate_output is geometry)
        reused += int(scale_output is geometry)

    operations = count * 2
    result: dict[str, Any] = {
        "output": {
            **_describe_realized(geometry),
            "iterations": count,
            "operations": operations,
            "input_reuses": reused,
            "input_object_reused": reused == operations,
        }
    }
    if include_semantic_outputs:
        result["_semantic_outputs"] = (rotate_output, scale_output)
    return result


def _cached_site_id_workload(*, iterations: int, code: CodeType) -> dict[str, Any]:
    _automatic_site_id.cache_clear()
    count = max(1, int(iterations))
    site_id = ""
    for _ in range(count):
        site_id = _automatic_site_id(code, 128, __name__)
    info = _automatic_site_id.cache_info()
    return {
        "output": {"lookups": count, "site_id": site_id},
        "cache": {
            "hits": int(info.hits),
            "misses": int(info.misses),
            "evictions": 0,
            "entries": int(info.currsize),
            "bytes": 0,
        },
    }


def _concat_inputs(*, parts: int, vertices_per_part: int) -> tuple[RealizedGeometry, ...]:
    part_count = max(1, int(parts))
    vertex_count = max(2, int(vertices_per_part))
    inputs: list[RealizedGeometry] = []
    for part_index in range(part_count):
        x = np.arange(vertex_count, dtype=np.float32) + np.float32(part_index)
        coords = np.column_stack([x, np.full_like(x, part_index % 13), np.zeros_like(x)]).astype(
            np.float32, copy=False
        )
        offsets = np.asarray([0, vertex_count], dtype=np.int32)
        inputs.append(RealizedGeometry(coords=coords, offsets=offsets))
    return tuple(inputs)


def _concat_workload(inputs: tuple[RealizedGeometry, ...]) -> dict[str, Any]:
    output = concat_realized_geometries(*inputs)
    return {"output": {**_describe_realized(output), "parts": len(inputs)}}


def _asemic_workload(
    *,
    text: str,
    nodes: int,
    include_semantic_geometry: bool = False,
) -> dict[str, Any]:
    coords, offsets = asemic(
        text=text,
        seed=17,
        n_nodes=int(nodes),
        candidates=8,
        stroke_min=2,
        stroke_max=4,
        walk_min_steps=2,
        walk_max_steps=4,
        stroke_style="bezier",
        bezier_samples=8,
    )
    info = _generate_asemic_glyph.cache_info()
    result: dict[str, Any] = {
        "output": _describe_arrays(coords, offsets),
        "cache": {
            "hits": int(info.hits),
            "misses": int(info.misses),
            "evictions": 0,
            "entries": int(info.currsize),
            "bytes": 0,
        },
    }
    if include_semantic_geometry:
        result["_semantic_geometry"] = (coords, offsets)
    return result


def _random_strokes(*, count: int, seed: int) -> list[_Stroke]:
    rng = np.random.default_rng(int(seed))
    endpoints = rng.integers(-10_000, 10_001, size=(max(1, int(count)), 2, 2))
    strokes: list[_Stroke] = []
    for index, points in enumerate(endpoints):
        start = (int(points[0, 0]), int(points[0, 1]))
        end = (int(points[1, 0]), int(points[1, 1]))
        strokes.append(
            _Stroke(
                poly_idx=index // 4,
                seg_idx=index % 4,
                points_canvas=[
                    (float(start[0]), float(start[1])),
                    (float(end[0]), float(end[1])),
                ],
                start_q=start,
                end_q=end,
            )
        )
    return strokes


def _gcode_ordering_workload(strokes: list[_Stroke]) -> dict[str, Any]:
    ordered = _order_strokes_in_layer(strokes, allow_reverse=True)
    digest = hashlib.blake2b(digest_size=8)
    reversed_count = 0
    for stroke, reversed_ in ordered:
        reversed_count += int(reversed_)
        digest.update(f"{stroke.poly_idx}:{stroke.seg_idx}:{int(reversed_)};".encode("ascii"))
    return {
        "output": {
            "strokes": len(ordered),
            "reversed": reversed_count,
            "checksum": digest.hexdigest(),
        }
    }


def _cold_import_benchmark(*, repeats: int) -> dict[str, Any]:
    samples: list[int] = []
    peak_rss = 0
    errors: list[str] = []
    script = (
        "import json,resource,sys,time\n"
        "started=time.perf_counter_ns()\n"
        "import grafix\n"
        "elapsed=time.perf_counter_ns()-started\n"
        "rss=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)\n"
        "rss=rss if sys.platform=='darwin' else rss*1024\n"
        "print(json.dumps({'wall_ns':elapsed,'peak_rss_bytes':rss}))\n"
    )
    environment = dict(os.environ)
    environment.setdefault("PYTHONHASHSEED", "0")
    for _ in range(max(1, int(repeats))):
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                timeout=120.0,
                env=environment,
            )
            payload = json.loads(completed.stdout.splitlines()[-1])
            samples.append(int(payload["wall_ns"]))
            peak_rss = max(peak_rss, int(payload["peak_rss_bytes"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{exc.__class__.__name__}: {exc}")

    result: dict[str, Any] = {
        "id": "cold_import_grafix",
        "label": "cold import grafix",
        "category": "system",
    }
    if not samples:
        result.update({"status": "error", "error": "; ".join(errors)})
        return result
    result.update(
        {
            "status": "ok",
            **summarize_nanoseconds(samples),
            "peak_rss_bytes": peak_rss,
            "output": {"module": "grafix"},
        }
    )
    if errors:
        result["errors"] = errors
    return result


def _describe_realized(geometry: RealizedGeometry) -> dict[str, int]:
    return _describe_arrays(geometry.coords, geometry.offsets)


def _describe_arrays(coords: np.ndarray, offsets: np.ndarray) -> dict[str, int]:
    return {
        "n_vertices": int(coords.shape[0]),
        "n_lines": max(0, int(offsets.size) - 1),
        "bytes": int(coords.nbytes + offsets.nbytes),
    }


def _peak_rss_bytes() -> int:
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return rss if sys.platform == "darwin" else rss * 1024


def setup_passthrough(parameters: dict[str, Any], _seed: int) -> object:
    return dict(parameters)


def setup_rotate_scale_identity(parameters: dict[str, Any], _seed: int) -> object:
    state = dict(parameters)
    state["geometry"] = _identity_geometry(points=int(state["points"]))
    return state


def setup_realized_concat(parameters: dict[str, Any], _seed: int) -> object:
    state = dict(parameters)
    state["inputs"] = _concat_inputs(
        parts=int(state["parts"]),
        vertices_per_part=int(state["vertices_per_part"]),
    )
    return state


def setup_gcode_ordering(parameters: dict[str, Any], seed: int) -> object:
    state = dict(parameters)
    state["stroke_values"] = _random_strokes(count=int(state["strokes"]), seed=int(seed))
    return state


def setup_concat_recipe(parameters: dict[str, Any], _seed: int) -> object:
    count = max(1, int(parameters["parts"]))
    return tuple(
        Geometry.create(
            "__benchmark_leaf__",
            params={"index": index},
        )
        for index in range(count)
    )


def workload_concat_recipe(state: object) -> BenchmarkOutput:
    geometries = cast(tuple[Geometry, ...], state)
    result = geometries[0]
    for geometry in geometries[1:]:
        result = cast(Geometry, result + geometry)
    return BenchmarkOutput(
        value=result,
        metrics=(
            counter_metric(
                "parts",
                len(geometries),
                unit="count",
                phase="measure",
                scope="core",
            ),
            counter_metric(
                "root_inputs",
                len(result.inputs),
                unit="count",
                phase="measure",
                scope="core",
            ),
            gauge_metric(
                "recipe_id",
                result.id,
                unit="sha256",
                phase="measure",
                scope="core",
            ),
        ),
    )


def setup_deep_dag(parameters: dict[str, Any], _seed: int) -> object:
    from grafix import G
    from grafix.core.builtins import ensure_builtin_effect_registered

    ensure_builtin_effect_registered("translate")
    node = G.line(length=1.0)
    for _ in range(max(1, int(parameters["depth"]))):
        node = Geometry.create(
            "translate",
            inputs=(node,),
            params={"activate": True, "delta": (0.001, 0.0, 0.0)},
        )
    return node


def workload_deep_dag(state: object) -> BenchmarkOutput:
    with RealizeSession(runtime_limits=RuntimeLimits(cpu_cache_bytes=0)) as session:
        geometry = session.realize(state)  # type: ignore[arg-type]
    return BenchmarkOutput(
        value=geometry,
        metrics=(
            counter_metric(
                "depth",
                5_000,
                unit="count",
                phase="measure",
                scope="core",
            ),
        ),
    )


def workload_geometry_signature(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    payload = _geometry_signature_workload(iterations=int(values["iterations"]))
    output = cast(dict[str, Any], payload["output"])
    return BenchmarkOutput(
        value=output,
        metrics=(
            counter_metric(
                "signatures",
                int(output["signatures"]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            gauge_metric(
                "checksum", str(output["checksum"]), unit="blake2b", phase="measure", scope="system"
            ),
        ),
    )


def workload_rotate_scale_identity(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    geometry = cast(RealizedGeometry, values["geometry"])
    payload = _rotate_scale_identity_workload(
        geometry, iterations=int(values["iterations"]), include_semantic_outputs=True
    )
    semantic_outputs = list(cast(tuple[object, ...], payload.pop("_semantic_outputs")))
    output = cast(dict[str, Any], payload["output"])
    return BenchmarkOutput(
        value=semantic_outputs,
        metrics=(
            counter_metric(
                "n_vertices",
                int(output["n_vertices"]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            counter_metric(
                "n_lines", int(output["n_lines"]), unit="count", phase="measure", scope="system"
            ),
            counter_metric(
                "output_bytes", int(output["bytes"]), unit="bytes", phase="measure", scope="system"
            ),
            counter_metric(
                "iterations",
                int(output["iterations"]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            counter_metric(
                "operations",
                int(output["operations"]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            counter_metric(
                "input_reuses",
                int(output["input_reuses"]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            gauge_metric(
                "input_object_reused",
                bool(output["input_object_reused"]),
                unit="boolean",
                phase="measure",
                scope="system",
            ),
        ),
    )


def workload_cached_site_id(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    payload = _cached_site_id_workload(
        iterations=int(values["iterations"]), code=_cached_site_id_workload.__code__
    )
    output = cast(dict[str, Any], payload["output"])
    cache = cast(dict[str, Any], payload["cache"])
    return BenchmarkOutput(
        value=output,
        metrics=(
            counter_metric(
                "lookups", int(output["lookups"]), unit="count", phase="measure", scope="system"
            ),
            gauge_metric(
                "site_id", str(output["site_id"]), unit="text", phase="measure", scope="system"
            ),
            *cache_metrics(cache, name="cache", phase="measure", scope="system"),
        ),
    )


def workload_realized_concat(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    result = concat_realized_geometries(*cast(tuple[RealizedGeometry, ...], values["inputs"]))
    return BenchmarkOutput(
        value=result,
        metrics=(
            counter_metric(
                "parts", int(values["parts"]), unit="count", phase="measure", scope="system"
            ),
            counter_metric(
                "n_vertices",
                int(result.coords.shape[0]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            counter_metric(
                "n_lines",
                int(result.offsets.size - 1),
                unit="count",
                phase="measure",
                scope="system",
            ),
            counter_metric(
                "output_bytes", result.byte_size, unit="bytes", phase="measure", scope="system"
            ),
        ),
    )


def workload_asemic(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    payload = _asemic_workload(
        text=str(values["text"]), nodes=int(values["nodes"]), include_semantic_geometry=True
    )
    semantic_geometry = cast(tuple[np.ndarray, np.ndarray], payload.pop("_semantic_geometry"))
    output = cast(dict[str, Any], payload["output"])
    return BenchmarkOutput(
        value=RealizedGeometry(coords=semantic_geometry[0], offsets=semantic_geometry[1]),
        metrics=(
            counter_metric(
                "n_vertices",
                int(output["n_vertices"]),
                unit="count",
                phase="measure",
                scope="system",
            ),
            counter_metric(
                "n_lines", int(output["n_lines"]), unit="count", phase="measure", scope="system"
            ),
            counter_metric(
                "output_bytes", int(output["bytes"]), unit="bytes", phase="measure", scope="system"
            ),
            *cache_metrics(
                cast(dict[str, Any], payload["cache"]),
                name="cache",
                phase="measure",
                scope="system",
            ),
        ),
    )


def workload_gcode_ordering(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    payload = _gcode_ordering_workload(values["stroke_values"])
    output = cast(dict[str, Any], payload["output"])
    return BenchmarkOutput(
        value=output,
        metrics=(
            counter_metric(
                "strokes", int(output["strokes"]), unit="count", phase="measure", scope="system"
            ),
            counter_metric(
                "reversed", int(output["reversed"]), unit="count", phase="measure", scope="system"
            ),
            gauge_metric(
                "checksum", str(output["checksum"]), unit="blake2b", phase="measure", scope="system"
            ),
        ),
    )


def workload_cold_import(state: object) -> BenchmarkOutput:
    values = cast(dict[str, Any], state)
    payload = _cold_import_benchmark(repeats=int(values["repeats"]))
    if payload.get("status") != "ok":
        raise RuntimeError(str(payload.get("error", "cold import failed")))
    return BenchmarkOutput(
        value=payload["output"],
        metrics=(
            gauge_metric(
                "mean_ms", float(payload["mean_ms"]), unit="ms", phase="measure", scope="system"
            ),
            gauge_metric(
                "median_ms", float(payload["median_ms"]), unit="ms", phase="measure", scope="system"
            ),
            gauge_metric(
                "p95_ms", float(payload["p95_ms"]), unit="ms", phase="measure", scope="system"
            ),
            counter_metric(
                "samples", int(payload["n"]), unit="count", phase="measure", scope="system"
            ),
            counter_metric(
                "peak_rss_bytes",
                int(payload["peak_rss_bytes"]),
                unit="bytes",
                phase="measure",
                scope="system",
            ),
        ),
    )


__all__ = [
    "case_definitions",
]
