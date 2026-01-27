from __future__ import annotations

from pathlib import Path

import numpy as np
from numba import njit

from grafix import E, G, P, run
from grafix.api import primitive
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    g = G.text(
        activate=True,
        text="Grafix",
        font="Geist-Black.ttf",
        font_index=0,
        text_align="center",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(75.824, 72.527, 0.0),
        scale=32.01,
    )

    e = E.reaction_diffusion(
        activate=True,
        grid_pitch=0.386,
        steps=1134,
        du=0.191,
        dv=0.038,
        feed=0.022,
        kill=0.058,
        dt=0.9420000000000001,
        seed=42,
        seed_radius=46.392,
        noise=0.041,
        level=0.057,
        min_points=5,
        boundary="dirichlet",
    ).fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=3000.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )

    g = e(g)

    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="12",
        explanation_text="G.text()\nE.reaction_diffusion()\n.fill()",
        explanation_density=500.0,
        template_color_rgb255=(255, 255, 255),
    )

    return g, frame


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
