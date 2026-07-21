from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.preset_registry import preset_registry
from grafix.core.primitive_registry import primitive_registry
from grafix.core.realize import realize
from grafix.interactive.runtime.mp_draw import MpDraw
from grafix.interactive.runtime.source_reload import (
    ReloadedDraw,
    SourceReloadController,
    SourceReloadResult,
)


def _write_source(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    stat_result = path.stat()
    os.utime(
        path,
        ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000),
    )


def _primitive_source(*, x: float, fail: bool = False) -> str:
    failure = "raise RuntimeError('candidate failed')" if fail else ""
    return f"""
import numpy as np
from grafix import G, primitive

@primitive
def watch_reload_shape():
    coords = np.asarray([[{x}, 0.0, 0.0], [{x + 1.0}, 0.0, 0.0]], dtype=np.float32)
    return coords, np.asarray([0, 2], dtype=np.int32)

{failure}

def draw(t):
    return G.watch_reload_shape()
"""


def _preset_source(
    *,
    name: str,
    generation: int,
    kind: str = "float",
    fail: bool = False,
    bind_registry_global: bool = False,
) -> str:
    registry_import = (
        "from grafix.core.preset_registry import "
        "preset_registry as imported_preset_registry"
        if bind_registry_global
        else ""
    )
    registry_check = (
        """
    from grafix.core.preset_registry import preset_registry as current_preset_registry
    if imported_preset_registry is not current_preset_registry:
        raise RuntimeError("staged preset registry leaked")
"""
        if bind_registry_global
        else ""
    )
    failure = "raise RuntimeError('candidate failed')" if fail else ""
    return f"""
from grafix import P, preset
from grafix.core.geometry import Geometry
{registry_import}

@preset(meta={{"amount": {{"kind": "{kind}"}}}})
def {name}(amount={generation}):
    return Geometry.create(
        op="concat",
        params={{"generation": {generation}, "amount": amount}},
    )

{failure}

def draw(t):
{registry_check}
    return P.{name}()
"""


def _draw_generation(draw: object) -> int:
    result = draw(0.0)  # type: ignore[operator]
    assert isinstance(result, Geometry)
    return int(dict(result.args)["generation"])


def test_reload_swaps_draw_and_registry_only_after_candidate_success(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with SourceReloadController(source_path) as controller:
        first_draw = controller.draw
        assert isinstance(first_draw, ReloadedDraw)
        assert first_draw.__grafix_source_path__ == source_path.resolve()
        assert first_draw.__grafix_source_bytes__ == source_path.read_bytes()
        np.testing.assert_allclose(realize(first_draw(0.0)).coords[:, 0], [1.0, 2.0])

        _write_source(source_path, _primitive_source(x=20.0, fail=True))
        failed = controller.poll(force=True)
        assert failed.status == "failed"
        assert failed.generation == 0
        assert failed.draw is first_draw
        assert failed.source is not None and str(source_path) in failed.source
        np.testing.assert_allclose(realize(controller.draw(0.0)).coords[:, 0], [1.0, 2.0])

        _write_source(source_path, _primitive_source(x=3.0))
        reloaded = controller.poll(force=True)
        assert reloaded.status == "reloaded"
        assert reloaded.generation == 1
        assert controller.draw is not first_draw
        np.testing.assert_allclose(realize(controller.draw(0.0)).coords[:, 0], [3.0, 4.0])

    assert "watch_reload_shape" not in primitive_registry


def test_unchanged_source_does_not_reload(tmp_path: Path) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with SourceReloadController(source_path) as controller:
        draw = controller.draw
        result = controller.poll()

        assert result.status == "unchanged"
        assert result.generation == 0
        assert result.draw is draw


def test_validated_source_snapshot_runs_in_spawn_worker(tmp_path: Path) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=7.0))

    with SourceReloadController(source_path) as controller:
        worker = MpDraw(controller.draw, n_worker=1)
        try:
            worker.submit(
                t=0.0,
                snapshot_revision=0,
                snapshot={},
                effect_order_snapshot={},
                epoch=0,
                quality="draft",
            )
            deadline = time.monotonic() + 5.0
            result = None
            while result is None and time.monotonic() < deadline:
                result = worker.poll_latest()
                if result is None:
                    time.sleep(0.01)
            assert result is not None
            assert result.error is None
            assert result.layers[0].geometry.op == "watch_reload_shape"
            np.testing.assert_allclose(
                realize(result.layers[0].geometry).coords[:, 0],
                [7.0, 8.0],
            )
        finally:
            worker.close()


