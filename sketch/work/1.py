from __future__ import annotations

import math

import numpy as np

from grafix import E, G, L, primitive, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def _rgb255(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb
    return float(r) / 255.0, float(g) / 255.0, float(b) / 255.0


@primitive
def closed_path(
    *,
    points: tuple[tuple[float, ...], ...] = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
):
    coords: list[tuple[float, float, float]] = []
    for point in points:
        if len(point) == 2:
            x, y = point
            z = 0.0
        elif len(point) == 3:
            x, y, z = point
        else:
            raise ValueError(
                "closed_path の points は (x, y) または (x, y, z) の列です"
            )
        coords.append((float(x), float(y), float(z)))

    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])

    arr = np.asarray(coords, dtype=np.float32)
    offsets = np.asarray([0, arr.shape[0]], dtype=np.int32)
    return arr, offsets


@primitive
def organic_blob(
    *,
    center: tuple[float, float, float] = (74.0, 105.0, 0.0),
    radius: float = 20.0,
    scale_x: float = 1.0,
    scale_y: float = 0.62,
    angle: float = 0.0,
    phase: float = 0.0,
    wobble: float = 0.13,
    n: int | float = 168,
):
    steps = max(24, int(round(float(n))))
    theta = np.linspace(0.0, 2.0 * math.pi, steps, endpoint=False, dtype=np.float32)
    phase_rad = math.radians(float(phase))

    wave = (
        1.0
        + float(wobble) * np.sin(theta * 3.0 + phase_rad)
        + float(wobble) * 0.45 * np.cos(theta * 5.0 - phase_rad * 0.7)
    )
    x = np.cos(theta) * wave * float(radius) * float(scale_x)
    y = np.sin(theta) * wave * float(radius) * float(scale_y)

    rot = math.radians(float(angle))
    cr = math.cos(rot)
    sr = math.sin(rot)
    xr = x * cr - y * sr
    yr = x * sr + y * cr

    cx, cy, cz = center
    coords = np.stack(
        [
            xr + np.float32(cx),
            yr + np.float32(cy),
            np.full_like(xr, np.float32(cz)),
        ],
        axis=1,
    ).astype(np.float32, copy=False)
    coords = np.concatenate([coords, coords[:1]], axis=0)
    offsets = np.asarray([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


def _fill(
    g,
    *,
    angle: float = 45.0,
    density: float = 200.0,
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


def _caption_text(
    *,
    text: str,
    center: tuple[float, float, float],
    scale: float,
    align: str = "left",
):
    return _fill(
        G.text(
            text=text,
            font="Helvetica.ttc",
            font_index=0,
            text_align=align,
            letter_spacing_em=0.16,
            line_height=1.15,
            use_bounding_box=False,
            quality=0.42,
            center=center,
            scale=scale,
        ),
        angle=28.0,
        density=85.0,
        remove_boundary=False,
    )


def draw(t: float):
    paper = _fill(
        G.closed_path(
            points=((0.0, 0.0), (148.0, 0.0), (148.0, 210.0), (0.0, 210.0)),
        ),
        angle=0.0,
        density=650.0,
        remove_boundary=True,
    )

    black_mass = _fill(
        G.closed_path(
            points=(
                (27.0, 56.4),
                (45.7, 56.4),
                (95.4, 181.0),
                (27.0, 181.0),
            ),
        ),
        angle=64.0,
        density=930.0,
        angle_sets=3,
        remove_boundary=False,
    )

    gray_shapes = [
        _fill(
            G.organic_blob(
                center=(66.0, 62.8, 0.0),
                radius=27.0,
                scale_x=1.12,
                scale_y=0.68,
                angle=22.0,
                phase=12.0,
                wobble=0.11,
            ),
            angle=17.0,
            density=190.0,
            angle_sets=2,
            remove_boundary=True,
        ),
        _fill(
            G.organic_blob(
                center=(76.5, 81.2, 0.0),
                radius=23.0,
                scale_x=0.88,
                scale_y=1.16,
                angle=-36.0,
                phase=91.0,
                wobble=0.10,
            ),
            angle=-22.0,
            density=220.0,
            angle_sets=2,
            remove_boundary=True,
        ),
        _fill(
            G.organic_blob(
                center=(92.0, 107.0, 0.0),
                radius=28.0,
                scale_x=1.12,
                scale_y=0.74,
                angle=8.0,
                phase=171.0,
                wobble=0.12,
            ),
            angle=9.0,
            density=205.0,
            angle_sets=2,
            remove_boundary=True,
        ),
        _fill(
            G.organic_blob(
                center=(100.0, 134.8, 0.0),
                radius=24.0,
                scale_x=0.72,
                scale_y=1.28,
                angle=-23.0,
                phase=227.0,
                wobble=0.10,
            ),
            angle=35.0,
            density=160.0,
            angle_sets=2,
            remove_boundary=True,
        ),
        _fill(
            G.organic_blob(
                center=(79.0, 82.6, 0.0),
                radius=20.0,
                scale_x=0.72,
                scale_y=1.08,
                angle=-31.0,
                phase=54.0,
                wobble=0.08,
            ),
            angle=50.0,
            density=260.0,
            angle_sets=2,
            remove_boundary=True,
        ),
    ]

    red_sun = _fill(
        G.polygon(
            n_sides=240,
            phase=0.0,
            sweep=360.0,
            center=(101.6, 45.0, 0.0),
            scale=28.6,
        ),
        angle=24.0,
        density=820.0,
        angle_sets=3,
        remove_boundary=False,
    )

    caption_number = _caption_text(
        text="No.\n27",
        center=(27.2, 193.6, 0.0),
        scale=1.45,
        align="left",
    )
    caption_rule = G.line(
        center=(52.0, 196.8, 0.0),
        anchor="center",
        length=7.1,
        angle=0.0,
    )
    caption_title = _caption_text(
        text="balance  of  form",
        center=(66.4, 195.5, 0.0),
        scale=1.08,
        align="left",
    )
    caption_year = _caption_text(
        text="MMXXIV",
        center=(109.2, 195.3, 0.0),
        scale=1.3,
        align="left",
    )

    return (
        # L(name="warm paper").layer(
        #     paper, color=_rgb255((247, 243, 234)), thickness=0.004
        # )
        L(name="pale gray forms").layer(
            gray_shapes[:4],
            color=_rgb255((151, 149, 139)),
            thickness=0.00045,
        )
        + L(name="dark overlap").layer(
            gray_shapes[4],
            color=_rgb255((76, 76, 70)),
            thickness=0.00045,
        )
        + L(name="black trapezoid").layer(
            black_mass,
            color=_rgb255((23, 25, 23)),
            thickness=0.0010,
        )
        + L(name="caption").layer(
            [caption_number, caption_rule, caption_title, caption_year],
            color=_rgb255((37, 37, 34)),
            thickness=0.00022,
        ),
        L(name="red circle").layer(
            red_sun,
            color=_rgb255((224, 31, 28)),
            thickness=0.00065,
        ),
    )


if __name__ == "__main__":
    run(
        draw,
        background_color=_rgb255((247, 243, 234)),
        line_thickness=0.0004,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
    )
