# どこで: `src/grafix/api/effects.py`。
# 何を: effect 適用パイプラインを組み立てる公開名前空間 E を提供する。
# なぜ: effect 専用のファサードに分離し、責務を明確化するため。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal

# prune_ops が effect registry を参照するため、parameters package を先に初期化する。
from ._param_resolution import resolve_api_params, set_api_label
from ._operation_selector import (
    FrozenParamsByTarget,
    freeze_params_by_target,
    resolve_effect_selection,
    validate_effect_selector_n_inputs,
    validate_effect_selector_target,
)
from grafix.core.builtins import (
    ensure_builtin_effect_registered,
    ensure_builtin_effects_registered,
)
from grafix.core.effect_registry import EffectFunc
from grafix.core.geometry import Geometry
from grafix.core.op_registry import OpCatalogEntry, OpSpec
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
from grafix.core.parameters.identity import identity_string
from grafix.core.value_validation import exact_bool

# parameters package の初期化後に読み、prune_ops 経由の循環 import を避ける。
import grafix.core.effect_registry as effect_registry_module

from ._op_validation import validate_operation_kwargs
from ._unset import _UNSET_TARGET, _UnsetTarget


@dataclass(frozen=True, slots=True, init=False)
class _EffectOperationStep:
    """通常 effect の canonical immutable step。"""

    op: str
    args: tuple[tuple[str, Any], ...]
    site_id: str

    @property
    def parameter_op(self) -> str:
        """Parameter topology で使う operation 名。"""

        return self.op


@dataclass(frozen=True, slots=True, init=False)
class _EffectSelectorStep:
    """DAG 構築時に実 effect step へ lower する selector 設定。"""

    target: str
    target_explicit: bool
    n_inputs: int
    params_by_target: FrozenParamsByTarget
    site_id: str

    @property
    def parameter_op(self) -> str:
        """Parameter topology で使う selector operation 名。"""

        return effect_selector_op(self.n_inputs)


_EffectStep = _EffectOperationStep | _EffectSelectorStep


@dataclass(frozen=True, slots=True)
class _LoweredEffectStep:
    """通常 step / selector step を同じ DAG 構築形へ lower した値。"""

    parameter_op: str
    op: str
    args: tuple[tuple[str, Any], ...]
    site_id: str
    n_inputs: int


def _make_effect_operation_step(
    *,
    op: str,
    params: dict[str, Any],
    site_id: str,
) -> _EffectOperationStep:
    """検証済み通常 effect 引数を immutable step に固定する。"""

    step = object.__new__(_EffectOperationStep)
    object.__setattr__(step, "op", identity_string(op, name="effect step op"))
    object.__setattr__(step, "args", tuple(sorted(params.items())))
    object.__setattr__(
        step,
        "site_id",
        identity_string(site_id, name="effect step site_id"),
    )
    return step


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
        identity_string(target, name="effect selector target"),
        n_inputs=count,
    )
    frozen_params = freeze_params_by_target(
        params_by_target,
        kind="effect",
        n_inputs=count,
    )
    step = object.__new__(_EffectSelectorStep)
    object.__setattr__(step, "target", target_s)
    object.__setattr__(
        step,
        "target_explicit",
        exact_bool(
            target_explicit,
            name="effect selector target_explicit",
        ),
    )
    object.__setattr__(step, "n_inputs", count)
    object.__setattr__(step, "params_by_target", frozen_params)
    object.__setattr__(
        step,
        "site_id",
        identity_string(site_id, name="effect selector site_id"),
    )
    return step


