# どこで: `src/grafix/core/parameters/history.py`。
# 何を: ParamStore 用の bounded Undo/Redo と A/B スナップショットを提供する。
# なぜ: 試行錯誤を壊さず、調整案を安心して比較できるようにするため。

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from typing import Literal

from .memento import (
    ParamStoreMemento,
    capture_param_store_memento,
    param_store_memento_matches,
    restore_param_store_memento,
)
from .store import ParamStore

SnapshotSlot = Literal["A", "B"]
_SNAPSHOT_SLOTS: tuple[SnapshotSlot, SnapshotSlot] = ("A", "B")


class ParamStoreHistory:
    """ParamStore の変更履歴。

    ``record_change`` は変更後に呼ぶ簡易 API。フレーム内で store が
    別用途でも変更される UI では、変更前を確実に捕まえる
    ``transaction`` を推奨する。
    """

    def __init__(
        self,
        store: ParamStore,
        *,
        capacity: int = 100,
        coalesce_seconds: float = 0.35,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if coalesce_seconds < 0.0:
            raise ValueError("coalesce_seconds must be >= 0")

        self._store = store
        self._capacity = int(capacity)
        self._coalesce_seconds = float(coalesce_seconds)
        self._clock = clock
        self._undo: deque[ParamStoreMemento] = deque(maxlen=self._capacity)
        self._redo: deque[ParamStoreMemento] = deque(maxlen=self._capacity)
        self._current = capture_param_store_memento(store)
        self._seen_revision = store.revision
        self._last_source: Hashable | None = None
        self._last_change_at: float | None = None

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    def synchronize(self, *, clear_history: bool = False) -> bool:
        """現在状態を履歴の基準にし、未記録の変更を Undo 対象にしない。

        draw によるパラメータ発見など、ユーザー操作以外の変更を
        GUI トランザクションの前に取り込む用途を想定する。
        """

        if self._store.revision == self._seen_revision and not clear_history:
            return False
        self._current = capture_param_store_memento(self._store)
        self._seen_revision = self._store.revision
        self._redo.clear()
        if clear_history:
            self._undo.clear()
        self.break_coalescing()
        return True

    def record_change(
        self,
        *,
        source: Hashable,
        now: float | None = None,
    ) -> bool:
        """直前の基準から現在までの変更を 1 操作として記録する。"""

        if self._store.revision == self._seen_revision:
            return False
        before = self._current
        after = capture_param_store_memento(self._store)
        return self._record_transition(
            before=before,
            after=after,
            source=source,
            now=self._clock() if now is None else float(now),
        )

    @contextmanager
    def transaction(
        self,
        *,
        source: Hashable,
        now: float | None = None,
    ) -> Iterator[None]:
        """ブロック内の store 変更を 1 操作として記録する。

        ブロック開始時の未記録変更は基準に取り込む。そのため、
        初回 draw の parameter discovery を Undo で消してしまわない。
        """

        if self._store.revision != self._seen_revision:
            self.synchronize()
        before_revision = self._store.revision
        before = self._current
        try:
            yield
        finally:
            if self._store.revision != before_revision:
                after = capture_param_store_memento(self._store)
                self._record_transition(
                    before=before,
                    after=after,
                    source=source,
                    now=self._clock() if now is None else float(now),
                )

    def undo(self) -> bool:
        """直前の記録済み操作を戻す。履歴が無ければ False。"""

        self._adopt_untracked_state()
        if not self._undo:
            return False
        target = self._undo.pop()
        self._redo.append(self._current)
        changed = restore_param_store_memento(self._store, target)
        # merge restore 後の store には、target 作成後に発見された
        # parameter も残る。次の履歴基準は target そのものではなく、
        # 実際に復元された現在状態から再 capture する。
        self._current = capture_param_store_memento(self._store)
        self._seen_revision = self._store.revision
        self.break_coalescing()
        return changed

    def redo(self) -> bool:
        """直前に Undo した操作を再適用する。履歴が無ければ False。"""

        self._adopt_untracked_state()
        if not self._redo:
            return False
        target = self._redo.pop()
        self._undo.append(self._current)
        changed = restore_param_store_memento(self._store, target)
        self._current = capture_param_store_memento(self._store)
        self._seen_revision = self._store.revision
        self.break_coalescing()
        return changed

    def clear(self) -> None:
        """履歴を消去し、現在状態を新しい基準にする。"""

        self.synchronize(clear_history=True)

    def break_coalescing(self) -> None:
        """次の変更を、直前とは別の Undo 単位にする。"""

        self._last_source = None
        self._last_change_at = None

    def _record_transition(
        self,
        *,
        before: ParamStoreMemento,
        after: ParamStoreMemento,
        source: Hashable,
        now: float,
    ) -> bool:
        # revision は label/ordinal など code-owned 構造でも進む。
        # GUI-owned 状態に実差分が無い場合は Undo を増やさない。
        if param_store_memento_matches(self._store, before):
            self._current = after
            self._seen_revision = self._store.revision
            return False

        last_at = self._last_change_at
        should_coalesce = (
            bool(self._undo)
            and self._last_source == source
            and last_at is not None
            and 0.0 <= now - last_at <= self._coalesce_seconds
        )
        if not should_coalesce:
            self._undo.append(before)
        self._redo.clear()
        self._current = after
        self._seen_revision = self._store.revision
        self._last_source = source
        self._last_change_at = now
        return True

    def _adopt_untracked_state(self) -> None:
        if self._store.revision == self._seen_revision:
            return
        # 履歴外の分岐後に古い redo を適用すると、新規に発見した
        # metadata まで消し得る。現在を基準にし、redo は捨てる。
        self._current = capture_param_store_memento(self._store)
        self._seen_revision = self._store.revision
        self._redo.clear()
        self.break_coalescing()


class ParamSnapshotSlots:
    """A/B の 2 スロットに ParamStore の調整案を保存する。"""

    def __init__(self, store: ParamStore) -> None:
        self._store = store
        self._slots: dict[SnapshotSlot, ParamStoreMemento] = {}

    @property
    def available_slots(self) -> tuple[SnapshotSlot, ...]:
        return tuple(slot for slot in _SNAPSHOT_SLOTS if slot in self._slots)

    def has(self, slot: SnapshotSlot) -> bool:
        self._validate_slot(slot)
        return slot in self._slots

    def capture(self, slot: SnapshotSlot) -> None:
        """現在状態を slot へ保存する（既存値は上書き）。"""

        self._validate_slot(slot)
        self._slots[slot] = capture_param_store_memento(self._store)

    def restore(self, slot: SnapshotSlot) -> bool:
        """slot を store へ merge 適用する。未保存/同一状態なら False。"""

        self._validate_slot(slot)
        memento = self._slots.get(slot)
        if memento is None:
            return False
        return restore_param_store_memento(self._store, memento)

    def clear(self, slot: SnapshotSlot | None = None) -> None:
        """1 スロット、または A/B 両方を消去する。"""

        if slot is None:
            self._slots.clear()
            return
        self._validate_slot(slot)
        self._slots.pop(slot, None)

    @staticmethod
    def _validate_slot(slot: object) -> None:
        if slot != "A" and slot != "B":
            raise ValueError("snapshot slot must be 'A' or 'B'")


__all__ = ["ParamStoreHistory", "ParamSnapshotSlots", "SnapshotSlot"]