def test_reload_removes_presets_deleted_from_source(tmp_path: Path) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(
        source_path,
        """
from grafix import G, P, preset

@preset(meta={"length": {"kind": "float"}})
def watch_reload_preset(length=2.0):
    return G.line(length=length)

def draw(t):
    return P.watch_reload_preset()
""",
    )

    with SourceReloadController(source_path) as controller:
        assert "preset.watch_reload_preset" in preset_registry

        _write_source(
            source_path,
            """
from grafix import G

def draw(t):
    return G.line(length=4.0)
""",
        )
        result = controller.poll(force=True)

        assert result.status == "reloaded"
        assert "preset.watch_reload_preset" not in preset_registry

    assert "preset.watch_reload_preset" not in preset_registry


def test_preset_reload_is_atomic_and_rollback_restores_one_spec(
    tmp_path: Path,
) -> None:
    name = "watch_atomic_preset"
    op = f"preset.{name}"
    source_path = tmp_path / "sketch.py"
    _write_source(
        source_path,
        _preset_source(name=name, generation=1),
    )

    controller = SourceReloadController(source_path)
    try:
        original_spec = dict(preset_registry.items())[op]
        original_revision = preset_registry.revision
        assert preset_registry[op] is original_spec
        assert original_spec.meta["amount"].kind == "float"
        assert _draw_generation(controller.draw) == 1

        _write_source(
            source_path,
            _preset_source(
                name=name,
                generation=2,
                kind="int",
                fail=True,
            ),
        )
        failed = controller.poll(force=True)

        assert failed.status == "failed"
        assert preset_registry.revision == original_revision
        assert dict(preset_registry.items())[op] is original_spec
        assert preset_registry[op] is original_spec
        assert _draw_generation(controller.draw) == 1

        _write_source(
            source_path,
            _preset_source(name=name, generation=2, kind="int"),
        )
        reloaded = controller.poll(force=True, retain_rollback=True)

        assert reloaded.status == "reloaded"
        assert preset_registry.revision == original_revision + 1
        replacement_spec = dict(preset_registry.items())[op]
        assert replacement_spec is not original_spec
        assert preset_registry[op] is replacement_spec
        assert replacement_spec.meta["amount"].kind == "int"
        assert _draw_generation(controller.draw) == 2

        restored_draw = controller.rollback_generation(reloaded.generation)

        assert preset_registry.revision == original_revision + 2
        assert dict(preset_registry.items())[op] is original_spec
        assert preset_registry[op] is original_spec
        assert restored_draw is controller.draw
        assert _draw_generation(restored_draw) == 1
    finally:
        before_close = preset_registry.revision
        controller.close()

    assert preset_registry.revision == before_close + 1
    assert op not in preset_registry


def test_reload_rebinds_source_module_registry_global_to_live_object(
    tmp_path: Path,
) -> None:
    name = "watch_registry_binding_preset"
    source_path = tmp_path / "sketch.py"
    _write_source(
        source_path,
        _preset_source(
            name=name,
            generation=3,
            bind_registry_global=True,
        ),
    )

    with SourceReloadController(source_path) as controller:
        assert _draw_generation(controller.draw) == 3
        assert f"preset.{name}" in preset_registry

    assert f"preset.{name}" not in preset_registry


def test_transactional_reload_can_rollback_registry_and_draw(tmp_path: Path) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with SourceReloadController(source_path) as controller:
        first_draw = controller.draw
        _write_source(source_path, _primitive_source(x=9.0))
        result = controller.poll(force=True, retain_rollback=True)

        assert result.status == "reloaded"
        np.testing.assert_allclose(realize(controller.draw(0.0)).coords[:, 0], [9.0, 10.0])

        restored = controller.rollback_generation(result.generation)

        assert restored is first_draw
        assert controller.generation == 0
        np.testing.assert_allclose(realize(controller.draw(0.0)).coords[:, 0], [1.0, 2.0])


