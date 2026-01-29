"""asemic primitive の最小テスト。"""

from __future__ import annotations

import numpy as np

from grafix.api import G
from grafix.core.primitives.asemic import asemic as asemic_impl
from grafix.core.realize import realize


def test_asemic_impl_is_deterministic() -> None:
    a = asemic_impl(seed=0, n_nodes=28, candidates=12)
    b = asemic_impl(seed=0, n_nodes=28, candidates=12)

    assert np.array_equal(a.coords, b.coords)
    assert np.array_equal(a.offsets, b.offsets)


def test_asemic_api_returns_valid_geometry() -> None:
    g = realize(G.asemic(seed=0, n_nodes=28, candidates=12))

    assert g.coords.dtype == np.float32
    assert g.offsets.dtype == np.int32
    assert g.offsets[0] == 0
    assert g.offsets[-1] == g.coords.shape[0]
    assert np.all(np.diff(g.offsets) >= 0)
    assert np.all(np.isfinite(g.coords))
    assert g.coords.shape[0] > 0

