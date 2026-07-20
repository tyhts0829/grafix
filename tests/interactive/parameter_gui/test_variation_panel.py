from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from grafix.core.parameters.favorites import set_parameters_favorite
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.history import ParamStoreHistory
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.parameters.variations import (
    create_variation,
    list_variations,
    set_parameters_locked,
)
from grafix.interactive.parameter_gui.gui import ParameterGUI
from grafix.interactive.parameter_gui.parameter_filter import ParameterFilterState
from grafix.interactive.parameter_gui.store_bridge import parameter_table_view_for_store
from grafix.interactive.parameter_gui.variation_panel import (
    VariationPanelState,
    make_capture_service_thumbnail_capture,
    normalize_variation_selection,
    variation_panel_model,
    variation_scope_summary,
)


META = ParamMeta(
    kind="float",
    ui_min=0.0,
    ui_max=10.0,
    recommended_range=(1.0, 9.0),
)


def _store() -> tuple[ParamStore, ParameterKey, ParameterKey]:
    store = ParamStore()
    key_a = ParameterKey("circle", "site-a", "radius")
    key_b = ParameterKey("circle", "site-b", "radius")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key_a,
                base=2.0,
                meta=META,
                effective=2.0,
                source="code",
                explicit=False,
            ),
            FrameParamRecord(
                key=key_b,
                base=4.0,
                meta=META,
                effective=4.0,
                source="code",
                explicit=False,
            ),
        ],
    )
    return store, key_a, key_b


def _set(store: ParamStore, key: ParameterKey, value: float) -> None:
    ok, error = update_state_from_ui(store, key, value, meta=META, override=True)
    assert ok and error is None


def _value(store: ParamStore, key: ParameterKey) -> float:
    state = store.get_state(key)
    assert state is not None
    return float(state.ui_value)


def _gui(
    gui: ParameterGUI,
    store: ParamStore,
    *,
    thumbnail: Path | None = None,
) -> Any:
    gui_state = cast(Any, gui)
    gui_state._store = store
    gui_state._history = ParamStoreHistory(store)
    gui_state._transport = None
    gui_state._show_inactive_params = True
    gui_state._parameter_filter_state = ParameterFilterState()
    gui_state._parameter_error_keys = frozenset()
    gui_state._favorite_parameter_keys = frozenset()
    gui_state._parameter_table_view = None
    gui_state._variation_panel_state = VariationPanelState()
    gui_state._variation_thumbnail_capture = (
        None if thumbnail is None else lambda _name: thumbnail
    )
    gui_state._variation_thumbnail_preview = None
    return gui_state


def test_panel_model_displays_metadata_diff_count_and_empty_state() -> None:
    store, key_a, _key_b = _store()
    empty = variation_panel_model(store)
    assert empty.items == ()
    assert empty.empty_message == "No saved variations yet."

    create_variation(
        store,
        "calm",
        note="soft motion",
        seed=7,
        thumbnail_path="calm.png",
        created_at=0.0,
    )
    _set(store, key_a, 8.0)

    model = variation_panel_model(store)

    assert model.count == 1
    assert model.items[0].name == "calm"
    assert model.items[0].note == "soft motion"
    assert model.items[0].timestamp == "1970-01-01 00:00:00 UTC"
    assert model.items[0].seed == 7
    assert model.items[0].diff_count == 1
    assert model.items[0].thumbnail_path == Path("calm.png")


def test_scope_model_uses_current_filter_or_all_favorites_and_counts_locks() -> None:
    store, key_a, key_b = _store()
    set_parameters_favorite(store, (key_a,), favorite=True)
    set_parameters_locked(store, (key_a,), locked=True)
    filtered_view = parameter_table_view_for_store(
        store,
        show_inactive_params=True,
        filter_state=ParameterFilterState(query="site-b"),
    )

    filtered = variation_scope_summary(store, filtered_view, "filtered")
    favorites = variation_scope_summary(store, filtered_view, "favorites")

    assert filtered.keys == (key_b,)
    assert filtered.locked_count == 0
    assert favorites.keys == (key_a,)
    assert favorites.locked_count == 1


def test_selection_falls_back_after_rename_or_delete() -> None:
    assert normalize_variation_selection(("a", "b"), "b") == "b"
    assert normalize_variation_selection(("a", "b"), "missing") == "a"
    assert normalize_variation_selection((), "missing") is None


