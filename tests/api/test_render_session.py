from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from grafix import G, Frame, RenderOptions, RenderSession, RuntimeLimits, render
from grafix.core.parameters import ParamStore
from grafix.core.resource_budget import ResourceBudget, ResourceLimitError
from grafix.core.parameters.style import style_key
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.runtime_config import (
    runtime_config,
    runtime_config_report,
    set_config_path,
)
from grafix.core.preview_quality import current_preview_quality, preview_quality_context


def _constant_draw():
    geometry = G.line(
        center=(0.0, 0.0, 0.0),
        anchor="left",
        length=10.0,
        angle=0.0,
    )

    def draw(_t: float):
        return geometry

    return draw


def test_render_session_reuses_store_config_style_and_realize_cache() -> None:
    session = RenderSession(
        _constant_draw(),
        options=RenderOptions(background_color="white"),
    )
    store = session.param_store
    config = session.config
    resolver = session.style_resolver
    realize_session = session.realize_session

    first = session.render(0.0)
    stats_after_first = realize_session.stats()

    background_key = style_key("background_color")
    background_meta = store.get_meta(background_key)
    assert background_meta is not None
    ok, error = update_state_from_ui(
        store,
        background_key,
        (255, 0, 0),
        meta=background_meta,
    )
    assert ok, error

    second = session.render(1.0)
    stats_after_second = realize_session.stats()

    assert session.param_store is store
    assert session.config is config
    assert session.style_resolver is resolver
    assert session.realize_session is realize_session
    assert first.metadata is session.metadata
    assert second.metadata is session.metadata
    assert first.metadata.effective_config is config
    assert first.background_color.rgb01 == (1.0, 1.0, 1.0)
    assert second.background_color.rgb01 == (1.0, 0.0, 0.0)
    assert stats_after_second.hits > stats_after_first.hits
    assert first.layers[0].realized is second.layers[0].realized

    session.close()


def test_render_session_is_context_managed_and_close_is_idempotent() -> None:
    with RenderSession(_constant_draw()) as session:
        frame = session.render(2.5)
        assert frame.t == pytest.approx(2.5)
        assert isinstance(frame.layers, tuple)
        assert session.closed is False

    assert session.closed is True
    session.close()
    with pytest.raises(RuntimeError, match="close 済み"):
        session.render(3.0)
    with pytest.raises(RuntimeError, match="close 済み"):
        session.__enter__()


def test_public_render_returns_one_final_headless_frame() -> None:
    observed_quality: list[str] = []

    def draw(t: float):
        observed_quality.append(current_preview_quality())
        return _constant_draw()(t)

    with preview_quality_context("draft"):
        frame = render(draw, 1.5, options=RenderOptions(canvas_size=(120, 80)))

    assert isinstance(frame, Frame)
    assert frame.t == pytest.approx(1.5)
    assert frame.canvas_size == (120, 80)
    assert observed_quality == ["final"]


def test_render_session_forces_final_quality_inside_draft_context() -> None:
    observed_quality: list[str] = []

    def draw(t: float):
        observed_quality.append(current_preview_quality())
        return _constant_draw()(t)

    with preview_quality_context("draft"), RenderSession(draw) as session:
        frame = session.render(0.0)

    assert observed_quality == ["final"]
    assert frame.provenance.frame.quality == "final"


def test_render_session_uses_final_runtime_limits() -> None:
    limits = RuntimeLimits(
        per_operation=ResourceBudget(
            max_output_vertices=10,
            max_output_lines=10,
            max_output_bytes=10_000,
        ),
        scene=ResourceBudget(
            max_output_vertices=1,
            max_output_lines=10,
            max_output_bytes=10_000,
        ),
    )
    with RenderSession(_constant_draw(), runtime_limits=limits) as session:
        assert session.runtime_limits is limits
        with pytest.raises(ResourceLimitError, match="scene aggregate"):
            session.render(0.0)


def test_code_parameter_source_does_not_read_implicit_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_module = importlib.import_module("grafix.api.render")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("code mode must not inspect or load parameter files")

    monkeypatch.setattr(render_module, "default_param_store_path", unexpected)
    monkeypatch.setattr(render_module, "load_param_store", unexpected)
    monkeypatch.setattr(render_module, "load_param_store_with_recovery", unexpected)

    with RenderSession(_constant_draw()) as session:
        frame = session.render(0.0)

    assert frame.metadata.parameter_source == "code"
    assert frame.metadata.parameter_store_path is None


