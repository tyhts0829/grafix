# どこで: `src/grafix/interactive/parameter_gui/monitor_bar.py`。
# 何を: Parameter GUI 上部の読み取り専用 status と、全幅 alert を描画する。
# なぜ: 制作操作と telemetry を分離し、異常だけを視覚的に強調するため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from grafix.interactive.telemetry import MonitorSnapshot

from .theme import PARAMETER_GUI_PALETTE

StatusToken = Literal["muted", "warning", "error"]


@dataclass(frozen=True, slots=True)
class MonitorLine:
    """Status surface または全幅 alert に描く一行。"""

    text: str
    token: StatusToken = "muted"


def _fmt_int(n: int) -> str:
    return f"{int(n):,}"


def monitor_status_lines(
    snapshot: MonitorSnapshot,
    *,
    midi_status: str | None,
    compact: bool,
) -> tuple[MonitorLine, ...]:
    """通常 telemetry と重要状態を、幅に応じた短い読み取り専用行へ整形する。"""

    fps = float(snapshot.fps)
    cpu_percent = float(snapshot.cpu_percent)
    rss_mb = float(snapshot.rss_mb)
    vertices = int(snapshot.vertices)
    lines = int(snapshot.lines)
    transport_t = float(snapshot.transport_t)
    transport_waiting = bool(snapshot.transport_waiting)
    transport_recording = bool(snapshot.transport_recording)
    frame_error = snapshot.frame_error
    capture_count = int(snapshot.capture_request_count)
    capture_notice = snapshot.capture_notice
    autosave_status = str(snapshot.autosave_status)
    recovered_session = bool(snapshot.recovered_session)

    if frame_error:
        state = MonitorLine("FRAME ERROR", "error")
    elif transport_recording:
        state = MonitorLine(f"REC  ·  {transport_t:.3f}s", "error")
    elif transport_waiting:
        state = MonitorLine(f"WAIT  ·  {transport_t:.3f}s", "warning")
    elif capture_notice:
        state = MonitorLine("CAPTURE NOTICE", "warning")
    elif capture_count > 0:
        state = MonitorLine(f"CAPTURE  ·  {capture_count} queued", "warning")
    elif autosave_status == "failed":
        state = MonitorLine("SAVE FAILED", "error")
    elif autosave_status == "saving":
        state = MonitorLine("SAVING")
    elif autosave_status == "dirty":
        state = MonitorLine("UNSAVED", "warning")
    else:
        state = None

    if recovered_session:
        state = MonitorLine(
            "RECOVERED SESSION"
            + ("" if state is None else f"  ·  {state.text}"),
            "warning" if state is None or state.token == "muted" else state.token,
        )

    midi_suffix = "" if midi_status is None else f"  ·  {midi_status}"

    if compact:
        if state is not None:
            return (
                MonitorLine(
                    f"{fps:.0f} FPS  ·  {state.text}{midi_suffix}",
                    state.token,
                ),
            )
        return (MonitorLine(f"{fps:.0f} FPS  ·  OK{midi_suffix}"),)

    telemetry = MonitorLine(
        f"{fps:.0f} FPS  ·  CPU {cpu_percent:.0f}%  ·  {rss_mb:,.0f} MB"
    )
    if state is not None:
        return telemetry, MonitorLine(f"{state.text}{midi_suffix}", state.token)

    geometry = f"{_fmt_int(vertices)} vtx  ·  {_fmt_int(lines)} lines"
    geometry += midi_suffix
    return telemetry, MonitorLine(geometry)


def monitor_alert_lines(snapshot: MonitorSnapshot) -> tuple[MonitorLine, ...]:
    """狭い status 列に押し込まない、詳細を含む全幅 alert を返す。"""

    result: list[MonitorLine] = []
    transport_t = float(snapshot.transport_t)
    transport_requested_t = float(snapshot.transport_requested_t)
    transport_waiting = bool(snapshot.transport_waiting)
    transport_speed = float(snapshot.transport_speed)
    if transport_waiting:
        result.append(
            MonitorLine(
                "WAIT — "
                f"rendered {transport_t:.3f}s · target {transport_requested_t:.3f}s · "
                f"{transport_speed:g}x · fresh frame pending",
                "warning",
            )
        )

    capture_count = int(snapshot.capture_request_count)
    capture_count_limit = int(snapshot.capture_request_limit)
    capture_bytes = int(snapshot.capture_retained_bytes)
    capture_byte_limit = int(snapshot.capture_byte_limit)
    capture_notice = snapshot.capture_notice
    if capture_count > 0 or capture_bytes > 0:
        result.append(
            MonitorLine(
                "CAPTURE QUEUE (estimated process-wide): "
                f"{capture_count}/{capture_count_limit} · "
                f"{capture_bytes / (1024 * 1024):.1f}/"
                f"{capture_byte_limit / (1024 * 1024):.1f} MiB",
                "warning",
            )
        )
    if capture_notice:
        result.append(MonitorLine(str(capture_notice), "warning"))

    frame_error = snapshot.frame_error
    if frame_error:
        result.append(
            MonitorLine(
                f"FRAME ERROR — showing last good frame · {frame_error}",
                "error",
            )
        )
    autosave_status = str(snapshot.autosave_status)
    autosave_error = snapshot.autosave_error
    if autosave_status == "failed":
        result.append(
            MonitorLine(
                "SAVE FAILED"
                + ("" if not autosave_error else f" — {autosave_error}"),
                "error",
            )
        )
    return tuple(result)


def render_monitor_status(
    imgui: Any,
    snapshot: MonitorSnapshot,
    *,
    midi_status: str | None,
    compact: bool = False,
) -> None:
    """Status surface 内へ短い telemetry / state だけを描画する。"""

    for line in monitor_status_lines(
        snapshot,
        midi_status=midi_status,
        compact=bool(compact),
    ):
        if line.token == "muted":
            _text_muted(imgui, line.text)
        else:
            _text_semantic(imgui, line.text, token=line.token, wrapped=False)


def render_monitor_alerts(imgui: Any, snapshot: MonitorSnapshot) -> None:
    """Controls / Status の下へ、詳細を含む actionable alert を全幅描画する。"""

    for line in monitor_alert_lines(snapshot):
        if line.token == "muted":
            _text_muted(imgui, line.text)
        else:
            _text_semantic(imgui, line.text, token=line.token, wrapped=True)


def _text_muted(imgui: Any, text: str) -> None:
    """通常状態を主操作より弱い文字で描く。"""

    imgui.text_disabled(str(text))


def _text_semantic(
    imgui: Any,
    text: str,
    *,
    token: Literal["warning", "error"],
    wrapped: bool,
) -> None:
    """重要度を文字と semantic color の双方で示す。"""

    imgui.push_style_color(imgui.COLOR_TEXT, *PARAMETER_GUI_PALETTE[token])
    try:
        _render_text(imgui, str(text), wrapped=wrapped)
    finally:
        imgui.pop_style_color()


def _render_text(imgui: Any, text: str, *, wrapped: bool) -> None:
    if wrapped:
        imgui.text_wrapped(str(text))
    else:
        imgui.text(str(text))
