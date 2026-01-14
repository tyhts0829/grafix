from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from grafix.api import preset
from grafix.core.parameters import ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.view import ParameterRow
from grafix.interactive.parameter_gui import store_bridge
from grafix.interactive.parameter_gui.visibility import active_mask_for_rows


def _base_is(name: str):
    def _pred(v: Mapping[str, Any]) -> bool:
        return str(v.get("base", "")) == str(name)

    return _pred


UI_VISIBLE = {
    "cell_size": _base_is("square"),
    "ratio": _base_is("ratio_lines"),
    "boom": lambda _v: 1 / 0,
}


@preset(
    meta={
        "base": ParamMeta(kind="choice"),
        "cell_size": ParamMeta(kind="float", ui_min=0.0, ui_max=100.0),
        "ratio": ParamMeta(kind="float", ui_min=1.01, ui_max=10.0),
        "boom": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    },
    ui_visible=UI_VISIBLE,
)
def _vis_preset(
    *,
    base: str = "square",
    cell_size: float = 10.0,
    ratio: float = 1.618,
    boom: float = 0.0,
    name=None,
    key=None,
):
    return None


def _row(*, arg: str, value: object) -> ParameterRow:
    return ParameterRow(
        label=f"1:{arg}",
        op="preset._vis_preset",
        site_id="s:1",
        arg=str(arg),
        kind="float",
        ui_value=value,
        ui_min=None,
        ui_max=None,
        choices=None,
        cc_key=None,
        override=True,
        ordinal=1,
    )


def test_active_mask_for_rows_hides_inactive_params() -> None:
    rows = [
        _row(arg="base", value="square"),
        _row(arg="cell_size", value=10.0),
        _row(arg="ratio", value=1.618),
    ]
    mask = active_mask_for_rows(rows, show_inactive=False, last_effective_by_key=None)
    assert mask == [True, True, False]

    rows2 = [
        _row(arg="base", value="ratio_lines"),
        _row(arg="cell_size", value=10.0),
        _row(arg="ratio", value=1.618),
    ]
    mask2 = active_mask_for_rows(rows2, show_inactive=False, last_effective_by_key=None)
    assert mask2 == [True, False, True]


def test_active_mask_for_rows_show_inactive_returns_all_true() -> None:
    rows = [
        _row(arg="base", value="square"),
        _row(arg="cell_size", value=10.0),
        _row(arg="ratio", value=1.618),
    ]
    mask = active_mask_for_rows(rows, show_inactive=True, last_effective_by_key=None)
    assert mask == [True, True, True]


def test_active_mask_uses_last_effective_by_key() -> None:
    rows = [
        _row(arg="base", value="square"),
        _row(arg="cell_size", value=10.0),
        _row(arg="ratio", value=1.618),
    ]
    eff = {
        ParameterKey(op="preset._vis_preset", site_id="s:1", arg="base"): "ratio_lines"
    }
    mask = active_mask_for_rows(rows, show_inactive=False, last_effective_by_key=eff)
    assert mask == [True, False, True]


def test_active_mask_predicate_error_does_not_hide() -> None:
    rows = [
        _row(arg="base", value="square"),
        _row(arg="boom", value=0.0),
    ]
    mask = active_mask_for_rows(rows, show_inactive=False, last_effective_by_key=None)
    assert mask == [True, True]


def test_render_store_parameter_table_filters_rows_passed_to_renderer(monkeypatch) -> None:
    store = ParamStore()
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=ParameterKey("preset._vis_preset", "s:1", "base"),
                base="square",
                effective="square",
                meta=ParamMeta(kind="choice"),
                explicit=False,
            ),
            FrameParamRecord(
                key=ParameterKey("preset._vis_preset", "s:1", "cell_size"),
                base=10.0,
                effective=10.0,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=100.0),
                explicit=False,
            ),
            FrameParamRecord(
                key=ParameterKey("preset._vis_preset", "s:1", "ratio"),
                base=1.618,
                effective=1.618,
                meta=ParamMeta(kind="float", ui_min=1.01, ui_max=10.0),
                explicit=False,
            ),
        ],
    )

    captured_args: list[str] = []

    def _fake_render_parameter_table(rows, **_kwargs):
        captured_args[:] = [str(r.arg) for r in rows]
        return False, list(rows)

    monkeypatch.setattr(store_bridge, "render_parameter_table", _fake_render_parameter_table)

    store_bridge.render_store_parameter_table(store, show_inactive_params=False)
    assert captured_args == ["base", "cell_size"]

    store_bridge.render_store_parameter_table(store, show_inactive_params=True)
    assert captured_args == ["base", "cell_size", "ratio"]

