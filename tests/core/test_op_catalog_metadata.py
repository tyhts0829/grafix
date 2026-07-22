"""decorator が immutable OpDeclaration と評価 adapter を作る契約を検証する。"""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from typing import Callable

import numpy as np
import pytest

import grafix.core.operation_authoring as operation_authoring_module
from grafix.core.authoring_definitions import RegistrationTarget, registration_scope
from grafix.core.definition_fingerprint import DefinitionFingerprintError
from grafix.core.operation_declaration import OpDeclaration
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple, RealizedGeometry


def _empty_geometry() -> GeomTuple:
    return (
        np.empty((0, 3), dtype=np.float32),
        np.zeros((1,), dtype=np.int32),
    )


def _register(
    decorator: Callable[[Callable[..., GeomTuple]], Callable[..., GeomTuple]],
    func: Callable[..., GeomTuple],
    *,
    kind: str,
) -> OpDeclaration:
    target = RegistrationTarget()
    with registration_scope(target):
        decorator(func)
    return target.snapshot().operations.resolve(kind, func.__name__).declaration  # type: ignore[arg-type]


def test_primitive_declaration_records_doc_source_and_required_args() -> None:
    def catalog_primitive(
        points: tuple[float, ...], *, count: int = 2
    ) -> GeomTuple:
        """catalog 検証用 primitive。

        2 行目以降も full doc に保持する。
        """

        _ = points, count
        return _empty_geometry()

    declaration = _register(
        operation_authoring_module.primitive(meta={"count": ParamMeta(kind="int")}),
        catalog_primitive,
        kind="primitive",
    )
    assert declaration.description == "catalog 検証用 primitive。"
    assert "2 行目以降" in declaration.doc
    assert declaration.accepted_args == ("points", "count")
    assert declaration.required_args == ("points",)
    assert declaration.source is not None
    assert Path(declaration.source).name == "test_op_catalog_metadata.py"
    assert declaration.provenance.endswith(".catalog_primitive")
    assert dict(declaration.schema.defaults) == {"activate": True, "count": 2}


def test_effect_declaration_excludes_each_geometry_input() -> None:
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

    declaration = _register(
        operation_authoring_module.effect(n_inputs=2),
        catalog_effect,
        kind="effect",
    )
    assert declaration.accepted_args == ("weight", "mode")
    assert declaration.required_args == ("weight",)
    assert declaration.description == "2 入力用 catalog 検証 effect。"


def test_content_cached_declaration_rejects_uncanonical_closure_dependency() -> None:
    output_coords = np.zeros((2, 3), dtype=np.float32)

    def dynamic_array_effect(g: GeomTuple) -> GeomTuple:
        return output_coords, g[1]

    target = RegistrationTarget()
    with registration_scope(target):
        with pytest.raises(DefinitionFingerprintError, match="output_coords"):
            operation_authoring_module.effect(dynamic_array_effect)
    assert len(target.snapshot().operations) == 0


def test_none_cached_effect_can_declare_dynamic_dependency_with_version() -> None:
    output_coords = np.asarray(
        [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
        dtype=np.float32,
    )

    def coords_only_effect(g: GeomTuple) -> GeomTuple:
        return output_coords, g[1]

    declaration = _register(
        operation_authoring_module.effect(cache_policy="none", version="coords-v1"),
        coords_only_effect,
        kind="effect",
    )
    input_geometry = RealizedGeometry(
        coords=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1, 2], dtype=np.int32),
    )
    result = declaration.evaluator([input_geometry], ())
    assert result.coords is not output_coords
    assert not np.shares_memory(result.coords, output_coords)
    assert result.offsets is input_geometry.offsets
    assert result.coords.flags.writeable is False


