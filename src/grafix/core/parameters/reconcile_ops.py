# どこで: `src/grafix/core/parameters/reconcile_ops.py`。
# 何を: loaded/observed の差分を再リンクし、グループの migrate を適用する。
# なぜ: site_id の揺れを吸収し、GUI の増殖と調整値の喪失を抑えるため。

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .key import ParameterKey
from .reconcile import (
    ReconcileOrphan,
    build_group_fingerprints,
    plan_group_reconciliation,
)
from .snapshot_ops import store_snapshot
from .store import ParamStore

if TYPE_CHECKING:
    from .history import ParamStoreHistory

GroupKey = tuple[str, str]  # (op, site_id)


def reconcile_loaded_groups_for_runtime(store: ParamStore) -> None:
    """ロード済みグループと観測済みグループの差分を再リンクする（削除はしない）。"""

    runtime = store._runtime_ref()
    # orphan は現在の loaded/observed 集合から毎回導出する runtime state。
    # code reload 後に解消した候補を残さないよう、早期 return より前に空にする。
    runtime.reconcile_orphans.clear()
    if not runtime.loaded_groups or not runtime.observed_groups:
        return

    from .style import STYLE_OP

    loaded_targets = {
        (op, site_id) for op, site_id in runtime.loaded_groups if op not in {STYLE_OP}
    }
    observed_targets = {
        (op, site_id) for op, site_id in runtime.observed_groups if op not in {STYLE_OP}
    }

    fresh = observed_targets - loaded_targets
    if not fresh:
        return

    stale = loaded_targets - observed_targets
    fresh_ops = {op for op, _site_id in fresh}
    already_migrated_old = {
        old_group for old_group, _new_group in runtime.reconcile_applied
    }
    stale_candidates = {
        group
        for group in stale
        if group[0] in fresh_ops and group not in already_migrated_old
    }
    if not stale_candidates:
        return

    snapshot = store_snapshot(store)
    fingerprints = build_group_fingerprints(snapshot)
    plan = plan_group_reconciliation(
        stale=sorted(stale_candidates),
        fresh=sorted(fresh),
        fingerprints=fingerprints,
    )

    for old_group, new_group in plan.matches:
        pair = (old_group, new_group)
        if pair in runtime.reconcile_applied:
            continue
        migrate_group(store, old_group, new_group)
        runtime.reconcile_applied.add(pair)
        # migration 済みの new group を次 frame で再び fresh と判定しない。
        runtime.loaded_groups.add(new_group)

    runtime.reconcile_orphans.update(
        {orphan.new_group: orphan for orphan in plan.orphans}
    )


def list_reconcile_orphans(store: ParamStore) -> tuple[ReconcileOrphan, ...]:
    """現在の runtime に残る曖昧な再リンク候補を安定順で返す。"""

    if not isinstance(store, ParamStore):
        raise TypeError("store must be a ParamStore")
    values = store._runtime_ref().reconcile_orphans.values()
    return tuple(sorted(values, key=lambda orphan: orphan.new_group))


def manual_migrate_orphan(
    store: ParamStore,
    old_group: GroupKey,
    new_group: GroupKey,
    *,
    history: ParamStoreHistory | None = None,
) -> None:
    """orphan の旧候補 1 件を現在 group へ手動 migrate する。

    Parameters
    ----------
    store : ParamStore
        対象 store。
    old_group : tuple[str, str]
        保存データ側の候補 ``(op, site_id)``。
    new_group : tuple[str, str]
        現在のコードで観測された orphan ``(op, site_id)``。
    history : ParamStoreHistory or None, optional
        指定時は migrate を単一 Undo/Redo 操作として記録する。

    Notes
    -----
    migrate 後の state は通常の ParamStore codec に含まれるため、追加の永続化形式を
    持たずに次回起動へ引き継がれる。runtime の orphan 自体は永続化しない。
    """

    if not isinstance(store, ParamStore):
        raise TypeError("store must be a ParamStore")
    if history is not None and history._store is not store:
        raise ValueError("history must belong to the same ParamStore")

    normalized_old = _normalize_group(old_group, name="old_group")
    normalized_new = _normalize_group(new_group, name="new_group")
    runtime = store._runtime_ref()
    orphan = runtime.reconcile_orphans.get(normalized_new)
    if orphan is None:
        raise KeyError(f"reconcile orphan が存在しません: {normalized_new!r}")
    if normalized_old not in orphan.candidate_old_groups:
        raise ValueError(
            f"old_group は orphan の候補ではありません: {normalized_old!r}"
        )
    if any(
        applied_old == normalized_old and applied_new != normalized_new
        for applied_old, applied_new in runtime.reconcile_applied
    ):
        raise ValueError(f"old_group は既に別 group へ migrate 済みです: {normalized_old!r}")

    def apply() -> None:
        migrate_group(store, normalized_old, normalized_new)

    if history is None:
        apply()
    else:
        history.break_coalescing()
        with history.transaction(
            source=("manual-reconcile", normalized_old, normalized_new)
        ):
            apply()

    runtime.reconcile_applied.add((normalized_old, normalized_new))
    runtime.loaded_groups.add(normalized_new)
    runtime.reconcile_orphans.pop(normalized_new, None)

    # 同じ旧 group は 1 件にしか割り当てられない。他 orphan の候補から外す。
    for target, other in tuple(runtime.reconcile_orphans.items()):
        remaining = tuple(
            candidate
            for candidate in other.candidate_old_groups
            if candidate != normalized_old
        )
        if not remaining:
            runtime.reconcile_orphans.pop(target, None)
        elif remaining != other.candidate_old_groups:
            runtime.reconcile_orphans[target] = replace(
                other,
                candidate_old_groups=remaining,
            )


