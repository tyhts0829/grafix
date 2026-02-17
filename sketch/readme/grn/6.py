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
        number_text="6",
        explanation_text="G.polygon()\nE.repeat().repeat()\n.drop().fill()",
        explanation_density=500.0,
        template_color_rgb255=(0, 0, 0),
    )

    g = G.polygon(
        activate=True,
        n_sides=4,
        phase=45.0,
        sweep=360.0,
        center=(38.462, 36.264, 0.0),
        scale=2.234,
    )

    e = (
        E.repeat(
            activate=True,
            layout="grid",
            count=56,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 113.736, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            auto_center=True,
        )
        .repeat(
            activate=True,
            layout="grid",
            count=34,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(71.429, 0.0, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            auto_center=True,
        )
        .drop(
            activate=True,
            interval=0,
            index_offset=0,
            min_length=-1.0,
            max_length=-1.0,
            probability_base=(0.0, 0.115, 0.0),
            probability_slope=(0.0, 0.319, 0.0),
            by="face",
            seed=614357440,
            keep_mode="drop",
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=1893.471,
            spacing_gradient=0.0,
            remove_boundary=False,
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
