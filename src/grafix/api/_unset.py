"""公開 API の省略値を、偽の型 cast なしで表す。"""

from __future__ import annotations


class _UnsetTarget:
    """selector target が省略されたことだけを表す private sentinel 型。"""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<unset-target>"


_UNSET_TARGET = _UnsetTarget()

__all__ = ["_UNSET_TARGET", "_UnsetTarget"]
