"""revision 単位で再利用する Parameter GUI の静的テーブルモデル。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeAlias
from weakref import WeakKeyDictionary

from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.snapshot_ops import ParamSnapshot, store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.view import ParameterRow

RegistryRevision: TypeAlias = tuple[int, int, int]
ParameterTableCacheKey: TypeAlias = tuple[int, RegistryRevision]


@dataclass(frozen=True, slots=True)
class ParameterTableModel:
    """store/registry revision にだけ依存する不変な表示構造。

    MIDI の最新値、effective 値、active/loaded 状態などフレームごとの動的値は
    意図的に含めない。呼び出し側が描画直前に合成することで、行の構築・分類・
    並べ替えを毎フレーム繰り返さずに済む。
    """

    cache_key: ParameterTableCacheKey
    value_revision: int
    snapshot: ParamSnapshot
    rows: tuple[ParameterRow, ...]
    row_index_by_key: Mapping[ParameterKey, int]
    raw_label_by_site: Mapping[tuple[str, str], str]
    primitive_header_by_group: Mapping[tuple[str, int], str]
    layer_style_name_by_site_id: Mapping[str, str]
    effect_chain_header_by_id: Mapping[str, str]
    step_info_by_site: Mapping[tuple[str, str], tuple[str, int]]
    effect_step_ordinal_by_site: Mapping[tuple[str, str], int]


ModelBuilder: TypeAlias = Callable[
    [ParamStore, ParamSnapshot, ParameterTableCacheKey], ParameterTableModel
]
ModelRefresher: TypeAlias = Callable[
    [ParamStore, ParameterTableModel, frozenset[ParameterKey]],
    ParameterTableModel,
]


class ParameterTableModelCache:
    """ParamStore ごとに直近 1 revision のモデルだけを保持する。"""

    def __init__(self) -> None:
        self._models: WeakKeyDictionary[ParamStore, ParameterTableModel] = (
            WeakKeyDictionary()
        )
        self._build_count = 0

    @property
    def build_count(self) -> int:
        """この cache がモデルを構築した回数を返す。"""

        return int(self._build_count)

    def get_or_build(
        self,
        store: ParamStore,
        *,
        registry_revision: RegistryRevision,
        builder: ModelBuilder,
        refresher: ModelRefresher,
    ) -> ParameterTableModel:
        """構造 revision が同じなら、変更 key の動的値だけを更新する。"""

        primitive_revision, effect_revision, preset_revision = registry_revision
        normalized_registry_revision: RegistryRevision = (
            int(primitive_revision),
            int(effect_revision),
            int(preset_revision),
        )
        cache_key: ParameterTableCacheKey = (
            int(store.table_revision),
            normalized_registry_revision,
        )
        cached = self._models.get(store)
        if cached is not None and cached.cache_key == cache_key:
            changed_keys = store.value_changes_since(cached.value_revision)
            if changed_keys is not None:
                if not changed_keys:
                    return cached
                refreshed = refresher(store, cached, changed_keys)
                self._models[store] = refreshed
                return refreshed

        model = builder(store, store_snapshot(store), cache_key)
        self._models[store] = model
        self._build_count += 1
        return model

    def clear(self) -> None:
        """全 store の cached model と計測値を破棄する。"""

        self._models.clear()
        self._build_count = 0


__all__ = [
    "ParameterTableCacheKey",
    "ParameterTableModel",
    "ParameterTableModelCache",
    "RegistryRevision",
]
