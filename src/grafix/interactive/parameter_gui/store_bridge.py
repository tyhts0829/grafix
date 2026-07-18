# どこで: `src/grafix/interactive/parameter_gui/store_bridge.py`。
# 何を: ParamStore snapshot と UI 行モデル（ParameterRow）の差分を反映する。
# なぜ: 「描画」と「永続状態の更新」を分離し、依存方向を単純化するため。

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence, Set as AbstractSet
from dataclasses import dataclass, replace
from types import MappingProxyType
from weakref import WeakKeyDictionary

from grafix.core.builtins import (
    ensure_builtin_effect_registered,
    ensure_builtin_primitive_registered,
)
from grafix.core.effect_registry import effect_registry
from grafix.core.primitive_registry import primitive_registry
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.favorites import set_parameters_favorite
from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.meta_ops import set_meta
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.style import STYLE_OP
from grafix.core.parameters.snapshot_ops import ParamSnapshot, store_snapshot
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.parameters.view import ParameterRow, rows_from_snapshot
from grafix.core.preset_registry import preset_registry

from .labeling import primitive_header_display_names_from_snapshot
from .labeling import (
    effect_chain_header_display_names_from_snapshot,
    effect_step_ordinals_by_site,
)
from .grouping import group_info_for_row
from .midi_learn import MidiLearnState
from .parameter_filter import (
    ParameterFilterRecord,
    ParameterFilterState,
    filter_parameter_records,
)
from .table import (
    parameter_group_collapse_keys,
    render_parameter_table,
    source_badge_for_row,
)
from .table_model import (
    ParameterTableCacheKey,
    ParameterTableModel,
    ParameterTableModelCache,
    RegistryRevision,
)
from .visibility import active_mask_for_rows

_logger = logging.getLogger(__name__)
_TABLE_MODEL_CACHE = ParameterTableModelCache()
_ENSURED_OPS_BY_STORE_REVISION: WeakKeyDictionary[ParamStore, int] = WeakKeyDictionary()


@dataclass(frozen=True, slots=True)
class ParameterTableView:
    """1 GUI frame の filter 合成結果。"""

    model: ParameterTableModel
    visible_mask: tuple[bool, ...]
    filtered_count: int
    total_count: int

    @property
    def hidden_count(self) -> int:
        """visibility/filter により現在表示されない行数を返す。"""

        return max(0, int(self.total_count) - int(self.filtered_count))


