"""subdivide effect の線細分化に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.effects import subdivide as subdivide_module
from grafix.core.effects.subdivide import subdivide as subdivide_impl
from grafix.core.operation_diagnostics import operation_diagnostic_context
from grafix.core.operation_authoring import primitive
from grafix.core.realize import RealizeError, realize
from grafix.core.realized_geometry import GeomTuple, RealizedGeometry


@primitive
def subdivide_test_line_0_10() -> GeomTuple:
    """x 軸上の 2 点ポリライン（長さ 10）を返す。"""
    coords = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def subdivide_test_short_segment() -> GeomTuple:
    """最短セグメント長ガード確認用の極短 2 点ポリラインを返す。"""
    coords = np.array([[0.0, 0.0, 0.0], [0.005, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def subdivide_test_two_lines() -> GeomTuple:
    """2 本の独立ポリライン（長さ 10 と 2）を返す。"""
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, 2, 4], dtype=np.int32)
    return coords, offsets


@primitive
def subdivide_test_float32_stop_boundary() -> GeomTuple:
    """事前見積もりと実生成の停止段数がずれる float32 境界線を返す。"""
    endpoint = np.nextafter(np.float32(0.32), np.float32(np.inf))
    coords = np.array(
        [[0.0, 0.0, 0.0], [endpoint, 0.0, 0.0]],
        dtype=np.float32,
    )
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def subdivide_test_float32_boundary_with_trailing_line() -> GeomTuple:
    """float32 境界線と、通常どおり細分される後続線を返す。"""
    endpoint = np.nextafter(np.float32(0.32), np.float32(np.inf))
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [endpoint, 0.0, 0.0],
            [0.0, 7.0, 0.0],
            [10.0, 7.0, 0.0],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, 2, 4], dtype=np.int32)
    return coords, offsets


@primitive
def subdivide_test_empty() -> GeomTuple:
    """空ジオメトリを返す。"""
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


def _iter_polylines(realized: RealizedGeometry):
    offsets = realized.offsets
    for i in range(len(offsets) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        yield realized.coords[s:e]


def _reference_effective_levels(vertices: np.ndarray, subdivisions: int) -> int:
    """高速化前と同じ解析式で、polyline の capacity 用反復数を返す。"""

    if len(vertices) < 2:
        return 0
    delta = vertices[1:] - vertices[:-1]
    distance_sq = np.einsum("ij,ij->i", delta, delta)
    min_distance_sq = float(np.min(distance_sq))
    if min_distance_sq < subdivide_module.MIN_SEG_LEN_SQ:
        return 0

    applied_levels = 0
    for _ in range(subdivisions):
        applied_levels += 1
        min_distance_sq *= 0.25
        if min_distance_sq < subdivide_module.MIN_SEG_LEN_SQ:
            break
    return applied_levels


def _reference_subdivide_line(
    vertices: np.ndarray,
    subdivisions: int,
    capacity: int,
) -> np.ndarray:
    """高速化前と同じ level-by-level midpoint 実装をテスト内に固定する。"""

    if len(vertices) < 2:
        return vertices
    delta = vertices[1:] - vertices[:-1]
    distance_sq = np.einsum("ij,ij->i", delta, delta)
    if float(np.min(distance_sq)) < subdivide_module.MIN_SEG_LEN_SQ:
        return vertices

    result = vertices.copy()
    for _ in range(subdivisions):
        new_count = 2 * len(result) - 1
        if capacity > 0 and new_count > capacity:
            break
        expanded = np.empty((new_count, result.shape[1]), dtype=result.dtype)
        expanded[::2] = result
        expanded[1::2] = (result[:-1] + result[1:]) / 2
        result = expanded

        delta = result[1:] - result[:-1]
        distance_sq = np.einsum("ij,ij->i", delta, delta)
        if float(np.min(distance_sq)) < subdivide_module.MIN_SEG_LEN_SQ:
            break
    return result


def _reference_subdivide(
    coords: np.ndarray,
    offsets: np.ndarray,
    *,
    subdivisions: int,
    max_total_vertices: int,
) -> GeomTuple:
    """高速化前の count・cap・生成順を再現する differential oracle。"""

    selected_divisions = subdivisions
    counts: list[int] = []
    while selected_divisions > 0:
        counts = []
        for line_index in range(len(offsets) - 1):
            start = int(offsets[line_index])
            end = int(offsets[line_index + 1])
            count = end - start
            levels = _reference_effective_levels(
                coords[start:end],
                selected_divisions,
            )
            for _ in range(levels):
                count = 2 * count - 1
            counts.append(count)
        if sum(counts) <= max_total_vertices:
            break
        selected_divisions -= 1

    if selected_divisions <= 0 or sum(counts) == len(coords):
        return coords, offsets

    coords_out = np.empty((sum(counts), 3), dtype=np.float32)
    offsets_out = np.empty((len(offsets),), dtype=np.int32)
    offsets_out[0] = 0
    write_at = 0
    for line_index, capacity in enumerate(counts):
        start = int(offsets[line_index])
        end = int(offsets[line_index + 1])
        line = _reference_subdivide_line(
            coords[start:end],
            selected_divisions,
            capacity,
        )
        next_at = write_at + len(line)
        coords_out[write_at:next_at] = line
        offsets_out[line_index + 1] = next_at
        write_at = next_at

    if write_at < len(coords_out):
        coords_out = coords_out[:write_at].copy()
    return coords_out, offsets_out


def test_subdivide_inserts_midpoint() -> None:
    g = G.subdivide_test_line_0_10()
    realized = realize(E.subdivide(subdivisions=1)(g))

    polylines = list(_iter_polylines(realized))
    assert len(polylines) == 1
    line = polylines[0]
    assert line.shape == (3, 3)
    np.testing.assert_allclose(line[:, 0], [0.0, 5.0, 10.0], rtol=0.0, atol=1e-6)


def test_subdivide_two_iterations_increases_vertex_count() -> None:
    g = G.subdivide_test_line_0_10()
    realized = realize(E.subdivide(subdivisions=2)(g))

    polylines = list(_iter_polylines(realized))
    assert len(polylines) == 1
    line = polylines[0]
    assert line.shape == (5, 3)
    np.testing.assert_allclose(line[:, 0], [0.0, 2.5, 5.0, 7.5, 10.0], rtol=0.0, atol=1e-6)


def test_subdivide_default_is_noop() -> None:
    g = G.subdivide_test_line_0_10()
    base = realize(g)
    realized = realize(E.subdivide()(g))

    np.testing.assert_allclose(realized.coords, base.coords, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == base.offsets.tolist()


def test_subdivide_short_segment_guard_is_noop() -> None:
    g = G.subdivide_test_short_segment()
    base = realize(g)
    realized = realize(E.subdivide(subdivisions=10)(g))

    np.testing.assert_allclose(realized.coords, base.coords, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == base.offsets.tolist()


def test_subdivide_multiple_polylines_preserves_offsets() -> None:
    g = G.subdivide_test_two_lines()
    realized = realize(E.subdivide(subdivisions=1)(g))

    polylines = list(_iter_polylines(realized))
    assert len(polylines) == 2
    assert realized.offsets.tolist() == [0, 3, 6]
    np.testing.assert_allclose(polylines[0][:, 0], [0.0, 5.0, 10.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(polylines[1][:, 0], [0.0, 1.0, 2.0], rtol=0.0, atol=1e-6)


def test_subdivide_float32_stop_boundary_uses_actual_vertex_count() -> None:
    realized = realize(
        E.subdivide(subdivisions=10)(G.subdivide_test_float32_stop_boundary())
    )

    assert realized.coords.shape == (33, 3)
    assert realized.offsets.tolist() == [0, 33]
    np.testing.assert_array_equal(
        realized.coords[[0, -1]],
        np.array(
            [
                [0.0, 0.0, 0.0],
                [
                    np.nextafter(np.float32(0.32), np.float32(np.inf)),
                    0.0,
                    0.0,
                ],
            ],
            dtype=np.float32,
        ),
    )


def test_subdivide_handles_translated_polyhedron_fill_chain() -> None:
    geometry = E.fill()(
        G.polyhedron(
            center=(255.8, 0.0, 0.0),
            scale=1.0,
        )
    )
    realized = realize(E.subdivide(subdivisions=6)(geometry))

    assert realized.coords.shape[0] > 0
    assert int(realized.offsets[-1]) == len(realized.coords)
    assert np.all(realized.offsets[1:] >= realized.offsets[:-1])


def test_subdivide_float32_stop_boundary_preserves_trailing_polyline() -> None:
    realized = realize(
        E.subdivide(subdivisions=6)(
            G.subdivide_test_float32_boundary_with_trailing_line()
        )
    )

    polylines = list(_iter_polylines(realized))
    assert len(polylines) == 2
    assert realized.offsets.tolist() == [0, 33, 98]
    assert int(realized.offsets[-1]) == len(realized.coords)
    assert polylines[1].shape == (65, 3)
    np.testing.assert_array_equal(
        polylines[1][[0, -1]],
        np.array(
            [[0.0, 7.0, 0.0], [10.0, 7.0, 0.0]],
            dtype=np.float32,
        ),
    )


def test_subdivide_float32_stop_boundary_reports_all_actual_levels() -> None:
    base = realize(G.subdivide_test_float32_boundary_with_trailing_line())

    with operation_diagnostic_context() as buffer:
        coords, offsets = subdivide_impl(
            (base.coords, base.offsets),
            subdivisions=6,
        )

    assert coords.shape == (98, 3)
    assert offsets.tolist() == [0, 33, 98]
    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.original_value == 6
    assert diagnostic.effective_value == (5, 6)
    assert (
        diagnostic.reason
        == "minimum segment length stopped one or more polylines early"
    )


def test_subdivide_empty_geometry_is_noop() -> None:
    g = G.subdivide_test_empty()
    realized = realize(E.subdivide(subdivisions=1)(g))

    assert realized.coords.shape == (0, 3)
    assert realized.offsets.tolist() == [0]


def test_subdivide_rejects_negative_subdivisions_before_empty_input() -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(E.subdivide(subdivisions=-1)(G.subdivide_test_empty()))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "subdivisions" in str(exc_info.value.__cause__)


def test_subdivide_vertex_cap_never_drops_trailing_polylines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = realize(G.subdivide_test_two_lines())
    monkeypatch.setattr(subdivide_module, "MAX_TOTAL_VERTICES", 3)

    out_coords, out_offsets = subdivide_impl(
        (base.coords, base.offsets),
        subdivisions=1,
    )

    assert out_coords is base.coords
    assert out_offsets is base.offsets
    assert out_offsets.tolist() == [0, 2, 4]


def test_subdivide_lowers_divisions_uniformly_to_fit_vertex_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = realize(G.subdivide_test_two_lines())
    monkeypatch.setattr(subdivide_module, "MAX_TOTAL_VERTICES", 5)

    out_coords, out_offsets = subdivide_impl(
        (base.coords, base.offsets),
        subdivisions=1,
    )

    assert out_coords is base.coords
    assert out_offsets is base.offsets
    assert out_offsets.tolist() == [0, 2, 4]


@pytest.mark.parametrize(
    ("vertex_cap", "expected_offsets", "expected_reason"),
    [
        (9, [0, 3, 6], "subdivisions was reduced to satisfy MAX_TOTAL_VERTICES"),
        (10, [0, 5, 10], None),
        (11, [0, 5, 10], None),
    ],
)
def test_subdivide_vertex_cap_before_exact_and_after_are_exact(
    monkeypatch: pytest.MonkeyPatch,
    vertex_cap: int,
    expected_offsets: list[int],
    expected_reason: str | None,
) -> None:
    base = realize(G.subdivide_test_two_lines())
    monkeypatch.setattr(subdivide_module, "MAX_TOTAL_VERTICES", vertex_cap)
    expected_coords, expected_offsets_array = _reference_subdivide(
        base.coords,
        base.offsets,
        subdivisions=2,
        max_total_vertices=vertex_cap,
    )

    with operation_diagnostic_context() as buffer:
        out_coords, out_offsets = subdivide_impl(
            (base.coords, base.offsets),
            subdivisions=2,
        )

    np.testing.assert_array_equal(out_coords, expected_coords)
    np.testing.assert_array_equal(out_offsets, expected_offsets_array)
    assert out_offsets.tolist() == expected_offsets
    diagnostics = buffer.snapshot()
    if expected_reason is None:
        assert diagnostics == ()
    else:
        assert len(diagnostics) == 1
        assert diagnostics[0].original_value == 2
        assert diagnostics[0].effective_value == 1
        assert diagnostics[0].reason == expected_reason


def test_subdivide_clamp_and_vertex_cap_diagnostic_payload_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = realize(G.subdivide_test_two_lines())
    monkeypatch.setattr(subdivide_module, "MAX_TOTAL_VERTICES", 9)
    requested = subdivide_module.MAX_SUBDIVISIONS + 4

    with operation_diagnostic_context() as buffer:
        out_coords, out_offsets = subdivide_impl(
            (base.coords, base.offsets),
            subdivisions=requested,
        )

    assert out_coords.shape == (6, 3)
    assert out_offsets.tolist() == [0, 3, 6]
    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.original_value == requested
    assert diagnostic.effective_value == 1
    assert diagnostic.reason == (
        f"subdivisions was clamped to MAX_SUBDIVISIONS="
        f"{subdivide_module.MAX_SUBDIVISIONS}; "
        "subdivisions was reduced to satisfy MAX_TOTAL_VERTICES"
    )
    assert diagnostic.severity == "warning"


@pytest.mark.parametrize(
    "endpoint",
    [
        np.nextafter(np.float32(0.01), np.float32(-np.inf)),
        np.float32(0.01),
        np.nextafter(np.float32(0.01), np.float32(np.inf)),
        np.nextafter(np.float32(0.32), np.float32(-np.inf)),
        np.float32(0.32),
        np.nextafter(np.float32(0.32), np.float32(np.inf)),
    ],
)
def test_subdivide_nextafter_boundaries_match_level_reference(
    endpoint: np.float32,
) -> None:
    coords = np.array([[0.0, 0.0, 0.0], [endpoint, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    expected_coords, expected_offsets = _reference_subdivide(
        coords,
        offsets,
        subdivisions=10,
        max_total_vertices=subdivide_module.MAX_TOTAL_VERTICES,
    )

    out_coords, out_offsets = subdivide_impl(
        (coords, offsets),
        subdivisions=10,
    )

    np.testing.assert_array_equal(out_coords, expected_coords)
    np.testing.assert_array_equal(out_offsets, expected_offsets)


def test_subdivide_fixed_randomized_inputs_match_level_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(20260719)
    segment_scales = np.array(
        [0.005, 0.01, 0.010000001, 0.02, 0.32, 1.0, 10.0],
        dtype=np.float32,
    )

    for _ in range(64):
        line_lengths = rng.integers(0, 8, size=int(rng.integers(1, 8)))
        offsets = np.concatenate(([0], np.cumsum(line_lengths))).astype(np.int32)
        coords = np.empty((int(offsets[-1]), 3), dtype=np.float32)
        for line_index, line_length_raw in enumerate(line_lengths):
            line_length = int(line_length_raw)
            if line_length == 0:
                continue
            start = int(offsets[line_index])
            end = int(offsets[line_index + 1])
            origin = rng.normal(size=(1, 3)).astype(np.float32)
            steps = rng.normal(size=(line_length, 3)).astype(np.float32)
            scale = segment_scales[int(rng.integers(len(segment_scales)))]
            coords[start:end] = origin + np.cumsum(
                steps * scale,
                axis=0,
                dtype=np.float32,
            )

        subdivisions = int(rng.integers(1, 7))
        base_count = len(coords)
        vertex_cap = int(
            rng.choice(
                [
                    max(0, base_count - 1),
                    base_count,
                    base_count + 1,
                    base_count + int(rng.integers(2, 300)),
                    100_000,
                ]
            )
        )
        coords_before = coords.copy()
        offsets_before = offsets.copy()
        expected_coords, expected_offsets = _reference_subdivide(
            coords,
            offsets,
            subdivisions=subdivisions,
            max_total_vertices=vertex_cap,
        )
        monkeypatch.setattr(
            subdivide_module,
            "MAX_TOTAL_VERTICES",
            vertex_cap,
        )

        out_coords, out_offsets = subdivide_impl(
            (coords, offsets),
            subdivisions=subdivisions,
        )

        np.testing.assert_array_equal(out_coords, expected_coords)
        np.testing.assert_array_equal(out_offsets, expected_offsets)
        np.testing.assert_array_equal(coords, coords_before)
        np.testing.assert_array_equal(offsets, offsets_before)
        assert (out_coords is coords) == (expected_coords is coords)
        assert (out_offsets is offsets) == (expected_offsets is offsets)
