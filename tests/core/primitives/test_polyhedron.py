"""polyhedron プリミティブの面ポリライン形状に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import G
from grafix.core.geometry import Geometry
from grafix.core.realize import realize
from grafix.core.primitives import polyhedron as _polyhedron_module  # noqa: F401


@pytest.mark.parametrize(
    "kind,expected_faces",
    [
        ("tetrahedron", 4),
        ("hexahedron", 6),
        ("octahedron", 8),
        ("dodecahedron", 12),
        ("icosahedron", 20),
    ],
)
def test_polyhedron_face_count_and_closed_polylines(
    kind: str,
    expected_faces: int,
) -> None:
    """面数が一致し、各面が閉ポリライン（先頭==末尾）になっている。"""
    g = Geometry.create("polyhedron", params={"kind": kind})
    realized = realize(g)

    assert realized.offsets.shape[0] == expected_faces + 1

    for i in range(expected_faces):
        start = int(realized.offsets[i])
        end = int(realized.offsets[i + 1])
        assert end - start >= 2
        np.testing.assert_array_equal(realized.coords[start], realized.coords[end - 1])


def test_polyhedron_kind_rejects_unknown_name() -> None:
    """未知の形状名を別の形へ黙って置換しない。"""
    with pytest.raises(ValueError, match="polyhedron.*kind"):
        G.polyhedron(kind="unknown")


def test_polyhedron_center_and_scale_affect_coords() -> None:
    """center/scale が座標に反映される。"""
    base = realize(Geometry.create("polyhedron", params={"kind": "tetrahedron"}))

    center = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    scale = 2.0
    moved = realize(
        Geometry.create(
            "polyhedron",
            params={
                "kind": "tetrahedron",
                "center": (float(center[0]), float(center[1]), float(center[2])),
                "scale": float(scale),
            },
        )
    )

    expected = base.coords * np.float32(scale) + center
    np.testing.assert_allclose(moved.coords, expected, rtol=0.0, atol=1e-6)
