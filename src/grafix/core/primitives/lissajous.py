"""
どこで: `src/grafix/core/primitives/lissajous.py`。リサージュ曲線プリミティブの実体生成。
何を: 周波数比・位相・サンプル数から、XY 平面上のリサージュ曲線を 1 本の開ポリラインとして生成する。
なぜ: 周期曲線の生成を `G` だけで完結させ、effect と組み合わせて再利用しやすくするため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

lissajous_meta = {
    "a": ParamMeta(kind="int", ui_min=0, ui_max=20),
    "b": ParamMeta(kind="int", ui_min=0, ui_max=20),
    "phase": ParamMeta(kind="float", ui_min=0.0, ui_max=360.0),
    "samples": ParamMeta(kind="int", ui_min=2, ui_max=8000),
    "turns": ParamMeta(kind="float", ui_min=0.0, ui_max=20.0),
    "center": ParamMeta(kind="vec3", ui_min=0.0, ui_max=300.0),
    "scale": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
}


@primitive(meta=lissajous_meta)
def lissajous(
    *,
    a: int = 3,
    b: int = 2,
    phase: float = 90.0,
    samples: int = 512,
    turns: float = 1.0,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> GeomTuple:
    """リサージュ曲線を 1 本の開ポリラインとして生成する。

    Parameters
    ----------
    a : int, optional
        X 方向の角周波数係数。
    b : int, optional
        Y 方向の角周波数係数。
    phase : float, optional
        X 方向の位相 [deg]。
    samples : int, optional
        サンプリング点数。2 未満は `ValueError`。
    turns : float, optional
        `t` 範囲の周回数。`t ∈ [0, 2π * turns]`。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率 s。縦横比変更は effect を使用する。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        リサージュ曲線を表す 1 本の開ポリライン（coords, offsets）。
    """
    samples_i = int(samples)
    if samples_i < 2:
        raise ValueError("lissajous の samples は 2 以上である必要がある")

    try:
        cx, cy, cz = center
    except Exception as exc:
        raise ValueError(
            "lissajous の center は長さ 3 のシーケンスである必要がある"
        ) from exc

    a_i = int(a)
    b_i = int(b)
    phase_rad = math.radians(float(phase))
    turns_f = float(turns)
    s_f = float(scale)
    cx_f, cy_f, cz_f = float(cx), float(cy), float(cz)

    t = np.linspace(
        0.0,
        np.float32(2.0 * math.pi * turns_f),
        num=samples_i,
        endpoint=True,
        dtype=np.float32,
    )
    x = np.sin(np.float32(a_i) * t + np.float32(phase_rad)) * np.float32(0.5)
    y = np.sin(np.float32(b_i) * t) * np.float32(0.5)
    z = np.zeros_like(x, dtype=np.float32)

    coords = np.stack([x, y, z], axis=1).astype(np.float32, copy=False)
    if s_f != 1.0:
        coords *= np.float32(s_f)
    if (cx_f, cy_f, cz_f) != (0.0, 0.0, 0.0):
        coords += np.array([cx_f, cy_f, cz_f], dtype=np.float32)

    offsets = np.array([0, int(coords.shape[0])], dtype=np.int32)
    return coords, offsets
