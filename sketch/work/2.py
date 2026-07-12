from __future__ import annotations

import math

import numpy as np

from grafix import E, G, L, primitive, run

CANVAS_WIDTH = 117
CANVAS_HEIGHT = 147

PAPER = (247, 242, 235)
INK = (22, 23, 22)
RED = (229, 73, 38)
HAIRLINE = (68, 70, 66)


def _rgb255(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb
    return float(r) / 255.0, float(g) / 255.0, float(b) / 255.0


def _arc(
    center: tuple[float, float],
    radius: tuple[float, float],
    start: float,
    end: float,
    steps: int,
) -> list[tuple[float, float]]:
    cx, cy = center
    rx, ry = radius
    angles = np.linspace(math.radians(start), math.radians(end), steps)
    return [
        (cx + math.cos(float(a)) * rx, cy + math.sin(float(a)) * ry) for a in angles
    ]


def _cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int,
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for u in np.linspace(0.0, 1.0, steps)[1:]:
        uu = float(u)
        v = 1.0 - uu
        x = (
            v * v * v * p0[0]
            + 3.0 * v * v * uu * p1[0]
            + 3.0 * v * uu * uu * p2[0]
            + uu * uu * uu * p3[0]
        )
        y = (
            v * v * v * p0[1]
            + 3.0 * v * v * uu * p1[1]
            + 3.0 * v * uu * uu * p2[1]
            + uu * uu * uu * p3[1]
        )
        out.append((x, y))
    return out


def _closed(points: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    if points[0] != points[-1]:
        points = [*points, points[0]]
    return tuple(points)


def _black_body_points() -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    points.extend(_arc((37.2, 18.2), (6.7, 6.5), -180.0, -90.0, 18))
    points.append((51.0, 11.7))
    points.extend(_arc((51.0, 18.2), (6.7, 6.5), -90.0, 0.0, 18)[1:])
    points.append((57.7, 34.4))
    points.extend(_cubic((57.7, 34.4), (57.7, 42.6), (63.0, 47.7), (71.2, 47.8), 28))
    points.extend(_cubic((71.2, 47.8), (81.8, 47.8), (88.2, 56.4), (88.2, 67.0), 34))
    points.append((88.2, 100.8))
    points.extend(
        _cubic((88.2, 100.8), (88.2, 111.7), (80.8, 118.3), (68.5, 118.3), 32)
    )
    points.append((49.2, 118.3))
    points.extend(_cubic((49.2, 118.3), (37.6, 118.3), (30.5, 111.4), (30.5, 99.4), 34))
    points.append((30.5, 91.2))
    points.extend(_cubic((30.5, 91.2), (30.5, 82.4), (39.0, 77.0), (49.0, 77.0), 30))
    points.append((52.8, 77.0))
    points.extend(_cubic((52.8, 77.0), (61.6, 76.5), (65.2, 67.0), (59.0, 60.0), 28))
    points.extend(_cubic((59.0, 60.0), (52.2, 52.2), (39.7, 52.7), (37.1, 64.7), 32))
    points.append((36.9, 69.5))
    points.extend(_cubic((36.9, 69.5), (36.9, 72.4), (35.1, 73.7), (32.8, 73.5), 16))
    points.extend(_cubic((32.8, 73.5), (30.9, 73.4), (30.5, 71.2), (30.5, 68.5), 12))
    points.append((30.5, 18.2))
    return _closed(points)


def _lower_field_points() -> tuple[tuple[float, float], ...]:
    points = [(36.0, 91.7)]
    points.extend(_cubic((36.0, 91.7), (36.5, 84.4), (43.4, 80.9), (50.0, 81.1), 28))
    points.extend(_cubic((50.0, 81.1), (58.8, 81.4), (60.8, 72.5), (68.6, 72.5), 28))
    points.extend(_cubic((68.6, 72.5), (78.7, 72.5), (84.4, 82.4), (84.5, 95.7), 34))
    points.extend(_cubic((84.5, 95.7), (84.7, 110.5), (76.2, 116.5), (64.0, 116.4), 36))
    points.append((49.6, 116.4))
    points.extend(
        _cubic((49.6, 116.4), (40.4, 116.2), (35.0, 111.2), (34.5, 102.0), 34)
    )
    points.extend(_cubic((34.5, 102.0), (34.2, 97.0), (34.3, 93.8), (36.0, 91.7), 22))
    return _closed(points)


def _shadow_points() -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for a in np.linspace(0.0, 2.0 * math.pi, 160, endpoint=False):
        aa = float(a)
        points.append((58.0 + math.cos(aa) * 25.7, 130.6 + math.sin(aa) * 0.78))
    return _closed(points)


def _circle_points(
    center: tuple[float, float],
    radius: float,
    *,
    steps: int = 220,
) -> tuple[tuple[float, float], ...]:
    cx, cy = center
    points: list[tuple[float, float]] = []
    for a in np.linspace(0.0, 2.0 * math.pi, steps, endpoint=False):
        aa = float(a)
        points.append((cx + math.cos(aa) * radius, cy + math.sin(aa) * radius))
    return _closed(points)


def _as_ring(points: tuple[tuple[float, float], ...]) -> np.ndarray:
    return np.asarray([(x, y, 0.0) for x, y in points], dtype=np.float32)


def _inside(point: tuple[float, float], ring: np.ndarray) -> bool:
    x, y = point
    inside = False
    j = ring.shape[0] - 1
    for i in range(ring.shape[0]):
        xi = float(ring[i, 0])
        yi = float(ring[i, 1])
        xj = float(ring[j, 0])
        yj = float(ring[j, 1])
        if (yi > y) != (yj > y):
            x_at_y = (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi
            if x < x_at_y:
                inside = not inside
        j = i
    return inside


@primitive
def closed_shape(
    *,
    points: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
):
    coords = _as_ring(points)
    offsets = np.asarray([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


@primitive
def flow_lines(
    *,
    boundary: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ),
    count: int | float = 70,
    samples: int | float = 240,
):
    ring = _as_ring(boundary)
    min_x = float(np.min(ring[:, 0])) - 1.8
    max_x = float(np.max(ring[:, 0])) + 1.8
    min_y = float(np.min(ring[:, 1])) - 1.5
    max_y = float(np.max(ring[:, 1])) + 1.5
    xs = np.linspace(min_x, max_x, max(12, int(round(float(count)))))
    ys = np.linspace(min_y, max_y, max(80, int(round(float(samples)))))

    polylines: list[np.ndarray] = []
    for i, base_x in enumerate(xs):
        phase = i * 0.71
        current: list[tuple[float, float, float]] = []
        for y in ys:
            yy = float(y)
            center_swirl = math.exp(
                -(((float(base_x) - 55.5) ** 2) / 80.0 + ((yy - 100.0) ** 2) / 150.0)
            )
            upper_swirl = math.exp(
                -(((float(base_x) - 69.0) ** 2) / 90.0 + ((yy - 82.0) ** 2) / 95.0)
            )
            lower_drift = math.exp(
                -(((float(base_x) - 58.0) ** 2) / 150.0 + ((yy - 112.0) ** 2) / 42.0)
            )
            x = (
                float(base_x)
                + 1.55 * math.sin(yy * 0.18 + phase)
                + 0.85 * math.sin(yy * 0.055 + float(base_x) * 0.28)
                + 3.0 * center_swirl * math.sin((yy - 90.0) * 0.34)
                - 2.1 * upper_swirl * math.cos((yy + float(base_x)) * 0.28)
                + 1.8 * lower_drift * math.sin((yy - 109.0) * 0.48 + phase)
            )
            if _inside((x, yy), ring):
                current.append((x, yy, 0.0))
            else:
                if len(current) >= 5:
                    polylines.append(np.asarray(current, dtype=np.float32))
                current = []
        if len(current) >= 5:
            polylines.append(np.asarray(current, dtype=np.float32))

    short_marks: list[np.ndarray] = []
    for i in range(34):
        x0 = min_x + 1.0 + (i * 1.47) % max(1.0, max_x - min_x - 2.0)
        y0 = min_y + 2.0 + (i * 5.83) % max(1.0, max_y - min_y - 4.0)
        length = 2.0 + (i % 5) * 0.45
        angle = -0.8 + 1.6 * (((i * 7) % 17) / 16.0)
        pts: list[tuple[float, float, float]] = []
        for s in np.linspace(0.0, 1.0, 9):
            ss = float(s)
            x = x0 + math.cos(angle) * length * ss
            y = y0 + math.sin(angle) * length * ss + math.sin(ss * math.pi) * 0.3
            if _inside((x, y), ring):
                pts.append((x, y, 0.0))
        if len(pts) >= 3:
            short_marks.append(np.asarray(pts, dtype=np.float32))

    all_lines = [*polylines, *short_marks]
    if not all_lines:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((1,), dtype=np.int32)

    offsets = np.zeros((len(all_lines) + 1,), dtype=np.int32)
    total = 0
    for i, line in enumerate(all_lines):
        total += line.shape[0]
        offsets[i + 1] = total
    coords = np.concatenate(all_lines, axis=0).astype(np.float32, copy=False)
    return coords, offsets


def _fill(
    g,
    *,
    angle: float = 45.0,
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
    lower_field_shape = _lower_field_points()
    lower_hole_mask = G.closed_shape(points=lower_field_shape)

    body = _fill(
        G.closed_shape(points=_black_body_points()),
        angle=18.0,
        density=640.0,
        angle_sets=4,
    )
    body = E.clip(mode="outside", draw_outline=True)(body, lower_hole_mask)
    field_lines = G.flow_lines(boundary=lower_field_shape)
    red_circle = _fill(
        G.closed_shape(points=_circle_points((74.1, 31.9), 11.0, steps=240)),
        angle=25.0,
        density=520.0,
        angle_sets=3,
    )
    shadow = _fill(
        G.closed_shape(points=_shadow_points()),
        angle=0.0,
        density=160.0,
        angle_sets=1,
        remove_boundary=False,
    )

    return (
        L(name="shadow").layer(
            shadow,
            color=_rgb255(INK),
            thickness=0.0033,
        )
        + L(name="black body").layer(
            body,
            color=_rgb255(INK),
            thickness=0.0042,
        )
        + L(name="field lines").layer(
            field_lines,
            color=_rgb255(HAIRLINE),
            thickness=0.00034,
        )
        + L(name="red circle").layer(
            red_circle,
            color=_rgb255(RED),
            thickness=0.0031,
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