def _lower_effect_step(
    step: _EffectStep,
    *,
    operation_spec: OpSpec[EffectFunc] | None,
) -> _LoweredEffectStep:
    """通常/selector step を一つの immutable DAG 引数形へ lower する。"""

    if isinstance(step, _EffectSelectorStep):
        selected = resolve_effect_selection(
            target=step.target,
            target_explicit=step.target_explicit,
            n_inputs=step.n_inputs,
            params_by_target=step.params_by_target,
            site_id=step.site_id,
        )
        return _LoweredEffectStep(
            parameter_op=step.parameter_op,
            op=selected.target,
            args=tuple(sorted(selected.params.items())),
            site_id=step.site_id,
            n_inputs=step.n_inputs,
        )

    if operation_spec is None:
        raise RuntimeError("通常 effect step の current spec がありません")
    spec = operation_spec
    current_params = validate_operation_kwargs(
        op=step.op,
        spec=spec,
        params=dict(step.args),
    )
    resolved = resolve_api_params(
        op=step.op,
        site_id=step.site_id,
        user_params=current_params,
        defaults=spec.defaults,
        meta=spec.meta,
    )
    return _LoweredEffectStep(
        parameter_op=step.parameter_op,
        op=step.op,
        args=tuple(sorted(resolved.items())),
        site_id=step.site_id,
        n_inputs=spec.n_inputs,
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
    Geometry に対する effect パイプラインを構築する。step と引数はすべて
    immutable tuple に固定されるため、builder は値として比較・hash 化できる。
    """

    steps: tuple[_EffectStep, ...]
    chain_id: str
    label_name: str | None = None

    def __post_init__(self) -> None:
        """step 列と identity を canonical immutable 形に限定する。"""

        if type(self.steps) is not tuple or any(
            type(step) not in {_EffectOperationStep, _EffectSelectorStep}
            for step in self.steps
        ):
            raise TypeError("EffectBuilder.steps は immutable effect step tuple が必要です")
        object.__setattr__(
            self,
            "chain_id",
            identity_string(self.chain_id, name="effect chain_id"),
        )
        if self.label_name is not None:
            object.__setattr__(
                self,
                "label_name",
                identity_string(self.label_name, name="effect label"),
            )

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
        operation_specs: list[OpSpec[EffectFunc] | None] = []
        for code_index, step in enumerate(self.steps):
            if isinstance(step, _EffectOperationStep):
                operation_spec = registry[step.op]
                n_inputs = operation_spec.n_inputs
            else:
                operation_spec = None
                n_inputs = step.n_inputs
            operation_specs.append(operation_spec)
            code_topology.append(
                EffectStepTopology(
                    op=step.parameter_op,
                    site_id=step.site_id,
                    n_inputs=n_inputs,
                    code_index=code_index,
                )
            )

        recording_enabled = current_param_recording_enabled()
        topology = tuple(code_topology)
        order_snapshot = current_effect_order_snapshot() if recording_enabled else {}
        order_override = order_snapshot.get(self.chain_id)
        if order_override is not None:
            topology_keys = tuple(step.key for step in topology)
            if (
                len(order_override) != len(topology_keys)
                or set(order_override) != set(topology_keys)
            ):
                # source reload で code topology が置換された最初の成功観測は
                # 新 topology を正本とする。context 終了時の merge が旧 override
                # を削除するまで、この evaluation だけ code order を使用する。
                order_override = None
        effective_topology = resolve_effective_steps(
            topology,
            order_override,
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
            lowered = _lower_effect_step(
                step,
                operation_spec=operation_specs[topology_step.code_index],
            )
            set_api_label(
                op=lowered.parameter_op,
                site_id=lowered.site_id,
                label=self.label_name,
            )

            # 直前までの result を inputs として 1 段 effect ノードを積む。
            # これを steps の数だけ繰り返すことでチェーン全体の DAG になる。
            n_inputs = lowered.n_inputs
            if step_index == 0:
                if len(first_inputs) != n_inputs:
                    raise TypeError(
                        f"effect {lowered.op!r} は入力 Geometry を {n_inputs} 個必要とします"
                    )
                inputs = first_inputs
            else:
                if n_inputs != 1:
                    raise TypeError(
                        "multi-input effect はチェーンの先頭にのみ使用できます"
                        f": {lowered.op!r}"
                    )
                inputs = (result,)
            result = Geometry._from_canonical_args(
                op=lowered.op,
                inputs=inputs,
                args=lowered.args,
            )
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
            params = validate_operation_kwargs(op=name, spec=spec, params=params)
            site_id = caller_site_id(
                skip=1,
                key=key,
                instance_key=instance_key,
                shared=shared,
            )
            new_steps = self.steps + (
                _make_effect_operation_step(
                    op=name,
                    params=params,
                    site_id=site_id,
                ),
            )
            return EffectBuilder(
                steps=new_steps,
                chain_id=self.chain_id,
                label_name=self.label_name,
            )

        return factory

    def select(
        self,
        *,
        target: str | _UnsetTarget = _UNSET_TARGET,
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
        target_explicit = target is not _UNSET_TARGET
        target_name = (
            identity_string(target, name="effect selector target")
            if target_explicit
            else "rotate"
        )
        step = _make_effect_selector_step(
            target=target_name,
            target_explicit=target_explicit,
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

        name_s = identity_string(name, name="effect name")
        if name_s not in effect_registry_module.effect_registry:
            ensure_builtin_effect_registered(name_s)
        if name_s not in effect_registry_module.effect_registry:
            raise KeyError(f"未登録の effect: {name_s!r}")
        return effect_registry_module.effect_registry.describe(name_s)

    def select(
        self,
        *,
        target: str | _UnsetTarget = _UNSET_TARGET,
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
        target_explicit = target is not _UNSET_TARGET
        target_name = (
            identity_string(target, name="effect selector target")
            if target_explicit
            else "rotate"
        )
        step = _make_effect_selector_step(
            target=target_name,
            target_explicit=target_explicit,
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
            params = validate_operation_kwargs(op=name, spec=spec, params=params)
            site_id = caller_site_id(
                skip=1,
                key=key,
                instance_key=instance_key,
                shared=shared,
            )
            return EffectBuilder(
                steps=(
                    _make_effect_operation_step(
                        op=name,
                        params=params,
                        site_id=site_id,
                    ),
                ),
                chain_id=site_id,
                label_name=self._pending_label,
            )

        return factory

    def __call__(self, name: str | None = None) -> "EffectNamespace":
        ns = EffectNamespace()
        ns._pending_label = (
            None if name is None else identity_string(name, name="effect label")
        )
        return ns

    _pending_label: str | None = None


E = EffectNamespace()
"""effect 適用パイプラインを構築する公開名前空間。"""

__all__ = ["E"]
