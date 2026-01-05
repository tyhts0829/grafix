from grafix import E, G, run

# A4
CANVAS_WIDTH = 210
CANVAS_HEIGHT = 297


def draw(t):
    t1 = G.text(text="g")
    t2 = G.text(text="g")
    t3 = G.text(text="g")
    t4 = G.text(text="g")
    t6 = G.text(text="g")
    # t7 = G.text(text="g")
    # t8 = G.text(text="g")
    e = E.scale()
    e2 = E.fill()

    return (
        e(e2(t1)),
        e(e2(t2)),
        e(e2(t3)),
        e(e2(t4)),
        e(e2(t6)),
        # e(e2(t7)),
        # e(e2(t8)),
    )


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=3.5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="OXI E16 „Éù„Éº„Éà3",
        midi_mode="7bit_rel",
    )
