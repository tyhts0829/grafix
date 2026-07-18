# どこで: `src/grafix/interactive/runtime/parameter_gui_system.py`。
# 何を: Parameter GUI を「1フレーム描画できるサブシステム」として提供する。
# なぜ: `src/grafix/api/runner.py` の `run()` から GUI 初期化/描画/後始末を分離し、肥大化を防ぐため。

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from grafix.interactive.parameter_gui import ParameterGUI, create_parameter_gui_window
from grafix.core.parameters import ParamStore
from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.parameters.style import STYLE_OP
from grafix.core.runtime_config import runtime_config
from grafix.interactive.midi import MidiSession

if TYPE_CHECKING:
    from grafix.core.parameters.autosave import ParamStoreAutosave
    from grafix.core.parameters.history import ParamSnapshotSlots, ParamStoreHistory
    from grafix.interactive.runtime.frame_clock import TransportClock
    from grafix.interactive.runtime.monitor import RuntimeMonitor
    from grafix.interactive.parameter_gui.variation_panel import (
        VariationThumbnailCapture,
        VariationThumbnailPreview,
    )

_logger = logging.getLogger(__name__)


class ParameterGUIWindowSystem:
    """Parameter GUI（別ウィンドウ）のサブシステム。"""

    def __init__(
        self,
        *,
        store: ParamStore,
        midi_session: MidiSession | None = None,
        monitor: RuntimeMonitor | None = None,
        transport: TransportClock | None = None,
        transport_fps: float = 60.0,
        history: ParamStoreHistory | None = None,
        snapshot_slots: ParamSnapshotSlots | None = None,
        autosave: ParamStoreAutosave | None = None,
        is_recording: Callable[[], bool] | None = None,
        variation_thumbnail_capture: VariationThumbnailCapture | None = None,
        variation_thumbnail_preview: VariationThumbnailPreview | None = None,
        ui_scale: float = 1.0,
        on_parameter_revision_created: (
            Callable[[int, int, str], None] | None
        ) = None,
    ) -> None:
        """GUI 用の window と ParameterGUI を初期化する。"""

        cfg = runtime_config()
        w, h = cfg.parameter_gui_window_size
        self.window = create_parameter_gui_window(width=w, height=h, vsync=False)
        self._store = store
        self._autosave = autosave
        self._monitor = monitor
        self._on_parameter_revision_created = on_parameter_revision_created
        self._gui = ParameterGUI(
            self.window,
            store=store,
            midi_session=midi_session,
            monitor=monitor,
            transport=transport,
            transport_fps=float(transport_fps),
            history=history,
            snapshot_slots=snapshot_slots,
            is_recording=is_recording,
            variation_thumbnail_capture=variation_thumbnail_capture,
            variation_thumbnail_preview=variation_thumbnail_preview,
            ui_scale=float(ui_scale),
        )

    def draw_frame(self) -> None:
        """1 フレーム分の GUI を描画する（`flip()` は呼ばない）。"""

        store = getattr(self, "_store", None)
        revision_before = None if store is None else int(store.revision)
        value_revision_before = (
            None if store is None else int(store.value_revision)
        )
        input_started_ns = time.monotonic_ns()
        self._gui.draw_frame()
        if store is not None:
            revision_after = int(store.revision)
            value_revision_after = int(store.value_revision)
            callback = getattr(
                self,
                "_on_parameter_revision_created",
                None,
            )
            if (
                callback is not None
                and revision_before is not None
                and value_revision_before is not None
                and revision_after != revision_before
                and value_revision_after != value_revision_before
            ):
                changed_keys = store.value_changes_since(
                    value_revision_before
                )
                domains = (
                    {"geometry"}
                    if changed_keys is None
                    else {
                        (
                            "style"
                            if key.op in {STYLE_OP, LAYER_STYLE_OP}
                            else "geometry"
                        )
                        for key in changed_keys
                    }
                )
                for domain in sorted(domains):
                    callback(revision_after, input_started_ns, domain)
        autosave = self._autosave
        if autosave is not None:
            try:
                autosave.tick(
                    suspended=bool(self._gui.parameter_edit_active),
                )
            except Exception:
                # preview は継続する。helper 側の debounce により毎 frame の再試行も避ける。
                _logger.exception("Failed to autosave ParameterStore: %s", autosave.path)
            finally:
                monitor = self._monitor
                if monitor is not None:
                    monitor.set_autosave(
                        status=autosave.status,
                        error=autosave.last_error,
                        source=str(autosave.path),
                    )

    def close(self) -> None:
        """GUI を終了し、ウィンドウを破棄する。"""

        self._gui.close()
