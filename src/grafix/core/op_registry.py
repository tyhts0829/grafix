"""primitive/effect が共有する immutable operation registry。"""

from __future__ import annotations

import inspect
from collections.abc import Callable, ItemsView, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Literal, TypeVar

from grafix.core.parameters.meta import ParamMeta

OpKind = Literal["primitive", "effect"]
CachePolicy = Literal["content", "none"]
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
    description: str = ""
    doc: str = ""
    source: str | None = None
    provenance: str = ""
    accepted_args: tuple[str, ...] = ()
    required_args: tuple[str, ...] = ()
    accepts_var_kwargs: bool = False
    cache_policy: CachePolicy = "content"

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
        object.__setattr__(self, "description", str(self.description))
        object.__setattr__(self, "doc", str(self.doc))
        object.__setattr__(self, "source", None if self.source is None else str(self.source))
        object.__setattr__(self, "provenance", str(self.provenance))
        object.__setattr__(
            self,
            "accepted_args",
            tuple(str(name) for name in self.accepted_args),
        )
        object.__setattr__(
            self,
            "required_args",
            tuple(str(name) for name in self.required_args),
        )
        object.__setattr__(self, "accepts_var_kwargs", bool(self.accepts_var_kwargs))
        if self.cache_policy not in {"content", "none"}:
            raise ValueError("cache_policy は 'content' または 'none' である必要がある")

        unknown_required = set(self.required_args) - set(self.accepted_args)
        if unknown_required:
            names = ", ".join(sorted(unknown_required))
            raise ValueError(f"required_args は accepted_args に含める必要がある: {names}")


@dataclass(frozen=True, slots=True)
class OpCatalogEntry(Generic[EvaluatorT]):
    """registry 内の operation 名と :class:`OpSpec` の immutable view。"""

    name: str
    spec: OpSpec[EvaluatorT]

    @property
    def kind(self) -> OpKind:
        """operation 種別。"""

        return self.spec.kind

    @property
    def n_inputs(self) -> int:
        """必要な Geometry 入力数。"""

        return self.spec.n_inputs

    @property
    def description(self) -> str:
        """docstring から抽出した短い説明。"""

        return self.spec.description

    @property
    def doc(self) -> str:
        """元 callable の正規化済み docstring。"""

        return self.spec.doc

    @property
    def source(self) -> str | None:
        """元 callable の source file。"""

        return self.spec.source

    @property
    def provenance(self) -> str:
        """元 callable の module/qualname。"""

        return self.spec.provenance

    @property
    def accepted_args(self) -> tuple[str, ...]:
        """元 callable が受け取る operation 引数名。"""

        return self.spec.accepted_args

    @property
    def required_args(self) -> tuple[str, ...]:
        """default を持たない operation 引数名。"""

        return self.spec.required_args

    @property
    def accepts_var_kwargs(self) -> bool:
        """元 callable が任意 keyword を受け入れるか。"""

        return self.spec.accepts_var_kwargs

    @property
    def cache_policy(self) -> CachePolicy:
        """operation結果のcache方針。"""

        return self.spec.cache_policy

    @property
    def defaults(self) -> Mapping[str, Any]:
        """GUI 対象引数の default。"""

        return self.spec.defaults

    @property
    def meta(self) -> Mapping[str, ParamMeta]:
        """parameter metadata。"""

        return self.spec.meta


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

    def replace_all(self, specs: Mapping[str, OpSpec[EvaluatorT]]) -> None:
        """検証済みspec集合へ一括置換し、revisionを一度だけ進める。

        source hot reloadがcandidate registryを隔離して組み立て、全検証成功後に
        live registryへcommitするためのtransaction境界である。
        """

        candidate: OpRegistry[EvaluatorT] = OpRegistry(kind=self._kind)
        for name, spec in specs.items():
            candidate.register(str(name), spec)
        self._specs = dict(candidate._specs)
        self._revision += 1

    def describe(self, name: str) -> OpCatalogEntry[EvaluatorT]:
        """登録済み operation の catalog entry を返す。"""

        name_s = str(name)
        return OpCatalogEntry(name=name_s, spec=self._specs[name_s])

    def catalog(self) -> tuple[OpCatalogEntry[EvaluatorT], ...]:
        """公開 operation の catalog entry を名前順で返す。"""

        return tuple(
            OpCatalogEntry(name=name, spec=self._specs[name])
            for name in sorted(self._specs)
            if not name.startswith("_")
        )


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


def op_callable_catalog_fields(
    *,
    kind: OpKind,
    func: Callable[..., object],
    n_inputs: int,
) -> dict[str, Any]:
    """元 callable から catalog 用の説明と signature 情報を抽出する。"""

    signature = inspect.signature(func)
    parameters = tuple(signature.parameters.values())
    if kind == "effect":
        parameters = parameters[int(n_inputs) :]

    accepted_args = tuple(
        parameter.name
        for parameter in parameters
        if parameter.kind
        not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    )
    required_args = tuple(
        parameter.name
        for parameter in parameters
        if parameter.kind
        not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        and parameter.default is inspect.Parameter.empty
    )

    doc = inspect.getdoc(func) or ""
    first_paragraph = doc.split("\n\n", 1)[0]
    description = " ".join(first_paragraph.splitlines()).strip()
    try:
        source = inspect.getsourcefile(func)
    except TypeError:
        source = None

    return {
        "description": description,
        "doc": doc,
        "source": source,
        "provenance": f"{func.__module__}:{func.__qualname__}",
        "accepted_args": accepted_args,
        "required_args": required_args,
        "accepts_var_kwargs": any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        ),
    }


__all__ = [
    "CachePolicy",
    "OpKind",
    "OpCatalogEntry",
    "OpRegistry",
    "OpSpec",
    "UiVisiblePred",
    "op_callable_catalog_fields",
    "op_defaults_and_order",
]
