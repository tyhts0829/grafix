"""primitive の activate パラメータのテスト。"""

from __future__ import annotations

import numpy as np

from grafix.api import G
from grafix.core.geometry import Geometry
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple


def test_primitive_activate_false_returns_empty_geometry() -> None:
    base = realize(G.polygon(n_sides=6))
    bypassed = realize(G.polygon(activate=False, n_sides=6))

    assert base.coords.shape[0] > 0
    assert bypassed.coords.shape == (0, 3)
    assert bypassed.offsets.tolist() == [0]


def test_primitive_activate_false_works_without_meta() -> None:
    @primitive(meta=None)
    def dummy_primitive(*, x: float = 1.0) -> GeomTuple:
        coords = np.asarray([[x, 0.0, 0.0]], dtype=np.float32)
        offsets = np.asarray([0, 1], dtype=np.int32)
        return coords, offsets

    base = realize(Geometry.create("dummy_primitive", params={"x": 2.0}))
    bypassed = realize(
        Geometry.create("dummy_primitive", params={"x": 2.0, "activate": False})
    )

    assert base.coords.shape == (1, 3)
    assert bypassed.coords.shape == (0, 3)
    assert bypassed.offsets.tolist() == [0]
