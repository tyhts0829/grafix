from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    c = G(name="circle").polygon(
        activate=True,
        n_sides=565,
        phase=0.0,
        sweep=360.0,
        center=(74.0, 92.935, 0.0),
        scale=111.684,
    )

    e = (
        E(name="e_circle")
        .repeat(
            activate=True,
            layout="grid",
            count=59,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 0.0, 61.29),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            auto_center=True,
        )
        .displace(
            activate=True,
            amplitude=(11.957, 0.0, 8.0),
            spatial_freq=(0.048, 0.033, 0.024),
            amplitude_gradient=(4.0, 4.0, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            gradient_center_offset=(0.533, 0.0, 0.0),
            gradient_profile="linear",
            min_gradient_factor=0.0,
            max_gradient_factor=1.549,
            t=0.617,
        )
        .affine(
            activate=True,
            auto_center=True,
            rotation=(0.0, 0.0, 48.387),
            scale=(0.8, 0.8, 1.0),
            delta=(0.0, 0.0, 0.0),
        )
    )

    c = e(c)

    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="1",
        explanation_text="G.polygon()\nE.repeat().displace()",
        template_color_rgb255=(0, 0, 0),
    )

    return c, frame


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
