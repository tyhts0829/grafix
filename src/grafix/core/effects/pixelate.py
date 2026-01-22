"""ポリラインをグリッド上の階段（水平/垂直）線に変換する effect。"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from numba import njit  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry

MAX_TOTAL_VERTICES = 10_000_000

pixelate_meta = {
    "step": ParamMeta(kind="vec3", ui_min=0.0, ui_max=10.0),
    "corner": ParamMeta(kind="choice", choices=("auto", "xy", "yx")),
}


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _round_half_away_from_zero(values: np.ndarray) -> np.ndarray:
    """0.5 境界を絶対値方向へ丸める（half away from zero）。"""
    return np.sign(values) * np.floor(np.abs(values) + 0.5)


@njit(cache=True)
def _pixelate_line_length(ix: np.ndarray, iy: np.ndarray, iz: np.ndarray) -> int:
    """ポリライン 1 本の pixelate 後頂点数（厳密）を返す（Numba）。"""
    n = int(ix.shape[0])
    if n <= 0:
        return 0
    if n == 1:
        return 1

    steps = 0
    for i in range(n - 1):
        dx = int(ix[i + 1] - ix[i])
        dy = int(iy[i + 1] - iy[i])
        ax = abs(dx)
        ay = abs(dy)
        steps += ax + ay
        if ax == 0 and ay == 0 and int(iz[i + 1]) != int(iz[i]):
            steps += 1

    return 1 + int(steps)


@njit(cache=True)
def _pixelate_segment_core(
    out: np.ndarray,
    write_index: int,
    ix0: int,
    iy0: int,
    ix1: int,
    iy1: int,
    z0: float,
    z1: float,
    sx: float,
    sy: float,
    corner_mode: int,
) -> int:
    """1 セグメントを 4-connected の階段へ展開して out へ書き込む（Numba）。"""
    dx = int(ix1 - ix0)
    dy = int(iy1 - iy0)
    ax = int(abs(dx))
    ay = int(abs(dy))

    if ax == 0 and ay == 0:
        if z0 != z1:
            out[write_index, 0] = ix0 * sx
            out[write_index, 1] = iy0 * sy
            out[write_index, 2] = z1
            return write_index + 1
        return write_index

    sx_i = 1 if dx > 0 else -1 if dx < 0 else 0
    sy_i = 1 if dy > 0 else -1 if dy < 0 else 0

    total_steps = ax + ay
    step_index = 0

    x = int(ix0)
    y = int(iy0)

    dz = float(z1 - z0)
    if corner_mode == 1:
        diag_first_is_x = True
    elif corner_mode == 2:
        diag_first_is_x = False
    else:
        diag_first_is_x = ax >= ay

    if ax >= ay:
        d = 2 * ay - ax
        for _ in range(ax):
            if d >= 0 and ay > 0:
                if diag_first_is_x:
                    x += sx_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1

                    y += sy_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1
                else:
                    y += sy_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1

                    x += sx_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1

                d += 2 * (ay - ax)
            else:
                x += sx_i
                step_index += 1
                t = step_index / total_steps
                out[write_index, 0] = x * sx
                out[write_index, 1] = y * sy
                out[write_index, 2] = z0 + dz * t
                write_index += 1

                d += 2 * ay
    else:
        d = 2 * ax - ay
        for _ in range(ay):
            if d >= 0 and ax > 0:
                if diag_first_is_x:
                    x += sx_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1

                    y += sy_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1
                else:
                    y += sy_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1

                    x += sx_i
                    step_index += 1
                    t = step_index / total_steps
                    out[write_index, 0] = x * sx
                    out[write_index, 1] = y * sy
                    out[write_index, 2] = z0 + dz * t
                    write_index += 1

                d += 2 * (ax - ay)
            else:
                y += sy_i
                step_index += 1
                t = step_index / total_steps
                out[write_index, 0] = x * sx
                out[write_index, 1] = y * sy
                out[write_index, 2] = z0 + dz * t
                write_index += 1

                d += 2 * ax

    return write_index


@njit(cache=True)
def _pixelate_line_into(
    out: np.ndarray,
    ix: np.ndarray,
    iy: np.ndarray,
    iz: np.ndarray,
    sx: float,
    sy: float,
    sz: float,
    corner_mode: int,
) -> int:
    """単一ポリラインを pixelate して out へ書き込む（Numba）。"""
    n = int(ix.shape[0])
    if n <= 0:
        return 0

    out[0, 0] = ix[0] * sx
    out[0, 1] = iy[0] * sy
    out[0, 2] = iz[0] * sz
    write_index = 1

    for i in range(n - 1):
        ix0 = int(ix[i])
        iy0 = int(iy[i])
        ix1 = int(ix[i + 1])
        iy1 = int(iy[i + 1])
        z0 = float(iz[i]) * sz
        z1 = float(iz[i + 1]) * sz
        write_index = _pixelate_segment_core(
            out, write_index, ix0, iy0, ix1, iy1, z0, z1, sx, sy, corner_mode
        )

    return write_index


@effect(meta=pixelate_meta)
def pixelate(
    inputs: Sequence[RealizedGeometry],
    *,
    step: tuple[float, float, float] = (1.0, 1.0, 1.0),
    corner: str = "auto",
) -> RealizedGeometry:
    """ポリラインをグリッド上の階段線へ変換する（XY）。

    Parameters
    ----------
    inputs : Sequence[RealizedGeometry]
        入力実体ジオメトリ列。通常は 1 要素。
    step : tuple[float, float, float], default (1.0, 1.0, 1.0)
        各軸の格子間隔 (sx, sy, sz)。いずれかが 0 以下なら no-op。
    corner : {"auto","xy","yx"}, default "auto"
        対角（x と y が同時に動く）を 2 手へ分解するときの順序。
        `"auto"` は major axis first（現状互換）。
        `"xy"` は常に x→y、`"yx"` は常に y→x。

    Returns
    -------
    RealizedGeometry
        pixelate 後の実体ジオメトリ（頂点数と offsets は変化する）。

    Notes
    -----
    - XY は 4-connected（水平/垂直のみ）となるように階段化する。
    - Z は `step[2]` でスナップした後、各入力セグメントの階段ステップ数に沿って線形補間する。
    - 対角の分解順序は `corner` に従う。
    """
    if not inputs:
        return _empty_geometry()

    base = inputs[0]
    coords = base.coords
    offsets = base.offsets
    if coords.shape[0] == 0:
        return base

    sx, sy, sz = float(step[0]), float(step[1]), float(step[2])
    if sx <= 0.0 or sy <= 0.0 or sz <= 0.0:
        return base

    corner_s = str(corner)
    if corner_s not in {"auto", "xy", "yx"}:
        return base
    corner_mode = 0 if corner_s == "auto" else 1 if corner_s == "xy" else 2

    step_vec = np.array([sx, sy, sz], dtype=np.float64)
    coords64 = coords.astype(np.float64, copy=False)
    q = coords64 / step_vec
    q_rounded = _round_half_away_from_zero(q)
    grid = q_rounded.astype(np.int64, copy=False)

    ix_all = grid[:, 0]
    iy_all = grid[:, 1]
    iz_all = grid[:, 2]

    n_lines = int(offsets.size) - 1
    if n_lines <= 0:
        return base

    line_ranges: list[tuple[int, int]] = []
    line_lengths: list[int] = []
    total_vertices = 0

    for li in range(n_lines):
        s = int(offsets[li])
        e = int(offsets[li + 1])
        if e <= s:
            continue

        ix = ix_all[s:e]
        iy = iy_all[s:e]
        iz = iz_all[s:e]

        est_n = int(_pixelate_line_length(ix, iy, iz))
        remaining = MAX_TOTAL_VERTICES - total_vertices
        if remaining <= 0 or est_n <= 0 or est_n > remaining:
            break

        line_ranges.append((s, e))
        line_lengths.append(est_n)
        total_vertices += est_n

    if not line_ranges:
        return _empty_geometry()

    offsets_out = np.empty((len(line_ranges) + 1,), dtype=np.int32)
    acc = 0
    offsets_out[0] = 0
    for i, n in enumerate(line_lengths):
        acc += int(n)
        offsets_out[i + 1] = acc

    coords_out = np.empty((acc, 3), dtype=np.float32)
    for i, (s, e) in enumerate(line_ranges):
        ws = int(offsets_out[i])
        we = int(offsets_out[i + 1])
        out_view = coords_out[ws:we]
        write_index = _pixelate_line_into(
            out_view, ix_all[s:e], iy_all[s:e], iz_all[s:e], sx, sy, sz, corner_mode
        )
        assert int(write_index) == int(out_view.shape[0])
    return RealizedGeometry(coords=coords_out, offsets=offsets_out)
