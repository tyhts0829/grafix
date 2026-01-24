from grafix import E, G, L, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    # =========== Layouts ===========
    layout = P(name="layout").layout_grid_system(
        activate=True,
        canvas_w=148.0,
        canvas_h=210.0,
        axes="both",
        margin_l=12.0,
        margin_r=12.0,
        margin_t=12.0,
        margin_b=12.0,
        show_center=False,
        cols=5,
        rows=8,
        gutter_x=4.0,
        gutter_y=4.0,
        show_column_centers=False,
        show_baseline=False,
        baseline_step=3.959,
        baseline_offset=0.0,
        offset=(0.0, 0.0, 0.0),
    )

    layout = L(name="layout").layer(layout)

    # ====================================================================
    line = G(name="separate_line").line(
        activate=True,
        center=(11.5, 174.5, 0.0),
        anchor="left",
        length=124.5,
        angle=0.0,
    )

    # ====================================================================
    c = G(name="circle").polygon(
        activate=True,
        n_sides=565,
        phase=0.0,
        sweep=360.0,
        center=(75.824, 80.769, 0.0),
        scale=111.684,
    )

    e = (
        E(name="e_circle")
        .repeat(
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
            t=0.41200000000000003,
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

    c = e(c)
    # ====================================================================
    title = G(name="title").text(
        activate=True,
        text="Grafix\nResearch",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=0.966,
        use_bounding_box=False,
        quality=0.5,
        center=(11.538, 178.022, 0.0),
        scale=8.0,
    )

    e_title = E(name="e_title").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=838.488,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    title = e_title(title)

    number = G(name="number").text(
        activate=True,
        text="1",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(63.0, 178.022, 0.0),
        scale=5.0,
    )

    e_number = E(name="e_number").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=35.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    number = e_number(number)

    explanation = G(name="explanation").text(
        activate=True,
        text="polygon -> repeat -> displace",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(89.011, 178.022, 0.0),
        scale=3.0,
    )

    e_explanation = E(name="e_explanation").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=572.165,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    explanation = e_explanation(explanation)

    bars = G(name="bars").polygon(
        activate=True,
        n_sides=4,
        phase=45.0,
        sweep=360.0,
        center=(24.725, 197.5, 0.0),
        scale=5.155,
    )

    e_bars = (
        E(name="e_bars")
        .scale(
            activate=True,
            mode="all",
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            scale=(5.824, 0.22, 1.0),
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=97.938,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
    )

    bars = e_bars(bars)

    return layout, c, line, title, number, explanation, bars, P.axes()


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
