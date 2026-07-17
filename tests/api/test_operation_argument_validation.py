"""G/E operation の eager argument validation を検証する。"""

from __future__ import annotations

import pytest

from grafix import E, G
from grafix.api._op_validation import validate_operation_kwargs
from grafix.core.op_registry import OpSpec


def test_primitive_rejects_unknown_keyword_with_suggestion() -> None:
    with pytest.raises(TypeError, match=r"lenght.*length.*誤り"):
        G.line(lenght=2.0)


def test_effect_rejects_unknown_keyword_in_first_and_chained_step() -> None:
    with pytest.raises(TypeError, match=r"scal.*scale.*誤り"):
        E.scale(scal=(2.0, 2.0, 2.0))

    with pytest.raises(TypeError, match=r"rotaton.*rotation.*誤り"):
        E.scale().rotate(rotaton=(0.0, 0.0, 1.0))


def test_primitive_and_effect_reject_invalid_choice() -> None:
    with pytest.raises(ValueError, match=r"anchor.*center.*left.*right"):
        G.line(anchor="middle")
    with pytest.raises(ValueError, match=r"mode.*all.*by_line.*by_face"):
        E.scale(mode="separate")


def test_valid_choice_and_reserved_arguments_are_accepted() -> None:
    primitive = G.line(anchor="left", activate=False, key="line")
    effect = E.scale(mode="by_line", activate=False, key="scale")

    assert primitive.op == "line"
    assert effect.steps[0][0] == "scale"


def test_var_keyword_operation_keeps_dynamic_authoring_contract() -> None:
    spec = OpSpec(
        evaluator=lambda: None,
        meta={},
        defaults={},
        param_order=(),
        ui_visible={},
        n_inputs=0,
        kind="primitive",
        accepts_var_kwargs=True,
    )

    validate_operation_kwargs(op="dynamic", spec=spec, params={"custom": 1})
