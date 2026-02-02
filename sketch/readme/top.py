from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g = G.polygon(
        activate=True,
        n_sides=96,
        phase=0.0,
        sweep=360.0,
        center=(74.0, 87.363, 0.0),
        scale=3.093,
    )

    e = (
        E.isocontour(
            activate=True,
            spacing=0.881,
            phase=0.0,
            max_dist=55.67,
            mode="outside",
            grid_pitch=1.321,
            gamma=2.156,
            level_step=1,
            auto_close_threshold=0.001,
            keep_original=False,
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
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
        n_worker=8,
    )
