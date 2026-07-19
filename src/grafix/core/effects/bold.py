"""入力ポリラインを複数回描画（複製）し、太線風の見た目を作る effect。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.effect_registry import effect
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
    r = float(radius) * np.sqrt(u)
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
        出力ストローク数（元の線を 1 本含む）。1 以下で no-op。
    radius : float, default 0.5
        ずらし量の最大半径 [mm] 相当（XY のみ）。0 以下で no-op。
    seed : int, default 0
        ずらし量生成の乱数シード（決定性のため）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        複製後の実体ジオメトリ（coords, offsets）。

    Notes
    -----
    - ずらし量は半径 `radius` の一様円盤からサンプルする。
    - z は維持し、XY の平行移動のみ適用する。
    - 最初の 1 本（k=0）はオフセット 0 で入力と一致する。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    copies = int(count)
    if copies <= 1:
        return coords, offsets

    r = float(radius)
    if not np.isfinite(r) or r <= 0.0:
        return coords, offsets

    n_vertices = int(coords.shape[0])
    n_lines = int(offsets.size) - 1
    if n_vertices <= 0 or n_lines <= 0:
        return coords, offsets

    # 従来の float64 作業配列を含む budget 判定境界を
    # 高速 path でも維持する。
    ensure_geometry_output(
        "bold",
        vertices=n_vertices * copies,
        lines=n_lines * copies,
        scratch_bytes=n_vertices * copies * 3 * 8,
        hint="count または入力 geometry の複雑さを減らしてください",
    )

    rng = np.random.default_rng(int(seed))
    offsets_xy = np.zeros((copies, 2), dtype=np.float64)
    offsets_xy[1:] = _sample_offsets_xy(rng=rng, n=copies - 1, radius=r)

    base_coords64 = coords.astype(np.float64, copy=False)
    standard_packed_input = (
        copies >= 3
        and type(coords) is np.ndarray
        and type(offsets) is np.ndarray
        and coords.dtype == np.float32
        and offsets.dtype == np.int32
        and coords.ndim == 2
        and coords.shape[1] == 3
        and offsets.ndim == 1
    )
    # 7 copies 以下は小配列で従来 loop の方が速いため、そのまま使う。
    direct_pack_candidate = copies >= 8 and standard_packed_input
    default_errstate = direct_pack_candidate and np.geterr() == {
        "divide": "warn",
        "over": "warn",
        "under": "ignore",
        "invalid": "warn",
    }
    if default_errstate:
        # C-order の全要素 reduction は、bool/abs の全長 temporary より速い。
        # signaling NaN 等の警告はこの判定では出さず、
        # 従来 branch 側だけで出す。
        with np.errstate(all="ignore"):
            coord_min = float(np.min(base_coords64))
            coord_max = float(np.max(base_coords64))
        finite_input = math.isfinite(coord_min) and math.isfinite(coord_max)
        max_abs_coord = max(abs(coord_min), abs(coord_max))
    else:
        finite_input = False
        max_abs_coord = float("inf")
    direct_pack = finite_input and r <= float(np.finfo(np.float32).max) - max_abs_coord

    if direct_pack:
        # 入力は float64 へ拡張してから加算し、ufunc の float64 loop から
        # float32 の出力へ cast する。従来の「float64 加算後 float32 化」と
        # 同じ丸めを保ちつつ、copies 倍の float64 作業配列を確保しない。
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
        # 非有限値、通常外 dtype/shape、ndarray subclass、変更された
        # NumPy errstate は警告・例外回数まで従来どおりにする。
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
    if standard_packed_input:
        shifts = np.arange(copies, dtype=np.int64) * n_vertices
        np.add(
            tail[None, :],
            shifts[:, None],
            out=out_offsets[1:].reshape(copies, n_lines),
            casting="unsafe",
        )
    else:
        for k in range(copies):
            start = 1 + k * n_lines
            end = start + n_lines
            out_offsets[start:end] = (tail + k * n_vertices).astype(
                np.int32, copy=False
            )

    return coords_out, out_offsets


__all__ = ["bold", "bold_meta"]
