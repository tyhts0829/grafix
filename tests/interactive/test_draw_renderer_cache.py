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
    renderer._dynamic_meshes = OrderedDict()
    renderer._mesh_cache_bytes = 0
    renderer._dynamic_mesh_bytes = 0
    renderer._dynamic_slot_count = 0
    renderer._mesh_upload_count = 0
    renderer._mesh_cache_max_bytes = 192 * 1024 * 1024
    renderer._mesh_cache_max_entries = 4_096
    renderer._mesh_candidates_max_entries = 4_096
    renderer._dynamic_mesh_max_bytes = 64 * 1024 * 1024
    renderer._dynamic_mesh_max_entries = 256
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

    assert renderer.mesh_cache_max_bytes == 9_000
    assert renderer._dynamic_mesh_max_bytes == 3_000
    assert (
        renderer.mesh_cache_max_bytes + renderer._dynamic_mesh_max_bytes
        == 12_000
    )
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


def test_renderer_reuses_topology_for_multiple_animated_layer_slots(
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
    offsets_by_layer = [
        np.asarray([0, 3], dtype=np.int32)
        for _ in range(8)
    ]

    for frame in range(120):
        for layer_index, offsets in enumerate(offsets_by_layer):
            mesh, _ = renderer.prepare_layer_mesh(
                _geometry(offsets=offsets, shift=float(frame)),
                cache_key=_cache_key(f"animated-{frame}-{layer_index}"),
                dynamic_slot=layer_index,
            )
            assert mesh is renderer._dynamic_meshes[layer_index].mesh

    assert build_count == 8
    assert len(renderer._dynamic_meshes) == 8
    assert sum(
        entry.mesh.index_upload_count
        for entry in renderer._dynamic_meshes.values()
    ) == 8
    assert sum(
        entry.mesh.vertices_only_upload_count
        for entry in renderer._dynamic_meshes.values()
    ) == 8 * 119


def test_renderer_dynamic_mesh_pool_is_entry_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    renderer._dynamic_mesh_max_entries = 2

    for layer_index in range(4):
        renderer.prepare_layer_mesh(
            _geometry(),
            cache_key=_cache_key(f"dynamic-{layer_index}"),
            dynamic_slot=layer_index,
        )

    assert list(renderer._dynamic_meshes) == [2, 3]
    assert all(mesh.released for mesh in _FakeMesh.instances[1:3])


def test_renderer_empty_geometry_releases_its_dynamic_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    mesh, _ = renderer.prepare_layer_mesh(
        _geometry(),
        cache_key=_cache_key("non-empty"),
        dynamic_slot=0,
    )
    assert 0 in renderer._dynamic_meshes

    empty = RealizedGeometry(
        coords=np.empty((0, 3), dtype=np.float32),
        offsets=np.asarray([0], dtype=np.int32),
    )
    empty_mesh, _ = renderer.prepare_layer_mesh(
        empty,
        cache_key=_cache_key("empty"),
        dynamic_slot=0,
    )

    assert empty_mesh is None
    assert 0 not in renderer._dynamic_meshes
    assert renderer._dynamic_mesh_bytes == 0
    assert mesh is not None and mesh.released is True


def test_renderer_prunes_trailing_dynamic_slots_when_layer_count_shrinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    meshes = []
    for slot in range(3):
        mesh, _ = renderer.prepare_layer_mesh(
            _geometry(shift=float(slot)),
            cache_key=_cache_key(f"slot-{slot}"),
            dynamic_slot=slot,
        )
        meshes.append(mesh)
    renderer.finish_dynamic_frame(3)

    renderer.finish_dynamic_frame(1)

    assert list(renderer._dynamic_meshes) == [0]
    assert meshes[1] is not None and meshes[1].released is True
    assert meshes[2] is not None and meshes[2].released is True


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


def test_renderer_stale_result_redisplay_does_not_promote_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    cache_key = _cache_key("held-mp-result")

    first_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
    )
    stale_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
    )

    assert first_mesh is stale_mesh is renderer._scratch_mesh
    assert not renderer._mesh_cache
    assert cache_key in renderer._mesh_candidates

    stable_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=2,
        snapshot_revision=10,
    )

    assert stable_mesh is not None
    assert stable_mesh is not renderer._scratch_mesh
    assert list(renderer._mesh_cache) == [cache_key]


def test_renderer_stale_dynamic_result_skips_duplicate_vbo_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    cache_key = _cache_key("held-dynamic-result")

    mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=0,
    )
    uploads_after_first = renderer.mesh_upload_count
    stale_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=0,
    )

    assert stale_mesh is mesh
    assert renderer.mesh_upload_count == uploads_after_first
    assert mesh is not None and mesh.vertex_upload_count == 1


def test_renderer_releases_dynamic_slot_after_static_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    cache_key = _cache_key("dynamic-to-static")

    dynamic_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=0,
    )
    assert dynamic_mesh is not None
    assert renderer._dynamic_mesh_bytes > 0

    static_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=2,
        snapshot_revision=10,
        dynamic_slot=0,
    )

    assert static_mesh is renderer._mesh_cache[cache_key].mesh
    assert 0 not in renderer._dynamic_meshes
    assert renderer._dynamic_mesh_bytes == 0
    assert dynamic_mesh.released is True
    assert renderer.mesh_upload_count == 2


def test_renderer_static_promotion_releases_every_duplicate_dynamic_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    cache_key = _cache_key("shared-dynamic-to-static")

    first_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=0,
    )
    second_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=1,
    )
    assert set(renderer._dynamic_meshes) == {0, 1}

    static_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=2,
        snapshot_revision=10,
        dynamic_slot=0,
    )

    assert static_mesh is renderer._mesh_cache[cache_key].mesh
    assert renderer._dynamic_meshes == {}
    assert renderer._dynamic_mesh_bytes == 0
    assert first_mesh is not None and first_mesh.released is True
    assert second_mesh is not None and second_mesh.released is True


def test_renderer_same_arrays_update_dynamic_cache_key_before_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    first_key = _cache_key("same-arrays-a")
    second_key = _cache_key("same-arrays-b")

    dynamic_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=first_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=0,
    )
    same_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=second_key,
        scene_serial=1,
        snapshot_revision=10,
        dynamic_slot=0,
    )
    assert same_mesh is dynamic_mesh
    assert renderer._dynamic_meshes[0].cache_key == second_key

    static_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=second_key,
        scene_serial=2,
        snapshot_revision=10,
        dynamic_slot=0,
    )

    assert static_mesh is renderer._mesh_cache[second_key].mesh
    assert renderer._dynamic_meshes == {}
    assert dynamic_mesh is not None and dynamic_mesh.released is True


def test_renderer_revisited_transient_revision_waits_for_stability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeMesh.instances.clear()
    monkeypatch.setattr(renderer_module, "LineMesh", _FakeMesh)
    renderer = _renderer()
    geometry = _geometry()
    cache_key = _cache_key("forward-reverse")

    renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=20,
    )
    revisited_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=2,
        snapshot_revision=21,
    )

    assert revisited_mesh is renderer._scratch_mesh
    assert not renderer._mesh_cache

    stable_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=3,
        snapshot_revision=21,
    )

    assert stable_mesh is not None
    assert stable_mesh is not renderer._scratch_mesh
    assert list(renderer._mesh_cache) == [cache_key]


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
    assert not renderer._dynamic_meshes