def _order_rows_for_display(
    rows: list[ParameterRow],
    *,
    step_info_by_site: Mapping[tuple[str, str], tuple[str, int]],
    display_order_by_group: Mapping[tuple[str, str], int],
) -> list[ParameterRow]:
    """GUI 表示順に並び替えた rows を返す。"""

    # この関数は「表示の読みやすさ」と「フレーム間の安定性」を優先して並べ替える。
    #
    # - style は “いつでも先頭” かつ固定順（ユーザーが探すことが多い）
    # - primitive/effect/other は “コードに現れた順” を基本にする
    #   （= display_order_by_group で安定化された順序）
    # - effect は “チェーン単位” にまとめる（折りたたみの単位を壊さない）

    style_global_rows: list[ParameterRow] = []
    style_layer_rows: list[ParameterRow] = []
    preset_rows: list[ParameterRow] = []
    primitive_rows: list[ParameterRow] = []
    effect_rows: list[ParameterRow] = []
    other_rows: list[ParameterRow] = []
    for row in rows:
        if row.op == STYLE_OP:
            style_global_rows.append(row)
        elif row.op == LAYER_STYLE_OP:
            style_layer_rows.append(row)
        elif row.op in preset_registry:
            preset_rows.append(row)
        elif row.op in primitive_registry:
            primitive_rows.append(row)
        elif row.op in effect_registry:
            effect_rows.append(row)
        else:
            other_rows.append(row)

    # Style（global）は固定の表示順に寄せる（background → thickness → line_color）。
    style_order = {
        "background_color": 0,
        "global_thickness": 1,
        "global_line_color": 2,
    }
    style_global_rows.sort(key=lambda r: (style_order.get(r.arg, 999), r.arg))

    # Style（layer）は layer ordinal 順に、line_thickness → line_color の順で出す。
    layer_style_order = {"line_thickness": 0, "line_color": 1}
    style_layer_rows.sort(
        key=lambda r: (int(r.ordinal), layer_style_order.get(r.arg, 999), r.arg)
    )

    def _display_order(row: ParameterRow) -> int:
        # display_order_by_group は (op, site_id) 単位の「観測順（コード順）」の近似。
        # 見つからない場合は末尾へ回す（未知 group / 互換性のための保険）。
        return int(display_order_by_group.get((row.op, row.site_id), 10**9))

    # --- Non-style: Preset / Primitive / Effect chain / other を “ブロック” として並べる ---
    #
    # - Preset は (op, ordinal) 単位
    # - Primitive は (op, ordinal) 単位
    # - Effect は chain_id 単位（折りたたみ維持）
    # - other は (op, site_id) 単位（最小限）

    primitive_arg_index_by_op: dict[str, dict[str, int]] = {}
    preset_arg_index_by_op: dict[str, dict[str, int]] = {}
    effect_arg_index_by_op: dict[str, dict[str, int]] = {}

    def _primitive_arg_index(op: str, arg: str) -> int:
        if op not in primitive_arg_index_by_op:
            order = primitive_registry[op].param_order
            primitive_arg_index_by_op[op] = {a: i for i, a in enumerate(order)}
        index_by_arg = primitive_arg_index_by_op[op]
        return int(index_by_arg.get(arg, 10**9))

    def _effect_arg_index(op: str, arg: str) -> int:
        if op not in effect_arg_index_by_op:
            order = effect_registry[op].param_order
            effect_arg_index_by_op[op] = {a: i for i, a in enumerate(order)}
        index_by_arg = effect_arg_index_by_op[op]
        return int(index_by_arg.get(arg, 10**9))

    def _preset_arg_index(op: str, arg: str) -> int:
        if op not in preset_arg_index_by_op:
            order = preset_registry.get_param_order(op)
            preset_arg_index_by_op[op] = {a: i for i, a in enumerate(order)}
        index_by_arg = preset_arg_index_by_op[op]
        return int(index_by_arg.get(arg, 10**9))

    primitive_blocks: dict[tuple[str, int], list[ParameterRow]] = {}
    for row in primitive_rows:
        # primitive は 1 つの呼び出し（site_id）に対して複数 arg 行がぶら下がる。
        # GUI では `circle#3` のように op と ordinal でまとまりを認識するため、
        # ブロックキーも (op, ordinal) に寄せる。
        primitive_blocks.setdefault((row.op, int(row.ordinal)), []).append(row)

    preset_blocks: dict[tuple[str, int], list[ParameterRow]] = {}
    for row in preset_rows:
        preset_blocks.setdefault((row.op, int(row.ordinal)), []).append(row)

    effect_blocks: dict[str, list[ParameterRow]] = {}
    effect_fallback_rows: list[ParameterRow] = []
    for row in effect_rows:
        # effect は `step_info_by_site` で「どのチェーンの何番目か」を引ける。
        # 引けないものは（不整合/旧データなど）other へフォールバックし、表示は崩さない。
        info = step_info_by_site.get((row.op, row.site_id))
        if info is None:
            effect_fallback_rows.append(row)
            continue
        chain_id, _step_index = info
        effect_blocks.setdefault(str(chain_id), []).append(row)

    other_blocks: dict[tuple[str, str], list[ParameterRow]] = {}
    for row in other_rows + effect_fallback_rows:
        # other は「最小限のまとまり」として (op, site_id) 単位にする。
        # （primitive/effect と違い、意味的なグルーピング規則が無い想定）
        other_blocks.setdefault((row.op, row.site_id), []).append(row)

    # effect チェーンは “チェーン内の各ステップの display_order” を持つが、
    # チェーン全体としては「最初に現れたステップの位置」に寄せて並べたい。
    # そのため chain_id ごとに min(display_order) を求め、チェーンの並び順に使う。
    chain_min_display_order: dict[str, int] = {}
    for (op, site_id), (chain_id, _step_index) in step_info_by_site.items():
        order = int(display_order_by_group.get((str(op), str(site_id)), 10**9))
        prev = chain_min_display_order.get(str(chain_id))
        if prev is None or order < prev:
            chain_min_display_order[str(chain_id)] = int(order)

    blocks: list[tuple[tuple[int, int, str], list[ParameterRow]]] = []

    for preset_key, block_rows in preset_blocks.items():
        op, ordinal = preset_key
        order = min(_display_order(r) for r in block_rows)
        blocks.append(
            (
                (int(order), 0, f"{op}#{int(ordinal)}"),
                sorted(
                    block_rows,
                    key=lambda r: (_preset_arg_index(op, str(r.arg)), str(r.arg)),
                ),
            )
        )

    for primitive_key, block_rows in primitive_blocks.items():
        op, ordinal = primitive_key
        # primitive ブロックの位置は、そのブロック内行の display_order の最小値に寄せる。
        # （同一 primitive 呼び出し内で arg 行の順序は固定だが、念のため min を取る）
        order = min(_display_order(r) for r in block_rows)
        blocks.append(
            (
                (int(order), 1, f"{op}#{int(ordinal)}"),
                sorted(
                    block_rows,
                    key=lambda r: (_primitive_arg_index(op, str(r.arg)), str(r.arg)),
                ),
            )
        )

    def _step_sort_key(r: ParameterRow) -> tuple[int, int, str]:
        # チェーン内では step_index（= effect 呼び出し順）を優先し、
        # 同一 step 内は arg 名で安定に並べる。
        info = step_info_by_site.get((r.op, r.site_id))
        if info is None:
            # effect_blocks の対象は step_info がある前提だが、
            # ここは保険として「末尾へ回す」だけに留める（過度に防御しない）。
            return (10**9, 10**9, str(r.arg))
        _cid, step_index = info
        return (
            int(step_index),
            _effect_arg_index(str(r.op), str(r.arg)),
            str(r.arg),
        )

    for chain_id, block_rows in effect_blocks.items():
        # effect チェーンの “ブロック位置” はチェーン内最小の display_order に寄せる。
        order = int(chain_min_display_order.get(chain_id, 10**9))
        blocks.append(
            (
                (int(order), 2, str(chain_id)),
                sorted(block_rows, key=_step_sort_key),
            )
        )

    for other_key, block_rows in other_blocks.items():
        op, site_id = other_key
        # other ブロックも primitive 同様、ブロック内の min(display_order) に寄せる。
        order = min(_display_order(r) for r in block_rows)
        if op in effect_registry:
            ordered = sorted(
                block_rows,
                key=lambda r: (_effect_arg_index(op, str(r.arg)), str(r.arg)),
            )
        else:
            ordered = sorted(block_rows, key=lambda r: str(r.arg))
        blocks.append(
            (
                (int(order), 3, f"{op}:{site_id}"),
                ordered,
            )
        )

    out_non_style: list[ParameterRow] = []
    for _sort_key, block_rows in sorted(blocks, key=lambda item: item[0]):
        # blocks の sort_key は (display_order, kind_rank, stable_id)。
        # - display_order : 基本の並び（コード順）
        # - kind_rank     : 同順序なら primitive -> effect -> other の順で出す
        # - stable_id     : 同順序のときも決定的にする（set/dict の揺れを潰す）
        out_non_style.extend(block_rows)

    # 最終的な表示順: style（global/layer 固定） → non-style（コード順 = display_order）
    return style_global_rows + style_layer_rows + out_non_style


