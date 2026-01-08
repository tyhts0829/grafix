# どこで: `sketch/presets/grid.py`。
# 何を: 構図検討用の参照グリッド（まずは正方形グリッド）を描くプリセット。
# なぜ: 下描き/構成の当たりを付ける補助線を、スケッチに簡単に重ねられるようにするため。

from __future__ import annotations

import math

from grafix import E, G, preset, run

CANVAS_SIZE = (100, 100)

meta = {
    "pattern": {"kind": "choice", "choices": ["square"]},
    "cell_size": {"kind": "float", "ui_min": 1.0, "ui_max": 50.0},
    "offset": {"kind": "vec3", "ui_min": -50.0, "ui_max": 50.0},
}


@preset(meta=meta)
def grid(
    *,
    canvas_size: tuple[float, float] = CANVAS_SIZE,
    pattern: str = "square",
    cell_size: float = 10.0,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """構図検討用の参照グリッドを生成する。

    Parameters
    ----------
    canvas_size : tuple[float, float]
        キャンバスサイズ（width, height）。
        `run(..., canvas_size=...)` と同じ値を渡すことを想定する。
    pattern : str
        グリッドの種類。現状は `"square"` のみ。
    cell_size : float
        グリッドのセルサイズ（ワールド単位）。
    offset : tuple[float, float, float]
        グリッドの平行移動量（x, y, z）。

    Returns
    -------
    Geometry
        グリッド線の Geometry。
    """
    if pattern != "square":
        raise ValueError(f"未対応の pattern です: {pattern!r}")

    canvas_w, canvas_h = canvas_size
    cell = float(cell_size)
    if cell <= 0.0:
        cell = 1.0

    ox, oy, oz = offset
    n_x = max(0, int(math.ceil(float(canvas_w) / cell)))
    n_y = max(0, int(math.ceil(float(canvas_h) / cell)))

    # repeat は「最後のコピーまでの総オフセット」を指定する（1 ステップ分ではない）。
    v0 = G.line(center=(ox, 0.5 * float(canvas_h) + oy, oz), length=canvas_h, angle=90.0)
    v_lines = E.repeat(
        bypass=False,
        count=n_x,
        cumulative_scale=False,
        cumulative_offset=False,
        cumulative_rotate=False,
        offset=(cell * n_x, 0.0, 0.0),
        rotation_step=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        curve=1.0,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
    )(v0)

    h0 = G.line(center=(0.5 * float(canvas_w) + ox, oy, oz), length=canvas_w, angle=0.0)
    h_lines = E.repeat(
        bypass=False,
        count=n_y,
        cumulative_scale=False,
        cumulative_offset=False,
        cumulative_rotate=False,
        offset=(0.0, cell * n_y, 0.0),
        rotation_step=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        curve=1.0,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
    )(h0)

    return v_lines + h_lines


def draw(t: float):
    return grid(canvas_size=CANVAS_SIZE)


if __name__ == "__main__":
    run(
        draw,
        canvas_size=CANVAS_SIZE,
        render_scale=8,
        midi_port_name="Grid",
        midi_mode="14bit",
    )

