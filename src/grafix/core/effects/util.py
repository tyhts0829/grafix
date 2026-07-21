from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numba import njit  # type: ignore[attr-defined, import-untyped]

from grafix.core.operation_diagnostics import emit_operation_diagnostic

DEFAULT_MAX_GRID_CELLS = 4_000_000
RESAMPLE_CLOSED_DISTANCE_EPS = 0.01
_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

_RESAMPLE_COPY = 0
_RESAMPLE_OPEN = 1
_RESAMPLE_CLOSED = 2


def round_half_away_from_zero(values: np.ndarray) -> np.ndarray:
    """0.5 境界を絶対値方向へ丸める。"""

    return np.sign(values) * np.floor(np.abs(values) + 0.5)


@njit(cache=True, fastmath=True, inline="always")  # type: ignore[misc]
def reflect_index(index: int, size: int) -> int:
    """端点を重ねる reflect 境界条件の配列 index を返す。"""

    reflected = int(index)
    count = int(size)
    if count <= 1:
        return 0
    while reflected < 0 or reflected >= count:
        if reflected < 0:
            reflected = -reflected
        elif reflected >= count:
            reflected = 2 * count - 2 - reflected
    return int(reflected)


def empty_geom() -> tuple[np.ndarray, np.ndarray]:
    """空のpacked geometryを標準dtypeで返す。"""

    return np.zeros((0, 3), dtype=np.float32), np.zeros((1,), dtype=np.int32)


