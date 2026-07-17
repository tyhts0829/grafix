"""Geometry の + 演算子（concat）テスト。"""

from __future__ import annotations

import pickle

import pytest

from grafix.core.geometry import Geometry


def _g(name: str) -> Geometry:
    return Geometry.create(name, params={"x": 1.0})


def test_add_creates_concat() -> None:
    a = _g("a")
    b = _g("b")
    c = a + b
    assert isinstance(c, Geometry)
    assert c.op == "concat"
    assert c.inputs == (a, b)
    assert c.args == ()


def test_add_keeps_left_associative_concat_binary() -> None:
    a = _g("a")
    b = _g("b")
    c = _g("c")
    combined = (a + b) + c
    assert combined.op == "concat"
    assert combined.inputs == (a + b, c)


def test_add_keeps_right_associative_concat_binary() -> None:
    a = _g("a")
    b = _g("b")
    c = _g("c")
    combined = a + (b + c)
    assert combined.op == "concat"
    assert combined.inputs == (a, b + c)
    assert combined.id != ((a + b) + c).id


def test_bulk_concat_flattens_nested_internal_concat() -> None:
    a = _g("a")
    b = _g("b")
    c = _g("c")

    combined = Geometry.concat(iter((a + b, Geometry.concat([c]))))

    assert combined.op == "concat"
    assert combined.inputs == (a, b, c)


def test_bulk_concat_empty_and_single() -> None:
    a = _g("a")
    nested = a + _g("b")

    empty = Geometry.concat([])

    assert empty.op == "concat"
    assert empty.inputs == ()
    assert Geometry.concat([a]) is a
    assert Geometry.concat([nested]) is nested


def test_bulk_concat_keeps_shared_concat_as_an_evaluation_boundary() -> None:
    leaf = _g("leaf")
    shared = leaf + leaf
    for _ in range(30):
        shared = shared + shared
    tail = _g("tail")

    combined = Geometry.concat([shared, tail])

    assert combined.inputs == (*shared.inputs, tail)
    assert len(combined.inputs) == 3


def test_bulk_concat_rejects_non_geometry() -> None:
    with pytest.raises(TypeError, match="Geometry"):
        Geometry.concat([_g("a"), object()])  # type: ignore[list-item]


def test_sum_works() -> None:
    a = _g("a")
    b = _g("b")
    c = _g("c")
    combined = sum([a, b, c])
    assert combined.op == "concat"
    assert combined.inputs[1] is c
    assert combined.inputs[0].inputs == (a, b)


def test_add_raises_on_invalid_type() -> None:
    a = _g("a")
    with pytest.raises(TypeError):
        _ = a + 1  # type: ignore[operator]


def test_deep_binary_recipe_object_protocols_do_not_recurse() -> None:
    leaf = _g("leaf")
    geometry = leaf
    for _ in range(10_000):
        geometry = geometry + leaf
    same_content = Geometry(
        id=geometry.id,
        op=geometry.op,
        inputs=geometry.inputs,
        args=geometry.args,
    )

    assert geometry == same_content
    assert hash(geometry) == hash(same_content)
    assert geometry.id in repr(geometry)

    restored = pickle.loads(pickle.dumps(geometry))

    assert restored == geometry
    assert restored.inputs[1] == leaf
