"""primitive/effect が共有する immutable operation registry。"""

from __future__ import annotations

import inspect
from collections.abc import Callable, ItemsView, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Literal, TypeVar, cast

from grafix.core.parameters.identity import identity_string
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.validation import validate_parameter_value
from grafix.core.value_validation import (
    canonical_immutable_value,
    exact_bool,
    exact_integer,
    exact_string,
    exact_string_choice,
)

OpKind = Literal["primitive", "effect"]
CachePolicy = Literal["content", "none"]
UiVisiblePred = Callable[[Mapping[str, Any]], bool]
EvaluatorT = TypeVar("EvaluatorT", bound=Callable[..., Any])
_WRAPPER_OWNED_ARGUMENTS = frozenset(
    {"activate", "instance_key", "key", "shared"}
)


def _operation_parameters(
    *,
    kind: OpKind,
    func: Callable[..., object],
    n_inputs: int,
) -> tuple[inspect.Parameter, ...]:
    """wrapper が呼び出せる callable signature を検証して引数列を返す。"""

    parameters = tuple(inspect.signature(func).parameters.values())
    if kind == "effect":
        if len(parameters) < n_inputs:
            raise TypeError(
                f"effect '{func.__name__}' は Geometry 入力を {n_inputs} 個"
                "位置引数として宣言する必要があります"
            )
        geometry_parameters = parameters[:n_inputs]
        for parameter in geometry_parameters:
            if parameter.kind not in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }:
                raise TypeError(
                    f"effect '{func.__name__}' の Geometry 入力 {parameter.name!r} は"
                    "位置引数である必要があります"
                )
            if parameter.default is not inspect.Parameter.empty:
                raise TypeError(
                    f"effect '{func.__name__}' の Geometry 入力 {parameter.name!r} に"
                    "default は指定できません"
                )
        operation_parameters = parameters[n_inputs:]
    else:
        operation_parameters = parameters

    for parameter in operation_parameters:
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise TypeError(
                f"{kind} '{func.__name__}' の operation 引数 {parameter.name!r} は"
                "keyword で受け取れる必要があります"
            )
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            raise TypeError(
                f"{kind} '{func.__name__}' に可変位置引数は使用できません"
            )

    reserved = sorted(
        parameter.name
        for parameter in parameters
        if parameter.name in _WRAPPER_OWNED_ARGUMENTS
    )
    if reserved:
        raise ValueError(
            f"{kind} '{func.__name__}' の wrapper 予約引数は使用できません: "
            f"{reserved!r}"
        )
    return operation_parameters


def _validate_code_default(value: object, *, name: str) -> None:
    """code-owned default が Geometry の canonical immutable 値か検証する。"""

    canonical_immutable_value(value, name=name)