def pack_polylines(lines: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """shape ``(N,3)`` のpolyline列をfloat32/int32のpacked geometryへ詰める。"""

    if not lines:
        return empty_geom()
    arrays = tuple(np.asarray(line) for line in lines)
    if any(array.ndim != 2 or array.shape[1] != 3 for array in arrays):
        raise ValueError("polyline は shape (N,3) の配列である必要がある")

    counts = np.fromiter((array.shape[0] for array in arrays), dtype=np.int64)
    offsets64 = np.empty((len(arrays) + 1,), dtype=np.int64)
    offsets64[0] = 0
    np.cumsum(counts, out=offsets64[1:])
    if int(offsets64[-1]) > int(np.iinfo(np.int32).max):
        raise ValueError("packed geometry の頂点数が int32 上限を超えている")

    coords = np.empty((int(offsets64[-1]), 3), dtype=np.float32)
    for index, array in enumerate(arrays):
        start = int(offsets64[index])
        stop = int(offsets64[index + 1])
        coords[start:stop] = array
    return coords, offsets64.astype(np.int32)


@dataclass(frozen=True, slots=True)
class PlanarRing:
    """平面化済みの閉曲線と、その二次元境界を保持する。

    ``vertices`` は先頭点と末尾点が一致する ``(N, 2)`` float64 配列、
    ``mins`` と ``maxs`` はその ``(2,)`` float64 境界である。
    """

    vertices: np.ndarray
    mins: np.ndarray
    maxs: np.ndarray


def planarity_threshold(points: np.ndarray) -> float:
    """点群の大きさに応じた平面性判定の許容値を返す。"""

    if points.size == 0:
        return float(_PLANAR_EPS_ABS)
    p = points.astype(np.float64, copy=False)
    mins = np.min(p, axis=0)
    maxs = np.max(p, axis=0)
    diag = float(np.linalg.norm(maxs - mins))
    return max(float(_PLANAR_EPS_ABS), float(_PLANAR_EPS_REL) * diag)


def close_curve(points: np.ndarray, threshold: float) -> np.ndarray:
    """端点間の距離が閾値以内なら、終点を始点へ揃える。"""

    if points.shape[0] < 2:
        return points
    dist = float(np.linalg.norm(points[0] - points[-1]))
    if dist <= float(threshold):
        return np.concatenate([points[:-1], points[0:1]], axis=0)
    return points


def extract_planar_rings(
    coords: np.ndarray,
    offsets: np.ndarray,
    *,
    auto_close_threshold: float,
) -> list[PlanarRing]:
    """平面化済みのpacked geometryから閉曲線だけを入力順に抽出する。"""

    rings: list[PlanarRing] = []
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        poly3 = coords[s:e]
        if poly3.shape[0] < 3:
            continue

        closed3 = close_curve(poly3, float(auto_close_threshold))
        if closed3.shape[0] < 4:
            continue
        if not np.allclose(closed3[0], closed3[-1], rtol=0.0, atol=1e-12):
            continue

        vertices = closed3[:, :2].astype(np.float64, copy=False)
        rings.append(
            PlanarRing(
                vertices=vertices,
                mins=np.min(vertices, axis=0),
                maxs=np.max(vertices, axis=0),
            )
        )
    return rings


def pack_planar_rings(
    rings: list[PlanarRing],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """閉曲線列をNumbaへ渡す連結バッファへ入力順に詰める。"""

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
        vertices = ring.vertices.astype(np.float64, copy=False)
        count = int(vertices.shape[0])
        ring_vertices[cursor : cursor + count] = vertices
        cursor += count
        ring_offsets[i + 1] = np.int32(cursor)
        ring_mins[i] = ring.mins
        ring_maxs[i] = ring.maxs

    return ring_vertices, ring_offsets, ring_mins, ring_maxs


def _grid_axis_count(*, span: float, pitch: float, limit: int) -> int:
    ratio = float(span) / float(pitch)
    if not math.isfinite(ratio) or ratio >= float(limit):
        return int(limit) + 1
    return max(2, int(math.ceil(ratio)) + 1)


@dataclass(frozen=True, slots=True)
class GridSpec:
    """確保前に上限を検証済みの等間隔2Dグリッド仕様。"""

    origin_x: float
    origin_y: float
    pitch: float
    nx: int
    ny: int
    requested_pitch: float

    @property
    def cell_count(self) -> int:
        """グリッド点数を返す。"""

        return int(self.nx) * int(self.ny)

    @property
    def coarsened(self) -> bool:
        """上限へ収めるためpitchを拡大したかを返す。"""

        return self.pitch > self.requested_pitch

    def coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        """X軸・Y軸の座標配列を確保して返す。"""

        xs = self.origin_x + self.pitch * np.arange(self.nx, dtype=np.float64)
        ys = self.origin_y + self.pitch * np.arange(self.ny, dtype=np.float64)
        return xs, ys

    @classmethod
    def from_bbox(
        cls,
        mins: Sequence[float] | np.ndarray,
        maxs: Sequence[float] | np.ndarray,
        *,
        pitch: float,
        padding: float = 0.0,
        max_cells: int = DEFAULT_MAX_GRID_CELLS,
        overflow: Literal["reject", "coarsen"] = "reject",
    ) -> GridSpec | None:
        """bboxから上限内のgridを計画し、不正またはreject超過ならNoneを返す。"""

        if overflow not in {"reject", "coarsen"}:
            raise ValueError(f"未知の overflow policy: {overflow!r}")

        requested_pitch = float(pitch)
        pad = float(padding)
        limit = int(max_cells)
        if (
            not math.isfinite(requested_pitch)
            or requested_pitch <= 0.0
            or not math.isfinite(pad)
            or pad < 0.0
            or limit < 4
        ):
            emit_operation_diagnostic(
                op="GridSpec.from_bbox",
                original_value=(requested_pitch, pad, limit, overflow),
                effective_value=None,
                reason="invalid grid pitch, padding, or cell limit was rejected",
                severity="warning",
            )
            return None

        min_x = float(mins[0])
        min_y = float(mins[1])
        max_x = float(maxs[0])
        max_y = float(maxs[1])
        if not all(math.isfinite(v) for v in (min_x, min_y, max_x, max_y)):
            emit_operation_diagnostic(
                op="GridSpec.from_bbox",
                original_value=(requested_pitch, pad, limit, overflow),
                effective_value=None,
                reason="non-finite bounding box was rejected",
                severity="warning",
            )
            return None
        if max_x < min_x or max_y < min_y:
            emit_operation_diagnostic(
                op="GridSpec.from_bbox",
                original_value=(requested_pitch, pad, limit, overflow),
                effective_value=None,
                reason="inverted bounding box was rejected",
                severity="warning",
            )
            return None

        origin_x = min_x - pad
        origin_y = min_y - pad
        span_x = max_x - min_x + 2.0 * pad
        span_y = max_y - min_y + 2.0 * pad
        if (
            not all(math.isfinite(v) for v in (origin_x, origin_y, span_x, span_y))
            or span_x <= 0.0
            or span_y <= 0.0
        ):
            emit_operation_diagnostic(
                op="GridSpec.from_bbox",
                original_value=(requested_pitch, pad, limit, overflow),
                effective_value=None,
                reason="degenerate grid bounds were rejected",
                severity="warning",
            )
            return None

        def shape_for(candidate_pitch: float) -> tuple[int, int, int]:
            nx = _grid_axis_count(span=span_x, pitch=candidate_pitch, limit=limit)
            ny = _grid_axis_count(span=span_y, pitch=candidate_pitch, limit=limit)
            return nx, ny, int(nx) * int(ny)

        effective_pitch = requested_pitch
        nx, ny, cells = shape_for(effective_pitch)
        if cells > limit:
            if overflow == "reject":
                emit_operation_diagnostic(
                    op="GridSpec.from_bbox",
                    original_value=(requested_pitch, cells, limit, overflow),
                    effective_value=None,
                    reason="requested grid exceeded the cell limit and was rejected",
                    severity="warning",
                )
                return None

            low = effective_pitch
            high = effective_pitch
            while True:
                high *= 2.0
                if not math.isfinite(high):
                    emit_operation_diagnostic(
                        op="GridSpec.from_bbox",
                        original_value=(requested_pitch, cells, limit, overflow),
                        effective_value=None,
                        reason="grid could not be coarsened to a finite pitch",
                        severity="error",
                    )
                    return None
                nx_high, ny_high, cells_high = shape_for(high)
                if cells_high <= limit:
                    break

            for _ in range(64):
                middle = low + 0.5 * (high - low)
                if middle == low or middle == high:
                    break
                _nx_mid, _ny_mid, cells_mid = shape_for(middle)
                if cells_mid > limit:
                    low = middle
                else:
                    high = middle

            effective_pitch = high
            nx, ny, cells = shape_for(effective_pitch)
            if cells > limit:
                emit_operation_diagnostic(
                    op="GridSpec.from_bbox",
                    original_value=(requested_pitch, cells, limit, overflow),
                    effective_value=None,
                    reason="grid coarsening did not satisfy the cell limit",
                    severity="error",
                )
                return None

            emit_operation_diagnostic(
                op="GridSpec.from_bbox",
                original_value=requested_pitch,
                effective_value=effective_pitch,
                reason="grid pitch was coarsened to satisfy the cell limit",
                severity="warning",
            )

        return cls(
            origin_x=float(origin_x),
            origin_y=float(origin_y),
            pitch=float(effective_pitch),
            nx=int(nx),
            ny=int(ny),
            requested_pitch=float(requested_pitch),
        )


def _readonly_vector(value: np.ndarray, *, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64).reshape(shape).copy()
    array.setflags(write=False)
    return array


def _invalid_planar_frame(*, status: str, rank: int, origin: np.ndarray | None = None) -> PlanarFrame:
    origin_array = np.zeros((3,), dtype=np.float64) if origin is None else origin
    invalid = np.full((3, 3), np.nan, dtype=np.float64)
    return PlanarFrame(
        origin=origin_array,
        basis=invalid,
        inverse=invalid,
        residual=float("inf"),
        rank=int(rank),
        status=status,
    )


def _frame_close_tolerance(points: np.ndarray) -> float:
    anchor = points[0]
    extent = float(np.max(np.abs(points - anchor))) if points.shape[0] else 0.0
    magnitude = float(np.max(np.abs(points))) if points.shape[0] else 0.0
    epsilon = float(np.finfo(np.float64).eps)
    tiny = float(np.finfo(np.float64).tiny)
    rounding = epsilon * max(magnitude, extent, tiny) * 32.0
    return max(extent * 1e-12, rounding)


def _clean_frame_lines(
    points: np.ndarray, offsets: np.ndarray | None, *, tolerance: float
) -> list[np.ndarray]:
    ranges: tuple[tuple[int, int], ...]
    if offsets is None:
        ranges = ((0, int(points.shape[0])),)
    else:
        ranges = tuple(
            (int(offsets[index]), int(offsets[index + 1]))
            for index in range(int(offsets.size) - 1)
        )

    lines: list[np.ndarray] = []
    tolerance_sq = float(tolerance) * float(tolerance)
    for start, stop in ranges:
        line = points[start:stop]
        if line.shape[0] == 0:
            continue
        if line.shape[0] > 1:
            delta = np.diff(line, axis=0)
            keep = np.ones((line.shape[0],), dtype=bool)
            keep[1:] = np.sum(delta * delta, axis=1) > tolerance_sq
            line = line[keep]
        if line.shape[0] > 1:
            close_delta = line[-1] - line[0]
            if float(np.dot(close_delta, close_delta)) <= tolerance_sq:
                line = line[:-1]
        if line.shape[0] > 0:
            lines.append(line)
    return lines


def _packed_clean_frame_offsets(
    points: np.ndarray,
    offsets: np.ndarray | None,
    *,
    tolerance: float,
) -> np.ndarray | None:
    """clean な packed 入力なら、追加の line 配列を作らず使える offsets を返す。"""

    point_count = int(points.shape[0])
    if offsets is None:
        packed_offsets = np.asarray([0, point_count], dtype=np.intp)
    else:
        source_offsets = np.asarray(offsets)
        if (
            source_offsets.ndim != 1
            or source_offsets.size < 2
            or not np.issubdtype(source_offsets.dtype, np.integer)
        ):
            return None
        packed_offsets = source_offsets.astype(np.intp, copy=False)

    if (
        int(packed_offsets[0]) != 0
        or int(packed_offsets[-1]) != point_count
    ):
        return None
    counts = np.diff(packed_offsets)
    if bool(np.any(counts <= 0)):
        return None

    tolerance_sq = float(tolerance) * float(tolerance)
    multi_point = counts > 1
    if bool(np.any(multi_point)):
        starts = packed_offsets[:-1][multi_point]
        stops = packed_offsets[1:][multi_point]
        close_delta = points[stops - 1] - points[starts]
        close_distance_sq = np.sum(close_delta * close_delta, axis=1)
        if bool(np.any(close_distance_sq <= tolerance_sq)):
            return None

    if point_count > 1:
        delta = points[1:] - points[:-1]
        distance_sq = np.sum(delta * delta, axis=1)
        boundaries = packed_offsets[1:-1] - 1
        if boundaries.size:
            distance_sq[boundaries] = np.inf
        if bool(np.any(distance_sq <= tolerance_sq)):
            return None
    return packed_offsets


def _newell_vector(points: np.ndarray, *, scale: float) -> np.ndarray:
    if points.shape[0] < 3:
        return np.zeros((3,), dtype=np.float64)
    local = (points - points[0]) / float(scale)
    following = np.roll(local, -1, axis=0)
    return np.sum(np.cross(local, following), axis=0).astype(np.float64, copy=False)


def _packed_newell_statistics(
    points: np.ndarray,
    offsets: np.ndarray,
    *,
    scale: float,
) -> tuple[np.ndarray, int, np.ndarray]:
    """packed line 群の Newell 合計・最大面積 line・そのベクトルを返す。"""

    line_count = int(offsets.size) - 1
    if line_count <= 64:
        total = np.zeros((3,), dtype=np.float64)
        reference_index = 0
        reference = np.zeros((3,), dtype=np.float64)
        reference_area = -1.0
        for index in range(line_count):
            start = int(offsets[index])
            stop = int(offsets[index + 1])
            newell = _newell_vector(points[start:stop], scale=scale)
            area = float(np.linalg.norm(newell))
            total += newell
            if area > reference_area:
                reference_index = index
                reference = newell
                reference_area = area
        return total, reference_index, reference

    counts = np.diff(offsets)
    if not bool(np.any(counts >= 3)):
        return (
            np.zeros((3,), dtype=np.float64),
            0,
            np.zeros((3,), dtype=np.float64),
        )

    anchors = np.repeat(points[offsets[:-1]], counts, axis=0)
    local = (points - anchors) / float(scale)
    contributions = np.zeros_like(local)
    contributions[:-1] = np.cross(local[:-1], local[1:])
    contributions[offsets[1:] - 1] = 0.0
    newells = np.add.reduceat(contributions, offsets[:-1], axis=0)
    newells[counts < 3] = 0.0

    areas = np.linalg.norm(newells, axis=1)
    reference_index = int(np.argmax(areas))
    return (
        np.sum(newells, axis=0).astype(np.float64, copy=False),
        reference_index,
        newells[reference_index],
    )


def _first_projected_packed_edge(
    points: np.ndarray,
    offsets: np.ndarray,
    *,
    normal: np.ndarray,
    reference_index: int,
    tolerance: float,
) -> np.ndarray | None:
    """reference line 優先のまま、packed buffer から最初の有効 edge を探す。"""

    line_count = int(offsets.size) - 1
    for order_index in range(line_count):
        line_index = (
            int(reference_index)
            if order_index == 0
            else order_index - 1
            if order_index <= int(reference_index)
            else order_index
        )
        start = int(offsets[line_index])
        stop = int(offsets[line_index + 1])
        for point_index in range(start, stop - 1):
            edge = points[point_index + 1] - points[point_index]
            projected = edge - float(np.dot(edge, normal)) * normal
            length = float(np.linalg.norm(projected))
            if length > float(tolerance):
                return projected / length
    return None


def _canonicalize_direction(vector: np.ndarray) -> np.ndarray:
    result = np.asarray(vector, dtype=np.float64)
    index = int(np.argmax(np.abs(result)))
    if float(result[index]) < 0.0:
        result = -result
    return result


def _stable_argmax(values: np.ndarray) -> int:
    """丸め誤差内の同率候補を小さい index 優先で選ぶ。"""

    array = np.asarray(values, dtype=np.float64)
    maximum = float(np.max(array))
    tolerance = max(
        1e-15,
        abs(maximum) * 1e-12,
        float(np.finfo(np.float64).eps) * 64.0,
    )
    for index, value in enumerate(array):
        if maximum - float(value) <= tolerance:
            return int(index)
    return int(np.argmax(array))


def _stable_canonicalize_direction(vector: np.ndarray) -> np.ndarray:
    """最大成分が丸め同率でも符号を決定的に固定する。"""

    result = np.asarray(vector, dtype=np.float64)
    index = _stable_argmax(np.abs(result))
    if float(result[index]) < 0.0:
        result = -result
    return result


def _cross3(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """3要素ベクトル同士の外積を返す。"""

    return np.asarray(
        (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        ),
        dtype=np.float64,
    )


@dataclass(frozen=True, slots=True)
class PlanarFrame:
    """全点から推定した、world座標と局所XY平面を結ぶ直交frame。"""

    origin: np.ndarray
    basis: np.ndarray
    inverse: np.ndarray
    residual: float
    rank: int
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", _readonly_vector(self.origin, shape=(3,)))
        object.__setattr__(self, "basis", _readonly_vector(self.basis, shape=(3, 3)))
        object.__setattr__(self, "inverse", _readonly_vector(self.inverse, shape=(3, 3)))

    @property
    def valid(self) -> bool:
        """2D平面を定義できるrankならTrue。"""

        return self.rank >= 2 and self.status in {"planar", "spatial"}

    @property
    def normal(self) -> np.ndarray:
        """world座標系の単位法線を返す。"""

        return self.basis[2]

    def is_planar(self, tolerance: float) -> bool:
        """有効かつ最大平面残差がtolerance以下ならTrue。"""

        threshold = float(tolerance)
        return self.valid and math.isfinite(threshold) and threshold >= 0.0 and self.residual <= threshold

    def to_local(self, points: np.ndarray) -> np.ndarray:
        """world座標をframeの局所座標へ変換する。"""

        if not self.valid:
            raise ValueError(f"無効な PlanarFrame は変換に使えない: {self.status}")
        values = np.asarray(points, dtype=np.float64)
        if values.shape[-1] != 3:
            raise ValueError("points は末尾shapeが3である必要がある")
        return (values - self.origin) @ self.inverse

    def to_world(self, points: np.ndarray) -> np.ndarray:
        """frameの局所座標をworld座標へ戻す。"""

        if not self.valid:
            raise ValueError(f"無効な PlanarFrame は変換に使えない: {self.status}")
        values = np.asarray(points, dtype=np.float64)
        if values.shape[-1] != 3:
            raise ValueError("points は末尾shapeが3である必要がある")
        return values @ self.basis + self.origin

    def project(self, points: np.ndarray) -> np.ndarray:
        """world座標をframeの局所XYへ射影する。"""

        if not self.valid:
            raise ValueError(f"無効な PlanarFrame は変換に使えない: {self.status}")
        values = np.asarray(points, dtype=np.float64)
        if values.shape[-1] != 3:
            raise ValueError("points は末尾shapeが3である必要がある")
        return (values - self.origin) @ self.inverse[:, :2]

    def lift(self, points: np.ndarray) -> np.ndarray:
        """frameの局所XY座標をworld座標へ持ち上げる。"""

        if not self.valid:
            raise ValueError(f"無効な PlanarFrame は変換に使えない: {self.status}")
        values = np.asarray(points, dtype=np.float64)
        if values.shape[-1] != 2:
            raise ValueError("points は末尾shapeが2である必要がある")
        return values @ self.basis[:2] + self.origin

    @classmethod
    def from_points(
        cls, points: np.ndarray, offsets: np.ndarray | None = None
    ) -> PlanarFrame:
        """全点PCAとringのNewell法から決定的なframeを推定する。"""

        values = np.asarray(points, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 3:
            raise ValueError("points は shape (N,3) である必要がある")
        if values.shape[0] == 0:
            return _invalid_planar_frame(status="empty", rank=0)
        if not bool(np.all(np.isfinite(values))):
            return _invalid_planar_frame(status="nonfinite", rank=0)

        tolerance = _frame_close_tolerance(values)
        packed_offsets = _packed_clean_frame_offsets(
            values,
            offsets,
            tolerance=tolerance,
        )
        if packed_offsets is None:
            lines = _clean_frame_lines(values, offsets, tolerance=tolerance)
            if not lines:
                return _invalid_planar_frame(status="empty", rank=0)
            samples = np.concatenate(lines, axis=0)
        else:
            lines = None
            samples = values

        anchor = samples[0]
        relative = samples - anchor
        origin = anchor + np.mean(relative, axis=0)
        centered = relative - np.mean(relative, axis=0)
        scale = float(np.max(np.linalg.norm(centered, axis=1)))
        if not math.isfinite(scale) or scale <= tolerance:
            return _invalid_planar_frame(status="point", rank=0, origin=origin)

        normalized = centered / scale
        covariance = (normalized.T @ normalized) / float(max(1, normalized.shape[0]))
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        except np.linalg.LinAlgError:
            return _invalid_planar_frame(status="nonfinite", rank=0, origin=origin)
        if not bool(np.all(np.isfinite(eigenvalues))) or not bool(
            np.all(np.isfinite(eigenvectors))
        ):
            return _invalid_planar_frame(status="nonfinite", rank=0, origin=origin)

        largest = max(0.0, float(eigenvalues[-1]))
        eigen_tolerance = max(
            largest * 1e-12,
            np.finfo(np.float64).eps * largest * max(3, normalized.shape[0]) * 16.0,
        )
        rank = int(np.count_nonzero(eigenvalues > eigen_tolerance))
        if rank < 2:
            status = "point" if rank == 0 else "linear"
            return _invalid_planar_frame(status=status, rank=rank, origin=origin)

        normal = eigenvectors[:, 0].astype(np.float64, copy=True)
        normal /= float(np.linalg.norm(normal))

        reference_line: np.ndarray | None = None
        reference_index = 0
        if packed_offsets is not None:
            total_newell, reference_index, reference_newell = (
                _packed_newell_statistics(
                    values,
                    packed_offsets,
                    scale=scale,
                )
            )
        else:
            total_newell = np.zeros((3,), dtype=np.float64)
            reference_newell = np.zeros((3,), dtype=np.float64)
            reference_area = -1.0
            assert lines is not None
            for line in lines:
                if line.shape[0] < 3:
                    newell = np.zeros((3,), dtype=np.float64)
                else:
                    newell = _newell_vector(line, scale=scale)
                area = float(np.linalg.norm(newell))
                total_newell += newell
                if area > reference_area:
                    reference_area = area
                    reference_line = line
                    reference_newell = newell

        orientation = total_newell
        if float(np.linalg.norm(orientation)) <= 1e-14:
            orientation = reference_newell
        orientation_norm = float(np.linalg.norm(orientation))
        if orientation_norm > 1e-14:
            if float(np.dot(normal, orientation)) < 0.0:
                normal = -normal
        else:
            normal = _canonicalize_direction(normal)

        edge_tolerance = max(tolerance, scale * 1e-12)
        if packed_offsets is not None:
            x_axis = _first_projected_packed_edge(
                values,
                packed_offsets,
                normal=normal,
                reference_index=reference_index,
                tolerance=edge_tolerance,
            )
        else:
            assert lines is not None
            ordered_lines = (
                [reference_line, *(line for line in lines if line is not reference_line)]
                if reference_line is not None
                else lines
            )
            x_axis = None
            for line in ordered_lines:
                if line is None or line.shape[0] < 2:
                    continue
                for edge in np.diff(line, axis=0):
                    projected = edge - float(np.dot(edge, normal)) * normal
                    length = float(np.linalg.norm(projected))
                    if length > edge_tolerance:
                        x_axis = projected / length
                        break
                if x_axis is not None:
                    break

        if x_axis is None:
            fallback = eigenvectors[:, -1].astype(np.float64, copy=True)
            fallback -= float(np.dot(fallback, normal)) * normal
            fallback_norm = float(np.linalg.norm(fallback))
            if fallback_norm <= 1e-14:
                return _invalid_planar_frame(status="linear", rank=1, origin=origin)
            x_axis = _canonicalize_direction(fallback / fallback_norm)

        y_axis = _cross3(normal, x_axis)
        y_norm = float(np.linalg.norm(y_axis))
        if y_norm <= 1e-14:
            return _invalid_planar_frame(status="linear", rank=1, origin=origin)
        y_axis /= y_norm
        x_axis = _cross3(y_axis, normal)
        x_axis /= float(np.linalg.norm(x_axis))

        basis = np.stack([x_axis, y_axis, normal], axis=0)
        inverse = basis.T
        residual = float(np.max(np.abs((values - origin) @ normal)))
        status = "planar" if rank == 2 else "spatial"
        return cls(
            origin=origin,
            basis=basis,
            inverse=inverse,
            residual=residual,
            rank=rank,
            status=status,
        )


def _world_canonical_basis(normal: np.ndarray) -> np.ndarray | None:
    """単位法線から world axis 優先の右手直交基底を返す。"""

    canonical_normal = _stable_canonicalize_direction(normal)
    world_axes = np.eye(3, dtype=np.float64)
    projected = world_axes - np.outer(
        world_axes @ canonical_normal,
        canonical_normal,
    )
    lengths = np.linalg.norm(projected, axis=1)
    axis_index = _stable_argmax(lengths)
    axis_length = float(lengths[axis_index])
    if not math.isfinite(axis_length) or axis_length <= 1e-14:
        return None

    x_axis = projected[axis_index] / axis_length
    if float(np.dot(x_axis, world_axes[axis_index])) < 0.0:
        x_axis = -x_axis
    y_axis = _cross3(canonical_normal, x_axis)
    y_length = float(np.linalg.norm(y_axis))
    if not math.isfinite(y_length) or y_length <= 1e-14:
        return None
    y_axis /= y_length
    x_axis = _cross3(y_axis, canonical_normal)
    x_axis /= float(np.linalg.norm(x_axis))
    return np.stack([x_axis, y_axis, canonical_normal], axis=0)


def _axis_aligned_planar_frame(points: np.ndarray) -> PlanarFrame | None:
    """明らかな axis-aligned rank-2 平面を canonical frame 化する。"""

    extents = np.ptp(points, axis=0)
    constant_axes = np.flatnonzero(extents == 0.0)
    if constant_axes.size != 1:
        return None
    normal_index = int(constant_axes[0])
    plane_axes = tuple(index for index in range(3) if index != normal_index)
    planar = points[:, plane_axes] - points[0, plane_axes]
    scale = float(np.max(np.linalg.norm(planar, axis=1)))
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    reference_index = int(np.argmax(np.linalg.norm(planar, axis=1)))
    reference = planar[reference_index]
    cross = reference[0] * planar[:, 1] - reference[1] * planar[:, 0]
    # 境界的な rank 判定は汎用 PCA に任せ、明白な面だけを高速化する。
    if float(np.max(np.abs(cross))) <= scale * scale * 1e-6:
        return None

    normal = np.zeros((3,), dtype=np.float64)
    normal[normal_index] = 1.0
    basis = _world_canonical_basis(normal)
    if basis is None:
        return None
    origin = normal * float(np.mean(points[:, normal_index]))
    return PlanarFrame(
        origin=origin,
        basis=basis,
        inverse=basis.T,
        residual=0.0,
        rank=2,
        status="planar",
    )


def _two_point_linear_frame(points: np.ndarray) -> PlanarFrame | None:
    """二点直線へ canonical principal plane を補う。"""

    direction = points[1] - points[0]
    length = float(np.linalg.norm(direction))
    if not math.isfinite(length) or length <= 0.0:
        return None
    x_axis = _stable_canonicalize_direction(direction / length)

    world_axes = np.asarray(
        (
            (0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ),
        dtype=np.float64,
    )
    projected = world_axes - np.outer(world_axes @ x_axis, x_axis)
    lengths = np.linalg.norm(projected, axis=1)
    axis_index = _stable_argmax(lengths)
    normal_length = float(lengths[axis_index])
    if not math.isfinite(normal_length) or normal_length <= 1e-14:
        return None
    normal = _stable_canonicalize_direction(
        projected[axis_index] / normal_length
    )

    y_axis = _cross3(normal, x_axis)
    y_length = float(np.linalg.norm(y_axis))
    if not math.isfinite(y_length) or y_length <= 1e-14:
        return None
    y_axis /= y_length
    x_axis = _cross3(y_axis, normal)
    x_axis /= float(np.linalg.norm(x_axis))

    center = np.mean(points, axis=0)
    origin = normal * float(np.dot(center, normal))
    residual = float(np.max(np.abs((points - origin) @ normal)))
    basis = np.stack([x_axis, y_axis, normal], axis=0)
    return PlanarFrame(
        origin=origin,
        basis=basis,
        inverse=basis.T,
        residual=residual,
        rank=2,
        status="planar",
    )


def canonical_planar_frame(
    points: np.ndarray,
    offsets: np.ndarray | None = None,
    *,
    allow_linear: bool = False,
) -> PlanarFrame:
    """入力順に依存しない world 基準の平面 frame を返す。

    ``PlanarFrame.from_points`` が推定した平面と残差を保ちながら、法線の符号と
    平面内の軸を固定 world axis から決め直す。ring の winding、seam、line 順を
    変えても同じ局所座標系が必要な平面演算で使う。

    ``allow_linear=True`` の場合は、rank 1 の点群に world axis を基準とする
    principal plane を補い、有効な rank 2 frame として返す。純粋な 3D 直線には
    平面が一意に定まらないため、この補完規則を明示的に選ぶ effect だけが使う。

    Parameters
    ----------
    points : np.ndarray
        shape ``(N, 3)`` の world 座標。
    offsets : np.ndarray or None, default None
        packed polyline の境界。省略時は全点を一本の線として扱う。
    allow_linear : bool, default False
        rank 1 の点群へ決定的な principal plane を補うか。

    Returns
    -------
    PlanarFrame
        world 基準へ canonicalize した frame。補完できない入力は
        ``PlanarFrame.from_points`` と同じ無効 frame を返す。
    """

    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("points は shape (N,3) である必要がある")
    fast_path_offsets = offsets is None
    if offsets is not None:
        packed_offsets = np.asarray(offsets)
        fast_path_offsets = bool(
            packed_offsets.ndim == 1
            and packed_offsets.size >= 2
            and np.issubdtype(packed_offsets.dtype, np.integer)
            and int(packed_offsets[0]) == 0
            and int(packed_offsets[-1]) == values.shape[0]
            and np.all(np.diff(packed_offsets) > 0)
        )
    if (
        fast_path_offsets
        and values.shape[0]
        and bool(np.all(np.isfinite(values)))
    ):
        axis_aligned = _axis_aligned_planar_frame(values)
        if axis_aligned is not None:
            return axis_aligned
        if bool(allow_linear) and values.shape[0] == 2:
            two_point = _two_point_linear_frame(values)
            if two_point is not None:
                return two_point

    source = PlanarFrame.from_points(values, offsets)
    if source.valid:
        basis = _world_canonical_basis(source.normal.copy())
        if basis is None:
            return source

        # world 原点から推定平面へ下ろした垂線の足を使うことで、入力の seam や
        # line 順が変わっても平面内原点を動かさない。
        normal = basis[2]
        origin = normal * float(np.dot(source.origin, normal))
        return PlanarFrame(
            origin=origin,
            basis=basis,
            inverse=basis.T,
            residual=source.residual,
            rank=source.rank,
            status=source.status,
        )

    if not bool(allow_linear) or source.status != "linear":
        return source

    tolerance = _frame_close_tolerance(values)
    lines = _clean_frame_lines(values, offsets, tolerance=tolerance)
    if not lines:
        return source
    samples = np.concatenate(lines, axis=0)
    center = np.mean(samples, axis=0)
    centered = samples - center
    covariance = centered.T @ centered
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    except np.linalg.LinAlgError:
        return source
    if not bool(np.all(np.isfinite(eigenvalues))) or not bool(
        np.all(np.isfinite(eigenvectors))
    ):
        return source
    if float(eigenvalues[-1]) <= float(tolerance) * float(tolerance):
        return source

    x_axis = _stable_canonicalize_direction(
        eigenvectors[:, -1].astype(np.float64, copy=True)
    )
    x_length = float(np.linalg.norm(x_axis))
    if not math.isfinite(x_length) or x_length <= 1e-14:
        return source
    x_axis /= x_length

    # 直線に最も直交する world axis を選ぶ。同率時は Z, Y, X の順とし、
    # 入力頂点の向きを反転しても同じ principal plane を得る。
    world_axes = np.asarray(
        (
            (0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ),
        dtype=np.float64,
    )
    projected = world_axes - np.outer(world_axes @ x_axis, x_axis)
    lengths = np.linalg.norm(projected, axis=1)
    axis_index = _stable_argmax(lengths)
    normal_length = float(lengths[axis_index])
    if not math.isfinite(normal_length) or normal_length <= 1e-14:
        return source
    normal = _stable_canonicalize_direction(projected[axis_index] / normal_length)

    y_axis = _cross3(normal, x_axis)
    y_length = float(np.linalg.norm(y_axis))
    if not math.isfinite(y_length) or y_length <= 1e-14:
        return source
    y_axis /= y_length
    x_axis = _cross3(y_axis, normal)
    x_axis /= float(np.linalg.norm(x_axis))

    origin = normal * float(np.dot(center, normal))
    residual = float(np.max(np.abs((values - origin) @ normal)))
    basis = np.stack([x_axis, y_axis, normal], axis=0)
    return PlanarFrame(
        origin=origin,
        basis=basis,
        inverse=basis.T,
        residual=residual,
        rank=2,
        status="planar",
    )


_EDT_INF = 1e20


@njit(cache=True)
def _scanline_evenodd_mask_nb(
    ys: np.ndarray,
    origin_x: float,
    pitch: float,
    nx: int,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
) -> np.ndarray:
    ny = int(ys.shape[0])
    inside = np.zeros((ny, int(nx)), dtype=np.uint8)
    n_rings = int(ring_offsets.shape[0]) - 1
    intersections = np.empty((int(ring_vertices.shape[0]),), dtype=np.float64)

    for row in range(ny):
        y = float(ys[row])
        count = 0
        for ring_index in range(n_rings):
            if y < float(ring_mins[ring_index, 1]) or y > float(
                ring_maxs[ring_index, 1]
            ):
                continue
            start = int(ring_offsets[ring_index])
            stop = int(ring_offsets[ring_index + 1])
            for vertex_index in range(start, stop - 1):
                ay = float(ring_vertices[vertex_index, 1])
                by = float(ring_vertices[vertex_index + 1, 1])
                if (ay > y) == (by > y):
                    continue
                ax = float(ring_vertices[vertex_index, 0])
                bx = float(ring_vertices[vertex_index + 1, 0])
                intersections[count] = ax + (y - ay) * (bx - ax) / (by - ay)
                count += 1

        if count < 2:
            continue
        intersections[:count].sort()
        for pair_index in range(0, count - 1, 2):
            left = float(intersections[pair_index])
            right = float(intersections[pair_index + 1])
            if right <= left:
                continue
            first = int(math.ceil((left - float(origin_x)) / float(pitch)))
            last = int(math.ceil((right - float(origin_x)) / float(pitch)))
            if first < 0:
                first = 0
            if last > int(nx):
                last = int(nx)
            for column in range(first, last):
                inside[row, column] = 1
    return inside


def scanline_evenodd_mask(
    ys: np.ndarray,
    *,
    origin_x: float,
    pitch: float,
    nx: int,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
) -> np.ndarray:
    """packed ring群をeven-odd規則で等間隔gridへscanline rasterizeする。"""

    return _scanline_evenodd_mask_nb(
        ys,
        float(origin_x),
        float(pitch),
        int(nx),
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
    )


@njit(cache=True)
def _round_grid_index_nb(value: float) -> int:
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


@njit(cache=True)
def _rasterize_ring_boundary_nb(
    boundary: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    origin_x: float,
    origin_y: float,
    inverse_pitch: float,
) -> None:
    ny = int(boundary.shape[0])
    nx = int(boundary.shape[1])
    for ring_index in range(int(ring_offsets.shape[0]) - 1):
        start = int(ring_offsets[ring_index])
        stop = int(ring_offsets[ring_index + 1])
        for vertex_index in range(start, stop - 1):
            ax = float(ring_vertices[vertex_index, 0])
            ay = float(ring_vertices[vertex_index, 1])
            bx = float(ring_vertices[vertex_index + 1, 0])
            by = float(ring_vertices[vertex_index + 1, 1])

            x0 = _round_grid_index_nb((ax - origin_x) * inverse_pitch)
            y0 = _round_grid_index_nb((ay - origin_y) * inverse_pitch)
            x1 = _round_grid_index_nb((bx - origin_x) * inverse_pitch)
            y1 = _round_grid_index_nb((by - origin_y) * inverse_pitch)
            dx = abs(int(x1 - x0))
            dy = abs(int(y1 - y0))
            step_x = 1 if x0 < x1 else -1
            step_y = 1 if y0 < y1 else -1
            error = dx - dy

            while True:
                if 0 <= x0 < nx and 0 <= y0 < ny:
                    boundary[y0, x0] = 1
                if x0 == x1 and y0 == y1:
                    break
                doubled_error = 2 * error
                if doubled_error > -dy:
                    error -= dy
                    x0 += step_x
                if doubled_error < dx:
                    error += dx
                    y0 += step_y


@njit(cache=True)
def _add_mask_boundary_nb(boundary: np.ndarray, inside: np.ndarray) -> None:
    ny = int(inside.shape[0])
    nx = int(inside.shape[1])
    for row in range(ny):
        for column in range(nx):
            value = int(inside[row, column])
            if column + 1 < nx and value != int(inside[row, column + 1]):
                boundary[row, column] = 1
                boundary[row, column + 1] = 1
            if row + 1 < ny and value != int(inside[row + 1, column]):
                boundary[row, column] = 1
                boundary[row + 1, column] = 1


def rasterize_ring_boundary_mask(
    shape: tuple[int, int],
    *,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    origin_x: float,
    origin_y: float,
    pitch: float,
    inside: np.ndarray | None = None,
) -> np.ndarray:
    """packed ring線分と任意のinside差分からEDT seed maskを作る。"""

    boundary = np.zeros((int(shape[0]), int(shape[1])), dtype=np.uint8)
    _rasterize_ring_boundary_nb(
        boundary,
        ring_vertices,
        ring_offsets,
        float(origin_x),
        float(origin_y),
        1.0 / float(pitch),
    )
    if inside is not None:
        _add_mask_boundary_nb(boundary, inside)
    return boundary


@njit(cache=True)
def _squared_edt_1d_nb(
    source: np.ndarray,
    output: np.ndarray,
    locations: np.ndarray,
    boundaries: np.ndarray,
) -> None:
    size = int(source.shape[0])
    first = -1
    for index in range(size):
        if float(source[index]) < float(_EDT_INF):
            first = index
            break
    if first < 0:
        for index in range(size):
            output[index] = float(_EDT_INF)
        return

    envelope_index = 0
    locations[0] = np.int64(first)
    boundaries[0] = -1e30
    boundaries[1] = 1e30
    for query in range(first + 1, size):
        query_value = float(source[query])
        if query_value >= float(_EDT_INF):
            continue
        while True:
            location = int(locations[envelope_index])
            location_value = float(source[location])
            intersection = (
                (query_value + float(query * query))
                - (location_value + float(location * location))
            ) / (2.0 * float(query - location))
            if intersection <= float(boundaries[envelope_index]):
                envelope_index -= 1
                if envelope_index < 0:
                    envelope_index = 0
                    break
                continue
            break
        envelope_index += 1
        locations[envelope_index] = np.int64(query)
        boundaries[envelope_index] = float(intersection)
        boundaries[envelope_index + 1] = 1e30

    envelope_index = 0
    for query in range(size):
        while float(boundaries[envelope_index + 1]) < float(query):
            envelope_index += 1
        location = int(locations[envelope_index])
        delta = float(query - location)
        output[query] = delta * delta + float(source[location])


@njit(cache=True)
def _squared_edt_2d_nb(features: np.ndarray) -> np.ndarray:
    ny = int(features.shape[0])
    nx = int(features.shape[1])
    horizontal = np.empty((ny, nx), dtype=np.float64)
    source_row = np.empty((nx,), dtype=np.float64)
    output_row = np.empty((nx,), dtype=np.float64)
    locations = np.empty((nx,), dtype=np.int64)
    boundaries = np.empty((nx + 1,), dtype=np.float64)

    for row in range(ny):
        has_feature = False
        for column in range(nx):
            if int(features[row, column]) != 0:
                source_row[column] = 0.0
                has_feature = True
            else:
                source_row[column] = float(_EDT_INF)
        if not has_feature:
            for column in range(nx):
                horizontal[row, column] = float(_EDT_INF)
            continue
        _squared_edt_1d_nb(source_row, output_row, locations, boundaries)
        for column in range(nx):
            horizontal[row, column] = output_row[column]

    squared_distance = np.empty((ny, nx), dtype=np.float64)
    source_column = np.empty((ny,), dtype=np.float64)
    output_column = np.empty((ny,), dtype=np.float64)
    column_locations = np.empty((ny,), dtype=np.int64)
    column_boundaries = np.empty((ny + 1,), dtype=np.float64)
    for column in range(nx):
        has_feature = False
        for row in range(ny):
            value = float(horizontal[row, column])
            source_column[row] = value
            if value < float(_EDT_INF):
                has_feature = True
        if not has_feature:
            for row in range(ny):
                squared_distance[row, column] = float(_EDT_INF)
            continue
        _squared_edt_1d_nb(
            source_column,
            output_column,
            column_locations,
            column_boundaries,
        )
        for row in range(ny):
            squared_distance[row, column] = output_column[row]
    return squared_distance


def squared_euclidean_distance_transform(features: np.ndarray) -> np.ndarray:
    """非zero featureまでの2D squared Euclidean distanceを2-passで返す。"""

    values = np.asarray(features)
    if values.ndim != 2:
        raise ValueError("features は2次元配列である必要がある")
    return _squared_edt_2d_nb(values)


@njit(cache=True)
def _signed_distance_grid_edt_nb(
    xs: np.ndarray,
    ys: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
    max_distance: float,
    gamma: float,
    pitch: float,
) -> np.ndarray:
    ny = int(ys.shape[0])
    nx = int(xs.shape[0])
    origin_x = float(xs[0])
    origin_y = float(ys[0])
    inside = _scanline_evenodd_mask_nb(
        ys,
        origin_x,
        pitch,
        nx,
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
    )
    boundary = np.zeros((ny, nx), dtype=np.uint8)
    _rasterize_ring_boundary_nb(
        boundary,
        ring_vertices,
        ring_offsets,
        origin_x,
        origin_y,
        1.0 / pitch,
    )
    _add_mask_boundary_nb(boundary, inside)
    squared_distance = _squared_edt_2d_nb(boundary)

    sdf = np.empty((ny, nx), dtype=np.float64)
    for row in range(ny):
        for column in range(nx):
            distance = math.sqrt(float(squared_distance[row, column])) * pitch
            if max_distance > 0.0 and gamma != 1.0:
                normalized = distance / max_distance
                if normalized < 0.0:
                    normalized = 0.0
                distance = max_distance * math.pow(normalized, gamma)
            if int(inside[row, column]) != 0:
                distance = -distance
            sdf[row, column] = distance
    return sdf


def signed_distance_grid_edt(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
    pitch: float,
    max_distance: float = 0.0,
    gamma: float = 1.0,
) -> np.ndarray:
    """packed ring群からscanline・boundary raster・2-pass EDTでSDFを作る。"""

    return _signed_distance_grid_edt_nb(
        xs,
        ys,
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
        float(max_distance),
        float(gamma),
        float(pitch),
    )


@njit(cache=True)
def _build_edge_neighbors_nb(
    node_count: int, edges_a: np.ndarray, edges_b: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    neighbors = np.full((node_count, 2), -1, dtype=np.int64)
    degree = np.zeros((node_count,), dtype=np.int32)
    for edge_index in range(int(edges_a.shape[0])):
        a = int(edges_a[edge_index])
        b = int(edges_b[edge_index])
        degree_a = int(degree[a])
        if degree_a < 2:
            neighbors[a, degree_a] = b
        degree[a] = degree_a + 1
        degree_b = int(degree[b])
        if degree_b < 2:
            neighbors[b, degree_b] = a
        degree[b] = degree_b + 1
    return neighbors, degree


@njit(cache=True)
def _collect_edge_cycles_nb(
    neighbors: np.ndarray, degree: np.ndarray
) -> tuple[np.ndarray, np.ndarray, int]:
    node_count = int(neighbors.shape[0])
    visited = np.zeros((node_count,), dtype=np.uint8)
    starts = np.empty((node_count,), dtype=np.int64)
    lengths = np.empty((node_count,), dtype=np.int32)
    cycle_count = 0
    for start in range(node_count):
        if int(degree[start]) != 2 or int(visited[start]) != 0:
            continue
        if int(neighbors[start, 0]) < 0 or int(neighbors[start, 1]) < 0:
            visited[start] = 1
            continue
        if int(neighbors[start, 0]) == int(neighbors[start, 1]):
            visited[start] = 1
            continue

        previous = -1
        current = start
        length = 0
        valid = True
        while True:
            if int(visited[current]) != 0:
                if current == start:
                    break
                valid = False
                break
            visited[current] = 1
            length += 1
            first = int(neighbors[current, 0])
            second = int(neighbors[current, 1])
            following = first if first != previous else second
            if following < 0 or int(degree[following]) != 2 or following == previous:
                valid = False
                break
            previous = current
            current = following
            if current == start:
                break
        if valid and length >= 3:
            starts[cycle_count] = start
            lengths[cycle_count] = length
            cycle_count += 1
    return starts, lengths, cycle_count


@njit(cache=True)
def _pack_edge_cycles_nb(
    neighbors: np.ndarray,
    starts: np.ndarray,
    lengths: np.ndarray,
    cycle_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    offsets = np.empty((cycle_count + 1,), dtype=np.int32)
    offsets[0] = 0
    total = 0
    for cycle_index in range(cycle_count):
        total += int(lengths[cycle_index]) + 1
        offsets[cycle_index + 1] = total
    indices = np.empty((total,), dtype=np.int64)
    cursor = 0
    for cycle_index in range(cycle_count):
        start = int(starts[cycle_index])
        previous = -1
        current = start
        for _ in range(int(lengths[cycle_index])):
            indices[cursor] = current
            cursor += 1
            first = int(neighbors[current, 0])
            second = int(neighbors[current, 1])
            following = first if first != previous else second
            previous = current
            current = following
        indices[cursor] = start
        cursor += 1
    return indices, offsets


@njit(cache=True)
def _compact_grid_edge_ids_nb(
    edges_a: np.ndarray, edges_b: np.ndarray, total_edge_count: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    segment_count = int(edges_a.shape[0])
    used = np.zeros((total_edge_count,), dtype=np.uint8)
    for segment_index in range(segment_count):
        used[int(edges_a[segment_index])] = 1
        used[int(edges_b[segment_index])] = 1
    node_count = 0
    for edge_id in range(total_edge_count):
        node_count += int(used[edge_id])

    node_edge_ids = np.empty((node_count,), dtype=np.int32)
    edge_to_node = np.full((total_edge_count,), -1, dtype=np.int32)
    cursor = 0
    for edge_id in range(total_edge_count):
        if int(used[edge_id]) != 0:
            edge_to_node[edge_id] = cursor
            node_edge_ids[cursor] = edge_id
            cursor += 1
    compact_a = np.empty((segment_count,), dtype=np.int32)
    compact_b = np.empty((segment_count,), dtype=np.int32)
    for segment_index in range(segment_count):
        compact_a[segment_index] = edge_to_node[int(edges_a[segment_index])]
        compact_b[segment_index] = edge_to_node[int(edges_b[segment_index])]
    return node_edge_ids, compact_a, compact_b


@njit(cache=True)
def _grid_edge_nodes_to_xy_nb(
    node_edge_ids: np.ndarray,
    horizontal_t: np.ndarray,
    vertical_t: np.ndarray,
    origin_x: float,
    origin_y: float,
    pitch: float,
    nx: int,
    ny: int,
) -> np.ndarray:
    horizontal_count = ny * (nx - 1)
    output = np.empty((int(node_edge_ids.shape[0]), 2), dtype=np.float64)
    for node_index in range(int(node_edge_ids.shape[0])):
        edge_id = int(node_edge_ids[node_index])
        if edge_id < horizontal_count:
            row = edge_id // (nx - 1)
            column = edge_id - row * (nx - 1)
            output[node_index, 0] = origin_x + pitch * (
                float(column) + float(horizontal_t[edge_id])
            )
            output[node_index, 1] = origin_y + pitch * float(row)
        else:
            local_id = edge_id - horizontal_count
            row = local_id // nx
            column = local_id - row * nx
            output[node_index, 0] = origin_x + pitch * float(column)
            output[node_index, 1] = origin_y + pitch * (
                float(row) + float(vertical_t[local_id])
            )
    return output


@njit(cache=True)
def _interpolate_level_nb(a: float, b: float, level: float) -> float:
    denominator = b - a
    if denominator == 0.0:
        return 0.5
    value = (level - a) / denominator
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@njit(cache=True)
def _count_marching_segments_nb(
    field: np.ndarray,
    level: float,
    mask: np.ndarray,
    use_mask: bool,
    samples: np.ndarray,
    use_sample_range: bool,
    sample_min: float,
    sample_max: float,
) -> int:
    ny = int(field.shape[0])
    nx = int(field.shape[1])
    count = 0
    for row in range(ny - 1):
        for column in range(nx - 1):
            if use_mask and (
                int(mask[row, column]) == 0
                or int(mask[row, column + 1]) == 0
                or int(mask[row + 1, column + 1]) == 0
                or int(mask[row + 1, column]) == 0
            ):
                continue
            v00 = float(field[row, column])
            v10 = float(field[row, column + 1])
            v11 = float(field[row + 1, column + 1])
            v01 = float(field[row + 1, column])
            b0 = v00 >= level
            b1 = v10 >= level
            b2 = v11 >= level
            b3 = v01 >= level
            case = (1 if b0 else 0) | (2 if b1 else 0) | (4 if b2 else 0) | (
                8 if b3 else 0
            )
            if case == 0 or case == 15:
                continue

            valid = 0
            if b0 != b1:
                interpolation = _interpolate_level_nb(v00, v10, level)
                sample = float(samples[row, column]) + interpolation * float(
                    samples[row, column + 1] - samples[row, column]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    valid += 1
            if b1 != b2:
                interpolation = _interpolate_level_nb(v10, v11, level)
                sample = float(samples[row, column + 1]) + interpolation * float(
                    samples[row + 1, column + 1] - samples[row, column + 1]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    valid += 1
            if b3 != b2:
                interpolation = _interpolate_level_nb(v01, v11, level)
                sample = float(samples[row + 1, column]) + interpolation * float(
                    samples[row + 1, column + 1] - samples[row + 1, column]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    valid += 1
            if b0 != b3:
                interpolation = _interpolate_level_nb(v00, v01, level)
                sample = float(samples[row, column]) + interpolation * float(
                    samples[row + 1, column] - samples[row, column]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    valid += 1
            if valid == 2:
                count += 1
            elif valid == 4:
                count += 2
    return count


@njit(cache=True)
def _fill_marching_segments_nb(
    field: np.ndarray,
    level: float,
    mask: np.ndarray,
    use_mask: bool,
    samples: np.ndarray,
    use_sample_range: bool,
    sample_min: float,
    sample_max: float,
    edges_a: np.ndarray,
    edges_b: np.ndarray,
    horizontal_t: np.ndarray,
    vertical_t: np.ndarray,
) -> int:
    ny = int(field.shape[0])
    nx = int(field.shape[1])
    horizontal_count = ny * (nx - 1)
    cursor = 0
    for row in range(ny - 1):
        for column in range(nx - 1):
            if use_mask and (
                int(mask[row, column]) == 0
                or int(mask[row, column + 1]) == 0
                or int(mask[row + 1, column + 1]) == 0
                or int(mask[row + 1, column]) == 0
            ):
                continue
            v00 = float(field[row, column])
            v10 = float(field[row, column + 1])
            v11 = float(field[row + 1, column + 1])
            v01 = float(field[row + 1, column])
            b0 = v00 >= level
            b1 = v10 >= level
            b2 = v11 >= level
            b3 = v01 >= level
            case = (1 if b0 else 0) | (2 if b1 else 0) | (4 if b2 else 0) | (
                8 if b3 else 0
            )
            if case == 0 or case == 15:
                continue

            present0 = False
            present1 = False
            present2 = False
            present3 = False
            id0 = np.int32(0)
            id1 = np.int32(0)
            id2 = np.int32(0)
            id3 = np.int32(0)
            if b0 != b1:
                interpolation = _interpolate_level_nb(v00, v10, level)
                sample = float(samples[row, column]) + interpolation * float(
                    samples[row, column + 1] - samples[row, column]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    present0 = True
                    edge_id = row * (nx - 1) + column
                    id0 = np.int32(edge_id)
                    horizontal_t[edge_id] = np.float32(interpolation)
            if b1 != b2:
                interpolation = _interpolate_level_nb(v10, v11, level)
                sample = float(samples[row, column + 1]) + interpolation * float(
                    samples[row + 1, column + 1] - samples[row, column + 1]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    present1 = True
                    edge_id = row * nx + column + 1
                    id1 = np.int32(horizontal_count + edge_id)
                    vertical_t[edge_id] = np.float32(interpolation)
            if b3 != b2:
                interpolation = _interpolate_level_nb(v01, v11, level)
                sample = float(samples[row + 1, column]) + interpolation * float(
                    samples[row + 1, column + 1] - samples[row + 1, column]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    present2 = True
                    edge_id = (row + 1) * (nx - 1) + column
                    id2 = np.int32(edge_id)
                    horizontal_t[edge_id] = np.float32(interpolation)
            if b0 != b3:
                interpolation = _interpolate_level_nb(v00, v01, level)
                sample = float(samples[row, column]) + interpolation * float(
                    samples[row + 1, column] - samples[row, column]
                )
                if not use_sample_range or sample_min <= sample <= sample_max:
                    present3 = True
                    edge_id = row * nx + column
                    id3 = np.int32(horizontal_count + edge_id)
                    vertical_t[edge_id] = np.float32(interpolation)

            point_count = int(present0) + int(present1) + int(present2) + int(present3)
            if point_count == 2:
                first = np.int32(0)
                second = np.int32(0)
                found = False
                if present0:
                    first = id0
                    found = True
                if present1:
                    if found:
                        second = id1
                    else:
                        first = id1
                        found = True
                if present2:
                    if found:
                        second = id2
                    else:
                        first = id2
                        found = True
                if present3:
                    if found:
                        second = id3
                    else:
                        first = id3
                edges_a[cursor] = first
                edges_b[cursor] = second
                cursor += 1
                continue
            if point_count != 4:
                continue

            center_inside = 0.25 * (v00 + v10 + v11 + v01) >= level
            if case == 5:
                if center_inside:
                    edges_a[cursor] = id0
                    edges_b[cursor] = id1
                    cursor += 1
                    edges_a[cursor] = id2
                    edges_b[cursor] = id3
                else:
                    edges_a[cursor] = id0
                    edges_b[cursor] = id3
                    cursor += 1
                    edges_a[cursor] = id1
                    edges_b[cursor] = id2
                cursor += 1
                continue
            if case == 10:
                if center_inside:
                    edges_a[cursor] = id0
                    edges_b[cursor] = id3
                    cursor += 1
                    edges_a[cursor] = id1
                    edges_b[cursor] = id2
                else:
                    edges_a[cursor] = id0
                    edges_b[cursor] = id1
                    cursor += 1
                    edges_a[cursor] = id2
                    edges_b[cursor] = id3
                cursor += 1
                continue
            edges_a[cursor] = id0
            edges_b[cursor] = id1
            cursor += 1
            edges_a[cursor] = id2
            edges_b[cursor] = id3
            cursor += 1
    return cursor


def _stitch_grid_edges(
    edges_a: np.ndarray,
    edges_b: np.ndarray,
    *,
    horizontal_t: np.ndarray,
    vertical_t: np.ndarray,
    origin_x: float,
    origin_y: float,
    pitch: float,
    nx: int,
    ny: int,
) -> list[np.ndarray]:
    if edges_a.size == 0:
        return []
    nondegenerate = edges_a != edges_b
    edges_a = edges_a[nondegenerate]
    edges_b = edges_b[nondegenerate]
    if edges_a.size == 0:
        return []
    total_edge_count = ny * (nx - 1) + (ny - 1) * nx
    node_edge_ids, compact_a, compact_b = _compact_grid_edge_ids_nb(
        edges_a.astype(np.int32, copy=False),
        edges_b.astype(np.int32, copy=False),
        total_edge_count,
    )
    node_xy = _grid_edge_nodes_to_xy_nb(
        node_edge_ids,
        horizontal_t,
        vertical_t,
        origin_x,
        origin_y,
        pitch,
        nx,
        ny,
    )
    neighbors, degree = _build_edge_neighbors_nb(
        int(node_xy.shape[0]), compact_a, compact_b
    )
    starts, lengths, cycle_count = _collect_edge_cycles_nb(neighbors, degree)
    if cycle_count <= 0:
        return []
    indices, offsets = _pack_edge_cycles_nb(
        neighbors, starts, lengths, int(cycle_count)
    )
    return [
        node_xy[indices[int(offsets[index]) : int(offsets[index + 1])]]
        for index in range(int(offsets.size) - 1)
        if int(offsets[index + 1]) - int(offsets[index]) >= 4
    ]


def marching_squares_loops(
    field: np.ndarray,
    *,
    origin_x: float,
    origin_y: float,
    pitch: float,
    level: float = 0.0,
    mask: np.ndarray | None = None,
    sample_field: np.ndarray | None = None,
    sample_range: tuple[float, float] | None = None,
) -> list[np.ndarray]:
    """等間隔gridのMarching Squaresをedge-idで縫合し閉loop列を返す。"""

    values = np.asarray(field)
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
        return []
    use_mask = mask is not None
    mask_values = np.empty((0, 0), dtype=np.uint8) if mask is None else np.asarray(mask)
    if use_mask and mask_values.shape != values.shape:
        raise ValueError("mask と field の shape は一致する必要がある")
    use_sample_range = sample_field is not None and sample_range is not None
    samples = values if sample_field is None else np.asarray(sample_field)
    if use_sample_range and samples.shape != values.shape:
        raise ValueError("sample_field と field の shape は一致する必要がある")
    sample_min, sample_max = (
        (-math.inf, math.inf) if sample_range is None else sample_range
    )
    segment_count = _count_marching_segments_nb(
        values,
        float(level),
        mask_values,
        bool(use_mask),
        samples,
        bool(use_sample_range),
        float(sample_min),
        float(sample_max),
    )
    if segment_count <= 0:
        return []

    ny, nx = int(values.shape[0]), int(values.shape[1])
    horizontal_count = ny * (nx - 1)
    vertical_count = (ny - 1) * nx
    edges_a = np.empty((segment_count,), dtype=np.int32)
    edges_b = np.empty((segment_count,), dtype=np.int32)
    horizontal_t = np.full((horizontal_count,), -1.0, dtype=np.float32)
    vertical_t = np.full((vertical_count,), -1.0, dtype=np.float32)
    filled = _fill_marching_segments_nb(
        values,
        float(level),
        mask_values,
        bool(use_mask),
        samples,
        bool(use_sample_range),
        float(sample_min),
        float(sample_max),
        edges_a,
        edges_b,
        horizontal_t,
        vertical_t,
    )
    return _stitch_grid_edges(
        edges_a[:filled],
        edges_b[:filled],
        horizontal_t=horizontal_t,
        vertical_t=vertical_t,
        origin_x=float(origin_x),
        origin_y=float(origin_y),
        pitch=float(pitch),
        nx=nx,
        ny=ny,
    )


@dataclass(frozen=True, slots=True)
class ResampleLinePlan:
    """1本のpolylineについて確保前に算出した再sample仕様。"""

    input_start: int
    input_stop: int
    sample_stop: int
    output_start: int
    output_stop: int
    mode: int

    @property
    def closed(self) -> bool:
        """周期境界として処理するlineならTrue。"""

        return self.mode == _RESAMPLE_CLOSED


@dataclass(frozen=True, slots=True)
class ResamplePlan:
    """全polylineの出力数を確保前に検証した再sample計画。"""

    step: float
    lines: tuple[ResampleLinePlan, ...]
    total_vertices: int
    max_vertices: int

    @property
    def fits(self) -> bool:
        """出力頂点数が上限内ならTrue。"""

        return self.total_vertices <= self.max_vertices

    @classmethod
    def from_geometry(
        cls,
        coords: np.ndarray,
        offsets: np.ndarray,
        *,
        step: float,
        closed: str,
        max_vertices: int,
        closed_distance: float = RESAMPLE_CLOSED_DISTANCE_EPS,
    ) -> ResamplePlan:
        """全lineをcountし、出力配列を作らず計画だけを返す。"""

        step_size = float(step)
        if not math.isfinite(step_size) or step_size <= 0.0:
            raise ValueError("step は有限の正数である必要がある")

        closed_mode = str(closed)
        if closed_mode not in {"auto", "open", "closed"}:
            closed_mode = "auto"
        closed_distance_sq = float(closed_distance) * float(closed_distance)

        lines: list[ResampleLinePlan] = []
        output_cursor = 0
        for line_index in range(int(offsets.size) - 1):
            start = int(offsets[line_index])
            stop = int(offsets[line_index + 1])
            vertices = coords[start:stop]
            source_count = int(stop - start)
            sample_stop = stop
            mode = _RESAMPLE_COPY if source_count < 2 else _RESAMPLE_OPEN
            output_count = source_count

            near_closed = False
            if source_count >= 3 and closed_mode != "open":
                near_closed = _endpoints_within_distance(vertices, closed_distance_sq)
            use_closed = source_count >= 3 and (
                closed_mode == "closed" or (closed_mode == "auto" and near_closed)
            )

            if use_closed:
                sample_stop = stop - 1 if near_closed else stop
                sample_vertices = coords[start:sample_stop]
                if sample_vertices.shape[0] >= 3:
                    mode = _RESAMPLE_CLOSED
                    total_length = float(_total_length_closed_nb(sample_vertices))
                    sample_count = _closed_resample_count(
                        total_length=total_length,
                        step=step_size,
                        source_count=int(sample_vertices.shape[0]),
                        max_vertices=int(max_vertices),
                    )
                    output_count = sample_count + 1
                else:
                    sample_stop = stop

            if mode == _RESAMPLE_OPEN:
                total_length = float(_total_length_open_nb(vertices))
                output_count = _open_resample_count(
                    total_length=total_length,
                    step=step_size,
                    source_count=source_count,
                    max_vertices=int(max_vertices),
                )

            output_stop = output_cursor + int(output_count)
            lines.append(
                ResampleLinePlan(
                    input_start=start,
                    input_stop=stop,
                    sample_stop=sample_stop,
                    output_start=output_cursor,
                    output_stop=output_stop,
                    mode=mode,
                )
            )
            output_cursor = output_stop

        return cls(
            step=step_size,
            lines=tuple(lines),
            total_vertices=int(output_cursor),
            max_vertices=max(0, int(max_vertices)),
        )


def _endpoints_within_distance(vertices: np.ndarray, distance_sq: float) -> bool:
    with np.errstate(over="ignore", invalid="ignore"):
        dx = float(vertices[-1, 0] - vertices[0, 0])
        dy = float(vertices[-1, 1] - vertices[0, 1])
        dz = float(vertices[-1, 2] - vertices[0, 2])
    if not math.isfinite(dx):
        dx = float(vertices[-1, 0]) - float(vertices[0, 0])
    if not math.isfinite(dy):
        dy = float(vertices[-1, 1]) - float(vertices[0, 1])
    if not math.isfinite(dz):
        dz = float(vertices[-1, 2]) - float(vertices[0, 2])
    return dx * dx + dy * dy + dz * dz <= float(distance_sq)


def _open_resample_count(
    *, total_length: float, step: float, source_count: int, max_vertices: int
) -> int:
    if total_length <= 0.0:
        return int(source_count)
    ratio = total_length / step
    if not math.isfinite(ratio):
        return max(0, int(max_vertices)) + 1
    count = int(math.floor(ratio)) + 1
    if float((count - 1) * step) < total_length:
        count += 1
    return max(2, count)


def _closed_resample_count(
    *, total_length: float, step: float, source_count: int, max_vertices: int
) -> int:
    if total_length <= 0.0:
        return int(source_count)
    ratio = total_length / step
    if not math.isfinite(ratio):
        return max(0, int(max_vertices)) + 1
    return max(3, int(math.ceil(ratio)))


def build_gaussian_kernel(*, sigma_in_samples: float, max_radius: int) -> np.ndarray:
    """sample単位のsigmaから正規化済みGaussian kernelを作る。"""

    radius = int(math.ceil(3.0 * float(sigma_in_samples)))
    radius = min(max(1, radius), max(1, int(max_radius)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    weights = np.exp(-0.5 * (x / float(sigma_in_samples)) ** 2)
    weight_sum = float(np.sum(weights))
    if weight_sum > 0.0:
        weights = weights / weight_sum
    return weights.astype(np.float64, copy=False)


@njit(cache=True)
def _resample_needs_float64_nb(vertices: np.ndarray, closed: bool) -> bool:
    """float32 の距離二乗が overflow する入力なら True を返す。"""

    count = int(vertices.shape[0])
    edge_count = count if closed and count >= 2 else max(0, count - 1)
    for index in range(edge_count):
        following = index + 1
        if following >= count:
            following = 0
        dx = vertices[following, 0] - vertices[index, 0]
        dy = vertices[following, 1] - vertices[index, 1]
        dz = vertices[following, 2] - vertices[index, 2]
        distance_sq = dx * dx + dy * dy + dz * dz
        if not np.isfinite(distance_sq):
            return True
    return False


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _total_length_open_fast_nb(vertices: np.ndarray) -> float:
    total = 0.0
    for index in range(vertices.shape[0] - 1):
        dx = float(vertices[index + 1, 0] - vertices[index, 0])
        dy = float(vertices[index + 1, 1] - vertices[index, 1])
        dz = float(vertices[index + 1, 2] - vertices[index, 2])
        total += float(np.sqrt(dx * dx + dy * dy + dz * dz))
    return float(total)


@njit(cache=True)
def _total_length_open_wide_nb(vertices: np.ndarray) -> float:
    total = 0.0
    for index in range(vertices.shape[0] - 1):
        dx = np.float64(vertices[index + 1, 0]) - np.float64(vertices[index, 0])
        dy = np.float64(vertices[index + 1, 1]) - np.float64(vertices[index, 1])
        dz = np.float64(vertices[index + 1, 2]) - np.float64(vertices[index, 2])
        total += np.sqrt(dx * dx + dy * dy + dz * dz)
    return float(total)


@njit(cache=True)
def _total_length_open_nb(vertices: np.ndarray) -> float:
    if _resample_needs_float64_nb(vertices, False):
        return _total_length_open_wide_nb(vertices)
    return _total_length_open_fast_nb(vertices)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _total_length_closed_fast_nb(vertices: np.ndarray) -> float:
    total = _total_length_open_fast_nb(vertices)
    count = int(vertices.shape[0])
    if count >= 2:
        dx = float(vertices[0, 0] - vertices[count - 1, 0])
        dy = float(vertices[0, 1] - vertices[count - 1, 1])
        dz = float(vertices[0, 2] - vertices[count - 1, 2])
        total += float(np.sqrt(dx * dx + dy * dy + dz * dz))
    return float(total)


@njit(cache=True)
def _total_length_closed_wide_nb(vertices: np.ndarray) -> float:
    total = _total_length_open_wide_nb(vertices)
    count = int(vertices.shape[0])
    if count >= 2:
        dx = np.float64(vertices[0, 0]) - np.float64(vertices[count - 1, 0])
        dy = np.float64(vertices[0, 1]) - np.float64(vertices[count - 1, 1])
        dz = np.float64(vertices[0, 2]) - np.float64(vertices[count - 1, 2])
        total += np.sqrt(dx * dx + dy * dy + dz * dz)
    return float(total)


@njit(cache=True)
def _total_length_closed_nb(vertices: np.ndarray) -> float:
    if _resample_needs_float64_nb(vertices, True):
        return _total_length_closed_wide_nb(vertices)
    return _total_length_closed_fast_nb(vertices)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _resample_open_fast_into_nb(
    vertices: np.ndarray,
    step: float,
    out: np.ndarray,
) -> None:
    count = int(out.shape[0])
    source_count = int(vertices.shape[0])
    if source_count < 2 or _total_length_open_fast_nb(vertices) <= 0.0:
        out[:] = vertices
        return

    out[0] = vertices[0]
    out[count - 1] = vertices[source_count - 1]
    segment_index = 0
    distance_acc = 0.0
    sx = float(vertices[0, 0])
    sy = float(vertices[0, 1])
    sz = float(vertices[0, 2])
    ex = float(vertices[1, 0])
    ey = float(vertices[1, 1])
    ez = float(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))
    target = float(step)
    output_index = 1

    while output_index < count - 1:
        if segment_length <= 0.0:
            segment_index += 1
            if segment_index >= source_count - 1:
                break
            sx = float(vertices[segment_index, 0])
            sy = float(vertices[segment_index, 1])
            sz = float(vertices[segment_index, 2])
            ex = float(vertices[segment_index + 1, 0])
            ey = float(vertices[segment_index + 1, 1])
            ez = float(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))
            continue

        if distance_acc + segment_length >= target:
            t = (target - distance_acc) / segment_length
            out[output_index, 0] = np.float32(sx + t * dx)
            out[output_index, 1] = np.float32(sy + t * dy)
            out[output_index, 2] = np.float32(sz + t * dz)
            output_index += 1
            target += float(step)
        else:
            distance_acc += segment_length
            segment_index += 1
            if segment_index >= source_count - 1:
                break
            sx = ex
            sy = ey
            sz = ez
            ex = float(vertices[segment_index + 1, 0])
            ey = float(vertices[segment_index + 1, 1])
            ez = float(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _resample_open_matches_source_fast_nb(
    vertices: np.ndarray,
    step: float,
) -> bool:
    """通常kernelの各内部標本が入力頂点とbyte等価か確保せず判定する。"""

    count = int(vertices.shape[0])
    if count < 3:
        return True

    segment_index = 0
    distance_acc = 0.0
    sx = float(vertices[0, 0])
    sy = float(vertices[0, 1])
    sz = float(vertices[0, 2])
    ex = float(vertices[1, 0])
    ey = float(vertices[1, 1])
    ez = float(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))
    target = float(step)
    output_index = 1

    while output_index < count - 1:
        if segment_length <= 0.0:
            segment_index += 1
            if segment_index >= count - 1:
                return False
            sx = float(vertices[segment_index, 0])
            sy = float(vertices[segment_index, 1])
            sz = float(vertices[segment_index, 2])
            ex = float(vertices[segment_index + 1, 0])
            ey = float(vertices[segment_index + 1, 1])
            ez = float(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))
            continue

        if distance_acc + segment_length >= target:
            t = (target - distance_acc) / segment_length
            x = np.float32(sx + t * dx)
            y = np.float32(sy + t * dy)
            z = np.float32(sz + t * dz)
            expected_x = vertices[output_index, 0]
            expected_y = vertices[output_index, 1]
            expected_z = vertices[output_index, 2]
            if x != expected_x or y != expected_y or z != expected_z:
                return False
            if x == 0.0 and np.signbit(x) != np.signbit(expected_x):
                return False
            if y == 0.0 and np.signbit(y) != np.signbit(expected_y):
                return False
            if z == 0.0 and np.signbit(z) != np.signbit(expected_z):
                return False
            output_index += 1
            target += float(step)
        else:
            distance_acc += segment_length
            segment_index += 1
            if segment_index >= count - 1:
                return False
            sx = ex
            sy = ey
            sz = ez
            ex = float(vertices[segment_index + 1, 0])
            ey = float(vertices[segment_index + 1, 1])
            ez = float(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))
    return True


@njit(cache=True)
def _resample_open_wide_into_nb(
    vertices: np.ndarray,
    step: float,
    out: np.ndarray,
) -> None:
    count = int(out.shape[0])
    source_count = int(vertices.shape[0])
    if source_count < 2 or _total_length_open_wide_nb(vertices) <= 0.0:
        out[:] = vertices
        return

    out[0] = vertices[0]
    out[count - 1] = vertices[source_count - 1]
    segment_index = 0
    distance_acc = 0.0
    sx = np.float64(vertices[0, 0])
    sy = np.float64(vertices[0, 1])
    sz = np.float64(vertices[0, 2])
    ex = np.float64(vertices[1, 0])
    ey = np.float64(vertices[1, 1])
    ez = np.float64(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)
    target = float(step)
    output_index = 1

    while output_index < count - 1:
        if segment_length <= 0.0:
            segment_index += 1
            if segment_index >= source_count - 1:
                break
            sx = np.float64(vertices[segment_index, 0])
            sy = np.float64(vertices[segment_index, 1])
            sz = np.float64(vertices[segment_index, 2])
            ex = np.float64(vertices[segment_index + 1, 0])
            ey = np.float64(vertices[segment_index + 1, 1])
            ez = np.float64(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)
            continue

        if distance_acc + segment_length >= target:
            t = (target - distance_acc) / segment_length
            out[output_index, 0] = np.float32(sx + t * dx)
            out[output_index, 1] = np.float32(sy + t * dy)
            out[output_index, 2] = np.float32(sz + t * dz)
            output_index += 1
            target += float(step)
        else:
            distance_acc += segment_length
            segment_index += 1
            if segment_index >= source_count - 1:
                break
            sx = ex
            sy = ey
            sz = ez
            ex = np.float64(vertices[segment_index + 1, 0])
            ey = np.float64(vertices[segment_index + 1, 1])
            ez = np.float64(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)


@njit(cache=True)
def _resample_open_matches_source_wide_nb(
    vertices: np.ndarray,
    step: float,
) -> bool:
    """float64退避kernelの各内部標本が入力頂点とbyte等価か判定する。"""

    count = int(vertices.shape[0])
    if count < 3:
        return True

    segment_index = 0
    distance_acc = 0.0
    sx = np.float64(vertices[0, 0])
    sy = np.float64(vertices[0, 1])
    sz = np.float64(vertices[0, 2])
    ex = np.float64(vertices[1, 0])
    ey = np.float64(vertices[1, 1])
    ez = np.float64(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)
    target = float(step)
    output_index = 1

    while output_index < count - 1:
        if segment_length <= 0.0:
            segment_index += 1
            if segment_index >= count - 1:
                return False
            sx = np.float64(vertices[segment_index, 0])
            sy = np.float64(vertices[segment_index, 1])
            sz = np.float64(vertices[segment_index, 2])
            ex = np.float64(vertices[segment_index + 1, 0])
            ey = np.float64(vertices[segment_index + 1, 1])
            ez = np.float64(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)
            continue

        if distance_acc + segment_length >= target:
            t = (target - distance_acc) / segment_length
            x = np.float32(sx + t * dx)
            y = np.float32(sy + t * dy)
            z = np.float32(sz + t * dz)
            expected_x = vertices[output_index, 0]
            expected_y = vertices[output_index, 1]
            expected_z = vertices[output_index, 2]
            if x != expected_x or y != expected_y or z != expected_z:
                return False
            if x == 0.0 and np.signbit(x) != np.signbit(expected_x):
                return False
            if y == 0.0 and np.signbit(y) != np.signbit(expected_y):
                return False
            if z == 0.0 and np.signbit(z) != np.signbit(expected_z):
                return False
            output_index += 1
            target += float(step)
        else:
            distance_acc += segment_length
            segment_index += 1
            if segment_index >= count - 1:
                return False
            sx = ex
            sy = ey
            sz = ez
            ex = np.float64(vertices[segment_index + 1, 0])
            ey = np.float64(vertices[segment_index + 1, 1])
            ez = np.float64(vertices[segment_index + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)
    return True


@njit(cache=True)
def _resample_open_into_nb(
    vertices: np.ndarray,
    step: float,
    out: np.ndarray,
) -> None:
    if _resample_needs_float64_nb(vertices, False):
        _resample_open_wide_into_nb(vertices, step, out)
    else:
        _resample_open_fast_into_nb(vertices, step, out)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _resample_closed_fast_into_nb(
    vertices: np.ndarray,
    step: float,
    out: np.ndarray,
) -> None:
    count = int(out.shape[0])
    source_count = int(vertices.shape[0])
    total_length = _total_length_closed_fast_nb(vertices)
    if total_length <= 0.0:
        out[:] = vertices
        return

    effective_step = float(step)
    if float(count - 1) * effective_step >= total_length:
        effective_step = total_length / float(count)

    out[0] = vertices[0]
    segment_index = 0
    distance_acc = 0.0
    sx = float(vertices[0, 0])
    sy = float(vertices[0, 1])
    sz = float(vertices[0, 2])
    ex = float(vertices[1, 0])
    ey = float(vertices[1, 1])
    ez = float(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))

    for output_index in range(1, count):
        target = float(output_index) * effective_step
        while segment_length <= 0.0 or distance_acc + segment_length < target:
            if segment_length > 0.0:
                distance_acc += segment_length
            segment_index += 1
            if segment_index >= source_count:
                segment_index = 0
            sx = ex
            sy = ey
            sz = ez
            next_index = segment_index + 1
            if next_index >= source_count:
                next_index = 0
            ex = float(vertices[next_index, 0])
            ey = float(vertices[next_index, 1])
            ez = float(vertices[next_index, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))

        if segment_length <= 0.0:
            out[output_index, 0] = np.float32(sx)
            out[output_index, 1] = np.float32(sy)
            out[output_index, 2] = np.float32(sz)
            continue

        t = (target - distance_acc) / segment_length
        out[output_index, 0] = np.float32(sx + t * dx)
        out[output_index, 1] = np.float32(sy + t * dy)
        out[output_index, 2] = np.float32(sz + t * dz)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _resample_closed_matches_source_fast_nb(
    vertices: np.ndarray,
    step: float,
) -> bool:
    """通常の閉曲線kernelが入力頂点列を再現するか確保せず判定する。"""

    count = int(vertices.shape[0])
    total_length = _total_length_closed_fast_nb(vertices)
    if count < 3 or total_length <= 0.0:
        return True

    effective_step = float(step)
    if float(count - 1) * effective_step >= total_length:
        effective_step = total_length / float(count)

    segment_index = 0
    distance_acc = 0.0
    sx = float(vertices[0, 0])
    sy = float(vertices[0, 1])
    sz = float(vertices[0, 2])
    ex = float(vertices[1, 0])
    ey = float(vertices[1, 1])
    ez = float(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))

    for output_index in range(1, count):
        target = float(output_index) * effective_step
        while segment_length <= 0.0 or distance_acc + segment_length < target:
            if segment_length > 0.0:
                distance_acc += segment_length
            segment_index += 1
            if segment_index >= count:
                segment_index = 0
            sx = ex
            sy = ey
            sz = ez
            next_index = segment_index + 1
            if next_index >= count:
                next_index = 0
            ex = float(vertices[next_index, 0])
            ey = float(vertices[next_index, 1])
            ez = float(vertices[next_index, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = float(np.sqrt(dx * dx + dy * dy + dz * dz))

        if segment_length <= 0.0:
            x = np.float32(sx)
            y = np.float32(sy)
            z = np.float32(sz)
        else:
            t = (target - distance_acc) / segment_length
            x = np.float32(sx + t * dx)
            y = np.float32(sy + t * dy)
            z = np.float32(sz + t * dz)

        expected_x = vertices[output_index, 0]
        expected_y = vertices[output_index, 1]
        expected_z = vertices[output_index, 2]
        if x != expected_x or y != expected_y or z != expected_z:
            return False
        if x == 0.0 and np.signbit(x) != np.signbit(expected_x):
            return False
        if y == 0.0 and np.signbit(y) != np.signbit(expected_y):
            return False
        if z == 0.0 and np.signbit(z) != np.signbit(expected_z):
            return False
    return True


@njit(cache=True)
def _resample_closed_wide_into_nb(
    vertices: np.ndarray,
    step: float,
    out: np.ndarray,
) -> None:
    count = int(out.shape[0])
    source_count = int(vertices.shape[0])
    total_length = _total_length_closed_wide_nb(vertices)
    if total_length <= 0.0:
        out[:] = vertices
        return

    effective_step = float(step)
    # closed の最小標本数は 3 なので、requested step が周長の半分以上では
    # 最後の標本位置が周長へ到達または超過する。その場合だけ周長を 3 等分以上
    # する実効間隔へ切り替え、seam への重複と巨大 step による多重周回を防ぐ。
    if float(count - 1) * effective_step >= total_length:
        effective_step = total_length / float(count)

    out[0] = vertices[0]
    segment_index = 0
    distance_acc = 0.0
    sx = np.float64(vertices[0, 0])
    sy = np.float64(vertices[0, 1])
    sz = np.float64(vertices[0, 2])
    ex = np.float64(vertices[1, 0])
    ey = np.float64(vertices[1, 1])
    ez = np.float64(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)

    for output_index in range(1, count):
        target = float(output_index) * effective_step
        while segment_length <= 0.0 or distance_acc + segment_length < target:
            if segment_length > 0.0:
                distance_acc += segment_length
            segment_index += 1
            if segment_index >= source_count:
                segment_index = 0
            sx = ex
            sy = ey
            sz = ez
            next_index = segment_index + 1
            if next_index >= source_count:
                next_index = 0
            ex = np.float64(vertices[next_index, 0])
            ey = np.float64(vertices[next_index, 1])
            ez = np.float64(vertices[next_index, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)

        if segment_length <= 0.0:
            out[output_index, 0] = np.float32(sx)
            out[output_index, 1] = np.float32(sy)
            out[output_index, 2] = np.float32(sz)
            continue

        t = (target - distance_acc) / segment_length
        out[output_index, 0] = np.float32(sx + t * dx)
        out[output_index, 1] = np.float32(sy + t * dy)
        out[output_index, 2] = np.float32(sz + t * dz)


@njit(cache=True)
def _resample_closed_matches_source_wide_nb(
    vertices: np.ndarray,
    step: float,
) -> bool:
    """float64退避の閉曲線kernelが入力頂点列を再現するか判定する。"""

    count = int(vertices.shape[0])
    total_length = _total_length_closed_wide_nb(vertices)
    if count < 3 or total_length <= 0.0:
        return True

    effective_step = float(step)
    if float(count - 1) * effective_step >= total_length:
        effective_step = total_length / float(count)

    segment_index = 0
    distance_acc = 0.0
    sx = np.float64(vertices[0, 0])
    sy = np.float64(vertices[0, 1])
    sz = np.float64(vertices[0, 2])
    ex = np.float64(vertices[1, 0])
    ey = np.float64(vertices[1, 1])
    ez = np.float64(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)

    for output_index in range(1, count):
        target = float(output_index) * effective_step
        while segment_length <= 0.0 or distance_acc + segment_length < target:
            if segment_length > 0.0:
                distance_acc += segment_length
            segment_index += 1
            if segment_index >= count:
                segment_index = 0
            sx = ex
            sy = ey
            sz = ez
            next_index = segment_index + 1
            if next_index >= count:
                next_index = 0
            ex = np.float64(vertices[next_index, 0])
            ey = np.float64(vertices[next_index, 1])
            ez = np.float64(vertices[next_index, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            segment_length = np.sqrt(dx * dx + dy * dy + dz * dz)

        if segment_length <= 0.0:
            x = np.float32(sx)
            y = np.float32(sy)
            z = np.float32(sz)
        else:
            t = (target - distance_acc) / segment_length
            x = np.float32(sx + t * dx)
            y = np.float32(sy + t * dy)
            z = np.float32(sz + t * dz)

        expected_x = vertices[output_index, 0]
        expected_y = vertices[output_index, 1]
        expected_z = vertices[output_index, 2]
        if x != expected_x or y != expected_y or z != expected_z:
            return False
        if x == 0.0 and np.signbit(x) != np.signbit(expected_x):
            return False
        if y == 0.0 and np.signbit(y) != np.signbit(expected_y):
            return False
        if z == 0.0 and np.signbit(z) != np.signbit(expected_z):
            return False
    return True


@njit(cache=True)
def _resample_closed_into_nb(
    vertices: np.ndarray,
    step: float,
    out: np.ndarray,
) -> None:
    if _resample_needs_float64_nb(vertices, True):
        _resample_closed_wide_into_nb(vertices, step, out)
    else:
        _resample_closed_fast_into_nb(vertices, step, out)


def resample_open_matches_source(vertices: np.ndarray, *, step: float) -> bool:
    """開曲線kernelが入力頂点列をbyte単位で再現するならTrueを返す。"""

    if bool(_resample_needs_float64_nb(vertices, False)):
        return bool(_resample_open_matches_source_wide_nb(vertices, float(step)))
    return bool(_resample_open_matches_source_fast_nb(vertices, float(step)))


def resample_closed_matches_source(vertices: np.ndarray, *, step: float) -> bool:
    """閉曲線kernelが入力頂点列をbyte単位で再現するならTrueを返す。"""

    if bool(_resample_needs_float64_nb(vertices, True)):
        return bool(_resample_closed_matches_source_wide_nb(vertices, float(step)))
    return bool(_resample_closed_matches_source_fast_nb(vertices, float(step)))


def resample_polylines(coords: np.ndarray, plan: ResamplePlan) -> tuple[np.ndarray, np.ndarray]:
    """上限検証済みplanに従い、packed polylineを一度だけ確保して再sampleする。"""

    if not plan.fits:
        raise ValueError("上限超過の ResamplePlan は実行できない")

    out_coords = np.empty((plan.total_vertices, 3), dtype=np.float32)
    out_offsets = np.empty((len(plan.lines) + 1,), dtype=np.int32)
    out_offsets[0] = 0
    for line_index, line in enumerate(plan.lines):
        source = coords[line.input_start : line.sample_stop]
        target = out_coords[line.output_start : line.output_stop]
        if line.mode == _RESAMPLE_COPY:
            target[:] = source
        elif line.mode == _RESAMPLE_CLOSED:
            _resample_closed_into_nb(source, float(plan.step), target[:-1])
            target[-1] = target[0]
        else:
            _resample_open_into_nb(source, float(plan.step), target)
        out_offsets[line_index + 1] = np.int32(line.output_stop)

    return out_coords, out_offsets
