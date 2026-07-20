# どこで: `src/grafix/core/parameters/memento.py`。
# 何を: ParamStore の GUI-owned 状態をスナップショットし、既存構造へ merge 復元する。
# なぜ: Undo/Redo や A/B 比較が、後から発見した parameter や code-owned 構造を壊さないため。

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

from .effects import EffectChainIndex, EffectTopologySignature
from .key import ParameterKey
from .labels import ParamLabels
from .meta import ParamMeta
from .ordinals import GroupOrdinals
from .state import ParamState
from .store import ParamStore


@dataclass(frozen=True, slots=True)
class _ParamGuiEntry:
    """1 key の GUI-owned 状態。patch history の最小コピー単位。"""

    state: ParamState | None
    meta: ParamMeta | None


def _capture_gui_entry(store: ParamStore, key: ParameterKey) -> _ParamGuiEntry:
    state = store._states.get(key)
    meta = store._meta.get(key)
    return _ParamGuiEntry(
        state=None if state is None else deepcopy(state),
        meta=None if meta is None else deepcopy(meta),
    )


def _gui_entries_match(left: _ParamGuiEntry, right: _ParamGuiEntry) -> bool:
    left_state = left.state
    right_state = right.state
    left_meta = left.meta
    right_meta = right.meta
    if left_state is None or right_state is None or left_meta is None or right_meta is None:
        return left_state == right_state and left_meta == right_meta
    return (
        str(left_meta.kind) == str(right_meta.kind)
        and left_state.override == right_state.override
        and left_state.ui_value == right_state.ui_value
        and left_state.cc_key == right_state.cc_key
        and left_meta.ui_min == right_meta.ui_min
        and left_meta.ui_max == right_meta.ui_max
    )


class ParamStorePatch:
    """少数 key の GUI-owned 差分を保持する Undo/Redo entry。"""

    __slots__ = (
        "_before_by_key",
        "_after_by_key",
        "_collapsed_before",
        "_collapsed_after",
    )

    def __init__(
        self,
        *,
        before_by_key: dict[ParameterKey, _ParamGuiEntry],
        after_by_key: dict[ParameterKey, _ParamGuiEntry],
        collapsed_before: dict[str, bool],
        collapsed_after: dict[str, bool],
    ) -> None:
        self._before_by_key = before_by_key
        self._after_by_key = after_by_key
        self._collapsed_before = collapsed_before
        self._collapsed_after = collapsed_after

    @property
    def changed_keys(self) -> frozenset[ParameterKey]:
        """この entry が変更する parameter key を返す。"""

        return frozenset(self._before_by_key)

    @property
    def changed_headers(self) -> frozenset[str]:
        """この entry が変更する collapse header を返す。"""

        return frozenset(self._collapsed_before)


