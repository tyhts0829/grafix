from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from grafix.core.effects.clip import clip
from grafix.core.effects.displace import displace
from grafix.core.effects.highpass import highpass
from grafix.core.effects.isocontour import isocontour
from grafix.core.effects.lowpass import lowpass
from grafix.core.effects.mirror3d import mirror3d
from grafix.core.effects.reaction_diffusion import reaction_diffusion
from grafix.core.effects.resample import resample
from grafix.core.effects.simplify import simplify
from grafix.core.effects.warp import warp
from grafix.core.primitives.asemic import asemic
from grafix.core.primitives.line import line
from grafix.core.primitives.lsystem import lsystem
from grafix.core.primitives.text import text
from grafix.core.realized_geometry import empty_geom_tuple

OperationCall = Callable[[dict[str, Any]], object]


def _unary(operation: Callable[..., object]) -> OperationCall:
    return lambda kwargs: operation(empty_geom_tuple(), **kwargs)


def _binary(operation: Callable[..., object]) -> OperationCall:
    return lambda kwargs: operation(
        empty_geom_tuple(),
        empty_geom_tuple(),
        **kwargs,
    )


def _primitive(operation: Callable[..., object]) -> OperationCall:
    return lambda kwargs: operation(**kwargs)


_CHOICE_ARGUMENTS = (
    (_unary(displace), "gradient_profile"),
    (_unary(reaction_diffusion), "boundary"),
    (_unary(highpass), "closed"),
    (_unary(lowpass), "closed"),
    (_unary(resample), "closed"),
    (_unary(simplify), "closed"),
    (_unary(isocontour), "mode"),
    (_binary(clip), "mode"),
    (_unary(mirror3d), "mode"),
    (_unary(mirror3d), "group"),
    (_binary(warp), "mode"),
    (_binary(warp), "kind"),
    (_binary(warp), "profile"),
    (_binary(warp), "direction"),
    (_primitive(line), "anchor"),
    (_primitive(lsystem), "kind"),
    (_primitive(asemic), "stroke_style"),
    (_primitive(asemic), "text_align"),
    (_primitive(text), "text_align"),
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
    (_unary(isocontour), "keep_original"),
    (_binary(clip), "draw_outline"),
    (_unary(mirror3d), "mirror_equator"),
    (_unary(mirror3d), "source_side"),
    (_unary(mirror3d), "use_reflection"),
    (_unary(mirror3d), "show_planes"),
    (_binary(warp), "inside_only"),
    (_binary(warp), "auto_center"),
    (_binary(warp), "show_mask"),
    (_binary(warp), "keep_original"),
    (_primitive(asemic), "use_bounding_box"),
    (_primitive(asemic), "show_bounding_box"),
    (_primitive(text), "use_bounding_box"),
    (_primitive(text), "show_bounding_box"),
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
        (_primitive(lsystem), "axiom"),
        (_primitive(lsystem), "rules"),
        (_primitive(asemic), "text"),
        (_primitive(text), "text"),
        (_primitive(text), "font"),
    ),
)
def test_string_arguments_reject_implicit_stringification(
    call: OperationCall,
    argument: str,
) -> None:
    with pytest.raises(TypeError):
        call({argument: 123})


_INTEGER_ARGUMENTS = (
    (_unary(reaction_diffusion), "steps"),
    (_unary(reaction_diffusion), "seed"),
    (_unary(reaction_diffusion), "min_points"),
    (_unary(isocontour), "level_step"),
    (_unary(mirror3d), "n_azimuth"),
    (_primitive(lsystem), "iters"),
    (_primitive(lsystem), "seed"),
    (_primitive(asemic), "seed"),
    (_primitive(asemic), "n_nodes"),
    (_primitive(asemic), "candidates"),
    (_primitive(asemic), "stroke_min"),
    (_primitive(asemic), "stroke_max"),
    (_primitive(asemic), "walk_min_steps"),
    (_primitive(asemic), "walk_max_steps"),
    (_primitive(asemic), "bezier_samples"),
    (_primitive(text), "font_index"),
)


@pytest.mark.parametrize(("call", "argument"), _INTEGER_ARGUMENTS)
def test_integer_arguments_reject_float_truncation(
    call: OperationCall,
    argument: str,
) -> None:
    with pytest.raises(TypeError):
        call({argument: 1.0})


def test_integer_arguments_accept_numpy_integer_scalars() -> None:
    coords, offsets = reaction_diffusion(
        empty_geom_tuple(),
        steps=np.int64(1),
        seed=np.int64(2),
        min_points=np.int64(4),
    )

    assert coords.shape == (0, 3)
    assert offsets.tolist() == [0]
