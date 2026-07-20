# どこで: `src/grafix/api/effects.py`。
# 何を: effect 適用パイプラインを組み立てる公開名前空間 E を提供する。
# なぜ: effect 専用のファサードに分離し、責務を明確化するため。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal

from ._param_resolution import resolve_api_params, set_api_label
from ._operation_selector import (
    FrozenParamsByTarget,
    freeze_params_by_target,
    resolve_effect_selection,
    validate_effect_selector_n_inputs,
    validate_effect_selector_target,
)
from grafix.core.builtins import ensure_builtin_effect_registered, ensure_builtin_effects_registered
from grafix.core.effect_registry import EffectFunc
from grafix.core.geometry import Geometry
from grafix.core.op_registry import OpCatalogEntry
from grafix.core.operation_selector import effect_selector_op
from grafix.core.parameters import (
    caller_site_id,
    current_effect_order_snapshot,
    current_frame_params,
)
from grafix.core.parameters.context import current_param_recording_enabled
from grafix.core.parameters.effects import (
    EffectStepTopology,
    resolve_effective_steps,
)

# parameters package の初期化後に読み、prune_ops 経由の循環 import を避ける。
import grafix.core.effect_registry as effect_registry_module

from ._op_validation import validate_operation_kwargs


class _EffectDefaultTarget(str):
    """target 省略と明示的な ``"rotate"`` を区別する内部 marker。"""


_DEFAULT_TARGET = _EffectDefaultTarget("rotate")


@dataclass(frozen=True, slots=True)
class _EffectSelectorStep:
    """DAG 構築時に実 effect step へ lower する selector 設定。"""

    target: str
    target_explicit: bool
    n_inputs: int
    params_by_target: FrozenParamsByTarget
    site_id: str


_EffectStep = tuple[str, dict[str, Any], str] | _EffectSelectorStep


def _make_effect_selector_step(
    *,
    target: str,
    target_explicit: bool,
    n_inputs: int,
    params_by_target: Mapping[str, Mapping[str, Any]] | None,
    site_id: str,
) -> _EffectSelectorStep:
    """公開 selector 引数を検証済み immutable step へ変換する。"""

    count = validate_effect_selector_n_inputs(n_inputs)
    target_s = validate_effect_selector_target(
        str(target),
        n_inputs=count,
    )
    frozen_params = freeze_params_by_target(
        params_by_target,
        kind="effect",
        n_inputs=count,
    )
    return _EffectSelectorStep(
        target=target_s,
        target_explicit=bool(target_explicit),
        n_inputs=count,
        params_by_target=frozen_params,
        site_id=str(site_id),
    )


