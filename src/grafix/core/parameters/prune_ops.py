# どこで: `src/grafix/core/parameters/prune_ops.py`。
# 何を: 実行時に観測されなかったロード済みグループを ParamStore から削除する。
# なぜ: GUI のヘッダ増殖と永続化ファイル肥大化を防ぐため。

"""ParamStore から不要になった parameter グループ/引数を削除する操作群。

このモジュールは、`ParamStore` に溜まっていく「もう使われていない parameter」を
実行の節目で掃除（prune）するための関数を提供する。

対象は大きく 2 種類:

- グループ単位の削除: `(op, site_id)` をキーとする一連の parameter 群
  （例: ある primitive / effect が存在していたが、今回の実行では観測されなかった等）
- 引数単位の削除: 登録済み op に対して、registry に存在しない `arg` を持つ parameter 群

I/O・副作用
----------
- いずれの関数も `store` を破壊的に変更する（内部辞書や runtime state を削除する）。
- 永続化ファイルの書き換え自体はこのモジュールでは行わない。

読む順番（主要フロー）
----------------------
1. `prune_stale_loaded_groups`: 実行終了時に「ロードされたが観測されなかった」グループを削除
2. `prune_unknown_args_in_known_ops`: registry と照合して、既知 op の未知 arg を削除
3. `prune_groups`: 実際の削除処理（labels/ordinals/effects/collapsed など関連状態も同期）
"""

from __future__ import annotations

from collections.abc import Iterable

from grafix.core.effect_registry import effect_registry
from grafix.core.primitive_registry import primitive_registry

from .key import ParameterKey
from .reconcile_ops import GroupKey, reconcile_loaded_groups_for_runtime
from .store import ParamStore


def prune_stale_loaded_groups(store: ParamStore) -> None:
    """実行終了時に「ロード済みだが観測されなかった」グループを削除する。

    Parameters
    ----------
    store : ParamStore
        対象の `ParamStore`。

    Notes
    -----
    - 「ロード済みグループ」は永続化ファイル等から読み込まれた parameter 群を指す。
    - 「観測されたグループ」は今回の実行中に実際に UI/実行系から参照された群を指す。
    - 両者の差分（loaded - observed）を「古い（stale）」とみなし、まとめて削除する。
    """

    runtime = store._runtime_ref()
    if not runtime.loaded_groups:
        # 今回の実行でロードされていないなら、比較対象がないので何もしない。
        return

    # 保存直前にもう一度だけ再リンクを試みる（最後まで観測した集合で最善を尽くす）。
    reconcile_loaded_groups_for_runtime(store)

    from .style import STYLE_OP

    # STYLE は "常に存在する/特別扱い" の前提で、stale 判定から除外する。
    # （STYLE を削除すると、UI 体験や既定スタイルの永続化に悪影響が出る可能性がある）
    loaded_targets = {
        (op, site_id) for op, site_id in runtime.loaded_groups if op not in {STYLE_OP}
    }
    observed_targets = {
        (op, site_id) for op, site_id in runtime.observed_groups if op not in {STYLE_OP}
    }

    stale = loaded_targets - observed_targets
    prune_groups(store, stale)


