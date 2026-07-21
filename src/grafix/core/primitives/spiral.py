"""Archimedean spiralを生成する基本primitive。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

spiral_meta = {
    "inner_radius": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="曲線の始点における中心からの半径を指定します。",
    ),
    "outer_radius": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="曲線の終点における中心からの半径を指定します。",
    ),
    "turns": ParamMeta(
        kind="float",
        ui_min=-20.0,
        ui_max=20.0,
        description="螺旋の符号付き周回数を指定します。負値は時計回りになります。",
    ),
    "phase": ParamMeta(
        kind="float",
        ui_min=-360.0,
        ui_max=360.0,
        description="+X 軸を基準とする始点の角度を度単位で指定します。",
    ),
    "samples": ParamMeta(
        kind="int",
        ui_min=2,
        ui_max=8000,
        description="始点と終点を含む曲線の頂点数を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=-300.0,
        ui_max=300.0,
        description="螺旋の中心となる XYZ 座標を指定します。",
    ),
}

_FLOAT32_MAX = float(np.finfo(np.float32).max)


def _assign_float32_component(
    destination: np.ndarray,
    values: np.ndarray,
    *,
    axis: str,
) -> None:
    """実際のsampleが有限なfloat32範囲にある場合だけ格納する。"""

    minimum = float(values.min())
    maximum = float(values.max())
    if (
        not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum < -_FLOAT32_MAX
        or maximum > _FLOAT32_MAX
    ):
        raise ValueError(
            f"spiral の出力 {axis} 座標は有限な float32 の範囲である必要がある"
        )
    destination[:] = values


@primitive(meta=spiral_meta)
def spiral(
    *,
    inner_radius: float = 0.0,
    outer_radius: float = 0.5,
    turns: float = 5.0,
    phase: float = 0.0,
    samples: int = 512,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """半径を線形補間するArchimedean spiralを生成する。

    頂点は始点から終点へ向かう順に格納する。局所座標はXY平面上にあり、
    ``center`` のXYZ成分で平行移動する。曲線は閉鎖点を追加しない1本の
    open polylineで、頂点数は常に``samples``である。

    Parameters
    ----------
    inner_radius : float, optional
        始点の半径。0以上。終点半径より大きい値も指定でき、その場合は中心へ向かう。
    outer_radius : float, optional
        終点の半径。0以上。
    turns : float, optional
        符号付き周回数。正値は反時計回り、負値は時計回り。
    phase : float, optional
        +X軸から測った始点角度。単位は度。
    samples : int, optional
        始点と終点を含む頂点数。2以上。
    center : tuple[float, float, float], optional
        螺旋の中心となるXYZ座標。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        1本のopen polylineを表す``(coords, offsets)``。

    Raises
    ------
    ValueError
        半径が負、引数が非有限、``samples``が2未満、または出力座標が
        float32の有限範囲を超える場合。
    """

    inner = inner_radius
    outer = outer_radius
    turns_f = turns
    phase_f = phase
    if inner < 0.0 or outer < 0.0:
        raise ValueError("spiral の inner_radius/outer_radius は 0 以上である必要がある")

    cx, cy, cz = center

    if abs(cz) > _FLOAT32_MAX:
        raise ValueError(
            "spiral の出力 Z 座標は有限な float32 の範囲である必要がある"
        )

    samples_i = samples
    if samples_i < 2:
        raise ValueError("spiral の samples は 2 以上である必要がある")
    # 位相は360度周期なので、巨大な有限値をそのままradiansへ拡大しない。
    # 先に剰余へ落とすことで、小さなturnsがfloatの桁落ちで消えるのを防ぐ。
    phase_rad = math.radians(math.remainder(phase_f, 360.0))
    angle_end = phase_rad + math.tau * turns_f
    if not math.isfinite(phase_rad) or not math.isfinite(angle_end):
        raise ValueError("spiral の phase と turns が表す角度は有限である必要がある")

    ensure_geometry_output(
        "spiral",
        vertices=samples_i,
        lines=1,
        # angle、radius、三角関数の再利用work領域はいずれもfloat64。
        scratch_bytes=samples_i * 3 * 8,
        hint="samples を減らしてください",
    )

    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        angles = np.linspace(phase_rad, angle_end, num=samples_i, dtype=np.float64)
        radii = np.linspace(inner, outer, num=samples_i, dtype=np.float64)
        work = np.empty((samples_i,), dtype=np.float64)
        coords = np.empty((samples_i, 3), dtype=np.float32)

        np.cos(angles, out=work)
        np.multiply(work, radii, out=work)
        if cx != 0.0:
            np.add(work, cx, out=work)
        _assign_float32_component(coords[:, 0], work, axis="X")

        np.sin(angles, out=work)
        np.multiply(work, radii, out=work)
        if cy != 0.0:
            np.add(work, cy, out=work)
        _assign_float32_component(coords[:, 1], work, axis="Y")
        coords[:, 2] = np.float32(cz)

    offsets = np.array([0, samples_i], dtype=np.int32)
    return coords, offsets


__all__ = ["spiral", "spiral_meta"]
