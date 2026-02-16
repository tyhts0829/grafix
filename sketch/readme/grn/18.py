from pathlib import Path

from grafix import G, L, P, cc, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210

# CONST
N_ROWS = 6
N_COLS = 4


def draw(t):
    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        number_text=Path(__file__).stem,
        explanation_text="G.lissajous()",
        explanation_density=450.0,
        template_color_rgb255=(255, 255, 255),
    )

    gs = []
    # WHITE_SPACEの幅、高さをccで制御できるようにする
    WS_X = cc[1] * 50.0  # 0.0 ~ 20.0
    WS_Y = cc[2] * 50.0  # 0.0
    OFFSET_Y = (cc[3] - 0.5) * 50

    # coefs
    coef_a = int(cc[4] * 10) + 1  # 1 ~ 11
    coef_b = int(cc[5] * 10) + 1  #

    for i in range(N_COLS):
        for j in range(N_ROWS):
            cx = WS_X + (i + 0.5) * (CANVAS_WIDTH - 2 * WS_X) / N_COLS
            cy = WS_Y + (j + 0.5) * (CANVAS_HEIGHT - 2 * WS_Y) / N_ROWS + OFFSET_Y
            g = G.lissajous(
                center=(cx, cy, 0.0),
                a=j + coef_a,
                b=i + coef_b,
                samples=10,
            )
            gs.append(g)
    gs = L.layer(gs, color=(1.0, 1.0, 1.0))

    return gs, frame


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