def migrate_group(store: ParamStore, old_group: GroupKey, new_group: GroupKey) -> None:
    """old_group の GUI 状態/メタを new_group へ可能な範囲で移す。"""

    old_op, old_site_id = old_group
    new_op, new_site_id = new_group
    if str(old_op) != str(new_op):
        raise ValueError(f"op mismatch: {old_group!r} -> {new_group!r}")
    op = str(old_op)

    labels = store._labels_ref()
    ordinals = store._ordinals_ref()

    old_label = labels.get(op, str(old_site_id))
    if old_label is not None and labels.get(op, str(new_site_id)) is None:
        labels.set(op, str(new_site_id), old_label)

    ordinals.migrate(op, str(old_site_id), str(new_site_id))

    collapsed = store._collapsed_headers_ref()
    old_collapse_key = f"primitive:{op}:{old_site_id}"
    if old_collapse_key in collapsed:
        collapsed.discard(old_collapse_key)
        collapsed.add(f"primitive:{op}:{new_site_id}")

    locked = store._locked_keys_ref()
    favorites = set(store._favorite_keys_snapshot())
    for old_key in _group_keys(store, op=op, site_id=str(old_site_id)):
        new_key = ParameterKey(op=op, site_id=str(new_site_id), arg=str(old_key.arg))
        old_meta = store._meta.get(old_key)
        new_meta = store._meta.get(new_key)
        if old_meta is None or new_meta is None:
            continue
        if old_meta.kind != new_meta.kind:
            continue

        old_state = store._states.get(old_key)
        new_state = store._states.get(new_key)
        if old_state is not None and new_state is not None:
            new_state.override = bool(old_state.override)
            new_state.ui_value = old_state.ui_value
            new_state.cc_key = old_state.cc_key

        old_explicit = store._explicit_by_key.get(old_key)
        if old_explicit is not None and new_key not in store._explicit_by_key:
            store._explicit_by_key[new_key] = bool(old_explicit)

        if old_key in locked:
            locked.discard(old_key)
            locked.add(new_key)

        if old_key in favorites:
            favorites.discard(old_key)
            favorites.add(new_key)

        ui_min = old_meta.ui_min if old_meta.ui_min is not None else new_meta.ui_min
        ui_max = old_meta.ui_max if old_meta.ui_max is not None else new_meta.ui_max
        if ui_min != new_meta.ui_min or ui_max != new_meta.ui_max:
            store._meta[new_key] = replace(
                new_meta,
                ui_min=ui_min,
                ui_max=ui_max,
            )

    store._replace_favorite_keys(favorites)
    store._touch()


def _group_keys(store: ParamStore, *, op: str, site_id: str) -> list[ParameterKey]:
    keys: set[ParameterKey] = set()
    for key in store._states.keys():
        if str(key.op) == str(op) and str(key.site_id) == str(site_id):
            keys.add(key)
    for key in store._meta.keys():
        if str(key.op) == str(op) and str(key.site_id) == str(site_id):
            keys.add(key)
    for key in store._locked_keys_ref():
        if str(key.op) == str(op) and str(key.site_id) == str(site_id):
            keys.add(key)
    for key in store._favorite_keys_ref():
        if str(key.op) == str(op) and str(key.site_id) == str(site_id):
            keys.add(key)
    return sorted(keys, key=lambda k: str(k.arg))


def _normalize_group(group: GroupKey, *, name: str) -> GroupKey:
    if (
        not isinstance(group, tuple)
        or len(group) != 2
        or not all(isinstance(part, str) and part for part in group)
    ):
        raise TypeError(f"{name} must be a non-empty (op, site_id) tuple[str, str]")
    return str(group[0]), str(group[1])


__all__ = [
    "GroupKey",
    "list_reconcile_orphans",
    "manual_migrate_orphan",
    "migrate_group",
    "reconcile_loaded_groups_for_runtime",
]
