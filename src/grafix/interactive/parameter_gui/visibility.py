# どこで: `src/grafix/interactive/parameter_gui/visibility.py`。
# 何を: Parameter GUI で「今の状態で効いている引数だけを表示する」ための可視性判定を提供する。
# なぜ: preset/primitive/effect の引数が多い場合でも、操作すべき行だけに絞って混乱を減らすため。

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from grafix.core.effect_registry import effect_registry
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.view import ParameterRow
from grafix.core.preset_registry import preset_registry
from grafix.core.primitive_registry import primitive_registry

_logger = logging.getLogger(__name__)


def active_mask_for_rows(
    rows: list[ParameterRow],
    *,
    show_inactive: bool,
    last_effective_by_key: Mapping[ParameterKey, object] | None,
) -> list[bool]:
    """rows と同じ長さの可視マスクを返す。

    Notes
    -----
    - mask は「描画/表示」のみを制御し、値や override を変更しない。
    - 例外時は UI を壊さないため “表示する” に倒す。
    """

    if bool(show_inactive):
        return [True] * len(rows)

    effective = last_effective_by_key

    # group=(op, site_id) ごとに「現在値辞書」を作る。
    # ルールは “同一呼び出し 1 回” の値にだけ依存する想定。
    values_by_group: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        group = (str(row.op), str(row.site_id))
        v = values_by_group.get(group)
        if v is None:
            v = {}
            values_by_group[group] = v
        key = ParameterKey(op=str(row.op), site_id=str(row.site_id), arg=str(row.arg))
        v[str(row.arg)] = (
            row.ui_value if effective is None else effective.get(key, row.ui_value)
        )

    ui_visible_by_op: dict[str, dict[str, object]] = {}

    # activate=False の group は、activate 行以外を一律で非表示にする。
    # 目的: ui_visible を書かなくても「無効化中は引数の海にならない」状態にする。
    disabled_groups: set[tuple[str, str]] = set()
    for group, values in values_by_group.items():
        if "activate" not in values:
            continue
        if not bool(values.get("activate", True)):
            disabled_groups.add(group)

    def _rules_for_op(op: str) -> dict[str, object]:
        cached = ui_visible_by_op.get(op)
        if cached is not None:
            return cached
        if op in preset_registry:
            rules = preset_registry.get_ui_visible(op)
        elif op in primitive_registry:
            rules = primitive_registry.get_ui_visible(op)
        elif op in effect_registry:
            rules = effect_registry.get_ui_visible(op)
        else:
            rules = {}
        ui_visible_by_op[op] = dict(rules)
        return ui_visible_by_op[op]

    mask: list[bool] = []
    for row in rows:
        op = str(row.op)
        arg = str(row.arg)

        group = (str(row.op), str(row.site_id))
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
            mask.append(bool(pred(values)))  # type: ignore[misc]
        except Exception as exc:
            _logger.warning(
                "ui_visible の評価に失敗: op=%s arg=%s err=%s", op, arg, exc
            )
            mask.append(True)

    return mask
