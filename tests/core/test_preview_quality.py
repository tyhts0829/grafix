from __future__ import annotations

import pytest

from grafix.core.preview_quality import (
    current_preview_quality,
    preview_quality_context,
)


def test_preview_quality_defaults_to_final_and_nested_context_restores() -> None:
    assert current_preview_quality() == "final"
    with preview_quality_context("draft"):
        assert current_preview_quality() == "draft"
        with preview_quality_context("final"):
            assert current_preview_quality() == "final"
        assert current_preview_quality() == "draft"
    assert current_preview_quality() == "final"


def test_preview_quality_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="quality"):
        with preview_quality_context("fast"):  # type: ignore[arg-type]
            pass
