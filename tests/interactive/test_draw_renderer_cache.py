from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from grafix.core.realize import GeometryCacheKey
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.runtime_limits import RuntimeLimits
from grafix.interactive.gl import draw_renderer as renderer_module
from grafix.interactive.gl.draw_renderer import DrawRenderer
from grafix.api.render import RenderOptions
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


class _FakeUniform:
    def __init__(self) -> None:
        self.values: list[object] = []
        self.writes: list[bytes] = []

    @property
    def value(self) -> object | None:
        return None if not self.values else self.values[-1]

    @value.setter
    def value(self, value: object) -> None:
        self.values.append(value)

    def write(self, value: bytes) -> None:
        self.writes.append(value)


class _FakeProgram(dict[str, _FakeUniform]):
    def __init__(self, uniforms: dict[str, _FakeUniform]) -> None:
        super().__init__(uniforms)
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeWindow:
    def __init__(self) -> None:
        self.switch_count = 0

    def switch_to(self) -> None:
        self.switch_count += 1


class _FakeDrawContext:
    LINE_STRIP = 3

    def __init__(self) -> None:
        self.viewport = (0, 0, 1, 1)
        self.clear_calls = 0
        self.released = False
        self.finish_count = 0

    def clear(self, *_args: object, **_kwargs: object) -> None:
        self.clear_calls += 1

    def release(self) -> None:
        self.released = True

    def finish(self) -> None:
        self.finish_count += 1


class _FakeVao:
    def __init__(self, name: str, draw_order: list[str]) -> None:
        self._name = name
        self._draw_order = draw_order
        self.calls: list[dict[str, int]] = []

    def render(self, **kwargs: int) -> None:
        self._draw_order.append(self._name)
        self.calls.append(dict(kwargs))


def _draw_renderer() -> tuple[
    DrawRenderer,
    dict[str, _FakeUniform],
]:
    uniforms = {
        "viewport_size": _FakeUniform(),
        "line_width_px": _FakeUniform(),
        "color": _FakeUniform(),
        "projection": _FakeUniform(),
    }
    renderer = _initialized_renderer(uniforms)
    renderer.viewport(800, 800)
    for uniform in uniforms.values():
        uniform.values.clear()
    return renderer, uniforms


def _draw_mesh(name: str, draw_order: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        vao=_FakeVao(name, draw_order),
        index_count=6,
    )


def _renderer() -> DrawRenderer:
    return _initialized_renderer(
        {
            "viewport_size": _FakeUniform(),
            "line_width_px": _FakeUniform(),
            "color": _FakeUniform(),
            "projection": _FakeUniform(),
        }
    )


def _initialized_renderer(
    uniforms: dict[str, _FakeUniform],
) -> DrawRenderer:
    context = _FakeDrawContext()
    program = _FakeProgram(uniforms)
    with (
        patch.object(
            renderer_module.moderngl,
            "create_context",
            return_value=context,
        ),
        patch.object(
            renderer_module.Shader,
            "create_shader",
            return_value=program,
        ),
        patch.object(renderer_module, "LineMesh", _FakeMesh),
    ):
        return DrawRenderer(
            _FakeWindow(),
            RenderOptions(canvas_size=(800, 800)),
        )


def test_renderer_skips_same_style_uniform_writes_across_layers_and_frames() -> None:
    renderer, uniforms = _draw_renderer()
    draw_order: list[str] = []
    first = _draw_mesh("first", draw_order)
    second = _draw_mesh("second", draw_order)
    third = _draw_mesh("third", draw_order)
    style = {"color": (0.2, 0.3, 0.4), "thickness": 0.01}

    renderer.draw_prepared_mesh(first, **style)
    renderer.draw_prepared_mesh(second, **style)
    renderer.clear((1.0, 1.0, 1.0))
    renderer.draw_prepared_mesh(third, **style)

    assert uniforms["line_width_px"].values == [4.0]
    assert uniforms["color"].values == [(0.2, 0.3, 0.4, 1.0)]
    assert draw_order == ["first", "second", "third"]
    for mesh in (first, second, third):
        assert mesh.vao.calls == [{"mode": 3, "vertices": 6}]


