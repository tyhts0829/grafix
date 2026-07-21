"""
どこで: `src/grafix/core/primitives/wave.py`。周期波形 primitive の実体生成。
何を: 単調な局所 X 軸に沿う sine / triangle 波を、XY 平面上の開ポリラインにする。
なぜ: `lissajous` や変形 effect では代替できない、基本的な一方向波形を提供するため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

_KIND_ORDER = ("sine", "triangle")
_SCRATCH_BYTES_PER_SAMPLE = 4 * np.dtype(np.float64).itemsize
_FLOAT32_MAX = float(np.finfo(np.float32).max)

wave_meta = {
    "kind": ParamMeta(
        kind="choice",
        choices=_KIND_ORDER,
        description="滑らかな正弦波または区分線形の三角波を選択します。",
    ),
    "length": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="回転前の局所 X 軸に沿う始点から終点までの長さを指定します。",
    ),
    "amplitude": ParamMeta(
        kind="float",
        ui_min=-200.0,
        ui_max=200.0,
        description="局所 Y 軸方向の符号付き振幅を指定します。",
    ),
    "cycles": ParamMeta(
        kind="float",
        ui_min=-20.0,
        ui_max=20.0,
        description="始点から終点までに進む符号付き周期数を指定します。",
    ),
    "phase": ParamMeta(
        kind="float",
        ui_min=-360.0,
        ui_max=360.0,
        description="始点における波形の位相を度単位で指定します。",
    ),
    "samples": ParamMeta(
        kind="int",
        ui_min=2,
        ui_max=8000,
        description="始点と終点を含むポリラインの頂点数を指定します。",
    ),
    "angle": ParamMeta(
        kind="float",
        ui_min=-180.0,
        ui_max=180.0,
        description="局所波形を XY 平面内で反時計回りに回転する角度を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=-300.0,
        ui_max=300.0,
        description="回転と平行移動の基準となる波形中央の XYZ 座標を指定します。",
    ),
}


def _assign_float32_component(
    destination: np.ndarray,
    values: np.ndarray,
    *,
    axis: str,
) -> None:
    """有限かつfloat32で表現可能な座標成分だけを出力へ格納する。"""

    minimum = float(values.min())
    maximum = float(values.max())
    if (
        not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum < -_FLOAT32_MAX
        or maximum > _FLOAT32_MAX
    ):
        raise ValueError(
            f"wave の出力 {axis} 座標は有限な float32 の範囲である必要がある"
        )
    destination[:] = values


@primitive(meta=wave_meta)
def wave(
    *,
    kind: str = "sine",
    length: float = 1.0,
    amplitude: float = 0.25,
    cycles: float = 3.0,
    phase: float = 0.0,
    samples: int = 256,
    angle: float = 0.0,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """単調な局所X座標に沿う周期波形を1本の開ポリラインとして生成する。

    局所X座標は ``-length / 2`` から ``+length / 2`` の順を常に保つ。
    負の ``cycles`` は頂点順を変えず、位相が進む方向だけを反転する。
    負の ``amplitude`` は局所X軸を基準に波形を反転する。``phase=0`` では
    sineとtriangleのいずれも局所Y=0から始まり、正の振幅・周期では直後に増加する。
    ``length=0`` でも有限な頂点を持つ1本の開ポリラインを返す。

    Parameters
    ----------
    kind : {"sine", "triangle"}, optional
        正弦波または三角波。
    length : float, optional
        局所X軸に沿う非負の長さ。
    amplitude : float, optional
        局所Y軸方向の符号付き振幅。
    cycles : float, optional
        始点から終点までに進む符号付き周期数。
    phase : float, optional
        始点における位相 [deg]。90度で正の振幅位置から始まる。
    samples : int, optional
        始点と終点を含む頂点数。2以上。
    angle : float, optional
        ``center`` を基準とするXY平面内の反時計回り回転角 [deg]。
    center : tuple[float, float, float], optional
        局所原点を配置する有限なXYZ座標。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        入力X順を維持した1本の開ポリラインを表す ``(coords, offsets)``。

    Raises
    ------
    ValueError
        kind、頂点数、長さ、有限性、または出力可能な数値範囲が不正な場合。
    """

    kind_s = kind
    if kind_s not in _KIND_ORDER:
        choices = ", ".join(repr(choice) for choice in _KIND_ORDER)
        raise ValueError(f"wave の kind は {choices} のいずれかである必要がある")

    samples_i = samples
    if samples_i < 2:
        raise ValueError("wave の samples は 2 以上である必要がある")

    length_f = length
    if length_f < 0.0:
        raise ValueError("wave の length は 0 以上である必要がある")
    amplitude_f = amplitude
    cycles_f = cycles
    phase_f = phase
    angle_f = angle
    cx, cy, cz = center
    if abs(cz) > _FLOAT32_MAX:
        raise ValueError("wave の出力 Z 座標は有限な float32 の範囲である必要がある")

    ensure_geometry_output(
        "wave",
        vertices=samples_i,
        lines=1,
        # parameter、waveform、回転work 2本のfloat64配列。
        scratch_bytes=samples_i * _SCRATCH_BYTES_PER_SAMPLE,
        hint="samples を減らしてください",
    )

    parameter = np.linspace(0.0, 1.0, samples_i, dtype=np.float64)
    waveform = np.empty(samples_i, dtype=np.float64)
    work = np.empty(samples_i, dtype=np.float64)
    component = np.empty(samples_i, dtype=np.float64)

    # 有限なsubnormalもambientなnp.seterrに左右されず0へ丸められるようにする。
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        # 周期単位で剰余を取ってから角度へ変換し、巨大でも有限な位相引数を扱う。
        np.multiply(parameter, cycles_f, out=waveform)
        np.remainder(waveform, 1.0, out=waveform)
        waveform += math.remainder(phase_f, 360.0) / 360.0
        np.remainder(waveform, 1.0, out=waveform)

        if kind_s == "sine":
            waveform *= 2.0 * math.pi
            np.sin(waveform, out=waveform)
        else:
            # 0から上昇し、1/4周期で+1となる連続なtriangle波。
            waveform += 0.25
            np.remainder(waveform, 1.0, out=waveform)
            waveform -= 0.5
            np.abs(waveform, out=waveform)
            waveform *= -4.0
            waveform += 1.0

        waveform *= amplitude_f
        parameter -= 0.5
        parameter *= length_f

        theta = math.radians(math.remainder(angle_f, 360.0))
        cos_theta = math.cos(theta)
        sin_theta = math.sin(theta)

        coords = np.empty((samples_i, 3), dtype=np.float32)

        np.multiply(parameter, cos_theta, out=work)
        np.multiply(waveform, sin_theta, out=component)
        np.subtract(work, component, out=work)
        work += cx
        _assign_float32_component(coords[:, 0], work, axis="X")

        np.multiply(parameter, sin_theta, out=work)
        np.multiply(waveform, cos_theta, out=component)
        np.add(work, component, out=work)
        work += cy
        _assign_float32_component(coords[:, 1], work, axis="Y")

    coords[:, 2] = np.float32(cz)
    offsets = np.array([0, samples_i], dtype=np.int32)
    return coords, offsets


__all__ = ["wave", "wave_meta"]
