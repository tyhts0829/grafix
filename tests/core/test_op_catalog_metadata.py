"""decorator が元 callable から OpSpec catalog 情報を作ることを検証する。"""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import numpy as np
import pytest

import grafix.core.effect_registry as effect_registry_module
import grafix.core.primitive_registry as primitive_registry_module
from grafix.core.effect_registry import EffectFunc
from grafix.core.op_registry import OpRegistry, OpSpec
from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import PrimitiveFunc
from grafix.core.realized_geometry import GeomTuple, RealizedGeometry


def _empty_geometry() -> GeomTuple:
    return (
        np.empty((0, 3), dtype=np.float32),
        np.zeros((1,), dtype=np.int32),
    )


def test_primitive_decorator_records_doc_source_and_required_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    @primitive_registry_module.primitive(meta={"count": ParamMeta(kind="int")})
    def catalog_primitive(points: tuple[float, ...], *, count: int = 2) -> GeomTuple:
        """catalog 検証用 primitive。

        2 行目以降も full doc に保持する。
        """

        _ = points, count
        return _empty_geometry()

    spec = registry["catalog_primitive"]
    assert spec.description == "catalog 検証用 primitive。"
    assert "2 行目以降" in spec.doc
    assert spec.accepted_args == ("points", "count")
    assert spec.required_args == ("points",)
    assert spec.source is not None
    assert Path(spec.source).name == "test_op_catalog_metadata.py"
    assert spec.provenance.endswith(".catalog_primitive")
    assert dict(spec.defaults) == {"activate": True, "count": 2}


def test_effect_decorator_excludes_each_geometry_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)

    @effect_registry_module.effect(n_inputs=2)
    def catalog_effect(
        first: GeomTuple,
        second: GeomTuple,
        *,
        weight: float,
        mode: str = "first",
    ) -> GeomTuple:
        """2 入力用 catalog 検証 effect。"""

        _ = second, weight, mode
        return first

    spec = registry["catalog_effect"]
    assert spec.accepted_args == ("weight", "mode")
    assert spec.required_args == ("weight",)
    assert spec.description == "2 入力用 catalog 検証 effect。"
    assert spec.provenance.endswith(".catalog_effect")


def test_effect_reuses_immutable_offsets_and_snapshots_changed_coords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)
    output_coords = np.asarray(
        [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
        dtype=np.float32,
    )

    @effect_registry_module.effect
    def coords_only_effect(g: GeomTuple) -> GeomTuple:
        return output_coords, g[1]

    input_geometry = RealizedGeometry(
        coords=np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            dtype=np.float32,
        ),
        offsets=np.asarray([0, 1, 2], dtype=np.int32),
    )
    result = registry["coords_only_effect"].evaluator([input_geometry], ())

    assert result.coords is not output_coords
    assert not np.shares_memory(result.coords, output_coords)
    assert result.offsets is input_geometry.offsets
    assert result.coords.flags.writeable is False
    assert output_coords.flags.writeable is True
    np.testing.assert_array_equal(
        result.coords,
        np.asarray(
            [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
            dtype=np.float32,
        ),
    )


def test_effect_rejects_noncanonical_coords_instead_of_converting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)
    output_coords = np.asarray(
        [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
        dtype=np.float64,
    )

    @effect_registry_module.effect
    def converted_effect(g: GeomTuple) -> GeomTuple:
        return output_coords, g[1]

    input_geometry = RealizedGeometry(
        coords=np.asarray(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            dtype=np.float32,
        ),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )
    with pytest.raises(ValueError, match=r"\(coords, offsets\) が不正") as exc_info:
        registry["converted_effect"].evaluator([input_geometry], ())

    assert isinstance(exc_info.value.__cause__, TypeError)
    assert "float32" in str(exc_info.value.__cause__)


def test_effect_different_offsets_use_normal_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)
    output_coords = np.asarray(
        [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
        dtype=np.float32,
    )
    output_offsets = np.asarray([0, 1, 2], dtype=np.int32)

    @effect_registry_module.effect
    def repartition_effect(_g: GeomTuple) -> GeomTuple:
        return output_coords, output_offsets

    input_geometry = RealizedGeometry(
        coords=np.zeros((2, 3), dtype=np.float32),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )
    result = registry["repartition_effect"].evaluator([input_geometry], ())

    assert result.coords is not output_coords
    assert result.offsets is not output_offsets
    assert not np.shares_memory(result.coords, output_coords)
    assert not np.shares_memory(result.offsets, output_offsets)
    assert result.offsets is not input_geometry.offsets
    assert result.coords.flags.writeable is False
    assert result.offsets.flags.writeable is False


class _TupleSubclass(tuple):
    pass


_NamedGeometryTuple = namedtuple("_NamedGeometryTuple", ("coords", "offsets"))


@pytest.mark.parametrize("named", [False, True])
def test_effect_rejects_tuple_subclass_output(
    monkeypatch: pytest.MonkeyPatch,
    named: bool,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)

    @effect_registry_module.effect
    def tuple_subclass_effect(g: GeomTuple) -> GeomTuple:
        if named:
            return _NamedGeometryTuple(g[0], g[1])  # type: ignore[return-value]
        return _TupleSubclass((g[0], g[1]))  # type: ignore[return-value]

    input_geometry = RealizedGeometry(
        coords=np.zeros((2, 3), dtype=np.float32),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )

    with pytest.raises(TypeError, match="期待する戻り値"):
        registry["tuple_subclass_effect"].evaluator([input_geometry], ())


def test_effect_trusted_offsets_length_mismatch_uses_existing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)

    @effect_registry_module.effect
    def invalid_coords_effect(g: GeomTuple) -> GeomTuple:
        return np.zeros((1, 3), dtype=np.float32), g[1]

    input_geometry = RealizedGeometry(
        coords=np.zeros((2, 3), dtype=np.float32),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )

    with pytest.raises(
        ValueError,
        match=r"@effect .*\.invalid_coords_effect: "
        r"\(coords, offsets\) が不正です",
    ):
        registry["invalid_coords_effect"].evaluator([input_geometry], ())


