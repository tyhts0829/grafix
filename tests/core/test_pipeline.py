"""core.pipeline の `realize_scene` をテスト。"""

from __future__ import annotations

import numpy as np

from grafix.core.geometry import Geometry
from grafix.core.layer import Layer, LayerStyleDefaults
from grafix.core.parameters import ParamStore, parameter_context
from grafix.core.parameters.context import parameter_context_from_snapshot
from grafix.core.parameters.layer_style import (
    LAYER_STYLE_LINE_COLOR,
    LAYER_STYLE_LINE_THICKNESS,
    LAYER_STYLE_OP,
    layer_style_key,
)
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.pipeline import realize_scene
from grafix.core.primitives import polygon as _polygon_module  # noqa: F401


def test_realize_scene_normalizes_and_realizes_layers() -> None:
    g1 = Geometry.create("polygon", params={"n_sides": 3})
    g2 = Geometry.create("polygon", params={"n_sides": 6})

    def draw(t: float):
        return [Layer(g1, site_id="layer:1", color=None, thickness=None), g2]

    defaults = LayerStyleDefaults(color=(0.1, 0.2, 0.3), thickness=0.05)
    realized_layers = realize_scene(draw, t=0.0, defaults=defaults)

    assert len(realized_layers) == 2
    colors = [item.color for item in realized_layers]
    thicknesses = [item.thickness for item in realized_layers]
    assert colors == [(0.1, 0.2, 0.3), (0.1, 0.2, 0.3)]
    assert thicknesses == [0.05, 0.05]
    assert all(isinstance(item.realized.coords, np.ndarray) for item in realized_layers)


def test_realize_scene_observes_and_applies_layer_style_overrides() -> None:
    g = Geometry.create("polygon", params={"n_sides": 3})

    def draw(t: float):
        return [Layer(g, site_id="layer:1", color=None, thickness=None, name="bg")]

    defaults = LayerStyleDefaults(color=(0.1, 0.2, 0.3), thickness=0.05)
    store = ParamStore()

    with parameter_context(store=store, cc_snapshot=None):
        _ = realize_scene(draw, t=0.0, defaults=defaults)

    assert store.get_label(LAYER_STYLE_OP, "layer:1") == "bg"

    key_thickness = layer_style_key("layer:1", LAYER_STYLE_LINE_THICKNESS)
    key_color = layer_style_key("layer:1", LAYER_STYLE_LINE_COLOR)

    meta_thickness = store.get_meta(key_thickness)
    meta_color = store.get_meta(key_color)
    assert meta_thickness is not None
    assert meta_color is not None

    ok, err = update_state_from_ui(
        store, key_thickness, 0.123, meta=meta_thickness, override=True
    )
    assert ok and err is None
    ok, err = update_state_from_ui(
        store, key_color, (255, 0, 0), meta=meta_color, override=True
    )
    assert ok and err is None

    with parameter_context(store=store, cc_snapshot=None):
        realized_layers = realize_scene(draw, t=0.0, defaults=defaults)

    assert realized_layers[0].thickness == 0.123
    assert realized_layers[0].color == (1.0, 0.0, 0.0)


def test_realize_scene_records_layer_style_without_param_store() -> None:
    g = Geometry.create("polygon", params={"n_sides": 3})

    def draw(t: float):
        return [Layer(g, site_id="layer:1", color=None, thickness=None, name="bg")]

    defaults = LayerStyleDefaults(color=(0.1, 0.2, 0.3), thickness=0.05)

    with parameter_context_from_snapshot(snapshot={}, cc_snapshot=None) as frame_params:
        realized_layers = realize_scene(draw, t=0.0, defaults=defaults)

    assert realized_layers[0].thickness == 0.05
    assert realized_layers[0].color == (0.1, 0.2, 0.3)

    assert (key_thickness := layer_style_key("layer:1", LAYER_STYLE_LINE_THICKNESS)) in {
        rec.key for rec in frame_params.records
    }
    assert (key_color := layer_style_key("layer:1", LAYER_STYLE_LINE_COLOR)) in {
        rec.key for rec in frame_params.records
    }
    assert any(
        (rec.op, rec.site_id, rec.label) == (LAYER_STYLE_OP, "layer:1", "bg")
        for rec in frame_params.labels
    )
