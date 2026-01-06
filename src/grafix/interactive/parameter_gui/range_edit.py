# どこで: `src/grafix/interactive/parameter_gui/range_edit.py`。
# 何を: ui_min/ui_max（レンジ）編集の純粋ロジックを提供する。
# なぜ: GUI / MIDI 入力の配線から切り離し、テスト可能に保つため。

from __future__ import annotations

from typing import Literal

RangeEditMode = Literal["shift", "min", "max"]


def apply_range_shift(
    *,
    kind: str,
    ui_min: float | int,
    ui_max: float | int,
    delta: float,
    mode: RangeEditMode,
    sensitivity: float = 1.0,
) -> tuple[float | int, float | int]:
    """ui_min/ui_max を delta に応じて更新して返す。

    Parameters
    ----------
    kind
        `"float"` / `"int"` / `"vec3"` を想定する（`"vec3"` は float と同じ扱い）。
    ui_min
        現在の下限値。
    ui_max
        現在の上限値。
    delta
        入力の差分（回した方向）。正で増加、負で減少。
    mode
        `"shift"`: ui_min/ui_max を同量シフトする。
        `"min"`: ui_min のみ調整する。
        `"max"`: ui_max のみ調整する。
    sensitivity
        シフト量の係数。

    Returns
    -------
    (ui_min, ui_max)
        更新後の (ui_min, ui_max) を返す。`ui_min > ui_max` の場合は swap する。
    """

    if mode not in ("shift", "min", "max"):
        raise ValueError(f"unknown mode: {mode!r}")

    if kind == "int":
        lo = int(ui_min)
        hi = int(ui_max)
        width = float(hi - lo)
        shift_f = float(delta) * float(sensitivity) * width
        shift_i = int(round(shift_f))
        if shift_i == 0 and shift_f != 0.0:
            shift_i = 1 if shift_f > 0.0 else -1

        if mode == "shift":
            lo += int(shift_i)
            hi += int(shift_i)
        elif mode == "min":
            lo += int(shift_i)
        else:
            hi += int(shift_i)

        if lo > hi:
            lo, hi = hi, lo
        return int(lo), int(hi)

    lo_f = float(ui_min)
    hi_f = float(ui_max)
    width_f = float(hi_f - lo_f)
    shift = float(delta) * float(sensitivity) * width_f

    if mode == "shift":
        lo_f += float(shift)
        hi_f += float(shift)
    elif mode == "min":
        lo_f += float(shift)
    else:
        hi_f += float(shift)

    if lo_f > hi_f:
        lo_f, hi_f = hi_f, lo_f
    return float(lo_f), float(hi_f)


__all__ = ["RangeEditMode", "apply_range_shift"]

