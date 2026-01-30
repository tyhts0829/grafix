"""閉曲線マスク（レンズ）の符号付き距離場で、入力線を局所的に変形する effect。

レンズ境界（SDF=0）で変形量が 0 になるようにブレンドし、
「境界付近だけ歪む」「内側へ向かって強まる」などの光学っぽい歪みを作る。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numba import njit, prange  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry, concat_realized_geometries

from .util import transform_back, transform_to_xy_plane

_AUTO_CLOSE_THRESHOLD_DEFAULT = 1e-3
_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

lens_meta = {
    "kind": ParamMeta(kind="choice", choices=("scale", "rotate", "shear", "swirl")),
    "strength": ParamMeta(kind="float", ui_min=0.0, ui_max=2.0),
    "profile": ParamMeta(kind="choice", choices=("band", "ramp")),
    "band": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
    "inside_only": ParamMeta(kind="bool"),
    "auto_center": ParamMeta(kind="bool"),
    "pivot": ParamMeta(kind="vec3", ui_min=-100.0, ui_max=100.0),
    "scale": ParamMeta(kind="float", ui_min=0.5, ui_max=3.0),
    "angle": ParamMeta(kind="float", ui_min=-180.0, ui_max=180.0),
    "shear": ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0),
    "show_lens": ParamMeta(kind="bool"),
    "keep_original": ParamMeta(kind="bool"),
}

lens_ui_visible = {
    "pivot": lambda v: not bool(v.get("auto_center", True)),
    "scale": lambda v: str(v.get("kind", "scale")) == "scale",
    "angle": lambda v: str(v.get("kind", "scale")) in {"rotate", "swirl"},
    "shear": lambda v: str(v.get("kind", "scale")) == "shear",
}


@dataclass(frozen=True, slots=True)
class _Ring2D:
    vertices: np.ndarray  # (N, 2) float64, closed (first == last)
    mins: np.ndarray  # (2,) float64
    maxs: np.ndarray  # (2,) float64


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _planarity_threshold(points: np.ndarray) -> float:
    if points.size == 0:
        return float(_PLANAR_EPS_ABS)
    p = points.astype(np.float64, copy=False)
    mins = np.min(p, axis=0)
    maxs = np.max(p, axis=0)
    diag = float(np.linalg.norm(maxs - mins))
    return max(float(_PLANAR_EPS_ABS), float(_PLANAR_EPS_REL) * diag)


def _apply_alignment(
    coords: np.ndarray, rotation_matrix: np.ndarray, z_offset: float
) -> np.ndarray:
    aligned = coords.astype(np.float64, copy=False) @ rotation_matrix.T
    aligned[:, 2] -= float(z_offset)
    return aligned


def _close_curve(points: np.ndarray, threshold: float) -> np.ndarray:
    if points.shape[0] < 2:
        return points
    dist = float(np.linalg.norm(points[0] - points[-1]))
    if dist <= float(threshold):
        return np.concatenate([points[:-1], points[0:1]], axis=0)
    return points


def _pick_representative_ring(base: RealizedGeometry) -> np.ndarray | None:
    coords = base.coords
    offsets = base.offsets
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        if e - s >= 3:
            return coords[s:e]
    return None


def _extract_rings_xy(
    coords_xy: np.ndarray,
    offsets: np.ndarray,
    *,
    auto_close_threshold: float,
) -> list[_Ring2D]:
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


@njit(cache=True)
def _evaluate_sdf_points_numba(
    points_xy: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
) -> np.ndarray:
    n_points = int(points_xy.shape[0])
    n_rings = int(ring_offsets.shape[0]) - 1

    out = np.empty((n_points,), dtype=np.float64)
    for pi in prange(n_points):
        x = float(points_xy[pi, 0])
        y = float(points_xy[pi, 1])
        min_ds = 1e300
        inside_parity = 0

        for ri in range(n_rings):
            s = int(ring_offsets[ri])
            e = int(ring_offsets[ri + 1])

            inside_possible = (
                x >= float(ring_mins[ri, 0])
                and x <= float(ring_maxs[ri, 0])
                and y >= float(ring_mins[ri, 1])
                and y <= float(ring_maxs[ri, 1])
            )

            inside = 0
            for k in range(s, e - 1):
                ax = float(ring_vertices[k, 0])
                ay = float(ring_vertices[k, 1])
                bx = float(ring_vertices[k + 1, 0])
                by = float(ring_vertices[k + 1, 1])

                dx = bx - ax
                dy = by - ay
                denom = dx * dx + dy * dy
                if denom <= 0.0:
                    ds = (x - ax) * (x - ax) + (y - ay) * (y - ay)
                else:
                    t = ((x - ax) * dx + (y - ay) * dy) / denom
                    if t < 0.0:
                        t = 0.0
                    elif t > 1.0:
                        t = 1.0
                    cx = ax + t * dx
                    cy = ay + t * dy
                    ds = (x - cx) * (x - cx) + (y - cy) * (y - cy)
                if ds < min_ds:
                    min_ds = ds

                if inside_possible and ((ay > y) != (by > y)):
                    x_int = ax + (y - ay) * (bx - ax) / (by - ay)
                    if x < x_int:
                        inside ^= 1

            inside_parity ^= inside

        dist = math.sqrt(min_ds)
        if inside_parity != 0:
            dist = -dist
        out[pi] = dist

    return out


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t0 = np.clip(t, 0.0, 1.0)
    return t0 * t0 * (3.0 - 2.0 * t0)


@effect(meta=lens_meta, ui_visible=lens_ui_visible, n_inputs=2)
def lens(
    inputs: Sequence[RealizedGeometry],
    *,
    kind: str = "scale",  # "scale" | "rotate" | "shear" | "swirl"
    strength: float = 1.0,
    profile: str = "band",  # "band" | "ramp"
    band: float = 20.0,
    inside_only: bool = True,
    auto_center: bool = True,
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.4,
    angle: float = 30.0,
    shear: tuple[float, float, float] = (0.2, 0.0, 0.0),
    show_lens: bool = False,
    keep_original: bool = False,
) -> RealizedGeometry:
    """SDF レンズで局所変形する。

    Parameters
    ----------
    inputs : Sequence[RealizedGeometry]
        `inputs[0]` が変形対象、`inputs[1]` がレンズ（閉曲線群）。
    kind : str, default "scale"
        変形の種類（"scale" | "rotate" | "shear" | "swirl"）。
    strength : float, default 1.0
        変形の強さ（ブレンド係数）。
    profile : str, default "band"
        距離プロファイル（"band" は境界付近だけ、"ramp" は内側へ向かって増える）。
    band : float, default 20.0
        境界からの距離スケール [mm]。0 以下はハード（一定）扱い。
    inside_only : bool, default True
        True ならレンズ内側（d<0）のみ変形する。False なら両側（|d|）で効く。
    auto_center : bool, default True
        True ならレンズ AABB の中心を変形中心にする。
    pivot : tuple[float, float, float], default (0.0,0.0,0.0)
        `auto_center=False` のときの変形中心（3D。内部ではレンズ平面へ整列して扱う）。
    scale : float, default 1.4
        `kind="scale"` の倍率（uniform）。
    angle : float, default 30.0
        `kind in {"rotate","swirl"}` の角度 [deg]。
    shear : tuple[float, float, float], default (0.2,0.0,0.0)
        `kind="shear"` の shear 係数（x,y を使用、z は無視）。
    show_lens : bool, default False
        True のとき、変形後にレンズ（mask）入力も出力に含める。
    keep_original : bool, default False
        True のとき、変形後に加えて元の入力も出力に含める。

    Returns
    -------
    RealizedGeometry
        変形後の実体ジオメトリ。
    """
    if not inputs:
        return _empty_geometry()
    if len(inputs) < 2:
        return inputs[0]

    base = inputs[0]
    lens_geom = inputs[1]

    def _with_extras(result: RealizedGeometry) -> RealizedGeometry:
        out_geoms = [result]
        if bool(keep_original):
            out_geoms.append(base)
        if bool(show_lens):
            out_geoms.append(lens_geom)
        return (
            concat_realized_geometries(*out_geoms)
            if len(out_geoms) > 1
            else out_geoms[0]
        )

    if base.coords.shape[0] == 0:
        return _with_extras(base)
    if lens_geom.coords.shape[0] == 0:
        return _with_extras(base)

    strength_f = float(strength)
    if not math.isfinite(strength_f) or strength_f == 0.0:
        return _with_extras(base)

    kind_s = str(kind)
    if kind_s not in {"scale", "rotate", "shear", "swirl"}:
        return _with_extras(base)

    profile_s = str(profile)
    if profile_s not in {"band", "ramp"}:
        return _with_extras(base)

    band_f = float(band)
    if not math.isfinite(band_f):
        return _with_extras(base)

    scale_f = float(scale)
    angle_rad = float(np.deg2rad(float(angle)))
    shx = float(shear[0])
    shy = float(shear[1])

    if kind_s == "scale" and scale_f == 1.0:
        return _with_extras(base)
    if kind_s in {"rotate", "swirl"} and angle_rad == 0.0:
        return _with_extras(base)
    if kind_s == "shear" and shx == 0.0 and shy == 0.0:
        return _with_extras(base)

    rep = _pick_representative_ring(lens_geom)
    if rep is None:
        return _with_extras(base)

    _rep_aligned, rotation_matrix, z_offset = transform_to_xy_plane(rep)
    aligned_base = _apply_alignment(base.coords, rotation_matrix, float(z_offset))
    aligned_lens = _apply_alignment(lens_geom.coords, rotation_matrix, float(z_offset))

    threshold = _planarity_threshold(rep)
    if float(np.max(np.abs(aligned_lens[:, 2]))) > threshold:
        return _with_extras(base)
    if float(np.max(np.abs(aligned_base[:, 2]))) > threshold:
        return _with_extras(base)

    rings = _extract_rings_xy(
        aligned_lens,
        lens_geom.offsets,
        auto_close_threshold=float(_AUTO_CLOSE_THRESHOLD_DEFAULT),
    )
    if not rings:
        return _with_extras(base)

    mins = np.min(np.stack([r0.mins for r0 in rings], axis=0), axis=0)
    maxs = np.max(np.stack([r0.maxs for r0 in rings], axis=0), axis=0)

    if bool(auto_center):
        center2 = 0.5 * (mins + maxs)
    else:
        pivot3 = np.array(
            [[float(pivot[0]), float(pivot[1]), float(pivot[2])]], dtype=np.float64
        )
        pivot_xy = _apply_alignment(pivot3, rotation_matrix, float(z_offset))[0, 0:2]
        center2 = pivot_xy.astype(np.float64, copy=False)

    ring_vertices, ring_offsets, ring_mins, ring_maxs = _pack_rings(rings)
    base_xy = aligned_base[:, 0:2].astype(np.float64, copy=False)
    d = _evaluate_sdf_points_numba(
        base_xy, ring_vertices, ring_offsets, ring_mins, ring_maxs
    )

    if band_f <= 0.0:
        if bool(inside_only):
            w = (d < 0.0).astype(np.float64)
        else:
            w = np.ones_like(d, dtype=np.float64)
    else:
        if bool(inside_only):
            t = (-d) / float(band_f)
        else:
            t = np.abs(d) / float(band_f)
        s = _smoothstep(t)
        if profile_s == "ramp":
            w = s
        else:
            w = 4.0 * s * (1.0 - s)
        if bool(inside_only):
            w = np.where(d < 0.0, w, 0.0)

    max_w = float(np.max(w)) if w.size else 0.0
    if not math.isfinite(max_w) or max_w <= 0.0:
        return _with_extras(base)

    mix = (strength_f * w).astype(np.float64, copy=False)
    mix = np.clip(mix, 0.0, 1e9)

    v = base_xy - center2[None, :]

    if kind_s == "scale":
        target_xy = center2[None, :] + float(scale_f) * v
    elif kind_s == "rotate":
        c = float(math.cos(angle_rad))
        s_ = float(math.sin(angle_rad))
        rx = c * v[:, 0] - s_ * v[:, 1]
        ry = s_ * v[:, 0] + c * v[:, 1]
        target_xy = center2[None, :] + np.stack([rx, ry], axis=1)
    elif kind_s == "shear":
        rx = v[:, 0] + float(shx) * v[:, 1]
        ry = float(shy) * v[:, 0] + v[:, 1]
        target_xy = center2[None, :] + np.stack([rx, ry], axis=1)
    else:  # kind_s == "swirl"
        span = maxs - mins
        r_ref = 0.5 * float(np.linalg.norm(span))
        if not math.isfinite(r_ref) or r_ref <= 1e-12:
            return _with_extras(base)
        r = np.sqrt(v[:, 0] * v[:, 0] + v[:, 1] * v[:, 1])
        theta = angle_rad * (r / r_ref)
        c = np.cos(theta)
        s_ = np.sin(theta)
        rx = c * v[:, 0] - s_ * v[:, 1]
        ry = s_ * v[:, 0] + c * v[:, 1]
        target_xy = center2[None, :] + np.stack([rx, ry], axis=1)

    out_xy = base_xy + mix[:, None] * (target_xy - base_xy)

    out3 = np.zeros((out_xy.shape[0], 3), dtype=np.float64)
    out3[:, 0:2] = out_xy
    restored = transform_back(out3, rotation_matrix, float(z_offset)).astype(
        np.float32, copy=False
    )
    out = RealizedGeometry(coords=restored, offsets=base.offsets)
    return _with_extras(out)


__all__ = ["lens", "lens_meta"]
