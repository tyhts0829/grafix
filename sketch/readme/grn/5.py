from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g = G.polygon(
        activate=True,
        n_sides=128,
        phase=137.288,
        sweep=265.424,
        center=(68.478, 63.587, 0.0),
        scale=44.068,
    )

    e = (
        E.rotate(
            activate=True,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, -121.935),
        )
        .buffer(
            activate=True,
            join="round",
            quad_segs=12,
            distance=8.0,
            union=False,
            keep_original=False,
        )
        .buffer(
            activate=True,
            join="round",
            quad_segs=12,
            distance=1.949,
            union=False,
            keep_original=False,
        )
        .repeat(
            activate=True,
            count=1,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(14.13, 57.609, 0.0),
            rotation_step=(0.0, 0.0, 180.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=1128.814,
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
    )
