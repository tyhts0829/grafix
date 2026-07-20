from __future__ import annotations

from dataclasses import replace

import pytest

import grafix.core.primitive_registry as primitive_registry_module
from grafix.core.builtins import ensure_builtin_ops_registered
from grafix.core.op_registry import OpRegistry
from grafix.core.primitive_registry import PrimitiveFunc
from grafix.devtools.generate_stub import _resolve_impl_callable


def test_resolve_impl_callable_rejects_missing_provenance_without_name_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_builtin_ops_registered()
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    registry.register(
        "line",
        replace(
            primitive_registry_module.primitive_registry["line"],
            provenance="",
        ),
    )
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    with pytest.raises(ValueError, match="provenance"):
        _resolve_impl_callable("primitive", "line")
