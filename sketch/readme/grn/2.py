from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="2",
        explanation_text="G.text()\nE.fill()",
        template_color_rgb255=(0, 0, 0),
    )

    DENSITY_RATIO = 1.5
    t1 = G.text(
        activate=True,
        text="g",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=1.0,
        center=(69.731, 70.31700000000001, 0.0),
        scale=26.271,
    )

    t2 = G.text(
        activate=True,
        text="g",
        font="Geist-Medium.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=1.0,
        center=(69.731, 70.31700000000001, 0.0),
        scale=26.271,
    )

    t3 = G.text(
        activate=True,
        text="g",
        font="Carlo.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=1.0,
        center=(69.731, 70.31700000000001, 0.0),
        scale=26.271,
    )

    t4 = G.text(
        activate=True,
        text="g",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=1.0,
        center=(69.731, 70.31700000000001, 0.0),
        scale=26.271,
    )

    t5 = G.text(
        activate=True,
        text="g",
        font="Bodoni 72.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=1.0,
        center=(69.731, 70.31700000000001, 0.0),
        scale=26.271,
    )

    e1 = E.fill(
        activate=True,
        angle_sets=1,
        angle=124.78,
        density=522.034 * DENSITY_RATIO,
        spacing_gradient=0.339,
        remove_boundary=True,
    )

    e2 = E.fill(
        activate=True,
        angle_sets=1,
        angle=32.949,
        density=447.458 * DENSITY_RATIO,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    e3 = E.fill(
        activate=True,
        angle_sets=1,
        angle=154.068,
        density=532.203 * DENSITY_RATIO,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    e4 = E.fill(
        activate=True,
        angle_sets=1,
        angle=29.898,
        density=716.9490000000001 * DENSITY_RATIO,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    e5 = E.fill(
        activate=True,
        angle_sets=1,
        angle=162.915,
        density=669.492 * DENSITY_RATIO,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    t1 = e1(t1)
    t2 = e2(t2)
    t3 = e3(t3)
    t4 = e4(t4)
    t5 = e5(t5)

    e = E(name="g_affine").affine(
        activate=True,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(5.932, 6.0, 6.0),
        delta=(0.0, 0.0, 0.0),
    )

    t1 = e(t1)
    t2 = e(t2)
    t3 = e(t3)
    t4 = e(t4)
    t5 = e(t5)
    return frame, t1, t2, t3, t4, t5


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
