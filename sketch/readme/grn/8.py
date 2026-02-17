from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g1 = P.dot_matrix()
    g2 = P.dot_matrix()

    e2 = E.rotate()

    g2 = e2(g2)
    g = g1 + g2
    e = E.affine(
        activate=True,
        auto_center=True,
        rotation=(0.0, 0.0, 0.0),
        scale=(0.85, 0.85, 1.0),
        delta=(0.0, 2.5, 0.0),
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
