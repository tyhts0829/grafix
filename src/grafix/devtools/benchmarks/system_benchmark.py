"""CPU system/micro benchmark を小さな共通 schema で計測する。"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from types import CodeType
from typing import Any
from unittest.mock import patch

import numpy as np

from grafix.core.builtins import ensure_builtin_effect_registered
from grafix.core.effect_registry import effect_registry
from grafix.core.geometry import Geometry
from grafix.core.layer import LayerStyleDefaults
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.key import _automatic_site_id
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.pipeline import realize_scene
from grafix.core.primitives.asemic import _generate_asemic_glyph, asemic
from grafix.core.realize import RealizeSession
from grafix.core.realized_geometry import RealizedGeometry, concat_realized_geometries
from grafix.export.gcode import _Stroke, _order_strokes_in_layer
from grafix.interactive.gl import draw_renderer as renderer_module
from grafix.interactive.gl.draw_renderer import DrawRenderer
from grafix.interactive.gl.index_buffer import build_line_indices_and_stats
from grafix.interactive.parameter_gui import store_bridge


@dataclass(slots=True)
class _FakeBuffer:
    size: int


class _BenchmarkFakeMesh:
    """GL を使わず upload 回数と予約 byte 数だけを再現する mesh。"""

    instances: list[_BenchmarkFakeMesh] = []

    def __init__(
        self,
        ctx: object,
        program: object,
        initial_reserve: int = 4_096,
    ) -> None:
        del ctx, program
        self.vbo = _FakeBuffer(size=int(initial_reserve))
        self.ibo = _FakeBuffer(size=int(initial_reserve))
        self.upload_count = 0
        self.vertex_upload_count = 0
        self.full_vertex_upload_bytes = 0
        self.full_index_upload_bytes = 0
        self.vertex_only_upload_bytes = 0
        self.last_vertices: np.ndarray | None = None
        self.last_indices: np.ndarray | None = None
        self.released = False
        self.instances.append(self)

    def upload(self, vertices: np.ndarray, indices: np.ndarray) -> None:
        vertices_f32 = np.ascontiguousarray(vertices, dtype=np.float32)
        indices_u32 = np.ascontiguousarray(indices, dtype=np.uint32)
        self.upload_count += 1
        self.full_vertex_upload_bytes += int(vertices_f32.nbytes)
        self.full_index_upload_bytes += int(indices_u32.nbytes)
        self.last_vertices = vertices_f32
        self.last_indices = indices_u32
        self.vbo.size = max(self.vbo.size, int(vertices_f32.nbytes))
        self.ibo.size = max(self.ibo.size, int(indices_u32.nbytes))

    def upload_vertices(self, vertices: np.ndarray) -> None:
        """scratch topology 再利用時の VBO-only upload を再現する。"""

        vertices_f32 = np.ascontiguousarray(vertices, dtype=np.float32)
        self.vertex_upload_count += 1
        self.vertex_only_upload_bytes += int(vertices_f32.nbytes)
        self.last_vertices = vertices_f32
        self.vbo.size = max(self.vbo.size, int(vertices_f32.nbytes))

    def release(self) -> None:
        self.released = True


def _summarize_ns(samples: list[int]) -> dict[str, float | int]:
    ordered = sorted(int(sample) for sample in samples)
    if not ordered:
        return {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "n": 0}
    mean = float(sum(ordered)) / float(len(ordered))
    return {
        "mean_ms": mean / 1_000_000.0,
        "median_ms": _percentile(ordered, 0.5) / 1_000_000.0,
        "p95_ms": _percentile(ordered, 0.95) / 1_000_000.0,
        "n": len(ordered),
    }


def _percentile(ordered: list[int], fraction: float) -> float:
    if len(ordered) == 1:
        return float(ordered[0])
    position = float(len(ordered) - 1) * float(fraction)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - float(lower)
    return float(ordered[lower]) * (1.0 - weight) + float(ordered[upper]) * weight


def _draw_geometry(*, frame: int, sides: int) -> Geometry:
    base = Geometry.create(
        "polygon",
        params={"n_sides": int(sides), "scale": 20.0},
    )
    angle = float(int(frame)) * 0.125
    return Geometry.create(
        "rotate",
        inputs=(base,),
        params={
            "rotation": (0.0, 0.0, angle),
            "auto_center": False,
            "pivot": (0.0, 0.0, 0.0),
        },
    )


def _animated_soak(*, frames: int, sides: int) -> dict[str, Any]:
    estimated_bytes = (int(sides) + 1) * 3 * np.dtype(np.float32).itemsize + 2 * np.dtype(
        np.int32
    ).itemsize
    cache_limit = max(1_024, 2 * int(estimated_bytes) + 64)
    last: RealizedGeometry | None = None
    with RealizeSession(max_cache_bytes=cache_limit) as session:
        for frame in range(max(1, int(frames))):
            last = session.realize(_draw_geometry(frame=frame, sides=int(sides)))
        stats = session.stats()

    assert last is not None
    return {
        "output": {
            **_describe_realized(last),
            "frames": max(1, int(frames)),
            "unique_geometry_ids": max(1, int(frames)),
            "static_base_hits": max(0, int(frames) - 1),
        },
        "cache": {
            "hits": stats.hits,
            "misses": stats.misses,
            "evictions": stats.evictions,
            "entries": stats.entries,
            "bytes": stats.bytes,
            "budget_bytes": cache_limit,
        },
    }


def _draw_realize_indices(*, grid_size: int) -> dict[str, Any]:
    size = max(1, int(grid_size))

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
    return {
        "output": {
            **_describe_realized(realized),
            "layers": len(layers),
            "index_count": int(indices.size),
            "index_bytes": int(indices.nbytes),
            "draw_vertices": draw_stats.draw_vertices,
            "draw_lines": draw_stats.draw_lines,
        },
        "cache": {
            "hits": cache.hits,
            "misses": cache.misses,
            "evictions": cache.evictions,
            "entries": cache.entries,
            "bytes": cache.bytes,
        },
    }


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
    ensure_builtin_effect_registered("rotate")
    ensure_builtin_effect_registered("scale")
    rotate = effect_registry["rotate"].evaluator
    scale = effect_registry["scale"].evaluator
    inputs = (geometry,)
    rotate_args = (("rotation", (0.0, 0.0, 0.0)),)
    scale_args = (("scale", (1.0, 1.0, 1.0)),)

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


def _parameter_store(*, rows: int) -> ParamStore:
    row_count = max(1, int(rows))
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=float(row_count))
    records = [
        FrameParamRecord(
            key=ParameterKey(
                op="line",
                site_id=f"model-bench-{index:06d}",
                arg="length",
            ),
            base=float(index),
            meta=meta,
            explicit=False,
            effective=float(index),
        )
        for index in range(row_count)
    ]
    store = ParamStore()
    merge_frame_params(store, records)
    return store


def _parameter_snapshot_model_workload(
    store: ParamStore,
    *,
    frames: int,
) -> dict[str, Any]:
    """実 UI を呼ばず、snapshot/model と毎frame準備だけを通す。"""

    frame_count = max(2, int(frames))
    store._touch()
    store_bridge.clear_parameter_table_model_cache()
    render_calls = 0
    visible_rows = 0

    def fake_render(rows: list[Any], **_kwargs: Any) -> tuple[bool, list[Any]]:
        nonlocal render_calls, visible_rows
        render_calls += 1
        visible_rows = len(rows)
        return False, rows

    samples: list[int] = []
    first_frame_ns = 0
    with patch.object(store_bridge, "render_parameter_table", fake_render):
        for frame in range(frame_count):
            started = time.perf_counter_ns()
            changed = store_bridge.render_store_parameter_table(
                store,
                show_inactive_params=True,
            )
            elapsed = time.perf_counter_ns() - started
            if changed:
                raise RuntimeError("benchmark の fake UI が store を変更した")
            if frame == 0:
                first_frame_ns = elapsed
            else:
                samples.append(elapsed)

    build_count = store_bridge.parameter_table_model_build_count()
    steady = _summarize_ns(samples)
    return {
        "output": {
            "frames": frame_count,
            "rows": visible_rows,
            "snapshot_entries": len(store_snapshot(store)),
            "render_calls": render_calls,
            "model_builds": build_count,
            "first_frame_ms": float(first_frame_ns) / 1_000_000.0,
            "steady_median_ms": steady["median_ms"],
            "steady_p95_ms": steady["p95_ms"],
        },
        "cache": {
            "hits": max(0, frame_count - build_count),
            "misses": build_count,
            "evictions": 0,
            "entries": int(build_count > 0),
            "bytes": 0,
        },
    }


def _renderer_geometry(*, polylines: int) -> RealizedGeometry:
    line_count = max(1, int(polylines))
    coords = np.zeros((line_count * 2, 3), dtype=np.float32)
    coords[:, 0] = np.arange(line_count * 2, dtype=np.float32)
    offsets = np.arange(0, line_count * 2 + 1, 2, dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _fake_renderer() -> Any:
    renderer: Any = DrawRenderer.__new__(DrawRenderer)
    renderer.ctx = object()
    renderer.program = object()
    renderer._scratch_mesh = _BenchmarkFakeMesh(renderer.ctx, renderer.program)
    renderer._scratch_topology = None
    renderer._mesh_cache = OrderedDict()
    renderer._mesh_candidates = OrderedDict()
    renderer._mesh_cache_bytes = 0
    renderer._mesh_cache_max_bytes = 256 * 1024 * 1024
    # 最適化前 source も同じ schema v3 harness で測れるよう、旧candidate
    # accounting fieldもfake instanceにだけ用意する。
    renderer._mesh_candidates_bytes = 0
    renderer._mesh_candidates_max_bytes = 64 * 1024 * 1024
    renderer._mesh_candidates_max_entries = 4_096
    return renderer


def _renderer_cache_workload(
    geometry: RealizedGeometry,
    *,
    frames: int,
    include_semantic_frames: bool = False,
) -> dict[str, Any]:
    """fake mesh で candidate→昇格→steady cache hit を計測する。"""

    frame_count = max(3, int(frames))
    _BenchmarkFakeMesh.instances.clear()
    renderer = _fake_renderer()
    cache_key = ("renderer-benchmark", (1, 1))
    original_build = renderer_module.build_line_indices_and_stats
    index_builds = 0
    cache_hits = 0
    cache_misses = 0

    def counted_build(offsets: np.ndarray):
        nonlocal index_builds
        index_builds += 1
        return original_build(offsets)

    steady_samples: list[int] = []
    semantic_frames: list[tuple[np.ndarray, np.ndarray]] = []
    stats = None
    with (
        patch.object(renderer_module, "LineMesh", _BenchmarkFakeMesh),
        patch.object(
            renderer_module,
            "build_line_indices_and_stats",
            counted_build,
        ),
    ):
        for frame in range(frame_count):
            cached_before = cache_key in renderer._mesh_cache
            started = time.perf_counter_ns()
            mesh, stats = renderer.prepare_layer_mesh(
                geometry,
                cache_key=cache_key,
            )
            elapsed = time.perf_counter_ns() - started
            if mesh is None:
                raise RuntimeError("renderer benchmark が空 mesh を返した")
            if include_semantic_frames:
                if mesh.last_vertices is None or mesh.last_indices is None:
                    raise RuntimeError("renderer benchmark mesh upload state is missing")
                semantic_frames.append((mesh.last_vertices, mesh.last_indices))
            cache_hits += int(cached_before)
            cache_misses += int(not cached_before)
            if frame >= 2:
                steady_samples.append(elapsed)

    if stats is None:
        raise RuntimeError("renderer benchmark の stats が未生成")
    uploads = sum(mesh.upload_count for mesh in _BenchmarkFakeMesh.instances)
    full_vertex_upload_bytes = sum(
        mesh.full_vertex_upload_bytes for mesh in _BenchmarkFakeMesh.instances
    )
    full_index_upload_bytes = sum(
        mesh.full_index_upload_bytes for mesh in _BenchmarkFakeMesh.instances
    )
    vertex_only_upload_bytes = sum(
        mesh.vertex_only_upload_bytes for mesh in _BenchmarkFakeMesh.instances
    )
    steady = _summarize_ns(steady_samples)
    result: dict[str, Any] = {
        "output": {
            **_describe_realized(geometry),
            "frames": frame_count,
            "index_count": stats.draw_vertices + max(0, stats.draw_lines - 1),
            "index_builds": index_builds,
            "uploads": uploads,
            "full_vertex_upload_bytes": full_vertex_upload_bytes,
            "full_index_upload_bytes": full_index_upload_bytes,
            "vertex_only_upload_bytes": vertex_only_upload_bytes,
            "steady_median_ms": steady["median_ms"],
            "steady_p95_ms": steady["p95_ms"],
        },
        "cache": {
            "hits": cache_hits,
            "misses": cache_misses,
            "evictions": 0,
            "entries": len(renderer._mesh_cache),
            "candidate_entries": len(renderer._mesh_candidates),
            "bytes": int(renderer._mesh_cache_bytes),
            "budget_bytes": int(renderer._mesh_cache_max_bytes),
        },
    }
    if include_semantic_frames:
        result["_semantic_frames"] = tuple(semantic_frames)
    return result


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
            **_summarize_ns(samples),
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


__all__: list[str] = []
