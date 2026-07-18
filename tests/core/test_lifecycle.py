from __future__ import annotations

import pytest

from grafix.core.lifecycle import CleanupErrors


def test_cleanup_errors_preserves_initial_error_and_reports_secondary_steps() -> None:
    calls: list[str] = []
    reported: list[str] = []
    initial_error = RuntimeError("session failed")
    errors = CleanupErrors(
        initial_error=initial_error,
        report_secondary=reported.append,
    )

    def fail() -> None:
        calls.append("fail")
        raise KeyboardInterrupt

    errors.attempt(fail, "secondary")
    errors.attempt(lambda: calls.append("finish"), "finish")

    with pytest.raises(RuntimeError) as exc_info:
        errors.raise_if_any()

    assert exc_info.value is initial_error
    assert calls == ["fail", "finish"]
    assert reported == ["secondary"]
