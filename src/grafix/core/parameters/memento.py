# どこで: `src/grafix/core/parameters/memento.py`。
# 何を: ParamStore の GUI-owned 状態をスナップショットし、既存構造へ merge 復元する。
# なぜ: Undo/Redo や A/B 比較が、後から発見した parameter や code-owned 構造を壊さないため。

from __future__ import annotations

from copy import deepcopy

from .effects import EffectChainIndex
from .key import ParameterKey
from .labels import ParamLabels
from .meta import ParamMeta
from .ordinals import GroupOrdinals
from .state import ParamState
from .store import ParamStore


def _known_collapse_headers(
    states: dict[ParameterKey, ParamState],
    effects: EffectChainIndex,
) -> set[str]:
    """Store 構造から、現在存在し得る GUI header ID を返す。"""

    groups = {(str(key.op), str(key.site_id)) for key in states}
    known: set[str] = set()
    style_ops = {"__style__", "__layer_style__"}
    if any(op in style_ops for op, _site_id in groups):
        known.add("style:global")
    for op, site_id in groups:
        if op in style_ops:
            continue
        # core は preset registry に依存しない。同じ group の候補を両方
        # 記録し、実際に使われる方だけが collapsed set と一致する。
        known.add(f"primitive:{op}:{site_id}")
        known.add(f"preset:{op}:{site_id}")

    for group, (chain_id, _step_index) in effects.step_info_by_site().items():
        if (str(group[0]), str(group[1])) in groups:
            known.add(f"effect_chain:{chain_id}")
    return known


class ParamStoreMemento:
    """ParamStore の GUI-owned 調整状態を保持する in-memory memento。

    保存対象は、各 parameter の ``override`` / ``ui_value`` /
    MIDI 割当、GUI が編集する ``ui_min`` / ``ui_max``、および
    折りたたみ状態である。ラベル、ordinal、effect chain、explicit
    フラグなど code-owned の構造は復元対象にしない。

    復元時は、現在も同じ ``ParameterKey`` と ``meta.kind`` で存在する
    parameter だけへ merge する。そのため、履歴作成後に draw が
    発見した parameter や、code reload 後の新しい metadata は消えない。

    Notes
    -----
    コンストラクタの keyword は従来 API と互換に保つ。ただし
    ``explicit_by_key`` / ``labels`` / ``ordinals`` は code-owned なので、
    互換入力として受け取るだけで復元対象には含めない。
    """

    __slots__ = ("_states", "_meta", "_collapsed_by_header")

    def __init__(
        self,
        *,
        states: dict[ParameterKey, ParamState],
        meta: dict[ParameterKey, ParamMeta],
        explicit_by_key: dict[ParameterKey, bool],
        labels: ParamLabels,
        ordinals: GroupOrdinals,
        effects: EffectChainIndex,
        collapsed_headers: set[str],
    ) -> None:
        # memento と復元先で可変オブジェクトを共有しない。
        self._states = deepcopy(states)
        self._meta = deepcopy(meta)
        known_headers = _known_collapse_headers(states, effects)
        self._collapsed_by_header = {
            header: header in collapsed_headers for header in known_headers
        }

        # 従来コンストラクタ API は保つが、code-owned 値は保存しない。
        _ = explicit_by_key, labels, ordinals


def capture_param_store_memento(store: ParamStore) -> ParamStoreMemento:
    """store の GUI-owned 状態を、後続変更から独立して記録する。"""

    return ParamStoreMemento(
        states=store._states,
        meta=store._meta,
        explicit_by_key=store._explicit_by_key,
        labels=store._labels_ref(),
        ordinals=store._ordinals_ref(),
        effects=store._effects_ref(),
        collapsed_headers=store._collapsed_headers_ref(),
    )


