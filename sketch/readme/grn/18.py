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
    g = G.polygon(
        activate=True,
        n_sides=128,
        phase=89.08500000000001,
        sweep=360.0,
        center=(74.176, 86.413, 0.0),
        scale=108.81400000000001,
    )

    e = E.reaction_diffusion(
        activate=True,
        grid_pitch=0.298,
        steps=4500,
        du=0.16,
        dv=0.08,
        feed=0.029,
        kill=0.057,
        dt=1.0,
        seed=42,
        seed_radius=10.0,
        noise=0.02,
        level=0.2,
        min_points=24,
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
        number_text=str(Path(__file__).stem),
        explanation_density=500.0,
        template_color_rgb255=(255, 255, 255),
    )

    return g, frame


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
        midi_mode="14bit",
    )
