"""lens effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.realize import realize


def test_lens_requires_two_inputs() -> None:
    a = G.line(length=100.0)
    with pytest.raises(TypeError):
        E.lens()(a)


def test_lens_noop_when_lens_has_no_valid_rings() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    lens = G.line(length=100.0)

    out = realize(E.lens()(base, lens))
    expected = realize(base)

    np.testing.assert_allclose(out.coords, expected.coords, rtol=0.0, atol=1e-6)
    assert out.offsets.tolist() == expected.offsets.tolist()


def test_lens_deforms_points_inside_and_keeps_outside() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    lens = G.polygon(n_sides=64, scale=100.0)

    out = realize(
        E.lens(
            kind="scale",
            scale=2.0,
            strength=1.0,
            profile="band",
            band=20.0,
            inside_only=True,
        )(base, lens)
    )
    expected = realize(base)

    assert out.offsets.tolist() == expected.offsets.tolist()

    moved = float(np.linalg.norm(out.coords[0, 0:2] - expected.coords[0, 0:2]))
    stayed = float(np.linalg.norm(out.coords[1, 0:2] - expected.coords[1, 0:2]))
    assert moved > 1e-3
    assert stayed < 1e-6


def test_lens_keep_original_appends_base() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    lens = G.polygon(n_sides=64, scale=100.0)

    out = realize(E.lens(keep_original=True)(base, lens))
    expected = realize(base)

    assert out.coords.shape[0] == expected.coords.shape[0] * 2
    assert out.offsets.size == expected.offsets.size + 1


def test_lens_show_lens_appends_lens_geom() -> None:
    base = G.line(length=10.0)
    lens = G.polygon(n_sides=6, scale=20.0)

    out = realize(E.lens(strength=0.0, show_lens=True)(base, lens))
    expected_base = realize(base)
    expected_lens = realize(lens)

    n0 = int(expected_base.coords.shape[0])
    n1 = int(expected_lens.coords.shape[0])

    assert out.offsets.tolist() == [0, n0, n0 + n1]
    np.testing.assert_allclose(out.coords[0:n0], expected_base.coords, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(out.coords[n0 : n0 + n1], expected_lens.coords, rtol=0.0, atol=1e-6)
