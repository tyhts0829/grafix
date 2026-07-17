"""MIDI controller、frozen値、接続状態を一つのruntime sessionへまとめる。"""

from __future__ import annotations

import traceback
import logging
from collections.abc import Callable, Mapping
from typing import Literal

from grafix.core.parameters import MidiFrameSnapshot
from grafix.interactive.runtime.diagnostics import (
    DiagnosticAction,
    DiagnosticCenter,
    DiagnosticEvent,
)

from .midi_controller import MidiController

MidiConnectionState = Literal["disabled", "live", "frozen"]
MidiReconnect = Callable[[], MidiController | None]

_logger = logging.getLogger(__name__)


class MidiSession:
    """MIDI入力と切断時のfrozen snapshotを所有する。

    Parameters
    ----------
    controller
        接続済みcontroller。未接続なら ``None``。
    frozen_values
        controllerが無いときに使う保存済みCC値。``None`` はMIDI無効を表し、
        空mappingは「接続を試したが値がまだ無いfrozen状態」を表す。
    reconnect
        再接続時に新しいcontrollerを返す関数。
    diagnostics
        切断・再接続失敗をpublishする共通診断center。
    clear_frozen
        永続化済みsnapshotも消去するcallback。
    """

    def __init__(
        self,
        *,
        controller: MidiController | None,
        frozen_values: Mapping[int, float] | None,
        reconnect: MidiReconnect | None = None,
        diagnostics: DiagnosticCenter | None = None,
        clear_frozen: Callable[[], None] | None = None,
    ) -> None:
        self._controller = controller
        self._frozen_values = (
            None
            if frozen_values is None and controller is None
            else dict(frozen_values or {})
        )
        self._reconnect = reconnect
        self._diagnostics = diagnostics
        self._clear_frozen = clear_frozen
        self._last_error: str | None = None

    @property
    def controller(self) -> MidiController | None:
        """現在接続中のcontrollerを返す。"""

        return self._controller

    @property
    def state(self) -> MidiConnectionState:
        """現在の接続状態を返す。"""

        if self._controller is not None:
            return "live"
        if self._frozen_values is not None:
            return "frozen"
        return "disabled"

    @property
    def status_label(self) -> str:
        """toolbarへ常設表示する短い接続状態を返す。"""

        if self.state == "live":
            controller = self._controller
            assert controller is not None
            return f"MIDI LIVE {controller.port_name}"
        if self.state == "frozen":
            return "MIDI FROZEN"
        return "MIDI OFF"

    @property
    def last_error(self) -> str | None:
        """直近のpoll/reconnect errorを返す。"""

        return self._last_error

    @property
    def last_cc_change(self) -> tuple[int, int] | None:
        """接続中controllerの直近CC変更を返す。"""

        controller = self._controller
        return None if controller is None else controller.last_cc_change

    def value_for_cc(self, cc: int) -> float | None:
        """接続中controllerが保持するCC値をpollせずに返す。"""

        controller = self._controller
        if controller is not None:
            value = controller.cc.get(int(cc))
            return None if value is None else float(value)
        frozen = self._frozen_values
        if frozen is None:
            return None
        value = frozen.get(int(cc))
        return None if value is None else float(value)

    def frame_snapshot(self) -> MidiFrameSnapshot | None:
        """pending入力を反映し、このframeで固定する値と由来を返す。"""

        controller = self._controller
        if controller is not None:
            try:
                controller.poll_pending()
                values = controller.snapshot()
            except Exception as exc:
                self._freeze_after_error(controller, exc)
            else:
                self._frozen_values = dict(values)
                self._last_error = None
                return MidiFrameSnapshot.from_mapping(values, source="midi_live")

        frozen = self._frozen_values
        if frozen is None:
            return None
        return MidiFrameSnapshot.from_mapping(frozen, source="midi_frozen")

    def reconnect(self) -> bool:
        """新しいcontrollerへ再接続し、成功時にTrueを返す。"""

        factory = self._reconnect
        if factory is None:
            self._publish_reconnect_failure("Reconnect is not configured.")
            return False
        try:
            controller = factory()
        except Exception as exc:
            self._last_error = str(exc)
            self._publish_reconnect_failure(
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            )
            return False
        if controller is None:
            self._last_error = "MIDI input is unavailable"
            self._publish_reconnect_failure(self._last_error)
            return False
        self._controller = controller
        self._last_error = None
        return True

    def clear_frozen_snapshot(self) -> None:
        """memory上と永続化先のfrozen値を消去する。"""

        clear = self._clear_frozen
        if clear is not None:
            clear()
        self._frozen_values = {} if self._controller is not None else None

    def close(self) -> None:
        """接続中controllerの値を保存し、入力portを閉じる。"""

        controller = self._controller
        self._controller = None
        if controller is None:
            return
        error: Exception | None = None
        try:
            controller.save()
        except Exception as exc:
            error = exc
        try:
            controller.close()
        except Exception:
            if error is None:
                raise
        if error is not None:
            raise error

    def _freeze_after_error(
        self,
        controller: MidiController,
        error: Exception,
    ) -> None:
        """poll失敗をfrozen遷移へ変換し、診断をpublishする。"""

        try:
            self._frozen_values = dict(controller.snapshot())
        except Exception:
            if self._frozen_values is None:
                self._frozen_values = {}
        try:
            controller.close()
        except Exception:
            pass
        self._controller = None
        self._last_error = str(error)
        _logger.warning(
            "MIDI input disconnected; using frozen values: %s",
            error,
        )
        center = self._diagnostics
        if center is not None:
            center.publish(
                DiagnosticEvent(
                    category="midi",
                    severity="error",
                    summary="MIDI input disconnected; using frozen values",
                    details="".join(
                        traceback.format_exception(
                            type(error),
                            error,
                            error.__traceback__,
                        )
                    ),
                    source=str(controller.port_name),
                    actions=(
                        DiagnosticAction("retry", "Reconnect"),
                        DiagnosticAction("discard", "Clear frozen snapshot"),
                    ),
                    dedupe_key="midi-poll-failed",
                )
            )

    def _publish_reconnect_failure(self, details: str) -> None:
        _logger.warning("MIDI reconnect failed: %s", details)
        center = self._diagnostics
        if center is None:
            return
        center.publish(
            DiagnosticEvent(
                category="midi",
                severity="error",
                summary="MIDI reconnect failed",
                details=str(details),
                actions=(DiagnosticAction("retry", "Reconnect"),),
                dedupe_key="midi-reconnect-failed",
            )
        )


__all__ = ["MidiConnectionState", "MidiReconnect", "MidiSession"]
