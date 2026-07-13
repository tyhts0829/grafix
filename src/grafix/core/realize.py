"""Geometry DAG の評価とセッション単位の bounded cache を提供する。"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TypeAlias

from grafix.core.builtins import (
    ensure_builtin_effect_registered,
    ensure_builtin_primitive_registered,
)
from grafix.core.effect_registry import effect_registry
from grafix.core.geometry import Geometry, GeometryId
from grafix.core.primitive_registry import primitive_registry
from grafix.core.realized_geometry import RealizedGeometry, concat_realized_geometries

RegistryRevision: TypeAlias = tuple[int, int]
"""``(primitive revision, effect revision)`` のスナップショット。"""

GeometryCacheKey: TypeAlias = tuple[GeometryId, RegistryRevision]
"""CPU/GPU cache で共有する、operation 実装の世代を含むキー。"""

DEFAULT_MAX_CACHE_BYTES = 256 * 1024 * 1024
_MAX_PREPARED_GEOMETRIES = 4096


class RealizeError(RuntimeError):
    """Geometry の評価中に発生した通常の失敗を表す。"""


@dataclass(frozen=True, slots=True)
class CacheStats:
    """RealizeSession の cache 統計スナップショット。"""

    hits: int
    misses: int
    evictions: int
    entries: int
    bytes: int


@dataclass(slots=True)
class _InflightEntry:
    """同じ cache key を評価するスレッド間で結果を受け渡す。"""

    condition: threading.Condition
    done: bool = False
    result: RealizedGeometry | None = None
    error: BaseException | None = None


def current_registry_revision() -> RegistryRevision:
    """現在の primitive/effect registry revision を返す。"""

    return primitive_registry.revision, effect_registry.revision


class RealizeSession:
    """Geometry の評価結果を byte 上限付きで再利用するセッション。

    Parameters
    ----------
    max_cache_bytes : int, optional
        cache に保持する配列の合計 byte 上限。0 は cache を無効化する。

    Notes
    -----
    cache と inflight coordinator は同じ lock で管理する。同一 key の同時評価は
    先行する 1 スレッドだけが実行し、残りはその結果を共有する。
    """

    def __init__(self, *, max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES) -> None:
        max_bytes = int(max_cache_bytes)
        if max_bytes < 0:
            raise ValueError("max_cache_bytes は 0 以上である必要がある")

        self._max_cache_bytes = max_bytes
        self._lock = threading.Lock()
        self._cache: OrderedDict[GeometryCacheKey, RealizedGeometry] = OrderedDict()
        self._cache_bytes = 0
        self._inflight: dict[GeometryCacheKey, _InflightEntry] = {}
        self._prepared_geometries: OrderedDict[GeometryId, None] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._closed = False

    def __enter__(self) -> RealizeSession:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @property
    def max_cache_bytes(self) -> int:
        """cache の byte 上限を返す。"""

        return self._max_cache_bytes

    def stats(self) -> CacheStats:
        """現在の cache 統計を lock 下で取得する。"""

        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                entries=len(self._cache),
                bytes=self._cache_bytes,
            )

    def clear(self) -> None:
        """完了済み cache を破棄する。進行中の評価は継続する。"""

        with self._lock:
            self._cache.clear()
            self._cache_bytes = 0

    def close(self) -> None:
        """新規評価を禁止し、完了済み cache を破棄する。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cache.clear()
            self._cache_bytes = 0
            self._prepared_geometries.clear()

    def realize(self, geometry: Geometry) -> RealizedGeometry:
        """Geometry を評価し、同一 key の結果をセッション内で再利用する。"""

        result, _ = self.realize_with_key(geometry)
        return result

    def realize_with_key(
        self,
        geometry: Geometry,
    ) -> tuple[RealizedGeometry, GeometryCacheKey]:
        """評価結果と、その評価に対応する cache key を返す。"""

        with self._lock:
            if self._closed:
                raise RuntimeError("close 済みの RealizeSession は使用できない")

        # lazy import による revision 増加を key の取得前に完了させる。
        self._ensure_geometry_ops_registered(geometry)
        revision = current_registry_revision()
        key = (geometry.id, revision)
        return self._realize(geometry, revision), key

    def _ensure_geometry_ops_registered(self, geometry: Geometry) -> None:
        """DAG が参照する組み込み operation を必要なものだけ import する。"""

        stack = [geometry]
        visited: set[GeometryId] = set()
        prepared_now: list[GeometryId] = []
        while stack:
            node = stack.pop()
            if node.id in visited:
                continue
            visited.add(node.id)

            with self._lock:
                already_prepared = node.id in self._prepared_geometries
                if already_prepared:
                    self._prepared_geometries.move_to_end(node.id)
            if already_prepared:
                continue

            if node.op != "concat":
                if node.inputs:
                    if node.op not in effect_registry:
                        ensure_builtin_effect_registered(node.op)
                elif node.op not in primitive_registry:
                    ensure_builtin_primitive_registered(node.op)
            prepared_now.append(node.id)
            stack.extend(node.inputs)

        with self._lock:
            if self._closed:
                return
            for geometry_id in prepared_now:
                self._prepared_geometries.pop(geometry_id, None)
                self._prepared_geometries[geometry_id] = None
            while len(self._prepared_geometries) > _MAX_PREPARED_GEOMETRIES:
                self._prepared_geometries.popitem(last=False)

    def _realize(
        self,
        geometry: Geometry,
        revision: RegistryRevision,
    ) -> RealizedGeometry:
        key = (geometry.id, revision)

        # cache fast path と coordinator の leader 選択を分け、leader 確定直前に
        # 同じ lock で再確認する。両区間の間に完了した計算を取りこぼさない。
        with self._lock:
            cached = self._get_cached_locked(key)
            if cached is not None:
                return cached

        with self._lock:
            cached = self._get_cached_locked(key)
            if cached is not None:
                return cached

            entry = self._inflight.get(key)
            if entry is None:
                entry = _InflightEntry(condition=threading.Condition(self._lock))
                self._inflight[key] = entry
                self._misses += 1
                is_leader = True
            else:
                is_leader = False

            if not is_leader:
                while not entry.done:
                    entry.condition.wait()
                if entry.error is not None:
                    if not isinstance(entry.error, Exception):
                        raise entry.error
                    raise RealizeError(
                        f"Geometry の評価に失敗した: id={geometry.id}"
                    ) from entry.error
                if entry.result is None:
                    raise RuntimeError("inflight entry に評価結果が設定されていない")
                return entry.result

        result: RealizedGeometry | None = None
        error: BaseException | None = None
        try:
            result = self._evaluate_geometry_node(geometry, revision)
        except BaseException as exc:  # noqa: BLE001
            error = exc
        finally:
            with self._lock:
                try:
                    if error is None and result is not None and not self._closed:
                        self._store_locked(key, result)
                except BaseException as exc:  # noqa: BLE001
                    result = None
                    error = exc
                finally:
                    completed = self._inflight.pop(key)
                    completed.result = result
                    completed.error = error
                    completed.done = True
                    completed.condition.notify_all()

        if error is not None:
            if not isinstance(error, Exception):
                raise error
            raise RealizeError(f"Geometry の評価に失敗した: id={geometry.id}") from error
        if result is None:
            raise RuntimeError("Geometry evaluator が結果を返さなかった")
        return result

    def _get_cached_locked(self, key: GeometryCacheKey) -> RealizedGeometry | None:
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self._hits += 1
        return cached

    def _evaluate_geometry_node(
        self,
        geometry: Geometry,
        revision: RegistryRevision,
    ) -> RealizedGeometry:
        op = geometry.op
        if op == "concat":
            realized_inputs = [self._realize(item, revision) for item in geometry.inputs]
            return concat_realized_geometries(*realized_inputs)

        if not geometry.inputs:
            if op not in primitive_registry:
                ensure_builtin_primitive_registered(op)
            primitive_spec = primitive_registry[op]
            return primitive_spec.evaluator(geometry.args)

        realized_inputs = [self._realize(item, revision) for item in geometry.inputs]
        if op not in effect_registry:
            ensure_builtin_effect_registered(op)
        effect_spec = effect_registry[op]
        return effect_spec.evaluator(realized_inputs, geometry.args)

    def _store_locked(self, key: GeometryCacheKey, result: RealizedGeometry) -> None:
        size = result.byte_size
        if size > self._max_cache_bytes:
            return

        previous = self._cache.pop(key, None)
        if previous is not None:
            self._cache_bytes -= previous.byte_size

        while self._cache and self._cache_bytes + size > self._max_cache_bytes:
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= evicted.byte_size
            self._evictions += 1

        self._cache[key] = result
        self._cache_bytes += size


def realize(
    geometry: Geometry,
    *,
    session: RealizeSession | None = None,
) -> RealizedGeometry:
    """Geometry を評価する。

    ``session`` を省略した呼び出しは一時セッションを所有する。複数回または複数
    layer 間で結果を再利用する場合は、明示的な :class:`RealizeSession` を渡す。
    """

    if session is not None:
        return session.realize(geometry)
    with RealizeSession() as owned_session:
        return owned_session.realize(geometry)


__all__ = [
    "CacheStats",
    "DEFAULT_MAX_CACHE_BYTES",
    "GeometryCacheKey",
    "RealizeError",
    "RealizeSession",
    "RegistryRevision",
    "current_registry_revision",
    "realize",
]
