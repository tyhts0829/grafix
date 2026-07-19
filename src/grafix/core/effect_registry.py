# src/core/effect_registry.py
# Geometry の effect ノードに対応する operation spec を登録する。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Sequence

from grafix.core.op_registry import (
    CachePolicy,
    OpRegistry,
    OpSpec,
    UiVisiblePred,
    op_callable_catalog_fields,
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

EffectFunc = Callable[
    [Sequence[RealizedGeometry], tuple[tuple[str, Any], ...]],
    RealizedGeometry,
]
effect_registry: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
"""グローバルな effect レジストリインスタンス。"""

_EFFECT_ACTIVATE_META = ParamMeta(
    kind="bool",
    description="このエフェクトによる形状変換を有効にする。",
)


def effect(
    func: Callable[..., GeomTuple] | None = None,
    *,
    overwrite: bool = False,
    cache_policy: CachePolicy = "content",
    n_inputs: int = 1,
    meta: Mapping[str, ParamMeta | Mapping[str, object]] | None = None,
    ui_visible: Mapping[str, UiVisiblePred] | None = None,
):
    """グローバル effect レジストリ用デコレータ。

    関数名をそのまま op 名として登録する。

    Parameters
    ----------
    func : Callable[..., GeomTuple] or None, optional
        デコレート対象の関数。ユーザー定義関数の I/O は `(coords, offsets)` タプル。
        引数なしデコレータ利用時は None。
    overwrite : bool, optional
        既存エントリがある場合に上書きするかどうか。
    cache_policy : {"content", "none"}, optional
        ``"content"`` はpure/deterministicな結果を同一入力間で再利用する。
        乱数は明示 ``seed`` 引数を使う。時刻・global stateへ依存するeffectだけ
        ``"none"`` を指定してCPU/GPU cacheを迂回する。
    n_inputs : int, optional
        effect が受け取る入力 Geometry の数。1 以上を指定し、デコレート対象関数は
        その数の `(coords, offsets)` タプルを位置引数として受け取る。
    meta : Mapping[str, ParamMeta | Mapping[str, object]] or None, optional
        キーワード引数名から Parameter GUI 用 metadata への対応。組み込み effect
        では必須、ユーザー定義 effect では任意。ユーザー定義時は各 metadata の
        ``description`` も任意だが、GUI Help と生成 stub のため記述を推奨する。
        None の場合、引数を Parameter GUI に表示しない。
    ui_visible : Mapping[str, UiVisiblePred] or None, optional
        引数名から、現在の引数値を受け取って表示可否を返す述語への対応。
        Parameter GUI の表示だけを制御し、非表示になった引数の値は変更しない。

    Examples
    --------
    @effect
    def scale(g, *, scale=(1.0, 1.0, 1.0)):
        coords, offsets = g
        ...
        return coords, offsets
    """

    meta_norm = None if meta is None else meta_dict_from_user(meta)
    if meta_norm is not None:
        reserved = {"activate", "key"} & set(meta_norm)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"effect の予約引数は meta に含められない: {names}")

    n_inputs_i = int(n_inputs)
    if n_inputs_i < 1:
        raise ValueError("n_inputs は 1 以上である必要がある")

    def decorator(
        f: Callable[..., GeomTuple],
    ) -> Callable[..., GeomTuple]:
        module = str(f.__module__)
        if meta_norm is None and (
            module.startswith("grafix.core.effects.") or module.startswith("core.effects.")
        ):
            raise ValueError(f"組み込み effect は meta 必須: {f.__module__}.{f.__name__}")

        meta_with_activate = (
            {"activate": _EFFECT_ACTIVATE_META, **meta_norm}
            if meta_norm is not None
            else None
        )

        def wrapper(
            inputs: Sequence[RealizedGeometry],
            args: tuple[tuple[str, Any], ...],
        ) -> RealizedGeometry:
            params: dict[str, Any] = dict(args)
            activate = bool(params.pop("activate", True))
            if not activate:
                if not inputs:
                    return concat_realized_geometries()
                if len(inputs) == 1:
                    return inputs[0]
                return concat_realized_geometries(*inputs)
            if len(inputs) != n_inputs_i:
                raise TypeError(
                    f"effect '{f.__name__}' は入力 Geometry を {n_inputs_i} 個必要とします"
                    f"（受け取った数: {len(inputs)}）"
                )

            inputs_as_tuples = tuple((g.coords, g.offsets) for g in inputs)
            out = f(*inputs_as_tuples, **params)
            if isinstance(out, tuple) and len(out) == 2:
                out_coords, out_offsets = out
                for g in inputs:
                    if out_coords is g.coords and out_offsets is g.offsets:
                        return g
                    if out_offsets is g.offsets:
                        realized = g._with_coords(out_coords)
                        if realized is not None:
                            return realized
            return realized_geometry_from_tuple(
                out,
                context=f"@effect {f.__module__}.{f.__name__}",
            )

        defaults: dict[str, Any] = {}
        param_order: tuple[str, ...] = ()
        if meta_norm is not None:
            user_defaults, user_order = op_defaults_and_order(
                kind="effect",
                func=f,
                meta=meta_norm,
            )
            defaults = {"activate": True, **user_defaults}
            param_order = ("activate", *user_order)

        spec: OpSpec[EffectFunc] = OpSpec(
            evaluator=wrapper,
            meta={} if meta_with_activate is None else meta_with_activate,
            defaults=defaults,
            param_order=param_order,
            ui_visible={} if ui_visible is None else ui_visible,
            n_inputs=n_inputs_i,
            kind="effect",
            cache_policy=cache_policy,
            **op_callable_catalog_fields(
                kind="effect",
                func=f,
                n_inputs=n_inputs_i,
            ),
        )
        effect_registry.register(
            f.__name__,
            spec,
            replace=overwrite,
        )
        return f

    if func is None:
        return decorator
    return decorator(func)


__all__ = ["EffectFunc", "effect", "effect_registry"]
