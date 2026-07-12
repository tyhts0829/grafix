from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from grafix import E, G, L, primitive, run

CANVAS_WIDTH = 117
CANVAS_HEIGHT = 147

PAPER = (247, 245, 239)
INK = (24, 25, 24)
RED = (197, 70, 41)
STRIP = (218, 209, 198)

STRIP_CUT = (48.25, 52.35)
RED_CENTER = (46.5, 115.6)
RED_RADIUS = 12.7


def _rgb255(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb
    return float(r) / 255.0, float(g) / 255.0, float(b) / 255.0


def _closed(points: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    if points[0] != points[-1]:
        points = [*points, points[0]]
    return tuple(points)


def _rect_points(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> tuple[tuple[float, float], ...]:
    return _closed([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _subtract_intervals(
    intervals: list[tuple[float, float]],
    cut: tuple[float, float],
) -> list[tuple[float, float]]:
    cut0, cut1 = cut
    out: list[tuple[float, float]] = []
    for x0, x1 in intervals:
        if x1 <= cut0 or cut1 <= x0:
            out.append((x0, x1))
            continue
        if x0 < cut0:
            out.append((x0, cut0))
        if cut1 < x1:
            out.append((cut1, x1))
    return [(x0, x1) for x0, x1 in out if x1 - x0 > 0.04]


def _circle_interval(
    *,
    y: float,
    center: tuple[float, float],
    radius: float,
) -> tuple[float, float] | None:
    cx, cy = center
    dy = y - cy
    if abs(dy) > radius:
        return None
    half = math.sqrt(max(0.0, radius * radius - dy * dy))
    return cx - half, cx + half


def _top_ring_intervals(y: float) -> list[tuple[float, float]]:
    outer = _circle_interval(y=y, center=(51.4, 38.0), radius=18.75)
    if outer is None:
        return []

    intervals = [outer]
    inner = _circle_interval(y=y, center=(51.4, 38.0), radius=9.55)
    if inner is not None:
        intervals = _subtract_intervals(intervals, inner)
    return _subtract_intervals(intervals, STRIP_CUT)


def _red_disc_intervals(y: float) -> list[tuple[float, float]]:
    interval = _circle_interval(y=y, center=RED_CENTER, radius=RED_RADIUS)
    if interval is None:
        return []
    return _subtract_intervals([interval], STRIP_CUT)


def _small_circle_intervals(y: float) -> list[tuple[float, float]]:
    interval = _circle_interval(y=y, center=(76.1, 128.2), radius=2.55)
    return [] if interval is None else [interval]


def _small_square_intervals(y: float) -> list[tuple[float, float]]:
    if 77.15 <= y <= 79.55:
        return [(30.6, 33.0)]
    return []


def _in_strip_gap(x: float) -> bool:
    return STRIP_CUT[0] <= x <= STRIP_CUT[1]


def _in_red_disc(x: float, y: float) -> bool:
    dx = x - RED_CENTER[0]
    dy = y - RED_CENTER[1]
    return dx * dx + dy * dy <= RED_RADIUS * RED_RADIUS


def _in_capsule(
    x: float,
    y: float,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    radius: float,
) -> bool:
    cx = min(max(x, x0 + radius), x1 - radius)
    cy = min(max(y, y0 + radius), y1 - radius)
    dx = x - cx
    dy = y - cy
    return dx * dx + dy * dy <= radius * radius


def _in_gate(x: float, y: float) -> bool:
    cap = (x - 62.3) ** 2 + (y - 80.2) ** 2 <= 15.25 * 15.25
    body = 47.6 <= x <= 77.2 and 79.0 <= y <= 111.2
    left_leg = 47.6 <= x <= 58.0 and 75.5 <= y <= 101.0
    outer = cap or body or left_leg
    if not outer:
        return False

    inner_slot = _in_capsule(
        x,
        y,
        x0=57.8,
        x1=66.0,
        y0=74.6,
        y1=113.6,
        radius=4.1,
    )
    if inner_slot or _in_strip_gap(x) or _in_red_disc(x, y):
        return False
    return True


def _sampled_intervals(
    y: float,
    *,
    x0: float,
    x1: float,
    step: float,
    predicate: Callable[[float, float], bool],
) -> list[tuple[float, float]]:
    xs = np.arange(x0, x1 + step, step)
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    prev_x = float(xs[0])
    for x in xs:
        xx = float(x)
        inside = predicate(xx, y)
        if inside and start is None:
            start = xx
        elif not inside and start is not None:
            intervals.append((start, prev_x))
            start = None
        prev_x = xx
    if start is not None:
        intervals.append((start, float(xs[-1])))
    return [(a, b) for a, b in intervals if b - a > 0.04]


@primitive
def horizontal_fill(
    *,
    kind: str = "top_ring",
    spacing: float = 0.17,
):
    kind_s = str(kind)
    spacing_f = max(0.05, float(spacing))

    if kind_s == "top_ring":
        y0, y1 = 19.0, 57.0
        interval_fn = _top_ring_intervals
    elif kind_s == "red_disc":
        y0, y1 = 102.5, 128.8
        interval_fn = _red_disc_intervals
    elif kind_s == "small_circle":
        y0, y1 = 125.4, 131.0
        interval_fn = _small_circle_intervals
    elif kind_s == "small_square":
        y0, y1 = 76.9, 79.8
        interval_fn = _small_square_intervals
    elif kind_s == "gate":
        y0, y1 = 62.5, 111.6

        def interval_fn(y: float) -> list[tuple[float, float]]:
            return _sampled_intervals(
                y,
                x0=45.5,
                x1=78.8,
                step=0.095,
                predicate=_in_gate,
            )

    else:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((1,), dtype=np.int32)

    lines: list[np.ndarray] = []
    for y in np.arange(y0, y1 + spacing_f * 0.5, spacing_f):
        yy = float(y)
        for x0, x1 in interval_fn(yy):
            lines.append(np.asarray([(x0, yy, 0.0), (x1, yy, 0.0)], dtype=np.float32))

    if not lines:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((1,), dtype=np.int32)

    offsets = np.zeros((len(lines) + 1,), dtype=np.int32)
    total = 0
    for i, line in enumerate(lines):
        total += int(line.shape[0])
        offsets[i + 1] = total
    return np.concatenate(lines, axis=0).astype(np.float32, copy=False), offsets


@primitive
def closed_shape(
    *,
    points: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
):
    coords = np.asarray([(x, y, 0.0) for x, y in points], dtype=np.float32)
    offsets = np.asarray([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


def _fill(
    g,
    *,
    angle: float = 0.0,
    density: float = 300.0,
    angle_sets: int = 1,
    remove_boundary: bool = False,
):
    return E.fill(
        angle_sets=angle_sets,
        angle=angle,
        density=density,
        spacing_gradient=0.0,
        remove_boundary=remove_boundary,
    )(g)


def draw(t: float):
    top_ring = G.horizontal_fill(kind="top_ring", spacing=0.155)
    gate = G.horizontal_fill(kind="gate", spacing=0.155)
    red_disc = G.horizontal_fill(kind="red_disc", spacing=0.155)
    small_square = G.horizontal_fill(kind="small_square", spacing=0.13)
    small_circle = G.horizontal_fill(kind="small_circle", spacing=0.13)

    strip_left = _fill(
        G.closed_shape(points=_rect_points(48.55, 10.6, 49.85, 134.0)),
        angle=90.0,
        density=520.0,
        remove_boundary=True,
    )
    strip_right = _fill(
        G.closed_shape(points=_rect_points(50.75, 10.6, 52.15, 134.0)),
        angle=90.0,
        density=520.0,
        remove_boundary=True,
    )

    return (
        L(name="black forms").layer(
            [top_ring, gate, small_square, small_circle],
            color=_rgb255(INK),
            thickness=0.0037,
        )
        + L(name="red circle").layer(
            red_disc,
            color=_rgb255(RED),
            thickness=0.0037,
        )
        + L(name="vertical pale strips").layer(
            [strip_left, strip_right],
            color=_rgb255(STRIP),
            thickness=0.0016,
        )
    )


if __name__ == "__main__":
    run(
        draw,
        background_color=_rgb255(PAPER),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
    )
