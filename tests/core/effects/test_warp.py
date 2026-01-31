"""warp effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.realize import realize


def test_warp_requires_two_inputs() -> None:
    a = G.line(length=100.0)
    with pytest.raises(TypeError):
        E.warp()(a)


def test_warp_lens_noop_when_mask_has_no_valid_rings() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    mask = G.line(length=100.0)

    out = realize(E.warp(mode="lens")(base, mask))
    expected = realize(base)

    np.testing.assert_allclose(out.coords, expected.coords, rtol=0.0, atol=1e-6)
    assert out.offsets.tolist() == expected.offsets.tolist()


def test_warp_lens_deforms_points_inside_and_keeps_outside() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    mask = G.polygon(n_sides=64, scale=100.0)

    out = realize(
        E.warp(
            mode="lens",
            kind="scale",
            scale=2.0,
            strength=1.0,
            profile="band",
            band=20.0,
            inside_only=True,
        )(base, mask)
    )
    expected = realize(base)

    assert out.offsets.tolist() == expected.offsets.tolist()

    moved = float(np.linalg.norm(out.coords[0, 0:2] - expected.coords[0, 0:2]))
    stayed = float(np.linalg.norm(out.coords[1, 0:2] - expected.coords[1, 0:2]))
    assert moved > 1e-3
    assert stayed < 1e-6


def test_warp_show_mask_appends_mask_geom_even_when_noop() -> None:
    base = G.line(length=10.0)
    mask = G.polygon(n_sides=6, scale=20.0)

    out = realize(E.warp(mode="lens", strength=0.0, show_mask=True)(base, mask))
    expected_base = realize(base)
    expected_mask = realize(mask)

    n0 = int(expected_base.coords.shape[0])
    n1 = int(expected_mask.coords.shape[0])

    assert out.offsets.tolist() == [0, n0, n0 + n1]
    np.testing.assert_allclose(out.coords[0:n0], expected_base.coords, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(out.coords[n0 : n0 + n1], expected_mask.coords, rtol=0.0, atol=1e-6)


def test_warp_keep_original_and_show_mask_appends_in_order() -> None:
    base = G.line(length=10.0)
    mask = G.polygon(n_sides=6, scale=20.0)

    out = realize(
        E.warp(
            mode="lens",
            kind="scale",
            scale=2.0,
            strength=1.0,
            band=0.0,
            keep_original=True,
            show_mask=True,
        )(base, mask)
    )
    expected_base = realize(base)
    expected_mask = realize(mask)

    n0 = int(expected_base.coords.shape[0])
    n1 = int(expected_mask.coords.shape[0])

    assert out.offsets.tolist() == [0, n0, n0 + n0, n0 + n0 + n1]
    np.testing.assert_allclose(out.coords[n0 : n0 + n0], expected_base.coords, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(
        out.coords[n0 + n0 : n0 + n0 + n1], expected_mask.coords, rtol=0.0, atol=1e-6
    )


def test_warp_attract_projects_line_endpoints_to_mask_boundary() -> None:
    base = G.line(center=(0.0, 0.0, 0.0), length=80.0, angle=0.0)
    mask = G.polygon(n_sides=64, scale=50.0)

    out = realize(
        E.warp(
            mode="attract",
            direction="attract",
            strength=1.0,
            bias=0.0,
            snap_band=0.0,
            falloff=0.0,
        )(base, mask)
    )

    assert out.coords.shape == (2, 3)
    assert out.offsets.tolist() == [0, 2]
    np.testing.assert_allclose(out.coords[:, 2], 0.0, rtol=0.0, atol=1e-6)

    # polygon(scale=50) は半径 25（=0.5*scale）。
    np.testing.assert_allclose(out.coords[0], (-25.0, 0.0, 0.0), rtol=0.0, atol=1e-4)
    np.testing.assert_allclose(out.coords[1], (25.0, 0.0, 0.0), rtol=0.0, atol=1e-4)

