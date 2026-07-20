"""Geometry 内容署名の canonical encoding を検証する。"""

from __future__ import annotations

from enum import Enum, IntEnum
from itertools import combinations
from math import copysign
from types import MappingProxyType
from typing import Any

import pytest

from grafix.core.geometry import Geometry


class _Color(Enum):
    RED = "red"


class _Code(IntEnum):
    ONE = 1


class _Label(str, Enum):
    ONE = "one"


class _MaskedColor(Enum):
    RED = "red"

    def __repr__(self) -> str:
        return "<masked>"


class _OtherMaskedColor(Enum):
    RED = "red"

    def __repr__(self) -> str:
        return "<masked>"


def _geometry(value: Any) -> Geometry:
    return Geometry.create("signature-test", params={"value": value})


def _typed_equal(left: Any, right: Any) -> bool:
    """通常の数値 equality では失われる型の違いも比較する。"""

    if type(left) is not type(right):
        return False
    if isinstance(left, tuple):
        return len(left) == len(right) and all(
            _typed_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def test_large_integer_is_preserved_without_float_round_trip() -> None:
    large = 2**53 + 1

    geometry = _geometry(large)

    assert geometry.args == (("value", large),)
    assert type(geometry.args[0][1]) is int
    assert geometry.id != _geometry(large - 1).id


def test_numeric_types_have_distinct_signatures() -> None:
    values = (True, 1, 1.0, _Code.ONE)
    geometries = tuple(_geometry(value) for value in values)

    assert len({geometry.id for geometry in geometries}) == len(values)
    assert tuple(type(geometry.args[0][1]) for geometry in geometries) == tuple(
        type(value) for value in values
    )


@pytest.mark.parametrize(
    ("enum_value", "underlying_value"),
    ((_Color.RED, "red"), (_Code.ONE, 1), (_Label.ONE, "one")),
)
def test_enum_type_is_preserved_and_part_of_signature(
    enum_value: Enum,
    underlying_value: object,
) -> None:
    geometry = _geometry(enum_value)

    assert geometry.args[0][1] is enum_value
    assert geometry.id != _geometry(underlying_value).id


def test_enum_signature_does_not_depend_on_custom_repr() -> None:
    assert repr(_MaskedColor.RED) == repr(_OtherMaskedColor.RED)
    assert _geometry(_MaskedColor.RED).id != _geometry(_OtherMaskedColor.RED).id


def test_string_delimiters_cannot_merge_tuple_elements() -> None:
    assert _geometry(("a", "b")).id != _geometry(("a,sb",)).id


def test_argument_delimiters_cannot_merge_adjacent_arguments() -> None:
    embedded = Geometry.create("signature-test", params={"a": "xk:b=sY"})
    separated = Geometry.create("signature-test", params={"a": "x", "b": "Y"})

    assert embedded.id != separated.id


def test_nested_sequence_boundaries_are_part_of_signature() -> None:
    nested = _geometry((("a", "b"), ("c",)))
    flat = _geometry(("a", "b", "c"))

    assert nested.id != flat.id


def test_mapping_order_is_canonical_and_runtime_value_is_immutable() -> None:
    left = _geometry({"b": [2, 3], "a": 1})
    right = _geometry(MappingProxyType({"a": 1, "b": (2, 3)}))

    assert left.args == (("value", (("a", 1), ("b", (2, 3)))),)
    assert left.args == right.args
    assert left.id == right.id


def test_negative_zero_is_canonicalized_to_positive_zero() -> None:
    negative = _geometry(-0.0)
    positive = _geometry(0.0)

    assert negative.id == positive.id
    normalized = negative.args[0][1]
    assert normalized == 0.0
    assert copysign(1.0, normalized) == 1.0


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_non_finite_float_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="非有限"):
        _geometry(value)


def test_geometry_signature_is_fixed_to_canonical_v2() -> None:
    geometry = Geometry.create("signature-test", params={"value": 1})

    assert geometry.id == "cab9e82cb486258a9ac6892af871ce82"


def test_equal_id_implies_identical_typed_runtime_arguments() -> None:
    values: tuple[Any, ...] = (
        None,
        False,
        True,
        0,
        1,
        2**53 + 1,
        -0.0,
        0.0,
        1.0,
        "",
        "1",
        "a,b",
        _Color.RED,
        _Code.ONE,
        _Label.ONE,
        (),
        (1,),
        [1],
        ("a", "b"),
        ("a,sb",),
        {"b": 2, "a": 1},
        (("a", 1), ("b", 2)),
    )
    geometries = tuple(_geometry(value) for value in values)

    for left, right in combinations(geometries, 2):
        if left.id == right.id:
            assert _typed_equal(left.args, right.args)
