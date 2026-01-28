from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g1 = G.polygon(
        activate=True,
        n_sides=128,
        phase=45.0,
        sweep=360.0,
        center=(74.176, 58.253, 0.0),
        scale=75.94500000000001,
    )

    e1 = (
        E.repeat(
            activate=True,
            count=1,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 52.747, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .metaball(
            activate=True,
            radius=1.804,
            threshold=0.387,
            grid_pitch=0.61,
            auto_close_threshold=0.001,
            output="both",
            keep_original=True,
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=1000.0,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .rotate(
            activate=True,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 180.0),
        )
    )

    g1 = e1(g1)
    return frame, g1


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
