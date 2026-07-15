# どこで: `src/grafix/core/parameters/autosave.py`。
# 何を: debounce と最大保存間隔を持つ ParamStore autosave を提供する。
# なぜ: 書き込み回数を抑えつつ、連続操作中も recovery を定期確定するため。

from __future__ import annotations

import time
from collections.abc import Callable
from math import isfinite
from pathlib import Path

from .persistence import save_param_store
from .store import ParamStore

SaveParamStore = Callable[[ParamStore, Path], None]


class ParamStoreAutosave:
    """ParamStore を debounce 後、または最大保存間隔で atomic save する。"""

    def __init__(
        self,
        store: ParamStore,
        path: Path,
        *,
        debounce_seconds: float = 0.75,
        max_interval_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        save: SaveParamStore = save_param_store,
    ) -> None:
        if not isfinite(float(debounce_seconds)) or debounce_seconds < 0.0:
            raise ValueError("debounce_seconds must be finite and >= 0")
        if not isfinite(float(max_interval_seconds)) or max_interval_seconds <= 0.0:
            raise ValueError("max_interval_seconds must be finite and > 0")
        self._store = store
        self._path = Path(path)
        self._debounce_seconds = float(debounce_seconds)
        self._max_interval_seconds = float(max_interval_seconds)
        self._clock = clock
        self._save = save
        self._observed_revision = store.revision
        self._saved_revision = store.revision
        self._dirty_since: float | None = None
        self._first_dirty_at: float | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def dirty(self) -> bool:
        return self._store.revision != self._saved_revision

    @property
    def last_saved_revision(self) -> int:
        return self._saved_revision

    def tick(self, *, now: float | None = None) -> bool:
        """変更を観測し、debounce または最大間隔到達時に保存する。"""

        current_time = self._clock() if now is None else float(now)
        self._observe(current_time)
        if not self.dirty or self._dirty_since is None:
            return False
        settled = current_time - self._dirty_since >= self._debounce_seconds
        reached_max_interval = (
            self._first_dirty_at is not None
            and current_time - self._first_dirty_at >= self._max_interval_seconds
        )
        if not settled and not reached_max_interval:
            return False
        return self._save_now(retry_from=current_time)

    def flush(self) -> bool:
        """未保存の変更があれば、debounce を待たずに保存する。"""

        current_time = self._clock()
        self._observe(current_time)
        if not self.dirty:
            return False
        return self._save_now(retry_from=current_time)

    def mark_clean(self) -> None:
        """別経路で保存した現在状態を保存済みとして取り込む。"""

        self._observed_revision = self._store.revision
        self._saved_revision = self._store.revision
        self._dirty_since = None
        self._first_dirty_at = None

    def _observe(self, now: float) -> None:
        revision = self._store.revision
        if revision == self._observed_revision:
            return
        self._observed_revision = revision
        if self._first_dirty_at is None:
            self._first_dirty_at = now
        self._dirty_since = now

    def _save_now(self, *, retry_from: float) -> bool:
        try:
            # 既存 save_param_store が atomic write と保存前 cleanup を担当する。
            self._save(self._store, self._path)
        except Exception:
            # 毎 frame リトライする hot loop を避け、次の debounce 後に再試行する。
            self._observed_revision = self._store.revision
            self._dirty_since = retry_from
            self._first_dirty_at = retry_from
            raise
        self._observed_revision = self._store.revision
        self._saved_revision = self._store.revision
        self._dirty_since = None
        self._first_dirty_at = None
        return True


__all__ = ["ParamStoreAutosave", "SaveParamStore"]
