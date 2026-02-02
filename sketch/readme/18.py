from grafix import E, G, L, P, run

# A4_LANDSCAPE
CANVAS_WIDTH = 297
CANVAS_HEIGHT = 210

EXPLANATION = """
Grafix is a line-based creative coding framework for Python. It approaches visual design
with an audio mindset, treating constraints as a source of creativity rather than a limitation.
Build sketches from primitives (G), shape them through method-chained processors into
pedal-like effects (E), and arrange the result into layers (L)—each with its own color and line
width, like pen changes on a plotter. A real-time OpenGL preview keeps the feedback loop
tight, and the same patch can be exported to PNG, SVG, G-code, and MP4, taking you from
experimentation to both on-screen playback and physical output.
"""


def draw(t):
    l1 = P.layout_grid_system(
        activate=True,
        canvas_w=297.0,
        canvas_h=210.0,
        axes="both",
        margin_l=12.0,
        margin_r=12.0,
        margin_t=12.0,
        margin_b=12.0,
        show_center=False,
        cols=8,
        rows=5,
        gutter_x=6.0,
        gutter_y=6.0,
        show_column_centers=False,
        show_baseline=False,
        baseline_step=4.215,
        baseline_offset=0.0,
        offset=(0.0, 0.0, 0.0),
    )

    l1 = L(name="l1").layer(l1)

    # ====================================================================
    title1 = G.text(
        activate=True,
        text="Grafix",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(11.413, 19, -0.8240000000000001),
        scale=15.354000000000001,
    )

    e_title1 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=312.71500000000003,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    title1 = e_title1(title1)

    title2 = G.text(
        activate=True,
        text="Principals",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(11.413, 32, 0.0),
        scale=15.354000000000001,
    )
    e_title2 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=664.407,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    title2 = e_title2(title2)

    title3 = G.text(
        activate=True,
        text="Creative Coding Framework",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(11.9, 12, 0.0),
        scale=4.237,
    )

    e_title3 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=530.508,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    title3 = e_title3(title3)
    title_black = L(name="title_black").layer([title1])
    title_gray = L(name="title_gray").layer([title2, title3])

    # ====================================================================
    g = G.polyhedron(
        activate=True,
        type_index=3,
        center=(45.652, 159.78300000000002, 0.0),
        scale=62.887,
    )

    e1 = E.rotate(
        activate=True,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
        rotation=(53.407000000000004, 67.253, 30.0),
    )

    e2 = E.translate(
        activate=True,
        delta=(68.478, 0.0, 0.0),
    ).fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=44.674,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    e3 = (
        E.translate(
            activate=True,
            delta=(71.429, 0.0, 0.0),
        )
        .subdivide(
            activate=True,
            subdivisions=3,
        )
        .displace(
            activate=True,
            amplitude=(8.0, 8.0, 8.0),
            spatial_freq=(0.04, 0.04, 0.04),
            amplitude_gradient=(0.0, 0.0, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            gradient_center_offset=(0.0, 0.0, 0.0),
            min_gradient_factor=0.1,
            max_gradient_factor=2.0,
            t=0.0,
        )
    )

    e4 = (
        E.affine(
            activate=True,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            rotation=(t * 10, t * 20, t * 30),
            scale=(1.0, 1.0, 1.0),
            delta=(142.308, 0.0, 0.0),
        )
        .subdivide(
            activate=True,
            subdivisions=3,
        )
        .displace(
            activate=True,
            amplitude=(4.0, 8.0, 12.0),
            spatial_freq=(0.06, 0.06, 0.06),
            amplitude_gradient=(0.0, 0.0, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            gradient_center_offset=(0.0, 0.0, 0.0),
            min_gradient_factor=0.1,
            max_gradient_factor=2.0,
            t=t * 0.025,
        )
    )

    g1 = e1(g)
    g2 = e2(g1)
    g3 = e3(g2)
    g4 = e4(g2)
    g = L(name="polyhedrons").layer([g1, g2, g3, g4])

    # ====================================================================
    text1 = G.text(
        activate=True,
        text="Principal1",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(11.6, 89, 0.0),
        scale=4.0,
    )

    e_text1 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=250.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    text1 = e_text1(text1)

    text2 = G.text(
        activate=True,
        text="Principal2",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(81.522, 89, 0.0),
        scale=4.0,
    )

    e_text2 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=250.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    text2 = e_text2(text2)

    text3 = G.text(
        activate=True,
        text="Principal3",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(151.63, 89, 0.0),
        scale=4.0,
    )

    e_text3 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=250.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    text3 = e_text3(text3)

    text4 = G.text(
        activate=True,
        text="Principal4",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(221.0, 89, 0.0),
        scale=4.0,
    )

    e_text4 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=250.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    text4 = e_text4(text4)

    text = L(name="Principals").layer([text1, text2, text3, text4])

    # ====================================================================
    discription1 = G(name="Discription1").text(
        activate=True,
        text="G.polyhedron()\nCreate a 3D polyhedral primitive.",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(11.5, 94, 0.0),
        scale=4.0,
    )

    e_discription1 = E.fill(density=450.0)
    discription1 = e_discription1(discription1)
    discription2 = G(name="Discription2").text(
        activate=True,
        text="E.fill()\nHatch the geometry with parallel\nlines to suggest surface.",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(81.5, 94, 0.0),
        scale=4.0,
    )

    e_discription2 = E.fill(density=450.0)
    discription2 = e_discription2(discription2)
    discription3 = G(name="Discription3").text(
        activate=True,
        text="E.subdivide().displace()\nSubdivide the line to smooth the \ncurve, and displace it to introduce\nmotion and variation.",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(151.648, 94, 0.0),
        scale=4.0,
    )

    e_discription3 = E.fill(density=450.0)
    discription3 = e_discription3(discription3)
    discription4 = G(name="Discription4").text(
        activate=True,
        text="E.displace(t=t)\nAnimate the displacement over time.",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(221.0, 94, 0.0),
        scale=4.0,
    )

    e_discription4 = E.fill(density=450.0)
    discription4 = e_discription4(discription4)
    discription = L(name="Discription").layer(
        [discription1, discription2, discription3, discription4]
    )

    # ====================================================================
    explanation = G.text(
        text=EXPLANATION,
        activate=True,
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(117.0, 7, 0.0),
        scale=4.0,
    )

    e_explanation = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=1000.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )
    explanation = e_explanation(explanation)
    explanation = L(name="explanation").layer([explanation])

    # ====================================================================
    h_line1 = G(name="HLine1").line(
        activate=True,
        center=(183.0, 83.0, 0.0),
        length=203.0,
        angle=0.0,
    )

    h_line2 = G.line(
        activate=True,
        center=(43.5, 83.0, 0.0),
        length=64.0,
        angle=0.0,
    )

    e_line2 = E.bold(
        activate=True,
        count=10,
        radius=0.192,
        seed=0,
    )

    h_line2 = e_line2(h_line2)

    line = L(name="line").layer([h_line1, h_line2])

    return (
        l1,
        title_black,
        title_gray,
        g,
        text,
        discription,
        explanation,
        line,
    )


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=4,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="7bit",
    )
