from __future__ import annotations

import pytest

from grafix.core.parameters import context as context_module
from grafix.core.parameters.context import (
    current_cc_snapshot,
    current_frame_params,
    current_param_snapshot,
    current_param_store,
    parameter_context,
)
from grafix.core.parameters.store import ParamStore


def _assert_current_context(
    *,
    store: ParamStore | None,
    frame_params: object | None,
    cc_snapshot: dict | None,
    param_snapshot: object,
) -> None:
    assert current_param_store() is store
    assert current_frame_params() is frame_params
    assert current_cc_snapshot() is cc_snapshot
    assert current_param_snapshot() == param_snapshot


@pytest.mark.parametrize("failing_merge", ["merge_frame_labels", "merge_frame_params"])
def test_parameter_context_restores_outer_context_when_merge_fails(
    monkeypatch: pytest.MonkeyPatch,
    failing_merge: str,
) -> None:
    outer_store = ParamStore()
    inner_store = ParamStore()
    outer_cc = {"outer": 1}

    with parameter_context(outer_store, outer_cc):
        outer_frame = current_frame_params()
        outer_snapshot = current_param_snapshot()

        def fail(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("merge failed")

        with monkeypatch.context() as patch:
            patch.setattr(context_module, failing_merge, fail)
            with pytest.raises(RuntimeError, match="merge failed"):
                with parameter_context(inner_store, {"inner": 2}):
                    assert current_param_store() is inner_store

        _assert_current_context(
            store=outer_store,
            frame_params=outer_frame,
            cc_snapshot=outer_cc,
            param_snapshot=outer_snapshot,
        )

    _assert_current_context(
        store=None,
        frame_params=None,
        cc_snapshot=None,
        param_snapshot={},
    )


def test_parameter_context_restores_state_when_body_raises() -> None:
    store = ParamStore()
    cc_snapshot = {"cc": 7}

    with pytest.raises(ValueError, match="draw failed"):
        with parameter_context(store, cc_snapshot):
            assert current_param_store() is store
            assert current_cc_snapshot() is cc_snapshot
            raise ValueError("draw failed")

    _assert_current_context(
        store=None,
        frame_params=None,
        cc_snapshot=None,
        param_snapshot={},
    )
