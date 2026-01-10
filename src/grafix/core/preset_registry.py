# どこで: `src/grafix/core/preset_registry.py`。
# 何を: preset（@preset）の op を登録し、GUI 側が “文字列規約” に依存しないためのレジストリを提供する。
# なぜ: `op.startswith("preset.")` のような推測ロジックを散らさず、分類/表示名/引数順を一元化するため。

from __future__ import annotations

from collections.abc import Callable, ItemsView
from dataclasses import dataclass
from typing import Any

from grafix.core.parameters.meta import ParamMeta


@dataclass(frozen=True, slots=True)
class PresetSpec:
    """preset 1 種類ぶんの静的情報。"""

    display_op: str
    meta: dict[str, ParamMeta]
    param_order: tuple[str, ...]


class PresetRegistry:
    """preset（@preset）の op -> spec を保持するレジストリ。"""

    def __init__(self) -> None:
        self._items: dict[str, PresetSpec] = {}

    def _register(
        self,
        op: str,
        *,
        display_op: str,
        meta: dict[str, ParamMeta],
        param_order: tuple[str, ...],
        overwrite: bool = True,
    ) -> None:
        """preset を登録する（内部用）。

        Notes
        -----
        登録は `@preset` デコレータ経由に統一する。
        このメソッドはデコレータ実装の内部からのみ呼ぶ。
        """

        op_s = str(op)
        if not overwrite and op_s in self._items:
            raise ValueError(f"preset '{op_s}' は既に登録されている")
        self._items[op_s] = PresetSpec(
            display_op=str(display_op),
            meta=dict(meta),
            param_order=tuple(str(a) for a in param_order),
        )

    def __contains__(self, op: object) -> bool:
        return str(op) in self._items

    def get_meta(self, op: str) -> dict[str, ParamMeta]:
        """op 名に対応する ParamMeta 辞書を取得する。"""

        return dict(self._items[str(op)].meta)

    def get_param_order(self, op: str) -> tuple[str, ...]:
        """op 名に対応する GUI 用の引数順序を返す。"""

        return tuple(self._items[str(op)].param_order)

    def get_display_op(self, op: str) -> str:
        """GUI 表示用の op 名（行ラベル用）を返す。"""

        return str(self._items[str(op)].display_op)


class PresetFuncRegistry:
    """preset（@preset）の name -> callable を保持するレジストリ。"""

    def __init__(self) -> None:
        self._items: dict[str, Callable[..., Any]] = {}

    def _register(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        overwrite: bool = False,
    ) -> None:
        """callable preset を登録する（内部用）。"""

        name_s = str(name)
        if not overwrite and name_s in self._items:
            raise ValueError(f"preset '{name_s}' は既に登録されている")
        self._items[name_s] = func

    def __contains__(self, name: object) -> bool:
        return str(name) in self._items

    def items(self) -> ItemsView[str, Callable[..., Any]]:
        """登録済みエントリの (name, func) ビューを返す。"""

        return self._items.items()

    def get(self, name: str) -> Callable[..., Any] | None:
        """name に対応する callable preset を返す。未登録なら None を返す。"""

        return self._items.get(str(name))


preset_registry = PresetRegistry()
"""グローバルな preset レジストリインスタンス。"""

preset_func_registry = PresetFuncRegistry()
"""グローバルな preset callable レジストリインスタンス。"""


__all__ = [
    "PresetFuncRegistry",
    "PresetRegistry",
    "preset_func_registry",
    "preset_registry",
]
