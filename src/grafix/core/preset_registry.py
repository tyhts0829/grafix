# どこで: `src/grafix/core/preset_registry.py`。
# 何を: preset（@preset）の op を登録し、GUI 側が “文字列規約” に依存しないためのレジストリを提供する。
# なぜ: `op.startswith("preset.")` のような推測ロジックを散らさず、分類/表示名/引数順を一元化するため。

from __future__ import annotations

from collections.abc import Callable, ItemsView, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from grafix.core.parameters.identity import identity_string
from grafix.core.parameters.key import validate_parameter_identity
from grafix.core.parameters.meta import ParamMeta
from grafix.core.scene import SceneItem

UiVisiblePred = Callable[[Mapping[str, Any]], bool]
_PRESET_PREFIX = "preset."


@dataclass(frozen=True, slots=True)
class PresetIdentity:
    """`P(...)` が preset invoker へ渡す呼び出し identity。"""

    name: str | None
    key: str | int | None
    instance_key: str | int | None
    shared: bool

    def __post_init__(self) -> None:
        if self.name is not None:
            identity_string(self.name, name="preset label")
        validate_parameter_identity(
            key=self.key,
            instance_key=self.instance_key,
            shared=self.shared,
        )


@dataclass(frozen=True, slots=True)
class PresetSpec:
    """preset 1 種類ぶんの静的情報。"""

    func: Callable[..., SceneItem]
    invoker: Callable[..., SceneItem]
    display_op: str
    meta: Mapping[str, ParamMeta]
    param_order: tuple[str, ...]
    ui_visible: Mapping[str, UiVisiblePred]

    def __post_init__(self) -> None:
        """callable と metadata を一つの immutable spec に固定する。"""

        if not callable(self.func):
            raise TypeError("preset func は callable である必要があります")
        if not callable(self.invoker):
            raise TypeError("preset invoker は callable である必要があります")
        identity_string(self.display_op, name="preset display_op")
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))
        object.__setattr__(
            self,
            "param_order",
            tuple(
                identity_string(arg, name="preset param_order item")
                for arg in self.param_order
            ),
        )
        object.__setattr__(self, "ui_visible", MappingProxyType(dict(self.ui_visible)))


def preset_op(name: str) -> str:
    """callable 名を ParameterKey 用の canonical preset op にする。"""

    return _PRESET_PREFIX + identity_string(name, name="preset name")


class PresetRegistry:
    """preset（@preset）の op -> spec を保持するレジストリ。"""

    def __init__(self) -> None:
        self._items: dict[str, PresetSpec] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        """登録または一括置換ごとに増える単調 revision。"""

        return self._revision

    def _register(
        self,
        name: str,
        func: Callable[..., SceneItem],
        invoker: Callable[..., SceneItem],
        *,
        display_op: str,
        meta: dict[str, ParamMeta],
        param_order: tuple[str, ...],
        ui_visible: Mapping[str, UiVisiblePred] | None = None,
    ) -> None:
        """preset を登録する（内部用）。

        Notes
        -----
        登録は `@preset` デコレータ経由に統一する。
        このメソッドはデコレータ実装の内部からのみ呼ぶ。
        """

        name_s = identity_string(name, name="preset name")
        op = preset_op(name_s)
        if op in self._items:
            raise ValueError(f"preset '{name_s}' は既に登録されている")
        spec = PresetSpec(
            func=func,
            invoker=invoker,
            display_op=identity_string(display_op, name="preset display_op"),
            meta=dict(meta),
            param_order=tuple(
                identity_string(arg, name="preset param_order item")
                for arg in param_order
            ),
            ui_visible={} if ui_visible is None else dict(ui_visible),
        )
        self._items[op] = spec
        self._revision += 1

    def __contains__(self, op: object) -> bool:
        return isinstance(op, str) and op in self._items

    def __getitem__(self, op: str) -> PresetSpec:
        return self._items[op]

    def items(self) -> ItemsView[str, PresetSpec]:
        """登録済みpreset specのviewを返す。"""

        return self._items.items()

    def replace_all(self, specs: Mapping[str, PresetSpec]) -> None:
        """candidate preset spec集合へ一括置換する。"""

        normalized: dict[str, PresetSpec] = {}
        for op, spec in specs.items():
            if not isinstance(spec, PresetSpec):
                raise TypeError("preset spec は PresetSpec である必要があります")
            normalized[identity_string(op, name="preset op")] = spec
        self._items = normalized
        self._revision += 1


preset_registry = PresetRegistry()
"""グローバルな preset レジストリインスタンス。"""


__all__ = [
    "PresetIdentity",
    "PresetRegistry",
    "PresetSpec",
    "UiVisiblePred",
    "preset_op",
    "preset_registry",
]
