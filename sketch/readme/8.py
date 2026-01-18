from grafix import E, G, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    DENSITY_RATIO = 0.9
    t1 = G.text(
        activate=True,
        text="g",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(95.514, 155.906, 0.0),
        scale=35.039,
    )

    t2 = G.text(
        activate=True,
        text="g",
        font="Geist-Medium.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(100.20100000000001, 155.906, 0.0),
        scale=35.039,
    )

    t3 = G.text(
        activate=True,
        text="g",
        font="Carlo.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(97.858, 155.906, 0.0),
        scale=35.039,
    )

    t4 = G.text(
        activate=True,
        text="g",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(103.131, 155.906, 0.0),
        scale=35.039,
    )

    t5 = G.text(
        activate=True,
        text="g",
        font="Bodoni 72.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=1.0,
        center=(91.412, 155.906, 0.0),
        scale=35.039,
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

    # t = e(t1 + t2 + t3 + t4 + t5)

    cross = G(name="cross").line(
        center=(20.0, 20.0, 0.0),
        length=10.0,
        angle=0.0,
    )

    e_cross = (
        E(name="cross_repeats")
        .repeat(
            activate=True,
            count=1,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 0.0, 0.0),
            rotation_step=(0.0, 0.0, 90.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .repeat(
            activate=True,
            count=1,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(170.0, 0.0, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
        .repeat(
            activate=True,
            count=1,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 257.0, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
    )

    cross = e_cross(cross)

    line_h = G(name="line_h").line(
        center=(105.0, 20.0, 0.0),
        length=30.0,
        angle=0.0,
    )

    line_h_repeat = E(name="line_h_repeat").repeat(
        activate=True,
        count=1,
        cumulative_scale=False,
        cumulative_offset=False,
        cumulative_rotate=False,
        offset=(0.0, 257.0, 0.0),
        rotation_step=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        curve=1.0,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
    )

    line_h = line_h_repeat(line_h)

    line_v = G(name="line_v").line(
        center=(20.0, 144.0, 0.0),
        length=77.0,
        angle=90.0,
    )

    line_v_repeat = E(name="line_v_repeat").repeat(
        activate=True,
        count=1,
        cumulative_scale=False,
        cumulative_offset=False,
        cumulative_rotate=False,
        offset=(170.0, 0.0, 0.0),
        rotation_step=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        curve=1.0,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
    )

    line_v = line_v_repeat(line_v)

    mt1 = G(name="mt1").text(
        text="repeat",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(35.0, 15.0, 0.0),
        scale=5.0,
    )

    mt2 = G(name="mt2").text(
        text="g",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(105.0, 15.0, 0.0),
        scale=5.0,
    )

    mt3 = G(name="mt3").text(
        text="5",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(145.0, 15.0, 0.0),
        scale=5.0,
    )

    mt4 = G(name="mt4").text(
        text="times",
        font="GoogleSans-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(178.0, 15.0, 0.0),
        scale=5.0,
    )

    mt = mt1 + mt2 + mt3 + mt4
    mt_e = E(name="mt_e").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=1000.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    mt = mt_e(mt)

    bar_code = G(name="bar_code").polygon(
        n_sides=4,
        phase=45.0,
        center=(8.0, 207.0, 0.0),
        scale=1.0,
    )

    bar_code_e = (
        E(name="bar_code_e")
        .scale(
            activate=True,
            mode="all",
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            scale=(20.0, 6.0, 1.0),
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=25.0,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .repeat(
            activate=True,
            count=4,
            cumulative_scale=False,
            cumulative_offset=False,
            cumulative_rotate=False,
            offset=(0.0, 38.0, 0.0),
            rotation_step=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            curve=1.0,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
        )
    )

    bar_code = bar_code_e(bar_code)

    waku = cross + line_h + line_v + mt

    aff = E.affine(
        activate=True,
        auto_center=False,
        pivot=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(0.704, 0.704, 1.0),
        delta=(0.0, 0.0, 0.0),
    )

    t1 = aff(t1)
    t2 = aff(t2)
    t3 = aff(t3)
    t4 = aff(t4)
    t5 = aff(t5)
    waku = aff(waku)
    bar_code = aff(bar_code)

    return t1, t2, t3, t4, t5, waku + bar_code


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=3.5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        run_id="A5",
        midi_port_name="Grid",
        midi_mode="14bit",
    )
