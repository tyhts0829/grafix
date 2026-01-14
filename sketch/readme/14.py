from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    r = G.text()
    g = G.text()
    b = G.text()

    r_e = E.fill()
    r = r_e(r)
    g_e = E.fill()
    g = g_e(g)
    b_e = E.fill()
    b = b_e(b)
    return r, g, b, P.layout(canvas_w=CANVAS_WIDTH, canvas_h=CANVAS_HEIGHT)


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        # midi_port_name="TX-6 Bluetooth",
        # midi_mode="7bit",
    )