def _applicable_entries(
    store: ParamStore,
    memento: ParamStoreMemento,
) -> list[tuple[ParameterKey, ParamState, ParamMeta, ParamState, ParamMeta]]:
    """現在の code-owned 構造に安全に適用できる entry を返す。"""

    applicable: list[tuple[ParameterKey, ParamState, ParamMeta, ParamState, ParamMeta]] = []
    for key, saved_state in memento._states.items():
        saved_meta = memento._meta.get(key)
        current_state = store._states.get(key)
        current_meta = store._meta.get(key)
        if saved_meta is None or current_state is None or current_meta is None:
            continue
        # kind 変更は code reload による構造変更として尊重する。
        if str(saved_meta.kind) != str(current_meta.kind):
            continue
        applicable.append((key, saved_state, saved_meta, current_state, current_meta))
    return applicable


def param_store_memento_matches(
    store: ParamStore,
    memento: ParamStoreMemento,
) -> bool:
    """memento を merge しても GUI-owned 状態が変わらなければ True。"""

    if not isinstance(memento, ParamStoreMemento):
        raise TypeError("memento must be a ParamStoreMemento")

    for _key, saved_state, saved_meta, current_state, current_meta in _applicable_entries(
        store, memento
    ):
        if (
            current_state.override != saved_state.override
            or current_state.ui_value != saved_state.ui_value
            or current_state.cc_key != saved_state.cc_key
            or current_meta.ui_min != saved_meta.ui_min
            or current_meta.ui_max != saved_meta.ui_max
        ):
            return False

    current_known_headers = _known_collapse_headers(store._states, store._effects_ref())
    collapsed = store._collapsed_headers_ref()
    for header, saved_collapsed in memento._collapsed_by_header.items():
        if header not in current_known_headers:
            continue
        if (header in collapsed) != bool(saved_collapsed):
            return False
    return True


def restore_param_store_memento(
    store: ParamStore,
    memento: ParamStoreMemento,
) -> bool:
    """memento の GUI-owned 状態を現在の store 構造へ merge する。

    store 自体、runtime、code-owned 構造の identity/内容は維持する。
    後から発見した key は削除せず、memento と現在の両方にある
    同一 kind の key だけを復元する。実変更が無い場合は revision を
    進めず False を返す。
    """

    if not isinstance(memento, ParamStoreMemento):
        raise TypeError("memento must be a ParamStoreMemento")
    if param_store_memento_matches(store, memento):
        return False

    changed = False
    for _key, saved_state, saved_meta, current_state, current_meta in _applicable_entries(
        store, memento
    ):
        if (
            current_state.override != saved_state.override
            or current_state.ui_value != saved_state.ui_value
            or current_state.cc_key != saved_state.cc_key
        ):
            current_state.override = bool(saved_state.override)
            current_state.ui_value = deepcopy(saved_state.ui_value)
            current_state.cc_key = deepcopy(saved_state.cc_key)
            changed = True

        if current_meta.ui_min != saved_meta.ui_min or current_meta.ui_max != saved_meta.ui_max:
            # kind/choices は現在の code-owned metadata を保持し、GUI が
            # 編集する range だけを復元する。
            store._meta[_key] = ParamMeta(
                kind=str(current_meta.kind),
                ui_min=deepcopy(saved_meta.ui_min),
                ui_max=deepcopy(saved_meta.ui_max),
                choices=current_meta.choices,
            )
            changed = True

    current_known_headers = _known_collapse_headers(store._states, store._effects_ref())
    collapsed = store._collapsed_headers_ref()
    for header, saved_collapsed in memento._collapsed_by_header.items():
        if header not in current_known_headers:
            continue
        if saved_collapsed and header not in collapsed:
            collapsed.add(header)
            changed = True
        elif not saved_collapsed and header in collapsed:
            collapsed.discard(header)
            changed = True

    if changed:
        # revision は過去の値へ戻さず単調に進め、読み取り cache を無効化する。
        store._touch()
    return changed


__all__ = [
    "ParamStoreMemento",
    "capture_param_store_memento",
    "param_store_memento_matches",
    "restore_param_store_memento",
]
