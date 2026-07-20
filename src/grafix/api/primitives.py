# どこで: `src/grafix/api/primitives.py`。
# 何を: primitive Geometry ノードを生成する公開名前空間 G を提供する。
# なぜ: primitive 専用のファサードに分離し、責務を明確化するため。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from grafix.core.builtins import (
    ensure_builtin_primitive_registered,
    ensure_builtin_primitives_registered,
)
from grafix.core.geometry import Geometry
from grafix.core.op_registry import OpCatalogEntry
from grafix.core.parameters import caller_site_id
from grafix.core.primitive_registry import PrimitiveFunc

# parameters package の初期化後に読み、prune_ops 経由の循環 import を避ける。
import grafix.core.primitive_registry as primitive_registry_module

from ._op_validation import validate_operation_kwargs
from ._operation_selector import (
    freeze_params_by_target,
    resolve_primitive_selection,
)
from ._param_resolution import resolve_api_params, set_api_label


class _PrimitiveDefaultTarget(str):
    """target 省略と明示的な ``"circle"`` を区別する内部 marker。"""


_DEFAULT_TARGET = _PrimitiveDefaultTarget("circle")


class PrimitiveNamespace:
    """primitive Geometry ノードを生成する名前空間。

    Attributes
    ----------
    <name> : Callable[..., Geometry]
        登録済み primitive 名ごとのファクトリ。
        例: G.circle(r=1.0) -> Geometry(op="circle", inputs=(), params=...)
    """

    def catalog(self) -> tuple[OpCatalogEntry[PrimitiveFunc], ...]:
        """登録済み primitive の catalog を名前順で返す。

        Returns
        -------
        tuple[OpCatalogEntry[PrimitiveFunc], ...]
            名前、説明、引数、source を含む immutable entry の列。
        """

        ensure_builtin_primitives_registered()
        return primitive_registry_module.primitive_registry.catalog()

    def describe(self, name: str) -> OpCatalogEntry[PrimitiveFunc]:
        """primitive の catalog entry を名前で取得する。

        Parameters
        ----------
        name : str
            primitive 名。

        Returns
        -------
        OpCatalogEntry[PrimitiveFunc]
            registry の :class:`~grafix.core.op_registry.OpSpec` を参照する entry。

        Raises
        ------
        KeyError
            ``name`` が未登録の場合。
        """

        name_s = str(name)
        if name_s not in primitive_registry_module.primitive_registry:
            ensure_builtin_primitive_registered(name_s)
        if name_s not in primitive_registry_module.primitive_registry:
            raise KeyError(f"未登録の primitive: {name_s!r}")
        return primitive_registry_module.primitive_registry.describe(name_s)

    def select(
        self,
        *,
        target: str = _DEFAULT_TARGET,
        params_by_target: Mapping[str, Mapping[str, Any]] | None = None,
        key: str | int | None = None,
        instance_key: str | int | None = None,
        shared: bool = False,
    ) -> Geometry:
        """登録済み primitive を選択して実 target の Geometry を生成する。

        Parameters
        ----------
        target : str, optional
            code 側の初期 primitive 名。Parameter GUI から上書きできる。
        params_by_target : Mapping[str, Mapping[str, Any]] or None, optional
            primitive 名ごとの base keyword 引数。
        key : str or int or None, optional
            コード移動に強い semantic parameter identity。
        instance_key : str or int or None, optional
            loop/comprehension の反復 instance identity。
        shared : bool, optional
            同じ semantic site を反復呼び出し間で共有するか。

        Returns
        -------
        Geometry
            選択された実 primitive を op に持つ Geometry。
        """

        frozen_params = freeze_params_by_target(
            params_by_target,
            kind="primitive",
        )
        site_id = caller_site_id(
            skip=1,
            key=key,
            instance_key=instance_key,
            shared=shared,
        )
        selected = resolve_primitive_selection(
            target=str(target),
            target_explicit=target is not _DEFAULT_TARGET,
            params_by_target=frozen_params,
            site_id=site_id,
        )
        set_api_label(
            op=selected.selector_op,
            site_id=site_id,
            label=self._pending_label,
        )
        return Geometry.create(op=selected.target, params=selected.params)

    def __getattr__(self, name: str) -> Callable[..., Geometry]:
        """primitive 名に対応する Geometry ファクトリを返す。

        Parameters
        ----------
        name : str
            primitive 名。

        Returns
        -------
        Callable[..., Geometry]
            Geometry ノードを生成する関数。

        Raises
        ------
        AttributeError
            未登録の primitive 名が指定された場合。
        """
        if name.startswith("_"):
            raise AttributeError(name)

        if name not in primitive_registry_module.primitive_registry:
            ensure_builtin_primitive_registered(name)
        if name not in primitive_registry_module.primitive_registry:
            raise AttributeError(f"未登録の primitive: {name!r}")

        def factory(**params: Any) -> Geometry:
            """primitive Geometry ノードを生成する。

            Parameters
            ----------
            **params : Any
                primitive に渡すパラメータ辞書。

            Returns
            -------
            Geometry
                生成された Geometry ノード。
            """

            spec = primitive_registry_module.primitive_registry[name]
            key = params.pop("key", None)
            instance_key = params.pop("instance_key", None)
            shared = params.pop("shared", False)
            validate_operation_kwargs(op=name, spec=spec, params=params)

            # key は semantic site、instance_key は loop/comprehension 内の個体を表す。
            # shared=True は個体 suffix を付けず、同じ semantic site を意図的に共有する。
            site_id = caller_site_id(
                skip=1,
                key=key,
                instance_key=instance_key,
                shared=shared,
            )

            # ParamStore が利用できるコンテキスト（parameter_context）内なら、
            # G(name="...") のラベル情報を (op, site_id) に紐づけて保存する。
            # GUI 側でヘッダ表示に利用する想定。
            set_api_label(op=name, site_id=site_id, label=self._pending_label)

            # meta: GUI 表示対象や UI レンジなどの情報（組み込み primitive は meta ありを前提）。
            # defaults: meta に含まれる引数について、関数シグネチャから抽出した安全なデフォルト値。
            # これにより、G.circle() のように kwargs を省略しても ParamStore にキーが観測され、
            # GUI が空になりにくい。
            resolved = resolve_api_params(
                op=name,
                site_id=site_id,
                user_params=params,
                defaults=spec.defaults,
                meta=spec.meta,
            )
            # resolved は Geometry.create に渡され、正規化・署名化される。
            # primitive は inputs を持たないため op と params のみでノードが確定する。
            return Geometry.create(op=name, params=resolved)

        return factory

    def __call__(self, name: str | None = None) -> "PrimitiveNamespace":
        ns = PrimitiveNamespace()
        ns._pending_label = name  # type: ignore[attr-defined]
        return ns

    _pending_label: str | None = None


G = PrimitiveNamespace()
"""primitive Geometry ノードを生成する公開名前空間。"""

__all__ = ["G"]
