"""effect chain topologyとGUI-owned適用順のstore操作を提供する。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TypeAlias

from .effects import (
    EffectOrder,
    EffectOrderPlacement,
    EffectStepKey,
    moved_effect_order,
)
from .frame_params import FrameEffectChainRecord
from .store import ParamStore

EffectOrderSnapshot: TypeAlias = Mapping[str, EffectOrder]

_EMPTY_EFFECT_ORDER_SNAPSHOT: EffectOrderSnapshot = MappingProxyType({})


def store_effect_order_snapshot(store: ParamStore) -> EffectOrderSnapshot:
    """現在のGUI-owned order overrideをimmutable snapshotへ固定する。"""

    overrides = store._effects_ref().order_overrides()
    if not overrides:
        return _EMPTY_EFFECT_ORDER_SNAPSHOT
    return MappingProxyType(overrides)


def begin_effect_chain_generation(store: ParamStore) -> None:
    """source reload後の次の成功evaluationをcanonical topologyにする。

    通常frameの条件分岐ではchainを蓄積したままにするため、このoperationは
    source generation交換時だけ呼ぶ。開始自体は公開状態を変えないのでrevisionを
    進めず、失敗evaluationでは保留状態も既存chainも維持する。
    """

    prefix = "effect_chain:"
    collapsed_chain_ids = {
        header[len(prefix) :]
        for header in store._collapsed_headers_ref()
        if header.startswith(prefix) and len(header) > len(prefix)
    }
    store._effects_ref().begin_observation_generation(
        additional_chain_ids=collapsed_chain_ids,
    )


def merge_frame_effect_chains(
    store: ParamStore,
    records: Sequence[FrameEffectChainRecord],
    *,
    observation_complete: bool = False,
) -> bool:
    """成功frameで観測したeffect topologyをstoreへmergeする。

    ``observation_complete`` は実際に一つのevaluationが成功した場合だけ指定する。
    source reload後の最初の完全な成功観測では、そのrecord集合をcanonicalとし、
    旧generationにしかないchainとcollapse状態を一度だけ削除する。
    """

    latest_by_chain: dict[str, FrameEffectChainRecord] = {}
    for record in records:
        latest_by_chain[str(record.chain_id)] = record
    changed = False
    effects = store._effects_ref()
    for record in latest_by_chain.values():
        changed = (
            effects.record_chain(
                chain_id=record.chain_id,
                steps=record.steps,
            )
            or changed
        )
    if observation_complete:
        stale_chain_ids = effects.complete_observation_generation(
            latest_by_chain,
        )
        if stale_chain_ids:
            collapsed = store._collapsed_headers_ref()
            for chain_id in stale_chain_ids:
                collapsed.discard(f"effect_chain:{chain_id}")
            changed = True
    if changed:
        store._touch()
    return changed


def set_effect_order(
    store: ParamStore,
    *,
    chain_id: str,
    order: Sequence[EffectStepKey],
) -> bool:
    """指定chainのGUI順を完全なpermutationで設定する。"""

    changed = store._effects_ref().set_order_override(str(chain_id), order)
    if changed:
        store._touch()
    return changed


def move_effect_step(
    store: ParamStore,
    *,
    chain_id: str,
    source: EffectStepKey,
    target: EffectStepKey,
    placement: EffectOrderPlacement,
) -> bool:
    """同一chain内のstepをtargetの前後へ移動する。"""

    effects = store._effects_ref()
    current = effects.effective_order(str(chain_id))
    if current is None:
        raise KeyError(f"unknown effect chain: {str(chain_id)!r}")
    moved = moved_effect_order(
        current,
        source=source,
        target=target,
        placement=placement,
    )
    return set_effect_order(store, chain_id=str(chain_id), order=moved)


def reset_effect_order(store: ParamStore, *, chain_id: str) -> bool:
    """指定chainをコード記述順へ戻す。"""

    changed = store._effects_ref().reset_order(str(chain_id))
    if changed:
        store._touch()
    return changed


def restore_effect_order_state(
    store: ParamStore,
    state_by_chain: Mapping[str, Sequence[EffectStepKey] | None],
) -> bool:
    """memento由来のorder stateを現在topologyへmergeする。"""

    changed = store._effects_ref().restore_order_state(state_by_chain)
    if changed:
        store._touch()
    return changed


__all__ = [
    "EffectOrderSnapshot",
    "begin_effect_chain_generation",
    "merge_frame_effect_chains",
    "move_effect_step",
    "reset_effect_order",
    "restore_effect_order_state",
    "set_effect_order",
    "store_effect_order_snapshot",
]
