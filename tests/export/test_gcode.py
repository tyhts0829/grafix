"""G-code export（`grafix.export.gcode.export_gcode`）のテスト。"""

from __future__ import annotations

from math import hypot
from typing import Any

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.gcode_params import GCodeParams as CoreGCodeParams
from grafix.core.layer import Layer
from grafix.core.evaluation_context import (
    EMPTY_EXTERNAL_DEPENDENCIES_FINGERPRINT,
    EvaluationFingerprint,
)
from grafix.core.pipeline import RealizedLayer
from grafix.core.realize import GeometryCacheKey
from grafix.core.realized_geometry import RealizedGeometry
from grafix.export.gcode import GCodeParams, export_gcode


def _realized_layer(
    *,
    coords: list[list[float]],
    offsets: list[int],
) -> RealizedLayer:
    geometry = Geometry.create("gcode-test-geometry")
    layer = Layer(geometry=geometry, site_id="layer:1")
    realized = RealizedGeometry(
        coords=np.asarray(coords, dtype=np.float32),
        offsets=np.asarray(offsets, dtype=np.int32),
    )
    return RealizedLayer(
        layer=layer,
        realized=realized,
        cache_key=GeometryCacheKey(
            geometry_id=geometry.id,
            evaluation=EvaluationFingerprint("0" * 64),
            external_dependencies=EMPTY_EXTERNAL_DEPENDENCIES_FINGERPRINT,
        ),
        color=(0.0, 0.0, 0.0),
        thickness=0.001,
    )


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


def test_gcode_params_is_the_public_reexport_of_the_core_type() -> None:
    assert GCodeParams is CoreGCodeParams


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("travel_feed", True),
        ("travel_feed", "3000"),
        ("draw_feed", float("nan")),
        ("z_up", float("inf")),
        ("z_down", object()),
        ("paper_margin_mm", False),
        ("bridge_draw_distance", "0.5"),
        ("canvas_height_mm", float("-inf")),
    ],
)
def test_gcode_params_rejects_non_real_or_non_finite_numeric_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        GCodeParams(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("travel_feed", 0.0),
        ("draw_feed", -1.0),
        ("paper_margin_mm", -0.1),
        ("bridge_draw_distance", -0.1),
        ("canvas_height_mm", 0.0),
    ],
)
def test_gcode_params_rejects_values_outside_semantic_ranges(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        GCodeParams(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["y_down", "optimize_travel", "allow_reverse"])
@pytest.mark.parametrize("value", [0, 1, "", object()])
def test_gcode_params_requires_exact_booleans(
    field: str,
    value: Any,
) -> None:
    with pytest.raises(TypeError):
        GCodeParams(**{field: value})


@pytest.mark.parametrize("value", [True, 1.0, "3", -1])
def test_gcode_params_requires_non_negative_integer_decimals(value: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        GCodeParams(decimals=value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin", [0.0, 0.0]),
        ("origin", (0.0,)),
        ("origin", (0.0, float("nan"))),
        ("bed_x_range", [0.0, 1.0]),
        ("bed_x_range", (1.0, 1.0)),
        ("bed_y_range", (2.0, 1.0)),
    ],
)
def test_gcode_params_requires_finite_ordered_tuples(
    field: str,
    value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        GCodeParams(**{field: value})  # type: ignore[arg-type]


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


def test_export_gcode_optimize_travel_reorders_clipped_fragments_only(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [-10.0, 1.0, 0.0],
                [-10.0, 110.0, 0.0],
                [90.0, 110.0, 0.0],
                [90.0, 2.0, 0.0],
                [90.0, 1.0, 0.0],
                [110.0, 1.0, 0.0],
                [110.0, 110.0, 0.0],
                [1.0, 110.0, 0.0],
                [1.0, 3.0, 0.0],
                [1.0, 2.0, 0.0],
            ],
            offsets=[0, 12],
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
    export_gcode(layers, a, canvas_size=(100.0, 100.0), params=params_no_opt)

    b = tmp_path / "optimized.gcode"
    export_gcode(layers, b, canvas_size=(100.0, 100.0), params=params_opt)

    travel_a = _travel_distance(
        a.read_text(encoding="utf-8"), z_up=params_no_opt.z_up, z_down=params_no_opt.z_down
    )
    travel_b = _travel_distance(
        b.read_text(encoding="utf-8"), z_up=params_opt.z_up, z_down=params_opt.z_down
    )
    assert travel_b < travel_a


def test_export_gcode_optimize_travel_can_reverse_clipped_fragment(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [-10.0, 1.0, 0.0],
                [-10.0, 110.0, 0.0],
                [90.0, 110.0, 0.0],
                [90.0, 2.0, 0.0],
                [90.0, 1.0, 0.0],
                [110.0, 1.0, 0.0],
                [110.0, 110.0, 0.0],
                [1.0, 110.0, 0.0],
                [1.0, 3.0, 0.0],
                [1.0, 2.0, 0.0],
            ],
            offsets=[0, 12],
        )
    ]
    params = GCodeParams(origin=(0.0, 0.0), y_down=False, paper_margin_mm=0.0, decimals=3)

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(100.0, 100.0), params=params)
    text = out_path.read_text(encoding="utf-8")

    stroke_comments = [
        line for line in text.splitlines() if line.startswith("; stroke polyline")
    ]
    assert stroke_comments[1].endswith("seg 2 reversed")


