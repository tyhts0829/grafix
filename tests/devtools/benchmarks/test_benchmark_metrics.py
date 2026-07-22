from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.realized_geometry import RealizedGeometry
from grafix.devtools.benchmarks.metrics import canonical_checksum, geometry_checksum


def test_geometry_checksum_includes_dtype_shape_and_bytes() -> None:
    first = RealizedGeometry(
        coords=np.asarray([[0.0, 1.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1], dtype=np.int32),
    )
    changed = RealizedGeometry(
        coords=np.asarray([[0.0, 2.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1], dtype=np.int32),
    )

    assert geometry_checksum(first) != geometry_checksum(changed)
    checksum, kind = canonical_checksum(first)
    assert checksum == geometry_checksum(first)
    assert kind == "realized_geometry_exact_v1"


def test_concat_checksum_tracks_leaf_order_not_parenthesization() -> None:
    leaves = tuple(Geometry.create("leaf", params={"index": index}) for index in range(3))
    left = (leaves[0] + leaves[1]) + leaves[2]
    right = leaves[0] + (leaves[1] + leaves[2])
    reordered = leaves[1] + (leaves[0] + leaves[2])

    assert canonical_checksum(left) == canonical_checksum(right)
    assert canonical_checksum(left) != canonical_checksum(reordered)


def test_canonical_checksum_rejects_unknown_or_nondeterministic_values() -> None:
    @dataclass
    class ArbitraryRecord:
        value: int

    invalid_values = (
        object(),
        ArbitraryRecord(1),
        {1: "non-string-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        np.asarray([object()], dtype=object),
        (
            np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 1], dtype=np.int32),
        ),
        np.asarray([(1, 2)], dtype=[("x", "i4"), ("y", "i4")]),
        np.longdouble("0.5"),
        np.clongdouble("0.5+0.25j"),
        (1, 2),
    )

    for value in invalid_values:
        with pytest.raises((TypeError, ValueError)):
            canonical_checksum(value)


def test_canonical_checksum_rejects_bytes_subclasses() -> None:
    class MisleadingBytes(bytes):
        def hex(self, *args: object, **kwargs: object) -> str:
            del args, kwargs
            return "00"

    with pytest.raises(TypeError, match="unsupported benchmark checksum value"):
        canonical_checksum(MisleadingBytes(b"abc"))


def test_canonical_checksum_normalizes_supported_numpy_scalars() -> None:
    assert canonical_checksum({"value": np.int64(3)}) == canonical_checksum({"value": 3})
    assert canonical_checksum({"value": np.float32(0.5)}) == canonical_checksum({"value": 0.5})


def test_canonical_checksum_type_tags_cannot_collide_with_user_mappings() -> None:
    array = np.asarray([1.0], dtype=np.float32)

    assert canonical_checksum(b"value") != canonical_checksum(
        {"$grafix_checksum_type": "bytes", "hex": b"value".hex()}
    )
    assert canonical_checksum(array) != canonical_checksum(
        {
            "$grafix_checksum_type": "ndarray",
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        }
    )


def test_canonical_checksum_mapping_is_independent_of_insertion_order() -> None:
    assert canonical_checksum({"a": 1, "b": 2}) == canonical_checksum({"b": 2, "a": 1})


def test_canonical_checksum_does_not_collapse_tuple_into_json_array() -> None:
    with pytest.raises(TypeError, match="unsupported benchmark checksum value"):
        canonical_checksum((1, 2))
