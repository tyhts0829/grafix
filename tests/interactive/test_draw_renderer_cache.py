from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pytest

from grafix.core.realize import GeometryCacheKey
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.runtime_limits import RuntimeLimits
from grafix.interactive.gl import draw_renderer as renderer_module
from grafix.interactive.gl.draw_renderer import DrawRenderer
from grafix.interactive.runtime.diagnostics import DiagnosticCenter


class _FakeMesh:
    instances: list["_FakeMesh"] = []

    def __init__(self, ctx: object, program: object, initial_reserve: int = 4096) -> None:
        del ctx, program
        self.vbo = SimpleNamespace(size=int(initial_reserve))
        self.ibo = SimpleNamespace(size=int(initial_reserve))
        self.upload_count = 0
        self.vertices_only_upload_count = 0
        self.vertex_upload_count = 0
        self.index_upload_count = 0
        self.released = False
        _FakeMesh.instances.append(self)

    def upload(self, vertices: np.ndarray, indices: np.ndarray) -> None:
        assert vertices.dtype == np.float32
        assert indices.dtype == np.uint32
        self.upload_count += 1
        self.vertex_upload_count += 1
        self.index_upload_count += 1

    def upload_vertices(self, vertices: np.ndarray) -> None:
        assert vertices.dtype == np.float32
        self.vertices_only_upload_count += 1
        self.vertex_upload_count += 1

    def release(self) -> None:
        self.released = True


def _renderer() -> DrawRenderer:
    renderer = DrawRenderer.__new__(DrawRenderer)
    renderer.ctx = SimpleNamespace(release=lambda: None)
    renderer.program = SimpleNamespace(release=lambda: None)
    renderer._scratch_mesh = _FakeMesh(renderer.ctx, renderer.program)
    renderer._scratch_topology = None
    renderer._mesh_cache = OrderedDict()
    renderer._mesh_candidates = OrderedDict()
    renderer._mesh_cache_bytes = 0
    renderer._mesh_cache_max_bytes = 256 * 1024 * 1024
    renderer._mesh_candidates_max_entries = 4_096
    return renderer


def _geometry(
    *,
    offsets: np.ndarray | None = None,
    shift: float = 0.0,
) -> RealizedGeometry:
    if offsets is None:
        offsets = np.asarray([0, 3], dtype=np.int32)
    return RealizedGeometry(
        coords=np.asarray(
            [[shift, 0, 0], [shift + 1, 0, 0], [shift + 2, 0, 0]],
            dtype=np.float32,
        ),
        offsets=offsets,
    )


def _cache_key(geometry_id: str, revision: int = 1) -> GeometryCacheKey:
    return geometry_id, (revision, revision)


def test_renderer_cache_builds_indices_once_and_uploads_static_mesh_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    original_build = renderer_module.build_line_indices_and_stats
    build_count = 0

    def counted_build(offsets: np.ndarray):
        nonlocal build_count
        build_count += 1
        return original_build(offsets)

    monkeypatch.setattr(renderer_module, "build_line_indices_and_stats", counted_build)
    renderer = _renderer()
    geometry = _geometry()

    cache_key = _cache_key("static")
    first_mesh, first_stats = renderer.prepare_layer_mesh(geometry, cache_key=cache_key)
    second_mesh, second_stats = renderer.prepare_layer_mesh(geometry, cache_key=cache_key)
    third_mesh, third_stats = renderer.prepare_layer_mesh(geometry, cache_key=cache_key)

    assert first_mesh is renderer._scratch_mesh
    assert second_mesh is third_mesh
    assert second_mesh is not renderer._scratch_mesh
    assert renderer._scratch_mesh.upload_count == 1
    assert second_mesh is not None
    assert second_mesh.upload_count == 1
    assert build_count == 1
    assert first_stats == second_stats == third_stats
    assert renderer._mesh_cache_bytes == second_mesh.vbo.size + second_mesh.ibo.size
    assert not hasattr(renderer._mesh_cache[cache_key], "indices")


def test_renderer_mesh_cache_evicts_lru_entry_by_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    renderer._mesh_cache_max_bytes = 9_000
    geometry = _geometry()

    first_key = _cache_key("first")
    second_key = _cache_key("second")
    renderer.prepare_layer_mesh(geometry, cache_key=first_key)
    first_mesh, _ = renderer.prepare_layer_mesh(geometry, cache_key=first_key)
    renderer.prepare_layer_mesh(geometry, cache_key=second_key)
    second_mesh, _ = renderer.prepare_layer_mesh(geometry, cache_key=second_key)

    assert list(renderer._mesh_cache) == [second_key]
    assert first_mesh is not None and first_mesh.released is True
    assert second_mesh is not None and second_mesh.released is False
    assert renderer._mesh_cache_bytes <= renderer._mesh_cache_max_bytes