def test_export_gcode_draw_bridge_skips_pen_up_between_fragments_of_one_polyline(
    tmp_path,
) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [10.0, 1.0, 0.0],
                [11.0, 1.0, 0.0],
                [11.0, 1.1, 0.0],
                [10.0, 1.1, 0.0],
                [2.0, 1.1, 0.0],
            ],
            offsets=[0, 6],
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

    i_end_first = lines.index("G1 X10.000 Y1.000")
    i_start_second = lines.index("G1 X10.000 Y1.100")
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


def _stroke_poly_indices(text: str) -> list[int]:
    out: list[int] = []
    for line in text.splitlines():
        if not line.startswith("; stroke polyline "):
            continue
        # "; stroke polyline {poly_idx} seg {seg_idx} ..."
        toks = line.split()
        if len(toks) < 6:
            continue
        out.append(int(toks[3]))
    return out


def test_export_gcode_keeps_input_polyline_order_when_optimization_is_enabled(
    tmp_path,
) -> None:
    """元 polyline 間の順序を形状や移動距離から推測して変更しない。"""

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
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=True,
        allow_reverse=True,
    )

    out_path = tmp_path / "input-order.gcode"
    export_gcode(layers, out_path, canvas_size=(200.0, 200.0), params=params)

    assert _stroke_poly_indices(out_path.read_text(encoding="utf-8")) == [0, 1, 2]


def test_export_gcode_draw_bridge_never_crosses_input_polyline_boundary(
    tmp_path,
) -> None:
    """bridge距離が大きくても、別の元polylineへ描線を追加しない。"""

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
        optimize_travel=True,
        bridge_draw_distance=1e6,
    )

    out_path = tmp_path / "no-cross-polyline-bridge.gcode"
    export_gcode(layers, out_path, canvas_size=(10.0, 10.0), params=params)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    first_end = lines.index("G1 X2.000 Y1.000")
    second_start = lines.index("G1 X2.100 Y1.000")

    assert "G1 Z3.000" in lines[first_end + 1 : second_start]


