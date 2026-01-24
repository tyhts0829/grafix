from collections.abc import Mapping

from grafix import E, G, preset, run

CANVAS_SIZE = (100, 100)

meta: dict[str, Mapping[str, object]] = {
    "center": {"kind": "vec3", "ui_min": 0.0, "ui_max": 100.0},
    "matrix_size": {"kind": "vec3", "ui_min": 0.0, "ui_max": 5.0},
    "dot_size": {"kind": "float", "ui_min": 0.1, "ui_max": 20.0},
    "fill_density_coef": {"kind": "float", "ui_min": 0.0, "ui_max": 1.0},
    "repeat_count_x": {"kind": "int", "ui_min": 1, "ui_max": 50},
    "repeat_count_y": {"kind": "int", "ui_min": 1, "ui_max": 50},
}


@preset(meta=meta)
def dot_matrix(
    center=(0, 0, 0),
    matrix_size=(1.0, 1.0, 1.0),
    dot_size=4.0,
    fill_density_coef=0.5,
    repeat_count_x=10,
    repeat_count_y=10,
):
    dot = G.polygon(
        n_sides=100,
        phase=0.0,
        center=center,
        scale=dot_size,
    )

    matrix = (
        E.fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=20 * fill_density_coef,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .repeat(
            activate=True,
            count=repeat_count_x,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(50 * matrix_size[0], 0.0, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .repeat(
            activate=True,
            count=repeat_count_y,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 50 * matrix_size[1], 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
    )

    return matrix(dot)


def draw(t):
    return dot_matrix()


if __name__ == "__main__":
    run(
        draw,
        canvas_size=CANVAS_SIZE,
        render_scale=8,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
