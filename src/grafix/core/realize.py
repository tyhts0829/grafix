"""Geometry DAG の評価とセッション単位の bounded cache を提供する。"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from grafix.core.builtins import (
    ensure_builtin_effect_registered,
    ensure_builtin_primitive_registered,
)
from grafix.core.effect_registry import effect_registry
from grafix.core.geometry import Geometry, GeometryId
from grafix.core.operation_diagnostics import emit_operation_diagnostic
from grafix.core.primitive_registry import primitive_registry
from grafix.core.realized_geometry import RealizedGeometry, concat_realized_geometries
from grafix.core.resource_budget import (
    DEFAULT_RESOURCE_BUDGET,
    ResourceBudget,
    ensure_geometry_output,
    resource_budget_context,
)
from grafix.core.runtime_limits import (
    DEFAULT_CPU_CACHE_BYTES,
    RuntimeLimits,
)

RegistryRevision: TypeAlias = tuple[int, int]
"""``(primitive revision, effect revision)`` のスナップショット。"""

GeometryCacheKey: TypeAlias = tuple[GeometryId, RegistryRevision]
"""CPU/GPU cache で共有する、operation 実装の世代を含むキー。"""

DEFAULT_MAX_CACHE_BYTES = DEFAULT_CPU_CACHE_BYTES
_MAX_PREPARED_GEOMETRIES = 4096


class PerformanceRecorder(Protocol):
    """RealizeSession が依存する最小 performance 記録契約。"""

    enabled: bool

    def record_operation(self, name: str, elapsed_ns: int) -> None: ...

    def record_layer(self, name: str, elapsed_ns: int) -> None: ...

    def record_cache(
        self,
        *,
        hits: int = 0,
        misses: int = 0,
        evictions: int = 0,
    ) -> None: ...


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


@dataclass(slots=True)
class _CacheTransaction:
    """scene aggregate 検査が通るまで新しい CPU cache entry を保持する。"""

    entries: OrderedDict[GeometryCacheKey, RealizedGeometry]
    commit_requested: bool = False

    def commit(self) -> None:
        self.commit_requested = True


def current_registry_revision() -> RegistryRevision:
    """現在の primitive/effect registry revision を返す。"""

    return primitive_registry.revision, effect_registry.revision


class RealizeSession:
    """Geometry の評価結果を byte 上限付きで再利用するセッション。

    Parameters
    ----------
    max_cache_bytes : int, optional
        cache に保持する配列の合計 byte 上限。0 は cache を無効化する。
    resource_budget : ResourceBudget, optional
        各 operation が大規模配列を確保する前に適用する頂点・線・byte 上限。
    profiler : PerformanceRecorder or None, optional
        operation/layer/cache の実測値を受け取る recorder。

    Notes
    -----
    cache と inflight coordinator は同じ lock で管理する。同一 key の同時評価は
    先行する 1 スレッドだけが実行し、残りはその結果を共有する。
    """

    def __init__(
        self,
        *,
        max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
        runtime_limits: RuntimeLimits | None = None,
        profiler: PerformanceRecorder | None = None,
    ) -> None:
        if runtime_limits is not None:
            if not isinstance(runtime_limits, RuntimeLimits):
                raise TypeError("runtime_limits は RuntimeLimits である必要がある")
            max_cache_bytes = int(runtime_limits.cpu_cache_bytes)
            resource_budget = runtime_limits.per_operation
        max_bytes = int(max_cache_bytes)
        if max_bytes < 0:
            raise ValueError("max_cache_bytes は 0 以上である必要がある")
        if not isinstance(resource_budget, ResourceBudget):
            raise TypeError("resource_budget は ResourceBudget である必要がある")

        self._max_cache_bytes = max_bytes
        self._resource_budget = resource_budget
        self._runtime_limits = (
            runtime_limits
            if runtime_limits is not None
            else RuntimeLimits(
                per_operation=resource_budget,
                scene=resource_budget,
                cpu_cache_bytes=max_bytes,
            )
        )
        self._profiler = profiler
        self._lock = threading.Lock()
        self._cache_transaction_local = threading.local()
        self._cache: OrderedDict[GeometryCacheKey, RealizedGeometry] = OrderedDict()
        self._cache_bytes = 0
        self._inflight: dict[GeometryCacheKey, _InflightEntry] = {}
        self._prepared_geometries: OrderedDict[GeometryId, None] = OrderedDict()
        self._cacheability: OrderedDict[GeometryCacheKey, bool] = OrderedDict()
        self._uncached_generation = 0
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

    @property
    def resource_budget(self) -> ResourceBudget:
        """operation の配列確保前検査に使う resource budget を返す。"""

        return self._resource_budget

    @property
    def runtime_limits(self) -> RuntimeLimits:
        """この session の operation/scene/cache 上限を返す。"""

        return self._runtime_limits

    @contextlib.contextmanager
    def cache_transaction(self) -> Iterator[_CacheTransaction]:
        """scene 検査成功まで新規 cache 書込みを遅延する。"""

        if getattr(self._cache_transaction_local, "current", None) is not None:
            raise RuntimeError("cache transaction は入れ子にできません")
        transaction = _CacheTransaction(entries=OrderedDict())
        self._cache_transaction_local.current = transaction
        try:
            yield transaction
        finally:
            del self._cache_transaction_local.current
            if transaction.commit_requested:
                with self._lock:
                    if not self._closed:
                        for key, result in transaction.entries.items():
                            self._store_cache_entry_locked(key, result)

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

    @contextlib.contextmanager
    def profile_layer(self, name: str) -> Iterator[None]:
        """1 layer の resolve/realize 区間を profiler へ記録する。"""

        profiler = self._profiler
        if profiler is None or not profiler.enabled:
            yield
            return
        started_ns = time.perf_counter_ns()
        try:
            yield
        finally:
            profiler.record_layer(str(name), time.perf_counter_ns() - started_ns)

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
            self._cacheability.clear()

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
        cacheable = self._is_geometry_cacheable(geometry, revision)
        result = self._realize(geometry, revision)
        if cacheable:
            key = (geometry.id, revision)
        else:
            # GPU mesh cacheにも毎評価を別内容として伝え、stateful outputを固定しない。
            with self._lock:
                self._uncached_generation += 1
                generation = self._uncached_generation
            key = (f"{geometry.id}:uncached:{generation}", revision)
        return result, key

    def _is_geometry_cacheable(
        self,
        geometry: Geometry,
        revision: RegistryRevision,
    ) -> bool:
        """node自身と全入力がcontent cache契約かを返す。"""

        key = (geometry.id, revision)
        with self._lock:
            cached = self._cacheability.get(key)
            if cached is not None:
                self._cacheability.move_to_end(key)
                return cached

        if geometry.op == "concat":
            cacheable = all(
                self._is_geometry_cacheable(item, revision) for item in geometry.inputs
            )
        elif geometry.inputs:
            spec = effect_registry[geometry.op]
            cacheable = spec.cache_policy == "content" and all(
                self._is_geometry_cacheable(item, revision) for item in geometry.inputs
            )
        else:
            cacheable = primitive_registry[geometry.op].cache_policy == "content"

        with self._lock:
            self._cacheability.pop(key, None)
            self._cacheability[key] = cacheable
            while len(self._cacheability) > _MAX_PREPARED_GEOMETRIES:
                self._cacheability.popitem(last=False)
        return cacheable

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

        if not self._is_geometry_cacheable(geometry, revision):
            with self._lock:
                self._misses += 1
                self._record_cache(misses=1)
            try:
                return self._evaluate_geometry_node(geometry, revision)
            except BaseException as uncached_error:  # noqa: BLE001
                if not isinstance(uncached_error, Exception):
                    raise
                raise RealizeError(
                    f"Geometry の評価に失敗した: id={geometry.id}"
                ) from uncached_error

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
                self._record_cache(misses=1)
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
        transaction = getattr(self._cache_transaction_local, "current", None)
        if transaction is not None:
            staged = transaction.entries.get(key)
            if staged is not None:
                transaction.entries.move_to_end(key)
                self._hits += 1
                self._record_cache(hits=1)
                return staged
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self._hits += 1
            self._record_cache(hits=1)
        return cached

    def _record_cache(
        self,
        *,
        hits: int = 0,
        misses: int = 0,
        evictions: int = 0,
    ) -> None:
        """既存 cache stats と同じ差分を任意 profiler へ転送する。"""

        profiler = self._profiler
        if profiler is not None and profiler.enabled:
            profiler.record_cache(
                hits=int(hits),
                misses=int(misses),
                evictions=int(evictions),
            )

    @contextlib.contextmanager
    def _profile_operation(self, op: str) -> Iterator[None]:
        """入力 DAG 評価を除く operation evaluator 区間を記録する。"""

        profiler = self._profiler
        if profiler is None or not profiler.enabled:
            yield
            return
        started_ns = time.perf_counter_ns()
        try:
            yield
        finally:
            profiler.record_operation(str(op), time.perf_counter_ns() - started_ns)

    def _evaluate_geometry_node(
        self,
        geometry: Geometry,
        revision: RegistryRevision,
    ) -> RealizedGeometry:
        op = geometry.op
        with resource_budget_context(self._resource_budget):
            if op == "concat":
                realized_inputs = [self._realize(item, revision) for item in geometry.inputs]

                def evaluate() -> RealizedGeometry:
                    ensure_geometry_output(
                        "concat",
                        vertices=sum(
                            int(item.coords.shape[0]) for item in realized_inputs
                        ),
                        lines=sum(
                            max(0, int(item.offsets.size) - 1)
                            for item in realized_inputs
                        ),
                        hint="入力 geometry または concat 対象数を減らしてください",
                    )
                    return concat_realized_geometries(*realized_inputs)

            elif not geometry.inputs:
                if op not in primitive_registry:
                    ensure_builtin_primitive_registered(op)
                primitive_spec = primitive_registry[op]

                def evaluate() -> RealizedGeometry:
                    return primitive_spec.evaluator(geometry.args)

            else:
                realized_inputs = [self._realize(item, revision) for item in geometry.inputs]
                if op not in effect_registry:
                    ensure_builtin_effect_registered(op)
                effect_spec = effect_registry[op]

                def evaluate() -> RealizedGeometry:
                    return effect_spec.evaluator(realized_inputs, geometry.args)

            # 組み込み operation の事前見積もりに加え、すべての evaluator 出力を
            # cache 投入前に検査する。これにより、事前検査を実装していない custom
            # primitive/effect も同じ session budget に従う。
            with self._profile_operation(op):
                result = evaluate()
                ensure_geometry_output(
                    op,
                    vertices=int(result.coords.shape[0]),
                    lines=max(0, int(result.offsets.size) - 1),
                    hint="operation の入力または出力パラメータを減らしてください",
                )
                return result

    def _store_locked(self, key: GeometryCacheKey, result: RealizedGeometry) -> None:
        transaction = getattr(self._cache_transaction_local, "current", None)
        if transaction is not None:
            transaction.entries.pop(key, None)
            transaction.entries[key] = result
            return
        self._store_cache_entry_locked(key, result)

    def _store_cache_entry_locked(
        self,
        key: GeometryCacheKey,
        result: RealizedGeometry,
    ) -> None:
        size = result.byte_size
        if size > self._max_cache_bytes:
            emit_operation_diagnostic(
                op="runtime.cpu_cache",
                original_value=size,
                effective_value=self._max_cache_bytes,
                reason="result exceeded the CPU cache limit and was not cached",
                severity="warning",
            )
            return

        previous = self._cache.pop(key, None)
        if previous is not None:
            self._cache_bytes -= previous.byte_size

        projected_bytes = self._cache_bytes + size
        evicted_count = 0
        while self._cache and self._cache_bytes + size > self._max_cache_bytes:
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= evicted.byte_size
            self._evictions += 1
            evicted_count += 1

        if evicted_count:
            self._record_cache(evictions=evicted_count)

        if evicted_count:
            emit_operation_diagnostic(
                op="runtime.cpu_cache",
                original_value=projected_bytes,
                effective_value=self._max_cache_bytes,
                reason=f"CPU cache limit evicted {evicted_count} entrie(s)",
                severity="info",
            )

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
    "PerformanceRecorder",
    "RealizeError",
    "RealizeSession",
    "RegistryRevision",
    "current_registry_revision",
    "realize",
]
