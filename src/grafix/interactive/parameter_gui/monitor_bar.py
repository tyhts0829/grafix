# どこで: `src/grafix/interactive/parameter_gui/monitor_bar.py`。
# 何を: Parameter GUI 上部に表示する監視バー（テキスト 1 行）を描画する。
# なぜ: 実行中の負荷（FPS/CPU/Mem/頂点/ライン）を即座に把握できるようにするため。

from __future__ import annotations

from typing import Any

from .theme import PARAMETER_GUI_PALETTE


def _fmt_int(n: int) -> str:
    return f"{int(n):,}"


def render_monitor_bar(imgui: Any, snapshot: Any, *, midi_port_name: str | None) -> None:
    """通常時は muted な 1 行へ畳み、注意が必要な状態だけ追加表示する。"""

    fps = float(snapshot.fps)
    cpu_percent = float(snapshot.cpu_percent)
    rss_mb = float(snapshot.rss_mb)
    vertices = int(snapshot.vertices)
    lines = int(snapshot.lines)
    transport_t = float(getattr(snapshot, "transport_t", 0.0))
    transport_requested_t = float(getattr(snapshot, "transport_requested_t", transport_t))
    transport_waiting = bool(getattr(snapshot, "transport_waiting", False))
    transport_playing = bool(getattr(snapshot, "transport_playing", True))
    transport_speed = float(getattr(snapshot, "transport_speed", 1.0))
    transport_recording = bool(getattr(snapshot, "transport_recording", False))
    transport_icon = (
        "REC"
        if transport_recording
        else ("WAIT" if transport_waiting else ("PLAY" if transport_playing else "PAUSE"))
    )

    text = (
        f"FPS {fps:.0f}  ·  CPU {cpu_percent:.0f}%  ·  {rss_mb:,.0f} MB"
        f"  ·  {_fmt_int(vertices)} vtx  ·  {_fmt_int(lines)} lines"
    )
    if midi_port_name is not None:
        text += f"  ·  MIDI {midi_port_name}"
    _text_muted(imgui, str(text))

    # 通常の再生状態は直上の transport toolbar から読み取れるため重複表示しない。
    # 録画・待機だけは作品の見え方に影響する重要状態として alert row にする。
    if transport_recording or transport_waiting:
        transport_text = f"{transport_icon} t={transport_t:.3f}s {transport_speed:g}x"
        if transport_waiting:
            transport_text += f" | target={transport_requested_t:.3f}s (fresh frame pending)"
        _text_alert(
            imgui,
            str(transport_text),
            token="error" if transport_recording else "warning",
        )
    capture_count = int(getattr(snapshot, "capture_request_count", 0))
    capture_count_limit = int(getattr(snapshot, "capture_request_limit", 0))
    capture_bytes = int(getattr(snapshot, "capture_retained_bytes", 0))
    capture_byte_limit = int(getattr(snapshot, "capture_byte_limit", 0))
    # 空の queue は通常状態なので面積を使わない。要求保持中・notice 発生時だけ表示する。
    capture_notice = getattr(snapshot, "capture_notice", None)
    if capture_count > 0 or capture_bytes > 0 or capture_notice:
        _text_alert(
            imgui,
            "CAPTURE QUEUE (estimated process-wide): "
            f"{capture_count}/{capture_count_limit} | "
            f"{capture_bytes / (1024 * 1024):.1f}/"
            f"{capture_byte_limit / (1024 * 1024):.1f} MiB",
            token="warning",
        )
    if capture_notice:
        _text_alert(imgui, str(capture_notice), token="warning")
    frame_error = getattr(snapshot, "frame_error", None)
    if frame_error:
        _text_alert(
            imgui,
            f"FRAME ERROR — showing last good frame | {frame_error}",
            token="error",
        )


def _text_muted(imgui: Any, text: str) -> None:
    """通常状態を主操作より弱い文字で描く。"""

    render = getattr(imgui, "text_disabled", None)
    if callable(render):
        render(str(text))
        return
    imgui.text(str(text))


def _text_alert(imgui: Any, text: str, *, token: str) -> None:
    """警告色を使いつつ、利用可能なら viewport 幅で折り返す。"""

    push = getattr(imgui, "push_style_color", None)
    pop = getattr(imgui, "pop_style_color", None)
    color_text = getattr(imgui, "COLOR_TEXT", None)
    if callable(push) and callable(pop) and color_text is not None:
        push(color_text, *PARAMETER_GUI_PALETTE[token])
        try:
            _text_wrapped(imgui, str(text))
        finally:
            pop()
        return
    _text_wrapped(imgui, str(text))


def _text_wrapped(imgui: Any, text: str) -> None:
    """backend が対応していれば長い通知を現在幅で折り返す。"""

    render = getattr(imgui, "text_wrapped", None)
    if callable(render):
        render(str(text))
        return
    imgui.text(str(text))
