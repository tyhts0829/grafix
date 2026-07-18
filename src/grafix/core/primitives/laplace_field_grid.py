"""
どこで: `src/grafix/core/primitives/laplace_field_grid.py`。共形写像ベースの直交格子プリミティブ。
何を: W=u+iv 平面の直交格子を、解析写像 z=f(W) で z 平面へ写してポリライン列として返す。
なぜ: ラプラス場に由来する “等ポテンシャル線 / 流線” 風の直交網を、安定に生成できるようにするため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

laplace_field_grid_meta = {
    "preset": ParamMeta(
        kind="choice",
        choices=("cylinder_uniform", "mobius", "exp"),
        description="W 平面の直交格子へ適用する解析写像の種類を選択します。",
    ),
    "u_min": ParamMeta(
        kind="float",
        ui_min=-10.0,
        ui_max=10.0,
        description="写像元 W=u+iv 平面で描画する u 座標の下限を指定します。",
    ),
    "u_max": ParamMeta(
        kind="float",
        ui_min=-10.0,
        ui_max=10.0,
        description="写像元 W=u+iv 平面で描画する u 座標の上限を指定します。",
    ),
    "v_min": ParamMeta(
        kind="float",
        ui_min=-10.0,
        ui_max=10.0,
        description="写像元 W=u+iv 平面で描画する v 座標の下限を指定します。",
    ),
    "v_max": ParamMeta(
        kind="float",
        ui_min=-10.0,
        ui_max=10.0,
        description="写像元 W=u+iv 平面で描画する v 座標の上限を指定します。",
    ),
    "n_u": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=200,
        description="u を固定して v 方向へたどる格子線の本数を指定します。",
    ),
    "n_v": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=200,
        description="v を固定して u 方向へたどる格子線の本数を指定します。",
    ),
    "samples": ParamMeta(
        kind="int",
        ui_min=2,
        ui_max=4000,
        description="写像前の各格子線を構成するサンプリング点数を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="写像後の格子全体を平行移動する XYZ 座標を指定します。",
    ),
    "scale": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="写像後の格子全体に適用する等方スケールを指定します。",
    ),
    "rotate": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=360.0,
        description="写像後の格子を原点まわりに回転させる角度を度単位で指定します。",
    ),
    "clip": ParamMeta(
        kind="bool",
        description="変換後の点を指定した XY 矩形内に限定し、連続区間へ分割します。",
    ),
    "clip_xmin": ParamMeta(
        kind="float",
        ui_min=-200.0,
        ui_max=200.0,
        description="変換後の座標でクリップ矩形の X 下限を指定します。",
    ),
    "clip_xmax": ParamMeta(
        kind="float",
        ui_min=-200.0,
        ui_max=200.0,
        description="変換後の座標でクリップ矩形の X 上限を指定します。",
    ),
    "clip_ymin": ParamMeta(
        kind="float",
        ui_min=-200.0,
        ui_max=200.0,
        description="変換後の座標でクリップ矩形の Y 下限を指定します。",
    ),
    "clip_ymax": ParamMeta(
        kind="float",
        ui_min=-200.0,
        ui_max=200.0,
        description="変換後の座標でクリップ矩形の Y 上限を指定します。",
    ),
    # --- cylinder_uniform ---
    "a": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=50.0,
        description="円柱一様流写像で障害物となる境界円の半径を指定します。",
    ),
    "U": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=5.0,
        description="円柱一様流写像で W 座標を除算する流速スケールを指定します。",
    ),
    "gap": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=0.05,
        description="格子線を境界円から離すため、半径に加える相対的な隙間を指定します。",
    ),
    "draw_boundary": ParamMeta(
        kind="bool",
        description="円柱一様流の格子線に障害物の境界円を追加します。",
    ),
    "boundary_samples": ParamMeta(
        kind="int",
        ui_min=3,
        ui_max=4000,
        description="障害物の境界円を構成するサンプリング点数を指定します。",
    ),
    # --- mobius ---
    "alpha_re": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における α の実部を指定します。",
    ),
    "alpha_im": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における α の虚部を指定します。",
    ),
    "beta_re": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における β の実部を指定します。",
    ),
    "beta_im": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における β の虚部を指定します。",
    ),
    "gamma_re": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における γ の実部を指定します。",
    ),
    "gamma_im": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における γ の虚部を指定します。",
    ),
    "delta_re": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における δ の実部を指定します。",
    ),
    "delta_im": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="Möbius 写像 (αW+β)/(γW+δ) における δ の虚部を指定します。",
    ),
    # --- exp ---
    "k_re": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="指数写像 exp(kW) で W に掛ける複素係数 k の実部を指定します。",
    ),
    "k_im": ParamMeta(
        kind="float",
        ui_min=-5.0,
        ui_max=5.0,
        description="指数写像 exp(kW) で W に掛ける複素係数 k の虚部を指定します。",
    ),
}


def _empty_geometry() -> GeomTuple:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


def _lines_to_realized(lines: list[np.ndarray]) -> GeomTuple:
    if not lines:
        return _empty_geometry()
    coords = np.concatenate(lines, axis=0).astype(np.float32, copy=False)
    offsets = np.empty((len(lines) + 1,), dtype=np.int32)
    offsets[0] = 0
    acc = 0
    for i, ln in enumerate(lines):
        acc += int(ln.shape[0])
        offsets[i + 1] = acc
    return coords, offsets


def _split_by_mask(points: np.ndarray, mask: np.ndarray) -> list[np.ndarray]:
    if points.shape[0] != mask.shape[0]:
        raise ValueError("laplace_field_grid: mask の長さが points と一致しない")
    if points.shape[0] < 2:
        return []

    out: list[np.ndarray] = []
    n = int(points.shape[0])
    start = -1
    for i in range(n):
        if bool(mask[i]):
            if start < 0:
                start = i
        else:
            if start >= 0:
                if i - start >= 2:
                    out.append(points[start:i])
                start = -1
    if start >= 0 and n - start >= 2:
        out.append(points[start:n])
    return out


def _map_cylinder_uniform(W: np.ndarray, *, a: float, U: float) -> np.ndarray:
    w = W / np.complex128(U)
    if a == 0.0:
        return w
    disc = w * w - np.complex128(4.0 * (a * a))
    root = np.sqrt(disc)
    z1 = 0.5 * (w + root)
    z2 = 0.5 * (w - root)
    choose_z1 = np.abs(z1) >= np.abs(z2)
    return np.where(choose_z1, z1, z2)


def _map_mobius(
    W: np.ndarray,
    *,
    alpha: complex,
    beta: complex,
    gamma: complex,
    delta: complex,
) -> np.ndarray:
    return (alpha * W + beta) / (gamma * W + delta)


def _map_exp(W: np.ndarray, *, k: complex) -> np.ndarray:
    return np.exp(k * W)


def _apply_transform(
    points: np.ndarray,
    *,
    center: tuple[float, float, float],
    scale: float,
    rotate_deg: float,
) -> np.ndarray:
    try:
        cx, cy, cz = center
    except Exception as exc:
        raise ValueError(
            "laplace_field_grid の center は長さ 3 のシーケンスである必要がある"
        ) from exc

    s_f = float(scale)
    theta = math.radians(float(rotate_deg))
    c = math.cos(theta)
    s = math.sin(theta)

    out = points.astype(np.float64, copy=True)
    out[:, 0:2] *= s_f

    if theta != 0.0:
        x = out[:, 0].copy()
        y = out[:, 1].copy()
        out[:, 0] = c * x - s * y
        out[:, 1] = s * x + c * y

    out[:, 0] += float(cx)
    out[:, 1] += float(cy)
    out[:, 2] += float(cz)
    return out


def _clip_and_split(
    points: np.ndarray,
    *,
    enabled: bool,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
) -> list[np.ndarray]:
    if not enabled:
        return [points]
    inside = (
        (points[:, 0] >= float(xmin))
        & (points[:, 0] <= float(xmax))
        & (points[:, 1] >= float(ymin))
        & (points[:, 1] <= float(ymax))
    )
    return _split_by_mask(points, inside)


LAPLACE_FIELD_GRID_UI_VISIBLE = {
    "clip_xmin": lambda v: bool(v.get("clip", False)),
    "clip_xmax": lambda v: bool(v.get("clip", False)),
    "clip_ymin": lambda v: bool(v.get("clip", False)),
    "clip_ymax": lambda v: bool(v.get("clip", False)),
    "a": lambda v: str(v.get("preset", "cylinder_uniform")) == "cylinder_uniform",
    "U": lambda v: str(v.get("preset", "cylinder_uniform")) == "cylinder_uniform",
    "gap": lambda v: str(v.get("preset", "cylinder_uniform")) == "cylinder_uniform",
    "draw_boundary": lambda v: str(v.get("preset", "cylinder_uniform"))
    == "cylinder_uniform",
    "boundary_samples": lambda v: str(v.get("preset", "cylinder_uniform"))
    == "cylinder_uniform"
    and bool(v.get("draw_boundary", True)),
    "alpha_re": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "alpha_im": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "beta_re": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "beta_im": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "gamma_re": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "gamma_im": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "delta_re": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "delta_im": lambda v: str(v.get("preset", "cylinder_uniform")) == "mobius",
    "k_re": lambda v: str(v.get("preset", "cylinder_uniform")) == "exp",
    "k_im": lambda v: str(v.get("preset", "cylinder_uniform")) == "exp",
}


@primitive(meta=laplace_field_grid_meta, ui_visible=LAPLACE_FIELD_GRID_UI_VISIBLE)
def laplace_field_grid(
    *,
    preset: str = "cylinder_uniform",
    u_min: float = -6.0,
    u_max: float = 6.0,
    v_min: float = -6.0,
    v_max: float = 6.0,
    n_u: int | float = 45,
    n_v: int | float = 45,
    samples: int | float = 900,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
    rotate: float = 0.0,
    clip: bool = False,
    clip_xmin: float = -10.0,
    clip_xmax: float = 10.0,
    clip_ymin: float = -10.0,
    clip_ymax: float = 10.0,
    a: float = 1.0,
    U: float = 1.0,
    gap: float = 0.002,
    draw_boundary: bool = True,
    boundary_samples: int | float = 720,
    alpha_re: float = 1.0,
    alpha_im: float = 0.0,
    beta_re: float = 0.0,
    beta_im: float = 0.0,
    gamma_re: float = 0.0,
    gamma_im: float = 0.0,
    delta_re: float = 1.0,
    delta_im: float = 0.0,
    k_re: float = 1.0,
    k_im: float = 0.0,
) -> GeomTuple:
    """共形写像ベースの直交格子（等ポテンシャル線/流線風）を生成する。

    Parameters
    ----------
    preset : str, default "cylinder_uniform"
        `"cylinder_uniform" | "mobius" | "exp"`。
    u_min, u_max, v_min, v_max : float
        W=u+iv 平面での描画範囲。
    n_u, n_v : int | float, optional
        `u=const`（縦線）/ `v=const`（横線）の本数。
    samples : int | float, optional
        1 本あたりのサンプル点数（2 以上）。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率。
    rotate : float, optional
        回転角 [deg]（XY 平面、origin 回り）。
    clip : bool, default False
        True のとき矩形クリップ（AABB）で線を分割する。
        交点補間はせず、範囲外点を落として連続区間を残す。
    clip_xmin, clip_xmax, clip_ymin, clip_ymax : float
        クリップ矩形（clip=True のときのみ使用）。
    a, U, gap : float
        `preset="cylinder_uniform"` 用。円柱半径/スケール/隙間比。
        `U=0` の場合は写像が定義できないため、格子線は省略し（必要なら）境界円のみ描画する。
    draw_boundary : bool, default True
        `preset="cylinder_uniform"` で境界円を追加する。
    boundary_samples : int | float, optional
        境界円のサンプル数（3 以上）。
    alpha_re..delta_im : float
        `preset="mobius"` の係数（複素数を re/im に分解して指定）。
    k_re, k_im : float
        `preset="exp"` の係数（複素数を re/im に分解して指定）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ポリライン列としての実体ジオメトリ（coords, offsets）。
    """

    preset_s = str(preset)

    n_u_i = int(n_u)
    n_v_i = int(n_v)
    samples_i = int(samples)
    if n_u_i < 0 or n_v_i < 0:
        raise ValueError("laplace_field_grid の n_u/n_v は 0 以上が必要")
    if samples_i < 2:
        raise ValueError("laplace_field_grid の samples は 2 以上が必要")

    u_min_f = float(u_min)
    u_max_f = float(u_max)
    v_min_f = float(v_min)
    v_max_f = float(v_max)
    if u_min_f > u_max_f:
        u_min_f, u_max_f = u_max_f, u_min_f
    if v_min_f > v_max_f:
        v_min_f, v_max_f = v_max_f, v_min_f

    clip_b = bool(clip)
    if clip_b:
        xmin = float(clip_xmin)
        xmax = float(clip_xmax)
        ymin = float(clip_ymin)
        ymax = float(clip_ymax)
        if not (xmin < xmax and ymin < ymax):
            raise ValueError("laplace_field_grid の clip 矩形が不正（min < max が必要）")
    else:
        xmin = xmax = ymin = ymax = 0.0

    u_line_values = (
        np.linspace(u_min_f, u_max_f, num=n_u_i, dtype=np.float64)
        if n_u_i > 0
        else np.empty((0,), dtype=np.float64)
    )
    v_line_values = (
        np.linspace(v_min_f, v_max_f, num=n_v_i, dtype=np.float64)
        if n_v_i > 0
        else np.empty((0,), dtype=np.float64)
    )
    v_samples = np.linspace(v_min_f, v_max_f, num=samples_i, dtype=np.float64)
    u_samples = np.linspace(u_min_f, u_max_f, num=samples_i, dtype=np.float64)

    lines_out: list[np.ndarray] = []

    def emit_line_from_z(z: np.ndarray, *, base_mask: np.ndarray) -> None:
        points = np.zeros((z.shape[0], 3), dtype=np.float64)
        points[:, 0] = z.real
        points[:, 1] = z.imag
        pieces = _split_by_mask(points, base_mask)
        for piece in pieces:
            transformed = _apply_transform(
                piece, center=center, scale=float(scale), rotate_deg=float(rotate)
            )
            for clipped in _clip_and_split(
                transformed, enabled=clip_b, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax
            ):
                lines_out.append(clipped.astype(np.float32, copy=False))

    if preset_s == "cylinder_uniform":
        a_f = float(a)
        U_f = float(U)
        gap_f = float(gap)
        if a_f < 0.0:
            raise ValueError("laplace_field_grid の a は 0 以上が必要")
        if gap_f < 0.0:
            raise ValueError("laplace_field_grid の gap は 0 以上が必要")
        if U_f == 0.0:
            if bool(draw_boundary) and a_f > 0.0:
                boundary_n = int(boundary_samples)
                if boundary_n < 3:
                    raise ValueError(
                        "laplace_field_grid の boundary_samples は 3 以上が必要"
                    )
                theta = np.linspace(
                    0.0, 2.0 * math.pi, num=boundary_n, dtype=np.float64
                )
                z = np.complex128(a_f) * np.exp(np.complex128(1j) * theta)
                base_mask = np.isfinite(z.real) & np.isfinite(z.imag)
                emit_line_from_z(z, base_mask=base_mask)
            return _lines_to_realized(lines_out)

        radius_min = a_f * (1.0 + gap_f)

        for u in u_line_values:
            W = np.complex128(float(u)) + np.complex128(1j) * v_samples.astype(
                np.complex128, copy=False
            )
            z = _map_cylinder_uniform(W, a=a_f, U=U_f)
            finite = np.isfinite(z.real) & np.isfinite(z.imag)
            base_mask = finite & (np.abs(z) >= radius_min)
            emit_line_from_z(z, base_mask=base_mask)

        for v in v_line_values:
            W = u_samples.astype(np.complex128, copy=False) + np.complex128(1j) * float(
                v
            )
            z = _map_cylinder_uniform(W, a=a_f, U=U_f)
            finite = np.isfinite(z.real) & np.isfinite(z.imag)
            base_mask = finite & (np.abs(z) >= radius_min)
            emit_line_from_z(z, base_mask=base_mask)

        if bool(draw_boundary) and a_f > 0.0:
            boundary_n = int(boundary_samples)
            if boundary_n < 3:
                raise ValueError("laplace_field_grid の boundary_samples は 3 以上が必要")
            theta = np.linspace(0.0, 2.0 * math.pi, num=boundary_n, dtype=np.float64)
            z = np.complex128(a_f) * np.exp(np.complex128(1j) * theta)
            base_mask = np.isfinite(z.real) & np.isfinite(z.imag)
            emit_line_from_z(z, base_mask=base_mask)

    elif preset_s == "mobius":
        alpha = complex(float(alpha_re), float(alpha_im))
        beta = complex(float(beta_re), float(beta_im))
        gamma = complex(float(gamma_re), float(gamma_im))
        delta = complex(float(delta_re), float(delta_im))
        det = alpha * delta - beta * gamma
        if abs(det) < 1e-12:
            raise ValueError("laplace_field_grid の mobius 係数が不正（alpha*delta - beta*gamma ≈ 0）")

        for u in u_line_values:
            W = np.complex128(float(u)) + np.complex128(1j) * v_samples.astype(
                np.complex128, copy=False
            )
            z = _map_mobius(W, alpha=alpha, beta=beta, gamma=gamma, delta=delta)
            base_mask = np.isfinite(z.real) & np.isfinite(z.imag)
            emit_line_from_z(z, base_mask=base_mask)

        for v in v_line_values:
            W = u_samples.astype(np.complex128, copy=False) + np.complex128(1j) * float(
                v
            )
            z = _map_mobius(W, alpha=alpha, beta=beta, gamma=gamma, delta=delta)
            base_mask = np.isfinite(z.real) & np.isfinite(z.imag)
            emit_line_from_z(z, base_mask=base_mask)

    elif preset_s == "exp":
        k = complex(float(k_re), float(k_im))
        for u in u_line_values:
            W = np.complex128(float(u)) + np.complex128(1j) * v_samples.astype(
                np.complex128, copy=False
            )
            z = _map_exp(W, k=k)
            base_mask = np.isfinite(z.real) & np.isfinite(z.imag)
            emit_line_from_z(z, base_mask=base_mask)

        for v in v_line_values:
            W = u_samples.astype(np.complex128, copy=False) + np.complex128(1j) * float(
                v
            )
            z = _map_exp(W, k=k)
            base_mask = np.isfinite(z.real) & np.isfinite(z.imag)
            emit_line_from_z(z, base_mask=base_mask)

    else:
        raise ValueError(f"laplace_field_grid の preset が不明: {preset_s!r}")

    return _lines_to_realized(lines_out)
