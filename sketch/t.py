from __future__ import annotations

import math

import numpy as np

from grafix import E, G, effect, primitive, run


flower_meta = {
    "center": {"kind": "vec3", "ui_min": 0.0, "ui_max": 100.0},
    "radius": {"kind": "float", "ui_min": 0.0, "ui_max": 80.0},
    "petals": {"kind": "int", "ui_min": 1, "ui_max": 16},
    "samples": {"kind": "int", "ui_min": 32, "ui_max": 4096},
}


@primitive(meta=flower_meta, overwrite=False)
def flower(
    *,
    center: tuple[float, float, float] = (50.0, 50.0, 0.0),
    radius: float = 40.0,
    petals: int = 7,
    samples: int = 1200,
) -> tuple[np.ndarray, np.ndarray]:
    """ローズ曲線（r = radius * sin(petals * θ)）の閉ポリラインを生成する。"""

    cx, cy, cz = center
    cx32, cy32, cz32 = np.float32(cx), np.float32(cy), np.float32(cz)

    radius32 = np.float32(radius)
    petals_i = max(1, int(petals))
    samples_i = max(32, int(samples))

    angles = np.linspace(
        0.0,
        2.0 * math.pi,
        num=samples_i,
        endpoint=False,
        dtype=np.float32,
    )
    r = radius32 * np.sin(np.float32(petals_i) * angles, dtype=np.float32)
    x = r * np.cos(angles, dtype=np.float32) + cx32
    y = r * np.sin(angles, dtype=np.float32) + cy32
    z = np.full_like(x, cz32, dtype=np.float32)

    coords = np.stack([x, y, z], axis=1).astype(np.float32, copy=False)
    coords = np.concatenate([coords, coords[:1]], axis=0)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


wave_y_meta = {
    "amp": {"kind": "float", "ui_min": 0.0, "ui_max": 20.0},
    "freq": {"kind": "float", "ui_min": 0.0, "ui_max": 1.0},
}


@effect(meta=wave_y_meta, overwrite=False)
def wave_y(
    g: tuple[np.ndarray, np.ndarray],
    *,
    amp: float = 4.0,
    freq: float = 0.12,
    phase: float = 0.0,  # phase は UI には出さず、draw(t) から注入する用途
) -> tuple[np.ndarray, np.ndarray]:
    """x に応じた sin 波で y を揺らす。"""
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    amp32 = np.float32(amp)
    if amp32 == 0.0:
        return coords, offsets

    freq32 = np.float32(freq)
    phase32 = np.float32(phase)

    coords_out = coords.copy()
    coords_out[:, 1] += amp32 * np.sin(
        coords_out[:, 0] * freq32 + phase32, dtype=np.float32
    )
    return coords_out, offsets


def draw(t: float):
    g = G.flower()
    e = E.wave_y(phase=2.0 * math.pi * t).rotate(rotation=(0.0, 0.0, 15.0 * t))
    return e(g)


if __name__ == "__main__":
    run(
        draw,
        canvas_size=(100, 100),
        render_scale=10,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
