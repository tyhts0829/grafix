"""閉曲線群から符号付き距離場を作り、複数レベルの等高線（等値線）をポリライン化する effect。

この実装は「オフセット曲線を 1 本ずつ抽出する」代わりに、
一度 SDF（Signed Distance Field: 符号付き距離場）を評価し、そこから複数レベルをまとめて取り出す。

処理の全体像（読む順）
----------------------
1. 入力ポリライン群を近似的に XY 平面へ整列し、平面性をチェックする
2. 閉曲線（リング）だけを抽出し、SDF 評価用に詰め直す
3. グリッド上で SDF を評価する（内側が負、外側が正）
4. `sin(pi*(SDF-phase)/spacing)` の 0 等値線を Marching Squares で抽出する
   - `sin()` を使うことで、`SDF = phase + k*spacing`（k は整数）の全レベルを 1 回の抽出で得る
5. 抽出した線分群をスナップしながら縫合し、閉ループ（ポリライン）に復元する
6. 元の 3D 座標系へ戻し、(coords, offsets) に詰めて返す

注意
----
- 入力が平面から外れている、または閉曲線が取れない場合は空ジオメトリを返す。
- 入力の「外周＋穴」は even-odd（奇偶）規則で内外判定する（ネストした穴も扱える）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple
from .util import (
    DEFAULT_MAX_GRID_CELLS,
    GridSpec,
    PlanarFrame,
    empty_geom,
    marching_squares_loops,
    pack_polylines,
    signed_distance_grid_edt,
)

MAX_GRID_POINTS = DEFAULT_MAX_GRID_CELLS

_AUTO_CLOSE_THRESHOLD_DEFAULT = 1e-3
_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

isocontour_meta = {
    "spacing": ParamMeta(
        kind="float",
        ui_min=0.2,
        ui_max=10.0,
        description="隣り合う符号付き距離の等値線どうしの間隔。",
    ),
    "phase": ParamMeta(
        kind="float",
        ui_min=-10.0,
        ui_max=10.0,
        description="等値線レベル全体を距離方向へずらす位相。",
    ),
    "max_dist": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="入力境界から等値線を抽出する最大距離。",
    ),
    "mode": ParamMeta(
        kind="choice",
        choices=("inside", "outside", "both"),
        description="入力境界の内側、外側、または両側のどこから等値線を抽出するか選ぶ。",
    ),
    "grid_pitch": ParamMeta(
        kind="float",
        ui_min=0.1,
        ui_max=5.0,
        description="符号付き距離場を評価する二次元グリッドの間隔。",
    ),
    "gamma": ParamMeta(
        kind="float",
        ui_min=0.3,
        ui_max=3.0,
        description="抽出範囲を保ったまま等値線の距離分布を非線形に変形する指数。",
    ),
    "level_step": ParamMeta(
        kind="int",
        ui_min=1,
        ui_max=20,
        description="生成した等値線を何本ごとに一つ残すか指定する。",
    ),
    "auto_close_threshold": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=5.0,
        description="入力線の端点を自動的に閉じるとみなす最大距離。",
    ),
    "keep_original": ParamMeta(
        kind="bool",
        description="生成した等値線に元の入力線を加えて出力する。",
    ),
}


@dataclass(frozen=True, slots=True)
class _Ring2D:
    """平面化済みの閉曲線（リング）を SDF 評価用に保持する。

    `isocontour()` は入力が 3D でも「ほぼ平面」と仮定して処理するため、
    まず XY 平面上の 2D 座標に揃え（Z を落とし）リングを抽出してから SDF を作る。

    Notes
    -----
    `vertices` は「閉じたポリライン」で、先頭と末尾が一致している前提（first == last）。
    """

    vertices: np.ndarray  # (N, 2) float64, closed (first == last)
    mins: np.ndarray  # (2,) float64
    maxs: np.ndarray  # (2,) float64


def _planarity_threshold(points: np.ndarray) -> float:
    """「平面から外れている」とみなす Z 方向の許容値を求める。

    入力スケールに依存しないように、
    - 絶対誤差 `_PLANAR_EPS_ABS`
    - 相対誤差 `_PLANAR_EPS_REL * bbox_diag`
    の大きい方を採用する。
    """

    if points.size == 0:
        return float(_PLANAR_EPS_ABS)
    p = points.astype(np.float64, copy=False)
    mins = np.min(p, axis=0)
    maxs = np.max(p, axis=0)
    diag = float(np.linalg.norm(maxs - mins))
    return max(float(_PLANAR_EPS_ABS), float(_PLANAR_EPS_REL) * diag)


def _close_curve(points: np.ndarray, threshold: float) -> np.ndarray:
    """端点が近いポリラインを「閉曲線」とみなし、先頭点を末尾に複製する。

    Notes
    -----
    すでに閉じている場合（last が first と同一）でも、そのまま返す。
    端点距離が `threshold` を超える場合は「開曲線」として扱い、変更しない。
    """

    if points.shape[0] < 2:
        return points
    dist = float(np.linalg.norm(points[0] - points[-1]))
    if dist <= float(threshold):
        return np.concatenate([points[:-1], points[0:1]], axis=0)
    return points


def _extract_rings_xy(
    coords_xy: np.ndarray,
    offsets: np.ndarray,
    *,
    auto_close_threshold: float,
) -> list[_Ring2D]:
    """XY 平面上のポリライン列から「閉曲線リング」だけを抽出する。

    - 点数が足りないものは捨てる
    - `auto_close_threshold` 以内なら閉曲線として扱い、先頭点を末尾に複製する
    - 閉曲線にならないもの（開曲線）は捨てる
    """

    rings: list[_Ring2D] = []
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        poly3 = coords_xy[s:e]
        if poly3.shape[0] < 3:
            continue

        closed3 = _close_curve(poly3, float(auto_close_threshold))
        if closed3.shape[0] < 4:
            continue

        # 明示的に「先頭と末尾が一致」しているものだけをリングとして扱う。
        # ここで弾くことで、以降の処理（SDF/内外判定/線分縫合）が単純になる。
        if not np.allclose(closed3[0], closed3[-1], rtol=0.0, atol=1e-12):
            continue

        v2 = closed3[:, :2].astype(np.float64, copy=False)
        mins = np.min(v2, axis=0)
        maxs = np.max(v2, axis=0)
        rings.append(_Ring2D(vertices=v2, mins=mins, maxs=maxs))

    return rings


def _pack_rings(
    rings: list[_Ring2D],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """リング群を Numba 用の「平坦な配列」に詰め直す。

    Numba 側では Python の list / dataclass を扱いにくいため、
    - `ring_vertices`: 全リングの頂点を連結した (total, 2)
    - `ring_offsets`: 各リングの開始位置（prefix sum）
    - `ring_mins`, `ring_maxs`: 各リングの AABB
    に分解して渡す。
    """

    n = len(rings)
    total = 0
    for ring in rings:
        total += int(ring.vertices.shape[0])

    ring_vertices = np.empty((total, 2), dtype=np.float64)
    ring_offsets = np.empty((n + 1,), dtype=np.int32)
    ring_mins = np.empty((n, 2), dtype=np.float64)
    ring_maxs = np.empty((n, 2), dtype=np.float64)

    ring_offsets[0] = 0
    cursor = 0
    for i, ring in enumerate(rings):
        v = ring.vertices.astype(np.float64, copy=False)
        m = int(v.shape[0])
        ring_vertices[cursor : cursor + m] = v
        cursor += m
        ring_offsets[i + 1] = np.int32(cursor)
        ring_mins[i] = ring.mins
        ring_maxs[i] = ring.maxs

    return ring_vertices, ring_offsets, ring_mins, ring_maxs



@effect(meta=isocontour_meta, n_inputs=1)
def isocontour(
    mask: GeomTuple,
    *,
    spacing: float = 2.0,
    phase: float = 0.0,
    max_dist: float = 30.0,
    mode: str = "inside",  # "inside" | "outside" | "both"
    grid_pitch: float = 0.5,
    gamma: float = 1.0,
    level_step: int = 1,
    auto_close_threshold: float = _AUTO_CLOSE_THRESHOLD_DEFAULT,
    keep_original: bool = False,
) -> GeomTuple:
    """閉曲線群から等高線（等値線）を複数レベル抽出して出力する。

    Parameters
    ----------
    mask : tuple[np.ndarray, np.ndarray]
        閉曲線群（外周＋穴）を想定する入力（coords, offsets）。開曲線は無視する。
    spacing : float, default 2.0
        レベル間隔。
    phase : float, default 0.0
        レベルの位相（`0` だと境界 `SDF=0` が含まれる）。
    max_dist : float, default 30.0
        抽出範囲（`|SDF| <= max_dist`）。
    mode : str, default "inside"
        `"inside"` は内側のみ、`"outside"` は外側のみ、`"both"` は両側を抽出する。
    grid_pitch : float, default 0.5
        SDF 評価グリッドのピッチ。
    gamma : float, default 1.0
        距離の非線形（`1.0` は線形）。`max_dist` を基準に 0..max_dist を保ったままカーブを歪める。
    level_step : int, default 1
        レベルの間引き。`n` のとき「n 本に 1 本」だけ残す（`1` は全て）。
    auto_close_threshold : float, default 1e-3
        閉曲線とみなす端点距離閾値。
    keep_original : bool, default False
        True のとき、生成結果に加えて元の入力も出力に含める。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        抽出した等値線のポリライン列（coords, offsets）。
    """
    mask_coords, mask_offsets = mask
    if mask_coords.shape[0] == 0:
        return empty_geom()

    pitch = float(grid_pitch)
    if pitch <= 0.0 or not math.isfinite(pitch):
        return empty_geom()

    spacing_f = float(spacing)
    if spacing_f <= 0.0 or not math.isfinite(spacing_f):
        return empty_geom()

    phase_f = float(phase)
    if not math.isfinite(phase_f):
        return empty_geom()

    max_d = float(max_dist)
    if not math.isfinite(max_d):
        return empty_geom()
    if max_d < 0.0:
        return empty_geom()

    mode_s = str(mode)
    if mode_s not in {"inside", "outside", "both"}:
        return empty_geom()

    auto_close = float(auto_close_threshold)
    if not math.isfinite(auto_close) or auto_close < 0.0:
        auto_close = float(_AUTO_CLOSE_THRESHOLD_DEFAULT)

    gamma_f = float(gamma)
    if not math.isfinite(gamma_f) or gamma_f <= 0.0:
        gamma_f = 1.0

    frame = PlanarFrame.from_points(mask_coords, mask_offsets)
    if not frame.is_planar(_planarity_threshold(mask_coords)):
        return empty_geom()
    coords_xy_all = frame.to_local(mask_coords)

    # 閉曲線のみを抽出（外周＋穴）。
    rings = _extract_rings_xy(coords_xy_all, mask_offsets, auto_close_threshold=auto_close)
    if not rings:
        return empty_geom()

    mins = np.min(np.stack([r0.mins for r0 in rings], axis=0), axis=0)
    maxs = np.max(np.stack([r0.maxs for r0 in rings], axis=0), axis=0)

    # SDF は「輪郭から max_dist だけ離れた範囲」まで必要なので、AABB を余裕を持って拡張する。
    margin = max(0.0, max_d) + 2.0 * pitch
    grid = GridSpec.from_bbox(
        mins,
        maxs,
        pitch=pitch,
        padding=margin,
        max_cells=MAX_GRID_POINTS,
        overflow="reject",
    )
    if grid is None:
        return empty_geom()
    xs, ys = grid.coordinates()
    x0 = grid.origin_x
    y0 = grid.origin_y
    pitch = grid.pitch

    # 1) グリッド上で SDF を評価する（EDT: 近似 / `O(Ngrid)`）。
    ring_vertices, ring_offsets, ring_mins, ring_maxs = _pack_rings(rings)
    sdf = signed_distance_grid_edt(
        xs.astype(np.float64, copy=False),
        ys.astype(np.float64, copy=False),
        ring_vertices=ring_vertices,
        ring_offsets=ring_offsets,
        ring_mins=ring_mins,
        ring_maxs=ring_maxs,
        max_distance=float(max_d),
        gamma=float(gamma_f),
        pitch=float(pitch),
    )

    # 2) `sin()` の 0 交差を取ることで複数レベルの等値線を一括抽出する。
    #    spacing_eff を大きくすると「間引き」になり、密度調整に使える。
    level_step_i = max(1, int(level_step))
    spacing_eff = float(spacing_f) * float(level_step_i)
    field = np.sin(np.pi * (sdf - float(phase_f)) / spacing_eff).astype(np.float64, copy=False)

    if mode_s == "inside":
        lo, hi = -max_d, 0.0
    elif mode_s == "outside":
        lo, hi = 0.0, max_d
    else:
        lo, hi = -max_d, max_d

    # 3) Marching Squares で線分を列挙し、端点の SDF が [lo, hi] に入るものだけ残す。
    loops_xy = marching_squares_loops(
        field,
        origin_x=float(x0),
        origin_y=float(y0),
        pitch=float(pitch),
        sample_field=sdf,
        sample_range=(float(lo), float(hi)),
    )

    out_lines: list[np.ndarray] = []
    for pts_xy in loops_xy:
        if pts_xy.shape[0] < 4:
            continue
        v3 = np.zeros((pts_xy.shape[0], 3), dtype=np.float64)
        v3[:, 0:2] = pts_xy
        # 元の 3D 平面へ戻し、出力は float32 に揃える。
        out = frame.to_world(v3).astype(np.float32, copy=False)
        out_lines.append(out)

    if bool(keep_original):
        # 生成結果に元の入力を足すオプション（デバッグ・比較用途）。
        for i in range(int(mask_offsets.size) - 1):
            s = int(mask_offsets[i])
            e = int(mask_offsets[i + 1])
            original = mask_coords[s:e]
            if original.shape[0] > 0:
                out_lines.append(original.astype(np.float32, copy=False))

    return pack_polylines(out_lines)
