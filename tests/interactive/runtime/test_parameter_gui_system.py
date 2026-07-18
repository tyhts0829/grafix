from __future__ import annotations

from grafix.core.parameters import ParameterKey
from grafix.core.parameters.style import STYLE_OP, STYLE_SITE_ID
from grafix.interactive.runtime.parameter_gui_system import ParameterGUIWindowSystem


class _Gui:
    def __init__(self, *, active: bool) -> None:
        self.parameter_edit_active = bool(active)
        self.draw_count = 0

    def draw_frame(self) -> None:
        self.draw_count += 1


class _Autosave:
    path = "autosave.json"
    status = "dirty"
    last_error = None

    def __init__(self) -> None:
        self.suspended_values: list[bool] = []

    def tick(self, *, suspended: bool) -> bool:
        self.suspended_values.append(bool(suspended))
        return False


class _Store:
    def __init__(self) -> None:
        self.revision = 4
        self.value_revision = 2
        self.changed_keys = frozenset(
            {ParameterKey("circle", "site", "radius")}
        )

    def value_changes_since(
        self,
        _revision: int,
    ) -> frozenset[ParameterKey]:
        return self.changed_keys


def test_gui_system_suspends_autosave_while_an_item_is_active() -> None:
    system = object.__new__(ParameterGUIWindowSystem)
    gui = _Gui(active=True)
    autosave = _Autosave()
    system._gui = gui
    system._autosave = autosave
    system._monitor = None

    system.draw_frame()

    assert gui.draw_count == 1
    assert autosave.suspended_values == [True]


def test_gui_system_reports_revision_from_start_of_edit_frame() -> None:
    system = object.__new__(ParameterGUIWindowSystem)
    store = _Store()
    events: list[tuple[int, int, str]] = []

    class EditingGui(_Gui):
        def draw_frame(self) -> None:
            super().draw_frame()
            store.revision += 1
            store.value_revision += 1

    system._store = store
    system._gui = EditingGui(active=True)
    system._autosave = None
    system._monitor = None
    system._on_parameter_revision_created = (
        lambda revision, timestamp_ns, domain: events.append(
            (revision, timestamp_ns, domain)
        )
    )

    system.draw_frame()

    assert len(events) == 1
    assert events[0][0] == 5
    assert events[0][1] > 0
    assert events[0][2] == "geometry"


def test_gui_system_ignores_structure_only_revision_for_input_latency() -> None:
    system = object.__new__(ParameterGUIWindowSystem)
    store = _Store()
    events: list[tuple[int, int, str]] = []

    class StructureGui(_Gui):
        def draw_frame(self) -> None:
            super().draw_frame()
            store.revision += 1

    system._store = store
    system._gui = StructureGui(active=False)
    system._autosave = None
    system._monitor = None
    system._on_parameter_revision_created = (
        lambda revision, timestamp_ns, domain: events.append(
            (revision, timestamp_ns, domain)
        )
    )

    system.draw_frame()

    assert events == []


def test_gui_system_classifies_style_revision_for_present_latency() -> None:
    system = object.__new__(ParameterGUIWindowSystem)
    store = _Store()
    store.changed_keys = frozenset(
        {ParameterKey(STYLE_OP, STYLE_SITE_ID, "global_thickness")}
    )
    events: list[tuple[int, int, str]] = []

    class EditingGui(_Gui):
        def draw_frame(self) -> None:
            super().draw_frame()
            store.revision += 1
            store.value_revision += 1

    system._store = store
    system._gui = EditingGui(active=True)
    system._autosave = None
    system._monitor = None
    system._on_parameter_revision_created = (
        lambda revision, timestamp_ns, domain: events.append(
            (revision, timestamp_ns, domain)
        )
    )

    system.draw_frame()

    assert len(events) == 1
    assert events[0][0] == 5
    assert events[0][2] == "style"
