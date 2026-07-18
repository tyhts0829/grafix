# どこで: `src/grafix/core/parameters/store.py`。
# 何を: ParamStore（永続データの核）を定義する。
# なぜ: God-object 化を避け、周辺ロジック（ordinal/reconcile/永続化など）を別モジュールへ分離するため。

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator, MutableSet
from typing import TYPE_CHECKING, Any

from .effects import EffectChainIndex
from .key import ParameterKey
from .labels import ParamLabels
from .meta import ParamMeta
from .ordinals import GroupOrdinals
from .runtime import LoadProvenance, ParamStoreLoadDiagnostic, ParamStoreRuntime
from .state import ParamState

if TYPE_CHECKING:
    from .variations import Variation


class _FavoriteKeySet(MutableSet[ParameterKey]):
    """favorite mutation を store revision へ接続する mutable view。"""

    __slots__ = ("_store",)

    def __init__(self, store: ParamStore) -> None:
        self._store = store

    def __contains__(self, key: object) -> bool:
        return key in self._store._favorite_keys_data

    def __iter__(self) -> Iterator[ParameterKey]:
        return iter(self._store._favorite_keys_data)

    def __len__(self) -> int:
        return len(self._store._favorite_keys_data)

    def add(self, key: ParameterKey) -> None:
        data = self._store._favorite_keys_data
        if key in data:
            return
        data.add(key)
        self._store._touch_favorites()

    def discard(self, key: ParameterKey) -> None:
        data = self._store._favorite_keys_data
        if key not in data:
            return
        data.discard(key)
        self._store._touch_favorites()


