from grafix import E, G, L, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    # =========== Layouts ===========
    layout = P(name="layout").layout_grid_system(
        activate=True,  # THIS GONNA BE VARIABLE
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

    layout = L(name="layout").layer(
        layout,
        color=(0.75, 0.75, 0.75),  # THIS GONNA BE VARIABLE
    )

    # ====================================================================
    line = G(name="separate_line").line(
        activate=True,
        center=(11.5, 174.5, 0.0),
        anchor="left",
        length=124.5,
        angle=0.0,
    )

    # ====================================================================
    series_name = G(name="series_name").text(
        activate=True,
        text="Grafix\nResearch\nNotes",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=0.966,
        use_bounding_box=False,
        quality=0.5,
        center=(11.538, 178.022, 0.0),
        scale=7.388,
    )

    e_series_name = E(name="e_series_name").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=838.488,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    series_name = e_series_name(series_name)
    number = G(name="number").text(
        activate=True,
        text="1",  # THIS GONNA BE VARIABLE
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(63.0, 178.022, 0.0),
        scale=4.553,
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
        text="G.polygon()\nE.repeat().displace()",  # THIS GONNA BE VARIABLE
        font="Helvetica.ttc",
        font_index=0,
        text_align="right",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=True,
        box_width=46.907000000000004,
        box_height=20.103,
        show_bounding_box=False,
        quality=0.5,
        center=(136.0, 178.022, 0.0),
        scale=2.9210000000000003,
    )

    e_explanation = E(name="e_explanation").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=300.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    explanation = e_explanation(explanation)

    bar = G(name="bars").polygon(
        activate=True,
        n_sides=4,
        phase=45.0,
        sweep=360.0,
        center=(126.923, 197.5, 0.0),
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

    bar = e_bars(bar)

    # ====================================================================
    template = L(name="template").layer(
        [
            line,
            series_name,
            number,
            explanation,
            bar,
        ],
        color=(0.0, 0.0, 0.0),  # THIS GONNA BE VARIABLE
    )
    return layout, template


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
