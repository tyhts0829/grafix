"""LayerNamespace (L) の挙動テスト。"""

from __future__ import annotations

import pytest

from grafix.api import L
from grafix.core.geometry import Geometry


def _g(name: str = "circle") -> Geometry:
    return Geometry.create(name, params={"r": 1.0})


def test_L_returns_list_for_single_geometry() -> None:
    layers = L.layer(_g())
    assert len(layers) == 1
    assert layers[0].geometry.op == "circle"


def test_L_applies_common_style_to_multiple_geometries() -> None:
    g1, g2 = _g("circle"), _g("circle")
    layers = L(name="foo").layer([g1, g2], color=(1.0, 0.0, 0.0), thickness=0.02)
    assert len(layers) == 1
    layer = layers[0]
    assert layer.color == (1.0, 0.0, 0.0)
    assert layer.thickness == 0.02
    assert layer.name == "foo"
    assert layer.geometry.op == "concat"
    # concat inputs should be preserved
    assert len(layer.geometry.inputs) == 2


def test_L_rejects_non_geometry_inputs() -> None:
    with pytest.raises(TypeError):
        L.layer([_g(), 123])


def test_L_rejects_non_positive_thickness() -> None:
    with pytest.raises(ValueError):
        L.layer(_g(), thickness=0.0)


def test_L_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        L.layer([])


def test_L_rejects_builder_style_kwargs() -> None:
    with pytest.raises(TypeError):
        L(color=(1.0, 0.0, 0.0))  # type: ignore[call-arg]


def test_L_rejects_layer_name_kwarg() -> None:
    with pytest.raises(TypeError):
        L(name="foo").layer(_g(), name="bar")  # type: ignore[call-arg]
