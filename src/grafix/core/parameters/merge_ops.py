# どこで: `src/grafix/core/parameters/merge_ops.py`。
# 何を: フレーム内で観測したパラメータレコードを ParamStore にマージする。
# なぜ: 書き込み経路を ops に固定し、不変条件の知識を 1 箇所へ寄せるため。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast
from weakref import WeakKeyDictionary

from .frame_params import FrameParamRecord
from .key import ParameterKey
from .reconcile_ops import reconcile_loaded_groups_for_runtime
from .runtime import ParamStoreRuntime
from .source import ValueSource
from .store import ParamStore
from .view import canonicalize_ui_value

_MISSING = object()
_VALUE_SOURCES = frozenset({"code", "ui", "midi_live", "midi_frozen"})


@dataclass(slots=True)
class _StableMergeEntry:
    """stable record の構造と直近 runtime 値をまとめた内部 cache entry。"""

    group: tuple[str, str]
    meta_kind: str
    effect_step: tuple[str, int] | None
    explicit: bool | None
    last_effective: object
    last_source: object
    runtime_frame_token: int = 0
    runtime_before_effective: object = _MISSING
    runtime_before_source: object = _MISSING
    runtime_differs: bool = False
    explicit_frame_token: int = 0
    explicit_in_frame: bool = False


@dataclass(slots=True)
class _StableMergeCache:
    """ParamStore の table revision に追従する merge 専用 cache。"""

    table_revision: int = -1
    runtime: ParamStoreRuntime | None = None
    next_frame_token: int = 0
    entries: dict[ParameterKey, _StableMergeEntry] = field(default_factory=dict)


# ParamStore 自身へ hot-path 専用 field を増やさず、store の寿命と一緒に破棄する。
_CACHE_BY_STORE: WeakKeyDictionary[ParamStore, _StableMergeCache] = WeakKeyDictionary()


def merge_frame_params(store: ParamStore, records: list[FrameParamRecord]) -> None:
    """フレームを merge し、effective/source の最終差分を revision 化する。"""

    runtime = store._runtime_ref()
    cache = _cache_for_store(store)
    cache_invalidated = (
        cache.table_revision != store.table_revision or cache.runtime is not runtime
    )
    if cache_invalidated:
        cache.entries.clear()
        cache.table_revision = store.table_revision
        cache.runtime = runtime

    cache.next_frame_token += 1
    frame_token = cache.next_frame_token
    runtime_changes: list[tuple[ParameterKey, _StableMergeEntry]] = []
    try:
        _merge_frame_params(
            store,
            records,
            cache=cache,
            frame_token=frame_token,
            cache_invalidated=cache_invalidated,
            runtime_changes=runtime_changes,
        )
    except BaseException:
        # failed frame の effective/source は公開しない。変更が起きた key だけを
        # 戻し、stable な 10,000 records のために全 key の before snapshot は作らない。
        for key, entry in runtime_changes:
            effective = entry.runtime_before_effective
            source = entry.runtime_before_source
            if effective is _MISSING:
                runtime.last_effective_by_key.pop(key, None)
            else:
                runtime.last_effective_by_key[key] = effective
            if source is _MISSING:
                runtime.last_source_by_key.pop(key, None)
            else:
                runtime.last_source_by_key[key] = source  # type: ignore[assignment]
            entry.last_effective = effective
            entry.last_source = source

        # 永続 store 側は従来どおり部分変更を保持し得るため、構造 cache だけは
        # 必ず捨て、次回 merge で現在状態から再検証する。
        cache.entries.clear()
        cache.table_revision = -1
        raise

    runtime.record_effective_changes(
        key for key, entry in runtime_changes if entry.runtime_differs
    )
    cache.table_revision = store.table_revision


