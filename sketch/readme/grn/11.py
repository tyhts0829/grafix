import math
from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        number_text=Path(__file__).stem,
        explanation_text="G.polygon()\nE.isocontour()\n.lowpass().fill()",
        explanation_density=500.0,
        template_color_rgb255=(255, 255, 255),
    )

    g = G.polygon(
        activate=True,
        n_sides=128,
        phase=45.0,
        sweep=360.0,
        center=(74.0, 87.363, 0.0),
        scale=3.093,
    )

    e = (
        E.isocontour(
            activate=True,
            spacing=0.46399999999999997,
            phase=-8.007,
            max_dist=55.669999999999995,
            mode="outside",
            grid_pitch=1.142,
            gamma=2.8699999999999997,
            level_step=1,
            auto_close_threshold=0.001,
            keep_original=True,
        )
        .lowpass(
            activate=True,
            step=2.459,
            sigma=4.742,
            closed="auto",
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=408.935,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
    )

    g = e(g)
    return frame, g


if __name__ == "__main__":
    run(
        draw,
        background_color=(0.0, 0.0, 0.0),
        line_thickness=0.001,
        line_color=(1.0, 1.0, 1.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="Grid",
        midi_mode="14bit",
        fps=24,
    )
