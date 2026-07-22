"""
どこで: `src/grafix/core/primitives/lissajous.py`。リサージュ曲線プリミティブの実体生成。
何を: 周波数比・位相・サンプル数から、XY 平面上のリサージュ曲線を 1 本の開ポリラインとして生成する。
なぜ: 周期曲線の生成を `G` だけで完結させ、effect と組み合わせて再利用しやすくするため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.operation_authoring import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

lissajous_meta = {
    "a": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=20,
        description="X 方向の振動回数を決める角周波数係数を指定します。",
    ),
    "b": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=20,
        description="Y 方向の振動回数を決める角周波数係数を指定します。",
    ),
    "phase": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=360.0,
        description="Y 振動に対する X 振動の位相差を度単位で指定します。",
    ),
    "samples": ParamMeta(
        kind="int",
        ui_min=2,
        ui_max=8000,
        description="曲線全体を構成するサンプリング点の数を指定します。",
    ),
    "turns": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=20.0,
        description="パラメータ t が 2π を周回する回数を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="生成した曲線全体を平行移動する XYZ 座標を指定します。",
    ),
    "scale": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="幅と高さが 1 の曲線全体に適用する等方スケールを指定します。",
    ),
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
        0 以上の X 方向角周波数係数。
    b : int, optional
        0 以上の Y 方向角周波数係数。
    phase : float, optional
        X 方向の位相 [deg]。
    samples : int, optional
        サンプリング点数。2 以上。
    turns : float, optional
        0 以上の `t` 範囲の周回数。`t ∈ [0, 2π * turns]`。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率 s。縦横比変更は effect を使用する。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        リサージュ曲線を表す 1 本の開ポリライン（coords, offsets）。

    Raises
    ------
    ValueError
        `a`、`b`、`turns` が負、または ``samples`` が 2 未満の場合。
    """
    if a < 0 or b < 0:
        raise ValueError("lissajous の a/b は 0 以上である必要がある")
    if turns < 0.0:
        raise ValueError("lissajous の turns は 0 以上である必要がある")
    if samples < 2:
        raise ValueError("lissajous の samples は 2 以上である必要がある")
    samples_i = samples
    ensure_geometry_output(
        "lissajous",
        vertices=samples_i,
        lines=1,
        # t/x/y/z と stack 前後の一時配列を保守的に見積もる。
        scratch_bytes=samples_i * 4 * 4,
        hint="samples を減らしてください",
    )

    cx, cy, cz = center

    a_i = a
    b_i = b
    phase_rad = math.radians(phase)
    turns_f = turns
    s_f = scale

    t = np.linspace(
        0.0,
        np.float32(2.0 * math.pi * turns_f),
        num=samples_i,
        endpoint=True,
        dtype=np.float32,
    )
    x = np.sin(np.float32(a_i) * t + np.float32(phase_rad)) * np.float32(0.5)
    y = np.sin(np.float32(b_i) * t) * np.float32(0.5)

    coords = np.empty((samples_i, 3), dtype=np.float32)
    coords[:, 0] = x
    coords[:, 1] = y
    coords[:, 2] = 0.0
    if s_f != 1.0:
        coords *= np.float32(s_f)
    if (cx, cy, cz) != (0.0, 0.0, 0.0):
        coords += np.array([cx, cy, cz], dtype=np.float32)

    offsets = np.array([0, int(coords.shape[0])], dtype=np.int32)
    return coords, offsets
