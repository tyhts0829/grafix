"""
どこで: `sketch/presets/layout.py`。
何を: レイアウト検討用のガイド（余白/グリッド/比率/カラム/ベースライン等）を生成する preset。
なぜ: 構図の当たり付けとタイポグリッドの初期検討を、同一呼び出しで重ねられるようにするため。
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
import math
from typing import Any

from grafix import G, preset, run

CANVAS_SIZE = (148, 210)  # A5 (mm)

_GOLDEN_F = (math.sqrt(5.0) - 1.0) / 2.0  # 0.618...
_GOLDEN_T = 1.0 - _GOLDEN_F  # 0.382...

meta = {
    "canvas_w": {"kind": "float", "ui_min": 10.0, "ui_max": 1000.0},
    "canvas_h": {"kind": "float", "ui_min": 10.0, "ui_max": 1000.0},
    "base": {
        "kind": "choice",
        "choices": [
            "none",
            "square",
            "ratio_lines",
            "metallic_rectangles",
            "columns",
            "modular",
        ],
    },
    "cell_size": {"kind": "float", "ui_min": 1.0, "ui_max": 50.0},
    "ratio": {"kind": "float", "ui_min": 1.01, "ui_max": 10.0},
    "metallic_n": {"kind": "int", "ui_min": 1, "ui_max": 12},
    "levels": {"kind": "int", "ui_min": 1, "ui_max": 8},
    "axes": {"kind": "choice", "choices": ["both", "vertical", "horizontal"]},
    "border": {"kind": "bool"},
    "margin_l": {"kind": "float", "ui_min": 0.0, "ui_max": 100.0},
    "margin_r": {"kind": "float", "ui_min": 0.0, "ui_max": 100.0},
    "margin_t": {"kind": "float", "ui_min": 0.0, "ui_max": 100.0},
    "margin_b": {"kind": "float", "ui_min": 0.0, "ui_max": 100.0},
    "use_safe_area": {"kind": "bool"},
    "show_margin": {"kind": "bool"},
    "trim": {"kind": "float", "ui_min": 0.0, "ui_max": 100.0},
    "show_trim": {"kind": "bool"},
    "cols": {"kind": "int", "ui_min": 1, "ui_max": 24},
    "rows": {"kind": "int", "ui_min": 1, "ui_max": 24},
    "gutter_x": {"kind": "float", "ui_min": 0.0, "ui_max": 50.0},
    "gutter_y": {"kind": "float", "ui_min": 0.0, "ui_max": 50.0},
    "show_column_centers": {"kind": "bool"},
    "show_baseline": {"kind": "bool"},
    "baseline_step": {"kind": "float", "ui_min": 0.1, "ui_max": 50.0},
    "baseline_offset": {"kind": "float", "ui_min": -50.0, "ui_max": 50.0},
    "show_center": {"kind": "bool"},
    "show_thirds": {"kind": "bool"},
    "show_golden": {"kind": "bool"},
    "show_diagonals": {"kind": "bool"},
    "show_intersections": {"kind": "bool"},
    "mark_size": {"kind": "float", "ui_min": 0.1, "ui_max": 20.0},
    "min_spacing": {"kind": "float", "ui_min": 0.0, "ui_max": 20.0},
    "max_lines": {"kind": "int", "ui_min": 0, "ui_max": 20000},
    "corner": {"kind": "choice", "choices": ["tl", "tr", "br", "bl"]},
    "clockwise": {"kind": "bool"},
    "offset": {"kind": "vec3", "ui_min": -50.0, "ui_max": 50.0},
}


def _base_is(name: str):
    def _pred(v: Mapping[str, Any]) -> bool:
        return str(v.get("base", "")) == str(name)

    return _pred


def _base_in(*names: str):
    allowed = {str(n) for n in names}

    def _pred(v: Mapping[str, Any]) -> bool:
        return str(v.get("base", "")) in allowed

    return _pred


def _any_true(*keys: str):
    def _pred(v: Mapping[str, Any]) -> bool:
        return any(bool(v.get(k)) for k in keys)

    return _pred


UI_VISIBLE = {
    "cell_size": _base_is("square"),
    "ratio": _base_is("ratio_lines"),
    "levels": _base_in("ratio_lines", "metallic_rectangles"),
    "min_spacing": _base_is("ratio_lines"),
    "max_lines": _base_is("ratio_lines"),
    "metallic_n": _base_is("metallic_rectangles"),
    "corner": _base_is("metallic_rectangles"),
    "clockwise": _base_is("metallic_rectangles"),
    "cols": _base_in("columns", "modular"),
    "gutter_x": _base_in("columns", "modular"),
    "show_column_centers": _base_in("columns", "modular"),
    "rows": _base_is("modular"),
    "gutter_y": _base_is("modular"),
    "baseline_step": _any_true("show_baseline"),
    "baseline_offset": _any_true("show_baseline"),
    "trim": _any_true("show_trim"),
    "mark_size": _any_true("show_intersections"),
    "margin_l": _any_true("use_safe_area", "show_margin"),
    "margin_r": _any_true("use_safe_area", "show_margin"),
    "margin_t": _any_true("use_safe_area", "show_margin"),
    "margin_b": _any_true("use_safe_area", "show_margin"),
}


def _axes_flags(axes: str) -> tuple[bool, bool]:
    if axes == "vertical":
        return True, False
    if axes == "horizontal":
        return False, True
    return True, True


def _v_line(*, x: float, y0: float, y1: float, z: float) -> object:
    return G.line(
        center=(float(x), 0.5 * (float(y0) + float(y1)), float(z)),
        length=abs(float(y1) - float(y0)),
        angle=90.0,
    )


def _h_line(*, y: float, x0: float, x1: float, z: float) -> object:
    return G.line(
        center=(0.5 * (float(x0) + float(x1)), float(y), float(z)),
        length=abs(float(x1) - float(x0)),
        angle=0.0,
    )


def _line_between(*, x0: float, y0: float, x1: float, y1: float, z: float) -> object:
    dx = float(x1) - float(x0)
    dy = float(y1) - float(y0)
    length = math.hypot(dx, dy)
    angle = math.degrees(math.atan2(dy, dx)) if length > 0.0 else 0.0
    return G.line(
        center=(0.5 * (float(x0) + float(x1)), 0.5 * (float(y0) + float(y1)), float(z)),
        length=float(length),
        angle=float(angle),
    )


def _metallic_mean(n: int) -> float:
    """貴金属比（metallic mean）を返す。"""
    n = int(n)
    if n < 1:
        n = 1
    return 0.5 * (float(n) + math.sqrt(float(n) * float(n) + 4.0))


def _concat(geoms: list[object]) -> object:
    if not geoms:
        raise ValueError("空の Geometry 連結はできません")
    out = geoms[0]
    for g in geoms[1:]:
        out = out + g
    return out


def _rect_from_canvas(
    *,
    canvas_w: float,
    canvas_h: float,
    offset: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    ox, oy, _oz = offset
    x0 = float(ox)
    y0 = float(oy)
    x1 = float(ox) + float(canvas_w)
    y1 = float(oy) + float(canvas_h)
    return (x0, y0, x1, y1)


def _inset_rect(
    rect: tuple[float, float, float, float],
    *,
    l: float,
    r: float,
    t: float,
    b: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    x0 = float(x0) + float(l)
    x1 = float(x1) - float(r)
    y0 = float(y0) + float(t)
    y1 = float(y1) - float(b)
    if x1 < x0:
        mid = 0.5 * (x0 + x1)
        x0 = mid
        x1 = mid
    if y1 < y0:
        mid = 0.5 * (y0 + y1)
        y0 = mid
        y1 = mid
    return (float(x0), float(y0), float(x1), float(y1))


def _rect_outline(
    rect: tuple[float, float, float, float],
    *,
    axes: str,
    z: float,
) -> list[object]:
    x0, y0, x1, y1 = rect
    show_v, show_h = _axes_flags(axes)
    out: list[object] = []
    if show_h:
        out.append(_h_line(y=y0, x0=x0, x1=x1, z=z))
        out.append(_h_line(y=y1, x0=x0, x1=x1, z=z))
    if show_v:
        out.append(_v_line(x=x0, y0=y0, y1=y1, z=z))
        out.append(_v_line(x=x1, y0=y0, y1=y1, z=z))
    return out


def _square_grid(
    rect: tuple[float, float, float, float],
    *,
    cell_size: float,
    axes: str,
    z: float,
) -> list[object]:
    x0, y0, x1, y1 = rect
    cell = float(cell_size)
    if cell <= 0.0:
        cell = 1.0

    show_v, show_h = _axes_flags(axes)
    out: list[object] = []

    if show_v:
        x = float(x0)
        while x <= float(x1) + 1e-9:
            out.append(_v_line(x=x, y0=y0, y1=y1, z=z))
            x += cell
    if show_h:
        y = float(y0)
        while y <= float(y1) + 1e-9:
            out.append(_h_line(y=y, x0=x0, x1=x1, z=z))
            y += cell

    return out


def _insert_position(
    positions: list[float],
    *,
    value: float,
    min_spacing: float,
) -> bool:
    if min_spacing <= 0.0:
        positions.append(float(value))
        return True

    v = float(value)
    i = bisect_left(positions, v)
    if i > 0 and abs(v - positions[i - 1]) < min_spacing:
        return False
    if i < len(positions) and abs(positions[i] - v) < min_spacing:
        return False
    positions.insert(i, v)
    return True


def _ratio_positions(
    *,
    length: float,
    ratio: float,
    levels: int,
    min_spacing: float,
    max_lines: int,
) -> list[float]:
    length = float(length)
    ratio = float(ratio)
    if ratio <= 1.0:
        ratio = 1.0001
    levels = int(levels)
    if levels < 1:
        levels = 1
    min_spacing = float(min_spacing)
    max_lines = int(max_lines)

    f = 1.0 / ratio
    segs: list[tuple[float, float]] = [(0.0, length)]
    positions: list[float] = []
    for _ in range(levels):
        next_segs: list[tuple[float, float]] = []
        for a, b in segs:
            span = float(b - a)
            p1 = a + span * f
            p2 = b - span * f
            lo, hi = (p1, p2) if p1 <= p2 else (p2, p1)

            # ratio によっては 2 本がほぼ同一点になる（ratio≈2 など）ので、その場合は 1 本に潰す。
            if abs(float(hi) - float(lo)) < 1e-9:
                _insert_position(positions, value=lo, min_spacing=min_spacing)
                if max_lines > 0 and len(positions) >= max_lines:
                    return positions
                next_segs.append((a, lo))
                next_segs.append((lo, b))
            else:
                _insert_position(positions, value=lo, min_spacing=min_spacing)
                _insert_position(positions, value=hi, min_spacing=min_spacing)
                if max_lines > 0 and len(positions) >= max_lines:
                    return positions
                next_segs.append((a, lo))
                next_segs.append((lo, hi))
                next_segs.append((hi, b))
        segs = next_segs
        if max_lines > 0 and len(positions) >= max_lines:
            return positions
    return positions


def _ratio_lines(
    *,
    rect: tuple[float, float, float, float],
    ratio: float,
    levels: int,
    axes: str,
    z: float,
    min_spacing: float,
    max_lines: int,
) -> list[object]:
    x0, y0, x1, y1 = rect
    w = float(x1 - x0)
    h = float(y1 - y0)
    show_v, show_h = _axes_flags(axes)

    out: list[object] = []
    if show_v:
        for x in _ratio_positions(
            length=w,
            ratio=ratio,
            levels=levels,
            min_spacing=min_spacing,
            max_lines=max_lines,
        ):
            out.append(_v_line(x=float(x0) + float(x), y0=y0, y1=y1, z=z))
    if show_h:
        for y in _ratio_positions(
            length=h,
            ratio=ratio,
            levels=levels,
            min_spacing=min_spacing,
            max_lines=max_lines,
        ):
            out.append(_h_line(y=float(y0) + float(y), x0=x0, x1=x1, z=z))
    return out


def _fit_rect(*, w: float, h: float, ratio: float) -> tuple[float, float]:
    w = float(w)
    h = float(h)
    ratio = float(ratio)
    if w <= 0.0 or h <= 0.0:
        return (0.0, 0.0)
    if ratio <= 1.0:
        ratio = 1.0001

    # 最大面積の「内接」矩形を選ぶ（w/h = ratio）。
    cand1 = (w, w / ratio)
    cand2 = (h * ratio, h)

    ok1 = cand1[1] <= h + 1e-9
    ok2 = cand2[0] <= w + 1e-9
    if ok1 and ok2:
        a1 = cand1[0] * cand1[1]
        a2 = cand2[0] * cand2[1]
        return cand1 if a1 >= a2 else cand2
    if ok1:
        return cand1
    if ok2:
        return cand2
    # ここには来ない想定だが、念のため。
    return (min(w, cand2[0]), min(h, cand1[1]))


def _metallic_rectangles(
    *,
    rect: tuple[float, float, float, float],
    metallic_n: int,
    levels: int,
    axes: str,
    corner: str,
    clockwise: bool,
    z: float,
) -> list[object]:
    x0_rect, y0_rect, x1_rect, y1_rect = rect
    canvas_w = float(x1_rect - x0_rect)
    canvas_h = float(y1_rect - y0_rect)
    show_v, show_h = _axes_flags(axes)

    n = int(metallic_n)
    if n < 1:
        n = 1
    levels = int(levels)
    if levels < 1:
        levels = 1

    ratio = _metallic_mean(n)
    rect_w, rect_h = _fit_rect(w=canvas_w, h=canvas_h, ratio=ratio)
    if rect_w <= 0.0 or rect_h <= 0.0:
        return []

    # 内接する比率矩形を corner にアンカーする（余白は corner と反対側へ出る）。
    cw = float(canvas_w)
    ch = float(canvas_h)
    rw = float(rect_w)
    rh = float(rect_h)
    if corner == "tl":
        x0, x1 = float(x0_rect), float(x0_rect) + rw
        y0, y1 = float(y0_rect), float(y0_rect) + rh
    elif corner == "tr":
        x0, x1 = float(x1_rect) - rw, float(x1_rect)
        y0, y1 = float(y0_rect), float(y0_rect) + rh
    elif corner == "br":
        x0, x1 = float(x1_rect) - rw, float(x1_rect)
        y0, y1 = float(y1_rect) - rh, float(y1_rect)
    elif corner == "bl":
        x0, x1 = float(x0_rect), float(x0_rect) + rw
        y0, y1 = float(y1_rect) - rh, float(y1_rect)
    else:
        raise ValueError(f"未対応の corner です: {corner!r}")

    def next_dir(d: str) -> str:
        if clockwise:
            return {"right": "down", "down": "left", "left": "up", "up": "right"}[d]
        return {"right": "up", "up": "left", "left": "down", "down": "right"}[d]

    if clockwise:
        start_dir = {"tl": "right", "tr": "down", "br": "left", "bl": "up"}[corner]
    else:
        start_dir = {"tl": "down", "tr": "left", "br": "up", "bl": "right"}[corner]

    out: list[object] = []

    # フレーム（このパターンの基準矩形の外周）は常に描く。
    if show_h:
        out.append(_h_line(y=y0, x0=x0, x1=x1, z=z))
        out.append(_h_line(y=y1, x0=x0, x1=x1, z=z))
    if show_v:
        out.append(_v_line(x=x0, y0=y0, y1=y1, z=z))
        out.append(_v_line(x=x1, y0=y0, y1=y1, z=z))

    d = start_dir
    for _ in range(levels):
        w = float(x1 - x0)
        h = float(y1 - y0)
        if w <= 0.0 or h <= 0.0:
            break

        if w >= h:
            s = h
            if d not in {"right", "left"}:
                d = "right"
            strip = float(n) * float(s)
            if strip >= w:
                break

            if show_v:
                if d == "right":
                    for i in range(1, n + 1):
                        out.append(_v_line(x=x0 + float(i) * s, y0=y0, y1=y1, z=z))
                    x0 = x0 + strip
                else:
                    for i in range(1, n + 1):
                        out.append(_v_line(x=x1 - float(i) * s, y0=y0, y1=y1, z=z))
                    x1 = x1 - strip
            else:
                x0 = x0 + strip if d == "right" else x0
                x1 = x1 - strip if d == "left" else x1
        else:
            s = w
            if d not in {"up", "down"}:
                d = "up"
            strip = float(n) * float(s)
            if strip >= h:
                break

            if show_h:
                if d == "up":
                    for i in range(1, n + 1):
                        out.append(_h_line(y=y0 + float(i) * s, x0=x0, x1=x1, z=z))
                    y0 = y0 + strip
                else:
                    for i in range(1, n + 1):
                        out.append(_h_line(y=y1 - float(i) * s, x0=x0, x1=x1, z=z))
                    y1 = y1 - strip
            else:
                y0 = y0 + strip if d == "up" else y0
                y1 = y1 - strip if d == "down" else y1

        d = next_dir(d)

    return out


def _columns(
    rect: tuple[float, float, float, float],
    *,
    cols: int,
    gutter_x: float,
    axes: str,
    show_centers: bool,
    z: float,
) -> list[object]:
    x0, y0, x1, y1 = rect
    show_v, _show_h = _axes_flags(axes)
    if not show_v:
        return []

    cols_i = int(cols)
    if cols_i < 1:
        cols_i = 1

    w = float(x1 - x0)
    gutter = float(gutter_x)
    if gutter < 0.0:
        gutter = 0.0

    usable = w - float(cols_i - 1) * gutter
    if usable <= 0.0:
        return []
    col_w = usable / float(cols_i)

    xs: list[float] = []
    x = float(x0)
    for _ in range(cols_i):
        xs.append(x)
        xs.append(x + col_w)
        x = x + col_w + gutter

    out: list[object] = []
    for xv in xs:
        out.append(_v_line(x=xv, y0=y0, y1=y1, z=z))

    if show_centers:
        x = float(x0)
        for _ in range(cols_i):
            out.append(_v_line(x=x + 0.5 * col_w, y0=y0, y1=y1, z=z))
            x = x + col_w + gutter

    return out


def _modular(
    rect: tuple[float, float, float, float],
    *,
    cols: int,
    rows: int,
    gutter_x: float,
    gutter_y: float,
    axes: str,
    show_column_centers: bool,
    z: float,
) -> list[object]:
    x0, y0, x1, y1 = rect
    show_v, show_h = _axes_flags(axes)
    out: list[object] = []

    if show_v:
        out.extend(
            _columns(
                rect,
                cols=cols,
                gutter_x=gutter_x,
                axes="vertical",
                show_centers=show_column_centers,
                z=z,
            )
        )

    if show_h:
        rows_i = int(rows)
        if rows_i < 1:
            rows_i = 1

        h = float(y1 - y0)
        gutter = float(gutter_y)
        if gutter < 0.0:
            gutter = 0.0

        usable = h - float(rows_i - 1) * gutter
        if usable > 0.0:
            row_h = usable / float(rows_i)
            ys: list[float] = []
            y = float(y0)
            for _ in range(rows_i):
                ys.append(y)
                ys.append(y + row_h)
                y = y + row_h + gutter
            for yv in ys:
                out.append(_h_line(y=yv, x0=x0, x1=x1, z=z))

    return out


def _baseline(
    rect: tuple[float, float, float, float],
    *,
    baseline_step: float,
    baseline_offset: float,
    axes: str,
    z: float,
) -> list[object]:
    x0, y0, x1, y1 = rect
    _show_v, show_h = _axes_flags(axes)
    if not show_h:
        return []

    step = float(baseline_step)
    if step <= 0.0:
        return []

    start = float(y0) + float(baseline_offset)
    if start < float(y0):
        k = math.ceil((float(y0) - start) / step)
        start = start + float(k) * step

    out: list[object] = []
    y = float(start)
    while y <= float(y1) + 1e-9:
        out.append(_h_line(y=y, x0=x0, x1=x1, z=z))
        y += step
    return out


def _cross_mark(*, x: float, y: float, size: float, z: float) -> list[object]:
    s = float(size)
    if s <= 0.0:
        return []
    half = 0.5 * s
    return [
        _h_line(y=float(y), x0=float(x) - half, x1=float(x) + half, z=z),
        _v_line(x=float(x), y0=float(y) - half, y1=float(y) + half, z=z),
    ]


@preset(meta=meta, ui_visible=UI_VISIBLE)
def layout(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    base: str = "square",
    cell_size: float = 10.0,
    ratio: float = 1.61803398875,
    metallic_n: int = 1,
    levels: int = 2,
    axes: str = "both",
    border: bool = False,
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    use_safe_area: bool = False,
    show_margin: bool = False,
    trim: float = 0.0,
    show_trim: bool = False,
    cols: int = 12,
    rows: int = 12,
    gutter_x: float = 4.0,
    gutter_y: float = 4.0,
    show_column_centers: bool = False,
    show_baseline: bool = False,
    baseline_step: float = 6.0,
    baseline_offset: float = 0.0,
    show_center: bool = False,
    show_thirds: bool = False,
    show_golden: bool = False,
    show_diagonals: bool = False,
    show_intersections: bool = False,
    mark_size: float = 2.0,
    min_spacing: float = 2.0,
    max_lines: int = 3000,
    corner: str = "tl",
    clockwise: bool = True,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """レイアウト検討用のガイドを生成する。

    Parameters
    ----------
    canvas_w : float
        キャンバス幅（world 単位）。
    canvas_h : float
        キャンバス高さ（world 単位）。
    base : str
        主ガイドの種類。

        - `"none"`: 主ガイドなし（overlay のみ）
        - `"square"`: 正方形グリッド
        - `"ratio_lines"`: 比率分割線（levels 段）
        - `"metallic_rectangles"`: 貴金属比の矩形分割（正方形タイル境界）
        - `"columns"`: カラム + ガター
        - `"modular"`: モジュラーグリッド（行×列 + ガター）
    cell_size : float
        正方形グリッドのセルサイズ（ワールド単位）。
    ratio : float
        `"ratio_lines"` の分割比率（1 より大きい値）。
    metallic_n : int
        貴金属比の n。
        `n=1` で黄金比、`n=2` で銀比、`n=3` で青銅比。
    levels : int
        段数（細かさ）。大きいほど線が増える。
    axes : str
        `"both" | "vertical" | "horizontal"`。
    border : bool
        True の場合、キャンバス外枠（axes に応じた辺）を描く。
    margin_l, margin_r, margin_t, margin_b : float
        余白（safe area）の内側オフセット。
    use_safe_area : bool
        True の場合、主ガイドと overlay を safe area 内へ制限する。
    show_margin : bool
        True の場合、safe area の外周を描く。
    trim : float
        仕上がり（trim）線の内側オフセット（均等）。
    show_trim : bool
        True の場合、trim の外周を描く。
    cols, rows : int
        `"columns"` / `"modular"` の分割数。
    gutter_x, gutter_y : float
        `"columns"` / `"modular"` のガター幅。
    show_column_centers : bool
        True の場合、各カラム中心線を追加で描く。
    show_baseline : bool
        True の場合、ベースライングリッドを追加で描く。
    baseline_step : float
        ベースラインの間隔。
    baseline_offset : float
        safe area（または canvas）の上端からのオフセット。
    show_center, show_thirds, show_golden, show_diagonals : bool
        定番 overlay の表示切り替え。
    show_intersections : bool
        True の場合、overlay の交点へマーカーを描く。
    mark_size : float
        交点マーカーのサイズ。
    min_spacing : float
        `"ratio_lines"` の最小線間隔（これ未満は間引く）。
    max_lines : int
        `"ratio_lines"` の線数上限（片軸あたり）。
    corner : str
        `"tl" | "tr" | "br" | "bl"`。
        `"metallic_rectangles"` の開始角に影響する。
    clockwise : bool
        `"metallic_rectangles"` の分割回り順。
    offset : tuple[float, float, float]
        全ガイドの平行移動量（x, y, z）。

    Returns
    -------
    Geometry
        ガイド線の Geometry。
    """
    axes = str(axes)
    base = str(base)
    ox, oy, oz = offset
    z = float(oz)

    out: list[object] = []

    if bool(border):
        canvas_rect = _rect_from_canvas(canvas_w=canvas_w, canvas_h=canvas_h, offset=offset)
        out.extend(_rect_outline(canvas_rect, axes=axes, z=z))
    else:
        canvas_rect = _rect_from_canvas(canvas_w=canvas_w, canvas_h=canvas_h, offset=offset)

    safe_rect = _inset_rect(
        canvas_rect,
        l=margin_l,
        r=margin_r,
        t=margin_t,
        b=margin_b,
    )
    if bool(show_margin):
        out.extend(_rect_outline(safe_rect, axes=axes, z=z))

    trim_rect = _inset_rect(canvas_rect, l=trim, r=trim, t=trim, b=trim)
    if bool(show_trim):
        out.extend(_rect_outline(trim_rect, axes=axes, z=z))

    target_rect = safe_rect if bool(use_safe_area) else canvas_rect

    if base == "none":
        pass
    elif base == "square":
        out.extend(_square_grid(target_rect, cell_size=cell_size, axes=axes, z=z))
    elif base == "ratio_lines":
        out.extend(
            _ratio_lines(
                rect=target_rect,
                ratio=ratio,
                levels=int(levels),
                axes=axes,
                z=z,
                min_spacing=min_spacing,
                max_lines=int(max_lines),
            )
        )
    elif base == "metallic_rectangles":
        out.extend(
            _metallic_rectangles(
                rect=target_rect,
                metallic_n=int(metallic_n),
                levels=int(levels),
                axes=axes,
                corner=str(corner),
                clockwise=bool(clockwise),
                z=z,
            )
        )
    elif base == "columns":
        out.extend(
            _columns(
                target_rect,
                cols=int(cols),
                gutter_x=gutter_x,
                axes=axes,
                show_centers=bool(show_column_centers),
                z=z,
            )
        )
    elif base == "modular":
        out.extend(
            _modular(
                target_rect,
                cols=int(cols),
                rows=int(rows),
                gutter_x=gutter_x,
                gutter_y=gutter_y,
                axes=axes,
                show_column_centers=bool(show_column_centers),
                z=z,
            )
        )
    else:
        raise ValueError(f"未対応の base です: {base!r}")

    if bool(show_baseline):
        out.extend(
            _baseline(
                target_rect,
                baseline_step=baseline_step,
                baseline_offset=baseline_offset,
                axes=axes,
                z=z,
            )
        )

    show_v, show_h = _axes_flags(axes)
    x0, y0, x1, y1 = target_rect
    w = float(x1 - x0)
    h = float(y1 - y0)

    overlay_xs: list[float] = []
    overlay_ys: list[float] = []

    if bool(show_center):
        if show_v:
            overlay_xs.append(float(x0) + 0.5 * w)
        if show_h:
            overlay_ys.append(float(y0) + 0.5 * h)
    if bool(show_thirds):
        if show_v:
            overlay_xs.extend([float(x0) + w / 3.0, float(x0) + 2.0 * w / 3.0])
        if show_h:
            overlay_ys.extend([float(y0) + h / 3.0, float(y0) + 2.0 * h / 3.0])
    if bool(show_golden):
        if show_v:
            overlay_xs.extend([float(x0) + _GOLDEN_T * w, float(x0) + _GOLDEN_F * w])
        if show_h:
            overlay_ys.extend([float(y0) + _GOLDEN_T * h, float(y0) + _GOLDEN_F * h])

    for xv in overlay_xs:
        out.append(_v_line(x=xv, y0=y0, y1=y1, z=z))
    for yv in overlay_ys:
        out.append(_h_line(y=yv, x0=x0, x1=x1, z=z))

    if bool(show_diagonals):
        out.append(_line_between(x0=x0, y0=y0, x1=x1, y1=y1, z=z))
        out.append(_line_between(x0=x0, y0=y1, x1=x1, y1=y0, z=z))

    if bool(show_intersections) and overlay_xs and overlay_ys:
        xs = sorted(set(float(x) for x in overlay_xs))
        ys = sorted(set(float(y) for y in overlay_ys))
        for xv in xs:
            for yv in ys:
                out.extend(_cross_mark(x=xv, y=yv, size=mark_size, z=z))

    if not out:
        return G.line(center=(float(ox), float(oy), float(z)), length=0.0, angle=0.0)
    return _concat(out)


def draw(t: float):
    return layout(canvas_w=float(CANVAS_SIZE[0]), canvas_h=float(CANVAS_SIZE[1]))


if __name__ == "__main__":
    run(
        draw,
        canvas_size=CANVAS_SIZE,
        render_scale=8,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
