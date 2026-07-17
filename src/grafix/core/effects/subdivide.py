"""各セグメントへ中点挿入を繰り返し、頂点密度を増やす effect。"""

from __future__ import annotations

import numpy as np
from numba import njit  # type: ignore[attr-defined, import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.operation_diagnostics import (
    OperationDiagnosticValue,
    emit_operation_diagnostic,
)
from grafix.core.realized_geometry import GeomTuple
from grafix.core.parameters.meta import ParamMeta

# 旧仕様（from_previous_project/subdivide.py）を踏襲した停止条件/上限。
MAX_SUBDIVISIONS = 10
MIN_SEG_LEN = 0.01
MIN_SEG_LEN_SQ = float(MIN_SEG_LEN * MIN_SEG_LEN)
MAX_TOTAL_VERTICES = 10_000_000

subdivide_meta = {
    "subdivisions": ParamMeta(kind="int", ui_min=0, ui_max=MAX_SUBDIVISIONS),
}


@effect(meta=subdivide_meta)
def subdivide(
    g: GeomTuple,
    *,
    subdivisions: int = 0,
) -> GeomTuple:
    """中点挿入で線を細分化する。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力実体ジオメトリ（coords, offsets）。
    subdivisions : int, default 0
        細分回数。0 以下は no-op。上限は 10。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        細分化後の実体ジオメトリ（coords, offsets）。

    Notes
    -----
    旧仕様踏襲:
    - 初期状態で最短セグメント長が `MIN_SEG_LEN` 未満なら、そのポリラインは細分化しない。
    - 細分化の途中で最短セグメント長が `MIN_SEG_LEN` 未満になった場合、そこで反復を停止する。
    - 出力合計頂点数が `MAX_TOTAL_VERTICES` を超えないようにガードする。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    requested_divisions = int(subdivisions)
    divisions = requested_divisions
    degradation_reasons: list[str] = []
    if divisions < 0:
        _emit_subdivide_diagnostic(
            requested=requested_divisions,
            effective=0,
            reasons=("negative subdivisions was clamped to zero",),
        )
        return coords, offsets
    if divisions == 0:
        return coords, offsets
    if divisions > MAX_SUBDIVISIONS:
        divisions = MAX_SUBDIVISIONS
        degradation_reasons.append(
            f"subdivisions was clamped to MAX_SUBDIVISIONS={MAX_SUBDIVISIONS}"
        )
    if divisions <= 0:
        return coords, offsets

    n_lines = int(offsets.size) - 1
    if n_lines <= 0:
        return coords, offsets

    base_total = int(coords.shape[0])
    if base_total > MAX_TOTAL_VERTICES:
        _emit_subdivide_diagnostic(
            requested=requested_divisions,
            effective=0,
            reasons=(
                "input already exceeded MAX_TOTAL_VERTICES; subdivision was skipped",
            ),
        )
        return coords, offsets

    # 全ポリラインを残せる共通の細分回数を、配列確保前に決める。
    selected_divisions = divisions
    counts: list[int] = []
    while selected_divisions > 0:
        counts = [
            _subdivided_vertex_count(
                coords[int(offsets[i]) : int(offsets[i + 1])],
                selected_divisions,
            )
            for i in range(n_lines)
        ]
        if sum(counts) <= MAX_TOTAL_VERTICES:
            break
        selected_divisions -= 1

    if selected_divisions <= 0:
        _emit_subdivide_diagnostic(
            requested=requested_divisions,
            effective=0,
            reasons=(*degradation_reasons, "vertex limit prevented subdivision"),
        )
        return coords, offsets

    if selected_divisions < divisions:
        degradation_reasons.append(
            "subdivisions was reduced to satisfy MAX_TOTAL_VERTICES"
        )

    if not counts:
        counts = [
            _subdivided_vertex_count(
                coords[int(offsets[i]) : int(offsets[i + 1])],
                selected_divisions,
            )
            for i in range(n_lines)
        ]

    total_vertices = sum(counts)
    if total_vertices == base_total:
        _emit_subdivide_diagnostic(
            requested=requested_divisions,
            effective=0,
            reasons=(
                *degradation_reasons,
                "minimum segment length prevented subdivision",
            ),
        )
        return coords, offsets

    applied_levels = tuple(
        sorted(
            {
                _effective_subdivision_count(
                    coords[int(offsets[i]) : int(offsets[i + 1])],
                    selected_divisions,
                )
                for i in range(n_lines)
            }
        )
    )
    if any(level < selected_divisions for level in applied_levels):
        degradation_reasons.append(
            "minimum segment length stopped one or more polylines early"
        )

    coords_out = np.empty((total_vertices, coords.shape[1]), dtype=np.float32)
    offsets_out = np.empty((n_lines + 1,), dtype=np.int32)
    offsets_out[0] = 0
    write_at = 0
    for li, count in enumerate(counts):
        start = int(offsets[li])
        end = int(offsets[li + 1])
        line = _subdivide_core(coords[start:end], selected_divisions, count)
        next_at = write_at + count
        coords_out[write_at:next_at] = line
        offsets_out[li + 1] = next_at
        write_at = next_at

    if degradation_reasons:
        effective: OperationDiagnosticValue = (
            applied_levels[0] if len(applied_levels) == 1 else applied_levels
        )
        _emit_subdivide_diagnostic(
            requested=requested_divisions,
            effective=effective,
            reasons=tuple(degradation_reasons),
        )
    return coords_out, offsets_out


def _emit_subdivide_diagnostic(
    *,
    requested: int,
    effective: OperationDiagnosticValue,
    reasons: tuple[str, ...],
) -> None:
    unique_reasons = tuple(dict.fromkeys(reason for reason in reasons if reason))
    emit_operation_diagnostic(
        op="subdivide",
        original_value=int(requested),
        effective_value=effective,
        reason="; ".join(unique_reasons),
        severity="warning",
    )


def _subdivided_vertex_count(vertices: np.ndarray, subdivisions: int) -> int:
    """配列を増やさず、``_subdivide_core`` の出力頂点数を返す。"""

    n = int(vertices.shape[0])
    if n < 2 or subdivisions <= 0:
        return n

    for _ in range(_effective_subdivision_count(vertices, subdivisions)):
        n = 2 * n - 1
    return n


def _effective_subdivision_count(vertices: np.ndarray, subdivisions: int) -> int:
    """最短segment制約を含め、実際に適用される反復数を返す。"""

    if int(vertices.shape[0]) < 2 or subdivisions <= 0:
        return 0
    delta = vertices[1:] - vertices[:-1]
    distance_sq = np.einsum("ij,ij->i", delta, delta)
    min_distance_sq = float(np.min(distance_sq))
    if min_distance_sq < MIN_SEG_LEN_SQ:
        return 0

    applied = 0
    for _ in range(min(int(subdivisions), MAX_SUBDIVISIONS)):
        applied += 1
        min_distance_sq *= 0.25
        if min_distance_sq < MIN_SEG_LEN_SQ:
            break
    return applied


@njit(fastmath=True, cache=True)
def _subdivide_core(vertices: np.ndarray, subdivisions: int, max_vertices: int) -> np.ndarray:
    """単一頂点配列の細分化処理（旧仕様踏襲の Numba 経路）。"""
    n0 = vertices.shape[0]
    if n0 < 2 or subdivisions <= 0:
        return vertices

    d0 = vertices[1:] - vertices[:-1]
    if d0.shape[0] > 0:
        dsq0 = d0[:, 0] * d0[:, 0] + d0[:, 1] * d0[:, 1] + d0[:, 2] * d0[:, 2]
        if np.min(dsq0) < MIN_SEG_LEN_SQ:  # type: ignore[operator]
            return vertices

    subdivisions = subdivisions if subdivisions <= MAX_SUBDIVISIONS else MAX_SUBDIVISIONS

    result = vertices.copy()
    for _ in range(subdivisions):
        n = result.shape[0]
        if n < 2:
            break

        new_n = 2 * n - 1
        if max_vertices > 0 and new_n > max_vertices:
            break

        new_vertices = np.empty((new_n, result.shape[1]), dtype=result.dtype)
        new_vertices[::2] = result
        new_vertices[1::2] = (result[:-1] + result[1:]) / 2
        result = new_vertices

        d = result[1:] - result[:-1]
        if d.shape[0] > 0:
            dsq = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1] + d[:, 2] * d[:, 2]
            if np.min(dsq) < MIN_SEG_LEN_SQ:  # type: ignore[operator]
                break

    return result
