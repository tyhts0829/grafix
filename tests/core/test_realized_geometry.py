from __future__ import annotations

import numpy as np
import pytest

from grafix.core.realized_geometry import (
    RealizedGeometry,
    concat_geom_tuples,
    concat_realized_geometries,
    empty_geom_tuple,
    lines_to_geom_tuple,
    realized_geometry_from_tuple,
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


def test_with_coords_reuses_immutable_offsets_and_snapshots_coords() -> None:
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [0, 1, 2])
    coords = np.asarray([[2, 0, 0], [3, 0, 0]], dtype=np.float32)

    result = geometry._with_coords(coords)

    assert result is not None
    assert result.coords is not coords
    assert not np.shares_memory(result.coords, coords)
    assert result.offsets is geometry.offsets
    assert result.coords.flags.writeable is False
    assert result.offsets.flags.writeable is False
    np.testing.assert_array_equal(result.coords, coords)
    coords[:] = 99.0
    np.testing.assert_array_equal(
        result.coords,
        np.asarray([[2, 0, 0], [3, 0, 0]], dtype=np.float32),
    )


def test_with_coords_defers_non_trusted_inputs_to_normal_validation() -> None:
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [0, 2])

    assert (
        geometry._with_coords(
            np.asarray([[2, 0, 0], [3, 0, 0]], dtype=np.float64)
        )
        is None
    )
    assert (
        geometry._with_coords(
            np.asarray([[2, 0], [3, 0]], dtype=np.float32)
        )
        is None
    )
    assert (
        geometry._with_coords(
            np.asarray([[2, 0, 0]], dtype=np.float32)
        )
        is None
    )


def test_public_constructor_still_rejects_non_monotonic_offsets() -> None:
    with pytest.raises(ValueError, match="offsets は単調非減少"):
        RealizedGeometry(
            coords=np.zeros((2, 3), dtype=np.float32),
            offsets=np.asarray([0, 2, 1, 2], dtype=np.int32),
        )


def test_constructor_owns_immutable_snapshots_without_freezing_callers() -> None:
    coords = np.asarray([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]], dtype=np.float32)
    offsets = np.asarray([0, 2], dtype=np.int32)

    geometry = RealizedGeometry(coords=coords, offsets=offsets)

    assert coords.flags.writeable
    assert offsets.flags.writeable
    assert not np.shares_memory(geometry.coords, coords)
    assert not np.shares_memory(geometry.offsets, offsets)

    coords[:] = -1.0
    offsets[:] = 0
    np.testing.assert_array_equal(
        geometry.coords,
        np.asarray([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]], dtype=np.float32),
    )
    np.testing.assert_array_equal(geometry.offsets, [0, 2])

    with pytest.raises(ValueError, match="WRITEABLE"):
        geometry.coords.setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        geometry.offsets.setflags(write=True)


def test_constructor_reuses_existing_immutable_snapshots() -> None:
    original = _geometry([[0.0, 0.0, 0.0]], [0, 1])

    rebuilt = RealizedGeometry(coords=original.coords, offsets=original.offsets)

    assert rebuilt.coords is original.coords
    assert rebuilt.offsets is original.offsets


def test_constructor_copies_readonly_memoryview_with_mutable_backing() -> None:
    raw = bytearray(
        np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32).tobytes(order="C")
    )
    coords = np.frombuffer(memoryview(raw).toreadonly(), dtype=np.float32).reshape(
        (1, 3)
    )

    geometry = RealizedGeometry(
        coords=coords,
        offsets=np.asarray([0, 1], dtype=np.int32),
    )
    np.frombuffer(raw, dtype=np.float32)[:] = 99.0

    assert not np.shares_memory(geometry.coords, coords)
    np.testing.assert_array_equal(
        geometry.coords,
        np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32),
    )


def test_constructor_copies_readonly_view_with_mutable_ndarray_base() -> None:
    base = np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32)
    coords = base.view()
    coords.setflags(write=False)

    geometry = RealizedGeometry(
        coords=coords,
        offsets=np.asarray([0, 1], dtype=np.int32),
    )
    base[:] = 99.0

    assert not np.shares_memory(geometry.coords, coords)
    np.testing.assert_array_equal(
        geometry.coords,
        np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32),
    )


def test_realized_geometry_from_tuple_requires_exact_tuple() -> None:
    class TupleSubclass(tuple):
        pass

    value = TupleSubclass(
        (
            np.zeros((1, 3), dtype=np.float32),
            np.asarray([0, 1], dtype=np.int32),
        )
    )

    with pytest.raises(TypeError, match="期待する戻り値"):
        realized_geometry_from_tuple(value, context="test")