def test_renderer_alternating_styles_keep_required_uniform_writes_and_order() -> None:
    renderer, uniforms = _draw_renderer()
    draw_order: list[str] = []
    mesh = _draw_mesh("mesh", draw_order)
    styles = (
        {"color": (0.2, 0.3, 0.4), "thickness": 0.01},
        {"color": (0.8, 0.1, 0.6), "thickness": 0.025},
        {"color": (0.2, 0.3, 0.4), "thickness": 0.01},
    )

    for style in styles:
        renderer.draw_prepared_mesh(mesh, **style)

    assert uniforms["line_width_px"].values == [4.0, 10.0, 4.0]
    assert uniforms["color"].values == [
        (0.2, 0.3, 0.4, 1.0),
        (0.8, 0.1, 0.6, 1.0),
        (0.2, 0.3, 0.4, 1.0),
    ]
    assert draw_order == ["mesh", "mesh", "mesh"]


def test_renderer_viewport_change_invalidates_draw_style_uniforms() -> None:
    renderer, uniforms = _draw_renderer()
    mesh = _draw_mesh("mesh", [])
    style = {"color": (0.2, 0.3, 0.4), "thickness": 0.01}

    renderer.draw_prepared_mesh(mesh, **style)
    renderer.viewport(400, 400)
    renderer.draw_prepared_mesh(mesh, **style)

    assert uniforms["viewport_size"].values == [(400.0, 400.0)]
    assert uniforms["line_width_px"].values == [4.0, 2.0]
    assert uniforms["color"].values == [
        (0.2, 0.3, 0.4, 1.0),
        (0.2, 0.3, 0.4, 1.0),
    ]


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
    first_mesh, first_stats = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=1,
        snapshot_revision=1,
    )
    second_mesh, second_stats = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=2,
        snapshot_revision=1,
    )
    third_mesh, third_stats = renderer.prepare_layer_mesh(
        geometry,
        cache_key=cache_key,
        scene_serial=2,
        snapshot_revision=1,
    )

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
    renderer.prepare_layer_mesh(
        geometry,
        cache_key=first_key,
        scene_serial=1,
        snapshot_revision=1,
    )
    first_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=first_key,
        scene_serial=2,
        snapshot_revision=1,
    )
    renderer.prepare_layer_mesh(
        geometry,
        cache_key=second_key,
        scene_serial=3,
        snapshot_revision=1,
    )
    second_mesh, _ = renderer.prepare_layer_mesh(
        geometry,
        cache_key=second_key,
        scene_serial=4,
        snapshot_revision=1,
    )

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

    renderer.prepare_layer_mesh(
        geometry,
        cache_key=old_key,
        scene_serial=1,
        snapshot_revision=1,
    )
    renderer.prepare_layer_mesh(
        geometry,
        cache_key=new_key,
        scene_serial=2,
        snapshot_revision=2,
    )

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
        scene_serial=1,
        snapshot_revision=1,
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
            scene_serial=frame + 1,
            snapshot_revision=frame,
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
            scene_serial=frame + 1,
            snapshot_revision=frame,
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
                scene_serial=frame + 1,
                snapshot_revision=frame,
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
            scene_serial=1,
            snapshot_revision=1,
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
        scene_serial=1,
        snapshot_revision=1,
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
        scene_serial=2,
        snapshot_revision=1,
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
            scene_serial=1,
            snapshot_revision=1,
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

    for scene_serial, key in enumerate(keys, start=1):
        renderer.prepare_layer_mesh(
            _geometry(offsets=offsets),
            cache_key=key,
            scene_serial=scene_serial,
            snapshot_revision=1,
        )

    assert list(renderer._mesh_candidates) == keys[-2:]
    assert [
        admission.scene_serial
        for admission in renderer._mesh_candidates.values()
    ] == [3, 4]


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
        scene_serial=1,
        snapshot_revision=1,
    )
    second_mesh, second_stats = renderer.prepare_layer_mesh(
        geometry,
        cache_key=_cache_key("empty-2"),
        scene_serial=2,
        snapshot_revision=1,
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
        scene_serial=1,
        snapshot_revision=1,
    )

    renderer.release()

    assert renderer._scratch_topology is None
    assert renderer._scratch_mesh.released is True
    assert not renderer._mesh_candidates
    assert not renderer._dynamic_meshes
