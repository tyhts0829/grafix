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
    l1 = P.layout_grid_system(canvas_h=CANVAS_HEIGHT, canvas_w=CANVAS_WIDTH)

    # ====================================================================
    title = G(name="title").text(
        activate=True,
        text="Grafix",
        font="HannariMincho-Regular.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(8.985, 33.107, 0.0),
        scale=29.592000000000002,
    )
    e_title = E(name="e_title").fill()
    title = e_title(title)

    # ====================================================================
    primitive = G(name="primitive").polyhedron(
        activate=True,
        type_index=3,
        center=(31.319, 65.385, 0.0),
        scale=34.768,
    )

    e_primitive = E(name="e_primitive").rotate(
        activate=True,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
        rotation=(-61.868, -149.061, 136.42600000000002),
    )

    primitive = e_primitive(primitive)
    filled_primitive = G(name="filled_primitive").polyhedron(
        activate=True,
        type_index=3,
        center=(74.176, 66.484, 0.0),
        scale=34.768,
    )

    e_filled_primitive = (
        E(name="e_filled_primitive")
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=35.0,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .rotate(
            activate=True,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            rotation=(-61.868, -149.061, 136.42600000000002),
        )
    )

    filled_primitive = e_filled_primitive(filled_primitive)
    displaced_primitive = G(name="displaced_primitive").polyhedron(
        activate=True,
        type_index=3,
        center=(117.033, 65.934, 0.0),
        scale=33.677,
    )

    e_displaced_primitive = (
        E(name="e_displaced_primitive")
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=35.0,
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
            t=0.266,
        )
        .rotate(
            activate=True,
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            rotation=(-61.868, -149.061, 136.42600000000002),
        )
    )
    displaced_primitive = e_displaced_primitive(displaced_primitive)

    polyhedron = G(name="polyhedron").text(
        activate=True,
        text="polyhedron()",
        font="HackGen35-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(32.967, 90.82600000000001, 0.0),
        scale=2.871,
    )

    e_polyhedron = E(name="e_polyhedron").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=35.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    polyhedron = e_polyhedron(polyhedron)
    fill = G(name="fill").text(
        activate=True,
        text="fill()",
        font="HackGen35-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(75.0, 90.82600000000001, 0.0),
        scale=2.871,
    )

    e_fill = E(name="e_fill").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=35.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    fill = e_fill(fill)
    displace = G(name="displace").text(
        activate=True,
        text="displace()",
        font="HackGen35-Regular.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        quality=0.5,
        center=(117.033, 90.82600000000001, 0.0),
        scale=2.871,
    )

    e_displace = E(name="e_displace").fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=35.0,
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
        title,
        primitive,
        filled_primitive,
        displaced_primitive,
        polyhedron,
        fill,
        displace,
        discription,
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
