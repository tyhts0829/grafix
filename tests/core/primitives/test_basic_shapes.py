"""第一級APIとして提供する基本2D shape primitiveを検証する。"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from grafix import G
from grafix.core.primitives.polyline import polyline as raw_polyline
from grafix.core.realize import RealizeError, realize
from grafix.core.resource_budget import ResourceLimitError


def test_circle_is_closed_and_uses_explicit_radius() -> None:
    result = realize(G.circle(radius=2.0, segments=8, center=(1.0, 2.0, 3.0)))

    assert result.offsets.tolist() == [0, 9]
    np.testing.assert_array_equal(result.coords[0], result.coords[-1])
    np.testing.assert_allclose(result.coords[0], [3.0, 2.0, 3.0], atol=1e-6)


def test_ellipse_and_rect_apply_angle_around_center() -> None:
    ellipse = realize(
        G.ellipse(radius_x=2.0, radius_y=1.0, angle=90.0, segments=8)
    )
    rect = realize(G.rect(width=2.0, height=4.0, angle=90.0))

    np.testing.assert_allclose(ellipse.coords[0], [0.0, 2.0, 0.0], atol=1e-6)
    np.testing.assert_array_equal(rect.coords[0], rect.coords[-1])
    np.testing.assert_allclose(rect.coords[0], [2.0, -1.0, 0.0], atol=1e-6)


def test_arc_is_open_and_supports_clockwise_sweep() -> None:
    result = realize(G.arc(radius=1.0, start=90.0, sweep=-90.0, segments=3))

    assert result.coords.shape == (4, 3)
    np.testing.assert_allclose(result.coords[0], [0.0, 1.0, 0.0], atol=1e-6)
    np.testing.assert_allclose(result.coords[-1], [1.0, 0.0, 0.0], atol=1e-6)
    assert not np.array_equal(result.coords[0], result.coords[-1])


def test_bezier_preserves_code_owned_endpoints() -> None:
    p0 = (1.0, 2.0, 3.0)
    p3 = (7.0, 8.0, 9.0)
    result = realize(
        G.bezier(p0=p0, p1=(2.0, 4.0), p2=(5.0, 6.0), p3=p3, segments=5)
    )

    assert result.coords.shape == (6, 3)
    np.testing.assert_allclose(result.coords[0], p0, atol=1e-6)
    np.testing.assert_allclose(result.coords[-1], p3, atol=1e-6)
    assert "p0" not in G.describe("bezier").meta


def test_polyline_accepts_2d_and_3d_points_and_closes_once() -> None:
    result = realize(
        G.polyline(points=[(0.0, 0.0), (1.0, 0.0, 2.0), (1.0, 1.0)], closed=True)
    )

    assert result.offsets.tolist() == [0, 4]
    np.testing.assert_allclose(result.coords[1], [1.0, 0.0, 2.0])
    np.testing.assert_array_equal(result.coords[0], result.coords[-1])
    assert "points" not in G.describe("polyline").meta


def test_polyline_empty_input_is_empty_geometry() -> None:
    result = realize(G.polyline(points=()))
    assert result.coords.shape == (0, 3)
    assert result.offsets.tolist() == [0]


@pytest.mark.parametrize("dimension", [2, 3])
@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.int64])
@pytest.mark.parametrize("closed", [False, True])
def test_polyline_ndarray_matches_sequence_fallback(
    dimension: int,
    dtype: type[np.generic],
    closed: bool,
) -> None:
    """数値ndarray経路は従来のsequence正規化と完全に同じ出力を返す。"""

    source = np.arange(63, dtype=dtype).reshape(21, 3)[:, :dimension]
    array_coords, array_offsets = raw_polyline(points=source, closed=closed)
    list_coords, list_offsets = raw_polyline(
        points=source.tolist(),
        closed=closed,
    )

    np.testing.assert_array_equal(array_coords, list_coords)
    np.testing.assert_array_equal(array_offsets, list_offsets)
    assert array_coords.flags.writeable
    assert array_offsets.flags.writeable
    assert not np.shares_memory(array_coords, source)


def test_polyline_ndarray_closure_uses_values_before_float32_rounding() -> None:
    """float32化で一致する端点も、入力値が異なれば閉鎖点を追加する。"""

    points = np.array([[1.0, -0.0], [1.0 + 2.0**-30, 0.0]], dtype=np.float64)
    coords, offsets = raw_polyline(points=points, closed=True)

    assert coords.shape == (3, 3)
    assert offsets.tolist() == [0, 3]
    np.testing.assert_array_equal(coords[0], coords[-1])


def test_polyline_ndarray_nan_endpoint_still_appends_closure() -> None:
    """NaNを含む端点は従来のtuple比較どおり等値と見なさない。"""

    points = np.array([[np.nan, -0.0], [np.nan, 0.0]], dtype=np.float64)
    coords, offsets = raw_polyline(points=points, closed=True)

    assert coords.shape == (3, 3)
    assert offsets.tolist() == [0, 3]
    np.testing.assert_array_equal(coords[0], coords[-1])


@pytest.mark.parametrize("dtype", [np.int64, np.uint64])
def test_polyline_wide_integer_keeps_python_float_rounding(
    dtype: type[np.generic],
) -> None:
    """64-bit整数を直接float32化して二段丸めを変えない。"""

    value = 2**53 + 2**29 + 1
    points = np.array([[value, 0], [value + 1, 1]], dtype=dtype)
    array_coords, array_offsets = raw_polyline(points=points)
    list_coords, list_offsets = raw_polyline(points=points.tolist())

    np.testing.assert_array_equal(array_coords, list_coords)
    np.testing.assert_array_equal(array_offsets, list_offsets)


def test_polyline_ndarray_preserves_scalar_cast_float_status_behavior() -> None:
    """underflow/sNaNは通知せず、overflowだけはseterrに従う。"""

    points = np.array(
        [[0x0000000000000001, 0], [0x7FF0000000000001, 0x3FF0000000000000]],
        dtype=np.uint64,
    ).view(np.float64)
    with np.errstate(under="raise", invalid="raise"):
        coords, _offsets = raw_polyline(points=points)

    assert coords[0, 0] == np.float32(0.0)
    assert np.isnan(coords[1, 0])

    overflowing = np.array([[1e300, 0.0], [0.0, 1.0]], dtype=np.float64)
    with np.errstate(over="raise"):
        with pytest.raises(FloatingPointError, match="overflow encountered in cast"):
            raw_polyline(points=overflowing)


def test_polyline_float32_signaling_nan_is_quieted_like_scalar_path() -> None:
    """float32 sNaNをraw bit copyせず、従来のPython float経路でquiet化する。"""

    points = np.array(
        [[0x7F800001, 0], [0, 0]],
        dtype=np.uint32,
    ).view(np.float32)
    coords, _offsets = raw_polyline(points=points)

    assert int(coords[0, 0].view(np.uint32)) == 0x7FC00001


def test_polyline_snapshots_ndarray_before_closed_boolean_evaluation() -> None:
    """closedのbool変換が入力を変更しても正規化済み点列は変えない。"""

    points = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    class MutatingClosed:
        def __bool__(self) -> bool:
            points[1] = (99.0, 98.0)
            return True

    coords, offsets = raw_polyline(
        points=points,
        closed=MutatingClosed(),  # type: ignore[arg-type]
    )

    np.testing.assert_array_equal(coords[1], [3.0, 4.0, 0.0])
    np.testing.assert_array_equal(points[1], [99.0, 98.0])
    assert offsets.tolist() == [0, 4]


def test_polyline_extended_float_uses_scalar_warning_semantics() -> None:
    """binary64より広いfloatは要素単位warningを保つfallbackへ送る。"""

    if np.dtype(np.longdouble).itemsize <= 8:
        pytest.skip("extended float dtype is unavailable")
    huge = np.longdouble(np.finfo(np.float64).max) * np.longdouble(2.0)
    points = np.array([[huge, 0.0], [-huge, 1.0]], dtype=np.longdouble)

    with warnings.catch_warnings(record=True) as array_warnings:
        warnings.simplefilter("always")
        with np.errstate(over="warn"):
            array_coords, array_offsets = raw_polyline(points=points)
    with warnings.catch_warnings(record=True) as sequence_warnings:
        warnings.simplefilter("always")
        with np.errstate(over="warn"):
            sequence_coords, sequence_offsets = raw_polyline(
                points=list(points),
            )

    np.testing.assert_array_equal(array_coords, sequence_coords)
    np.testing.assert_array_equal(array_offsets, sequence_offsets)
    assert [str(item.message) for item in array_warnings] == [
        str(item.message) for item in sequence_warnings
    ]


def test_polyline_finite_overflow_keeps_per_element_warning_count() -> None:
    """有限overflowを一括castの1 warningへ集約しない。"""

    points = np.array(
        [[1e300, 2e300], [-1e300, -2e300]],
        dtype=np.float64,
    )
    with warnings.catch_warnings(record=True) as array_warnings:
        warnings.simplefilter("always")
        with np.errstate(over="warn"):
            array_coords, array_offsets = raw_polyline(points=points)
    with warnings.catch_warnings(record=True) as sequence_warnings:
        warnings.simplefilter("always")
        with np.errstate(over="warn"):
            sequence_coords, sequence_offsets = raw_polyline(
                points=list(points),
            )

    np.testing.assert_array_equal(array_coords, sequence_coords)
    np.testing.assert_array_equal(array_offsets, sequence_offsets)
    assert [str(item.message) for item in array_warnings] == [
        str(item.message) for item in sequence_warnings
    ]
    assert len(array_warnings) == 4


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        (G.circle(segments=2), "3 以上"),
        (G.arc(segments=0), "1 以上"),
        (G.rect(width=-1.0), "0以上"),
    ],
)
def test_basic_shapes_reject_invalid_dimensions(geometry, message: str) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(geometry)
    assert exc_info.value.__cause__ is not None
    assert message in str(exc_info.value.__cause__)


def test_shape_preflight_uses_resource_budget() -> None:
    from grafix.core.realize import RealizeSession
    from grafix.core.resource_budget import ResourceBudget
    from grafix.core.runtime_limits import RuntimeLimits

    with RealizeSession(
        runtime_limits=RuntimeLimits(
            per_operation=ResourceBudget(
                max_output_vertices=4,
                max_output_lines=1,
                max_output_bytes=1024,
            )
        )
    ) as session:
        with pytest.raises(RealizeError) as exc_info:
            session.realize(G.circle(segments=8))

    assert isinstance(exc_info.value.__cause__, ResourceLimitError)


def test_basic_shapes_are_discoverable_from_catalog() -> None:
    names = {entry.name for entry in G.catalog()}
    assert {"arc", "bezier", "circle", "ellipse", "polyline", "rect"} <= names