@dataclass(frozen=True, slots=True)
class OpSpec(Generic[EvaluatorT]):
    """1 operation の evaluator と静的メタデータをまとめた仕様。

    Notes
    -----
    ``ui_visible`` mapping はコピーして固定するが、predicate 自体は実行時 policy
    であるため同一 callable を保持する。closure 内部状態の所有は登録側が担う。
    """

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

        kind = exact_string_choice(
            self.kind,
            name="kind",
            choices=("primitive", "effect"),
        )
        if kind == "primitive":
            n_inputs = exact_integer(self.n_inputs, name="n_inputs", minimum=0)
            if n_inputs != 0:
                raise ValueError("primitive の n_inputs は 0 である必要がある")
        else:
            n_inputs = exact_integer(self.n_inputs, name="n_inputs", minimum=1)

        meta: dict[str, ParamMeta] = {}
        for raw_name, raw_meta in self.meta.items():
            name = identity_string(raw_name, name="meta argument")
            if type(raw_meta) is not ParamMeta:
                raise TypeError(f"meta[{name!r}] は ParamMeta である必要があります")
            meta[name] = raw_meta

        raw_defaults: dict[str, Any] = {}
        for raw_name, raw_default in self.defaults.items():
            name = identity_string(raw_name, name="default argument")
            raw_defaults[name] = raw_default
        if set(raw_defaults) != set(meta):
            missing = sorted(set(meta) - set(raw_defaults))
            extra = sorted(set(raw_defaults) - set(meta))
            details: list[str] = []
            if missing:
                details.append(f"default が無い meta: {missing!r}")
            if extra:
                details.append(f"meta が無い default: {extra!r}")
            raise ValueError("meta/default の引数集合が一致しません: " + "; ".join(details))
        defaults = {
            name: validate_parameter_value(
                raw_defaults[name],
                kind=arg_meta.kind,
                choices=arg_meta.choices,
            )
            for name, arg_meta in meta.items()
        }

        object.__setattr__(self, "meta", MappingProxyType(meta))
        object.__setattr__(self, "defaults", MappingProxyType(defaults))
        object.__setattr__(
            self,
            "param_order",
            tuple(
                identity_string(name, name="param_order item")
                for name in self.param_order
            ),
        )
        ui_visible: dict[str, UiVisiblePred] = {}
        for raw_name, predicate in self.ui_visible.items():
            name = identity_string(raw_name, name="ui_visible argument")
            if not callable(predicate):
                raise TypeError(
                    f"ui_visible[{name!r}] は callable である必要があります"
                )
            ui_visible[name] = predicate
        object.__setattr__(self, "ui_visible", MappingProxyType(ui_visible))
        object.__setattr__(self, "n_inputs", n_inputs)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "description",
            exact_string(self.description, name="description"),
        )
        object.__setattr__(self, "doc", exact_string(self.doc, name="doc"))
        object.__setattr__(
            self,
            "source",
            (
                None
                if self.source is None
                else exact_string(self.source, name="source")
            ),
        )
        object.__setattr__(
            self,
            "provenance",
            exact_string(self.provenance, name="provenance"),
        )
        object.__setattr__(
            self,
            "accepted_args",
            tuple(
                identity_string(name, name="accepted_args item")
                for name in self.accepted_args
            ),
        )
        object.__setattr__(
            self,
            "required_args",
            tuple(
                identity_string(name, name="required_args item")
                for name in self.required_args
            ),
        )
        object.__setattr__(
            self,
            "accepts_var_kwargs",
            exact_bool(self.accepts_var_kwargs, name="accepts_var_kwargs"),
        )
        object.__setattr__(
            self,
            "cache_policy",
            exact_string_choice(
                self.cache_policy,
                name="cache_policy",
                choices=("content", "none"),
            ),
        )

        unknown_required = set(self.required_args) - set(self.accepted_args)
        if unknown_required:
            names = ", ".join(sorted(unknown_required))
            raise ValueError(f"required_args は accepted_args に含める必要がある: {names}")

        if len(self.param_order) != len(self.meta) or set(self.param_order) != set(
            self.meta
        ):
            raise ValueError("param_order は meta の引数を過不足なく含める必要がある")
        unknown_visible = set(self.ui_visible) - set(self.meta)
        if unknown_visible:
            names = ", ".join(sorted(unknown_visible))
            raise ValueError(f"ui_visible の引数は meta に含める必要がある: {names}")


@dataclass(frozen=True, slots=True)
class OpCatalogEntry(Generic[EvaluatorT]):
    """registry 内の operation 名と :class:`OpSpec` の immutable view。"""

    name: str
    spec: OpSpec[EvaluatorT]

    def __post_init__(self) -> None:
        identity_string(self.name, name="operation name")

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
        self._kind: OpKind = cast(
            OpKind,
            exact_string_choice(
                kind,
                name="registry kind",
                choices=("primitive", "effect"),
            ),
        )
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

        name_s = identity_string(name, name=f"{self._kind} name")
        replace = exact_bool(replace, name="replace")
        if name_s == "concat":
            raise ValueError("'concat' は Grafix 内部予約 operation のため登録できない")
        if not isinstance(spec, OpSpec):
            raise TypeError("spec は OpSpec である必要があります")
        if spec.kind != self._kind:
            raise ValueError(f"{self._kind} registry に {spec.kind} spec は登録できない")
        if name_s in self._specs and not replace:
            raise ValueError(f"{self._kind} '{name_s}' は既に登録されている")

        self._specs[name_s] = spec
        self._revision += 1

    def __contains__(self, name: object) -> bool:
        return type(name) is str and name in self._specs

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
            candidate.register(name, spec)
        self._specs = dict(candidate._specs)
        self._revision += 1

    def describe(self, name: str) -> OpCatalogEntry[EvaluatorT]:
        """登録済み operation の catalog entry を返す。"""

        name_s = identity_string(name, name=f"{self._kind} name")
        return OpCatalogEntry(name=name_s, spec=self._specs[name_s])

    def catalog(self) -> tuple[OpCatalogEntry[EvaluatorT], ...]:
        """公開 operation の catalog entry を名前順で返す。"""

        return tuple(
            OpCatalogEntry(name=name, spec=self._specs[name])
            for name in sorted(self._specs)
            if not name.startswith("_")
        )