@pytest.mark.parametrize(
    ("parameter_source", "expected_loader", "expected_source"),
    [
        ("saved", "saved", "saved"),
        ("recovery", "recovery", "recovery"),
        (Path("specific.json"), "saved", "path"),
    ],
)
def test_parameter_source_selects_one_explicit_load_path(
    parameter_source: str | Path,
    expected_loader: str,
    expected_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    render_module = importlib.import_module("grafix.api.render")

    default_path = tmp_path / "default.json"
    calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(
        render_module,
        "default_param_store_path",
        lambda *_args, **_kwargs: default_path,
    )

    def load_saved(path: Path) -> ParamStore:
        calls.append(("saved", Path(path)))
        return ParamStore()

    def load_recovery(path: Path) -> ParamStore:
        calls.append(("recovery", Path(path)))
        return ParamStore()

    monkeypatch.setattr(render_module, "load_param_store", load_saved)
    monkeypatch.setattr(render_module, "load_param_store_with_recovery", load_recovery)

    source: str | Path
    if isinstance(parameter_source, Path):
        source = tmp_path / parameter_source
    else:
        source = parameter_source
    with RenderSession(_constant_draw(), parameter_source=source) as session:
        metadata = session.metadata

    assert calls == [
        (
            expected_loader,
            (tmp_path / "specific.json").resolve()
            if expected_source == "path"
            else default_path,
        )
    ]
    assert metadata.parameter_source == (
        (tmp_path / "specific.json").resolve() if expected_source == "path" else expected_source
    )


def test_render_session_rejects_unknown_parameter_source() -> None:
    with pytest.raises(ValueError, match="parameter_source"):
        RenderSession(_constant_draw(), parameter_source="implicit")  # type: ignore[arg-type]


def test_render_session_metadata_keeps_effective_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """version: 1
paths:
  output_dir: artifacts
""",
        encoding="utf-8",
    )

    try:
        with RenderSession(_constant_draw(), config_path=config_path) as session:
            frame = session.render(0.0)
            metadata = session.metadata

        assert metadata.config_path == config_path.resolve()
        assert metadata.effective_config is frame.metadata.effective_config
        assert metadata.effective_config.output_dir == (tmp_path / "artifacts").resolve()
    finally:
        set_config_path(None)


def test_render_session_restores_caller_config_and_freezes_session_config(
    tmp_path: Path,
) -> None:
    caller_config_path = tmp_path / "caller.yaml"
    caller_config_path.write_text(
        "version: 1\npaths:\n  output_dir: caller-artifacts\n",
        encoding="utf-8",
    )
    session_config_path = tmp_path / "session.yaml"
    session_config_path.write_text(
        "version: 1\npaths:\n  output_dir: session-artifacts\n",
        encoding="utf-8",
    )
    observed_configs = []

    def draw(t: float):
        observed_configs.append(runtime_config())
        return _constant_draw()(t)

    set_config_path(caller_config_path)
    caller_config = runtime_config()
    caller_report = runtime_config_report()
    try:
        session = RenderSession(draw, config_path=session_config_path)
        session_config = session.config
        assert runtime_config() is session_config
        assert runtime_config_report().config is session_config

        # Session 作成後に設定ファイルが変化しても、評価は開始時 snapshot を使う。
        session_config_path.write_text(
            "version: 1\npaths:\n  output_dir: changed-artifacts\n",
            encoding="utf-8",
        )
        session.render(0.0)
        session.close()

        assert observed_configs == [session_config]
        assert session_config.output_dir == (tmp_path / "session-artifacts").resolve()
        assert runtime_config() is caller_config
        assert runtime_config_report() is caller_report
        assert runtime_config().output_dir == (tmp_path / "caller-artifacts").resolve()
    finally:
        set_config_path(None)


def test_render_session_restores_caller_config_when_initialization_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_module = importlib.import_module("grafix.api.render")
    caller_config_path = tmp_path / "caller.yaml"
    caller_config_path.write_text(
        "version: 1\npaths:\n  output_dir: caller-artifacts\n",
        encoding="utf-8",
    )
    session_config_path = tmp_path / "session.yaml"
    session_config_path.write_text(
        "version: 1\npaths:\n  output_dir: session-artifacts\n",
        encoding="utf-8",
    )

    set_config_path(caller_config_path)
    caller_config = runtime_config()

    def fail_load(*_args: object, **_kwargs: object) -> tuple[object, object, object]:
        raise RuntimeError("parameter load failed")

    monkeypatch.setattr(render_module, "_load_parameter_store", fail_load)
    try:
        with pytest.raises(RuntimeError, match="parameter load failed"):
            RenderSession(_constant_draw(), config_path=session_config_path)

        assert runtime_config() is caller_config
    finally:
        set_config_path(None)
