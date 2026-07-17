"""decorator が元 callable から OpSpec catalog 情報を作ることを検証する。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import grafix.core.effect_registry as effect_registry_module
import grafix.core.primitive_registry as primitive_registry_module
from grafix.core.effect_registry import EffectFunc
from grafix.core.op_registry import OpRegistry, OpSpec
from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import PrimitiveFunc
from grafix.core.realized_geometry import GeomTuple


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