class BuiltinOpCatalog(Generic[EvaluatorT]):
    """module import 時に確定した builtin spec を保持する append-only catalog。"""

    __slots__ = ("_kind", "_specs")

    def __init__(self, *, kind: OpKind) -> None:
        self._kind: OpKind = cast(
            OpKind,
            exact_string_choice(
                kind,
                name="builtin catalog kind",
                choices=("primitive", "effect"),
            ),
        )
        self._specs: dict[str, OpSpec[EvaluatorT]] = {}

    def record(self, name: str, spec: OpSpec[EvaluatorT]) -> None:
        """builtin spec を一度だけ記録する。既存 entry の置換は許可しない。"""

        name_s = identity_string(name, name=f"builtin {self._kind} name")
        if type(spec) is not OpSpec:
            raise TypeError("builtin spec は exact OpSpec である必要があります")
        if spec.kind != self._kind:
            raise ValueError(
                f"{self._kind} builtin catalog に {spec.kind} spec は記録できない"
            )
        if name_s in self._specs:
            raise RuntimeError(
                f"builtin {self._kind} spec は既に確定しています: {name_s!r}"
            )
        self._specs[name_s] = spec

    def get(self, name: str) -> OpSpec[EvaluatorT] | None:
        """記録済み spec を返す。未 import の builtin なら None。"""

        name_s = identity_string(name, name=f"builtin {self._kind} name")
        return self._specs.get(name_s)


def op_defaults_and_order(
    *,
    kind: OpKind,
    func: Callable[..., object],
    meta: Mapping[str, ParamMeta],
    n_inputs: int,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """関数 signature の default を検証し、meta default と表示順を返す。"""

    parameters = _operation_parameters(
        kind=kind,
        func=func,
        n_inputs=n_inputs,
    )
    defaults: dict[str, Any] = {}
    for arg in meta:
        parameter = next(
            (parameter for parameter in parameters if parameter.name == arg),
            None,
        )
        if parameter is None:
            raise ValueError(
                f"{kind} '{func.__name__}' の meta 引数がシグネチャに存在しない: {arg!r}"
            )
        if parameter.default is inspect.Parameter.empty:
            raise ValueError(f"{kind} '{func.__name__}' の meta 引数は default 必須: {arg!r}")
        defaults[arg] = validate_parameter_value(
            parameter.default,
            kind=meta[arg].kind,
            choices=meta[arg].choices,
        )

    for parameter in parameters:
        if (
            parameter.name in meta
            or parameter.default is inspect.Parameter.empty
            or parameter.kind
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        ):
            continue
        _validate_code_default(
            parameter.default,
            name=f"{kind} '{func.__name__}' の {parameter.name!r} default",
        )

    order = tuple(parameter.name for parameter in parameters if parameter.name in meta)
    return defaults, order


def op_callable_catalog_fields(
    *,
    kind: OpKind,
    func: Callable[..., object],
    n_inputs: int,
) -> dict[str, Any]:
    """元 callable から catalog 用の説明と signature 情報を抽出する。"""

    parameters = _operation_parameters(
        kind=kind,
        func=func,
        n_inputs=n_inputs,
    )

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
    "BuiltinOpCatalog",
    "CachePolicy",
    "OpKind",
    "OpCatalogEntry",
    "OpRegistry",
    "OpSpec",
    "UiVisiblePred",
    "op_callable_catalog_fields",
    "op_defaults_and_order",
]