@pytest.mark.parametrize(
    ("coords", "offsets"),
    [
        (
            np.zeros((2, 2), dtype=np.float32),
            np.asarray([0, 2], dtype=np.int32),
        ),
        (
            np.zeros((2, 3), dtype=np.float64),
            np.asarray([0, 2], dtype=np.int32),
        ),
        (
            np.zeros((2, 3), dtype=np.float32),
            np.asarray([0, 2], dtype=np.int64),
        ),
        (
            np.asarray([[0.0, 0.0, 0.0], [np.nan, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 2], dtype=np.int32),
        ),
        (
            np.zeros((3, 3), dtype=np.float32)[::2],
            np.asarray([0, 2], dtype=np.int32),
        ),
        (
            np.zeros((2, 3), dtype=np.float32),
            np.asarray([0, 1, 2, 2], dtype=np.int32)[::2],
        ),
    ],
)
def test_user_primitive_rejects_every_noncanonical_output_array(
    monkeypatch: pytest.MonkeyPatch,
    coords: np.ndarray,
    offsets: np.ndarray,
) -> None:
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    @primitive_registry_module.primitive
    def invalid_output_primitive() -> GeomTuple:
        return coords, offsets

    with pytest.raises(ValueError, match=r"\(coords, offsets\) が不正"):
        registry["invalid_output_primitive"].evaluator(())


def test_new_op_spec_catalog_fields_have_compatible_defaults() -> None:
    spec = OpSpec(
        evaluator=lambda: None,
        meta={},
        defaults={},
        param_order=(),
        ui_visible={},
        n_inputs=0,
        kind="primitive",
    )

    assert spec.description == ""
    assert spec.doc == ""
    assert spec.source is None
    assert spec.provenance == ""
    assert spec.accepted_args == ()
    assert spec.required_args == ()
    assert spec.accepts_var_kwargs is False


def test_op_spec_rejects_required_arg_outside_accepted_args() -> None:
    with pytest.raises(ValueError, match="accepted_args"):
        OpSpec(
            evaluator=lambda: None,
            meta={},
            defaults={},
            param_order=(),
            ui_visible={},
            n_inputs=0,
            kind="primitive",
            required_args=("missing",),
        )


def test_catalog_records_var_keyword_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    @primitive_registry_module.primitive
    def dynamic_primitive(**params: object) -> GeomTuple:
        return _empty_geometry()

    assert registry["dynamic_primitive"].accepts_var_kwargs is True


def test_primitive_builtin_meta_requirement_uses_only_canonical_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    def canonical_builtin() -> GeomTuple:
        return _empty_geometry()

    canonical_builtin.__module__ = "grafix.core.primitives.example"
    with pytest.raises(ValueError, match="meta 必須"):
        primitive_registry_module.primitive(canonical_builtin)

    def similarly_named_user_module() -> GeomTuple:
        return _empty_geometry()

    similarly_named_user_module.__module__ = "core.primitives.example"
    primitive_registry_module.primitive(similarly_named_user_module)

    assert "similarly_named_user_module" in registry


def test_effect_builtin_meta_requirement_uses_only_canonical_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    monkeypatch.setattr(effect_registry_module, "effect_registry", registry)

    def canonical_builtin(g: GeomTuple) -> GeomTuple:
        return g

    canonical_builtin.__module__ = "grafix.core.effects.example"
    with pytest.raises(ValueError, match="meta 必須"):
        effect_registry_module.effect(canonical_builtin)

    def similarly_named_user_module(g: GeomTuple) -> GeomTuple:
        return g

    similarly_named_user_module.__module__ = "core.effects.example"
    effect_registry_module.effect(similarly_named_user_module)

    assert "similarly_named_user_module" in registry
