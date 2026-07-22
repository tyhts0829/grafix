"""
どこで: `src/grafix/primitives/torus.py`。トーラスプリミティブの実体生成。
何を: major/minor 半径と分割数から、子午線+緯線の閉ポリライン列を構築する。
なぜ: 3D プリミティブの基本形状として、回転や変形 effect の入力に使えるようにするため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.operation_authoring import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

torus_meta = {
    "major_radius": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=100.0,
        description="トーラス中心から管の中心線までの大半径を指定します。",
    ),
    "minor_radius": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=100.0,
        description="管の中心線から表面までの小半径を指定します。",
    ),
    "major_segments": ParamMeta(
        kind="int",
        ui_min=3,
        ui_max=256,
        description="大円方向の分割数と子午線の本数を指定します。",
    ),
    "minor_segments": ParamMeta(
        kind="int",
        ui_min=3,
        ui_max=256,
        description="管断面方向の分割数と緯線の本数を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="トーラス全体を平行移動する XYZ 座標を指定します。",
    ),
    "scale": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="指定した二つの半径で生成した形状に適用する等方スケールを指定します。",
    ),
}


@primitive(meta=torus_meta)
def torus(
    *,
    major_radius: float = 1.0,
    minor_radius: float = 0.5,
    major_segments: int = 32,
    minor_segments: int = 16,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> GeomTuple:
    """トーラスのワイヤーフレーム（子午線+緯線）を生成する。

    Parameters
    ----------
    major_radius : float, optional
        0 以上の大半径。
    minor_radius : float, optional
        0 以上の小半径。
    major_segments : int, optional
        major 方向の分割数。3 以上。
    minor_segments : int, optional
        minor 方向の分割数。3 以上。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率 s。縦横比変更は effect を使用する。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        子午線 `major_segments` 本と緯線 `minor_segments` 本からなる閉ポリライン列（coords, offsets）。

    Raises
    ------
    ValueError
        半径が負、または ``major_segments`` / ``minor_segments`` が 3 未満の場合。
    """
    major_r = major_radius
    minor_r = minor_radius

    if major_r < 0.0 or minor_r < 0.0:
        raise ValueError("torus の major_radius/minor_radius は 0 以上である必要がある")
    if major_segments < 3 or minor_segments < 3:
        raise ValueError("torus の major_segments/minor_segments は 3 以上である必要がある")
    major_n = major_segments
    minor_n = minor_segments

    output_vertices = major_n * (minor_n + 1) + minor_n * (major_n + 1)
    output_lines = major_n + minor_n
    # sin/cos、broadcast 後の座標成分、stack 前後を含む概算。output 本体とは別枠。
    scratch_bytes = major_n * minor_n * 3 * 4
    ensure_geometry_output(
        "torus",
        vertices=output_vertices,
        lines=output_lines,
        scratch_bytes=scratch_bytes,
        hint="major_segments と minor_segments を減らしてください",
    )

    cx, cy, cz = center
    s_f = scale

    theta = np.linspace(
        0.0,
        2.0 * math.pi,
        num=major_n,
        endpoint=False,
        dtype=np.float32,
    )
    phi = np.linspace(
        0.0,
        2.0 * math.pi,
        num=minor_n,
        endpoint=False,
        dtype=np.float32,
    )

    cos_theta = np.cos(theta, dtype=np.float32)
    sin_theta = np.sin(theta, dtype=np.float32)
    cos_phi = np.cos(phi, dtype=np.float32)
    sin_phi = np.sin(phi, dtype=np.float32)

    major_r32 = np.float32(major_r)
    minor_r32 = np.float32(minor_r)

    # 公開する出力順を「子午線群、緯線群」とし、最終配列へ直接書き込む。
    # stack/concatenate を重ねないことで、major_n * minor_n に比例する一時配列を減らす。
    coords = np.empty((output_vertices, 3), dtype=np.float32)

    # --- 子午線（major 角ごとに 1 本）---
    meridian_len = minor_n + 1
    meridian_vertices = major_n * meridian_len
    coords_m = coords[:meridian_vertices].reshape(major_n, meridian_len, 3)

    r_phi = major_r32 + minor_r32 * cos_phi  # (minor_n,)
    coords_m[:, :-1, 0] = r_phi[None, :] * cos_theta[:, None]
    coords_m[:, :-1, 1] = r_phi[None, :] * sin_theta[:, None]
    z_phi = minor_r32 * sin_phi
    coords_m[:, :-1, 2] = z_phi[None, :]
    coords_m[:, -1, :] = coords_m[:, 0, :]

    # --- 緯線（minor 角ごとに 1 本）---
    parallel_len = major_n + 1
    coords_p = coords[meridian_vertices:].reshape(minor_n, parallel_len, 3)

    r_ring = major_r32 + minor_r32 * cos_phi  # (minor_n,)
    coords_p[:, :-1, 0] = r_ring[:, None] * cos_theta[None, :]
    coords_p[:, :-1, 1] = r_ring[:, None] * sin_theta[None, :]
    z_p = (minor_r32 * sin_phi)[:, None]
    coords_p[:, :-1, 2] = z_p
    coords_p[:, -1, :] = coords_p[:, 0, :]

    polyline_count = major_n + minor_n
    offsets = np.empty((polyline_count + 1,), dtype=np.int32)
    offsets[0] = 0
    offsets[1 : major_n + 1] = np.arange(1, major_n + 1, dtype=np.int32) * np.int32(
        meridian_len
    )
    base = np.int32(major_n * meridian_len)
    offsets[major_n + 1 :] = base + np.arange(
        1, minor_n + 1, dtype=np.int32
    ) * np.int32(parallel_len)

    if (cx, cy, cz) != (0.0, 0.0, 0.0) or s_f != 1.0:
        center_vec = np.array([cx, cy, cz], dtype=np.float32)
        coords = coords * np.float32(s_f) + center_vec

    return coords, offsets
