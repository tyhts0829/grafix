# どこで: `sketch/presets/layout_guides.py`。
# 何を: 配置/サイズ検討用の参照ガイド（正方形グリッド / 比率分割 / 貴金属比の矩形分割）を描くプリセット。
# なぜ: 構成の当たりを付ける補助線を、同じ UI/同じ呼び出しで切り替えて重ねられるようにするため。

from __future__ import annotations

import math

from grafix import E, G, preset, run

CANVAS_SIZE = (100, 100)

meta = {
    "canvas_w": {"kind": "float", "ui_min": 10.0, "ui_max": 1000.0},
    "canvas_h": {"kind": "float", "ui_min": 10.0, "ui_max": 1000.0},
    "pattern": {
        "kind": "choice",
        "choices": ["square", "ratio_lines", "metallic_rectangles"],
    },
    "cell_size": {"kind": "float", "ui_min": 1.0, "ui_max": 50.0},
    "metallic_n": {"kind": "int", "ui_min": 1, "ui_max": 12},
    "levels": {"kind": "int", "ui_min": 1, "ui_max": 8},
    "axes": {"kind": "choice", "choices": ["both", "vertical", "horizontal"]},
    "border": {"kind": "bool"},
    "corner": {"kind": "choice", "choices": ["tl", "tr", "br", "bl"]},
    "clockwise": {"kind": "bool"},
    "offset": {"kind": "vec3", "ui_min": -50.0, "ui_max": 50.0},
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


def _canvas_border(
    *,
    canvas_size: tuple[float, float],
    axes: str,
    offset: tuple[float, float, float],
) -> list[object]:
    w, h = canvas_size
    ox, oy, oz = offset
    x0 = float(ox)
    x1 = float(ox) + float(w)
    y0 = float(oy)
    y1 = float(oy) + float(h)

    show_v, show_h = _axes_flags(axes)
    out: list[object] = []
    if show_h:
        out.append(_h_line(y=y0, x0=x0, x1=x1, z=oz))
        out.append(_h_line(y=y1, x0=x0, x1=x1, z=oz))
    if show_v:
        out.append(_v_line(x=x0, y0=y0, y1=y1, z=oz))
        out.append(_v_line(x=x1, y0=y0, y1=y1, z=oz))
    return out


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


def _square_grid(
    *,
    canvas_size: tuple[float, float],
    cell_size: float,
    axes: str,
    offset: tuple[float, float, float],
) -> object:
    canvas_w, canvas_h = canvas_size
    cell = float(cell_size)
    if cell <= 0.0:
        cell = 1.0

    ox, oy, oz = offset
    n_x = max(0, int(math.ceil(float(canvas_w) / cell)))
    n_y = max(0, int(math.ceil(float(canvas_h) / cell)))

    show_v, show_h = _axes_flags(axes)
    out: list[object] = []

    if show_v:
        # repeat は「最後のコピーまでの総オフセット」を指定する（1 ステップ分ではない）。
        v0 = G.line(
            center=(ox, 0.5 * float(canvas_h) + oy, oz),
            length=canvas_h,
            angle=90.0,
        )
        out.append(
            E.repeat(
                bypass=False,
                count=n_x,
                cumulative_scale=False,
                cumulative_offset=False,
                cumulative_rotate=False,
                offset=(cell * n_x, 0.0, 0.0),
                rotation_step=(0.0, 0.0, 0.0),
                scale=(1.0, 1.0, 1.0),
                curve=1.0,
                auto_center=True,
                pivot=(0.0, 0.0, 0.0),
            )(v0)
        )

    if show_h:
        h0 = G.line(
            center=(0.5 * float(canvas_w) + ox, oy, oz),
            length=canvas_w,
            angle=0.0,
        )
        out.append(
            E.repeat(
                bypass=False,
                count=n_y,
                cumulative_scale=False,
                cumulative_offset=False,
                cumulative_rotate=False,
                offset=(0.0, cell * n_y, 0.0),
                rotation_step=(0.0, 0.0, 0.0),
                scale=(1.0, 1.0, 1.0),
                curve=1.0,
                auto_center=True,
                pivot=(0.0, 0.0, 0.0),
            )(h0)
        )

    return _concat(out)


def _ratio_positions(*, length: float, ratio: float, levels: int) -> list[float]:
    length = float(length)
    ratio = float(ratio)
    if ratio <= 1.0:
        ratio = 1.0001
    levels = int(levels)
    if levels < 1:
        levels = 1

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
                positions.append(lo)
                next_segs.append((a, lo))
                next_segs.append((lo, b))
            else:
                positions.append(lo)
                positions.append(hi)
                next_segs.append((a, lo))
                next_segs.append((lo, hi))
                next_segs.append((hi, b))
        segs = next_segs
    return positions


def _ratio_lines(
    *,
    canvas_size: tuple[float, float],
    ratio: float,
    levels: int,
    axes: str,
    offset: tuple[float, float, float],
) -> object:
    w, h = canvas_size
    ox, oy, oz = offset
    show_v, show_h = _axes_flags(axes)

    out: list[object] = []
    if show_v:
        y0 = float(oy)
        y1 = float(oy) + float(h)
        for x in _ratio_positions(length=w, ratio=ratio, levels=levels):
            out.append(_v_line(x=float(ox) + float(x), y0=y0, y1=y1, z=oz))
    if show_h:
        x0 = float(ox)
        x1 = float(ox) + float(w)
        for y in _ratio_positions(length=h, ratio=ratio, levels=levels):
            out.append(_h_line(y=float(oy) + float(y), x0=x0, x1=x1, z=oz))
    return _concat(out)


def _fit_rect(*, canvas_size: tuple[float, float], ratio: float) -> tuple[float, float]:
    w, h = canvas_size
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
    canvas_size: tuple[float, float],
    ratio: float,
    metallic_n: int,
    levels: int,
    axes: str,
    corner: str,
    clockwise: bool,
    offset: tuple[float, float, float],
) -> object:
    canvas_w, canvas_h = canvas_size
    ox, oy, oz = offset
    show_v, show_h = _axes_flags(axes)

    n = int(metallic_n)
    if n < 1:
        n = 1
    levels = int(levels)
    if levels < 1:
        levels = 1

    rect_w, rect_h = _fit_rect(canvas_size=canvas_size, ratio=ratio)
    if rect_w <= 0.0 or rect_h <= 0.0:
        return G.line(center=(float(ox), float(oy), float(oz)), length=0.0, angle=0.0)

    # 内接する比率矩形を corner にアンカーする（余白は corner と反対側へ出る）。
    cw = float(canvas_w)
    ch = float(canvas_h)
    rw = float(rect_w)
    rh = float(rect_h)
    if corner == "tl":
        x0, x1 = 0.0, rw
        y0, y1 = ch - rh, ch
    elif corner == "tr":
        x0, x1 = cw - rw, cw
        y0, y1 = ch - rh, ch
    elif corner == "br":
        x0, x1 = cw - rw, cw
        y0, y1 = 0.0, rh
    elif corner == "bl":
        x0, x1 = 0.0, rw
        y0, y1 = 0.0, rh
    else:
        raise ValueError(f"未対応の corner です: {corner!r}")

    # オフセットは最後にまとめて適用する。
    x0 += float(ox)
    x1 += float(ox)
    y0 += float(oy)
    y1 += float(oy)

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
        out.append(_h_line(y=y0, x0=x0, x1=x1, z=oz))
        out.append(_h_line(y=y1, x0=x0, x1=x1, z=oz))
    if show_v:
        out.append(_v_line(x=x0, y0=y0, y1=y1, z=oz))
        out.append(_v_line(x=x1, y0=y0, y1=y1, z=oz))

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
                        out.append(_v_line(x=x0 + float(i) * s, y0=y0, y1=y1, z=oz))
                    x0 = x0 + strip
                else:
                    for i in range(1, n + 1):
                        out.append(_v_line(x=x1 - float(i) * s, y0=y0, y1=y1, z=oz))
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
                        out.append(_h_line(y=y0 + float(i) * s, x0=x0, x1=x1, z=oz))
                    y0 = y0 + strip
                else:
                    for i in range(1, n + 1):
                        out.append(_h_line(y=y1 - float(i) * s, x0=x0, x1=x1, z=oz))
                    y1 = y1 - strip
            else:
                y0 = y0 + strip if d == "up" else y0
                y1 = y1 - strip if d == "down" else y1

        d = next_dir(d)

    return _concat(out)


