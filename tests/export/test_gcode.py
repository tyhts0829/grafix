"""G-code export（`grafix.export.gcode.export_gcode`）のテスト。"""

from __future__ import annotations

from math import hypot

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.layer import Layer
from grafix.core.pipeline import RealizedLayer
from grafix.core.realized_geometry import RealizedGeometry
from grafix.export.gcode import GCodeParams, export_gcode


def _realized_layer(
    *,
    coords: list[list[float]],
    offsets: list[int],
) -> RealizedLayer:
    geometry = Geometry.create("line")
    layer = Layer(geometry=geometry, site_id="layer:1")
    realized = RealizedGeometry(
        coords=np.asarray(coords, dtype=np.float32),
        offsets=np.asarray(offsets, dtype=np.int32),
    )
    return RealizedLayer(layer=layer, realized=realized, color=(0.0, 0.0, 0.0), thickness=0.001)


def _parse_xy(line: str) -> tuple[float, float] | None:
    if not line.startswith("G1 "):
        return None

    x: float | None = None
    y: float | None = None
    for tok in line.split():
        if tok.startswith("X"):
            x = float(tok[1:])
        elif tok.startswith("Y"):
            y = float(tok[1:])
    if x is None or y is None:
        return None
    return x, y


def _pen_is_down_from_z(z: float, *, z_up: float, z_down: float) -> bool:
    return abs(float(z) - float(z_down)) <= abs(float(z) - float(z_up))


def _travel_distance(text: str, *, z_up: float, z_down: float) -> float:
    pen_is_down = True
    current_xy: tuple[float, float] | None = None
    travel = 0.0
    for line in text.splitlines():
        if line.startswith("G1 Z"):
            z_txt = line.split("Z", 1)[1].strip().split()[0]
            pen_is_down = _pen_is_down_from_z(float(z_txt), z_up=z_up, z_down=z_down)
            continue

        xy = _parse_xy(line)
        if xy is None:
            continue
        if current_xy is not None and not pen_is_down:
            travel += hypot(xy[0] - current_xy[0], xy[1] - current_xy[1])
        current_xy = xy
    return float(travel)


def _pen_up_xy_targets(text: str, *, z_up: float, z_down: float) -> list[tuple[float, float]]:
    pen_is_down = True
    out: list[tuple[float, float]] = []
    for line in text.splitlines():
        if line.startswith("G1 Z"):
            z_txt = line.split("Z", 1)[1].strip().split()[0]
            pen_is_down = _pen_is_down_from_z(float(z_txt), z_up=z_up, z_down=z_down)
            continue
        xy = _parse_xy(line)
        if xy is None:
            continue
        if not pen_is_down:
            out.append(xy)
    return out


def test_export_gcode_writes_file_and_is_deterministic(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
                [10.0, 10.0, 0.0],
                [11.0, 10.0, 0.0],
                [3.0, 1.0, 0.0],
                [4.0, 1.0, 0.0],
            ],
            offsets=[0, 2, 4, 6],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=True,
        allow_reverse=True,
    )

    a = tmp_path / "a.gcode"
    b = tmp_path / "b.gcode"
    export_gcode(layers, a, canvas_size=(20.0, 20.0), params=params)
    export_gcode(layers, b, canvas_size=(20.0, 20.0), params=params)

    assert a.read_bytes() == b.read_bytes()


def test_export_gcode_clips_to_paper_and_uses_pen_up_for_outside(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [12.0, 1.0, 0.0],
                [12.0, 9.0, 0.0],
                [1.0, 9.0, 0.0],
            ],
            offsets=[0, 4],
        )
    ]
    params = GCodeParams(origin=(0.0, 0.0), y_down=False, paper_margin_mm=0.0, decimals=3)

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    text = out_path.read_text(encoding="utf-8")

    assert "X12.000" not in text
    assert "Y12.000" not in text

    lines = text.splitlines()

    i_draw_to_exit = lines.index("G1 X10.000 Y1.000")
    i_travel_to_entry = lines.index("G1 X10.000 Y9.000")
    i_draw_after_entry = lines.index("G1 X1.000 Y9.000")

    assert i_draw_to_exit < i_travel_to_entry < i_draw_after_entry
    assert "G1 Z3.000" in lines[i_draw_to_exit + 1 : i_travel_to_entry]
    assert f"G1 Z{float(params.z_down):.3f}" in lines[i_travel_to_entry + 1 : i_draw_after_entry]


