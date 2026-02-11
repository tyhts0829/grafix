"""`from grafix import effect, primitive` が利用できることのテスト。"""

from __future__ import annotations

from grafix import effect, primitive
from grafix.core.effect_registry import effect as registry_effect
from grafix.core.primitive_registry import primitive as registry_primitive


def test_root_effect_is_registry_decorator() -> None:
    assert effect is registry_effect


def test_root_primitive_is_registry_decorator() -> None:
    assert primitive is registry_primitive