def _registry_revision() -> RegistryRevision:
    """テーブル構造に影響する registry revision をまとめて返す。"""

    return (
        int(primitive_registry.revision),
        int(effect_registry.revision),
        int(preset_registry.revision),
    )


def _build_parameter_table_model(
    store: ParamStore,
    snapshot: ParamSnapshot,
    cache_key: ParameterTableCacheKey,
) -> ParameterTableModel:
    """snapshot から revision 内で不変なテーブル構造を 1 回だけ構築する。"""

    raw_label_by_site: dict[tuple[str, str], str] = {}
    for key, (_meta, _state, _ordinal, label) in snapshot.items():
        op = str(key.op)
        if (
            op not in primitive_registry
            and op not in effect_registry
            and op not in preset_registry
            and op != LAYER_STYLE_OP
        ):
            continue
        if label is None:
            continue
        label_s = str(label).strip()
        if not label_s:
            continue
        raw_label_by_site.setdefault((op, str(key.site_id)), label_s)

    runtime = store._runtime_ref()
    primitive_header_by_group = primitive_header_display_names_from_snapshot(
        snapshot,
        is_primitive_op=lambda op: op in primitive_registry or op in preset_registry,
        display_order_by_group=runtime.display_order_by_group,
    )

    step_info_by_site = store.effect_steps()
    effect_chain_header_by_id = effect_chain_header_display_names_from_snapshot(
        snapshot,
        step_info_by_site=step_info_by_site,
        display_order_by_group=runtime.display_order_by_group,
        is_effect_op=lambda op: op in effect_registry,
    )
    effect_step_ordinal_by_site = effect_step_ordinals_by_site(step_info_by_site)

    primitive_known_args_by_op: dict[str, set[str]] = {}
    preset_known_args_by_op: dict[str, set[str]] = {}
    effect_known_args_by_op: dict[str, set[str]] = {}
    unknown_args_new: set[tuple[str, str]] = set()
    filtered_rows: list[ParameterRow] = []

    for row in rows_from_snapshot(snapshot):
        op = str(row.op)
        arg = str(row.arg)
        key = ParameterKey(op=op, site_id=str(row.site_id), arg=arg)
        row = replace(row, favorite=key in store._favorite_keys_ref())

        if op in primitive_registry:
            known_args = primitive_known_args_by_op.get(op)
            if known_args is None:
                known_args = set(primitive_registry[op].meta)
                primitive_known_args_by_op[op] = known_args
            if arg not in known_args:
                pair = (op, arg)
                if pair not in runtime.warned_unknown_args:
                    runtime.warned_unknown_args.add(pair)
                    unknown_args_new.add(pair)
                continue
        elif op in preset_registry:
            known_args = preset_known_args_by_op.get(op)
            if known_args is None:
                known_args = set(preset_registry.get_meta(op))
                preset_known_args_by_op[op] = known_args
            if arg not in known_args:
                pair = (op, arg)
                if pair not in runtime.warned_unknown_args:
                    runtime.warned_unknown_args.add(pair)
                    unknown_args_new.add(pair)
                continue
        elif op in effect_registry:
            known_args = effect_known_args_by_op.get(op)
            if known_args is None:
                known_args = set(effect_registry[op].meta)
                effect_known_args_by_op[op] = known_args
            if arg not in known_args:
                pair = (op, arg)
                if pair not in runtime.warned_unknown_args:
                    runtime.warned_unknown_args.add(pair)
                    unknown_args_new.add(pair)
                continue

        filtered_rows.append(row)

    if unknown_args_new:
        pairs = ", ".join(f"{op}.{arg}" for op, arg in sorted(unknown_args_new))
        _logger.warning("未登録引数を無視します（次回保存で削除）: %s", pairs)

    rows = _order_rows_for_display(
        filtered_rows,
        step_info_by_site=step_info_by_site,
        display_order_by_group=runtime.display_order_by_group,
    )

    layer_style_name_by_site_id: dict[str, str] = {}
    for key, (_meta, _state, _ordinal, label) in snapshot.items():
        if key.op != LAYER_STYLE_OP:
            continue
        site_id = str(key.site_id)
        layer_style_name_by_site_id.setdefault(site_id, str(label) if label else "layer")

    return ParameterTableModel(
        cache_key=cache_key,
        value_revision=int(store.value_revision),
        snapshot=snapshot,
        rows=tuple(rows),
        row_index_by_key=MappingProxyType(
            {
                ParameterKey(
                    op=str(row.op),
                    site_id=str(row.site_id),
                    arg=str(row.arg),
                ): index
                for index, row in enumerate(rows)
            }
        ),
        raw_label_by_site=MappingProxyType(raw_label_by_site),
        primitive_header_by_group=MappingProxyType(primitive_header_by_group),
        layer_style_name_by_site_id=MappingProxyType(layer_style_name_by_site_id),
        effect_chain_header_by_id=MappingProxyType(effect_chain_header_by_id),
        step_info_by_site=MappingProxyType(step_info_by_site),
        effect_step_ordinal_by_site=MappingProxyType(effect_step_ordinal_by_site),
    )


