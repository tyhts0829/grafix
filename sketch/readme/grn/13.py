from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text=(Path(__file__).stem),
        explanation_text="G.text()\nE.pixelate()\n.lowpass().fill()",
        explanation_density=500.0,
        template_color_rgb255=(255, 255, 255),
    )

    g = G.text(
        activate=True,
        text="グラフィックス\nパイソンベース\nクリエイティブ\nコーディング\nフレームワーク\n\n",
        font="Hiragino Sans GB.ttc",
        font_index=0,
        text_align="center",
        letter_spacing_em=-0.10400000000000001,
        line_height=1.431,
        use_bounding_box=False,
        quality=0.5,
        center=(74.176, 34.615, 0.0),
        scale=16.581,
    )

    e = (
        E.pixelate(
            activate=True,
            step=(3.7800000000000002, 3.7800000000000002, 1.0),
            corner="yx",
        )
        .lowpass(
            activate=True,
            step=0.157,
            sigma=0.9450000000000001,
            closed="auto",
        )
        .fill(
            activate=True,
            angle_sets=1,
            angle=45.0,
            density=527.491,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
    )

    g = e(g)
    return frame, g


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
