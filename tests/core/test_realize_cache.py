"""RealizeSession の bounded LRU と inflight coordination をテストする。"""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Sequence
from typing import cast

import numpy as np
import pytest

from grafix.core.effect_registry import EffectFunc
from grafix.core.geometry import Geometry
from grafix.core.op_registry import OpRegistry, OpSpec
from grafix.core.primitive_registry import PrimitiveFunc
from grafix.core.realize import RealizeError, RealizeSession, realize
from grafix.core.realized_geometry import RealizedGeometry

realize_module = importlib.import_module("grafix.core.realize")


def _primitive_spec(evaluator: PrimitiveFunc) -> OpSpec[PrimitiveFunc]:
    return OpSpec(
        evaluator=evaluator,
        meta={},
        defaults={},
        param_order=(),
        ui_visible={},
        n_inputs=0,
        kind="primitive",
    )


def _effect_spec(evaluator: EffectFunc) -> OpSpec[EffectFunc]:
    return OpSpec(
        evaluator=evaluator,
        meta={},
        defaults={},
        param_order=(),
        ui_visible={},
        n_inputs=1,
        kind="effect",
    )


def _realized(n_vertices: int, *, value: float = 0.0) -> RealizedGeometry:
    coords = np.full((n_vertices, 3), value, dtype=np.float32)
    offsets = np.asarray([0, n_vertices], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@pytest.fixture
def isolated_registries(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]]:
    """realize module だけが参照する空の registry を用意する。"""

    primitives: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    effects: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(realize_module, "primitive_registry", primitives)
    monkeypatch.setattr(realize_module, "effect_registry", effects)
    return primitives, effects


