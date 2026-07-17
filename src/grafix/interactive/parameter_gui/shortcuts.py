"""Parameter GUI shortcut設定の解決とHelp表示model。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_ACTION_LABELS: dict[str, str] = {
    "play_pause": "Play / Pause",
    "reset_time": "Reset time",
    "step_backward": "Step backward",
    "step_forward": "Step forward",
    "slower": "Slower",
    "faster": "Faster",
    "range_shift": "Range: shift",
    "range_min": "Range: minimum",
    "range_max": "Range: maximum",
    "cancel": "Cancel",
    "undo": "Undo",
    "redo": "Redo",
}

_KEY_LABELS = {
    "BRACKETLEFT": "[",
    "BRACKETRIGHT": "]",
    "ESCAPE": "Esc",
    "LEFT": "Left",
    "RIGHT": "Right",
    "SPACE": "Space",
}


def resolve_shortcut_keys(
    bindings: Iterable[tuple[str, str]],
    *,
    key_namespace: Any,
) -> dict[str, int]:
    """設定されたpyglet key名をaction別の整数symbolへ解決する。"""

    resolved: dict[str, int] = {}
    for action, key_name in bindings:
        action_s = str(action)
        key_s = str(key_name).strip().upper()
        if action_s not in _ACTION_LABELS:
            raise ValueError(f"unknown Parameter GUI shortcut action: {action_s!r}")
        if not key_s or not hasattr(key_namespace, key_s):
            raise ValueError(f"unknown Parameter GUI shortcut key: {key_s!r}")
        resolved[action_s] = int(getattr(key_namespace, key_s))
    return resolved


def shortcut_help_lines(
    bindings: Iterable[tuple[str, str]],
) -> tuple[str, ...]:
    """設定順を保ったshortcut一覧の表示行を返す。"""

    lines: list[str] = []
    for action, key_name in bindings:
        action_s = str(action)
        if action_s not in _ACTION_LABELS:
            raise ValueError(f"unknown Parameter GUI shortcut action: {action_s!r}")
        key_s = str(key_name).strip().upper()
        key_label = _KEY_LABELS.get(key_s, key_s.title())
        if action_s in {"undo", "redo"}:
            key_label = f"Cmd/Ctrl+{key_label}"
        lines.append(f"{_ACTION_LABELS[action_s]} — {key_label}")
    return tuple(lines)


__all__ = ["resolve_shortcut_keys", "shortcut_help_lines"]
