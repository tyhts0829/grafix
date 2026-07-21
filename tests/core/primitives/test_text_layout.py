from __future__ import annotations

import numpy as np
import pytest

from grafix.core.primitives._text_layout import (
    aligned_line_origin_em,
    bounding_box_polylines_em,
    measure_line_width_em,
    wrap_line_by_width_em,
)


def _advance(char: str) -> float:
    return 0.5 if char == " " else 1.0


def test_measure_line_width_uses_advance_and_inter_character_spacing() -> None:
    assert measure_line_width_em(
        "A B", char_advance_em=_advance, letter_spacing_em=0.25
    ) == pytest.approx(3.0)
    assert measure_line_width_em(
        "", char_advance_em=_advance, letter_spacing_em=0.25
    ) == 0.0


def test_measure_line_width_preserves_sequential_floating_point_rounding() -> None:
    advances = {"A": 0.1, "B": 0.25}

    assert measure_line_width_em(
        "ABA",
        char_advance_em=advances.__getitem__,
        letter_spacing_em=-0.05,
    ).hex() == (0.35).hex()


@pytest.mark.parametrize(
    ("line", "max_width", "expected"),
    [
        ("A A A", 2.0, ["A", "A", "A"]),
        ("ABCD", 2.0, ["AB", "CD"]),
        ("A   B", 2.0, ["A ", "B"]),
        ("", 2.0, [""]),
        ("ABC", 0.0, ["ABC"]),
    ],
)
def test_wrap_line_prefers_spaces_then_falls_back_to_characters(
    line: str, max_width: float, expected: list[str]
) -> None:
    assert (
        wrap_line_by_width_em(
            line,
            max_width_em=max_width,
            char_advance_em=_advance,
            letter_spacing_em=0.0,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("align", "expected"),
    [("left", 0.0), ("center", -2.0), ("right", -4.0)],
)
def test_aligned_line_origin(align: str, expected: float) -> None:
    assert aligned_line_origin_em(4.0, align) == expected


def test_layout_rejects_unknown_alignment() -> None:
    with pytest.raises(ValueError, match="未対応"):
        aligned_line_origin_em(1.0, "justify")
    with pytest.raises(ValueError, match="未対応"):
        bounding_box_polylines_em(
            width_em=1.0, height_em=1.0, align="justify"
        )


def test_bounding_box_polylines_preserve_order_dtype_and_alignment() -> None:
    edges = bounding_box_polylines_em(
        width_em=4.0, height_em=3.0, align="center"
    )

    assert len(edges) == 4
    assert all(edge.dtype == np.float32 for edge in edges)
    assert [edge.tolist() for edge in edges] == [
        [[-2.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        [[2.0, 0.0, 0.0], [2.0, 3.0, 0.0]],
        [[2.0, 3.0, 0.0], [-2.0, 3.0, 0.0]],
        [[-2.0, 3.0, 0.0], [-2.0, 0.0, 0.0]],
    ]