def test_capture_service_adapter_exports_current_frame_without_clobber(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, Path, bool]] = []

    class _CaptureService:
        def export(
            self,
            frame: object,
            path: str | Path,
            *,
            overwrite: bool,
            output_size: tuple[int, int] | None,
        ) -> SimpleNamespace:
            output = Path(path)
            calls.append((frame, output, bool(overwrite)))
            assert output_size == (96, 64)
            return SimpleNamespace(path=output)

    frame = object()
    capture = make_capture_service_thumbnail_capture(
        cast(Any, _CaptureService()),
        frame_provider=lambda: frame,  # type: ignore[arg-type,return-value]
        output_path_for_name=lambda name: tmp_path / f"{name}.png",
        output_size=(96, 64),
    )

    assert capture("candidate") == tmp_path / "candidate.png"
    assert calls == [(frame, tmp_path / "candidate.png", False)]


def test_gui_save_uses_thumbnail_boundary_and_load_is_undoable(
    tmp_path: Path,
    initialized_parameter_gui: ParameterGUI,
) -> None:
    store, key_a, _key_b = _store()
    thumbnail = tmp_path / "variation.png"
    gui = _gui(initialized_parameter_gui, store, thumbnail=thumbnail)
    state = gui._variation_state()
    state.new_name = "candidate"
    state.new_note = "keep this"
    state.random_seed = 23

    assert gui._save_named_variation() is True

    saved = list_variations(store)[0]
    assert saved.name == "candidate"
    assert saved.note == "keep this"
    assert saved.seed == 23
    assert saved.thumbnail_path == str(thumbnail)

    _set(store, key_a, 8.0)
    gui._history.synchronize()
    assert gui._load_named_variation("candidate") is True
    assert _value(store, key_a) == 2.0
    assert gui._history.undo() is True
    assert _value(store, key_a) == 8.0