def test_session_reuses_same_content_across_geometry_instances(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    primitives.register("shape", _primitive_spec(lambda _args: _realized(4)))
    first_geometry = Geometry.create("shape", params={"variant": 1})
    same_geometry = Geometry.create("shape", params={"variant": 1})

    with RealizeSession() as session:
        first = session.realize(first_geometry)
        second = session.realize(same_geometry)
        stats = session.stats()

    assert first_geometry.id == same_geometry.id
    assert second is first
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.entries == 1
    assert stats.bytes == first.byte_size


def test_module_convenience_call_does_not_share_global_cache(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    calls = 0

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        nonlocal calls
        calls += 1
        return _realized(2)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")

    first = realize(geometry)
    second = realize(geometry)

    assert first is not second
    assert calls == 2
    assert not hasattr(realize_module, "realize_cache")


def test_lru_evicts_least_recently_used_entry_by_byte_budget(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries

    def evaluate(args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        return _realized(cast(int, dict(args)["n"]))

    primitives.register("shape", _primitive_spec(evaluate))
    geometries = [Geometry.create("shape", params={"n": n}) for n in (3, 4, 5)]
    entry_size = _realized(5).byte_size

    with RealizeSession(max_cache_bytes=entry_size * 2) as session:
        first = session.realize(geometries[0])
        second = session.realize(geometries[1])
        assert session.realize(geometries[0]) is first

        session.realize(geometries[2])
        after_eviction = session.stats()
        assert session.realize(geometries[0]) is first
        assert session.realize(geometries[1]) is not second
        final_stats = session.stats()

    assert after_eviction.evictions == 1
    assert after_eviction.entries == 2
    assert after_eviction.bytes <= entry_size * 2
    assert final_stats.bytes <= entry_size * 2


def test_result_larger_than_budget_is_delivered_but_not_cached(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    calls = 0

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        nonlocal calls
        calls += 1
        return _realized(8)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")
    result_size = _realized(8).byte_size

    with RealizeSession(max_cache_bytes=result_size - 1) as session:
        first = session.realize(geometry)
        second = session.realize(geometry)
        stats = session.stats()

    assert first is not second
    assert calls == 2
    assert stats.misses == 2
    assert stats.entries == 0
    assert stats.bytes == 0


def test_inflight_avoids_duplicate_computation_under_concurrency(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=2.0)
        return _realized(4)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")
    session = RealizeSession()
    results: list[RealizedGeometry] = []
    errors: list[Exception] = []
    result_lock = threading.Lock()
    start = threading.Barrier(9)

    def worker() -> None:
        start.wait()
        try:
            result = session.realize(geometry)
        except Exception as exc:  # noqa: BLE001
            with result_lock:
                errors.append(exc)
        else:
            with result_lock:
                results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    start.wait()
    assert entered.wait(timeout=2.0)
    time.sleep(0.02)
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    session.close()
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == len(threads)
    assert len({id(result) for result in results}) == 1
    assert calls == 1


def test_failed_inflight_notifies_waiters_and_allows_retry(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            entered.set()
            assert release.wait(timeout=2.0)
            raise ValueError("expected failure")
        return _realized(3)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")
    session = RealizeSession()
    errors: list[RealizeError] = []
    error_lock = threading.Lock()
    start = threading.Barrier(7)

    def worker() -> None:
        start.wait()
        try:
            session.realize(geometry)
        except RealizeError as exc:
            with error_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    start.wait()
    assert entered.wait(timeout=2.0)
    time.sleep(0.02)
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len(errors) == len(threads)
    assert calls == 1
    assert session.realize(geometry).coords.shape == (3, 3)
    assert calls == 2
    session.close()


@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(KeyboardInterrupt, id="keyboard-interrupt"),
        pytest.param(SystemExit, id="system-exit"),
    ],
)
def test_leader_preserves_process_control_exception_and_cleans_inflight(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
    error_factory: Callable[[], BaseException],
) -> None:
    primitives, _ = isolated_registries
    should_fail = True

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        if should_fail:
            raise error_factory()
        return _realized(2)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")

    with RealizeSession() as session:
        with pytest.raises((KeyboardInterrupt, SystemExit)) as exc_info:
            session.realize(geometry)
        should_fail = False
        result = session.realize(geometry)

    assert type(exc_info.value) is type(error_factory())
    assert result.coords.shape == (2, 3)


@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(KeyboardInterrupt, id="keyboard-interrupt"),
        pytest.param(SystemExit, id="system-exit"),
    ],
)
def test_process_control_exception_keeps_its_type_for_leader_and_waiters(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
    error_factory: Callable[[], BaseException],
) -> None:
    primitives, _ = isolated_registries
    entered = threading.Event()
    release = threading.Event()
    start = threading.Barrier(7)
    should_fail = True
    calls = 0
    calls_lock = threading.Lock()

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        nonlocal calls
        with calls_lock:
            calls += 1
        if should_fail:
            entered.set()
            assert release.wait(timeout=2.0)
            raise error_factory()
        return _realized(2)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")
    session = RealizeSession()
    errors: list[BaseException] = []
    error_lock = threading.Lock()

    def worker() -> None:
        start.wait()
        try:
            session.realize(geometry)
        except BaseException as exc:  # noqa: BLE001
            with error_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    start.wait()
    assert entered.wait(timeout=2.0)
    time.sleep(0.02)
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len(errors) == len(threads)
    assert {type(error) for error in errors} == {type(error_factory())}
    assert calls == 1

    should_fail = False
    assert session.realize(geometry).coords.shape == (2, 3)
    assert calls == 2
    session.close()


def test_registry_revision_invalidates_cached_geometry(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    primitives.register("shape", _primitive_spec(lambda _args: _realized(2, value=1.0)))
    geometry = Geometry.create("shape")

    with RealizeSession() as session:
        first, first_key = session.realize_with_key(geometry)
        primitives.register(
            "shape",
            _primitive_spec(lambda _args: _realized(2, value=2.0)),
            replace=True,
        )
        second, second_key = session.realize_with_key(geometry)

    assert first_key[0] == second_key[0] == geometry.id
    assert first_key[1] != second_key[1]
    assert first is not second
    np.testing.assert_array_equal(first.coords, np.full((2, 3), 1.0, dtype=np.float32))
    np.testing.assert_array_equal(second.coords, np.full((2, 3), 2.0, dtype=np.float32))


def test_animation_soak_stays_bounded_and_keeps_static_upstream_hot(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, effects = isolated_registries
    primitive_calls = 0
    effect_calls = 0

    def make_base(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        nonlocal primitive_calls
        primitive_calls += 1
        return _realized(16)

    def animate(
        inputs: Sequence[RealizedGeometry],
        args: tuple[tuple[str, object], ...],
    ) -> RealizedGeometry:
        nonlocal effect_calls
        effect_calls += 1
        frame = float(cast(int, dict(args)["frame"]))
        return RealizedGeometry(
            coords=inputs[0].coords + np.float32(frame),
            offsets=inputs[0].offsets,
        )

    primitives.register("base", _primitive_spec(make_base))
    effects.register("animate", _effect_spec(animate))
    base = Geometry.create("base")
    entry_size = _realized(16).byte_size

    with RealizeSession(max_cache_bytes=entry_size * 4) as session:
        base_result = session.realize(base)
        for frame in range(5000):
            animated = Geometry.create("animate", inputs=(base,), params={"frame": frame})
            session.realize(animated)

        stats = session.stats()
        assert session.realize(base) is base_result

    assert primitive_calls == 1
    assert effect_calls == 5000
    assert stats.entries <= 4
    assert stats.bytes <= entry_size * 4
    assert stats.evictions > 0


def test_clear_and_close_release_cache_and_close_is_idempotent(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    primitives.register("shape", _primitive_spec(lambda _args: _realized(4)))
    geometry = Geometry.create("shape")
    session = RealizeSession()

    session.realize(geometry)
    session.clear()
    assert session.stats().entries == 0
    assert session.stats().bytes == 0
    session.realize(geometry)

    session.close()
    session.close()
    assert session.stats().entries == 0
    assert session.stats().bytes == 0
    with pytest.raises(RuntimeError, match="close 済み"):
        session.realize(geometry)


def test_close_allows_inflight_leader_to_finish_without_repopulating_cache(
    isolated_registries: tuple[OpRegistry[PrimitiveFunc], OpRegistry[EffectFunc]],
) -> None:
    primitives, _ = isolated_registries
    entered = threading.Event()
    release = threading.Event()

    def evaluate(_args: tuple[tuple[str, object], ...]) -> RealizedGeometry:
        entered.set()
        assert release.wait(timeout=2.0)
        return _realized(4)

    primitives.register("shape", _primitive_spec(evaluate))
    geometry = Geometry.create("shape")
    session = RealizeSession()
    results: list[RealizedGeometry] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            results.append(session.realize(geometry))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=2.0)

    session.close()
    release.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert errors == []
    assert len(results) == 1
    assert session.stats().entries == 0
    assert session.stats().bytes == 0


def test_negative_cache_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="0 以上"):
        RealizeSession(max_cache_bytes=-1)
