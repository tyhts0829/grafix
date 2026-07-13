from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pytest

from grafix.core.realize import GeometryCacheKey
from grafix.core.realized_geometry import RealizedGeometry
from grafix.interactive.gl import draw_renderer as renderer_module
from grafix.interactive.gl.draw_renderer import DrawRenderer


class _FakeMesh:
    instances: list["_FakeMesh"] = []

    def __init__(self, ctx: object, program: object, initial_reserve: int = 4096) -> None:
        del ctx, program
        self.vbo = SimpleNamespace(size=int(initial_reserve))
        self.ibo = SimpleNamespace(size=int(initial_reserve))
        self.upload_count = 0
        self.released = False
        _FakeMesh.instances.append(self)

    def upload(self, vertices: np.ndarray, indices: np.ndarray) -> None:
        assert vertices.dtype == np.float32
        assert indices.dtype == np.uint32
        self.upload_count += 1

    def release(self) -> None:
        self.released = True


def _renderer() -> DrawRenderer:
    renderer = DrawRenderer.__new__(DrawRenderer)
    renderer.ctx = object()
    renderer.program = object()
    renderer._scratch_mesh = _FakeMesh(renderer.ctx, renderer.program)
    renderer._mesh_cache = OrderedDict()
    renderer._mesh_candidates = OrderedDict()
    renderer._mesh_cache_bytes = 0
    renderer._mesh_candidates_bytes = 0
    renderer._mesh_cache_max_bytes = 256 * 1024 * 1024
    renderer._mesh_candidates_max_bytes = 64 * 1024 * 1024
    return renderer


def _geometry() -> RealizedGeometry:
    return RealizedGeometry(
        coords=np.asarray([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=np.float32),
        offsets=np.asarray([0, 3], dtype=np.int32),
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