def _refresh_parameter_table_model_values(
    store: ParamStore,
    model: ParameterTableModel,
    changed_keys: frozenset[ParameterKey],
) -> ParameterTableModel:
    """既存モデルのうち、変更された行の value state だけを差し替える。"""

    rows: list[ParameterRow] | None = None
    for key in changed_keys:
        index = model.row_index_by_key.get(key)
        state = store._get_state_ref(key)
        if index is None or state is None:
            continue
        current = model.rows[index] if rows is None else rows[index]
        updated = replace(
            current,
            ui_value=state.ui_value,
            override=bool(state.override),
            cc_key=state.cc_key,
            reset_to_code=False,
        )
        if updated == current:
            continue
        if rows is None:
            rows = list(model.rows)
        rows[index] = updated
    return replace(
        model,
        value_revision=int(store.value_revision),
        rows=model.rows if rows is None else tuple(rows),
    )


def _parameter_table_model_for_store(store: ParamStore) -> ParameterTableModel:
    revision = int(store.table_revision)
    if _ENSURED_OPS_BY_STORE_REVISION.get(store) != revision:
        # GUI に実際に現れた op だけを遅延登録する。全 built-in の eager import は
        # optional dependency を不要に読み、起動時間も増やすため行わない。
        ops = {str(key.op) for key in store_snapshot(store)}
        for op in ops:
            if op not in primitive_registry and op not in effect_registry:
                ensure_builtin_primitive_registered(op)
                ensure_builtin_effect_registered(op)
        _ENSURED_OPS_BY_STORE_REVISION[store] = revision
    return _TABLE_MODEL_CACHE.get_or_build(
        store,
        registry_revision=_registry_revision(),
        builder=_build_parameter_table_model,
        refresher=_refresh_parameter_table_model_values,
    )