@preset(meta=meta)
def layout_guides(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    pattern: str = "square",
    cell_size: float = 10.0,
    metallic_n: int = 1,
    levels: int = 2,
    axes: str = "both",
    border: bool = False,
    corner: str = "tl",
    clockwise: bool = True,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """配置/サイズ検討用の参照ガイドを生成する。

    Parameters
    ----------
    canvas_w : float
        キャンバス幅（world 単位）。
    canvas_h : float
        キャンバス高さ（world 単位）。
    pattern : str
        ガイドの種類。

        - `"square"`: 正方形グリッド
        - `"ratio_lines"`: 比率で分割線を増やす（左右/上下から。levels で段数）
        - `"metallic_rectangles"`: 貴金属比の矩形分割（正方形タイル境界）
    cell_size : float
        正方形グリッドのセルサイズ（ワールド単位）。
    metallic_n : int
        貴金属比の n。
        `n=1` で黄金比、`n=2` で銀比、`n=3` で青銅比。
        `"metallic_rectangles"` の場合は「1 ステップで並べる正方形の個数」にも使う。
    levels : int
        段数（細かさ）。大きいほど線が増える。
    axes : str
        `"both" | "vertical" | "horizontal"`。
    border : bool
        True の場合、キャンバス外枠（axes に応じた辺）を描く。
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
    canvas_size = (float(canvas_w), float(canvas_h))
    ratio = _metallic_mean(int(metallic_n))

    out: list[object] = []

    if bool(border):
        out.extend(
            _canvas_border(canvas_size=canvas_size, axes=str(axes), offset=offset)
        )

    if pattern == "square":
        out.append(
            _square_grid(
                canvas_size=canvas_size,
                cell_size=cell_size,
                axes=str(axes),
                offset=offset,
            )
        )
        return _concat(out)

    if pattern == "ratio_lines":
        out.append(
            _ratio_lines(
                canvas_size=canvas_size,
                ratio=ratio,
                levels=int(levels),
                axes=str(axes),
                offset=offset,
            )
        )
        return _concat(out)

    if pattern == "metallic_rectangles":
        out.append(
            _metallic_rectangles(
                canvas_size=canvas_size,
                ratio=ratio,
                metallic_n=int(metallic_n),
                levels=int(levels),
                axes=str(axes),
                corner=str(corner),
                clockwise=bool(clockwise),
                offset=offset,
            )
        )
        return _concat(out)

    raise ValueError(f"未対応の pattern です: {pattern!r}")


def draw(t: float):
    return layout_guides(canvas_w=float(CANVAS_SIZE[0]), canvas_h=float(CANVAS_SIZE[1]))


if __name__ == "__main__":
    run(
        draw,
        canvas_size=CANVAS_SIZE,
        render_scale=8,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
