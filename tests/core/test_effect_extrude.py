"""effect extrude（押し出し）のスモークテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.operation_authoring import primitive
from grafix.core.realize import RealizeError, realize
from grafix.core.realized_geometry import GeomTuple


@primitive
def extrude_test_empty() -> GeomTuple:
    """空ジオメトリを返す。"""
    return np.zeros((0, 3), dtype=np.float32), np.zeros((1,), dtype=np.int32)


def test_extrude_noop_returns_input_geometry() -> None:
    g = G.line(center=(10.0, 0.0, 0.0), length=2.0, angle=0.0)
    out = E.extrude(
        delta=(0.0, 0.0, 0.0),
        scale=1.0,
        subdivisions=0,
        center_mode="auto",
    )(g)

    base_realized = realize(g)
    out_realized = realize(out)
    assert np.array_equal(out_realized.offsets, base_realized.offsets)
    assert np.array_equal(out_realized.coords, base_realized.coords)


def test_extrude_translates_and_connects_vertices() -> None:
    g = G.line(center=(0.0, 0.0, 0.0), length=2.0, angle=0.0)
    out = E.extrude(
        delta=(0.0, 10.0, 0.0),
        scale=1.0,
        subdivisions=0,
        center_mode="origin",
    )(g)

    realized = realize(out)
    assert realized.offsets.tolist() == [0, 2, 4, 6, 8]

    expected = np.asarray(
        [
            [-1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [-1.0, 10.0, 0.0],
            [1.0, 10.0, 0.0],
            [-1.0, 0.0, 0.0],
            [-1.0, 10.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 10.0, 0.0],
        ],
        dtype=np.float32,
    )
    assert realized.coords.dtype == np.float32
    assert np.allclose(realized.coords, expected)


def test_extrude_subdivisions_increase_vertex_density() -> None:
    g = G.line(center=(0.0, 0.0, 0.0), length=2.0, angle=0.0)
    out = E.extrude(
        delta=(0.0, 10.0, 0.0),
        scale=1.0,
        subdivisions=1,
        center_mode="auto",
    )(g)

    realized = realize(out)
    assert realized.offsets.tolist() == [0, 3, 6, 8, 10, 12]

    expected_first = np.asarray(
        [[-1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        dtype=np.float32,
    )
    assert np.allclose(realized.coords[0:3], expected_first)


@pytest.mark.parametrize(
    ("kwargs", "parameter"),
    [
        ({"scale": -0.1}, "scale"),
        ({"subdivisions": -1}, "subdivisions"),
    ],
)
def test_extrude_rejects_negative_parameters_before_empty_input(
    kwargs: dict[str, int | float],
    parameter: str,
) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(E.extrude(**kwargs)(G.extrude_test_empty()))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert parameter in str(exc_info.value.__cause__)
