# どこで: `src/grafix/interactive/parameter_gui/rules.py`。
# 何を: Parameter GUI の「列ごとの描画ルール（min-max / cc_key / override）」を 1 箇所に集約する。
# なぜ: `table.py` に例外条件が分散すると、変更時に漏れやすく管理が難しくなるため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.parameters.style import STYLE_OP
from grafix.core.parameters.view import ParameterRow

MinMaxMode = Literal["none", "float_range", "int_range"]
CcKeyMode = Literal["none", "int", "int3"]


@dataclass(frozen=True, slots=True)
class RowUiRules:
    """ParameterRow をどう描画するかのルール。"""

    minmax: MinMaxMode
    cc_key: CcKeyMode
    show_override: bool


_DISABLE_MINMAX_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        (STYLE_OP, "global_thickness"),
        (LAYER_STYLE_OP, "line_thickness"),
    }
)

# Style / Layer Style は geometry parameter の ``resolve_params()`` を通らず、
# それぞれ専用 resolver で CODE/UI の値だけを解決する。現状それらの resolver は
# ``cc_snapshot`` を参照しないため、MIDI control を表示すると「割り当てられるのに
# 描画へ効かない」状態になる。RGB も tuple CC の実効値解決をまだ持たない。
#
# 非機能 control を見せないことを優先し、対応 resolver と source reporting が揃うまで
# ここで明示的に無効化する。非対応 mapping 自体は parameter validator が拒否する。
_DISABLE_CC_OPS: frozenset[str] = frozenset({STYLE_OP, LAYER_STYLE_OP})


def ui_rules_for_row(row: ParameterRow) -> RowUiRules:
    """行の UI ルールを返す。

    優先順位:
    1) kind によるデフォルト
    2) (op, arg) による例外上書き（意味/セマンティクス）
    """

    # --- 1) kind によるデフォルト ---
    if row.kind in {"float", "vec3"}:
        minmax: MinMaxMode = "float_range"
    elif row.kind == "int":
        minmax = "int_range"
    else:
        minmax = "none"

    if row.kind == "bool":
        cc_key: CcKeyMode = "none"
        show_override = True
    elif row.kind in {"str", "font"}:
        cc_key = "none"
        show_override = True
    elif row.kind == "choice":
        cc_key = "int"
        show_override = True
    elif row.kind == "vec3":
        cc_key = "int3"
        show_override = True
    elif row.kind == "rgb":
        # resolve_params() の tuple CC は vec3 専用。対応するまで RGB には出さない。
        cc_key = "none"
        show_override = True
    elif row.kind in {"float", "int"}:
        cc_key = "int"
        show_override = True
    else:
        raise ValueError(f"unknown parameter kind: {row.kind!r}")

    # --- 2) (op, arg) の例外上書き ---
    if (row.op, row.arg) in _DISABLE_MINMAX_KEYS:
        minmax = "none"
    if row.op in _DISABLE_CC_OPS:
        cc_key = "none"

    return RowUiRules(minmax=minmax, cc_key=cc_key, show_override=show_override)
