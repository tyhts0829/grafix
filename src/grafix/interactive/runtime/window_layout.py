"""初期ウィンドウ配置を副作用なしで計算する。

描画 preview と Parameter GUI は別々の native window なので、固定座標だけでは
画面サイズや DPI によって重なったり画面外へ出たりする。このモジュールは OS / pyglet
へ依存せず、利用可能領域と現在の content size だけから初期 rect を決める。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEFAULT_WINDOW_GAP = 16
# pyglet/Cocoa の set_location は content top 基準で、native title bar はその上へ
# 約 28px 出る。32px を確保し、NSScreen.visibleFrame 内に outer frame も残す。
DEFAULT_SCREEN_MARGIN = 32
DEFAULT_MIN_PREVIEW_SIZE = 480
DEFAULT_MIN_PARAMETER_GUI_SIZE = 560


@dataclass(frozen=True, slots=True)
class WindowRect:
    """top-left 原点の矩形。"""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return int(self.x + self.width)

    @property
    def bottom(self) -> int:
        return int(self.y + self.height)


@dataclass(frozen=True, slots=True)
class WindowPairLayout:
    """preview / GUI の初期矩形と採用した並べ方。"""

    preview: WindowRect
    parameter_gui: WindowRect
    orientation: Literal["side_by_side", "stacked"]


def _validate_size(name: str, value: tuple[int, int]) -> tuple[int, int]:
    width, height = int(value[0]), int(value[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"{name} は正の (width, height) である必要があります")
    return width, height


def _clamp(value: int, lower: int, upper: int) -> int:
    return int(max(int(lower), min(int(value), int(upper))))


def _inset_bounds(bounds: WindowRect, margin: int) -> WindowRect:
    """極端に小さい bounds でも各軸を最低 2px 残して inset する。"""

    margin_x = min(int(margin), max(0, (int(bounds.width) - 2) // 2))
    margin_y = min(int(margin), max(0, (int(bounds.height) - 2) // 2))
    return WindowRect(
        x=int(bounds.x + margin_x),
        y=int(bounds.y + margin_y),
        width=int(bounds.width - 2 * margin_x),
        height=int(bounds.height - 2 * margin_y),
    )


def _scaled_size(
    size: tuple[int, int],
    *,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """aspect ratio を保ち、指定領域を超えない size を返す（拡大はしない）。"""

    width, height = size
    scale = min(
        1.0,
        float(max_width) / float(width),
        float(max_height) / float(height),
    )
    return (
        max(1, min(int(max_width), int(round(float(width) * scale)))),
        max(1, min(int(max_height), int(round(float(height) * scale)))),
    )


def _allocate_lengths(
    *,
    desired_a: int,
    desired_b: int,
    minimum_a: int,
    minimum_b: int,
    budget: int,
) -> tuple[int, int]:
    """2領域へ整数 budget を配る。

    自然長が収まれば縮めない。収まらない場合は minimum までの余白を比例配分し、
    minimum 自体も収まらない小画面では両方を比例縮小する。
    """

    desired_a = max(1, int(desired_a))
    desired_b = max(1, int(desired_b))
    budget = max(2, int(budget))
    if desired_a + desired_b <= budget:
        return desired_a, desired_b

    floor_a = min(desired_a, max(1, int(minimum_a)))
    floor_b = min(desired_b, max(1, int(minimum_b)))
    floor_total = floor_a + floor_b

    if floor_total <= budget:
        flex_a = desired_a - floor_a
        flex_b = desired_b - floor_b
        flex_total = flex_a + flex_b
        extra_budget = budget - floor_total
        if flex_total <= 0:
            return floor_a, floor_b

        extra_a = min(
            flex_a,
            max(0, int(round(float(extra_budget) * float(flex_a) / float(flex_total)))),
        )
        extra_b = min(flex_b, max(0, extra_budget - extra_a))
        remainder = extra_budget - extra_a - extra_b
        if remainder > 0:
            add_a = min(remainder, flex_a - extra_a)
            extra_a += add_a
            remainder -= add_a
        if remainder > 0:
            extra_b += min(remainder, flex_b - extra_b)
        return floor_a + extra_a, floor_b + extra_b

    # 推奨 minimum も同時には確保できない場合。片方を 0 にせず、比率を保って
    # available length を使い切る。
    length_a = _clamp(
        int(round(float(budget) * float(floor_a) / float(floor_total))),
        1,
        budget - 1,
    )
    return length_a, budget - length_a


def _clamped_origin(
    preferred: tuple[int, int],
    *,
    width: int,
    height: int,
    bounds: WindowRect,
) -> tuple[int, int]:
    return (
        _clamp(int(preferred[0]), int(bounds.x), int(bounds.right - width)),
        _clamp(int(preferred[1]), int(bounds.y), int(bounds.bottom - height)),
    )


def layout_window_pair(
    *,
    preview_size: tuple[int, int],
    parameter_gui_size: tuple[int, int],
    usable_bounds: WindowRect,
    preferred_preview_position: tuple[int, int] | None = None,
    preferred_parameter_gui_position: tuple[int, int] | None = None,
    gap: int = DEFAULT_WINDOW_GAP,
    margin: int = DEFAULT_SCREEN_MARGIN,
    min_preview_size: int = DEFAULT_MIN_PREVIEW_SIZE,
    min_parameter_gui_size: int = DEFAULT_MIN_PARAMETER_GUI_SIZE,
) -> WindowPairLayout:
    """画面内かつ非重複になる preview / GUI rect を返す。

    横並びを優先し、推奨最小幅まで縮めても横に収まらない場合だけ縦積みにする。
    preview は常に aspect ratio を保つ。Parameter GUI は独立に幅・高さを縮める。
    最後にグループの origin を margin 内へ clamp する。

    `usable_bounds` 自体が極端に小さく推奨 minimum を満たせない場合も、両 window を
    1px 以上に比例縮小して非重複を維持する。
    """

    preview_w, preview_h = _validate_size("preview_size", preview_size)
    gui_w, gui_h = _validate_size("parameter_gui_size", parameter_gui_size)
    if int(usable_bounds.width) < 2 or int(usable_bounds.height) < 2:
        raise ValueError("usable_bounds は各辺 2px 以上である必要があります")
    if int(gap) < 0 or int(margin) < 0:
        raise ValueError("gap と margin は 0 以上である必要があります")
    if int(min_preview_size) <= 0 or int(min_parameter_gui_size) <= 0:
        raise ValueError("minimum size は正である必要があります")

    inner = _inset_bounds(usable_bounds, int(margin))
    preview_preferred = preferred_preview_position or (inner.x, inner.y)
    gui_preferred = preferred_parameter_gui_position or preview_preferred

    # まず高さだけを画面内へ収めたときの自然幅を求める。GUI は aspect ratio を
    # 固定しないので、各軸を独立に clamp する。
    side_preview_desired = _scaled_size(
        (preview_w, preview_h),
        max_width=inner.width,
        max_height=inner.height,
    )
    side_gui_desired = (min(gui_w, inner.width), min(gui_h, inner.height))

    side_gap = min(int(gap), max(0, int(inner.width) - 2))
    side_budget = int(inner.width - side_gap)
    side_preview_floor = min(side_preview_desired[0], int(min_preview_size))
    side_gui_floor = min(side_gui_desired[0], int(min_parameter_gui_size))

    if side_preview_floor + side_gui_floor <= side_budget:
        allocated_preview_w, allocated_gui_w = _allocate_lengths(
            desired_a=side_preview_desired[0],
            desired_b=side_gui_desired[0],
            minimum_a=side_preview_floor,
            minimum_b=side_gui_floor,
            budget=side_budget,
        )
        final_preview_size = _scaled_size(
            (preview_w, preview_h),
            max_width=allocated_preview_w,
            max_height=inner.height,
        )
        final_gui_size = (allocated_gui_w, side_gui_desired[1])

        group_width = final_preview_size[0] + side_gap + final_gui_size[0]
        group_height = max(final_preview_size[1], final_gui_size[1])
        preferred_group_y = min(int(preview_preferred[1]), int(gui_preferred[1]))
        group_x, group_y = _clamped_origin(
            (int(preview_preferred[0]), preferred_group_y),
            width=group_width,
            height=group_height,
            bounds=inner,
        )
        return WindowPairLayout(
            preview=WindowRect(
                group_x,
                group_y,
                final_preview_size[0],
                final_preview_size[1],
            ),
            parameter_gui=WindowRect(
                group_x + final_preview_size[0] + side_gap,
                group_y,
                final_gui_size[0],
                final_gui_size[1],
            ),
            orientation="side_by_side",
        )

    # 横幅が推奨 minimum を下回る場合は縦積みへ fallback。高さについても
    # natural -> minimum -> 比例縮小の順で配分する。
    stacked_preview_desired = _scaled_size(
        (preview_w, preview_h),
        max_width=inner.width,
        max_height=inner.height,
    )
    stacked_gui_desired = (min(gui_w, inner.width), min(gui_h, inner.height))
    stacked_gap = min(int(gap), max(0, int(inner.height) - 2))
    stacked_budget = int(inner.height - stacked_gap)
    allocated_preview_h, allocated_gui_h = _allocate_lengths(
        desired_a=stacked_preview_desired[1],
        desired_b=stacked_gui_desired[1],
        minimum_a=min(stacked_preview_desired[1], int(min_preview_size)),
        minimum_b=min(stacked_gui_desired[1], int(min_parameter_gui_size)),
        budget=stacked_budget,
    )
    final_preview_size = _scaled_size(
        (preview_w, preview_h),
        max_width=inner.width,
        max_height=allocated_preview_h,
    )
    final_gui_size = (stacked_gui_desired[0], allocated_gui_h)

    group_height = final_preview_size[1] + stacked_gap + final_gui_size[1]
    _unused_x, group_y = _clamped_origin(
        (int(preview_preferred[0]), int(preview_preferred[1])),
        width=max(final_preview_size[0], final_gui_size[0]),
        height=group_height,
        bounds=inner,
    )
    preview_x = _clamp(
        int(preview_preferred[0]),
        int(inner.x),
        int(inner.right - final_preview_size[0]),
    )
    gui_x = _clamp(
        int(gui_preferred[0]),
        int(inner.x),
        int(inner.right - final_gui_size[0]),
    )
    return WindowPairLayout(
        preview=WindowRect(
            preview_x,
            group_y,
            final_preview_size[0],
            final_preview_size[1],
        ),
        parameter_gui=WindowRect(
            gui_x,
            group_y + final_preview_size[1] + stacked_gap,
            final_gui_size[0],
            final_gui_size[1],
        ),
        orientation="stacked",
    )


__all__ = [
    "DEFAULT_MIN_PARAMETER_GUI_SIZE",
    "DEFAULT_MIN_PREVIEW_SIZE",
    "DEFAULT_SCREEN_MARGIN",
    "DEFAULT_WINDOW_GAP",
    "WindowPairLayout",
    "WindowRect",
    "layout_window_pair",
]
