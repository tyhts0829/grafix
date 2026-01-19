from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
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
        canvas_w=148.0,
        canvas_h=210.0,
        axes="both",
        margin_l=10.0,
        margin_r=10.0,
        margin_t=10.0,
        margin_b=8.935,
        show_center=False,
        cols=3,
        rows=5,
        gutter_x=2.0,
        gutter_y=3.608,
        show_column_centers=False,
        show_baseline=False,
        baseline_step=2.672,
        baseline_offset=0.0,
        offset=(0.0, 0.0, 0.0),
    )

    # ====================================================================
    title1 = G.text(
        activate=False,
        text="GRA",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(8.985, 21.429000000000002, 0.0),
        scale=14.691,
    )

    e_title1 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=333.333,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    title1 = e_title1(title1)

    title2 = G.text(
        activate=False,
        text="FIX",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.22,
        line_height=1.2,
        quality=0.5,
        center=(9.615, 34.615, 0.0),
        scale=14.691,
    )

    e_title2 = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=333.333,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    title2 = e_title2(title2)

    # ====================================================================

    displaced_primitive = G.polyhedron(
        activate=True,
        type_index=3,
        center=(95.604, 47.802, 0.0),
        scale=68.385,
    )

    e_displaced_primitive = (
        E.fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=80.756,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .subdivide(
            activate=True,
            subdivisions=4,
        )
        .displace(
            activate=True,
            amplitude=(4.0, 4.0, 4.0),
            spatial_freq=(0.06, 0.06, 0.06),
            amplitude_gradient=(0.0, 0.0, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            gradient_center_offset=(0.0, 0.0, 0.0),
            min_gradient_factor=0.1,
            max_gradient_factor=2.0,
            t=t * 0.1,
        )
        .rotate(
            activate=True,
            auto_center=True,
            rotation=(t * 6, t * 8, t * 12),
        )
    )

    displaced_primitive = e_displaced_primitive(displaced_primitive)
    displace = G.text(
        activate=True,
        text="def draw(t):\n    dodeca = G.polyhedron(type_index=4)\n    effs = E.fill().subdivide().displace(t=t*0.1)\n    return effs(dodeca)",
        font="HackGen35-Regular.ttf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(53.846000000000004, 90.82600000000001, 0.0),
        scale=2.871,
    )

    e_displace = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=824.742,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    displace = e_displace(displace)

    # ====================================================================

    discription = G(name="description").text(
        activate=True,
        text="\nGrafix is a line-based creative coding framework for Python\nthat approaches visual design with an audio mindset, treating\nconstraints as a source of creativity rather than a limitation.\n\nYou build sketches from primitives (G), shape them through\nmethod-chained processors to form synth-like effect (E), and\norganize the result into layers (L) that carry their own color\nand line width, like pen changes on a plotter.\n\nParameters can be mapped to MIDI CC (cc) and driven\nover time, so geometry becomes something you can play.\n\nA real-time OpenGL preview (run(draw(t))) keeps iteration,\nwhile the same patch can be exported to PNG, SVG, G-code,\nand MP4, providing a continuous path from experimentation\nto both on-screen playback and physical output.\n\nNew primitives and effects are defined as Python decorators,\nkeeping the system extensible without collapsing into\na monolithic graphics API.\n",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.221,
        quality=0.5,
        center=(10.938, 126.18, 0.0),
        scale=2.871,
    )

    e_discription = E(name="e_description").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=1000.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )
    discription = e_discription(discription)

    return (
        l1,
        title1,
        title2,
        displaced_primitive,
        displace,
        discription,
        P.logo(),
        P.flow(),
    )


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
