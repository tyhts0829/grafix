# src/core/primitive_registry.py
# Geometry の primitive ノードに対応する operation spec を登録する。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from grafix.core.op_registry import (
    OpRegistry,
    OpSpec,
    UiVisiblePred,
    op_defaults_and_order,
)
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.meta_spec import meta_dict_from_user
from grafix.core.realized_geometry import (
    GeomTuple,
    RealizedGeometry,
    concat_realized_geometries,
    realized_geometry_from_tuple,
)

PrimitiveFunc = Callable[[tuple[tuple[str, Any], ...]], RealizedGeometry]
primitive_registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
"""グローバルな primitive レジストリインスタンス。"""


def primitive(
    func: Callable[..., GeomTuple] | None = None,
    *,
    overwrite: bool = False,
    meta: Mapping[str, ParamMeta | Mapping[str, object]] | None = None,
    ui_visible: Mapping[str, UiVisiblePred] | None = None,
):
    """グローバル primitive レジストリ用デコレータ。

    関数名をそのまま op 名として登録する。

    Parameters
    ----------
    func : Callable[..., GeomTuple] or None, optional
        デコレート対象の関数。ユーザー定義関数の戻り値は `(coords, offsets)` タプル。
        引数なしデコレータ利用時は None。
    overwrite : bool, optional
        既存エントリがある場合に上書きするかどうか。

    Examples
    --------
    @primitive
    def circle(*, r=1.0, cx=0.0, cy=0.0, segments=64):
        ...
        return coords, offsets
    """

    meta_norm = None if meta is None else meta_dict_from_user(meta)
    if meta_norm is not None:
        reserved = {"activate", "key"} & set(meta_norm)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"primitive の予約引数は meta に含められない: {names}")

    def decorator(
        f: Callable[..., GeomTuple],
    ) -> Callable[..., GeomTuple]:
        module = str(f.__module__)
        if meta_norm is None and (
            module.startswith("grafix.core.primitives.") or module.startswith("core.primitives.")
        ):
            raise ValueError(f"組み込み primitive は meta 必須: {f.__module__}.{f.__name__}")

        def wrapper(args: tuple[tuple[str, Any], ...]) -> RealizedGeometry:
            params: dict[str, Any] = dict(args)
            activate = bool(params.pop("activate", True))
            if not activate:
                return concat_realized_geometries()
            out = f(**params)
            return realized_geometry_from_tuple(
                out,
                context=f"@primitive {f.__module__}.{f.__name__}",
            )

        defaults: dict[str, Any] = {}
        param_order: tuple[str, ...] = ()
        meta_with_activate: dict[str, ParamMeta] = {}
        if meta_norm is not None:
            meta_with_activate = {"activate": ParamMeta(kind="bool"), **meta_norm}
            user_defaults, user_order = op_defaults_and_order(
                kind="primitive",
                func=f,
                meta=meta_norm,
            )
            defaults = {"activate": True, **user_defaults}
            param_order = ("activate", *user_order)

        spec: OpSpec[PrimitiveFunc] = OpSpec(
            evaluator=wrapper,
            meta=meta_with_activate,
            defaults=defaults,
            param_order=param_order,
            ui_visible={} if ui_visible is None else ui_visible,
            n_inputs=0,
            kind="primitive",
        )
        primitive_registry.register(
            f.__name__,
            spec,
            replace=overwrite,
        )
        return f

    if func is None:
        return decorator
    return decorator(func)


__all__ = ["PrimitiveFunc", "primitive", "primitive_registry"]
