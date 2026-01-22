"""
どこで: `sketch/generated/muller_brockmann_generative.py`。
何を: Müller-Brockmann 的なグリッド構成に、生成的な「崩れ（ノイズ変位）」を衝突させたポスター風スケッチ。
なぜ: 秩序（grid / タイポ）と生成（perlin 変位 / リズム）の同居を、少ない要素で成立させるため。
"""

from __future__ import annotations

import math

from grafix import E, G, L

# A4 portrait (mm)
CANVAS_SIZE = (210, 297)


def _smoothstep(u: float) -> float:
    x = float(u)
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * (3.0 - 2.0 * x)


def _grid(
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    cols: int,
    rows: int,
    step_cols: int,
    step_rows: int,
):
    out = None
    w = float(x1) - float(x0)
    h = float(y1) - float(y0)
    for ci in range(0, int(cols) + 1, max(1, int(step_cols))):
        x = float(x0) + w * (float(ci) / float(cols))
        g = G.line(center=(x, float(y0) + 0.5 * h, 0.0), length=h, angle=90.0)
        out = g if out is None else out + g
    for ri in range(0, int(rows) + 1, max(1, int(step_rows))):
        y = float(y0) + h * (float(ri) / float(rows))
        g = G.line(center=(float(x0) + 0.5 * w, y, 0.0), length=w, angle=0.0)
        out = g if out is None else out + g
    return out


def _circle(*, cx: float, cy: float, r: float, phase_deg: float, n: int = 192):
    return G.polygon(
        n_sides=int(n),
        phase=float(phase_deg),
        center=(float(cx), float(cy), 0.0),
        scale=2.0 * float(r),
    )


def draw(t: float):
    w, h = CANVAS_SIZE
    margin = 12.0
    x0 = float(margin)
    y0 = float(margin)
    x1 = float(w) - float(margin)
    y1 = float(h) - float(margin)

    cols = 12
    rows = 18
    cell_w = (x1 - x0) / float(cols)
    cell_h = (y1 - y0) / float(rows)

    u = max(0.0, min(1.0, float(t)))
    k = _smoothstep(u)

    # --- background grid (order) ---
    minor = _grid(x0=x0, y0=y0, x1=x1, y1=y1, cols=cols, rows=rows, step_cols=1, step_rows=1)
    major = _grid(x0=x0, y0=y0, x1=x1, y1=y1, cols=cols, rows=rows, step_cols=3, step_rows=3)

    axis_x = x0 + 6.0 * cell_w
    axis = G.line(center=(axis_x, y0 + 0.5 * (y1 - y0), 0.0), length=(y1 - y0), angle=90.0)
    rule_y = y0 + (3.0 + 2.0 * k) * cell_h
    rule = G.line(center=(x0 + 3.5 * cell_w, rule_y, 0.0), length=7.0 * cell_w, angle=0.0)

    # --- generative arcs (noise meets grid) ---
    cx = x0 + (4.0 + 0.8 * k) * cell_w
    cy = y0 + (10.0 - 0.6 * k) * cell_h
    radii = (96.0, 78.0, 60.0, 42.0)

    arcs = None
    base_amp = 0.0 + 4.5 * k
    for i, r in enumerate(radii):
        phase = 12.0 * float(i)
        circle = _circle(cx=cx, cy=cy, r=r, phase_deg=phase, n=192)
        start = 0.10 + 0.02 * float(i) + 0.06 * k
        end = 0.90 - 0.01 * float(i) - 0.10 * k
        arc = E.trim(start_param=start, end_param=end)(circle)
        amp_i = base_amp * (0.70 + 0.18 * float(i))
        arc = E.displace(
            amplitude=(amp_i, amp_i, 0.0),
            spatial_freq=(0.045, 0.032, 0.0),
            t=u,
        )(arc)
        arcs = arc if arcs is None else arcs + arc

    # accent: crisp arc segment that slides with t (Swiss red mark)
    outer = _circle(cx=cx, cy=cy, r=radii[0], phase_deg=0.0, n=192)
    a0 = 0.04 + 0.42 * k
    a1 = a0 + 0.10
    accent = E.trim(start_param=a0, end_param=a1)(outer)

    # --- rhythm block (generative but geometric) ---
    barcode = None
    bx = x1 - 2.0 * cell_w
    for ri in range(rows):
        yy = y0 + (float(ri) + 0.5) * cell_h
        v = 0.5 - 0.5 * math.cos(2.0 * math.pi * (0.12 * float(ri) + 0.85 * k))
        length = cell_w * (1.0 + 3.2 * v)
        g = G.line(center=(bx, yy, 0.0), length=length, angle=0.0)
        barcode = g if barcode is None else barcode + g

    # --- type ---
    title = G.text(
        text="GRID\nNOISE",
        text_align="left",
        letter_spacing_em=0.08,
        line_height=1.02,
        quality=0.35,
        center=(x0, y1 - 1.0 * cell_h, 0.0),
        scale=12.0,
    )
    caption = G.text(
        text="MULLER / BROCKMANN / GENERATIVE",
        text_align="left",
        letter_spacing_em=0.07,
        line_height=1.0,
        quality=0.25,
        center=(x0, y0 + 1.6 * cell_h, 0.0),
        scale=4.2,
    )

    layers: list[object] = []
    layers += L(name="grid_minor").layer(minor, thickness=0.00032)
    layers += L(name="grid_major").layer(major, thickness=0.00052)
    layers += L(name="rules").layer(axis + rule, thickness=0.00105)
    layers += L(name="rhythm").layer(barcode, thickness=0.00078)
    layers += L(name="arcs").layer(arcs, thickness=0.00120)
    layers += L(name="accent").layer(
        accent, thickness=0.00125, color=(0.85, 0.0, 0.0)
    )
    layers += L(name="type").layer(title + caption, thickness=0.00110)
    return layers


__all__ = ["CANVAS_SIZE", "draw"]
