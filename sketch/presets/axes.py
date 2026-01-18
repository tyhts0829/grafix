# どこで: `sketch/presets/axes.py`。
# 何を: X 軸と目盛りを生成するプリセット。
# なぜ: `line` と `repeat` の組み合わせで、最小構成のガイドを手早く描けるようにするため。

import math

from grafix import E, G, preset, run

CANVAS_SIZE = (100, 100)

meta = {
    "center": {"kind": "vec3", "ui_min": 0.0, "ui_max": 300.0},
    "axis_length": {"kind": "float", "ui_min": 0.0, "ui_max": 300.0},
    "axis_visible_ratio": {"kind": "float", "ui_min": 0.0, "ui_max": 1.0},
    "axis_visible_anchor": {
        "kind": "choice",
        "choices": ["left", "center", "right"],
    },
    "tick_count_x": {"kind": "int", "ui_min": 2, "ui_max": 301},
    "tick_length": {"kind": "float", "ui_min": 0.0, "ui_max": 20.0},
    "tick_offset": {"kind": "float", "ui_min": -20.0, "ui_max": 20.0},
    "tick_log": {"kind": "bool"},
}


@preset(meta=meta)
def axes(
    center=(50.0, 50.0, 0.0),
    axis_length=100.0,
    axis_visible_ratio=1.0,
    axis_visible_anchor="center",
    tick_count_x=11,
    tick_length=2.0,
    tick_offset=0.0,
    tick_log=False,
):
    cx, cy, cz = center

    axis_visible_ratio = float(axis_visible_ratio)
    if axis_visible_ratio < 0.0:
        axis_visible_ratio = 0.0
    if axis_visible_ratio > 1.0:
        axis_visible_ratio = 1.0

    visible_length = axis_length * axis_visible_ratio
    axis_center_x = cx
    if axis_visible_anchor == "left":
        axis_center_x = cx - 0.5 * axis_length + 0.5 * visible_length
    elif axis_visible_anchor == "right":
        axis_center_x = cx + 0.5 * axis_length - 0.5 * visible_length

    x_axis = G.line(
        center=(axis_center_x, cy, cz),
        length=visible_length,
        angle=0.0,
    )

    x_start = cx - 0.5 * axis_length
    tick_center_y = cy + tick_offset

    if tick_log:
        tick_count_x_i = int(tick_count_x)
        if tick_count_x_i <= 1:
            x_ticks = G.line(
                center=(x_start, tick_center_y, cz),
                length=tick_length,
                angle=90.0,
            )
        else:
            log_base = 10.0
            denom = math.log(log_base)
            scale = log_base - 1.0
            x_ticks = sum(
                G.line(
                    center=(
                        x_start
                        + axis_length
                        * (
                            math.log(1.0 + scale * (k / (tick_count_x_i - 1))) / denom
                        ),
                        tick_center_y,
                        cz,
                    ),
                    length=tick_length,
                    angle=90.0,
                )
                for k in range(tick_count_x_i)
            )
    else:
        x_tick = G.line(
            center=(x_start, tick_center_y, cz),
            length=tick_length,
            angle=90.0,
        )

        x_ticks = E.repeat(
            activate=True,
            count=tick_count_x - 1,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(axis_length, 0.0, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )(x_tick)

    return x_axis + x_ticks


def draw(t):
    return axes()


if __name__ == "__main__":
    run(
        draw,
        canvas_size=CANVAS_SIZE,
        render_scale=8,
    )
