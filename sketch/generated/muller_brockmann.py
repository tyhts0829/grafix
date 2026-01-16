"""
どこで: `sketch/generated/muller_brockmann.py`。
何を: Josef Müller-Brockmann へのオマージュとして、グリッドと円弧で構成したポスター風の 1 枚を生成する。
なぜ: 「配置」と「余白」を主役にした、反復改良しやすいベースを用意するため。
"""

from __future__ import annotations

import math

from grafix import E, G, L

# A4 portrait (mm)
CANVAS_SIZE = (210, 297)


def _line_between(
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    z: float = 0.0,
):
    dx = float(x1) - float(x0)
    dy = float(y1) - float(y0)
    length = math.hypot(dx, dy)
    angle = math.degrees(math.atan2(dy, dx)) if length > 0.0 else 0.0
    return G.line(
        center=(0.5 * (float(x0) + float(x1)), 0.5 * (float(y0) + float(y1)), float(z)),
        length=float(length),
        angle=float(angle),
    )


def _rect(*, x: float, y: float, w: float, h: float, z: float = 0.0):
    """軸平行な矩形（閉ポリライン）。"""
    unit = G.polygon(n_sides=4, phase=45.0, center=(0.0, 0.0, float(z)), scale=math.sqrt(2.0))
    cx = float(x) + 0.5 * float(w)
    cy = float(y) + 0.5 * float(h)
    return E.affine(scale=(float(w), float(h), 1.0), delta=(cx, cy, 0.0))(unit)


def _circle(*, cx: float, cy: float, r: float, phase_deg: float, z: float = 0.0, n: int = 256):
    """円（多角形近似、閉ポリライン）。"""
    return G.polygon(
        n_sides=int(n),
        phase=float(phase_deg),
        center=(float(cx), float(cy), float(z)),
        scale=2.0 * float(r),
    )


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
    z: float = 0.0,
):
    out = None
    w = float(x1) - float(x0)
    h = float(y1) - float(y0)
    if cols <= 0 or rows <= 0 or w <= 0.0 or h <= 0.0:
        return G.line(center=(float(x0), float(y0), float(z)), length=0.0, angle=0.0)

    for ci in range(0, int(cols) + 1, max(1, int(step_cols))):
        x = float(x0) + w * (float(ci) / float(cols))
        g = G.line(center=(x, float(y0) + 0.5 * h, float(z)), length=h, angle=90.0)
        out = g if out is None else out + g

    for ri in range(0, int(rows) + 1, max(1, int(step_rows))):
        y = float(y0) + h * (float(ri) / float(rows))
        g = G.line(center=(float(x0) + 0.5 * w, y, float(z)), length=w, angle=0.0)
        out = g if out is None else out + g

    if out is None:
        return G.line(center=(float(x0), float(y0), float(z)), length=0.0, angle=0.0)
    return out


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

    u = float(t) % 1.0
    wig = 0.5 - 0.5 * math.cos(2.0 * math.pi * u)

    grid = _grid(
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        cols=cols,
        rows=rows,
        step_cols=2,
        step_rows=3,
    )

    block_x = x0 + 8.0 * cell_w
    block_y = y0 + 1.0 * cell_h
    block_w = 4.0 * cell_w
    block_h = 8.0 * cell_h
    block = _rect(x=block_x, y=block_y, w=block_w, h=block_h)
    block = E.fill(angle=90.0, density=32.0 + 18.0 * wig, remove_boundary=False)(block)

    cx = x0 + 4.0 * cell_w
    cy = y0 + 10.0 * cell_h
    radii = (92.0, 74.0, 56.0, 38.0)
    arcs = None
    for i, r in enumerate(radii):
        phase = 360.0 * u + 24.0 * float(i)
        circle = _circle(cx=cx, cy=cy, r=r, phase_deg=phase, n=256)
        start = 0.10 + 0.02 * float(i)
        end = min(0.92, 0.74 + 0.06 * math.sin(2.0 * math.pi * u + 0.7 * float(i)) + 0.02 * float(i))
        arc = E.trim(start_param=start, end_param=end)(circle)
        arcs = arc if arcs is None else arcs + arc

    axis_x = x0 + 6.0 * cell_w
    axis = G.line(center=(axis_x, y0 + 0.5 * (y1 - y0), 0.0), length=(y1 - y0), angle=90.0)
    rule = _line_between(x0=x0, y0=y1 - 5.0 * cell_h, x1=x0 + 7.0 * cell_w, y1=y1 - 5.0 * cell_h)

    type_block = G.text(
        text="MULLER\nBROCKMANN",
        text_align="left",
        letter_spacing_em=0.06,
        line_height=1.05,
        quality=0.35,
        center=(x0, y1 - 1.0 * cell_h, 0.0),
        scale=10.0,
    )

    caption = G.text(
        text="STUDY / GRID / ARC",
        text_align="left",
        letter_spacing_em=0.08,
        line_height=1.0,
        quality=0.25,
        center=(x0, y0 + 2.0 * cell_h, 0.0),
        scale=4.0,
    )

    red_mark = _rect(x=block_x - 1.0 * cell_w, y=block_y + block_h - 1.0 * cell_h, w=cell_w, h=cell_h)
    red_mark = E.fill(angle=0.0, density=18.0, remove_boundary=False)(red_mark)

    layers: list[object] = []
    layers += L(grid, thickness=0.00055, name="grid")
    layers += L(axis + rule + caption + type_block, thickness=0.00105, name="type")
    layers += L(block, thickness=0.00075, name="block")
    layers += L(arcs, thickness=0.00125, color=(0.85, 0.0, 0.0), name="accent")
    layers += L(red_mark, thickness=0.0009, color=(0.85, 0.0, 0.0), name="accent_mark")
    return layers


__all__ = ["CANVAS_SIZE", "draw"]

