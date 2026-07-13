"""primitive/effect が共有する immutable operation registry。"""

from __future__ import annotations

import inspect
from collections.abc import Callable, ItemsView, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Literal, TypeVar

from grafix.core.parameters.meta import ParamMeta

OpKind = Literal["primitive", "effect"]
UiVisiblePred = Callable[[Mapping[str, Any]], bool]
EvaluatorT = TypeVar("EvaluatorT", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class OpSpec(Generic[EvaluatorT]):
    """1 operation の evaluator と静的メタデータをまとめた仕様。"""

    evaluator: EvaluatorT
    meta: Mapping[str, ParamMeta]
    defaults: Mapping[str, Any]
    param_order: tuple[str, ...]
    ui_visible: Mapping[str, UiVisiblePred]
    n_inputs: int
    kind: OpKind

    def __post_init__(self) -> None:
        """mutable な入力 mapping をコピーし、spec 全体を不変にする。"""

        n_inputs = int(self.n_inputs)
        if self.kind == "primitive":
            if n_inputs != 0:
                raise ValueError("primitive の n_inputs は 0 である必要がある")
        elif self.kind == "effect":
            if n_inputs < 1:
                raise ValueError("effect の n_inputs は 1 以上である必要がある")
        else:
            raise ValueError(f"未対応の operation kind: {self.kind!r}")

        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))
        object.__setattr__(self, "defaults", MappingProxyType(dict(self.defaults)))
        object.__setattr__(self, "param_order", tuple(str(name) for name in self.param_order))
        object.__setattr__(self, "ui_visible", MappingProxyType(dict(self.ui_visible)))
        object.__setattr__(self, "n_inputs", n_inputs)


class OpRegistry(Generic[EvaluatorT]):
    """operation 名から immutable :class:`OpSpec` を引くレジストリ。"""

    def __init__(self, *, kind: OpKind) -> None:
        if kind not in {"primitive", "effect"}:
            raise ValueError(f"未対応の operation kind: {kind!r}")
        self._kind = kind
        self._specs: dict[str, OpSpec[EvaluatorT]] = {}
        self._revision = 0

    @property
    def kind(self) -> OpKind:
        """このレジストリが受け付ける operation 種別。"""

        return self._kind

    @property
    def revision(self) -> int:
        """登録または明示的 replace ごとに増える単調増加 revision。"""

        return self._revision

    def register(
        self,
        name: str,
        spec: OpSpec[EvaluatorT],
        *,
        replace: bool = False,
    ) -> None:
        """spec を登録する。既存 operation の置換は明示指定を必須とする。"""

        name_s = str(name)
        if name_s == "concat":
            raise ValueError("'concat' は Grafix 内部予約 operation のため登録できない")
        if spec.kind != self._kind:
            raise ValueError(f"{self._kind} registry に {spec.kind} spec は登録できない")
        if name_s in self._specs and not replace:
            raise ValueError(f"{self._kind} '{name_s}' は既に登録されている")

        self._specs[name_s] = spec
        self._revision += 1

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._specs

    def __getitem__(self, name: str) -> OpSpec[EvaluatorT]:
        return self._specs[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def items(self) -> ItemsView[str, OpSpec[EvaluatorT]]:
        """登録済みの ``(name, spec)`` view を返す。"""

        return self._specs.items()


def op_defaults_and_order(
    *,
    kind: OpKind,
    func: Callable[..., object],
    meta: Mapping[str, ParamMeta],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """関数 signature と meta を検証し、default と引数順を返す。"""

    signature = inspect.signature(func)
    defaults: dict[str, Any] = {}
    for arg in meta:
        parameter = signature.parameters.get(arg)
        if parameter is None:
            raise ValueError(
                f"{kind} '{func.__name__}' の meta 引数がシグネチャに存在しない: {arg!r}"
            )
        if parameter.default is inspect.Parameter.empty:
            raise ValueError(f"{kind} '{func.__name__}' の meta 引数は default 必須: {arg!r}")
        if parameter.default is None:
            raise ValueError(
                f"{kind} '{func.__name__}' の meta 引数 default に None は使えない: {arg!r}"
            )
        defaults[arg] = parameter.default

    order = tuple(name for name in signature.parameters if name in meta)
    return defaults, order


__all__ = [
    "OpKind",
    "OpRegistry",
    "OpSpec",
    "UiVisiblePred",
    "op_defaults_and_order",
]