def clear_parameter_table_model_cache() -> None:
    """テスト/明示再初期化用にテーブルモデル cache を破棄する。"""

    _TABLE_MODEL_CACHE.clear()
    _ENSURED_OPS_BY_STORE_REVISION.clear()


def parameter_table_model_build_count() -> int:
    """テーブルモデルの累積構築回数を返す。"""

    return _TABLE_MODEL_CACHE.build_count


def _visible_mask_for_model(
    store: ParamStore,
    rows: Sequence[ParameterRow],
    *,
    show_inactive: bool,
    activity_mask: Sequence[bool] | None = None,
) -> list[bool]:
    """静的 rows に active/loaded などフレーム動的な可視性を合成する。"""

    runtime = store._runtime_ref()
    if bool(show_inactive):
        active_mask = [True] * len(rows)
    else:
        if activity_mask is None:
            activity_mask = active_mask_for_rows(
                rows,
                show_inactive=False,
                last_effective_by_key=runtime.last_effective_by_key,
            )
        if len(activity_mask) != len(rows):
            raise ValueError("activity_mask は rows と同じ長さである必要があります")
        active_mask = [bool(active) for active in activity_mask]
    if not runtime.loaded_groups:
        return active_mask

    loaded = {
        (str(op), str(site_id))
        for op, site_id in runtime.loaded_groups
        if str(op) != STYLE_OP
    }
    observed = {
        (str(op), str(site_id))
        for op, site_id in runtime.observed_groups
        if str(op) != STYLE_OP
    }
    hidden_groups = loaded - observed
    if not hidden_groups:
        return active_mask
    return [
        visible and (str(row.op), str(row.site_id)) not in hidden_groups
        for row, visible in zip(rows, active_mask, strict=True)
    ]


