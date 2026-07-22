# どこで: `src/grafix/interactive/parameter_gui/session_state.py`。
# 何を: Parameter GUI の frame 間 UI state を一つの lifetime owner にまとめる。
# なぜ: ParameterGUI 本体を描画順序と controller 配線へ集中させるため。

from __future__ import annotations

from dataclasses import dataclass, field

from grafix.core.parameters.favorites import favorite_parameter_key_set
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.reconcile_ops import list_reconcile_orphans
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.view import ParameterRow

from .midi_learn import MidiLearnState
from .parameter_filter import ParameterFilterState
from .reconcile_panel import ReconcileOrphanPanelModel, reconcile_orphan_panel_model
from .store_bridge import ParameterTableView


@dataclass(frozen=True, slots=True)
class MidiClearNotice:
    """MIDI mapping 一括解除後の Undo 導線。"""

    message: str
    history_token: tuple[int, int] | None


@dataclass(slots=True)
class ParameterGuiSessionState:
    """Parameter GUI instance と同じ寿命を持つ frame 間 state。"""

    show_inactive_parameters: bool = False
    filter_state: ParameterFilterState = field(default_factory=ParameterFilterState)
    table_view: ParameterTableView | None = None
    favorite_keys: frozenset[ParameterKey] = frozenset()
    error_keys: frozenset[ParameterKey] = frozenset()
    help_row: ParameterRow | None = None
    parameter_edit_active: bool = False
    reconcile_model: ReconcileOrphanPanelModel = field(
        default_factory=lambda: reconcile_orphan_panel_model(())
    )
    reconcile_error: str | None = None
    midi_clear_notice: MidiClearNotice | None = None
    midi_learn: MidiLearnState = field(default_factory=MidiLearnState)

    @classmethod
    def for_store(cls, store: ParamStore) -> ParameterGuiSessionState:
        """store 由来の初期 state を構築する。"""

        return cls(
            favorite_keys=favorite_parameter_key_set(store),
            reconcile_model=reconcile_orphan_panel_model(
                list_reconcile_orphans(store)
            ),
        )

    def invalidate_table(self) -> None:
        """次の描画で immutable table view を再構築させる。"""

        self.table_view = None


__all__ = ["MidiClearNotice", "ParameterGuiSessionState"]