def test_renderer_cache_separates_registry_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    old_key = _cache_key("same-geometry", revision=1)
    new_key = _cache_key("same-geometry", revision=2)

    renderer.prepare_layer_mesh(geometry, cache_key=old_key)
    renderer.prepare_layer_mesh(geometry, cache_key=new_key)

    assert list(renderer._mesh_candidates) == [old_key, new_key]


def test_renderer_applies_gpu_cache_runtime_limit() -> None:
    renderer = _renderer()

    renderer.apply_runtime_limits(RuntimeLimits(gpu_cache_bytes=12_000))

    assert renderer.mesh_cache_max_bytes == 12_000
    assert renderer.mesh_candidate_cache_max_entries == 11


def test_renderer_publishes_gpu_cache_limit_to_common_center() -> None:
    renderer = _renderer()
    center = DiagnosticCenter()
    renderer._diagnostic_center = center
    renderer.apply_runtime_limits(RuntimeLimits(gpu_cache_bytes=0))

    renderer.prepare_layer_mesh(
        _geometry(),
        cache_key=_cache_key("gpu-limit"),
    )

    event = center.snapshot()[0]
    assert event.category == "resource"
    assert event.summary.startswith("GPU cache limit reached")


def test_renderer_reuses_scratch_topology_for_animated_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    original_build = renderer_module.build_line_indices_and_stats
    build_count = 0

    def counted_build(offsets: np.ndarray):
        nonlocal build_count
        build_count += 1
        return original_build(offsets)

    monkeypatch.setattr(renderer_module, "build_line_indices_and_stats", counted_build)
    renderer = _renderer()
    offsets = np.asarray([0, 3], dtype=np.int32)

    for frame in range(3):
        mesh, _ = renderer.prepare_layer_mesh(
            _geometry(offsets=offsets, shift=float(frame)),
            cache_key=_cache_key(f"animated-{frame}"),
        )
        assert mesh is renderer._scratch_mesh

    assert renderer._scratch_topology is not None
    assert renderer._scratch_topology.offsets is offsets
    assert build_count == 1
    assert renderer._scratch_mesh.vertex_upload_count == 3
    assert renderer._scratch_mesh.index_upload_count == 1
    assert renderer._scratch_mesh.vertices_only_upload_count == 2


def test_renderer_rebuilds_scratch_topology_for_new_offsets_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    original_build = renderer_module.build_line_indices_and_stats
    build_count = 0

    def counted_build(offsets: np.ndarray):
        nonlocal build_count
        build_count += 1
        return original_build(offsets)

    monkeypatch.setattr(renderer_module, "build_line_indices_and_stats", counted_build)
    renderer = _renderer()

    for frame in range(2):
        renderer.prepare_layer_mesh(
            _geometry(offsets=np.asarray([0, 3], dtype=np.int32)),
            cache_key=_cache_key(f"topology-{frame}"),
        )

    assert build_count == 2
    assert renderer._scratch_mesh.vertex_upload_count == 2
    assert renderer._scratch_mesh.index_upload_count == 2


def test_renderer_candidate_cache_is_key_only_and_count_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    renderer._mesh_candidates_max_entries = 2
    offsets = np.asarray([0, 3], dtype=np.int32)
    keys = [_cache_key(f"candidate-{index}") for index in range(4)]

    for key in keys:
        renderer.prepare_layer_mesh(_geometry(offsets=offsets), cache_key=key)

    assert list(renderer._mesh_candidates) == keys[-2:]
    assert list(renderer._mesh_candidates.values()) == [None, None]


def test_renderer_reuses_empty_scratch_topology_without_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    original_build = renderer_module.build_line_indices_and_stats
    build_count = 0

    def counted_build(offsets: np.ndarray):
        nonlocal build_count
        build_count += 1
        return original_build(offsets)

    monkeypatch.setattr(renderer_module, "build_line_indices_and_stats", counted_build)
    renderer = _renderer()
    offsets = np.asarray([0], dtype=np.int32)
    geometry = RealizedGeometry(
        coords=np.empty((0, 3), dtype=np.float32),
        offsets=offsets,
    )

    first_mesh, first_stats = renderer.prepare_layer_mesh(
        geometry,
        cache_key=_cache_key("empty-1"),
    )
    second_mesh, second_stats = renderer.prepare_layer_mesh(
        geometry,
        cache_key=_cache_key("empty-2"),
    )

    assert first_mesh is second_mesh is None
    assert first_stats == second_stats
    assert build_count == 1
    assert renderer._scratch_mesh.vertex_upload_count == 0
    assert renderer._scratch_mesh.index_upload_count == 0


def test_renderer_release_drops_scratch_topology_reference() -> None:
    renderer = _renderer()
    offsets = np.asarray([0, 3], dtype=np.int32)
    renderer.prepare_layer_mesh(
        _geometry(offsets=offsets),
        cache_key=_cache_key("release"),
    )

    renderer.release()

    assert renderer._scratch_topology is None
    assert renderer._scratch_mesh.released is True
    assert not renderer._mesh_candidates
