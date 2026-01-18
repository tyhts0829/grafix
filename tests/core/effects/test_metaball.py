"""metaball effect のテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import RealizedGeometry


def _circle_xy(*, center: tuple[float, float], r: float, n: int = 96) -> np.ndarray:
    cx, cy = float(center[0]), float(center[1])
    t = np.linspace(0.0, 2.0 * np.pi, int(n), endpoint=False, dtype=np.float64)
    x = cx + float(r) * np.cos(t)
    y = cy + float(r) * np.sin(t)
    z = np.zeros_like(x)
    coords = np.stack([x, y, z], axis=1).astype(np.float32, copy=False)
    return np.concatenate([coords, coords[0:1]], axis=0)


@primitive
def metaball_test_two_circles_near_xy() -> RealizedGeometry:
    a = _circle_xy(center=(-12.0, 0.0), r=10.0)
    b = _circle_xy(center=(12.0, 0.0), r=10.0)
    coords = np.concatenate([a, b], axis=0).astype(np.float32, copy=False)
    offsets = np.array([0, int(a.shape[0]), int(a.shape[0] + b.shape[0])], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def metaball_test_two_circles_far_xy() -> RealizedGeometry:
    a = _circle_xy(center=(-30.0, 0.0), r=10.0)
    b = _circle_xy(center=(30.0, 0.0), r=10.0)
    coords = np.concatenate([a, b], axis=0).astype(np.float32, copy=False)
    offsets = np.array([0, int(a.shape[0]), int(a.shape[0] + b.shape[0])], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def metaball_test_donut_xy() -> RealizedGeometry:
    outer = _circle_xy(center=(0.0, 0.0), r=10.0)
    inner = _circle_xy(center=(0.0, 0.0), r=5.0)
    coords = np.concatenate([outer, inner], axis=0).astype(np.float32, copy=False)
    offsets = np.array(
        [0, int(outer.shape[0]), int(outer.shape[0] + inner.shape[0])],
        dtype=np.int32,
    )
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def metaball_test_nonplanar_ring() -> RealizedGeometry:
    ring = _circle_xy(center=(0.0, 0.0), r=10.0, n=48).astype(np.float64, copy=True)
    ring[:, 2] = np.linspace(0.0, 1.0, int(ring.shape[0]), dtype=np.float64)
    coords = ring.astype(np.float32, copy=False)
    offsets = np.array([0, int(coords.shape[0])], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def test_metaball_connects_near_circles() -> None:
    g = G.metaball_test_two_circles_near_xy()
    out = E.metaball(radius=3.0, threshold=1.0, grid_pitch=0.5)(g)
    realized = realize(out)

    assert int(realized.offsets.size) == 2
    assert int(realized.coords.shape[0]) > 10
    np.testing.assert_allclose(realized.coords[:, 2], 0.0, rtol=0.0, atol=1e-4)


def test_metaball_does_not_connect_far_circles() -> None:
    g = G.metaball_test_two_circles_far_xy()
    out = E.metaball(radius=3.0, threshold=1.0, grid_pitch=0.5)(g)
    realized = realize(out)

    assert int(realized.offsets.size) == 3
    assert int(realized.coords.shape[0]) > 10
    np.testing.assert_allclose(realized.coords[:, 2], 0.0, rtol=0.0, atol=1e-4)


def test_metaball_radius_zero_is_noop() -> None:
    g = G.metaball_test_two_circles_near_xy()
    base = realize(g)
    out = E.metaball(radius=0.0, threshold=1.0, grid_pitch=0.5)(g)
    realized = realize(out)

    assert realized.offsets.tolist() == base.offsets.tolist()
    np.testing.assert_allclose(realized.coords, base.coords, rtol=0.0, atol=1e-6)


def test_metaball_nonplanar_is_noop() -> None:
    g = G.metaball_test_nonplanar_ring()
    base = realize(g)
    out = E.metaball(radius=3.0, threshold=1.0, grid_pitch=0.5)(g)
    realized = realize(out)

    assert realized.offsets.tolist() == base.offsets.tolist()
    np.testing.assert_allclose(realized.coords, base.coords, rtol=0.0, atol=1e-6)


def test_metaball_outputs_holes_for_donut() -> None:
    g = G.metaball_test_donut_xy()
    out = E.metaball(radius=1.0, threshold=1.0, grid_pitch=0.5)(g)
    realized = realize(out)

    assert int(realized.offsets.size) >= 3
    np.testing.assert_allclose(realized.coords[:, 2], 0.0, rtol=0.0, atol=1e-4)

    widths: list[float] = []
    for i in range(int(realized.offsets.size) - 1):
        s = int(realized.offsets[i])
        e = int(realized.offsets[i + 1])
        line = realized.coords[s:e, :2].astype(np.float64, copy=False)
        if line.shape[0] < 4:
            continue
        mins = np.min(line, axis=0)
        maxs = np.max(line, axis=0)
        widths.append(float(np.max(maxs - mins)))

    assert widths
    assert max(widths) > 1.5 * min(widths)

