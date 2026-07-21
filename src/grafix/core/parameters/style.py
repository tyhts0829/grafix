"""
どこで: `src/grafix/core/parameters/style.py`。
何を: 描画用 “Style” の ParamStore キーと変換ユーティリティを定義する。
なぜ: GUI と描画側で同じ識別子を共有し、Style 編集を素直に実装するため。
"""

from __future__ import annotations

from typing import cast

from .key import ParameterKey
from .validation import validate_parameter_value

STYLE_OP = "__style__"
STYLE_SITE_ID = "__global__"

STYLE_BACKGROUND_COLOR = "background_color"
STYLE_GLOBAL_THICKNESS = "global_thickness"
STYLE_GLOBAL_LINE_COLOR = "global_line_color"


def line_width_for_short_side(
    thickness: float,
    size: tuple[float, float],
) -> float:
    """正規化線幅を ``size`` の短辺と同じ単位へ変換する。"""

    width, height = float(size[0]), float(size[1])
    if width <= 0.0 or height <= 0.0:
        raise ValueError("size は正の値である必要がある")
    return float(thickness) * min(width, height) * 0.5


def style_key(arg: str) -> ParameterKey:
    """Style 用の ParameterKey を返す。"""

    return ParameterKey(op=STYLE_OP, site_id=STYLE_SITE_ID, arg=arg)


def validate_rgb255(value: object) -> tuple[int, int, int]:
    """canonical RGB255 タプル `(r, g, b)` を strict に検証する。

    Parameters
    ----------
    value : object
        exact int だけからなる `(r, g, b)` タプル。

    Returns
    -------
    tuple[int, int, int]
        検証済みの RGB。

    Raises
    ------
    TypeError, ValueError
        型、長さ、値域が canonical RGB255 契約に合わない場合。
    """

    return cast(
        tuple[int, int, int],
        validate_parameter_value(value, kind="rgb", choices=None),
    )


def rgb01_to_rgb255(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    """0..1 float の RGB を 0..255 int の RGB に変換して返す。"""

    r, g, b = rgb
    out: list[int] = []
    for v in (r, g, b):
        fv = float(v)
        fv = 0.0 if fv < 0.0 else 1.0 if fv > 1.0 else fv
        out.append(int(round(fv * 255.0)))
    return int(out[0]), int(out[1]), int(out[2])


def rgb255_to_rgb01(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """0..255 int の RGB を 0..1 float の RGB に変換して返す。"""

    r, g, b = rgb
    return float(r) / 255.0, float(g) / 255.0, float(b) / 255.0