def test_export_gcode_keeps_mixed_open_and_closed_polylines_in_input_order(
    tmp_path,
) -> None:
    layers = [
        _realized_layer(
            coords=[
                # face A ring (poly 0, 4 verts)
                [0.0, 0.0, 0.0],
                [10.0, 0.0, 0.0],
                [10.0, 10.0, 0.0],
                [0.0, 10.0, 0.0],
                # face A fill segments (poly 1-2, 2 verts each)
                [1.0, 1.0, 0.0],
                [9.0, 1.0, 0.0],
                [1.0, 2.0, 0.0],
                [9.0, 2.0, 0.0],
                # face B ring (poly 3, 4 verts)
                [20.0, 0.0, 0.0],
                [30.0, 0.0, 0.0],
                [30.0, 10.0, 0.0],
                [20.0, 10.0, 0.0],
                # face B fill segments (poly 4-5, 2 verts each)
                [21.0, 1.0, 0.0],
                [29.0, 1.0, 0.0],
                [21.0, 2.0, 0.0],
                [29.0, 2.0, 0.0],
            ],
            offsets=[0, 4, 6, 8, 12, 14, 16],
        )
    ]
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=True,
        allow_reverse=True,
        bridge_draw_distance=None,
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(100.0, 100.0), params=params)
    text = out_path.read_text(encoding="utf-8")

    poly_idxs = _stroke_poly_indices(text)
    assert poly_idxs

    assert poly_idxs == [0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("remove_boundary", [False, True])
def test_export_gcode_keeps_multiple_face_and_hole_source_order(
    tmp_path,
    *,
    remove_boundary: bool,
) -> None:
    """fill相当の境界有無にかかわらず、exporterはfaceを推測しない。"""

    fill_lines = [
        [[2.0, 5.0, 0.0], [18.0, 5.0, 0.0]],
        [[32.0, 5.0, 0.0], [48.0, 5.0, 0.0]],
    ]
    boundaries = [
        [
            [0.0, 0.0, 0.0],
            [20.0, 0.0, 0.0],
            [20.0, 20.0, 0.0],
            [0.0, 20.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        [
            [7.0, 7.0, 0.0],
            [13.0, 7.0, 0.0],
            [13.0, 13.0, 0.0],
            [7.0, 13.0, 0.0],
            [7.0, 7.0, 0.0],
        ],
        [
            [30.0, 0.0, 0.0],
            [50.0, 0.0, 0.0],
            [50.0, 20.0, 0.0],
            [30.0, 20.0, 0.0],
            [30.0, 0.0, 0.0],
        ],
    ]
    polylines = fill_lines if remove_boundary else [
        boundaries[0],
        boundaries[1],
        fill_lines[0],
        boundaries[2],
        fill_lines[1],
    ]
    coords = [point for polyline in polylines for point in polyline]
    offsets = [0]
    for polyline in polylines:
        offsets.append(offsets[-1] + len(polyline))

    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=True,
        allow_reverse=True,
    )
    out_path = tmp_path / f"fill-remove-boundary-{remove_boundary}.gcode"
    export_gcode(
        [_realized_layer(coords=coords, offsets=offsets)],
        out_path,
        canvas_size=(60.0, 30.0),
        params=params,
    )

    assert _stroke_poly_indices(out_path.read_text(encoding="utf-8")) == list(
        range(len(polylines))
    )


def test_export_gcode_draw_bridge_does_not_cross_mixed_polyline_boundaries(
    tmp_path,
) -> None:
    layers = [
        _realized_layer(
            coords=[
                # face A ring (poly 0)
                [0.0, 0.0, 0.0],
                [10.0, 0.0, 0.0],
                [10.0, 10.0, 0.0],
                [0.0, 10.0, 0.0],
                # face A fill segment (poly 1)
                [1.0, 1.0, 0.0],
                [9.0, 1.0, 0.0],
                # face B ring (poly 2)
                [20.0, 0.0, 0.0],
                [30.0, 0.0, 0.0],
                [30.0, 10.0, 0.0],
                [20.0, 10.0, 0.0],
                # face B fill segment (poly 3)
                [21.0, 1.0, 0.0],
                [29.0, 1.0, 0.0],
            ],
            offsets=[0, 4, 6, 10, 12],
        )
    ]

    # bridge_draw_distance を極端に大きくしても、元polyline境界ではブリッジしない。
    params = GCodeParams(
        origin=(0.0, 0.0),
        y_down=False,
        paper_margin_mm=0.0,
        decimals=3,
        optimize_travel=True,
        allow_reverse=True,
        bridge_draw_distance=1e6,
    )

    out_path = tmp_path / "out.gcode"
    export_gcode(layers, out_path, canvas_size=(100.0, 100.0), params=params)
    lines = out_path.read_text(encoding="utf-8").splitlines()

    assert "; source_polyline 0 start" in lines
    assert "; source_polyline 1 start" in lines

    pen_is_down = True
    want_check = False
    checked = False

    for line in lines:
        if line == "; source_polyline 1 start":
            want_check = True
            continue

        if line.startswith("G1 Z"):
            z_txt = line.split("Z", 1)[1].strip().split()[0]
            pen_is_down = _pen_is_down_from_z(
                float(z_txt), z_up=params.z_up, z_down=params.z_down
            )
            continue

        xy = _parse_xy(line)
        if xy is None:
            continue

        if want_check and not checked:
            assert not pen_is_down
            checked = True
            break

    assert checked


def test_export_gcode_requires_explicit_params(tmp_path) -> None:
    layers = [
        _realized_layer(
            coords=[
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
            ],
            offsets=[0, 2],
        )
    ]

    out_path = tmp_path / "out.gcode"
    with pytest.raises(TypeError, match="params"):
        export_gcode(layers, out_path, canvas_size=(10.0, 10.0))  # type: ignore[call-arg]

    assert not out_path.exists()
