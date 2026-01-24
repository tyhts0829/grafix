"""
どこで: `sketch/presets/grn/a5_frame.py`。
何を: A5 向けのテンプレート枠（layout + template）を生成する preset。
なぜ: サンプル集の “テンプレフォーマット枠” を 1 つの呼び出しにまとめるため。
"""

from __future__ import annotations

from collections.abc import Mapping

from grafix import E, G, L, P, preset

CANVAS_SIZE = (148, 210)  # A5 (mm)


def _rgb255_to_rgb01(rgb255: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb255
    return float(r) / 255.0, float(g) / 255.0, float(b) / 255.0


meta: dict[str, Mapping[str, object]] = {
    "show_layout": {"kind": "bool"},
    "layout_color_rgb255": {"kind": "rgb", "ui_min": 0, "ui_max": 255},
    "number_text": {"kind": "str"},
    "explanation_text": {"kind": "str"},
    "template_color_rgb255": {"kind": "rgb", "ui_min": 0, "ui_max": 255},
}


@preset(meta=meta)
def grn_a5_frame(
    *,
    show_layout: bool = True,
    layout_color_rgb255: tuple[int, int, int] = (191, 191, 191),
    number_text: str = "1",
    explanation_text: str = "G.polygon()\nE.repeat().displace()",
    template_color_rgb255: tuple[int, int, int] = (0, 0, 0),
):
    layout_geom = P.layout_grid_system(
        activate=bool(show_layout),
        canvas_w=float(CANVAS_SIZE[0]),
        canvas_h=float(CANVAS_SIZE[1]),
        axes="both",
        margin_l=12.0,
        margin_r=12.0,
        margin_t=12.0,
        margin_b=12.0,
        show_center=False,
        cols=5,
        rows=8,
        gutter_x=4.0,
        gutter_y=4.0,
        show_column_centers=False,
        show_baseline=False,
        baseline_step=3.959,
        baseline_offset=0.0,
        offset=(0.0, 0.0, 0.0),
    )

    layout = L(name="layout").layer(
        layout_geom,
        color=_rgb255_to_rgb01(layout_color_rgb255),
    )

    line = G.line(
        activate=True,
        center=(11.5, 174.5, 0.0),
        anchor="left",
        length=124.5,
        angle=0.0,
    )

    series_name = G.text(
        activate=True,
        text="Grafix\nResearch\nNotes",
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=0.966,
        use_bounding_box=False,
        quality=0.5,
        center=(11.538, 178.022, 0.0),
        scale=7.388,
    )
    series_name = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=838.488,
        spacing_gradient=0.0,
        remove_boundary=False,
    )(series_name)

    number = G.text(
        activate=True,
        text=str(number_text),
        font="Helvetica.ttc",
        font_index=0,
        text_align="left",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=False,
        quality=0.5,
        center=(63.0, 178.022, 0.0),
        scale=4.553,
    )
    number = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=35.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )(number)

    explanation = G.text(
        activate=True,
        text=str(explanation_text),
        font="Helvetica.ttc",
        font_index=0,
        text_align="right",
        letter_spacing_em=0.0,
        line_height=1.2,
        use_bounding_box=True,
        box_width=46.907000000000004,
        box_height=20.103,
        show_bounding_box=False,
        quality=0.5,
        center=(136.0, 178.022, 0.0),
        scale=2.9210000000000003,
    )
    explanation = E.fill(
        activate=True,
        angle_sets=1,
        angle=45.0,
        density=300.0,
        spacing_gradient=0.0,
        remove_boundary=False,
    )(explanation)

    bar = G.polygon(
        activate=True,
        n_sides=4,
        phase=45.0,
        sweep=360.0,
        center=(126.923, 197.5, 0.0),
        scale=5.155,
    )
    bar = (
        E.scale(
            activate=True,
            mode="all",
            auto_center=True,
            pivot=(0.0, 0.0, 0.0),
            scale=(5.824, 0.22, 1.0),
        ).fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=97.938,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
    )(bar)

    template = L(name="template").layer(
        [
            line,
            series_name,
            number,
            explanation,
            bar,
        ],
        color=_rgb255_to_rgb01(template_color_rgb255),
    )
    return layout + template
