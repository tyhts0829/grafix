from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g = G.polyhedron(
        activate=True,
        type_index=1,
        center=(76.63, 132.065, 0.0),
        scale=82.034,
    )

    e = E.rotate(
        activate=True,
        auto_center=True,
        rotation=(90.0, -39.13, 127.15),
    ).repeat(
        activate=True,
        layout="grid",
        count=1,
        cumulative_scale=False,
        cumulative_offset=False,
        cumulative_rotate=False,
        offset=(0.0, -76.087, 0.0),
        rotation_step=(-48.913000000000004, -115.435, 40.645),
        scale=(1.0, 1.0, 1.0),
        auto_center=True,
    )

    return e(g), frame


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
    )
