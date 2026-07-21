"""第一級APIとして提供する基本2D shape primitiveを検証する。"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from grafix import G
from grafix.core.primitives.bezier import bezier
from grafix.core.primitives.polyline import polyline
from grafix.core.primitives.spline import spline
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
        G.polyline(
            points=((0.0, 0.0), (1.0, 0.0, 2.0), (1.0, 1.0)),
            closed=True,
        )
    )

    assert result.offsets.tolist() == [0, 4]
    np.testing.assert_allclose(result.coords[1], [1.0, 0.0, 2.0])
    np.testing.assert_array_equal(result.coords[0], result.coords[-1])
    assert "points" not in G.describe("polyline").meta


def test_polyline_empty_input_is_empty_geometry() -> None:
    result = realize(G.polyline(points=()))
    assert result.coords.shape == (0, 3)
    assert result.offsets.tolist() == [0]


def test_polyline_rejects_ndarray_before_evaluation() -> None:
    points = np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64)

    with pytest.raises(TypeError, match="immutable"):
        G.polyline(points=points)


@pytest.mark.parametrize(
    "points",
    [
        ((True, 0.0),),
        (("0.0", 1.0),),
    ],
)
def test_polyline_rejects_non_numeric_point_components(
    points: tuple[tuple[object, ...], ...],
) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(G.polyline(points=points))

    assert isinstance(exc_info.value.__cause__, TypeError)


def test_polyline_rejects_nonfinite_points_before_evaluation() -> None:
    with pytest.raises(ValueError, match="非有限"):
        G.polyline(points=((0.0, float("nan")),))


def test_polyline_raw_path_requires_exact_point_tuples() -> None:
    with pytest.raises(TypeError, match="points.*exact tuple"):
        polyline(points=[(0.0, 0.0)])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"points\[0\].*exact tuple"):
        polyline(points=([0.0, 0.0],))  # type: ignore[arg-type]


def test_polyline_raw_path_accepts_exact_builtin_numeric_components() -> None:
    coords, offsets = polyline(
        points=((0, 0.0), (1, 1.5)),
    )

    np.testing.assert_allclose(coords, [[0.0, 0.0, 0.0], [1.0, 1.5, 0.0]])
    assert offsets.tolist() == [0, 2]


@pytest.mark.parametrize(
    "component",
    [
        True,
        Fraction(1, 2),
        np.float32(0.5),
        np.int64(1),
    ],
)
@pytest.mark.parametrize(
    "factory",
    [
        lambda component: polyline(points=((component, 0.0),)),
        lambda component: bezier(p0=(component, 0.0)),
        lambda component: spline(points=((component, 0.0),)),
    ],
)
def test_raw_code_owned_points_reject_non_exact_numeric_components(
    factory,
    component: object,
) -> None:
    with pytest.raises(TypeError, match=r"exact int.*float"):
        factory(component)


def test_polyline_raw_path_rejects_invalid_numeric_ranges() -> None:
    with pytest.raises(ValueError, match="有限値"):
        polyline(points=((0.0, float("inf")),))
    with pytest.raises(ValueError, match="float32"):
        polyline(points=((0.0, float(np.finfo(np.float32).max) * 2.0),))


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
