from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="4",
        explanation_text="G.sphere()\nE.rotate().extrude()",
        explanation_density=100.0,
        template_color_rgb255=(0, 0, 0),
    )

    g = G.sphere(
        activate=True,
        subdivisions=0,
        type_index=3,
        mode=2,
        center=(75.0, 93.0, 0.0),
        scale=93.898,
    )

    e = E.rotate(
        activate=True,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
        rotation=(-140.623, -147.654, -180.0),
    ).extrude(
        activate=True,
        delta=(0.0, 0.0, 0.0),
        scale=1.063,
        subdivisions=4,
        center_mode="auto",
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
