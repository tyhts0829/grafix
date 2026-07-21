"""spline primitiveの補間規則とcanonical出力契約を検証する。"""

from __future__ import annotations

import importlib
import warnings

import numpy as np
import pytest

from grafix.core.primitives.spline import spline, spline_meta
from grafix.core.resource_budget import (
    ResourceBudget,
    ResourceLimitError,
    resource_budget_context,
)

spline_module = importlib.import_module("grafix.core.primitives.spline")


def test_spline_meta_exposes_only_gui_owned_parameters() -> None:
    """code-owned pointsを除き、全GUI引数に説明を持たせる。"""

    assert set(spline_meta) == {"closed", "tension", "segments_per_span"}
    assert all(meta.description for meta in spline_meta.values())


def test_spline_open_interpolates_mixed_2d_and_3d_anchors() -> None:
    """open curveは各anchorを入力順に1度ずつ通過する。"""

    points = ((0.0, 0.0), (1.0, 1.0, 2.0), (4.0, 0.0), (5.0, 2.0, -1.0))
    coords, offsets = spline(points=points, segments_per_span=4)

    assert coords.shape == (13, 3)
    assert offsets.tolist() == [0, 13]
    expected_anchors = np.array(
        ((0.0, 0.0, 0.0), (1.0, 1.0, 2.0), (4.0, 0.0, 0.0), (5.0, 2.0, -1.0)),
        dtype=np.float32,
    )
    np.testing.assert_array_equal(coords[::4], expected_anchors)


def test_spline_uses_centripetal_catmull_rom_parameterization() -> None:
    """不均等なchord長でもuniform Catmull–Romへ退行しない。"""

    coords, _ = spline(
        points=((0.0, 0.0), (1.0, 1.0), (4.0, 0.0), (5.0, 2.0)),
        segments_per_span=4,
    )

    # Barry–Goldman評価による第2 span中央のcentripetal参照値。
    np.testing.assert_allclose(
        coords[6],
        [2.51024731, 0.45751852, 0.0],
        rtol=0.0,
        atol=1e-6,
    )


def test_spline_closed_removes_boundary_duplicate_and_closes_bit_exactly() -> None:
    """closed curveは共有anchorを重ねず、末尾だけを厳密な閉鎖点とする。"""

    points = (
        (0.0, 0.0),
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
        (0.0, 0.0),
        (0.0, 0.0),
    )

    coords, offsets = spline(
        points=points,
        closed=True,
        segments_per_span=3,
    )

    assert coords.shape == (13, 3)
    assert offsets.tolist() == [0, 13]
    expected_anchors = np.array(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0),
        ),
        dtype=np.float32,
    )
    np.testing.assert_array_equal(coords[::3], expected_anchors)
    assert coords[0].tobytes() == coords[-1].tobytes()


@pytest.mark.parametrize("closed", [False, True])
def test_spline_empty_points_return_standard_empty_geometry(closed: bool) -> None:
    """空入力はopen/closedにかかわらずpolylineを持たない。"""

    coords, offsets = spline(points=(), closed=closed)

    assert coords.shape == (0, 3)
    assert coords.dtype == np.float32
    assert offsets.tolist() == [0]
    assert offsets.dtype == np.int32


@pytest.mark.parametrize("closed", [False, True])
def test_spline_one_unique_anchor_returns_one_vertex(closed: bool) -> None:
    """1点と全点一致は不要な閉鎖点を追加せず1頂点へ縮退する。"""

    coords, offsets = spline(
        points=((1.0, 2.0), (1.0, 2.0, 0.0), (1.0, 2.0)),
        closed=closed,
        segments_per_span=7,
    )

    np.testing.assert_array_equal(coords, [[1.0, 2.0, 0.0]])
    assert offsets.tolist() == [0, 1]


def test_spline_two_anchors_use_linear_open_span() -> None:
    """2点openはCatmull–Rom接線を作らず直線を等間隔samplingする。"""

    coords, offsets = spline(
        points=((0.0, 0.0), (2.0, 0.0)),
        segments_per_span=4,
    )

    np.testing.assert_array_equal(
        coords,
        np.array(
            (
                (0.0, 0.0, 0.0),
                (0.5, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.5, 0.0, 0.0),
                (2.0, 0.0, 0.0),
            ),
            dtype=np.float32,
        ),
    )
    assert offsets.tolist() == [0, 5]