def _merge_frame_params(
    store: ParamStore,
    records: list[FrameParamRecord],
    *,
    cache: _StableMergeCache,
    frame_token: int,
    cache_invalidated: bool,
    runtime_changes: list[tuple[ParameterKey, _StableMergeEntry]],
) -> None:
    """レコードを単一 pass で保存し、stable record の構造処理を省略する。"""

    runtime = store._runtime_ref()
    ordinals = store._ordinals_ref()
    effects = store._effects_ref()
    entries = cache.entries
    explicit_changes: list[tuple[ParameterKey, _StableMergeEntry]] = []
    structure_changed = False

    for rec in records:
        key = rec.key
        desired_effect_step = _effect_step_for_record(rec)
        entry = entries.get(key)

        if (
            entry is None
            or entry.meta_kind != rec.meta.kind
            or (
                desired_effect_step is not None
                and entry.effect_step != desired_effect_step
            )
        ):
            # 初出・構造変更・cache 再構築時だけ汎用 path へ入る。stable path の
            # eligibility を判定するための records 全件 pre-scan は行わない。
            group = (str(key.op), str(key.site_id))
            if group not in runtime.observed_groups:
                runtime.observed_groups.add(group)
                structure_changed = True
            if group not in runtime.display_order_by_group:
                runtime.display_order_by_group[group] = int(runtime.next_display_order)
                runtime.next_display_order += 1
                store._touch()
                structure_changed = True

            if ordinals.get(key.op, key.site_id) is None:
                ordinals.get_or_assign(key.op, key.site_id)
                store._touch()
                structure_changed = True

            # canonicalize は初期 ui_value を作るときだけ必要であり、既存 state の
            # stable frame では base が変化しても永続 ui_value へ書かれない。
            if key not in store._states:
                store._ensure_state(
                    key,
                    base_value=canonicalize_ui_value(rec.base, rec.meta),
                    initial_override=(not bool(rec.explicit)),
                )
                structure_changed = True

            existing_meta = store._meta.get(key)
            if existing_meta is None or existing_meta.kind != rec.meta.kind:
                store._set_meta(key, rec.meta)
                structure_changed = True

            current_effect_step = effects.get_step(key.op, key.site_id)
            if (
                desired_effect_step is not None
                and current_effect_step != desired_effect_step
            ):
                effects.record_step(
                    op=str(key.op),
                    site_id=str(key.site_id),
                    chain_id=desired_effect_step[0],
                    step_index=desired_effect_step[1],
                )
                store._touch()
                structure_changed = True
                current_effect_step = desired_effect_step

            if entry is None:
                entry = _StableMergeEntry(
                    group=group,
                    meta_kind=str(rec.meta.kind),
                    effect_step=current_effect_step,
                    explicit=store._explicit_by_key.get(key),
                    last_effective=runtime.last_effective_by_key.get(key, _MISSING),
                    last_source=runtime.last_source_by_key.get(key, _MISSING),
                )
                entries[key] = entry
            else:
                # duplicate key が同一 frame 中に構造を変えても、runtime/explicit の
                # frame-local 状態は同じ entry に残して last-record-wins を守る。
                entry.group = group
                entry.meta_kind = str(rec.meta.kind)
                entry.effect_step = current_effect_step

        _merge_runtime_observation(
            runtime=runtime,
            key=key,
            rec=rec,
            entry=entry,
            frame_token=frame_token,
            runtime_changes=runtime_changes,
        )
        _record_explicit_change(
            key=key,
            explicit=bool(rec.explicit),
            entry=entry,
            frame_token=frame_token,
            explicit_changes=explicit_changes,
        )

    # label 変更など、merge より前に table revision が変化した場合も fingerprint を
    # 再評価する。一方、完全 stable frame では大きな loaded/observed 集合を再走査しない。
    if cache_invalidated or structure_changed:
        reconcile_loaded_groups_for_runtime(store)

    explicit_by_key = {
        key: entry.explicit_in_frame
        for key, entry in explicit_changes
        if entry.explicit_in_frame != entry.explicit
    }
    # 空 mapping でも呼ぶことで、既存の commit hook/例外伝播 semantics を維持する。
    _apply_explicit_override_follow_policy(store, explicit_by_key)
    for key, entry in explicit_changes:
        entry.explicit = store._explicit_by_key.get(key)


