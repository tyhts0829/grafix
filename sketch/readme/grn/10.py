from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="10",
        explanation_text="G.line()\nE.repeat().subdivide()\n.displace()",
        explanation_density=500.0,
        template_color_rgb255=(255, 255, 255),
    )

    g = G.line(
        activate=True,
        center=(32.967, 36.264, 0.0),
        anchor="left",
        length=81.787,
        angle=0.0,
    )

    e = (
        E.repeat(
            activate=True,
            count=60,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 113.915, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .subdivide(
            activate=True,
            subdivisions=9,
        )
        .displace(
            activate=True,
            amplitude=(0.0, 8.516, 8.0),
            spatial_freq=(0.121, 0.157, 0.04),
            amplitude_gradient=(-4.0, 0.967, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            gradient_center_offset=(0.0, 0.0, 0.0),
            gradient_profile="radial",
            gradient_radius=(0.307, 1.803, 0.5),
            min_gradient_factor=0.048,
            max_gradient_factor=2.062,
            t=0.447,
        )
    )

    g = e(g)
    return frame, g


if __name__ == "__main__":
    run(
        draw,
        background_color=(0.0, 0.0, 0.0),
        line_thickness=0.001,
        line_color=(1.0, 1.0, 1.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
    )
