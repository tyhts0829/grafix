"""G-code export（`grafix.export.gcode.export_gcode`）のテスト。"""

from __future__ import annotations

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


def test_export_gcode_writes_file_and_is_deterministic(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]],
            offsets=[0, 2],
        )
    ]
    params = GCodeParams(origin=(0.0, 0.0), paper_margin_mm=0.0, decimals=3)

    a = tmp_path / "a.gcode"
    b = tmp_path / "b.gcode"
    export_gcode(layers, a, canvas_size=(10.0, 10.0), params=params)
    export_gcode(layers, b, canvas_size=(10.0, 10.0), params=params)

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
    params = GCodeParams(origin=(0.0, 0.0), paper_margin_mm=0.0, decimals=3)

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
    assert "G1 Z-2.000" in lines[i_travel_to_entry + 1 : i_draw_after_entry]


def test_export_gcode_allows_input_outside_bed_if_output_is_inside(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[[-100.0, 5.0, 0.0], [5.0, 5.0, 0.0]],
            offsets=[0, 2],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
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
        paper_margin_mm=0.0,
        decimals=3,
        bed_x_range=(0.0, 9.0),
        bed_y_range=(0.0, 10.0),
    )

    out_path = tmp_path / "out.gcode"
    with pytest.raises(ValueError):
        export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)


def test_export_gcode_connects_nearby_polylines(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
                [2.05, 1.0, 0.0],
                [3.0, 1.0, 0.0],
            ],
            offsets=[0, 2, 4],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        paper_margin_mm=0.0,
        decimals=3,
        connect_distance=0.1,
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    i_end_first = lines.index("G1 X2.000 Y1.000")
    i_start_second = lines.index("G1 X2.050 Y1.000")
    assert i_end_first < i_start_second
    assert all(
        not (line.startswith("G1 Z") or line == "G1 F1500")
        for line in lines[i_end_first + 1 : i_start_second]
    )


def test_export_gcode_x_reverse_flips_by_canvas_size_width(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]],
            offsets=[0, 2],
        )
    ]
    params = GCodeParams(origin=(0.0, 0.0), paper_margin_mm=0.0, decimals=3, x_reverse=True)

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    text = out_path.read_text(encoding="utf-8")

    assert "G1 X9.000 Y2.000" in text
    assert "G1 X7.000 Y4.000" in text


def test_export_gcode_x_reverse_uses_canvas_width_mm_if_given(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]],
            offsets=[0, 2],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        paper_margin_mm=0.0,
        decimals=3,
        x_reverse=True,
        canvas_width_mm=8.0,
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    text = out_path.read_text(encoding="utf-8")

    assert "G1 X7.000 Y2.000" in text
    assert "G1 X5.000 Y4.000" in text
