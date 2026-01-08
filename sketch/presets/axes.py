# どこで: `sketch/presets/axes.py`。
# 何を: X 軸と目盛りを生成するプリセット。
# なぜ: `line` と `repeat` の組み合わせで、最小構成のガイドを手早く描けるようにするため。

from grafix import E, G, preset, run

CANVAS_SIZE = (100, 100)

meta = {
    "center": {"kind": "vec3", "ui_min": 0.0, "ui_max": 300.0},
    "axis_length_x": {"kind": "float", "ui_min": 0.0, "ui_max": 300.0},
    "tick_count_x": {"kind": "int", "ui_min": 2, "ui_max": 301},
    "tick_length": {"kind": "float", "ui_min": 0.0, "ui_max": 20.0},
    "tick_offset": {"kind": "float", "ui_min": -20.0, "ui_max": 20.0},
}


@preset(meta=meta)
def axes(
    center=(50.0, 50.0, 0.0),
    axis_length_x=100.0,
    tick_count_x=11,
    tick_length=2.0,
    tick_offset=0.0,
):
    cx, cy, cz = center

    x_axis = G.line(
        center=center,
        length=axis_length_x,
        angle=0.0,
    )

    x_tick = G.line(
        center=(cx - 0.5 * axis_length_x, cy + tick_offset, cz),
        length=tick_length,
        angle=90.0,
    )

    x_ticks = E.repeat(
        bypass=False,
        count=tick_count_x - 1,
        cumulative_scale=False,
        cumulative_offset=False,
        cumulative_rotate=False,
        offset=(axis_length_x, 0.0, 0.0),
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