@pytest.mark.parametrize(
    ("coords", "offsets", "message"),
    [
        (
            np.zeros((2, 2), dtype=np.float32),
            np.asarray([0, 2], dtype=np.int32),
            r"shape \(N,3\)",
        ),
        (
            np.zeros((2, 3), dtype=np.float64),
            np.asarray([0, 2], dtype=np.int32),
            "float32",
        ),
        (
            np.zeros((2, 3), dtype=np.float32),
            np.asarray([0.0, 2.0], dtype=np.float64),
            "int32",
        ),
        (
            np.asarray([[0.0, 0.0, 0.0], [np.inf, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 2], dtype=np.int32),
            "有限値",
        ),
        (
            np.zeros((3, 3), dtype=np.float32)[::2],
            np.asarray([0, 2], dtype=np.int32),
            "C-contiguous",
        ),
        (
            np.zeros((2, 3), dtype=np.float32),
            np.asarray([0, 1, 2, 2], dtype=np.int32)[::2],
            "C-contiguous",
        ),
    ],
)
def test_constructor_rejects_noncanonical_arrays(
    coords: np.ndarray,
    offsets: np.ndarray,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        RealizedGeometry(coords=coords, offsets=offsets)


def test_constructor_rejects_array_subclasses_and_python_sequences() -> None:
    class ArraySubclass(np.ndarray):
        pass

    coords = np.zeros((2, 3), dtype=np.float32)
    offsets = np.asarray([0, 2], dtype=np.int32)

    with pytest.raises(TypeError, match="exact np.ndarray"):
        RealizedGeometry(coords=coords.view(ArraySubclass), offsets=offsets)
    with pytest.raises(TypeError, match="exact np.ndarray"):
        RealizedGeometry(coords=coords, offsets=[0, 2])  # type: ignore[arg-type]


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


def test_concat_geom_tuples_requires_canonical_inputs() -> None:
    first = (
        np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.asarray([0, 1], dtype=np.int32),
    )
    second = (
        np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
        np.asarray([0, 1], dtype=np.int32),
    )

    coords, offsets = concat_geom_tuples(first, second)

    assert coords.dtype == np.float32
    assert offsets.dtype == np.int32
    assert offsets.tolist() == [0, 1, 2]

    with pytest.raises(TypeError, match="float32"):
        concat_geom_tuples(
            (
                np.asarray([[0.0, 0.0, 0.0]], dtype=np.float64),
                first[1],
            )
        )
    with pytest.raises(TypeError, match="int32"):
        concat_geom_tuples(
            (
                first[0],
                np.asarray([0, 1], dtype=np.int64),
            )
        )


def test_concat_single_geom_tuple_returns_canonical_arrays() -> None:
    coords = np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.asarray([0, 1], dtype=np.int32)

    result_coords, result_offsets = concat_geom_tuples((coords, offsets))

    assert result_coords is coords
    assert result_offsets is offsets


def test_concat_geom_tuples_rejects_noncanonical_tuple_shape() -> None:
    with pytest.raises(TypeError, match="exact"):
        concat_geom_tuples(  # type: ignore[arg-type]
            [
                np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
                np.asarray([0, 1], dtype=np.int32),
            ]
        )


def test_concat_geom_tuples_rejects_noncanonical_array_layout() -> None:
    with pytest.raises(ValueError, match="C-contiguous"):
        concat_geom_tuples(
            (
                np.zeros((3, 3), dtype=np.float32)[::2],
                np.asarray([0, 2], dtype=np.int32),
            )
        )


def test_concat_geom_tuples_preserves_empty_lines() -> None:
    coords, offsets = concat_geom_tuples(
        (
            np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 0, 1], dtype=np.int32),
        ),
        (
            np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 1, 1], dtype=np.int32),
        ),
    )

    assert coords.shape == (2, 3)
    assert offsets.tolist() == [0, 0, 1, 2, 2]


def test_concat_single_realized_geometry_reuses_immutable_object() -> None:
    geometry = _geometry([[0, 0, 0], [1, 0, 0]], [0, 2])

    assert concat_realized_geometries(geometry) is geometry


def test_concat_no_geometries_returns_canonical_empty_geometry() -> None:
    result = concat_realized_geometries()

    assert result.coords.shape == (0, 3)
    assert result.offsets.tolist() == [0]


def test_empty_geom_tuple_returns_fresh_standard_buffers() -> None:
    first_coords, first_offsets = empty_geom_tuple()
    second_coords, second_offsets = empty_geom_tuple()

    assert first_coords.shape == (0, 3)
    assert first_coords.dtype == np.float32
    assert first_offsets.tolist() == [0]
    assert first_offsets.dtype == np.int32
    assert first_coords is not second_coords
    assert first_offsets is not second_offsets


def test_lines_to_geom_tuple_preserves_order_dtypes_and_empty_lines() -> None:
    lines = [
        np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.float64),
        np.empty((0, 3), dtype=np.float32),
        np.asarray([[6, 7, 8]], dtype=np.float32),
    ]

    coords, offsets = lines_to_geom_tuple(lines)

    assert coords.dtype == np.float32
    assert coords.flags.c_contiguous
    assert coords.flags.owndata
    assert offsets.dtype == np.int32
    assert offsets.flags.c_contiguous
    assert offsets.flags.owndata
    assert offsets.tolist() == [0, 2, 2, 3]
    np.testing.assert_array_equal(
        coords,
        np.asarray([[0, 1, 2], [3, 4, 5], [6, 7, 8]], dtype=np.float32),
    )


def test_lines_to_geom_tuple_keeps_each_all_empty_line_in_offsets() -> None:
    coords, offsets = lines_to_geom_tuple(
        [
            np.empty((0, 3), dtype=np.float64),
            np.empty((0, 3), dtype=np.float32),
        ]
    )

    assert coords.shape == (0, 3)
    assert coords.dtype == np.float32
    assert offsets.tolist() == [0, 0, 0]
