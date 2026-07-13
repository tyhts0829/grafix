from __future__ import annotations

import numpy as np

from grafix.core.realized_geometry import (
    RealizedGeometry,
    concat_geom_tuples,
    concat_realized_geometries,
)


def _geometry(
    coords: list[list[float]],
    offsets: list[int],
) -> RealizedGeometry:
    return RealizedGeometry(
        coords=np.asarray(coords, dtype=np.float32).reshape((-1, 3)),
        offsets=np.asarray(offsets, dtype=np.int32),
    )


def test_realized_geometry_byte_size_counts_both_arrays() -> None:
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [0, 2])

    assert geometry.byte_size == geometry.coords.nbytes + geometry.offsets.nbytes


def test_concat_realized_geometries_preserves_empty_lines_and_offsets() -> None:
    first = _geometry([[0, 0, 0], [1, 0, 0]], [0, 0, 2])
    second = _geometry([[2, 0, 0], [3, 0, 0]], [0, 2, 2])

    result = concat_realized_geometries(first, second)

    np.testing.assert_array_equal(
        result.coords,
        np.asarray([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], dtype=np.float32),
    )
    assert result.offsets.tolist() == [0, 0, 2, 4, 4]
    assert result.coords.dtype == np.float32
    assert result.offsets.dtype == np.int32


def test_concat_geom_tuples_uses_packed_output_dtypes() -> None:
    coords, offsets = concat_geom_tuples(
        (
            np.asarray([[0.0, 0.0, 0.0]], dtype=np.float64),
            np.asarray([0, 1], dtype=np.int64),
        ),
        (
            np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 1], dtype=np.int32),
        ),
    )

    assert coords.dtype == np.float32
    assert offsets.dtype == np.int32
    assert offsets.tolist() == [0, 1, 2]


def test_concat_single_realized_geometry_reuses_immutable_object() -> None:
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [0, 2])

    assert concat_realized_geometries(geometry) is geometry


def test_concat_no_geometries_returns_canonical_empty_geometry() -> None:
    result = concat_realized_geometries()

    assert result.coords.shape == (0, 3)
    assert result.offsets.tolist() == [0]