def test_effect_rejects_noncanonical_coords_instead_of_converting() -> None:
    output_coords = np.asarray(
        [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
        dtype=np.float64,
    )

    def converted_effect(g: GeomTuple) -> GeomTuple:
        return output_coords, g[1]

    declaration = _register(
        operation_authoring_module.effect(cache_policy="none", version="converted-v1"),
        converted_effect,
        kind="effect",
    )
    input_geometry = RealizedGeometry(
        coords=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )
    with pytest.raises(ValueError, match=r"\(coords, offsets\) が不正") as exc_info:
        declaration.evaluator([input_geometry], ())
    assert isinstance(exc_info.value.__cause__, TypeError)
    assert "float32" in str(exc_info.value.__cause__)


def test_effect_different_offsets_use_normal_validation() -> None:
    output_coords = np.asarray(
        [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32
    )
    output_offsets = np.asarray([0, 1, 2], dtype=np.int32)

    def repartition_effect(_g: GeomTuple) -> GeomTuple:
        return output_coords, output_offsets

    declaration = _register(
        operation_authoring_module.effect(cache_policy="none", version="partition-v1"),
        repartition_effect,
        kind="effect",
    )
    input_geometry = RealizedGeometry(
        coords=np.zeros((2, 3), dtype=np.float32),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )
    result = declaration.evaluator([input_geometry], ())
    assert result.coords is not output_coords
    assert result.offsets is not output_offsets
    assert result.offsets is not input_geometry.offsets
    assert result.coords.flags.writeable is False
    assert result.offsets.flags.writeable is False


class _TupleSubclass(tuple):
    pass


_NamedGeometryTuple = namedtuple("_NamedGeometryTuple", ("coords", "offsets"))


@pytest.mark.parametrize("named", [False, True])
def test_effect_rejects_tuple_subclass_output(named: bool) -> None:
    def tuple_subclass_effect(g: GeomTuple) -> GeomTuple:
        if named:
            return _NamedGeometryTuple(g[0], g[1])  # type: ignore[return-value]
        return _TupleSubclass((g[0], g[1]))  # type: ignore[return-value]

    declaration = _register(
        operation_authoring_module.effect(cache_policy="none", version="tuple-v1"),
        tuple_subclass_effect,
        kind="effect",
    )
    input_geometry = RealizedGeometry(
        coords=np.zeros((2, 3), dtype=np.float32),
        offsets=np.asarray([0, 2], dtype=np.int32),
    )
    with pytest.raises(TypeError, match="期待する戻り値"):
        declaration.evaluator([input_geometry], ())


@pytest.mark.parametrize(
    ("coords", "offsets"),
    [
        (np.zeros((2, 2), dtype=np.float32), np.asarray([0, 2], dtype=np.int32)),
        (np.zeros((2, 3), dtype=np.float64), np.asarray([0, 2], dtype=np.int32)),
        (np.zeros((2, 3), dtype=np.float32), np.asarray([0, 2], dtype=np.int64)),
        (
            np.asarray([[0.0, 0.0, 0.0], [np.nan, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 2], dtype=np.int32),
        ),
        (np.zeros((3, 3), dtype=np.float32)[::2], np.asarray([0, 2], dtype=np.int32)),
        (
            np.zeros((2, 3), dtype=np.float32),
            np.asarray([0, 1, 2, 2], dtype=np.int32)[::2],
        ),
    ],
)
def test_user_primitive_rejects_every_noncanonical_output_array(
    coords: np.ndarray,
    offsets: np.ndarray,
) -> None:
    def invalid_output_primitive() -> GeomTuple:
        return coords, offsets

    declaration = _register(
        operation_authoring_module.primitive(
            cache_policy="none", version="invalid-output-v1"
        ),
        invalid_output_primitive,
        kind="primitive",
    )
    with pytest.raises(ValueError, match=r"\(coords, offsets\) が不正"):
        declaration.evaluator(())


def test_declaration_records_var_keyword_support() -> None:
    def dynamic_primitive(**params: object) -> GeomTuple:
        _ = params
        return _empty_geometry()

    declaration = _register(
        operation_authoring_module.primitive,
        dynamic_primitive,
        kind="primitive",
    )
    assert declaration.accepts_var_kwargs is True


def test_builtin_detection_uses_exact_manifest_locator() -> None:
    def prefix_only_primitive() -> GeomTuple:
        return _empty_geometry()

    prefix_only_primitive.__module__ = "grafix.core.primitives.example"
    declaration = _register(
        operation_authoring_module.primitive,
        prefix_only_primitive,
        kind="primitive",
    )
    assert declaration.schema.meta == {}

    def exact_circle() -> GeomTuple:
        return _empty_geometry()

    exact_circle.__module__ = "grafix.core.primitives.circle"
    exact_circle.__name__ = "circle"
    with pytest.raises(ValueError, match="meta 必須"):
        operation_authoring_module.primitive(exact_circle)

    def prefix_only_effect(g: GeomTuple) -> GeomTuple:
        return g

    prefix_only_effect.__module__ = "grafix.core.effects.example"
    declaration = _register(
        operation_authoring_module.effect,
        prefix_only_effect,
        kind="effect",
    )
    assert declaration.schema.meta == {}

    def exact_scale(g: GeomTuple) -> GeomTuple:
        return g

    exact_scale.__module__ = "grafix.core.effects.scale"
    exact_scale.__name__ = "scale"
    with pytest.raises(ValueError, match="meta 必須"):
        operation_authoring_module.effect(exact_scale)