def test_pending_transaction_must_be_explicitly_finished_before_next_poll(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with SourceReloadController(source_path) as controller:
        first_draw = controller.draw
        _write_source(source_path, _primitive_source(x=9.0))
        result = controller.poll(force=True, retain_rollback=True)

        with pytest.raises(RuntimeError, match="未確定.*accept_generation.*rollback_generation"):
            controller.poll()
        with pytest.raises(RuntimeError, match="generation=1"):
            controller.poll(force=True)

        assert controller.generation == result.generation
        restored = controller.rollback_generation(result.generation)
        assert restored is first_draw
        assert controller.generation == 0


def test_explicit_accept_allows_the_next_poll(tmp_path: Path) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with SourceReloadController(source_path) as controller:
        _write_source(source_path, _primitive_source(x=2.0))
        result = controller.poll(force=True, retain_rollback=True)

        controller.accept_generation(result.generation)
        unchanged = controller.poll()

        assert unchanged.status == "unchanged"
        assert unchanged.generation == result.generation


def test_accept_and_rollback_are_one_shot_and_check_generation(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with SourceReloadController(source_path) as controller:
        _write_source(source_path, _primitive_source(x=2.0))
        accepted = controller.poll(force=True, retain_rollback=True)

        with pytest.raises(ValueError, match="generation"):
            controller.accept_generation(accepted.generation - 1)
        with pytest.raises(ValueError, match="generation"):
            controller.rollback_generation(accepted.generation - 1)
        controller.accept_generation(accepted.generation)
        with pytest.raises(ValueError, match="accept可能"):
            controller.accept_generation(accepted.generation)
        with pytest.raises(ValueError, match="rollback可能"):
            controller.rollback_generation(accepted.generation)

        _write_source(source_path, _primitive_source(x=3.0))
        rolled_back = controller.poll(force=True, retain_rollback=True)
        controller.rollback_generation(rolled_back.generation)
        with pytest.raises(ValueError, match="accept可能"):
            controller.accept_generation(rolled_back.generation)
        with pytest.raises(ValueError, match="rollback可能"):
            controller.rollback_generation(rolled_back.generation)


def test_close_finishes_a_pending_transaction_as_terminal_cleanup(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))
    controller = SourceReloadController(source_path)
    _write_source(source_path, _primitive_source(x=2.0))
    controller.poll(force=True, retain_rollback=True)

    controller.close()
    controller.close()

    assert "watch_reload_shape" not in primitive_registry


def test_runtime_error_then_source_fix_uses_new_generation(tmp_path: Path) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=4.0))

    with SourceReloadController(source_path) as controller:
        last_good = realize(controller.draw(0.0))
        _write_source(
            source_path,
            "from grafix import G\n\ndef draw(t):\n    raise RuntimeError('bad frame')\n",
        )
        bad = controller.poll(force=True)
        assert bad.status == "reloaded"
        with pytest.raises(RuntimeError, match="bad frame"):
            controller.draw(0.0)
        np.testing.assert_allclose(last_good.coords[:, 0], [4.0, 5.0])

        _write_source(source_path, _primitive_source(x=6.0))
        fixed = controller.poll(force=True)
        assert fixed.status == "reloaded"
        np.testing.assert_allclose(realize(controller.draw(0.0)).coords[:, 0], [6.0, 7.0])


@pytest.mark.parametrize(
    "source",
    [
        "value = 1\n",
        "def draw():\n    return None\n",
        "async def draw(t):\n    return None\n",
    ],
)
def test_initial_load_rejects_missing_or_invalid_draw_signature(
    tmp_path: Path,
    source: str,
) -> None:
    source_path = tmp_path / "invalid.py"
    _write_source(source_path, source)

    with pytest.raises(RuntimeError, match="draw|callable"):
        SourceReloadController(source_path)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("status", "legacy", ValueError),
        ("generation", True, TypeError),
        ("generation", -2, ValueError),
        ("draw", object(), TypeError),
        ("summary", object(), TypeError),
    ],
)
def test_source_reload_result_validates_direct_construction(
    field: str,
    value: object,
    error: type[Exception],
) -> None:
    values: dict[str, object] = {
        "status": "unchanged",
        "generation": 0,
        "draw": lambda _t: (),
    }
    values[field] = value
    with pytest.raises(error):
        SourceReloadResult(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("path", "sketch.py", TypeError),
        ("source_bytes", bytearray(b""), TypeError),
        ("module_name", 1, TypeError),
        ("module_name", "", ValueError),
        ("draw_attribute", 1, TypeError),
        ("draw_attribute", "", ValueError),
        ("loaded_draw", object(), TypeError),
    ],
)
def test_reloaded_draw_rejects_implicit_constructor_coercion(
    field: str,
    value: object,
    error: type[Exception],
) -> None:
    values: dict[str, object] = {
        "path": Path("sketch.py"),
        "source_bytes": b"",
        "module_name": "_sketch",
        "draw_attribute": "draw",
        "loaded_draw": lambda _t: (),
    }
    values[field] = value
    with pytest.raises(error):
        ReloadedDraw(**values)  # type: ignore[arg-type]


def test_reloaded_draw_rejects_implicit_time_coercion() -> None:
    draw = ReloadedDraw(
        path=Path("sketch.py"),
        source_bytes=b"",
        module_name="_sketch",
        draw_attribute="draw",
        loaded_draw=lambda _t: (),
    )
    with pytest.raises(TypeError, match="t"):
        draw("0")  # type: ignore[arg-type]


def test_source_reload_controller_rejects_noncanonical_controls(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "sketch.py"
    _write_source(source_path, _primitive_source(x=1.0))

    with pytest.raises(TypeError, match="path"):
        SourceReloadController(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="draw_attribute"):
        SourceReloadController(source_path, draw_attribute=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="空白"):
        SourceReloadController(source_path, draw_attribute=" draw ")

    with SourceReloadController(source_path) as controller:
        with pytest.raises(TypeError, match="force"):
            controller.poll(force=1)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="retain_rollback"):
            controller.poll(retain_rollback=0)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="generation"):
            controller.accept_generation(True)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="generation"):
            controller.rollback_generation("0")  # type: ignore[arg-type]