class ParamStorePatchCapture:
    """GUI transaction 中に、実際に触れた key の変更前値だけを遅延 capture する。"""

    __slots__ = ("_store", "_before_by_key", "_collapsed_before")

    def __init__(self, store: ParamStore) -> None:
        self._store = store
        self._before_by_key: dict[ParameterKey, _ParamGuiEntry] = {}
        self._collapsed_before: frozenset[str] | None = None

    def observe_key(self, key: ParameterKey) -> None:
        """key を最初に変更する直前の値だけを保存する。"""

        if key not in self._before_by_key:
            self._before_by_key[key] = _capture_gui_entry(self._store, key)

    def observe_headers(self, headers: frozenset[str] | None = None) -> None:
        """collapse set を最初に変更する直前だけ保存する。"""

        if self._collapsed_before is None:
            self._collapsed_before = (
                frozenset(self._store._collapsed_headers_ref())
                if headers is None
                else frozenset(headers)
            )

    def finish(self) -> ParamStorePatch | None:
        """実差分だけを immutable history entry として返す。"""

        before_by_key: dict[ParameterKey, _ParamGuiEntry] = {}
        after_by_key: dict[ParameterKey, _ParamGuiEntry] = {}
        for key, before in self._before_by_key.items():
            after = _capture_gui_entry(self._store, key)
            if _gui_entries_match(before, after):
                continue
            before_by_key[key] = before
            after_by_key[key] = after

        collapsed_before: dict[str, bool] = {}
        collapsed_after: dict[str, bool] = {}
        if self._collapsed_before is not None:
            after_headers = frozenset(self._store._collapsed_headers_ref())
            for header in self._collapsed_before ^ after_headers:
                collapsed_before[header] = header in self._collapsed_before
                collapsed_after[header] = header in after_headers

        if not before_by_key and not collapsed_before:
            return None
        return ParamStorePatch(
            before_by_key=before_by_key,
            after_by_key=after_by_key,
            collapsed_before=collapsed_before,
            collapsed_after=collapsed_after,
        )


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
    折りたたみ状態、およびeffectのGUI順である。ラベル、ordinal、
    effect topology、explicitフラグなどcode-ownedの構造は復元対象にしない。

    復元時は、現在も同じ ``ParameterKey`` と ``meta.kind`` で存在する
    parameter だけへ merge する。そのため、履歴作成後に draw が
    発見した parameter や、code reload 後の新しい metadata は消えない。

    Notes
    -----
    コンストラクタの keyword は従来 API と互換に保つ。ただし
    ``explicit_by_key`` / ``labels`` / ``ordinals`` は code-owned なので、
    互換入力として受け取るだけで復元対象には含めない。
    """

    __slots__ = (
        "_states",
        "_meta",
        "_collapsed_by_header",
        "_effect_order_state",
        "_effect_topology_signatures",
    )

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
        self._effect_order_state = effects.order_state_by_chain()
        self._effect_topology_signatures = effects.topology_signatures()

        # 従来コンストラクタ API は保つが、code-owned 値は保存しない。
        _ = explicit_by_key, labels, ordinals

    @classmethod
    def _from_gui_owned_parts(
        cls,
        *,
        states: dict[ParameterKey, ParamState],
        meta: dict[ParameterKey, ParamMeta],
        collapsed_by_header: dict[str, bool],
        effect_order_state: dict[
            str,
            tuple[tuple[str, str], ...] | None,
        ],
        effect_topology_signatures: dict[str, EffectTopologySignature],
    ) -> ParamStoreMemento:
        """永続化済み GUI-owned 部分から memento を再構築する。

        Notes
        -----
        named variation の codec 向けの package-private constructor。
        通常の capture は ``capture_param_store_memento`` を使う。
        """

        memento = cls.__new__(cls)
        memento._states = deepcopy(states)
        memento._meta = deepcopy(meta)
        memento._collapsed_by_header = {
            str(header): bool(collapsed)
            for header, collapsed in collapsed_by_header.items()
        }
        memento._effect_order_state = deepcopy(effect_order_state)
        memento._effect_topology_signatures = deepcopy(
            effect_topology_signatures
        )
        return memento


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
    candidate_effects = deepcopy(store._effects_ref())
    if candidate_effects.restore_order_state(
        memento._effect_order_state,
        topology_signatures=memento._effect_topology_signatures,
    ):
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

    changed_value_keys: list[ParameterKey] = []
    structure_changed = False
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
            changed_value_keys.append(_key)

        if current_meta.ui_min != saved_meta.ui_min or current_meta.ui_max != saved_meta.ui_max:
            # kind/choices は現在の code-owned metadata を保持し、GUI が
            # 編集する range だけを復元する。
            store._meta[_key] = replace(
                current_meta,
                ui_min=deepcopy(saved_meta.ui_min),
                ui_max=deepcopy(saved_meta.ui_max),
            )
            structure_changed = True

    current_known_headers = _known_collapse_headers(store._states, store._effects_ref())
    collapsed = store._collapsed_headers_ref()
    for header, saved_collapsed in memento._collapsed_by_header.items():
        if header not in current_known_headers:
            continue
        if saved_collapsed and header not in collapsed:
            collapsed.add(header)
            structure_changed = True
        elif not saved_collapsed and header in collapsed:
            collapsed.discard(header)
            structure_changed = True

    if store._effects_ref().restore_order_state(
        memento._effect_order_state,
        topology_signatures=memento._effect_topology_signatures,
    ):
        structure_changed = True

    changed = structure_changed or bool(changed_value_keys)
    if changed:
        # revision は過去の値へ戻さず単調に進め、読み取り cache を無効化する。
        store._touch(
            structure=structure_changed,
            value_keys=changed_value_keys,
        )
    return changed


def _apply_gui_entry(
    store: ParamStore,
    key: ParameterKey,
    saved: _ParamGuiEntry,
) -> tuple[bool, bool]:
    """1 key を適用し、(state_changed, meta_changed) を返す。"""

    saved_state = saved.state
    saved_meta = saved.meta
    current_state = store._states.get(key)
    current_meta = store._meta.get(key)
    if (
        saved_state is None
        or saved_meta is None
        or current_state is None
        or current_meta is None
        or str(saved_meta.kind) != str(current_meta.kind)
    ):
        return False, False

    state_changed = (
        current_state.override != saved_state.override
        or current_state.ui_value != saved_state.ui_value
        or current_state.cc_key != saved_state.cc_key
    )
    if state_changed:
        current_state.override = bool(saved_state.override)
        current_state.ui_value = deepcopy(saved_state.ui_value)
        current_state.cc_key = deepcopy(saved_state.cc_key)

    meta_changed = (
        current_meta.ui_min != saved_meta.ui_min
        or current_meta.ui_max != saved_meta.ui_max
    )
    if meta_changed:
        store._meta[key] = replace(
            current_meta,
            ui_min=deepcopy(saved_meta.ui_min),
            ui_max=deepcopy(saved_meta.ui_max),
        )
    return state_changed, meta_changed


def restore_param_store_patch(
    store: ParamStore,
    patch: ParamStorePatch,
    *,
    after: bool,
) -> bool:
    """patch の変更前、または変更後を現在の code-owned 構造へ merge する。"""

    if not isinstance(patch, ParamStorePatch):
        raise TypeError("patch must be a ParamStorePatch")
    entries = patch._after_by_key if after else patch._before_by_key
    header_states = patch._collapsed_after if after else patch._collapsed_before

    changed_value_keys: list[ParameterKey] = []
    meta_changed = False
    for key, saved in entries.items():
        state_changed, entry_meta_changed = _apply_gui_entry(store, key, saved)
        if state_changed:
            changed_value_keys.append(key)
        meta_changed = meta_changed or entry_meta_changed

    headers_changed = False
    if header_states:
        known_headers = _known_collapse_headers(store._states, store._effects_ref())
        collapsed = store._collapsed_headers_ref()
        for header, should_collapse in header_states.items():
            if header not in known_headers:
                continue
            if should_collapse and header not in collapsed:
                collapsed.add(header)
                headers_changed = True
            elif not should_collapse and header in collapsed:
                collapsed.discard(header)
                headers_changed = True

    if not changed_value_keys and not meta_changed and not headers_changed:
        return False
    store._touch(
        structure=bool(meta_changed or headers_changed),
        value_keys=changed_value_keys,
    )
    return True


def coalesce_param_store_patches(
    first: ParamStorePatch,
    second: ParamStorePatch,
) -> ParamStorePatch | None:
    """同じ対象を連続変更した patch を 1 Undo 単位へまとめる。"""

    if (
        first.changed_keys != second.changed_keys
        or first.changed_headers != second.changed_headers
    ):
        return None
    return ParamStorePatch(
        before_by_key=dict(first._before_by_key),
        after_by_key=dict(second._after_by_key),
        collapsed_before=dict(first._collapsed_before),
        collapsed_after=dict(second._collapsed_after),
    )


def update_param_store_memento_from_patch(
    memento: ParamStoreMemento,
    patch: ParamStorePatch,
    *,
    after: bool,
) -> None:
    """履歴基準 memento を patch と同じ側へ少数 key だけ更新する。"""

    entries = patch._after_by_key if after else patch._before_by_key
    for key, saved in entries.items():
        if saved.state is None or saved.meta is None:
            continue
        memento._states[key] = deepcopy(saved.state)
        memento._meta[key] = deepcopy(saved.meta)

    header_states = patch._collapsed_after if after else patch._collapsed_before
    for header, collapsed in header_states.items():
        memento._collapsed_by_header[str(header)] = bool(collapsed)


__all__ = [
    "ParamStorePatch",
    "ParamStorePatchCapture",
    "ParamStoreMemento",
    "capture_param_store_memento",
    "coalesce_param_store_patches",
    "param_store_memento_matches",
    "restore_param_store_memento",
    "restore_param_store_patch",
    "update_param_store_memento_from_patch",
]
