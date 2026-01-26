from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g1 = G.polygon()
    g2 = G.polygon()
    g3 = G.polygon()
    g = g1 + g2 + g3

    e1 = E.buffer().buffer().weave()
    e2 = E.bold()
    e3 = E.clip()
    g_weave = e1(g)
    g_weave = e3([g_weave, g])
    g_fill = e2(g)
    g = g_weave + g_fill
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