def _cache_for_store(store: ParamStore) -> _StableMergeCache:
    cache = _CACHE_BY_STORE.get(store)
    if cache is None:
        cache = _StableMergeCache()
        _CACHE_BY_STORE[store] = cache
    return cache


def _effect_step_for_record(rec: FrameParamRecord) -> tuple[str, int] | None:
    if rec.chain_id is None or rec.step_index is None:
        return None
    return str(rec.chain_id), int(rec.step_index)


def _same_runtime_value(left: object, right: object) -> bool:
    """runtime 値を比較し、非 scalar の曖昧な比較は変更として扱う。"""

    if left is right:
        return True
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _merge_runtime_observation(
    *,
    runtime: ParamStoreRuntime,
    key: ParameterKey,
    rec: FrameParamRecord,
    entry: _StableMergeEntry,
    frame_token: int,
    runtime_changes: list[tuple[ParameterKey, _StableMergeEntry]],
) -> None:
    """effective/source の実変更だけを保存し、rollback entry を遅延作成する。"""

    effective_changed = rec.effective is not None and not _same_runtime_value(
        rec.effective, entry.last_effective
    )
    source_changed = rec.source in _VALUE_SOURCES and not _same_runtime_value(
        rec.source, entry.last_source
    )
    if not effective_changed and not source_changed:
        return

    if entry.runtime_frame_token != frame_token:
        entry.runtime_frame_token = frame_token
        entry.runtime_before_effective = entry.last_effective
        entry.runtime_before_source = entry.last_source
        entry.runtime_differs = False
        runtime_changes.append((key, entry))

    if effective_changed:
        entry.last_effective = rec.effective
        runtime.last_effective_by_key[key] = rec.effective
    if source_changed:
        entry.last_source = rec.source
        runtime.last_source_by_key[key] = cast(ValueSource, rec.source)

    entry.runtime_differs = not (
        _same_runtime_value(entry.last_effective, entry.runtime_before_effective)
        and _same_runtime_value(entry.last_source, entry.runtime_before_source)
    )


def _record_explicit_change(
    *,
    key: ParameterKey,
    explicit: bool,
    entry: _StableMergeEntry,
    frame_token: int,
    explicit_changes: list[tuple[ParameterKey, _StableMergeEntry]],
) -> None:
    """explicit の最終差分だけを follow policy へ渡す。"""

    if entry.explicit_frame_token == frame_token:
        entry.explicit_in_frame = bool(explicit)
        return
    if entry.explicit == bool(explicit):
        return
    entry.explicit_frame_token = frame_token
    entry.explicit_in_frame = bool(explicit)
    explicit_changes.append((key, entry))


def _apply_explicit_override_follow_policy(
    store: ParamStore, explicit_by_key_this_frame: Mapping[ParameterKey, bool]
) -> None:
    """explicit/implicit の変化に追従して override を条件付きで更新する。"""

    for key, new_explicit in explicit_by_key_this_frame.items():
        prev_explicit = store._explicit_by_key.get(key)
        new_explicit = bool(new_explicit)

        if prev_explicit is None:
            # 旧 JSON（explicit 情報なし）もあるので、unknown の場合は触らず記録だけ行う。
            store._set_explicit(key, new_explicit)
            continue

        prev_explicit = bool(prev_explicit)
        if prev_explicit == new_explicit:
            continue

        state = store._states.get(key)
        if state is None:
            store._set_explicit(key, new_explicit)
            continue

        default_override_prev = not prev_explicit
        default_override_new = not new_explicit
        if bool(state.override) == bool(default_override_prev):
            next_override = bool(default_override_new)
            if state.override != next_override:
                state.override = next_override
                store._touch()

        store._set_explicit(key, new_explicit)


__all__ = ["merge_frame_params"]