def test_gui_rename_duplicate_and_delete_selected_variation(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    store, _key_a, _key_b = _store()
    create_variation(store, "first", created_at=100.0)
    gui = _gui(initialized_parameter_gui, store)
    state = gui._variation_state()
    state.selected_name = "first"
    state.target_name = "renamed"

    assert gui._rename_selected_variation() is True
    assert [variation.name for variation in list_variations(store)] == ["renamed"]

    state.duplicate_name = "copy"
    assert gui._duplicate_selected_variation() is True
    assert [variation.name for variation in list_variations(store)] == [
        "renamed",
        "copy",
    ]

    assert gui._request_delete_selected_variation() is True
    assert state.pending_delete_name == "copy"
    assert [variation.name for variation in list_variations(store)] == [
        "renamed",
        "copy",
    ]

    assert gui._confirm_delete_pending_variation() is True
    assert state.pending_delete_name is None
    assert [variation.name for variation in list_variations(store)] == ["renamed"]


class _OpenedModal:
    opened = True

    def __enter__(self) -> _OpenedModal:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _DeleteConfirmationImgui:
    def __init__(self, *, confirm: bool) -> None:
        self.confirm = bool(confirm)
        self.labels: list[str] = []
        self.messages: list[str] = []
        self.closed = False

    def begin_popup_modal(self, label: str) -> _OpenedModal:
        self.labels.append(label)
        return _OpenedModal()

    def text_wrapped(self, message: str) -> None:
        self.messages.append(str(message))

    def text_disabled(self, message: str) -> None:
        self.messages.append(str(message))

    def button(self, label: str) -> bool:
        return self.confirm and str(label).startswith("Delete permanently")

    def same_line(self) -> None:
        return None

    def close_current_popup(self) -> None:
        self.closed = True


def test_delete_confirmation_modal_names_target_before_permanent_delete(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    store, _key_a, _key_b = _store()
    create_variation(store, "precious")
    gui = _gui(initialized_parameter_gui, store)
    state = gui._variation_state()
    state.selected_name = "precious"
    assert gui._request_delete_selected_variation() is True
    assert list_variations(store)[0].name == "precious"

    imgui = _DeleteConfirmationImgui(confirm=True)
    gui._imgui = imgui

    assert gui._render_variation_delete_confirmation() is True
    assert imgui.closed is True
    assert any("precious" in message for message in imgui.messages)
    assert list_variations(store) == ()


def test_gui_randomize_and_lock_use_favorite_or_filtered_scope(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    store, key_a, key_b = _store()
    set_parameters_favorite(store, (key_a,), favorite=True)
    gui = _gui(initialized_parameter_gui, store)
    state = gui._variation_state()
    state.scope = "favorites"
    state.random_seed = 91

    before_b = _value(store, key_b)
    assert gui._randomize_variation_scope() is True
    randomized_a = _value(store, key_a)
    assert randomized_a != 2.0
    assert _value(store, key_b) == before_b
    assert gui._history.undo() is True
    assert _value(store, key_a) == 2.0

    assert gui._set_variation_scope_locked(locked=True) is True
    assert gui._randomize_variation_scope() is False
    assert state.notice is not None and "locked" in state.notice
    assert _value(store, key_a) == 2.0
    assert gui._set_variation_scope_locked(locked=True) is False
    assert state.notice is not None and "already locked" in state.notice
    assert gui._set_variation_scope_locked(locked=False) is True
    assert gui._set_variation_scope_locked(locked=False) is False
    assert state.notice is not None and "No parameters" in state.notice

    state.scope = "filtered"
    gui._parameter_filter_state = ParameterFilterState(query="site-b")
    assert gui._randomize_variation_scope() is True
    assert _value(store, key_a) == 2.0
    assert _value(store, key_b) != before_b


def test_gui_morph_applies_only_current_scope_and_is_undoable(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    store, key_a, key_b = _store()
    set_parameters_favorite(store, (key_a,), favorite=True)
    _set(store, key_a, 1.0)
    _set(store, key_b, 3.0)
    create_variation(store, "A", created_at=100.0)
    _set(store, key_a, 9.0)
    _set(store, key_b, 7.0)
    create_variation(store, "B", created_at=200.0)
    gui = _gui(initialized_parameter_gui, store)
    state = gui._variation_state()
    state.scope = "favorites"
    state.morph_a = "A"
    state.morph_b = "B"
    state.morph_amount = 0.5

    assert gui._morph_variation_scope() is True

    assert _value(store, key_a) == pytest.approx(5.0)
    assert _value(store, key_b) == pytest.approx(7.0)
    assert gui._history.undo() is True
    assert _value(store, key_a) == pytest.approx(9.0)


def test_zero_and_all_locked_scope_actions_report_explicit_no_op(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    store, key_a, _key_b = _store()
    _set(store, key_a, 1.0)
    create_variation(store, "A")
    _set(store, key_a, 9.0)
    create_variation(store, "B")
    gui = _gui(initialized_parameter_gui, store)
    state = gui._variation_state()
    state.morph_a = "A"
    state.morph_b = "B"
    state.scope = "filtered"
    gui._parameter_filter_state = ParameterFilterState(query="does-not-exist")

    assert gui._randomize_variation_scope() is False
    assert state.notice is not None and "No parameters" in state.notice
    assert gui._set_variation_scope_locked(locked=True) is False
    assert state.notice is not None and "No parameters" in state.notice
    assert gui._morph_variation_scope() is False
    assert state.notice is not None and "No parameters" in state.notice

    gui._parameter_filter_state = ParameterFilterState(query="site-a")
    set_parameters_locked(store, (key_a,), locked=True)
    assert gui._randomize_variation_scope() is False
    assert state.notice is not None and "locked" in state.notice
    assert gui._morph_variation_scope() is False
    assert state.notice is not None and "locked" in state.notice


def test_real_pyimgui_renders_empty_variation_popup(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    imgui = pytest.importorskip("imgui")
    store, _key_a, _key_b = _store()
    gui = _gui(initialized_parameter_gui, store)
    context = gui._context
    imgui.set_current_context(context)
    try:
        io = imgui.get_io()
        io.display_size = (900.0, 900.0)
        io.delta_time = 1.0 / 60.0
        io.fonts.get_tex_data_as_rgba32()
        imgui.new_frame()
        imgui.begin("variation popup smoke")
        gui._imgui = imgui

        assert gui._render_variation_popup() is False

        imgui.end()
        imgui.render()
        assert imgui.get_draw_data() is not None
    finally:
        imgui.set_current_context(context)
