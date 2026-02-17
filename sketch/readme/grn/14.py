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
        text="grafix is \na python-based\ncreative coding\nframework.",
        font="karakaze-R.otf",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.017,
        line_height=1.087,
        use_bounding_box=False,
        quality=0.5,
        center=(19.78, 59.341, 0.0),
        scale=14.003,
    )

    e = (
        E.pixelate(
            activate=True,
            step=(1.719, 1.719, 1.0),
            corner="yx",
        )
        .lowpass(
            activate=True,
            step=0.275,
            sigma=1.8900000000000001,
            closed="auto",
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=1000.0,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .affine(
            activate=True,
            auto_center=True,
            rotation=(0.0, 0.0, 0.0),
            scale=(0.8, 0.8, 1.0),
            delta=(3.261, 1.087, 0.0),
        )
    )

    g = e(g)

    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text="14",
        explanation_text="G.text()\nE.pixelate()\n.lowpass().fill()",
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
