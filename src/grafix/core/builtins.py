"""
どこで: `src/grafix/core/builtins.py`。
何を: 組み込み primitive/effect の登録（registry 初期化）を単一入口へ集約する。
なぜ: import 副作用の分散と手動列挙の重複をなくし、保守性を上げるため。
"""

from __future__ import annotations

import importlib
from types import MappingProxyType

_BUILTIN_PRIMITIVE_MODULES = MappingProxyType({
    name: f"grafix.core.primitives.{name}"
    for name in (
        "arc",
        "asemic",
        "bezier",
        "circle",
        "ellipse",
        "grid",
        "line",
        "lissajous",
        "laplace_field_grid",
        "lsystem",
        "polygon",
        "polyline",
        "polyhedron",
        "rect",
        "sphere",
        "spiral",
        "spline",
        "text",
        "torus",
        "wave",
    )
})

_BUILTIN_EFFECT_MODULES = MappingProxyType({
    name: f"grafix.core.effects.{name}"
    for name in (
        "collapse",
        "scale",
        "rotate",
        "fill",
        "dash",
        "displace",
        "wobble",
        "affine",
        "subdivide",
        "quantize",
        "pixelate",
        "partition",
        "mirror",
        "mirror3d",
        "metaball",
        "isocontour",
        "translate",
        "extrude",
        "repeat",
        "buffer",
        "bold",
        "drop",
        "trim",
        "lowpass",
        "highpass",
        "clip",
        "twist",
        "weave",
        "growth",
        "relax",
        "reaction_diffusion",
        "warp",
        "resample",
        "simplify",
        "deduplicate",
        "boolean",
        "offset_curve",
    )
})


def ensure_builtin_primitive_registered(name: str) -> bool:
    """builtin primitive を catalog から live registry へ不足時だけ登録する。"""

    module = _BUILTIN_PRIMITIVE_MODULES.get(name)
    if module is None:
        return False
    importlib.import_module(module)
    from . import primitive_registry as registry_module

    spec = registry_module.builtin_primitive_catalog.get(name)
    if spec is None:
        raise RuntimeError(f"builtin primitive spec が記録されていません: {name!r}")
    registry = registry_module.primitive_registry
    if name not in registry:
        registry.register(name, spec)
    return registry[name] is spec


def ensure_builtin_effect_registered(name: str) -> bool:
    """builtin effect を catalog から live registry へ不足時だけ登録する。"""

    module = _BUILTIN_EFFECT_MODULES.get(name)
    if module is None:
        return False
    importlib.import_module(module)
    from . import effect_registry as registry_module

    spec = registry_module.builtin_effect_catalog.get(name)
    if spec is None:
        raise RuntimeError(f"builtin effect spec が記録されていません: {name!r}")
    registry = registry_module.effect_registry
    if name not in registry:
        registry.register(name, spec)
    return registry[name] is spec


def ensure_builtin_primitives_registered() -> None:
    """組み込み primitive を registry に登録する（idempotent）。"""

    for name in _BUILTIN_PRIMITIVE_MODULES:
        ensure_builtin_primitive_registered(name)


def ensure_builtin_effects_registered() -> None:
    """組み込み effect を registry に登録する（idempotent）。"""

    for name in _BUILTIN_EFFECT_MODULES:
        ensure_builtin_effect_registered(name)


def ensure_builtin_ops_registered() -> None:
    """組み込み primitive/effect をまとめて登録する（idempotent）。"""

    ensure_builtin_primitives_registered()
    ensure_builtin_effects_registered()


__all__ = [
    "ensure_builtin_effect_registered",
    "ensure_builtin_effects_registered",
    "ensure_builtin_ops_registered",
    "ensure_builtin_primitive_registered",
    "ensure_builtin_primitives_registered",
]