def test_spline_two_anchors_closed_traverse_two_spans_without_shared_duplicate() -> None:
    """2点closedは終点を1度だけ共有して同じ線分を逆向きに戻る。"""

    coords, offsets = spline(
        points=((0.0, 0.0), (2.0, 0.0)),
        closed=True,
        segments_per_span=4,
    )

    np.testing.assert_array_equal(
        coords[:, 0],
        np.array(
            (0.0, 0.5, 1.0, 1.5, 2.0, 1.5, 1.0, 0.5, 0.0),
            dtype=np.float32,
        ),
    )
    assert offsets.tolist() == [0, 9]
    assert coords[0].tobytes() == coords[-1].tobytes()


def test_spline_tension_one_keeps_every_sample_on_its_anchor_chord() -> None:
    """tension=1はanchorを維持したまま各spanを直線化する。"""

    points = (
        (0.0, 0.0),
        (1.0, 1.0),
        (4.0, 0.0),
        (5.0, 2.0),
    )
    coords, _ = spline(
        points=points,
        tension=1.0,
        segments_per_span=8,
    )

    for span_index in range(3):
        start = np.asarray(points[span_index], dtype=np.float64)
        chord = np.asarray(points[span_index + 1], dtype=np.float64) - start
        samples = coords[
            span_index * 8 : (span_index + 1) * 8 + 1,
            :2,
        ]
        relative = samples - start
        cross = relative[:, 0] * chord[1] - relative[:, 1] * chord[0]
        np.testing.assert_allclose(cross, 0.0, rtol=0.0, atol=1e-6)


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"segments_per_span": 0}, ValueError, "segments_per_span.*1 以上"),
        ({"tension": -0.01}, ValueError, "tension.*0 以上 1 以下"),
        ({"tension": 1.01}, ValueError, "tension.*0 以上 1 以下"),
        ({"points": ((0.0,),)}, TypeError, "points.*2または3成分"),
        ({"points": ((0.0, "x"),)}, TypeError, "points.*exact int.*float"),
        ({"points": ((1e100, 0.0),)}, ValueError, "points.*float32範囲内"),
    ],
)
def test_spline_rejects_invalid_parameters(
    kwargs: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    """補間を定義できない値を暗黙補正しない。"""

    with pytest.raises(error, match=message):
        spline(**kwargs)  # type: ignore[arg-type]


def test_spline_rejects_float32_overflow_from_curve_overshoot_without_warning() -> None:
    """有限なanchorからのovershootもinfへcastせず明示的に拒否する。"""

    scale = float(np.finfo(np.float32).max) * 0.99
    points = (
        (0.0, 0.0),
        (scale, 0.0),
        (scale, scale),
        (0.0, scale),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(ValueError, match="補間結果.*float32範囲内"):
            spline(
                points=points,
                closed=True,
                segments_per_span=3,
            )


@pytest.mark.parametrize(
    "points",
    [
        ((float(np.nextafter(0.0, 1.0)), 0.0, 0.0),),
        ((0.0, 0.0, 0.0), (float(np.nextafter(0.0, 1.0)), 0.0, 0.0)),
        (
            (0.0, 0.0, 0.0),
            (float(np.nextafter(0.0, 1.0)), 0.0, 0.0),
            (0.0, float(np.nextafter(0.0, 1.0)), 0.0),
        ),
    ],
)
def test_spline_is_independent_of_numpy_underflow_policy(
    points: tuple[tuple[float, float, float], ...],
) -> None:
    """有限subnormal anchorを呼出元のnp.seterr設定に左右されず処理する。"""

    with np.errstate(all="raise"):
        coords, offsets = spline(points=points, segments_per_span=2)

    assert offsets[0] == 0
    assert offsets[-1] == coords.shape[0]
    assert np.isfinite(coords).all()


def test_spline_resource_preflight_uses_deduplicated_anchor_count() -> None:
    """連続重複除去後の正確な頂点数でbudgetを検査する。"""

    points = ((0.0, 0.0),) * 100 + ((1.0, 0.0),) * 100
    budget = ResourceBudget(
        max_output_vertices=4,
        max_output_lines=1,
        max_output_bytes=1024,
    )
    with resource_budget_context(budget):
        coords, offsets = spline(points=points, segments_per_span=3)

    assert coords.shape == (4, 3)
    assert offsets.tolist() == [0, 4]

    too_small = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=1,
        max_output_bytes=1024,
    )
    with resource_budget_context(too_small), pytest.raises(
        ResourceLimitError,
        match="spline.*vertices=4",
    ):
        spline(points=points, segments_per_span=3)


def test_spline_resource_budget_accepts_exact_estimate() -> None:
    """最終geometryと宣言scratchのvertex/line/byte境界を受理する。"""

    points = ((0.0, 0.0), (1.0, 1.0), (2.0, 0.0))
    segments = 4
    vertex_count = 9
    estimated_bytes = (
        vertex_count * 3 * 4
        + 2 * 4
        + len(points) * 3 * 8
        + segments * 128
    )
    budget = ResourceBudget(
        max_output_vertices=vertex_count,
        max_output_lines=1,
        max_output_bytes=estimated_bytes,
    )

    with resource_budget_context(budget):
        coords, offsets = spline(
            points=points,
            segments_per_span=segments,
        )

    assert coords.shape == (vertex_count, 3)
    assert offsets.tolist() == [0, vertex_count]


@pytest.mark.parametrize(
    ("vertices", "lines", "byte_delta"),
    [
        (8, 1, 0),
        (9, 0, 0),
        (9, 1, -1),
    ],
)
def test_spline_resource_budget_rejects_one_below_boundary(
    vertices: int,
    lines: int,
    byte_delta: int,
) -> None:
    """vertex、line、byteの各上限超過をexact境界の1手前で拒否する。"""

    points = ((0.0, 0.0), (1.0, 1.0), (2.0, 0.0))
    segments = 4
    estimated_bytes = 9 * 3 * 4 + 2 * 4 + len(points) * 3 * 8 + segments * 128
    budget = ResourceBudget(
        max_output_vertices=vertices,
        max_output_lines=lines,
        max_output_bytes=estimated_bytes + byte_delta,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="spline",
    ):
        spline(points=points, segments_per_span=segments)


def test_spline_resource_rejection_precedes_numpy_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """budget違反時はanchor/output NumPy配列を確保しない。"""

    def fail_allocation(*args: object, **kwargs: object) -> np.ndarray:
        raise AssertionError(f"unexpected allocation: {args!r}, {kwargs!r}")

    monkeypatch.setattr(spline_module.np, "asarray", fail_allocation)
    budget = ResourceBudget(
        max_output_vertices=8,
        max_output_lines=1,
        max_output_bytes=10_000,
    )
    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="spline",
    ):
        spline(
            points=((0.0, 0.0), (1.0, 1.0), (2.0, 0.0)),
            segments_per_span=4,
        )


