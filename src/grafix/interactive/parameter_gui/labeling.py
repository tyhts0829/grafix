# どこで: `src/grafix/interactive/parameter_gui/labeling.py`。
# 何を: GUI 表示用のヘッダ名/行ラベルを生成する純粋関数を提供する。
# なぜ: imgui 描画から分離し、衝突解消や整形をユニットテスト可能にするため。

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Mapping
from typing import TypeVar

from grafix.core.operation_selector import selector_kind
from grafix.core.parameters.key import ParameterKey

PrimitiveDisplayGroupKey = tuple[str, int]
K = TypeVar("K", bound=Hashable)


def operation_display_name(op: str) -> str:
    """内部 selector 名を公開 API 名へ置き換えた operation 表示名を返す。"""

    return "select" if selector_kind(op) is not None else op


def humanize_identifier(value: str) -> str:
    """code identifier を短い人間向け表示へ変換する。

    内部 key と ImGui ID は変更せず、表示文字列だけを整える。
    """

    text = " ".join(value.replace("_", " ").replace("#", " #").split())
    if not text:
        return ""
    return text[0].upper() + text[1:]


def format_contextual_row_label(op: str, ordinal: int, arg: str) -> str:
    """Effect 等、親内で operation 名も必要な行の表示ラベルを返す。"""

    return f"{humanize_identifier(op)} {int(ordinal)} · {humanize_identifier(arg)}"


def dedup_display_names_in_order(items: list[tuple[K, str]]) -> dict[K, str]:
    """同名がある場合だけ `name#N` を付与して表示名を返す。

    - 衝突解消は表示専用で、永続化される label そのものは変更しない。
    - 連番は `items` の順序に従う。
    """

    counts = Counter(name for _key, name in items)
    seen: dict[str, int] = defaultdict(int)

    out: dict[K, str] = {}
    for key, name in items:
        if counts[name] <= 1:
            out[key] = name
            continue
        seen[name] += 1
        out[key] = f"{name}#{seen[name]}"
    return out


def primitive_header_display_names_from_snapshot(
    snapshot: Mapping[ParameterKey, tuple[object, object, int, str | None]],
    *,
    is_primitive_op: Callable[[str], bool],
    display_order_by_group: Mapping[tuple[str, str], int] | None = None,
) -> dict[PrimitiveDisplayGroupKey, str]:
    """snapshot から Primitive 用のヘッダ表示名（衝突解消済み）を作る。"""

    base_name_by_group: dict[PrimitiveDisplayGroupKey, str] = {}
    site_id_by_group: dict[PrimitiveDisplayGroupKey, str] = {}
    for key, (_meta, _state, ordinal, label) in snapshot.items():
        if not is_primitive_op(key.op):
            continue
        group_key = (key.op, int(ordinal))
        if group_key in base_name_by_group:
            continue
        if label:
            base_name = label
        else:
            base_name = operation_display_name(key.op)
        base_name_by_group[group_key] = base_name
        site_id_by_group[group_key] = key.site_id

    def _sort_key(group_key: PrimitiveDisplayGroupKey) -> tuple[int, str, int]:
        op, ordinal = group_key
        site_id = site_id_by_group.get(group_key, "")
        order = 10**9
        if display_order_by_group is not None:
            order = int(display_order_by_group.get((op, site_id), 10**9))
        return (int(order), op, int(ordinal))

    ordered = [(k, base_name_by_group[k]) for k in sorted(base_name_by_group, key=_sort_key)]
    return dedup_display_names_in_order(ordered)


EffectStepKey = tuple[str, str]  # (op, site_id)


def effect_step_ordinals_by_site(
    step_info_by_site: Mapping[EffectStepKey, tuple[str, int]],
) -> dict[EffectStepKey, int]:
    """同一チェーン内の “同一 op の出現回数” でステップ連番を計算する。"""

    steps_by_chain: dict[str, list[tuple[int, str, str]]] = {}
    for (op, site_id), (chain_id, step_index) in step_info_by_site.items():
        steps_by_chain.setdefault(chain_id, []).append((int(step_index), op, site_id))

    out: dict[EffectStepKey, int] = {}
    for chain_id, steps in steps_by_chain.items():
        counts: dict[str, int] = defaultdict(int)
        for _step_index, op, site_id in sorted(steps):
            counts[op] += 1
            out[(op, site_id)] = int(counts[op])
    return out


def effect_chain_header_display_names_from_snapshot(
    snapshot: Mapping[ParameterKey, tuple[object, object, int, str | None]],
    *,
    step_info_by_site: Mapping[EffectStepKey, tuple[str, int]],
    display_order_by_group: Mapping[tuple[str, str], int],
    is_effect_op: Callable[[str], bool],
) -> dict[str, str]:
    """snapshot から Effect チェーン用のヘッダ表示名（衝突解消済み）を作る。"""

    # chain_id ごとの「明示ラベル（あれば）」を集める。
    # - E(name=...) が付いている場合: label をヘッダ名として採用
    # - そうでない場合: 無名チェーンとして扱う
    label_by_chain: dict[str, str | None] = {}
    for key, (_meta, _state, _ordinal, label) in snapshot.items():
        op = key.op
        if not is_effect_op(op):
            continue
        step = step_info_by_site.get((op, key.site_id))
        if step is None:
            continue
        chain_id, _step_index = step
        if chain_id in label_by_chain:
            continue
        label_by_chain[chain_id] = label

    # 表示順は “コード順（観測順）” に寄せる。
    chain_min_display_order: dict[str, int] = {}
    for (op, site_id), (chain_id, _step_index) in step_info_by_site.items():
        order = int(display_order_by_group.get((op, site_id), 10**9))
        prev = chain_min_display_order.get(chain_id)
        if prev is None or order < prev:
            chain_min_display_order[chain_id] = int(order)

    chain_ids_sorted = sorted(
        label_by_chain.keys(),
        key=lambda chain_id: (
            int(chain_min_display_order.get(chain_id, 10**9)),
            chain_id,
        ),
    )

    # effect#N は “無名チェーンだけ” を対象に 1..K へ正規化する。
    # これにより、名前付きチェーンが存在しても無名は必ず effect#1 から始まる。
    unnamed_count = 0
    base_name_by_chain: dict[str, str] = {}
    for chain_id in chain_ids_sorted:
        label = label_by_chain.get(chain_id)
        if label:
            base_name_by_chain[chain_id] = label
            continue
        unnamed_count += 1
        base_name_by_chain[chain_id] = f"effect#{unnamed_count}"

    ordered = [(cid, base_name_by_chain[cid]) for cid in chain_ids_sorted]
    return dedup_display_names_in_order(ordered)