def _search_label_for_row(row: ParameterRow, model: ParameterTableModel) -> str:
    """表示 label/header/raw label を検索用の 1 文字列へまとめる。"""

    info = group_info_for_row(
        row,
        primitive_header_by_group=model.primitive_header_by_group,
        layer_style_name_by_site_id=model.layer_style_name_by_site_id,
        effect_chain_header_by_id=model.effect_chain_header_by_id,
        step_info_by_site=model.step_info_by_site,
        effect_step_ordinal_by_site=model.effect_step_ordinal_by_site,
    )
    raw_label = model.raw_label_by_site.get((str(row.op), str(row.site_id)), "")
    return " ".join(
        part
        for part in (str(info.visible_label), str(info.header or ""), str(raw_label))
        if part
    )


def parameter_table_view_for_store(
    store: ParamStore,
    *,
    show_inactive_params: bool,
    filter_state: ParameterFilterState | None = None,
    error_keys: AbstractSet[ParameterKey] = frozenset(),
    favorite_keys: AbstractSet[ParameterKey] | None = None,
) -> ParameterTableView:
    """既存 visibility と検索/filter を合成した immutable view を返す。"""

    state = ParameterFilterState() if filter_state is None else filter_state
    favorites = (
        store._favorite_keys_ref()
        if favorite_keys is None
        else favorite_keys
    )
    model = _parameter_table_model_for_store(store)
    rows = model.rows
    runtime = store._runtime_ref()
    # activity が表示条件にも filter にも不要なら、group ごとの値辞書と
    # ui_visible rule の全行評価を省く。検索/favorite/error 等は active flag を
    # 参照しないため、show_inactive=True ではこの fast path を共有できる。
    activity_mask: Sequence[bool] | None = None
    if not bool(show_inactive_params) or state.activity != "all":
        activity_mask = active_mask_for_rows(
            rows,
            show_inactive=False,
            last_effective_by_key=runtime.last_effective_by_key,
        )
    base_visible_mask = _visible_mask_for_model(
        store,
        rows,
        show_inactive=bool(show_inactive_params),
        activity_mask=activity_mask,
    )

    # 通常時（検索/filter 無し）は静的 search label/source record を組み立てない。
    # 大規模 scene の既定フレームコストを、従来の visibility 判定と同程度に保つ。
    if state == ParameterFilterState():
        visible_mask = tuple(bool(visible) for visible in base_visible_mask)
        return ParameterTableView(
            model=model,
            visible_mask=visible_mask,
            filtered_count=sum(visible_mask),
            total_count=len(rows),
        )

    records: list[ParameterFilterRecord] = []
    for index, row in enumerate(rows):
        key = ParameterKey(op=str(row.op), site_id=str(row.site_id), arg=str(row.arg))
        records.append(
            ParameterFilterRecord(
                row=row,
                label=_search_label_for_row(row, model),
                source=source_badge_for_row(
                    row,
                    runtime.last_source_by_key.get(key),
                ),
                active=(
                    True
                    if activity_mask is None
                    else bool(activity_mask[index])
                ),
                has_error=key in error_keys,
                favorite=key in favorites,
            )
        )

    filtered = filter_parameter_records(records, state)
    visible_mask = tuple(
        bool(base_visible and matches_filter)
        for base_visible, matches_filter in zip(
            base_visible_mask,
            filtered.mask,
            strict=True,
        )
    )
    return ParameterTableView(
        model=model,
        visible_mask=visible_mask,
        filtered_count=sum(visible_mask),
        total_count=len(rows),
    )


