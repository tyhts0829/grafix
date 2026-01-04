from grafix import E, G, run

# A4
CANVAS_WIDTH = 210
CANVAS_HEIGHT = 297


def draw(t):
    circle = G(name="circle").polygon()
    circle_e = E(name="circle_e").fill()
    circle = circle_e(circle)

    text = G.text()
    text_e = E(name="text_e").fill()
    text = text_e(text)

    return circle, text


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=3.5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        # midi_port_name="Grid",
        # midi_mode="14bit",
    )