class ParamStore:
    """ParameterKey -> ParamState を保持する永続ストア。

    Notes
    -----
    - このクラスは「永続データの入れ物」に寄せる。
    - parameter lock / favorite は永続 UI state として保持する。
    - 外部へはミュータブルな参照（ParamState）を渡さない。
      変更は ops 経由で行う想定とする。
    """

    def __init__(self) -> None:
        self._states: dict[ParameterKey, ParamState] = {}
        self._meta: dict[ParameterKey, ParamMeta] = {}
        self._explicit_by_key: dict[ParameterKey, bool] = {}

        self._labels = ParamLabels()
        self._ordinals = GroupOrdinals()
        self._effects = EffectChainIndex()
        self._collapsed_headers: set[str] = set()
        self._locked_keys: set[ParameterKey] = set()
        self._favorite_keys_data: set[ParameterKey] = set()
        self._variations: dict[str, Variation] = {}

        # 永続化しない実行時情報（loaded/observed/reconcile-applied）。
        self._runtime = ParamStoreRuntime()
        self._revision = 0
        self._table_revision = 0
        self._value_revision = 0
        self._style_revision = 0
        self._favorite_revision = 0
        self._favorite_snapshot_revision = -1
        self._favorite_snapshot: frozenset[ParameterKey] = frozenset()
        self._favorite_tuple: tuple[ParameterKey, ...] = ()
        self._value_change_log: deque[tuple[int, tuple[ParameterKey, ...]]] = deque(
            maxlen=4096
        )
        self._history_key_observer: Callable[[ParameterKey], None] | None = None
        self._history_headers_observer: (
            Callable[[frozenset[str] | None], None] | None
        ) = None
        self._snapshot_cache_revision = -1
        self._snapshot_cache_value_revision = -1
        self._snapshot_cache_rebuilt_entries = 0
        self._snapshot_cache: object | None = None

    @property
    def revision(self) -> int:
        """snapshot/model に影響する永続状態の変更時だけ増える単調 revision。"""

        return self._revision

    @property
    def table_revision(self) -> int:
        """Parameter GUI の行構造・静的属性が変わったときだけ増える revision。"""

        return self._table_revision

    @property
    def value_revision(self) -> int:
        """既存 parameter の表示値が変わったときだけ増える revision。"""

        return self._value_revision

    @property
    def style_revision(self) -> int:
        """global/layer style の値または関連し得る構造が変わる revision。"""

        return self._style_revision

    @property
    def favorite_revision(self) -> int:
        """favorite 集合が変化したときだけ増える単調 revision。"""

        return self._favorite_revision

    @property
    def _favorite_keys(self) -> set[ParameterKey]:
        """既存の recovery 境界向けに raw favorite set を返す。"""

        return self._favorite_keys_data

    @_favorite_keys.setter
    def _favorite_keys(self, keys: Iterable[ParameterKey]) -> None:
        self._replace_favorite_keys(keys)

    def _replace_favorite_keys(self, keys: Iterable[ParameterKey]) -> bool:
        """favorite 集合を置換し、変更時だけ revision を一度進める。"""

        normalized = set(keys)
        if normalized == self._favorite_keys_data:
            return False
        self._favorite_keys_data = normalized
        self._touch_favorites()
        return True

    @property
    def load_provenance(self) -> LoadProvenance:
        """現在のデータを復元した load 経路を返す。"""

        return self._runtime.load_provenance

    @property
    def load_diagnostics(self) -> tuple[ParamStoreLoadDiagnostic, ...]:
        """load 中の migration/quarantine 診断を返す。"""

        return self._runtime.load_diagnostics

    def get_state(self, key: ParameterKey) -> ParamState | None:
        """登録済みの ParamState を返す。未登録なら None。"""

        state = self._states.get(key)
        if state is None:
            return None
        return ParamState(**vars(state))

    def get_meta(self, key: ParameterKey) -> ParamMeta | None:
        """登録済みの ParamMeta を返す。未登録なら None。"""

        return self._meta.get(key)

    def get_label(self, op: str, site_id: str) -> str | None:
        """(op, site_id) のラベルを返す。未登録なら None。"""

        return self._labels.get(op, site_id)

    def get_ordinal(self, op: str, site_id: str) -> int | None:
        """(op, site_id) の ordinal を返す。未登録なら None。"""

        return self._ordinals.get(op, site_id)

    def get_effect_step(self, op: str, site_id: str) -> tuple[str, int] | None:
        """(op, site_id) の effect ステップ情報を返す。未登録なら None。"""

        return self._effects.get_step(op, site_id)

    def effect_steps(self) -> dict[tuple[str, str], tuple[str, int]]:
        """(op, site_id) -> (chain_id, step_index) のコピーを返す。"""

        return self._effects.step_info_by_site()

    def chain_ordinals(self) -> dict[str, int]:
        """chain_id -> ordinal のコピーを返す。"""

        return self._effects.chain_ordinals()

    # --- 内部 API（ops/codec からのみ利用する想定）---
    def _get_state_ref(self, key: ParameterKey) -> ParamState | None:
        return self._states.get(key)

    def _ensure_state(
        self,
        key: ParameterKey,
        *,
        base_value: Any,
        initial_override: bool | None = None,
    ) -> ParamState:
        """ParamState を確保し、無ければ base_value で初期化して返す。"""

        state = self._states.get(key)
        if state is not None:
            return state

        self._observe_history_key_before(key)
        state = ParamState(ui_value=base_value)
        if initial_override is not None:
            state.override = bool(initial_override)
        self._states[key] = state
        self._touch()
        return state

    def _get_meta_ref(self, key: ParameterKey) -> ParamMeta | None:
        return self._meta.get(key)

    def _set_meta(self, key: ParameterKey, meta: ParamMeta) -> None:
        if self._meta.get(key) == meta:
            return
        self._observe_history_key_before(key)
        self._meta[key] = meta
        self._touch()

    def _get_explicit_ref(self, key: ParameterKey) -> bool | None:
        return self._explicit_by_key.get(key)

    def _set_explicit(self, key: ParameterKey, value: bool) -> None:
        normalized = bool(value)
        if self._explicit_by_key.get(key) == normalized:
            return
        self._explicit_by_key[key] = normalized
        self._touch()

    def _labels_ref(self) -> ParamLabels:
        return self._labels

    def _ordinals_ref(self) -> GroupOrdinals:
        return self._ordinals

    def _effects_ref(self) -> EffectChainIndex:
        return self._effects

    def _collapsed_headers_ref(self) -> set[str]:
        return self._collapsed_headers

    def _locked_keys_ref(self) -> set[ParameterKey]:
        return self._locked_keys

    def _favorite_keys_ref(self) -> MutableSet[ParameterKey]:
        # self 参照を永続属性に置くと exact-store deepcopy/restore の所有権が
        # 壊れるため、mutation 境界でだけ lightweight view を作る。
        return _FavoriteKeySet(self)

    def _favorite_keys_snapshot(self) -> frozenset[ParameterKey]:
        """revision 内で同一 identity の immutable favorite 集合を返す。"""

        if self._favorite_snapshot_revision != self._favorite_revision:
            snapshot = frozenset(self._favorite_keys_data)
            self._favorite_snapshot = snapshot
            self._favorite_tuple = tuple(
                sorted(
                    snapshot,
                    key=lambda key: (key.op, key.site_id, key.arg),
                )
            )
            self._favorite_snapshot_revision = self._favorite_revision
        return self._favorite_snapshot

    def _favorite_keys_tuple(self) -> tuple[ParameterKey, ...]:
        self._favorite_keys_snapshot()
        return self._favorite_tuple

    def _variations_ref(self) -> dict[str, Variation]:
        return self._variations

    def _runtime_ref(self) -> ParamStoreRuntime:
        return self._runtime

    def _touch(
        self,
        *,
        structure: bool = True,
        value_keys: Iterable[ParameterKey] = (),
    ) -> None:
        """永続 revision と用途別 revision を一度に更新する。

        ``structure=False`` は、既存行の値だけが変わる hot path でのみ使う。
        呼び出し側が指定を忘れた場合は静的モデルを再構築する安全側へ倒す。
        """

        changed_keys = tuple(dict.fromkeys(value_keys))
        self._revision += 1
        if structure:
            self._table_revision += 1
            # 構造変更には style parameter の追加・削除や復元も含まれる。
            # 呼び出し側が値 key を列挙できない bulk 経路でも、保持中 scene の
            # style overlay を取りこぼさないよう安全側へ倒す。
            self._style_revision += 1
        if changed_keys:
            self._value_revision += 1
            if not structure and any(
                key.op in {"__style__", "__layer_style__"}
                for key in changed_keys
            ):
                self._style_revision += 1
            self._value_change_log.append((self._value_revision, changed_keys))
        if structure:
            # label/meta/ordinal/entry cardinality が変わり得るため、value patch の
            # base としても使わない。value-only 変更では immutable な旧 snapshot
            # を次回差分構築の seed として保持する。
            self._snapshot_cache = None
            self._snapshot_cache_revision = -1
            self._snapshot_cache_value_revision = -1
        elif (
            not changed_keys
            and self._snapshot_cache is not None
            and self._snapshot_cache_value_revision == self._value_revision
        ):
            # collapse state など ParamSnapshot に含まれない変更では、同じ
            # immutable mapping をそのまま現 revision の cache として扱える。
            self._snapshot_cache_revision = self._revision

    def _touch_favorites(self) -> None:
        """favorite overlay と永続保存だけを無効化する。"""

        self._revision += 1
        self._favorite_revision += 1
        self._favorite_snapshot_revision = -1
        # favorite は ParamSnapshot entry に含まれない。既存 snapshot の identity
        # を保ち、Parameter GUI 側の favorite revision だけを無効化する。
        if (
            self._snapshot_cache is not None
            and self._snapshot_cache_value_revision == self._value_revision
        ):
            self._snapshot_cache_revision = self._revision

    def value_changes_since(
        self,
        revision: int,
    ) -> frozenset[ParameterKey] | None:
        """指定 value revision 以降の key を返す。log 欠落時は ``None``。"""

        since = int(revision)
        if since == self._value_revision:
            return frozenset()
        if since < 0 or since > self._value_revision:
            return None
        if not self._value_change_log:
            return None
        first_revision = self._value_change_log[0][0]
        if since < first_revision - 1:
            return None
        changed: set[ParameterKey] = set()
        for change_revision, keys in reversed(self._value_change_log):
            if change_revision <= since:
                break
            changed.update(keys)
        return frozenset(changed)

    def _begin_history_patch_capture(
        self,
        *,
        observe_key: Callable[[ParameterKey], None],
        observe_headers: Callable[[frozenset[str] | None], None],
    ) -> None:
        """単一 GUI transaction の変更前値 observer を登録する。"""

        if self._history_key_observer is not None:
            raise RuntimeError("history patch capture is already active")
        self._history_key_observer = observe_key
        self._history_headers_observer = observe_headers

    def _end_history_patch_capture(self) -> None:
        """現在の GUI transaction observer を解除する。"""

        self._history_key_observer = None
        self._history_headers_observer = None

    def _observe_history_key_before(self, key: ParameterKey) -> None:
        observer = self._history_key_observer
        if observer is not None:
            observer(key)

    def _observe_history_headers_before(
        self,
        headers: frozenset[str] | None = None,
    ) -> None:
        observer = self._history_headers_observer
        if observer is not None:
            observer(headers)

    def _get_snapshot_cache(self) -> object | None:
        if self._snapshot_cache_revision != self._revision:
            return None
        return self._snapshot_cache

    def _get_snapshot_cache_seed(self) -> tuple[object, int] | None:
        """structure change 以降の immutable snapshot と value revision を返す。"""

        snapshot = self._snapshot_cache
        if snapshot is None or self._snapshot_cache_value_revision < 0:
            return None
        return snapshot, self._snapshot_cache_value_revision

    def _set_snapshot_cache(
        self,
        snapshot: object,
        *,
        rebuilt_entries: int,
    ) -> None:
        self._snapshot_cache = snapshot
        self._snapshot_cache_revision = self._revision
        self._snapshot_cache_value_revision = self._value_revision
        self._snapshot_cache_rebuilt_entries = int(rebuilt_entries)


__all__ = ["ParamStore"]
