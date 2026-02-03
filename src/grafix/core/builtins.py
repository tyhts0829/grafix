"""
どこで: `src/grafix/core/builtins.py`。
何を: 組み込み primitive/effect の登録（registry 初期化）を単一入口へ集約する。
なぜ: import 副作用の分散と手動列挙の重複をなくし、保守性を上げるため。
"""

from __future__ import annotations

import importlib

_BUILTIN_PRIMITIVE_MODULES: tuple[str, ...] = (
    "grafix.core.primitives.asemic",
    "grafix.core.primitives.grid",
    "grafix.core.primitives.line",
    "grafix.core.primitives.polygon",
    "grafix.core.primitives.polyhedron",
    "grafix.core.primitives.sphere",
    "grafix.core.primitives.text",
    "grafix.core.primitives.torus",
)

_BUILTIN_EFFECT_MODULES: tuple[str, ...] = (
    "grafix.core.effects.collapse",
    "grafix.core.effects.scale",
    "grafix.core.effects.rotate",
    "grafix.core.effects.fill",
    "grafix.core.effects.dash",
    "grafix.core.effects.displace",
    "grafix.core.effects.wobble",
    "grafix.core.effects.affine",
    "grafix.core.effects.subdivide",
    "grafix.core.effects.quantize",
    "grafix.core.effects.pixelate",
    "grafix.core.effects.partition",
    "grafix.core.effects.mirror",
    "grafix.core.effects.mirror3d",
    "grafix.core.effects.metaball",
    "grafix.core.effects.isocontour",
    "grafix.core.effects.translate",
    "grafix.core.effects.extrude",
    "grafix.core.effects.repeat",
    "grafix.core.effects.buffer",
    "grafix.core.effects.bold",
    "grafix.core.effects.drop",
    "grafix.core.effects.trim",
    "grafix.core.effects.lowpass",
    "grafix.core.effects.highpass",
    "grafix.core.effects.clip",
    "grafix.core.effects.twist",
    "grafix.core.effects.weave",
    "grafix.core.effects.growth_in_mask",
    "grafix.core.effects.relax",
    "grafix.core.effects.reaction_diffusion",
    "grafix.core.effects.warp",
)

_BUILTIN_PRIMITIVES_REGISTERED = False
_BUILTIN_EFFECTS_REGISTERED = False


def ensure_builtin_primitives_registered() -> None:
    """組み込み primitive を registry に登録する（idempotent）。"""

    global _BUILTIN_PRIMITIVES_REGISTERED
    if _BUILTIN_PRIMITIVES_REGISTERED:
        return
    for module in _BUILTIN_PRIMITIVE_MODULES:
        importlib.import_module(module)
    _BUILTIN_PRIMITIVES_REGISTERED = True


def ensure_builtin_effects_registered() -> None:
    """組み込み effect を registry に登録する（idempotent）。"""

    global _BUILTIN_EFFECTS_REGISTERED
    if _BUILTIN_EFFECTS_REGISTERED:
        return
    for module in _BUILTIN_EFFECT_MODULES:
        importlib.import_module(module)
    _BUILTIN_EFFECTS_REGISTERED = True


def ensure_builtin_ops_registered() -> None:
    """組み込み primitive/effect をまとめて登録する（idempotent）。"""

    ensure_builtin_primitives_registered()
    ensure_builtin_effects_registered()


__all__ = [
    "ensure_builtin_effects_registered",
    "ensure_builtin_ops_registered",
    "ensure_builtin_primitives_registered",
]