def test_export_gcode_allows_input_outside_bed_if_output_is_inside(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[[-100.0, 5.0, 0.0], [5.0, 5.0, 0.0]],
            offsets=[0, 2],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        bed_x_range=(0.0, 10.0),
        bed_y_range=(0.0, 10.0),
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    assert out_path.exists()


def test_export_gcode_raises_if_output_outside_bed(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[[9.5, 1.0, 0.0], [9.5, 2.0, 0.0]],
            offsets=[0, 2],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        bed_x_range=(0.0, 9.0),
        bed_y_range=(0.0, 10.0),
    )

    out_path = tmp_path / "out.gcode"
    with pytest.raises(ValueError):
        export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)


def test_export_gcode_optimize_travel_reorders_strokes_to_reduce_travel_distance(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [100.0, 0.0, 0.0],
                [100.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [1.0, 2.0, 0.0],
            ],
            offsets=[0, 2, 4, 6],
        )
    ]
    params_no_opt = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=False,
    )
    params_opt = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=True,
    )

    a = tmp_path / "baseline.gcode"
    export_gcode(layers, a, canvas_size=(200.0, 200.0), params=params_no_opt)

    b = tmp_path / "optimized.gcode"
    export_gcode(layers, b, canvas_size=(200.0, 200.0), params=params_opt)

    travel_a = _travel_distance(
        a.read_text(encoding="utf-8"), z_up=params_no_opt.z_up, z_down=params_no_opt.z_down
    )
    travel_b = _travel_distance(
        b.read_text(encoding="utf-8"), z_up=params_opt.z_up, z_down=params_opt.z_down
    )
    assert travel_b < travel_a


def test_export_gcode_optimize_travel_can_reverse_stroke_direction(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [10.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
            ],
            offsets=[0, 2, 4],
        )
    ]
    params = GCodeParams(origin=(0.0, 0.0), y_down=False, paper_margin_mm=0.0, decimals=3)

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(20.0, 20.0), params=params)
    text = out_path.read_text(encoding="utf-8")

    targets = _pen_up_xy_targets(text, z_up=params.z_up, z_down=params.z_down)
    assert len(targets) >= 2
    assert targets[1] == (1.0, 1.0)


def test_export_gcode_draw_bridge_skips_pen_up_when_move_is_short(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
                [2.1, 1.0, 0.0],
                [3.1, 1.0, 0.0],
            ],
            offsets=[0, 2, 4],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=False,
        bridge_draw_distance=0.2,
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    lines = out_path.read_text(encoding="utf-8").splitlines()

    i_end_first = lines.index("G1 X2.000 Y1.000")
    i_start_second = lines.index("G1 X2.100 Y1.000")
    assert i_end_first < i_start_second

    travel_feed = f"G1 F{int(round(float(params.travel_feed)))}"
    assert all(
        not (line.startswith("G1 Z") or line == travel_feed)
        for line in lines[i_end_first + 1 : i_start_second]
    )


def test_export_gcode_draw_bridge_disabled_uses_pen_up(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
                [2.1, 1.0, 0.0],
                [3.1, 1.0, 0.0],
            ],
            offsets=[0, 2, 4],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=False,
        bridge_draw_distance=None,
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    lines = out_path.read_text(encoding="utf-8").splitlines()

    i_end_first = lines.index("G1 X2.000 Y1.000")
    i_start_second = lines.index("G1 X2.100 Y1.000")
    assert i_end_first < i_start_second

    assert "G1 Z3.000" in lines[i_end_first + 1 : i_start_second]
