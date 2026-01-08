from grafix import E, G, run
from sketch.presets.axes import axes

# A4
CANVAS_WIDTH = 210
CANVAS_HEIGHT = 297


def draw(t):
    l = G.line()
    e = E.repeat().collapse().collapse().displace()
    return e(l), axes()


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=3.5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="TX-6 Bluetooth",
        midi_mode="7bit",
    )
