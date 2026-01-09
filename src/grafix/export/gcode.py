"""
どこで: `src/grafix/export/gcode.py`。
何を: realize 済みシーンを G-code として保存する関数を提供する。
なぜ: ペンプロッタ向け出力を interactive 依存なしで追加できるようにするため。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import hypot
from pathlib import Path

import numpy as np

from grafix.core.pipeline import RealizedLayer


_DEFAULT_PAPER_MARGIN_MM = 2.0


@dataclass(frozen=True, slots=True)
class GCodeParams:
    """G-code 生成パラメータ。

    Parameters
    ----------
    travel_feed : float
        ペンアップ移動のフィードレート [mm/min]。
    draw_feed : float
        ペンダウン描画のフィードレート [mm/min]。
    z_up : float
        ペンアップ時の Z 高さ [mm]。
    z_down : float
        ペンダウン時の Z 高さ [mm]。
    y_down : bool
        True の場合、Y 反転を行う。
    origin : tuple[float, float]
        出力座標の原点オフセット [mm]（X, Y）。
    decimals : int
        数値出力の小数点以下の桁数。
    paper_margin_mm : float
        紙（canvas）の外周安全マージン [mm]。
    connect_distance : float or None
        近接連結のしきい値 [mm]。None で無効。
    bed_x_range : tuple[float, float] or None
        3D プリンタのベッド X 範囲 [mm]。None で無効。
    bed_y_range : tuple[float, float] or None
        3D プリンタのベッド Y 範囲 [mm]。None で無効。
    canvas_height_mm : float or None
        `y_down=True` 時の厳密反転に使うキャンバス高さ [mm]。
        None の場合、`export_gcode(canvas_size=...)` の高さを使う。
    """

    travel_feed: float = 1500.0
    draw_feed: float = 1000.0
    z_up: float = 3.0
    z_down: float = -2.0
    y_down: bool = False
    origin: tuple[float, float] = (91.0, -0.75)
    decimals: int = 3
    paper_margin_mm: float = _DEFAULT_PAPER_MARGIN_MM
    connect_distance: float | None = None
    bed_x_range: tuple[float, float] | None = None
    bed_y_range: tuple[float, float] | None = None
    canvas_height_mm: float | None = None


def _fmt_float(value: float, *, decimals: int) -> str:
    """小数を固定桁の文字列にして返す。

    Notes
    -----
    G-code はテキストであり、出力が少しでも揺れると差分比較が難しくなる。
    そのため常に固定桁でフォーマットし、`-0.000` のような表現だけを `0.000` に正規化する。
    """

    text = f"{float(value):.{int(decimals)}f}"
    if text.startswith("-0") and float(text) == 0.0:
        return text[1:]
    return text


def _is_inside_rect(xy: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    """点が矩形（閉区間）に含まれるなら True を返す。"""

    x, y = xy
    x_min, x_max, y_min, y_max = rect
    return (x_min <= x <= x_max) and (y_min <= y <= y_max)


def _clip_segment_to_rect(
    p0: tuple[float, float],
    p1: tuple[float, float],
    rect: tuple[float, float, float, float],
    *,
    eps: float = 1e-12,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """線分を矩形へクリップし、内側部分の端点 2 点を返す。"""

    # Liang–Barsky line clipping を使う。
    # 線分をパラメータ表現 `P(u)=P0 + u*(P1-P0), u in [0,1]` にして、
    # 矩形の 4 辺に対する不等式制約を u の範囲 `[u1, u2]` として更新する。

    x0, y0 = p0
    x1, y1 = p1
    x_min, x_max, y_min, y_max = rect

    dx = x1 - x0
    dy = y1 - y0

    # 可視区間の u 範囲（最初は線分全体）。
    u1 = 0.0
    u2 = 1.0

    # 各辺の不等式を `p*u <= q` の形に落とし込む。
    #   x >= x_min  -> -dx*u <= x0 - x_min
    #   x <= x_max  ->  dx*u <= x_max - x0
    #   y >= y_min  -> -dy*u <= y0 - y_min
    #   y <= y_max  ->  dy*u <= y_max - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - x_min, x_max - x0, y0 - y_min, y_max - y0)

    for pi, qi in zip(p, q):
        # 方向成分が 0 に近い（= 辺と平行）場合:
        # - qi < 0 なら「矩形の外側に平行」なので交差なし
        # - それ以外は u 制約を更新しない
        if abs(pi) < eps:
            if qi < 0.0:
                return None
            continue

        # 辺との交点に対応する u 値。
        r = qi / pi
        if pi < 0.0:
            # こちら側は下限更新（u >= r）。
            if r > u2:
                return None
            if r > u1:
                u1 = r
        else:
            # こちら側は上限更新（u <= r）。
            if r < u1:
                return None
            if r < u2:
                u2 = r

    if u1 > u2:
        return None

    # クリップ後の端点（u1/u2 が更新された線分）。
    ax = x0 + u1 * dx
    ay = y0 + u1 * dy
    bx = x0 + u2 * dx
    by = y0 + u2 * dy

    # 交点が 1 点に潰れてしまう場合は「線分なし」として扱う。
    if hypot(bx - ax, by - ay) < eps:
        return None

    return (ax, ay), (bx, by)


def _append_point(
    points: list[tuple[float, float]],
    xy: tuple[float, float],
    *,
    eps: float = 1e-9,
) -> None:
    """直前点と同一（極近傍）なら追加せず、そうでなければ追加する。"""

    # クリップ処理では境界交点などが連続して出やすいので、
    # 近すぎる点は抑制して「無意味な G1」を減らす。
    if points:
        x0, y0 = points[-1]
        x1, y1 = xy
        if hypot(x1 - x0, y1 - y0) < eps:
            return
    points.append(xy)


def _clip_polyline_to_rect(
    polyline_xy: np.ndarray,
    rect: tuple[float, float, float, float],
) -> list[list[tuple[float, float]]]:
    """polyline を矩形へクリップし、紙内に残る polyline 群を返す。"""

    # 方針:
    # - 元 polyline を「連続点の線分列」として扱う
    # - 各線分を矩形へクリップする
    # - クリップ結果が連続する範囲を 1 つの polyline としてまとめ、断絶があれば分割する
    #
    # 出力は「紙内に残る polyline 群」なので、紙外を跨ぐ部分はここで断ち切られる。
    # これにより export 側は「分断された区間は必ずペンアップ移動」を簡単に実現できる。

    if polyline_xy.shape[0] < 2:
        return []

    out: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    for i in range(int(polyline_xy.shape[0]) - 1):
        # 元線分の端点。
        p0 = (float(polyline_xy[i, 0]), float(polyline_xy[i, 1]))
        p1 = (float(polyline_xy[i + 1, 0]), float(polyline_xy[i + 1, 1]))
        clipped = _clip_segment_to_rect(p0, p1, rect)

        if clipped is None:
            # 今の線分は紙内に寄与しないので、溜めていた polyline を確定してリセットする。
            if current and len(current) >= 2:
                out.append(current)
            current = []
            continue

        a, b = clipped
        if not current:
            # 新しい紙内 polyline を開始する。
            current = []
            _append_point(current, a)
            _append_point(current, b)
        else:
            if hypot(a[0] - current[-1][0], a[1] - current[-1][1]) > 1e-9:
                # 連続性が崩れた（紙外を跨いだ / 別辺から再侵入した等）ので分割する。
                if len(current) >= 2:
                    out.append(current)
                current = []
                _append_point(current, a)
                _append_point(current, b)
            else:
                # 直前点から連続しているので末尾へ延長する。
                _append_point(current, b)

        if not _is_inside_rect(p1, rect):
            # 次の元点が紙外なら「ここで紙外へ出た」ことになるので flush する。
            # これにより export 側で「次の紙内復帰は必ずペンアップ移動」とできる。
            if current and len(current) >= 2:
                out.append(current)
            current = []

    if current and len(current) >= 2:
        out.append(current)

    return out


def _paper_safe_rect(
    canvas_size: tuple[float, float],
    *,
    paper_margin_mm: float,
) -> tuple[float, float, float, float]:
    """紙（canvas）の安全領域矩形 `[x_min, x_max] × [y_min, y_max]` を返す。"""

    w, h = canvas_size
    m = float(paper_margin_mm)
    if m < 0:
        raise ValueError("paper_margin_mm は 0 以上である必要がある")
    if m * 2 >= w or m * 2 >= h:
        # 余白が大きすぎると安全領域が空になるため、クリップが常に消える。
        raise ValueError("paper_margin_mm が大きすぎます（安全領域が空になります）")
    return (m, w - m, m, h - m)


def _canvas_to_machine_xy(
    xy: tuple[float, float],
    *,
    params: GCodeParams,
    canvas_size: tuple[float, float],
) -> tuple[float, float]:
    """canvas 座標（紙座標）を machine 座標へ変換して返す。

    Notes
    -----
    変換順序は「Y 反転 → origin 加算」。
    """

    x, y = xy
    if params.y_down:
        # y_down=True の場合:
        # canvas は `(0,0)` が左上・Y が下向き、の感覚で描けるようにしつつ、
        # 出力は `y -> (H - y)` で反転して機械座標へ合わせる。
        canvas_h = (
            float(params.canvas_height_mm)
            if params.canvas_height_mm is not None
            else float(canvas_size[1])
        )
        y = canvas_h - y

    # origin は「機械原点との差」を吸収するためのオフセット。
    ox, oy = params.origin
    return x + float(ox), y + float(oy)


def _quantize_xy(xy: tuple[float, float], *, decimals: int) -> tuple[float, float]:
    """出力用に XY を丸めて返す。"""

    # G-code の範囲検証は「実際に出力する値」で行いたいので、
    # 丸めは文字列化より先に行い、以降は丸め後座標を正とする。
    x, y = xy
    return (float(round(float(x), int(decimals))), float(round(float(y), int(decimals))))


def _validate_bed_xy(
    xy: tuple[float, float],
    *,
    bed_x_range: tuple[float, float] | None,
    bed_y_range: tuple[float, float] | None,
) -> None:
    """ベッド範囲（3D プリンタの安全領域）を検証する。

    Notes
    -----
    この検証は「入力の頂点が範囲外かどうか」ではなく、
    **実際に出力する `G1 X.. Y..` の移動先**が範囲外かどうかだけを確認する。
    （紙クリップ後の出力が安全なら、入力が大きくても許容する）
    """

    if bed_x_range is None and bed_y_range is None:
        return

    x, y = xy
    if bed_x_range is not None:
        x_min, x_max = bed_x_range
        if not (float(x_min) <= x <= float(x_max)):
            raise ValueError("G-code 出力が bed_x_range の範囲外です")
    if bed_y_range is not None:
        y_min, y_max = bed_y_range
        if not (float(y_min) <= y <= float(y_max)):
            raise ValueError("G-code 出力が bed_y_range の範囲外です")


def export_gcode(
    layers: Sequence[RealizedLayer],
    path: str | Path,
    *,
    canvas_size: tuple[float, float],
    params: GCodeParams | None = None,
) -> Path:
    """Layer 列を G-code として保存する。

    Parameters
    ----------
    layers : Sequence[RealizedLayer]
        realize 済みの Layer 列。
    path : str or Path
        出力先パス。
    canvas_size : tuple[float, float]
        紙サイズ（mm）として扱うキャンバス寸法 `(width, height)`。
    params : GCodeParams or None
        G-code 出力パラメータ。None の場合は既定値を使う。

    Returns
    -------
    Path
        保存先パス（正規化済み）。

    Raises
    ------
    ValueError
        `canvas_size` が不正、または bed 範囲検証に失敗した場合。
    """

    # --- パイプライン（処理順）---
    # 1) canvas_size から紙の安全領域（safe_rect）を決める（紙めくれ防止）。
    # 2) realized の polyline を safe_rect にクリップして「紙内区間」だけに分割する。
    # 3) 各区間の開始ごとに「travel/draw の切替」「近接連結」を判断する。
    # 4) move ごとに (canvas -> machine) 変換し、丸め、bed 範囲を検証し、G1 X/Y を出力する。
    #
    # 方針の要点:
    # - 紙外を跨ぐ箇所は必ず Z up のまま移動する（force_travel）。
    # - bed 範囲検証は「実際に出力した座標」だけを対象にする。
    # - 近接連結は polyline 間の最適化だが、紙外由来の分断には適用しない。

    _path = Path(path)
    p = params if params is not None else GCodeParams()

    # canvas_size は「紙サイズ（mm）」として扱う。
    canvas_w, canvas_h = float(canvas_size[0]), float(canvas_size[1])
    if canvas_w <= 0 or canvas_h <= 0:
        raise ValueError("canvas_size は正の (width, height) である必要がある")
    canvas = (canvas_w, canvas_h)

    # 紙の外周へ安全マージンを入れた「描画してよい矩形」。
    safe_rect = _paper_safe_rect(canvas, paper_margin_mm=float(p.paper_margin_mm))

    # 出力の決定性を優先し、整数化できるものは先に正規化しておく。
    decimals = int(p.decimals)
    travel_feed_i = int(round(float(p.travel_feed)))
    draw_feed_i = int(round(float(p.draw_feed)))

    lines: list[str] = []
    lines.extend(
        [
            "; ====== Header ======",
            "G21 ; Set units to millimeters",
            "G90 ; Absolute positioning",
            "G28 ; Home all axes",
            "M107 ; Turn off fan",
            "M420 S1 Z10; Enable bed leveling matrix",
            "; ====== Body ======",
        ]
    )

    # set_pen_down()/set_feed()/move_xy() は「同じ命令の連続」を避けるために状態を持つ。
    # - pen_is_down: 現在の Z 状態（ペンが下がっているか）
    # - current_feed: 最後に出力した F 値
    # - current_xy: 最後に出力した XY（丸め後）
    pen_is_down = True
    current_feed: int | None = None
    current_xy: tuple[float, float] | None = None

    def set_pen_down(down: bool) -> None:
        nonlocal pen_is_down
        if bool(down) == pen_is_down:
            return
        pen_is_down = bool(down)
        # down=True で z_down、down=False で z_up を出す。
        z = float(p.z_down) if pen_is_down else float(p.z_up)
        lines.append(f"G1 Z{_fmt_float(round(z, decimals), decimals=decimals)}")

    def set_feed(feed: int) -> None:
        nonlocal current_feed
        if current_feed == int(feed):
            return
        current_feed = int(feed)
        lines.append(f"G1 F{int(feed)}")

    def move_xy(xy_canvas: tuple[float, float]) -> None:
        nonlocal current_xy
        # move の都度、座標変換→丸め→bed 検証→G1 生成を行う。
        # （bed 検証は「実際に出力する座標」だけを検証したいので、丸め後で行う）
        xy_machine = _canvas_to_machine_xy(xy_canvas, params=p, canvas_size=canvas)
        xy_q = _quantize_xy(xy_machine, decimals=decimals)
        _validate_bed_xy(xy_q, bed_x_range=p.bed_x_range, bed_y_range=p.bed_y_range)
        if current_xy is not None and hypot(xy_q[0] - current_xy[0], xy_q[1] - current_xy[1]) < 1e-12:
            return
        current_xy = xy_q
        x_txt = _fmt_float(xy_q[0], decimals=decimals)
        y_txt = _fmt_float(xy_q[1], decimals=decimals)
        lines.append(f"G1 X{x_txt} Y{y_txt}")

    # 近接連結のために「前の polyline の終点」を覚えておく。
    # レイヤを跨ぐときは事故線のリスクがあるのでリセットする（後述）。
    prev_last_in_layer: tuple[float, float] | None = None
    connect_dist = p.connect_distance

    for layer_idx, layer in enumerate(layers):
        coords = np.asarray(layer.realized.coords, dtype=np.float64)
        offsets = np.asarray(layer.realized.offsets, dtype=np.int32)

        lines.append(f"; layer {int(layer_idx)} start")

        for poly_idx, (start, end) in enumerate(zip(offsets[:-1], offsets[1:])):
            s = int(start)
            e = int(end)
            if e - s < 2:
                continue

            polyline = np.ascontiguousarray(coords[s:e, :2], dtype=np.float64)

            # 紙安全化: polyline を安全領域へクリップし、紙内の連続区間に分割する。
            # `clipped` は list[polyline] であり、複数要素になる場合がある（紙外を跨いだ）。
            clipped = _clip_polyline_to_rect(polyline, safe_rect)
            if not clipped:
                continue

            lines.append(f"; polyline {int(poly_idx)} start")

            for seg_idx, seg in enumerate(clipped):
                if len(seg) < 2:
                    continue

                # seg_idx>0 は「同一 polyline が紙外を跨いで分断された」ことを意味する。
                # このケースでは必ずペンアップ移動で開始点へ行く（紙外ショートカットはしない）。
                force_travel = int(seg_idx) > 0
                start_xy = seg[0]

                connected = False
                if (
                    (not force_travel)
                    and connect_dist is not None
                    and prev_last_in_layer is not None
                ):
                    # 近接連結: 前の終点と次の始点が近ければ「ペンアップ移動」を省略する。
                    # ただし force_travel（紙外由来の分断）には適用しない。
                    connected = hypot(
                        start_xy[0] - prev_last_in_layer[0],
                        start_xy[1] - prev_last_in_layer[1],
                    ) < float(connect_dist)

                if force_travel:
                    # 紙外を跨ぐ分断: ペンアップで開始点へ移動し、そこから描画する。
                    set_pen_down(False)
                    set_feed(travel_feed_i)
                    move_xy(start_xy)
                    set_pen_down(True)
                    set_feed(draw_feed_i)
                elif connected:
                    # 近接連結: ペンを上げずに次の区間へ繋ぐ（最適化）。
                    set_pen_down(True)
                    set_feed(draw_feed_i)
                    move_xy(start_xy)
                else:
                    # 通常: ペンアップで開始点へ移動し、ペンダウンして描画する。
                    set_pen_down(False)
                    set_feed(travel_feed_i)
                    move_xy(start_xy)
                    set_pen_down(True)
                    set_feed(draw_feed_i)

                # seg の残り点はすべて描画フィードのまま順次移動する。
                for xy in seg[1:]:
                    move_xy(xy)

                # 次の polyline との連結判断に使うため、終点を更新する（canvas 座標系）。
                prev_last_in_layer = seg[-1]

            lines.append(f"; polyline {int(poly_idx)} end")

        lines.append(f"; layer {int(layer_idx)} end")

        # レイヤを跨いだ連結は「意図しない線」を作りやすいのでリセットする。
        # （レイヤは色/太さだけでなく、意味的に別ストローク集合として扱う）
        prev_last_in_layer = None

    # 最後は安全側に倒してペンアップで終わる。
    lines.extend(["; ====== Footer ======", f"G1 Z{_fmt_float(round(float(p.z_up), decimals), decimals=decimals)}"])

    _path.parent.mkdir(parents=True, exist_ok=True)
    with _path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return _path


__all__ = ["GCodeParams", "export_gcode"]