def _apply_updated_rows_to_store(
    store: ParamStore,
    snapshot: Mapping[ParameterKey, tuple[ParamMeta, object, int, str | None]],
    rows_before: Sequence[ParameterRow],
    rows_after: Sequence[ParameterRow],
) -> None:
    """rows の変更を ParamStore に反映する。

    - ui_min/ui_max の変更は meta に反映する
    - ui_value/override/cc_key の変更は `update_state_from_ui` 経由で反映する
    """

    def _cc_set(
        cc_key: int | tuple[int | None, int | None, int | None] | None,
    ) -> set[int]:
        # cc_key は scalar(int) または vec3/rgb 用の (a,b,c) を取り得る。
        # 「割当解除（CC が減った）」判定を set 差分でシンプルにするため、集合へ正規化する。
        #
        # - None            : 未割当（空集合）
        # - int             : {cc}
        # - (a,b,c)         : {a,b,c}（None 成分は除外）
        #
        # ここで例外処理を厚くしないのは、
        # cc_key の型は update_state_from_ui / UI 側で既に正規化されている前提のため。
        if cc_key is None:
            return set()
        if isinstance(cc_key, int):
            return {int(cc_key)}
        return {int(v) for v in cc_key if v is not None}

    reset_font_index_for: set[tuple[str, str]] = set()

    for before, after in zip(rows_before, rows_after, strict=True):
        # renderer は未変更 row の identity を維持する。changed frame でも
        # ほぼ全行を読み直さず、実際に更新された row だけ store へ反映する。
        if before is after or before == after:
            continue
        key = ParameterKey(
            op=str(before.op),
            site_id=str(before.site_id),
            arg=str(before.arg),
        )
        entry = snapshot.get(key)
        if entry is None:
            continue
        meta = entry[0]
        effective_meta = meta

        if after.ui_min != before.ui_min or after.ui_max != before.ui_max:
            effective_meta = replace(
                meta,
                ui_min=after.ui_min,
                ui_max=after.ui_max,
            )
            set_meta(store, key, effective_meta)

        if after.favorite != before.favorite:
            set_parameters_favorite(
                store,
                (key,),
                favorite=bool(after.favorite),
            )

        if (
            after.ui_value != before.ui_value
            or after.override != before.override
            or after.cc_key != before.cc_key
        ):
            cc_removed = False
            if after.cc_key != before.cc_key:
                before_cc = _cc_set(before.cc_key)
                after_cc = _cc_set(after.cc_key)
                removed = before_cc - after_cc
                added = after_cc - before_cc
                cc_removed = bool(removed) and not bool(added)

            baked_effective = (
                store._runtime_ref().last_effective_by_key.get(key)
                if cc_removed and not after.reset_to_code
                else None
            )
            if baked_effective is not None:
                update_state_from_ui(
                    store,
                    key,
                    baked_effective,
                    meta=effective_meta,
                    override=True,
                    cc_key=after.cc_key,
                )
            else:
                update_state_from_ui(
                    store,
                    key,
                    after.ui_value,
                    meta=effective_meta,
                    override=after.override,
                    cc_key=after.cc_key,
                )

        if (
            key.op == "text"
            and key.arg == "font"
            and after.ui_value != before.ui_value
            and str(after.ui_value).strip().lower().endswith(".ttc")
        ):
            reset_font_index_for.add((str(key.op), str(key.site_id)))

    for op, site_id in sorted(reset_font_index_for):
        font_index_key = ParameterKey(
            op=str(op),
            site_id=str(site_id),
            arg="font_index",
        )
        entry = snapshot.get(font_index_key)
        if entry is None:
            continue
        font_index_meta = entry[0]
        update_state_from_ui(
            store,
            font_index_key,
            0,
            meta=font_index_meta,
            override=True,
        )


