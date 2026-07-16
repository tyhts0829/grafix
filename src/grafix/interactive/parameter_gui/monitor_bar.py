# どこで: `src/grafix/interactive/parameter_gui/monitor_bar.py`。
# 何を: Parameter GUI 上部の読み取り専用 status と、全幅 alert を描画する。
# なぜ: 制作操作と telemetry を分離し、異常だけを視覚的に強調するため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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
    snapshot: Any,
    *,
    midi_port_name: str | None,
    compact: bool,
) -> tuple[MonitorLine, ...]:
    """通常 telemetry と重要状態を、幅に応じた短い読み取り専用行へ整形する。"""

    fps = float(snapshot.fps)
    cpu_percent = float(snapshot.cpu_percent)
    rss_mb = float(snapshot.rss_mb)
    vertices = int(snapshot.vertices)
    lines = int(snapshot.lines)
    transport_t = float(getattr(snapshot, "transport_t", 0.0))
    transport_waiting = bool(getattr(snapshot, "transport_waiting", False))
    transport_recording = bool(getattr(snapshot, "transport_recording", False))
    frame_error = getattr(snapshot, "frame_error", None)
    capture_count = int(getattr(snapshot, "capture_request_count", 0))
    capture_notice = getattr(snapshot, "capture_notice", None)

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
    else:
        state = None

    if compact:
        if state is not None:
            return (MonitorLine(f"{fps:.0f} FPS  ·  {state.text}", state.token),)
        return (MonitorLine(f"{fps:.0f} FPS  ·  OK"),)

    telemetry = MonitorLine(
        f"{fps:.0f} FPS  ·  CPU {cpu_percent:.0f}%  ·  {rss_mb:,.0f} MB"
    )
    if state is not None:
        return telemetry, state

    geometry = f"{_fmt_int(vertices)} vtx  ·  {_fmt_int(lines)} lines"
    if midi_port_name is not None:
        geometry += f"  ·  MIDI {midi_port_name}"
    return telemetry, MonitorLine(geometry)


def monitor_alert_lines(snapshot: Any) -> tuple[MonitorLine, ...]:
    """狭い status 列に押し込まない、詳細を含む全幅 alert を返す。"""

    result: list[MonitorLine] = []
    transport_t = float(getattr(snapshot, "transport_t", 0.0))
    transport_requested_t = float(getattr(snapshot, "transport_requested_t", transport_t))
    transport_waiting = bool(getattr(snapshot, "transport_waiting", False))
    transport_speed = float(getattr(snapshot, "transport_speed", 1.0))
    if transport_waiting:
        result.append(
            MonitorLine(
                "WAIT — "
                f"rendered {transport_t:.3f}s · target {transport_requested_t:.3f}s · "
                f"{transport_speed:g}x · fresh frame pending",
                "warning",
            )
        )

    capture_count = int(getattr(snapshot, "capture_request_count", 0))
    capture_count_limit = int(getattr(snapshot, "capture_request_limit", 0))
    capture_bytes = int(getattr(snapshot, "capture_retained_bytes", 0))
    capture_byte_limit = int(getattr(snapshot, "capture_byte_limit", 0))
    capture_notice = getattr(snapshot, "capture_notice", None)
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

    frame_error = getattr(snapshot, "frame_error", None)
    if frame_error:
        result.append(
            MonitorLine(
                f"FRAME ERROR — showing last good frame · {frame_error}",
                "error",
            )
        )
    return tuple(result)


def render_monitor_status(
    imgui: Any,
    snapshot: Any,
    *,
    midi_port_name: str | None,
    compact: bool = False,
) -> None:
    """Status surface 内へ短い telemetry / state だけを描画する。"""

    for line in monitor_status_lines(
        snapshot,
        midi_port_name=midi_port_name,
        compact=bool(compact),
    ):
        if line.token == "muted":
            _text_muted(imgui, line.text)
        else:
            _text_semantic(imgui, line.text, token=line.token, wrapped=False)


def render_monitor_alerts(imgui: Any, snapshot: Any) -> None:
    """Controls / Status の下へ、詳細を含む actionable alert を全幅描画する。"""

    for line in monitor_alert_lines(snapshot):
        if line.token == "muted":
            _text_muted(imgui, line.text)
        else:
            _text_semantic(imgui, line.text, token=line.token, wrapped=True)


def render_monitor_bar(imgui: Any, snapshot: Any, *, midi_port_name: str | None) -> None:
    """互換 API: 通常 status の後に actionable alert を描画する。"""

    render_monitor_status(
        imgui,
        snapshot,
        midi_port_name=midi_port_name,
        compact=False,
    )
    render_monitor_alerts(imgui, snapshot)


def _text_muted(imgui: Any, text: str) -> None:
    """通常状態を主操作より弱い文字で描く。"""

    render = getattr(imgui, "text_disabled", None)
    if callable(render):
        render(str(text))
        return
    imgui.text(str(text))


def _text_semantic(
    imgui: Any,
    text: str,
    *,
    token: Literal["warning", "error"],
    wrapped: bool,
) -> None:
    """重要度を文字と semantic color の双方で示す。"""

    push = getattr(imgui, "push_style_color", None)
    pop = getattr(imgui, "pop_style_color", None)
    color_text = getattr(imgui, "COLOR_TEXT", None)
    if callable(push) and callable(pop) and color_text is not None:
        push(color_text, *PARAMETER_GUI_PALETTE[token])
        try:
            _render_text(imgui, str(text), wrapped=wrapped)
        finally:
            pop()
        return
    _render_text(imgui, str(text), wrapped=wrapped)


def _render_text(imgui: Any, text: str, *, wrapped: bool) -> None:
    if wrapped:
        render = getattr(imgui, "text_wrapped", None)
        if callable(render):
            render(str(text))
            return
    imgui.text(str(text))
