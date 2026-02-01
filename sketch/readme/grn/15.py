from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210
DESCRIPTION = """This framework approaches visual design with an audio mindset.A minimal, line-based geometry engine keeps the representation intentionally simple,treating constraints as a source of creativity rather than a limitation.

Instead of hiding structure and styling decisions inside a black-box renderer,grafix keeps them close to your code: you build multi-layer sketcheswhere each layer can carry its own color and line weight,echoing pen changes in a plotter.Effects are composed as method-chained processors,forming an effect chain that feels closer to a synth and pedalboard than a monolithic graphics API.

MIDI control and LFO-driven modulation keep parameters in constant motion,making geometry something you can “play” rather than merely render.From real-time OpenGL preview to pen-plotter-ready G-code,grafix offers a continuous path from experimental patch to physical output,with new Shapes and Effects defined as lightweight Python decorators.The aim is not just to produce images, but to compose line-based scores that unfold in time,on screen and on paper."""


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="15",
        explanation_text="G.asemic()\nE.quantize()\n.lowpass().bold()",
        explanation_density=500.0,
        template_color_rgb255=(255, 255, 255),
    )

    g = G.asemic(
        activate=True,
        text="This framework approaches visual design with an audio mindset.A minimal, line-based geometry engine keeps the representation intentionally simple,treating constraints as a source of creativity rather than a limitation.\n\nInstead of hiding structure and styling decisions inside a black-box renderer,grafix keeps them close to your code: you build multi-layer sketcheswhere each layer can carry its own color and line weight,echoing pen changes in a plotter.Effects are composed as method-chained processors,forming an effect chain that feels closer to a synth and pedalboard than a monolithic graphics API.\n\nMIDI control and LFO-driven modulation keep parameters in constant motion,making geometry something you can “play” rather than merely render.\n\nFrom real-time OpenGL preview to pen-plotter-ready G-code,grafix offers a continuous path from experimental patch to physical output,with new Shapes and Effects defined as lightweight Python decorators.The aim is not just to produce images, but to compose line-based scores that unfold in time,on screen and on paper.",
        seed=214776,
        n_nodes=5,
        candidates=4,
        stroke_min=3,
        stroke_max=6,
        walk_min_steps=2,
        walk_max_steps=5,
        stroke_style="bezier",
        bezier_samples=12,
        bezier_tension=0.366,
        text_align="left",
        glyph_advance_em=1.155,
        space_advance_em=1.371,
        letter_spacing_em=-0.078,
        line_height=1.828,
        use_bounding_box=True,
        box_width=125.258,
        box_height=-1.0,
        show_bounding_box=False,
        center=(13.187, 13.187, 0.0),
        scale=2.603,
    )

    e = (
        E.quantize(
            activate=True,
            step=(0.965, 0.965, 0.965),
        )
        .lowpass(
            activate=True,
            step=0.619,
            sigma=0.328,
            closed="open",
        )
        .bold(
            activate=True,
            count=100,
            radius=0.134,
            seed=0,
        )
    )

    g = e(g)
    return frame, g


if __name__ == "__main__":
    run(
        draw,
        background_color=(0.0, 0.0, 0.0),
        line_thickness=0.001,
        line_color=(1.0, 1.0, 1.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        # midi_mode="14bit",
    )