def prune_unknown_args_in_known_ops(store: ParamStore) -> list[ParameterKey]:
    """登録済み primitive/effect の未登録引数（arg）をストアから削除する。

    Parameters
    ----------
    store : ParamStore
        対象の `ParamStore`。

    Returns
    -------
    list[ParameterKey]
        削除したキーの一覧（元の `ParameterKey` を返す）。

    Notes
    -----
    - `op` が未登録（primitive/effect どちらでもない）のものは削除しない。
      （プラグイン未ロード等の可能性があるため）
    - 判定は registry の meta keys を基準にする（`param_order` は並び専用）。
    """

    removed: list[ParameterKey] = []

    primitive_known_args_by_op: dict[str, set[str]] = {}
    effect_known_args_by_op: dict[str, set[str]] = {}

    keys = set(store._states) | set(store._meta) | set(store._explicit_by_key)
    # 何が削除されたかをデバッグしやすいよう、順序を固定して走査する。
    for key in sorted(keys, key=lambda k: (str(k.op), str(k.site_id), str(k.arg))):
        op = str(key.op)
        arg = str(key.arg)

        if op in primitive_registry:
            # registry の meta は op ごとに一定なので、1 回引いたらキャッシュする。
            known_args = primitive_known_args_by_op.get(op)
            if known_args is None:
                known_args = set(primitive_registry.get_meta(op).keys())
                primitive_known_args_by_op[op] = known_args
            if arg in known_args:
                continue

        elif op in effect_registry:
            # primitive と同様に、effect 側も op ごとに meta keys をキャッシュする。
            known_args = effect_known_args_by_op.get(op)
            if known_args is None:
                known_args = set(effect_registry.get_meta(op).keys())
                effect_known_args_by_op[op] = known_args
            if arg in known_args:
                continue

        else:
            # op が未登録なら、削除せず残す（プラグイン未ロード等の可能性がある）。
            continue

        # op は登録済みだが arg は未知、というケースなのでストアから消す。
        removed.append(key)
        store._states.pop(key, None)
        store._meta.pop(key, None)
        store._explicit_by_key.pop(key, None)

    return removed


def prune_groups(store: ParamStore, groups_to_remove: Iterable[GroupKey]) -> None:
    """指定された `(op, site_id)` グループをストアから削除する。

    Parameters
    ----------
    store : ParamStore
        対象の `ParamStore`。
    groups_to_remove : Iterable[GroupKey]
        削除対象の `(op, site_id)` の反復可能。

    Notes
    -----
    - parameter の実体（`_states` / `_meta` / `_explicit_by_key`）だけでなく、
      GUI/実行系が参照する周辺状態（labels/ordinals/effects/collapsed/runtime）も同期して削除する。
    """

    # GroupKey が str 以外（Enum 的な wrapper 等）でも一致判定できるよう、文字列に正規化する。
    groups = {(str(op), str(site_id)) for op, site_id in groups_to_remove}
    if not groups:
        return

    runtime = store._runtime_ref()
    labels = store._labels_ref()
    ordinals = store._ordinals_ref()
    effects = store._effects_ref()
    collapsed = store._collapsed_headers_ref()
    chain_ids_before = set(effects.chain_ordinals().keys())

    affected_ops: set[str] = set()

    # 走査中に dict を削除するため、keys() を list 化してから回す。
    for key in list(store._states.keys()):
        if (str(key.op), str(key.site_id)) in groups:
            del store._states[key]
    for key in list(store._meta.keys()):
        if (str(key.op), str(key.site_id)) in groups:
            del store._meta[key]
    for key in list(store._explicit_by_key.keys()):
        if (str(key.op), str(key.site_id)) in groups:
            del store._explicit_by_key[key]

    # 表示ラベルは parameter の有無とは独立に残ってしまうので、グループ単位で明示削除する。
    for op, site_id in groups:
        labels.delete(op, site_id)

    # ordinals/effects/collapsed/runtime は「グループの存在」を前提にした情報なのでまとめて消す。
    for op, site_id in groups:
        affected_ops.add(str(op))
        ordinals.delete(op, site_id)
        effects.delete_step(op, site_id)
        collapsed.discard(f"primitive:{op}:{site_id}")
        runtime.loaded_groups.discard((str(op), str(site_id)))
        runtime.observed_groups.discard((str(op), str(site_id)))

    # 同じ op の中で site_id が間引かれると ordinal に穴が空くので、op 単位で詰め直す。
    for op in affected_ops:
        ordinals.compact(op)

    # ステップ削除の結果、参照されなくなった effect chain を落とす。
    effects.prune_unused_chains()
    chain_ids_after = set(effects.chain_ordinals().keys())
    # 消えた chain に対応する collapsed 状態も取り除き、UI 側にゴミが残らないようにする。
    for removed_chain_id in chain_ids_before - chain_ids_after:
        collapsed.discard(f"effect_chain:{removed_chain_id}")


__all__ = ["prune_stale_loaded_groups", "prune_unknown_args_in_known_ops", "prune_groups"]
