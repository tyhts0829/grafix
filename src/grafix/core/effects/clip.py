"""
被切り抜きポリライン列を、閉曲線マスクの内側/外側だけにクリップする effect。

入力:
- base: 被切り抜き（開いたポリライン列を想定）
- mask: マスク（閉ループ列）

処理:
- マスクの全点から姿勢（平面）を推定し、両入力を XY 平面へ整列して 2D クリップする。
- 結果のポリラインを元の姿勢へ戻して出力する。
"""

from __future__ import annotations

import numpy as np
import pyclipper  # type: ignore[import-not-found, import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

from .util import PlanarFrame, empty_geom, pack_polylines

clip_meta = {
    "mode": ParamMeta(
        kind="choice",
        choices=("inside", "outside"),
        description="マスクの内側と外側のどちらを残すか選ぶ。",
    ),
    "draw_outline": ParamMeta(
        kind="bool",
        description="クリップ結果にマスク輪郭を加えて出力する。",
    ),
}

_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5


def _planarity_threshold(points: np.ndarray) -> float:
    if points.size == 0:
        return float(_PLANAR_EPS_ABS)
    p = points.astype(np.float64, copy=False)
    mins = np.min(p, axis=0)
    maxs = np.max(p, axis=0)
    diag = float(np.linalg.norm(maxs - mins))
    return max(float(_PLANAR_EPS_ABS), float(_PLANAR_EPS_REL) * diag)


def _remove_consecutive_duplicates(
    path: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if len(path) < 2:
        return path
    out = [path[0]]
    for pt in path[1:]:
        if pt != out[-1]:
            out.append(pt)
    return out


def _to_int_path_open(xy: np.ndarray, scale: int) -> list[tuple[int, int]] | None:
    if xy.shape[0] < 2:
        return None
    scaled = np.rint(xy.astype(np.float64, copy=False) * float(scale)).astype(
        np.int64, copy=False
    )
    path = [(int(p[0]), int(p[1])) for p in scaled]
    path = _remove_consecutive_duplicates(path)
    if len(path) < 2:
        return None
    if path[0] == path[-1]:
        path = path[:-1]
    return path if len(path) >= 2 else None


def _to_int_path_ring(xy: np.ndarray, scale: int) -> list[tuple[int, int]] | None:
    if xy.shape[0] < 3:
        return None
    scaled = np.rint(xy.astype(np.float64, copy=False) * float(scale)).astype(
        np.int64, copy=False
    )
    path = [(int(p[0]), int(p[1])) for p in scaled]
    path = _remove_consecutive_duplicates(path)
    if len(path) < 3:
        return None
    if path[0] == path[-1]:
        path = path[:-1]
    return path if len(path) >= 3 else None


@effect(meta=clip_meta, n_inputs=2)
def clip(
    base: GeomTuple,
    mask: GeomTuple,
    *,
    mode: str = "inside",  # "inside" | "outside"
    draw_outline: bool = False,
) -> GeomTuple:
    """XY 平面へ整列した上で、閉曲線マスクで線分列をクリップする。

    Parameters
    ----------
    base : tuple[np.ndarray, np.ndarray]
        被切り抜き対象（coords, offsets）。
    mask : tuple[np.ndarray, np.ndarray]
        閉曲線マスク（coords, offsets）。
    mode : str, default "inside"
        `"inside"` はマスク内側だけ残す。`"outside"` は外側だけ残す。
    draw_outline : bool, default False
        True のとき、マスク輪郭を追加で出力に含める。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        クリップ後の実体ジオメトリ（coords, offsets）。
    """
    scale_i = 1000
    draw_outline_b = bool(draw_outline)
    base_coords, base_offsets = base
    mask_coords, mask_offsets = mask
    if base_coords.shape[0] == 0:
        return base_coords, base_offsets
    if mask_coords.shape[0] == 0:
        return base_coords, base_offsets

    frame = PlanarFrame.from_points(mask_coords, mask_offsets)
    threshold = _planarity_threshold(mask_coords)
    if not frame.is_planar(threshold):
        return base_coords, base_offsets

    aligned_base = frame.to_local(base_coords)
    aligned_mask = frame.to_local(mask_coords)

    if float(np.max(np.abs(aligned_base[:, 2]))) > threshold:
        return base_coords, base_offsets

    mode_s = str(mode)
    if mode_s not in {"inside", "outside"}:
        return base_coords, base_offsets

    subject_paths: list[list[tuple[int, int]]] = []
    for i in range(int(base_offsets.size) - 1):
        s = int(base_offsets[i])
        e = int(base_offsets[i + 1])
        path = _to_int_path_open(aligned_base[s:e, 0:2], scale_i)
        if path is not None:
            subject_paths.append(path)

    clip_paths: list[list[tuple[int, int]]] = []
    for i in range(int(mask_offsets.size) - 1):
        s = int(mask_offsets[i])
        e = int(mask_offsets[i + 1])
        path = _to_int_path_ring(aligned_mask[s:e, 0:2], scale_i)
        if path is not None:
            clip_paths.append(path)

    if not clip_paths:
        return base_coords, base_offsets
    outline_lines: list[np.ndarray] = []
    if draw_outline_b:
        for ring in clip_paths:
            if len(ring) < 3:
                continue
            xy = np.asarray(ring + [ring[0]], dtype=np.float64) / float(scale_i)
            v = np.zeros((xy.shape[0], 3), dtype=np.float64)
            v[:, 0:2] = xy
            restored = frame.to_world(v)
            outline_lines.append(restored)

    if not subject_paths:
        if outline_lines:
            return pack_polylines(outline_lines)
        return base_coords, base_offsets

    pc = pyclipper.Pyclipper()  # type: ignore[attr-defined]
    pc.AddPaths(subject_paths, pyclipper.PT_SUBJECT, False)  # type: ignore[attr-defined]
    pc.AddPaths(clip_paths, pyclipper.PT_CLIP, True)  # type: ignore[attr-defined]

    cliptype = (
        pyclipper.CT_INTERSECTION if mode_s == "inside" else pyclipper.CT_DIFFERENCE  # type: ignore[attr-defined]
    )
    polytree = pc.Execute2(cliptype, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)  # type: ignore[attr-defined]
    out_paths = pyclipper.OpenPathsFromPolyTree(polytree)  # type: ignore[attr-defined]

    if not out_paths:
        if outline_lines:
            return pack_polylines(outline_lines)
        return empty_geom()

    out_lines: list[np.ndarray] = []
    for path in out_paths:
        if len(path) < 2:  # type: ignore
            continue
        xy = np.asarray(path, dtype=np.float64) / float(scale_i)
        v = np.zeros((xy.shape[0], 3), dtype=np.float64)
        v[:, 0:2] = xy
        restored = frame.to_world(v)
        out_lines.append(restored)

    out_lines.extend(outline_lines)
    if not out_lines:
        return empty_geom()
    return pack_polylines(out_lines)