@dataclass(frozen=True, slots=True)
class EffectBuilder:
    """effect 適用パイプラインを表現するビルダ。

    Parameters
    ----------
    steps : tuple[_EffectStep, ...]
        通常 effect または selector の immutable step 列。

    Notes
    -----
    E.scale(...).rotate(...)(g) のようにメソッドチェーンで
    Geometry に対する effect パイプラインを構築する。
    """

    steps: tuple[_EffectStep, ...]
    chain_id: str
    label_name: str | None = None

    def __call__(self, geometry: Geometry, *more_geometries: Geometry) -> Geometry:
        """保持している effect 列を Geometry に適用する。

        Parameters
        ----------
        geometry : Geometry
            入力 Geometry（1 つ目）。
        *more_geometries : Geometry
            追加入力 Geometry（multi-input effect 用）。

        Returns
        -------
        Geometry
            すべての effect を適用した Geometry。
        """
        # effect チェーンは「入力 Geometry に対して、steps を順番に wrap していく」だけの処理。
        # ここでは実体変換は行わず、あくまで Geometry DAG（レシピ）を構築する。
        registry = effect_registry_module.effect_registry
        code_topology: list[EffectStepTopology] = []
        for code_index, step in enumerate(self.steps):
            if isinstance(step, _EffectSelectorStep):
                parameter_op = effect_selector_op(step.n_inputs)
                n_inputs = int(step.n_inputs)
                site_id = step.site_id
            else:
                parameter_op, _params, site_id = step
                n_inputs = int(registry[parameter_op].n_inputs)
            code_topology.append(
                EffectStepTopology(
                    op=parameter_op,
                    site_id=site_id,
                    n_inputs=n_inputs,
                    code_index=code_index,
                )
            )

        recording_enabled = current_param_recording_enabled()
        topology = tuple(code_topology)
        order_snapshot = current_effect_order_snapshot() if recording_enabled else {}
        effective_topology = resolve_effective_steps(
            topology,
            order_snapshot.get(self.chain_id),
        )
        frame_params = current_frame_params()
        if recording_enabled and frame_params is not None:
            frame_params.record_effect_chain(
                chain_id=self.chain_id,
                steps=topology,
            )

        first_inputs = (geometry, *more_geometries)
        result = geometry
        for step_index, topology_step in enumerate(effective_topology):
            step = self.steps[topology_step.code_index]
            if isinstance(step, _EffectSelectorStep):
                selected = resolve_effect_selection(
                    target=step.target,
                    target_explicit=step.target_explicit,
                    n_inputs=step.n_inputs,
                    params_by_target=step.params_by_target,
                    site_id=step.site_id,
                    chain_id=self.chain_id,
                    step_index=int(step_index),
                )
                set_api_label(
                    op=selected.selector_op,
                    site_id=step.site_id,
                    label=self.label_name,
                )
                n_inputs = int(step.n_inputs)
                if step_index == 0:
                    if len(first_inputs) != n_inputs:
                        raise TypeError(
                            f"effect {selected.target!r} は入力 Geometry を "
                            f"{n_inputs} 個必要とします"
                        )
                    inputs = first_inputs
                else:
                    if n_inputs != 1:
                        raise TypeError(
                            "multi-input effect はチェーンの先頭にのみ使用できます"
                            f": {selected.target!r}"
                        )
                    inputs = (result,)
                result = Geometry.create(
                    op=selected.target,
                    inputs=inputs,
                    params=selected.params,
                )
                continue

            op, params, site_id = step
            # site_id は「その effect ステップが宣言された呼び出し箇所」。
            # 例: E.scale(...).rotate(...)(g) の scale と rotate を別の GUI 行として扱うため、
            # apply（__call__）時点ではなく「ステップ追加時点」で固定された site_id を使う。
            spec = registry[op]

            resolved = resolve_api_params(
                op=op,
                site_id=site_id,
                user_params=params,
                defaults=spec.defaults,
                meta=spec.meta,
                chain_id=self.chain_id,
                step_index=int(step_index),
            )

            # E(name="...") で付与されたラベルは、各ステップの (op, site_id) に保存する。
            # GUI 側でヘッダ表示などに使う想定。
            set_api_label(op=op, site_id=site_id, label=self.label_name)

            # 直前までの result を inputs として 1 段 effect ノードを積む。
            # これを steps の数だけ繰り返すことでチェーン全体の DAG になる。
            n_inputs = spec.n_inputs
            if step_index == 0:
                if len(first_inputs) != n_inputs:
                    raise TypeError(
                        f"effect {op!r} は入力 Geometry を {n_inputs} 個必要とします"
                    )
                inputs = first_inputs
            else:
                if n_inputs != 1:
                    raise TypeError(
                        f"multi-input effect はチェーンの先頭にのみ使用できます: {op!r}"
                    )
                inputs = (result,)
            result = Geometry.create(op=op, inputs=inputs, params=resolved)
        return result

    def __getattr__(self, name: str) -> Callable[..., "EffectBuilder"]:
        """effect 名に対応するチェーン用ファクトリを返す。

        Parameters
        ----------
        name : str
            effect 名。

        Returns
        -------
        Callable[..., EffectBuilder]
            追加の effect を連結した新しい EffectBuilder を返す関数。

        Raises
        ------
        AttributeError
            未登録の effect 名が指定された場合。
        """
        if name.startswith("_"):
            raise AttributeError(name)

        if name not in effect_registry_module.effect_registry:
            ensure_builtin_effect_registered(name)
        if name not in effect_registry_module.effect_registry:
            raise AttributeError(f"未登録の effect: {name!r}")

        def factory(**params: Any) -> "EffectBuilder":
            """effect を 1 つ追加した EffectBuilder を生成する。

            Parameters
            ----------
            **params : Any
                effect に渡すパラメータ辞書。

            Returns
            -------
            EffectBuilder
                既存の steps に 1 つ追加したビルダ。
            """

            key = params.pop("key", None)
            instance_key = params.pop("instance_key", None)
            shared = params.pop("shared", False)
            spec = effect_registry_module.effect_registry[name]
            validate_operation_kwargs(op=name, spec=spec, params=params)
            site_id = caller_site_id(
                skip=1,
                key=key,
                instance_key=instance_key,
                shared=shared,
            )
            new_steps = self.steps + ((name, dict(params), site_id),)
            return EffectBuilder(
                steps=new_steps,
                chain_id=self.chain_id,
                label_name=self.label_name,
            )

        return factory

    def select(
        self,
        *,
        target: str = _DEFAULT_TARGET,
        n_inputs: Literal[1] = 1,
        params_by_target: Mapping[str, Mapping[str, Any]] | None = None,
        key: str | int | None = None,
        instance_key: str | int | None = None,
        shared: bool = False,
    ) -> "EffectBuilder":
        """チェーン末尾へ arity 互換な effect selector を追加する。

        Parameters
        ----------
        target : str, optional
            code 側の初期 effect 名。Parameter GUI から上書きできる。
        n_inputs : int, optional
            選択候補の入力 Geometry 数。チェーン中段では 1 のみ指定できる。
        params_by_target : Mapping[str, Mapping[str, Any]] or None, optional
            effect 名ごとの base keyword 引数。
        key : str or int or None, optional
            コード移動に強い semantic parameter identity。
        instance_key : str or int or None, optional
            loop/comprehension の反復 instance identity。
        shared : bool, optional
            同じ semantic site を反復呼び出し間で共有するか。

        Returns
        -------
        EffectBuilder
            selector step を追加した immutable builder。
        """

        count = validate_effect_selector_n_inputs(n_inputs)
        if self.steps and count != 1:
            raise TypeError(
                "multi-input effect selector はチェーンの先頭にのみ使用できます"
            )
        site_id = caller_site_id(
            skip=1,
            key=key,
            instance_key=instance_key,
            shared=shared,
        )
        step = _make_effect_selector_step(
            target=str(target),
            target_explicit=target is not _DEFAULT_TARGET,
            n_inputs=count,
            params_by_target=params_by_target,
            site_id=site_id,
        )
        return EffectBuilder(
            steps=(*self.steps, step),
            chain_id=self.chain_id,
            label_name=self.label_name,
        )


