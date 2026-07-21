from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from grafix import G

OperationCall = Callable[[dict[str, Any]], object]


def _primitive(operation: Callable[..., object]) -> OperationCall:
    return lambda kwargs: operation(**kwargs)


_CHOICE_ARGUMENTS = (
    (_primitive(G.line), "anchor"),
    (_primitive(G.lsystem), "kind"),
    (_primitive(G.asemic), "stroke_style"),
    (_primitive(G.asemic), "text_align"),
    (_primitive(G.text), "text_align"),
)


@pytest.mark.parametrize(("call", "argument"), _CHOICE_ARGUMENTS)
@pytest.mark.parametrize(
    ("invalid", "error_type"),
    ((1, TypeError), ("unknown", ValueError)),
)
def test_choice_arguments_reject_coercion_and_unknown_values(
    call: OperationCall,
    argument: str,
    invalid: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        call({argument: invalid})


_BOOL_ARGUMENTS = (
    (_primitive(G.asemic), "use_bounding_box"),
    (_primitive(G.asemic), "show_bounding_box"),
    (_primitive(G.text), "use_bounding_box"),
    (_primitive(G.text), "show_bounding_box"),
)


@pytest.mark.parametrize(("call", "argument"), _BOOL_ARGUMENTS)
def test_bool_arguments_reject_truthy_integer_coercion(
    call: OperationCall,
    argument: str,
) -> None:
    with pytest.raises(TypeError):
        call({argument: 1})


@pytest.mark.parametrize(
    ("call", "argument"),
    (
        (_primitive(G.lsystem), "axiom"),
        (_primitive(G.lsystem), "rules"),
        (_primitive(G.asemic), "text"),
        (_primitive(G.text), "text"),
        (_primitive(G.text), "font"),
    ),
)
def test_string_arguments_reject_implicit_stringification(
    call: OperationCall,
    argument: str,
) -> None:
    with pytest.raises(TypeError):
        call({argument: 123})


_INTEGER_ARGUMENTS = (
    (_primitive(G.lsystem), "iters"),
    (_primitive(G.lsystem), "seed"),
    (_primitive(G.asemic), "seed"),
    (_primitive(G.asemic), "n_nodes"),
    (_primitive(G.asemic), "candidates"),
    (_primitive(G.asemic), "stroke_min"),
    (_primitive(G.asemic), "stroke_max"),
    (_primitive(G.asemic), "walk_min_steps"),
    (_primitive(G.asemic), "walk_max_steps"),
    (_primitive(G.asemic), "bezier_samples"),
    (_primitive(G.text), "font_index"),
)


@pytest.mark.parametrize(("call", "argument"), _INTEGER_ARGUMENTS)
def test_integer_arguments_reject_float_truncation(
    call: OperationCall,
    argument: str,
) -> None:
    with pytest.raises(TypeError):
        call({argument: 1.0})
