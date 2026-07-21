"""primitive の activate パラメータのテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import G
from grafix.core.primitive_registry import primitive, primitive_registry
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple


def test_primitive_activate_false_returns_empty_geometry() -> None:
    base = realize(G.polygon(n_sides=6))
    bypassed = realize(G.polygon(activate=False, n_sides=6))

    assert base.coords.shape[0] > 0
    assert bypassed.coords.shape == (0, 3)
    assert bypassed.offsets.tolist() == [0]


def test_primitive_without_meta_has_no_hidden_activate_argument() -> None:
    original_specs = dict(primitive_registry.items())
    try:
        @primitive(meta=None)
        def dummy_primitive(*, x: float = 1.0) -> GeomTuple:
            coords = np.asarray([[x, 0.0, 0.0]], dtype=np.float32)
            offsets = np.asarray([0, 1], dtype=np.int32)
            return coords, offsets

        base = realize(G.dummy_primitive(x=2.0))

        assert base.coords.shape == (1, 3)
        with pytest.raises(TypeError, match="不明な引数"):
            G.dummy_primitive(x=2.0, activate=False)
    finally:
        primitive_registry.replace_all(original_specs)
