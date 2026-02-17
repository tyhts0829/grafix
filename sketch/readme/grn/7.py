from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(number_text=str(Path(__file__).stem))
    g = G.text(
        activate=True,
        text="ds",
        font="Bodoni Ornaments.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(75.824, 75.824, 0.0),
        scale=56.186,
    )

    e = (
        E.fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=1000.0,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .subdivide(
            activate=True,
            subdivisions=5,
        )
        .displace(
            activate=False,
        )
        .mirror(
            activate=True,
            n_mirror=3,
            cx=74.0,
            cy=96.907,
            show_planes=False,
        )
        .rotate(
            activate=True,
            auto_center=True,
            rotation=(0.0, 0.0, 30.0),
        )
        .scale(
            activate=True,
            mode="all",
            auto_center=True,
            scale=(0.8, 0.8, 1.0),
        )
        .translate(
            activate=True,
            delta=(0.0, -3.297, 0.0),
        )
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
