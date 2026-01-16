from grafix import E, G, P, run

# A4
CANVAS_WIDTH = 210
CANVAS_HEIGHT = 297


def draw(t):
    ax = P.axes()
    e = E.bold()
    ax = e(ax)

    t = G.text()
    et = E.quantize().buffer().buffer().fill()
    t = et(t)

    m = 12.0
    guides = (
        P.layout_bounds(
            canvas_w=CANVAS_WIDTH,
            canvas_h=CANVAS_HEIGHT,
            border=True,
            show_margin=True,
            margin_l=m,
            margin_r=m,
            margin_t=m,
            margin_b=m,
        )
        + P.layout_grid_system(
            canvas_w=CANVAS_WIDTH,
            canvas_h=CANVAS_HEIGHT,
            cols=12,
            rows=12,
            gutter_x=4.0,
            gutter_y=4.0,
            show_baseline=True,
            baseline_step=6.0,
            baseline_offset=0.0,
            margin_l=m,
            margin_r=m,
            margin_t=m,
            margin_b=m,
        )
        + P.layout_golden_ratio(
            canvas_w=CANVAS_WIDTH,
            canvas_h=CANVAS_HEIGHT,
            margin_l=m,
            margin_r=m,
            margin_t=m,
            margin_b=m,
        )
        + P.layout_intersections(
            canvas_w=CANVAS_WIDTH,
            canvas_h=CANVAS_HEIGHT,
            show_golden=True,
            mark_size=2.0,
            margin_l=m,
            margin_r=m,
            margin_t=m,
            margin_b=m,
        )
    )

    return ax, guides, t


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=3.5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
