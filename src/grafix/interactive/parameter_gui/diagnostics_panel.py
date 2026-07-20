"""DiagnosticCenter の内容を Parameter GUI に表示する。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from grafix.interactive.runtime.diagnostics import DiagnosticCenter, DiagnosticEvent


def render_diagnostics_panel(
    imgui: Any,
    events: Sequence[DiagnosticEvent],
    *,
    center: DiagnosticCenter | None = None,
) -> None:
    """診断がある場合だけ折り畳み可能な詳細 panel を描画する。"""

    if not events:
        return
    opened, _visible = imgui.collapsing_header(
        f"DIAGNOSTICS ({len(events)})##diagnostics"
    )
    if not opened:
        return

    for index, event in enumerate(reversed(tuple(events))):
        count = "" if int(event.count) == 1 else f" ×{int(event.count)}"
        imgui.text(f"{event.severity.upper()} · {event.category}{count}")
        _text_wrapped(imgui, event.summary)
        if event.source:
            imgui.text_disabled(str(event.source))
        if event.details:
            _text_wrapped(imgui, event.details)

        for action in event.actions:
            if imgui.button(f"{action.label}##diagnostic_{index}_{action.action_id}"):
                if action.action_id == "copy":
                    imgui.set_clipboard_text(event.details or event.summary)
                elif center is not None:
                    center.dispatch_action(event, action)
            imgui.same_line()
        if center is not None and imgui.button(f"Dismiss##diagnostic_{index}_dismiss"):
            center.dismiss(event)
        imgui.separator()


def _text_wrapped(imgui: Any, text: str) -> None:
    imgui.text_wrapped(str(text))


__all__ = ["render_diagnostics_panel"]
