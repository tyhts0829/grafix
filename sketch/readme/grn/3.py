from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame()
    g = G.sphere(
        activate=True,
        subdivisions=0,
        type_index=2,
        mode=2,
        center=(74.0, 86.413, 0.0),
        scale=99.661,
    )

    e = E.rotate(
        activate=True,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
        rotation=(0.0, 20.900000000000002, 30.0),
    ).bold(
        activate=True,
        count=10,
        radius=0.202,
        seed=58236844,
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
