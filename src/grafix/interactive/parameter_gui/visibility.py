# どこで: `src/grafix/interactive/parameter_gui/visibility.py`。
# 何を: Parameter GUI で「今の状態で効いている引数だけを表示する」ための可視性判定を提供する。
# なぜ: preset/primitive/effect の引数が多い場合でも、操作すべき行だけに絞って混乱を減らすため。

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from grafix.core.operation_schema import UiVisiblePred
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.view import ParameterRow

from .catalog import ParameterGuiCatalog, current_parameter_gui_catalog

_logger = logging.getLogger(__name__)


def active_mask_for_rows(
    rows: Sequence[ParameterRow],
    *,
    catalog: ParameterGuiCatalog | None = None,
    show_inactive: bool,
    last_effective_by_key: Mapping[ParameterKey, object] | None,
) -> list[bool]:
    """rows と同じ長さの可視マスクを返す。

    Notes
    -----
    - mask は「描画/表示」のみを制御し、値や override を変更しない。
    - 例外時は UI を壊さないため “表示する” に倒す。
    """

    selected_catalog = current_parameter_gui_catalog() if catalog is None else catalog
    if type(selected_catalog) is not ParameterGuiCatalog:
        raise TypeError("catalog は exact ParameterGuiCatalog である必要があります")

    if bool(show_inactive):
        return [True] * len(rows)

    effective = last_effective_by_key

    # group=(op, site_id) ごとに「現在値辞書」を作る。
    # ルールは “同一呼び出し 1 回” の値にだけ依存する想定。
    values_by_group: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        group = (row.op, row.site_id)
        v = values_by_group.get(group)
        if v is None:
            v = {}
            values_by_group[group] = v
        key = ParameterKey(op=row.op, site_id=row.site_id, arg=row.arg)
        v[row.arg] = row.ui_value if effective is None else effective.get(key, row.ui_value)

    ui_visible_by_op: dict[str, dict[str, UiVisiblePred]] = {}

    # activate=False の group は、activate 行以外を一律で非表示にする。
    # 目的: ui_visible を書かなくても「無効化中は引数の海にならない」状態にする。
    disabled_groups: set[tuple[str, str]] = set()
    for group, values in values_by_group.items():
        if "activate" not in values:
            continue
        if not bool(values.get("activate", True)):
            disabled_groups.add(group)

    def _rules_for_op(op: str) -> dict[str, UiVisiblePred]:
        cached = ui_visible_by_op.get(op)
        if cached is not None:
            return cached
        entry = selected_catalog.resolve(op)
        rules: Mapping[str, UiVisiblePred] = {} if entry is None else entry.schema.ui_visible
        ui_visible_by_op[op] = dict(rules)
        return ui_visible_by_op[op]

    mask: list[bool] = []
    for row in rows:
        op = row.op
        arg = row.arg

        group = (row.op, row.site_id)
        if group in disabled_groups:
            mask.append(arg == "activate")
            continue

        rules = _rules_for_op(op)
        pred = rules.get(arg)
        if pred is None:
            mask.append(True)
            continue

        values = values_by_group.get(group, {})
        try:
            mask.append(bool(pred(values)))
        except Exception as exc:
            _logger.warning("ui_visible の評価に失敗: op=%s arg=%s err=%s", op, arg, exc)
            mask.append(True)

    return mask
