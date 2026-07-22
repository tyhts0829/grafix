"""`from grafix import effect, primitive` が利用できることのテスト。"""

from __future__ import annotations

from grafix import effect, primitive
from grafix.core.operation_authoring import effect as authoring_effect
from grafix.core.operation_authoring import primitive as authoring_primitive


def test_root_effect_is_authoring_decorator() -> None:
    assert effect is authoring_effect


def test_root_primitive_is_authoring_decorator() -> None:
    assert primitive is authoring_primitive

