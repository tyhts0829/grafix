from __future__ import annotations

import math

import pytest

from grafix.core.parameters.codec import (
    dumps_param_store,
    encode_param_store,
    loads_param_store,
)
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.memento import (
    capture_param_store_memento,
    restore_param_store_memento,
)
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.meta_spec import meta_from_spec, meta_to_spec
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.variations import create_variation, list_variations
from grafix.core.parameters.view import rows_from_snapshot


SEMANTIC_META = ParamMeta(
    kind="float",
    ui_min=0.1,
    ui_max=100.0,
    choices=("fine", "coarse"),
    display_name="Stroke width",
    description="描画する線の太さ。",
    unit="mm",
    step=0.1,
    format="%.2f",
    scale="log",
    category="Stroke",
    advanced=True,
    recommended_range=(0.2, 5.0),
)


def _store_with_semantic_meta() -> tuple[ParamStore, ParameterKey]:
    store = ParamStore()
    key = ParameterKey(op="semantic-op", site_id="site-1", arg="width")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=1.5,
                meta=SEMANTIC_META,
                explicit=False,
            )
        ],
    )
    return store, key


def test_meta_spec_roundtrip_preserves_all_semantic_fields() -> None:
    spec = meta_to_spec(SEMANTIC_META)

    assert spec["recommended_range"] == [0.2, 5.0]
    assert spec["choices"] == ["fine", "coarse"]
    assert meta_from_spec(spec) == SEMANTIC_META


@pytest.mark.parametrize("step", [0.0, -0.1, math.nan, math.inf, -math.inf])
def test_param_meta_rejects_invalid_step_value(step: float) -> None:
    with pytest.raises(ValueError, match="step"):
        ParamMeta(kind="float", step=step)


@pytest.mark.parametrize("step", [True, "0.1", object()])
def test_param_meta_rejects_non_numeric_step(step: object) -> None:
    with pytest.raises(TypeError, match="step"):
        ParamMeta(kind="float", step=step)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "recommended_range",
    [
        (),
        (1.0,),
        (1.0, 2.0, 3.0),
        (1.0, 1.0),
        (2.0, 1.0),
        (math.nan, 1.0),
        (1.0, math.inf),
    ],
)
def test_param_meta_rejects_invalid_recommended_range(
    recommended_range: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError, match="recommended_range"):
        ParamMeta(
            kind="float",
            recommended_range=recommended_range,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("recommended_range", ["0,1", ("low", 1.0), object()])
def test_param_meta_rejects_non_numeric_recommended_range(
    recommended_range: object,
) -> None:
    with pytest.raises(TypeError, match="recommended_range"):
        ParamMeta(
            kind="float",
            recommended_range=recommended_range,  # type: ignore[arg-type]
        )


def test_param_meta_rejects_invalid_scale() -> None:
    with pytest.raises(ValueError, match="scale"):
        ParamMeta(kind="float", scale="sqrt")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="scale"):
        ParamMeta(kind="float", scale=1)  # type: ignore[arg-type]


def test_codec_and_variation_roundtrip_preserve_semantic_meta() -> None:
    store, key = _store_with_semantic_meta()
    create_variation(store, "semantic", created_at=10.0)

    encoded = encode_param_store(store)
    encoded_meta = encoded["meta"][0]
    assert encoded_meta["display_name"] == "Stroke width"
    assert encoded_meta["scale"] == "log"
    assert encoded_meta["recommended_range"] == [0.2, 5.0]

    loaded = loads_param_store(dumps_param_store(store))

    assert loaded.get_meta(key) == SEMANTIC_META
    variations = list_variations(loaded)
    assert len(variations) == 1
    assert variations[0].parameter_snapshot._meta[key] == SEMANTIC_META


def test_memento_restores_only_gui_range_and_keeps_current_semantic_meta() -> None:
    store, key = _store_with_semantic_meta()
    memento = capture_param_store_memento(store)
    current_meta = ParamMeta(
        kind="float",
        ui_min=1.0,
        ui_max=1000.0,
        display_name="Current width",
        description="現在のコードが定義した説明。",
        unit="cm",
        step=1.0,
        format="%.1f",
        scale="log",
        category="Current",
        advanced=False,
        recommended_range=(2.0, 20.0),
    )
    store._set_meta(key, current_meta)

    assert restore_param_store_memento(store, memento) is True
    assert store.get_meta(key) == ParamMeta(
        kind="float",
        ui_min=SEMANTIC_META.ui_min,
        ui_max=SEMANTIC_META.ui_max,
        display_name=current_meta.display_name,
        description=current_meta.description,
        unit=current_meta.unit,
        step=current_meta.step,
        format=current_meta.format,
        scale=current_meta.scale,
        category=current_meta.category,
        advanced=current_meta.advanced,
        recommended_range=current_meta.recommended_range,
    )


def test_rows_from_snapshot_carries_semantic_meta() -> None:
    store, _key = _store_with_semantic_meta()

    [row] = rows_from_snapshot(store_snapshot(store))

    assert row.display_name == SEMANTIC_META.display_name
    assert row.description == SEMANTIC_META.description
    assert row.unit == SEMANTIC_META.unit
    assert row.step == SEMANTIC_META.step
    assert row.format == SEMANTIC_META.format
    assert row.scale == SEMANTIC_META.scale
    assert row.category == SEMANTIC_META.category
    assert row.advanced is True
    assert row.recommended_range == SEMANTIC_META.recommended_range
