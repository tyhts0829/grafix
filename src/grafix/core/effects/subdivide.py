"""各セグメントへ中点挿入を繰り返し、頂点密度を増やす effect。"""

from __future__ import annotations

import numpy as np
from numba import njit  # type: ignore[attr-defined, import-untyped]

from grafix.core.operation_authoring import effect
from grafix.core.operation_diagnostics import (
    OperationDiagnosticValue,
    emit_operation_diagnostic,
)
from grafix.core.realized_geometry import GeomTuple
from grafix.core.parameters.meta import ParamMeta

# 細分化の停止条件と出力上限。
MAX_SUBDIVISIONS = 10
MIN_SEG_LEN = 0.01
MIN_SEG_LEN_SQ = float(MIN_SEG_LEN * MIN_SEG_LEN)
MAX_TOTAL_VERTICES = 10_000_000
_BATCH_SAFE_COORD_ABS_MAX = np.float32(
    np.sqrt(np.finfo(np.float32).max / 16.0)
)

subdivide_meta = {
    "subdivisions": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=MAX_SUBDIVISIONS,
        description="各線分へ中点を挿入して細分する反復回数。",
    ),
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
        細分回数。0 は no-op。10 を超える値はクランプする。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        細分化後の実体ジオメトリ（coords, offsets）。

    Raises
    ------
    ValueError
        `subdivisions` が負の場合。

    Notes
    -----
    - 初期状態で最短セグメント長が `MIN_SEG_LEN` 未満なら、そのポリラインは細分化しない。
    - 細分化の途中で最短セグメント長が `MIN_SEG_LEN` 未満になった場合、そこで反復を停止する。
    - 出力合計頂点数が `MAX_TOTAL_VERTICES` を超えないようにガードする。
    """
    if subdivisions < 0:
        raise ValueError("subdivide の subdivisions は 0 以上である必要がある")

    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    requested_divisions = subdivisions
    divisions = requested_divisions
    degradation_reasons: list[str] = []
    if divisions == 0:
        return coords, offsets
    if divisions > MAX_SUBDIVISIONS:
        divisions = MAX_SUBDIVISIONS
        degradation_reasons.append(
            f"subdivisions was clamped to MAX_SUBDIVISIONS={MAX_SUBDIVISIONS}"
        )
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

    use_batch = _subdivide_batch_values_are_safe(coords)
    if use_batch:
        # canonical finite geometry は全 polyline を一括解析する。
        selected_divisions, counts, total_vertices = _analyze_subdivision_plan(
            coords,
            offsets,
            divisions,
            MAX_TOTAL_VERTICES,
        )
    if not use_batch:
        # 極端な有限座標や NumPy error policy では strict NumPy 経路を使う。
        selected_divisions = divisions
        count_list: list[int] = []
        while selected_divisions > 0:
            count_list = [
                _subdivided_vertex_count(
                    coords[int(offsets[i]) : int(offsets[i + 1])],
                    selected_divisions,
                )
                for i in range(n_lines)
            ]
            if sum(count_list) <= MAX_TOTAL_VERTICES:
                break
            selected_divisions -= 1
        counts = np.asarray(count_list, dtype=np.int64)
        total_vertices = int(sum(count_list))

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

    total_vertices = int(total_vertices)
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

    coords_out = np.empty((total_vertices, 3), dtype=np.float32)
    offsets_out = np.empty((n_lines + 1,), dtype=np.int32)
    if use_batch:
        write_at, applied_levels_mask = _subdivide_batch(
            coords,
            offsets,
            selected_divisions,
            counts,
            coords_out,
            offsets_out,
        )
        applied_levels = tuple(
            level
            for level in range(selected_divisions + 1)
            if applied_levels_mask & (1 << level)
        )
    else:
        offsets_out[0] = 0
        applied_levels_list: list[int] = []
        write_at = 0
        for line_index, capacity in enumerate(counts):
            start = int(offsets[line_index])
            end = int(offsets[line_index + 1])
            line, applied_level = _subdivide_core(
                coords[start:end],
                selected_divisions,
                int(capacity),
            )
            applied_levels_list.append(applied_level)
            next_at = write_at + int(line.shape[0])
            coords_out[write_at:next_at] = line
            offsets_out[line_index + 1] = next_at
            write_at = next_at
        applied_levels = tuple(sorted(set(applied_levels_list)))

    if write_at < total_vertices:
        coords_out = coords_out[:write_at].copy()

    if any(level < selected_divisions for level in applied_levels):
        degradation_reasons.append(
            "minimum segment length stopped one or more polylines early"
        )

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
        original_value=requested,
        effective_value=effective,
        reason="; ".join(unique_reasons),
        severity="warning",
    )


def _subdivide_batch_values_are_safe(coords: np.ndarray) -> bool:
    """一括 kernel で strict NumPy 経路と同じ演算を保てる値域か返す。"""

    if np.geterr()["under"] != "ignore":
        return False
    coords_abs_max = np.max(np.abs(coords))
    return bool(coords_abs_max <= _BATCH_SAFE_COORD_ABS_MAX)


def _subdivided_vertex_count(vertices: np.ndarray, subdivisions: int) -> int:
    """strict NumPy 経路の出力頂点数を配列確保なしで返す。"""

    n = int(vertices.shape[0])
    if n < 2 or subdivisions <= 0:
        return n

    for _ in range(_effective_subdivision_count(vertices, subdivisions)):
        n = 2 * n - 1
    return n


def _effective_subdivision_count(vertices: np.ndarray, subdivisions: int) -> int:
    """入力 dtype の最短 segment 制約を含む反復数を返す。"""

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


@njit(cache=True)
def _analyze_subdivision_plan(
    coords: np.ndarray,
    offsets: np.ndarray,
    subdivisions: int,
    max_total_vertices: int,
) -> tuple[int, np.ndarray, int]:
    """全 polyline の解析上の反復数と capacity を一括で求める。"""

    n_lines = offsets.size - 1
    counts = np.empty((n_lines,), dtype=np.int64)

    # NumPy count 経路と同じ strict な浮動小数点演算にする。
    for line_index in range(n_lines):
        start = int(offsets[line_index])
        end = int(offsets[line_index + 1])
        n_vertices = end - start
        if n_vertices < 2:
            counts[line_index] = 0
            continue

        dx = coords[start + 1, 0] - coords[start, 0]
        dy = coords[start + 1, 1] - coords[start, 1]
        dz = coords[start + 1, 2] - coords[start, 2]
        min_distance_sq = dx * dx + dy * dy + dz * dz
        for vertex_index in range(start + 1, end - 1):
            dx = coords[vertex_index + 1, 0] - coords[vertex_index, 0]
            dy = coords[vertex_index + 1, 1] - coords[vertex_index, 1]
            dz = coords[vertex_index + 1, 2] - coords[vertex_index, 2]
            distance_sq = dx * dx + dy * dy + dz * dz
            if distance_sq < min_distance_sq:
                min_distance_sq = distance_sq

        scaled_min_distance_sq = np.float64(min_distance_sq)
        if scaled_min_distance_sq < MIN_SEG_LEN_SQ:
            counts[line_index] = 0
            continue

        applied_levels = 0
        for _ in range(subdivisions):
            applied_levels += 1
            scaled_min_distance_sq *= 0.25
            if scaled_min_distance_sq < MIN_SEG_LEN_SQ:
                break
        counts[line_index] = applied_levels

    selected_divisions = subdivisions
    total_vertices = 0
    while selected_divisions > 0:
        total_vertices = 0
        for line_index in range(n_lines):
            n_vertices = int(offsets[line_index + 1]) - int(offsets[line_index])
            levels = int(counts[line_index])
            if levels > selected_divisions:
                levels = selected_divisions
            count = n_vertices
            for _ in range(levels):
                count = 2 * count - 1
            total_vertices += count
        if total_vertices <= max_total_vertices:
            break
        selected_divisions -= 1

    if selected_divisions > 0:
        for line_index in range(n_lines):
            n_vertices = int(offsets[line_index + 1]) - int(offsets[line_index])
            levels = int(counts[line_index])
            if levels > selected_divisions:
                levels = selected_divisions
            count = n_vertices
            for _ in range(levels):
                count = 2 * count - 1
            counts[line_index] = count

    return selected_divisions, counts, total_vertices


@njit(fastmath=True, cache=True)
def _subdivide_core(
    vertices: np.ndarray,
    subdivisions: int,
    max_vertices: int,
) -> tuple[np.ndarray, int]:
    """極端な有限値を strict NumPy の演算順で細分化する。"""

    n0 = vertices.shape[0]
    if n0 < 2 or subdivisions <= 0:
        return vertices, 0

    d0 = vertices[1:] - vertices[:-1]
    if d0.shape[0] > 0:
        dsq0 = d0[:, 0] * d0[:, 0] + d0[:, 1] * d0[:, 1] + d0[:, 2] * d0[:, 2]
        if np.min(dsq0) < MIN_SEG_LEN_SQ:  # type: ignore[operator]
            return vertices, 0

    subdivisions = subdivisions if subdivisions <= MAX_SUBDIVISIONS else MAX_SUBDIVISIONS

    result = vertices.copy()
    applied_levels = 0
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
        applied_levels += 1

        d = result[1:] - result[:-1]
        if d.shape[0] > 0:
            dsq = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1] + d[:, 2] * d[:, 2]
            if np.min(dsq) < MIN_SEG_LEN_SQ:  # type: ignore[operator]
                break

    return result, applied_levels


@njit(fastmath=True, cache=True)
def _subdivide_batch(
    coords: np.ndarray,
    offsets: np.ndarray,
    subdivisions: int,
    capacities: np.ndarray,
    coords_out: np.ndarray,
    offsets_out: np.ndarray,
) -> tuple[int, int]:
    """確保済み capacity 内で全 polyline を一括細分化する。"""

    n_lines = offsets.size - 1
    n_dims = coords.shape[1]
    write_at = 0
    reserved_at = 0
    applied_levels_mask = 0
    offsets_out[0] = 0

    for line_index in range(n_lines):
        start = int(offsets[line_index])
        end = int(offsets[line_index + 1])
        n_vertices = end - start
        capacity = int(capacities[line_index])

        for vertex_index in range(n_vertices):
            for axis in range(n_dims):
                coords_out[reserved_at + vertex_index, axis] = coords[
                    start + vertex_index, axis
                ]

        current_count = n_vertices
        applied_levels = 0
        can_subdivide = n_vertices >= 2
        if can_subdivide:
            dx = coords[start + 1, 0] - coords[start, 0]
            dy = coords[start + 1, 1] - coords[start, 1]
            dz = coords[start + 1, 2] - coords[start, 2]
            min_distance_sq = dx * dx + dy * dy + dz * dz
            for vertex_index in range(start + 1, end - 1):
                dx = coords[vertex_index + 1, 0] - coords[vertex_index, 0]
                dy = coords[vertex_index + 1, 1] - coords[vertex_index, 1]
                dz = coords[vertex_index + 1, 2] - coords[vertex_index, 2]
                distance_sq = dx * dx + dy * dy + dz * dz
                if distance_sq < min_distance_sq:
                    min_distance_sq = distance_sq
            can_subdivide = not min_distance_sq < MIN_SEG_LEN_SQ

        if can_subdivide:
            for _ in range(subdivisions):
                new_count = 2 * current_count - 1
                if capacity > 0 and new_count > capacity:
                    break

                # 元頂点を壊さないよう、末尾から同じ capacity 内へ展開する。
                for axis in range(n_dims):
                    coords_out[
                        reserved_at + 2 * (current_count - 1), axis
                    ] = coords_out[reserved_at + current_count - 1, axis]
                for vertex_index in range(current_count - 2, -1, -1):
                    for axis in range(n_dims):
                        left = coords_out[reserved_at + vertex_index, axis]
                        right = coords_out[reserved_at + vertex_index + 1, axis]
                        coords_out[reserved_at + 2 * vertex_index + 1, axis] = (
                            left + right
                        ) / 2
                        coords_out[reserved_at + 2 * vertex_index, axis] = left

                current_count = new_count
                applied_levels += 1

                dx = coords_out[reserved_at + 1, 0] - coords_out[reserved_at, 0]
                dy = coords_out[reserved_at + 1, 1] - coords_out[reserved_at, 1]
                dz = coords_out[reserved_at + 1, 2] - coords_out[reserved_at, 2]
                min_distance_sq = dx * dx + dy * dy + dz * dz
                for vertex_index in range(1, current_count - 1):
                    dx = (
                        coords_out[reserved_at + vertex_index + 1, 0]
                        - coords_out[reserved_at + vertex_index, 0]
                    )
                    dy = (
                        coords_out[reserved_at + vertex_index + 1, 1]
                        - coords_out[reserved_at + vertex_index, 1]
                    )
                    dz = (
                        coords_out[reserved_at + vertex_index + 1, 2]
                        - coords_out[reserved_at + vertex_index, 2]
                    )
                    distance_sq = dx * dx + dy * dy + dz * dz
                    if distance_sq < min_distance_sq:
                        min_distance_sq = distance_sq
                if min_distance_sq < MIN_SEG_LEN_SQ:
                    break

        applied_levels_mask |= 1 << applied_levels

        # 解析 capacity と float32 実停止がずれた分を前方へ詰める。
        if write_at != reserved_at:
            for vertex_index in range(current_count):
                for axis in range(n_dims):
                    coords_out[write_at + vertex_index, axis] = coords_out[
                        reserved_at + vertex_index, axis
                    ]
        write_at += current_count
        offsets_out[line_index + 1] = write_at
        reserved_at += capacity

    return write_at, applied_levels_mask
