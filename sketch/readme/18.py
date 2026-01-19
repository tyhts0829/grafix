from grafix import E, G, L, P, run

# A4_LANDSCAPE
CANVAS_WIDTH = 297
CANVAS_HEIGHT = 210

DESCRIPTION = """
Grafix is a line-based creative coding framework for Python
that approaches visual design with an audio mindset, treating
constraints as a source of creativity rather than a limitation.

You build sketches from primitives (G), shape them through
method-chained processors to form synth-like effect (E), and
organize the result into layers (L) that carry their own color
and line width, like pen changes on a plotter.

Parameters can be mapped to MIDI CC (cc) and driven
over time, so geometry becomes something you can play.

A real-time OpenGL preview (run(draw(t))) keeps iteration,
while the same patch can be exported to PNG, SVG, G-code,
and MP4, providing a continuous path from experimentation
to both on-screen playback and physical output.

New primitives and effects are defined as Python decorators,
keeping the system extensible without collapsing into
a monolithic graphics API.
"""


def draw(t):
    l1 = P.layout_grid_system(
        activate=True,
        canvas_w=297.0,
        canvas_h=210.0,
        axes="both",
        margin_l=10.0,
        margin_r=10.0,
        margin_t=10.0,
        margin_b=8.935,
        show_center=False,
        cols=8,
        rows=5,
        gutter_x=2.0,
        gutter_y=3.608,
        show_column_centers=False,
        show_baseline=False,
        baseline_step=2.672,
        baseline_offset=0.0,
        offset=(0.0, 0.0, 0.0),
    )
    l1 = L(name="l1", geometry_or_list=l1)

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
        center=(10.236, 29.67, -0.8240000000000001),
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
        center=(10.236, 44.505, 0.0),
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
        center=(11.413, 14.674, 0.0),
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
    title_black = L(name="title_black", geometry_or_list=[title1])
    title_gray = L(name="title_gray", geometry_or_list=[title2, title3])
    return (l1, title_black, title_gray)


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=4,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="TX-6 Bluetooth",
        midi_mode="7bit",
    )
