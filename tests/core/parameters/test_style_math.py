from __future__ import annotations

import pytest

from grafix.core.parameters.style import line_width_for_short_side


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((100.0, 100.0), 0.05),
        ((100.0, 200.0), 0.05),
        ((200.0, 100.0), 0.05),
    ],
)
def test_line_width_uses_short_side(
    size: tuple[float, float],
    expected: float,
) -> None:
    assert line_width_for_short_side(0.001, size) == pytest.approx(expected)


@pytest.mark.parametrize("size", [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0)])
def test_line_width_rejects_non_positive_size(size: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="正の値"):
        line_width_for_short_side(0.001, size)
