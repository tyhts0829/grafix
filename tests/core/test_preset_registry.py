from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from grafix.core.geometry import Geometry
from grafix.core.parameters.meta import ParamMeta
from grafix.core.preset_registry import (
    PresetIdentity,
    PresetRegistry,
    PresetSpec,
    preset_op,
)


def _empty_scene(**_kwargs: object) -> Geometry:
    return Geometry.create(op="concat")


def _invoke_empty(_identity: object, **kwargs: object) -> Geometry:
    return _empty_scene(**kwargs)


def test_preset_registry_owns_callable_and_metadata_under_canonical_op() -> None:
    registry = PresetRegistry()
    meta = {"amount": ParamMeta(kind="float")}
    visible = {"amount": lambda values: float(values["amount"]) > 0.0}

    registry._register(
        "sample",
        _empty_scene,
        invoker=_invoke_empty,
        display_op="sample",
        meta=meta,
        param_order=("amount",),
        ui_visible=visible,
    )

    assert registry.revision == 1
    assert preset_op("sample") == "preset.sample"
    assert "preset.sample" in registry
    assert "sample" not in registry

    spec = registry["preset.sample"]
    assert spec.func is _empty_scene
    assert spec.display_op == "sample"
    assert spec.param_order == ("amount",)
    assert spec.meta["amount"].kind == "float"
    assert spec.ui_visible["amount"]({"amount": 1.0}) is True

    meta.clear()
    visible.clear()
    assert tuple(spec.meta) == ("amount",)
    assert tuple(spec.ui_visible) == ("amount",)
    with pytest.raises(TypeError):
        cast(dict[str, ParamMeta], spec.meta)["other"] = ParamMeta(kind="int")


def test_preset_registry_duplicate_is_non_mutating_and_uses_bare_name() -> None:
    registry = PresetRegistry()
    registry._register(
        "duplicate",
        _empty_scene,
        invoker=_invoke_empty,
        display_op="duplicate",
        meta={},
        param_order=(),
    )
    original = dict(registry.items())["preset.duplicate"]
    original_revision = registry.revision

    with pytest.raises(
        ValueError,
        match=r"^preset 'duplicate' は既に登録されている$",
    ):
        registry._register(
            "duplicate",
            lambda: Geometry.create(op="concat"),
            invoker=_invoke_empty,
            display_op="duplicate",
            meta={},
            param_order=(),
        )

    assert registry.revision == original_revision
    assert dict(registry.items())["preset.duplicate"] is original
    assert registry["preset.duplicate"].func is _empty_scene


@pytest.mark.parametrize("invalid", (1, object()))
def test_preset_registry_rejects_implicitly_stringifiable_names(
    invalid: object,
) -> None:
    registry = PresetRegistry()

    with pytest.raises(TypeError, match="空でない文字列"):
        preset_op(cast(str, invalid))
    with pytest.raises(TypeError, match="空でない文字列"):
        registry._register(
            cast(str, invalid),
            _empty_scene,
            invoker=_invoke_empty,
            display_op="sample",
            meta={},
            param_order=(),
        )


def test_preset_registry_rejects_empty_names_and_labels() -> None:
    registry = PresetRegistry()

    with pytest.raises(ValueError, match="空でない文字列"):
        preset_op("")
    with pytest.raises(ValueError, match="空でない文字列"):
        PresetIdentity(name="", key=None, instance_key=None, shared=False)
    with pytest.raises(TypeError, match="空でない文字列"):
        PresetIdentity(name=cast(str, 1), key=None, instance_key=None, shared=False)
    with pytest.raises(ValueError, match="空でない文字列"):
        registry._register(
            "sample",
            _empty_scene,
            invoker=_invoke_empty,
            display_op="",
            meta={},
            param_order=(),
        )


def test_preset_registry_replace_all_validates_before_assignment() -> None:
    registry = PresetRegistry()
    registry._register(
        "first",
        _empty_scene,
        invoker=_invoke_empty,
        display_op="first",
        meta={},
        param_order=(),
    )
    original_items = dict(registry.items())
    original_revision = registry.revision

    with pytest.raises(TypeError, match="PresetSpec"):
        registry.replace_all(
            cast(Mapping[str, PresetSpec], {"preset.invalid": object()})
        )

    assert registry.revision == original_revision
    assert dict(registry.items()) == original_items

    replacement = PresetSpec(
        func=_empty_scene,
        invoker=_invoke_empty,
        display_op="replacement",
        meta={"amount": ParamMeta(kind="float")},
        param_order=("amount",),
        ui_visible={},
    )
    registry.replace_all({"preset.replacement": replacement})

    assert registry.revision == original_revision + 1
    assert dict(registry.items()) == {"preset.replacement": replacement}
    assert registry["preset.replacement"].func is _empty_scene


def test_preset_spec_rejects_non_callable_without_exposing_mutable_state() -> None:
    with pytest.raises(TypeError, match="callable"):
        PresetSpec(
            func=cast(Any, object()),
            invoker=_invoke_empty,
            display_op="invalid",
            meta={},
            param_order=(),
            ui_visible={},
        )


def test_preset_spec_rejects_implicit_param_order_conversion() -> None:
    with pytest.raises(TypeError):
        PresetSpec(
            func=_empty_scene,
            invoker=_invoke_empty,
            display_op="sample",
            meta={},
            param_order=(1,),  # type: ignore[arg-type]
            ui_visible={},
        )
