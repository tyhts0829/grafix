from grafix import E, G, L, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    # =========== Layouts ===========
    layout = P(name="layout1").layout_grid_system(
        activate=True,
        canvas_w=148.0,
        canvas_h=210.0,
        axes="both",
        margin_l=8.0,
        margin_r=8.0,
        margin_t=8.0,
        margin_b=8.0,
        show_center=False,
        cols=5,
        rows=8,
        gutter_x=4.0,
        gutter_y=4.0,
        show_column_centers=False,
        show_baseline=False,
        baseline_step=8.417,
        baseline_offset=0.0,
        offset=(0.0, 0.0, 0.0),
    )

    layout = L(name="layout1").layer(layout)

    # ====================================================================
    line = G.line()

    # ====================================================================
    c = G(name="circle").polygon(
        activate=True,
        n_sides=565,
        phase=0.0,
        sweep=360.0,
        center=(73.37, 117.033, 0.0),
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

    # ====================================================================
    grafix = G(name="grafix").text(
        activate=True,
        text="Grafix",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(89.011, 8.242, 0.0),
        scale=19.244,
    )

    e_grafix = E(name="e_grafix").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=603.093,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    grafix = e_grafix(grafix)
    description = G(name="description").text()
    e_description = E(name="e_description").fill()
    description = e_description(description)
    return layout, e(c), grafix, description, line


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
