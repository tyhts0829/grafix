import math
from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    f1 = P.flow(
        activate=True,
        center=(24.8, 42.308, 0.0),
        scale=(2.033, 2.033, 1.0),
        fill_density_coef=0.811,
        fill_angle=0.0,
        subdivide_levels=6,
        displace_amplitude=(5.0, 5.0, 0.0),
        displace_frequency=(0.025, 0.025, 0.0),
    )

    f2 = P.flow(
        activate=True,
        center=(23.626, 42.857, 0.0),
        scale=(2.033, 2.033, 1.0),
        fill_density_coef=0.811,
        fill_angle=139.227,
        subdivide_levels=6,
        displace_amplitude=(5.0, 5.0, 0.0),
        displace_frequency=(0.025, 0.025, 0.0),
    )

    e = E.rotate(
        activate=True,
        auto_center=True,
        rotation=(0.0, 0.0, 45.0),
    )

    f2 = e(f2)
    return f1, f2, frame


if __name__ == "__main__":
    run(
        draw,
        background_color=(0.0, 0.0, 0.0),
        line_thickness=0.001,
        line_color=(1.0, 1.0, 1.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
        fps=24,
    )
