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
    g = G.text()
    e = E.fill()
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
