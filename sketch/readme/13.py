from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    layout = P.layout_metallic_rectangles(canvas_h=CANVAS_HEIGHT, canvas_w=CANVAS_WIDTH)
    c = G.polygon(
        activate=True,
        n_sides=565,
        phase=0.0,
        center=(71.739, 105.97800000000001, 0.0),
        scale=108.47500000000001,
    )

    e = (
        E.repeat(
            activate=True,
            count=59,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 0.0, 61.29),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=0.897,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .displace(
            activate=True,
            amplitude=(11.957, 0.0, 8.0),
            spatial_freq=(0.048, 0.033, 0.024),
            amplitude_gradient=(4.0, 4.0, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            gradient_center_offset=(0.533, 0.0, 0.0),
            min_gradient_factor=0.0,
            max_gradient_factor=1.549,
            t=0.381,
        )
        .affine(
            activate=True,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 48.387),
            scale=(1.0, 1.0, 1.0),
            delta=(0.0, 0.0, 0.0),
        )
    )

    return layout, e(c)


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