@pytest.mark.parametrize(
    "points",
    [
        (),
        ((1.0, 2.0),),
        ((0.0, 0.0), (1.0, 2.0), (3.0, -1.0)),
    ],
)
def test_spline_evaluator_arrays_are_fresh_writable_c_contiguous(
    points: tuple[tuple[float, ...], ...],
) -> None:
    """evaluator呼び出しごとに独立した標準dtype配列を返す。"""

    coords_a, offsets_a = spline(points=points)
    coords_b, offsets_b = spline(points=points)

    assert coords_a.dtype == np.float32
    assert offsets_a.dtype == np.int32
    assert coords_a.flags.c_contiguous
    assert offsets_a.flags.c_contiguous
    assert coords_a.flags.writeable
    assert offsets_a.flags.writeable
    assert coords_b.flags.writeable
    assert offsets_b.flags.writeable
    assert not np.shares_memory(coords_a, coords_b)
    assert not np.shares_memory(offsets_a, offsets_b)

    coords_expected = coords_b.copy()
    offsets_expected = offsets_b.copy()
    if coords_a.size:
        coords_a.flat[0] = np.float32(123.0)
    offsets_a[0] = np.int32(1)
    np.testing.assert_array_equal(coords_b, coords_expected)
    np.testing.assert_array_equal(offsets_b, offsets_expected)
