from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210

DESCRIPTION = """
Grafix is a line-based creative coding
framework for Python that approaches
visual design with an audio mindset,
treating constraints as a source of
creativity rather than a limitation.

You build sketches from simple primitives (G),
shape them through method-chained processors
to form synth-like effect chains (E), and
organize the result into layers that carry their
own color and line weight (L)—echoing pen changes
on a plotter.

Parameters can be mapped to MIDI CC (cc) and
driven over time, so geometry becomes something
you can “play” instead of merely render.

A real-time OpenGL preview (run(draw(t))) keeps
iteration tight, while the same patch can be
exported to PNG, SVG, pen-plotter-ready G-code,
and MP4, providing a continuous path from
experimentation to both on-screen playback and
physical output. New primitives and effects are
defined as lightweight Python decorators, keeping
the system extensible without collapsing
into a monolithic graphics API.
"""


def draw(t):
    l1 = P.layout_grid_system(canvas_h=CANVAS_HEIGHT, canvas_w=CANVAS_WIDTH)
    discription = G(name="description").text(text=DESCRIPTION)
    return l1, discription


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
