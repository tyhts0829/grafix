from grafix import E, G, run

# A4
CANVAS_WIDTH = 210
CANVAS_HEIGHT = 297


def draw(t):
    t1 = G.text(
        text="g",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(89.764, 155.906, 0.0),
        scale=35.039,
    )

    t2 = G.text(
        text="g",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(89.764, 155.906, 0.0),
        scale=35.039,
    )

    t3 = G.text(
        text="g",
        font="Geist-Medium.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(89.764, 155.906, 0.0),
        scale=35.039,
    )

    t4 = G.text(
        text="g",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(89.764, 155.906, 0.0),
        scale=35.039,
    )

    t5 = G.text(
        text="g",
        font="Bodoni 72.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(89.764, 155.906, 0.0),
        scale=35.039,
    )

    e1 = E.fill(
        bypass=False,
        angle_sets=1,
        angle=124.78,
        density=522.034,
        spacing_gradient=0.339,
        remove_boundary=True,
    )

    e2 = E.fill(
        bypass=False,
        angle_sets=1,
        angle=32.949,
        density=447.458,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    e3 = E.fill(
        bypass=False,
        angle_sets=1,
        angle=154.068,
        density=532.203,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    e4 = E.fill(
        bypass=False,
        angle_sets=1,
        angle=29.898,
        density=716.9490000000001,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    e5 = E.fill(
        bypass=False,
        angle_sets=1,
        angle=162.915,
        density=669.492,
        spacing_gradient=0.0,
        remove_boundary=True,
    )

    t1 = e1(t1)
    t2 = e2(t2)
    t3 = e3(t3)
    t4 = e4(t4)
    t5 = e5(t5)

    e = E.scale()

    t = e(t1 + t2 + t3 + t4 + t5)

    l = G.line()
    el = E.repeat().repeat()
    l = el(l)

    return t, l


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=3.5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
    )
