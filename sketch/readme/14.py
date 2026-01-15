from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    return P.layout_metallic_rectangles(canvas_h=CANVAS_HEIGHT, canvas_w=CANVAS_WIDTH)


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
