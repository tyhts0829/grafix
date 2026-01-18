"""
どこで: `src/grafix/core/parameters/layer_style.py`。
何を: Layer ごとの line_thickness/line_color を ParamStore で表現するキーと観測レコード生成ヘルパを定義する。
なぜ: Layer style も primitive/effect と同じく「観測→フレーム終端でマージ」の流れに統合するため。
"""

from __future__ import annotations

from .frame_params import FrameParamRecord
from .context import current_frame_params, current_param_store
from .key import ParameterKey
from .labels_ops import set_label
from .meta import ParamMeta
from .style import coerce_rgb255, rgb01_to_rgb255, rgb255_to_rgb01

LAYER_STYLE_OP = "__layer_style__"

LAYER_STYLE_LINE_THICKNESS = "line_thickness"
LAYER_STYLE_LINE_COLOR = "line_color"

LAYER_STYLE_THICKNESS_META = ParamMeta(kind="float", ui_min=1e-4, ui_max=1e-2)
LAYER_STYLE_COLOR_META = ParamMeta(kind="rgb", ui_min=0, ui_max=255)


def layer_style_key(layer_site_id: str, arg: str) -> ParameterKey:
    """Layer style 用の ParameterKey を返す。"""

    return ParameterKey(op=LAYER_STYLE_OP, site_id=str(layer_site_id), arg=str(arg))


def layer_style_records(
    *,
    layer_site_id: str,
    base_line_thickness: float,
    base_line_color_rgb01: tuple[float, float, float],
    explicit_line_thickness: bool,
    explicit_line_color: bool,
) -> list[FrameParamRecord]:
    """Layer style の観測レコード（line_thickness/line_color）を返す。"""

    thickness_key = layer_style_key(layer_site_id, LAYER_STYLE_LINE_THICKNESS)
    color_key = layer_style_key(layer_site_id, LAYER_STYLE_LINE_COLOR)

    return [
        FrameParamRecord(
            key=thickness_key,
            base=float(base_line_thickness),
            meta=LAYER_STYLE_THICKNESS_META,
            explicit=bool(explicit_line_thickness),
        ),
        FrameParamRecord(
            key=color_key,
            base=rgb01_to_rgb255(base_line_color_rgb01),
            meta=LAYER_STYLE_COLOR_META,
            explicit=bool(explicit_line_color),
        ),
    ]


def observe_and_apply_layer_style(
    *,
    layer_site_id: str,
    layer_name: str | None,
    base_line_thickness: float,
    base_line_color_rgb01: tuple[float, float, float],
    explicit_line_thickness: bool,
    explicit_line_color: bool,
) -> tuple[float, tuple[float, float, float]]:
    """Layer style を観測し、必要なら GUI override を適用して描画値を返す。

    Parameters
    ----------
    layer_site_id : str
        対象 Layer の site_id。
    layer_name : str | None
        Layer 名。None の場合は label は設定しない。
    base_line_thickness : float
        resolve_layer_style() 後の線幅（base）。
    base_line_color_rgb01 : tuple[float, float, float]
        resolve_layer_style() 後の線色（0..1, base）。
    explicit_line_thickness : bool
        Layer が thickness を明示指定したかどうか。
    explicit_line_color : bool
        Layer が color を明示指定したかどうか。

    Returns
    -------
    tuple[float, tuple[float, float, float]]
        `(thickness, color_rgb01)`。ParamStore 上で `override=True` の場合のみ GUI 値を採用する。

    Notes
    -----
    - `parameter_recording_muted()` 中でも Layer style は観測/適用する（現状維持）。
    - ParamStore が無いコンテキストでも、FrameParamsBuffer があれば records/labels を蓄積する。
      （例: `parameter_context_from_snapshot()` で実行したとき）
    """

    thickness = float(base_line_thickness)
    color = base_line_color_rgb01

    frame_params = current_frame_params()
    if frame_params is not None:
        frame_params.records.extend(
            layer_style_records(
                layer_site_id=layer_site_id,
                base_line_thickness=thickness,
                base_line_color_rgb01=color,
                explicit_line_thickness=explicit_line_thickness,
                explicit_line_color=explicit_line_color,
            )
        )

    if layer_name is not None:
        store = current_param_store()
        if store is not None:
            set_label(store, op=LAYER_STYLE_OP, site_id=layer_site_id, label=layer_name)
        elif frame_params is not None:
            frame_params.set_label(op=LAYER_STYLE_OP, site_id=layer_site_id, label=layer_name)

    store = current_param_store()
    if store is None:
        return thickness, color

    thickness_state = store.get_state(layer_style_key(layer_site_id, LAYER_STYLE_LINE_THICKNESS))
    if thickness_state is not None and thickness_state.override:
        thickness = float(thickness_state.ui_value)

    color_state = store.get_state(layer_style_key(layer_site_id, LAYER_STYLE_LINE_COLOR))
    if color_state is not None and color_state.override:
        rgb255 = coerce_rgb255(color_state.ui_value)
        color = rgb255_to_rgb01(rgb255)

    return thickness, color