def set_all_parameter_groups_collapsed(
    store: ParamStore,
    table_view: ParameterTableView,
    *,
    collapsed: bool,
) -> bool:
    """現在の parameter group を一括で折りたたみ、または展開する。"""

    if not isinstance(collapsed, bool):
        raise TypeError("collapsed must be a bool")

    model = table_view.model
    collapse_keys = parameter_group_collapse_keys(
        list(model.rows),
        primitive_header_by_group=model.primitive_header_by_group,
        layer_style_name_by_site_id=model.layer_style_name_by_site_id,
        effect_chain_header_by_id=model.effect_chain_header_by_id,
        step_info_by_site=model.step_info_by_site,
        effect_step_ordinal_by_site=model.effect_step_ordinal_by_site,
    )
    headers = store._collapsed_headers_ref()
    before = frozenset(headers)
    store._observe_history_headers_before()
    if collapsed:
        headers.update(collapse_keys)
    else:
        headers.difference_update(collapse_keys)
    if before == headers:
        return False
    store._touch(structure=False)
    return True


def clear_all_midi_assignments(store: ParamStore) -> bool:
    """すべてのパラメータの MIDI CC 割当（cc_key）を解除する。"""

    snapshot = store_snapshot(store)
    rows_before = rows_from_snapshot(snapshot)
    if not any(row.cc_key is not None for row in rows_before):
        return False

    rows_after = [
        row if row.cc_key is None else replace(row, cc_key=None) for row in rows_before
    ]
    _apply_updated_rows_to_store(store, snapshot, rows_before, rows_after)
    return True


def render_store_parameter_table(
    store: ParamStore,
    *,
    metric_scale: float | None = None,
    show_inactive_params: bool = True,
    filter_state: ParameterFilterState | None = None,
    error_keys: AbstractSet[ParameterKey] = frozenset(),
    favorite_keys: AbstractSet[ParameterKey] | None = None,
    table_view: ParameterTableView | None = None,
    midi_learn_state: MidiLearnState | None = None,
    midi_last_cc_change: tuple[int, int] | None = None,
    on_help_row: Callable[[ParameterRow, bool], None] | None = None,
) -> bool:
    """ParamStore を 4 列テーブルとして描画し、変更を store に反映する。"""

    # 行・ヘッダ・順序は (store revision, registry revision) 内で不変。
    # effective/MIDI/active/loaded はモデル外に置き、描画直前にだけ合成する。
    model = _parameter_table_model_for_store(store)
    if table_view is None or table_view.model is not model:
        table_view = parameter_table_view_for_store(
            store,
            show_inactive_params=bool(show_inactive_params),
            filter_state=filter_state,
            error_keys=error_keys,
            favorite_keys=favorite_keys,
        )
        model = table_view.model
    rows_before = model.rows
    visible_mask = table_view.visible_mask
    view_rows = [
        row for row, visible in zip(rows_before, visible_mask, strict=True) if visible
    ]

    runtime = store._runtime_ref()
    collapsed_before = frozenset(store._collapsed_headers_ref())
    changed, view_rows_after = render_parameter_table(
        view_rows,
        metric_scale=metric_scale,
        primitive_header_by_group=model.primitive_header_by_group,
        layer_style_name_by_site_id=model.layer_style_name_by_site_id,
        effect_chain_header_by_id=model.effect_chain_header_by_id,
        step_info_by_site=model.step_info_by_site,
        effect_step_ordinal_by_site=model.effect_step_ordinal_by_site,
        last_effective_by_key=runtime.last_effective_by_key,
        last_source_by_key=runtime.last_source_by_key,
        raw_label_by_site=model.raw_label_by_site,
        midi_learn_state=midi_learn_state,
        midi_last_cc_change=midi_last_cc_change,
        collapsed_headers=store._collapsed_headers_ref(),
        on_help_row=on_help_row,
    )
    collapsed_changed = collapsed_before != store._collapsed_headers_ref()
    if collapsed_changed:
        store._observe_history_headers_before(collapsed_before)
        store._touch(structure=False)

    if changed:
        view_iter = iter(view_rows_after)
        rows_after = [
            next(view_iter) if visible else row
            for row, visible in zip(rows_before, visible_mask, strict=True)
        ]
        _apply_updated_rows_to_store(
            store,
            model.snapshot,
            rows_before,
            rows_after,
        )
    return bool(changed or collapsed_changed)