class EffectNamespace:
    """effect ビルダを提供する名前空間。

    Attributes
    ----------
    <name> : Callable[..., EffectBuilder]
        登録済み effect 名ごとのビルダファクトリ。
        例: E.scale(scale=(2.0, 2.0, 2.0))(g) -> Geometry(op="scale", inputs=(g,), params=...)
    """

    def catalog(self) -> tuple[OpCatalogEntry[EffectFunc], ...]:
        """登録済み effect の catalog を名前順で返す。

        Returns
        -------
        tuple[OpCatalogEntry[EffectFunc], ...]
            名前、説明、引数、source を含む immutable entry の列。
        """

        ensure_builtin_effects_registered()
        return effect_registry_module.effect_registry.catalog()

    def describe(self, name: str) -> OpCatalogEntry[EffectFunc]:
        """effect の catalog entry を名前で取得する。

        Parameters
        ----------
        name : str
            effect 名。

        Returns
        -------
        OpCatalogEntry[EffectFunc]
            registry の :class:`~grafix.core.op_registry.OpSpec` を参照する entry。

        Raises
        ------
        KeyError
            ``name`` が未登録の場合。
        """

        name_s = str(name)
        if name_s not in effect_registry_module.effect_registry:
            ensure_builtin_effect_registered(name_s)
        if name_s not in effect_registry_module.effect_registry:
            raise KeyError(f"未登録の effect: {name_s!r}")
        return effect_registry_module.effect_registry.describe(name_s)

    def select(
        self,
        *,
        target: str = _DEFAULT_TARGET,
        n_inputs: int = 1,
        params_by_target: Mapping[str, Mapping[str, Any]] | None = None,
        key: str | int | None = None,
        instance_key: str | int | None = None,
        shared: bool = False,
    ) -> EffectBuilder:
        """登録済み effect を選択する builder を返す。

        Parameters
        ----------
        target : str, optional
            code 側の初期 effect 名。Parameter GUI から上書きできる。
        n_inputs : int, optional
            選択候補と適用時の入力 Geometry 数。
        params_by_target : Mapping[str, Mapping[str, Any]] or None, optional
            effect 名ごとの base keyword 引数。
        key : str or int or None, optional
            コード移動に強い semantic parameter identity。
        instance_key : str or int or None, optional
            loop/comprehension の反復 instance identity。
        shared : bool, optional
            同じ semantic site を反復呼び出し間で共有するか。

        Returns
        -------
        EffectBuilder
            適用時に選択 target へ lower する immutable builder。
        """

        site_id = caller_site_id(
            skip=1,
            key=key,
            instance_key=instance_key,
            shared=shared,
        )
        step = _make_effect_selector_step(
            target=str(target),
            target_explicit=target is not _DEFAULT_TARGET,
            n_inputs=n_inputs,
            params_by_target=params_by_target,
            site_id=site_id,
        )
        return EffectBuilder(
            steps=(step,),
            chain_id=site_id,
            label_name=self._pending_label,
        )

    def __getattr__(self, name: str) -> Callable[..., EffectBuilder]:
        """effect 名に対応する EffectBuilder ファクトリを返す。

        Parameters
        ----------
        name : str
            effect 名。

        Returns
        -------
        Callable[..., EffectBuilder]
            EffectBuilder を返す関数。

        Raises
        ------
        AttributeError
            未登録の effect 名が指定された場合。
        """
        if name.startswith("_"):
            raise AttributeError(name)

        if name not in effect_registry_module.effect_registry:
            ensure_builtin_effect_registered(name)
        if name not in effect_registry_module.effect_registry:
            raise AttributeError(f"未登録の effect: {name!r}")

        def factory(**params: Any) -> EffectBuilder:
            """単一 effect からなる EffectBuilder を生成する。

            Parameters
            ----------
            **params : Any
                effect に渡すパラメータ辞書。

            Returns
            -------
            EffectBuilder
                1 つの effect を保持するビルダ。
            """

            key = params.pop("key", None)
            instance_key = params.pop("instance_key", None)
            shared = params.pop("shared", False)
            spec = effect_registry_module.effect_registry[name]
            validate_operation_kwargs(op=name, spec=spec, params=params)
            site_id = caller_site_id(
                skip=1,
                key=key,
                instance_key=instance_key,
                shared=shared,
            )
            return EffectBuilder(
                steps=((name, dict(params), site_id),),
                chain_id=site_id,
                label_name=self._pending_label,
            )

        return factory

    def __call__(self, name: str | None = None) -> "EffectNamespace":
        ns = EffectNamespace()
        ns._pending_label = name  # type: ignore[attr-defined]
        return ns

    _pending_label: str | None = None


E = EffectNamespace()
"""effect 適用パイプラインを構築する公開名前空間。"""

__all__ = ["E"]
