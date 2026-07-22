"""入力ポリラインを複数回描画（複製）し、太線風の見た目を作る effect。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.operation_authoring import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

bold_meta = {
    "count": ParamMeta(
        kind="int",
        ui_min=1,
        ui_max=10,
        description="元の線を含めて出力するストロークの本数。",
    ),
    "radius": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=1.0,
        description="複製ストロークを XY 平面でずらす最大半径。",
    ),
    "seed": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=2**31 - 1,
        description="ストロークのずれを再現可能にする乱数シード。",
    ),
}


def _sample_offsets_xy(*, rng: np.random.Generator, n: int, radius: float) -> np.ndarray:
    """半径 radius の一様円盤から (dx, dy) を n 個サンプリングする。"""
    if n <= 0:
        return np.zeros((0, 2), dtype=np.float64)

    u = rng.random(n)
    v = rng.random(n)
    r = radius * np.sqrt(u)
    theta = 2.0 * math.pi * v
    dx = r * np.cos(theta)
    dy = r * np.sin(theta)
    return np.stack([dx, dy], axis=1).astype(np.float64, copy=False)


@effect(meta=bold_meta)
def bold(
    g: GeomTuple,
    *,
    count: int = 5,
    radius: float = 0.5,
    seed: int = 0,
) -> GeomTuple:
    """入力を複製して太線風にする。

    同じ線を少しずつずらして複数回描画することで、インクの重なりによる
    太線の見た目を作る。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力実体ジオメトリ（coords, offsets）。
    count : int, default 5
        出力ストローク数（元の線を 1 本含む）。1 で no-op。
    radius : float, default 0.5
        ずらし量の最大半径 [mm] 相当（XY のみ）。0 で no-op。
    seed : int, default 0
        0 以上のずらし量生成用乱数シード（決定性のため）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        複製後の実体ジオメトリ（coords, offsets）。

    Raises
    ------
    ValueError
        `count` が 1 未満、`radius` が負、または `seed` が負の場合。

    Notes
    -----
    - ずらし量は半径 `radius` の一様円盤からサンプルする。
    - z は維持し、XY の平行移動のみ適用する。
    - 最初の 1 本（k=0）はオフセット 0 で入力と一致する。
    """
    if count < 1:
        raise ValueError("bold の count は 1 以上である必要がある")
    if radius < 0.0:
        raise ValueError("bold の radius は 0 以上である必要がある")
    if seed < 0:
        raise ValueError("bold の seed は 0 以上である必要がある")

    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    copies = count
    if copies == 1:
        return coords, offsets

    r = radius
    if r == 0.0:
        return coords, offsets

    n_vertices = int(coords.shape[0])
    n_lines = int(offsets.size) - 1
    if n_vertices <= 0 or n_lines <= 0:
        return coords, offsets

    # float64 作業領域まで含めた一貫した memory budget を両方の実行経路へ適用する。
    ensure_geometry_output(
        "bold",
        vertices=n_vertices * copies,
        lines=n_lines * copies,
        scratch_bytes=n_vertices * copies * 3 * 8,
        hint="count または入力 geometry の複雑さを減らしてください",
    )

    rng = np.random.default_rng(seed)
    offsets_xy = np.zeros((copies, 2), dtype=np.float64)
    offsets_xy[1:] = _sample_offsets_xy(rng=rng, n=copies - 1, radius=r)

    base_coords64 = coords.astype(np.float64, copy=False)
    # 7 copies 以下は配列準備コストより単純な小配列 loop の方が小さい。
    if copies >= 8:
        # float64 加算後の値を直接 float32 出力へ格納し、copies 倍の
        # float64 作業配列を確保しない。
        coords_out = np.empty((n_vertices * copies, 3), dtype=np.float32)
        out_coords_view = coords_out.reshape(copies, n_vertices, 3)
        out_coords_view[...] = base_coords64
        np.add(
            out_coords_view[:, :, 0],
            offsets_xy[:, None, 0],
            out=out_coords_view[:, :, 0],
            casting="unsafe",
        )
        np.add(
            out_coords_view[:, :, 1],
            offsets_xy[:, None, 1],
            out=out_coords_view[:, :, 1],
            casting="unsafe",
        )
    else:
        out_coords64 = np.empty((n_vertices * copies, 3), dtype=np.float64)
        for k in range(copies):
            s = k * n_vertices
            e = s + n_vertices
            out_coords64[s:e] = base_coords64
            out_coords64[s:e, 0] += offsets_xy[k, 0]
            out_coords64[s:e, 1] += offsets_xy[k, 1]
        coords_out = out_coords64.astype(np.float32, copy=False)

    tail = offsets[1:].astype(np.int64, copy=False)
    out_offsets = np.empty((n_lines * copies + 1,), dtype=np.int32)
    out_offsets[0] = 0
    shifts = np.arange(copies, dtype=np.int64) * n_vertices
    np.add(
        tail[None, :],
        shifts[:, None],
        out=out_offsets[1:].reshape(copies, n_lines),
        casting="unsafe",
    )

    return coords_out, out_offsets


__all__ = ["bold", "bold_meta"]
