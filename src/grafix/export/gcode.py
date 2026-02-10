"""
どこで: `src/grafix/export/gcode.py`。
何を: realize 済みシーンを G-code として保存する関数を提供する。
なぜ: ペンプロッタ向け出力を interactive 依存なしで追加できるようにするため。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import hypot
from pathlib import Path

import numpy as np

from grafix.core.pipeline import RealizedLayer
from grafix.core.runtime_config import runtime_config

_DEFAULT_PAPER_MARGIN_MM = 2.0

# --- 実装全体の前提（概要）---
#
# 入力（RealizedLayer）は「連結 coords 配列 + offsets（polyline 境界）」を持つ。
# 本モジュールはそれを G-code（主に G1）へ落とし込むため、以下の順で処理する。
#
# 1) 紙の安全領域（paper_margin_mm）を決める
# 2) polyline を安全領域へクリップし、紙内に残る連続区間（stroke）へ分割する
# 3) レイヤ内で stroke の順序を（任意で）並び替え、ペンアップ移動距離を減らす（optimize_travel）
# 4) stroke 間の移動が十分短い場合、ペンアップを省略して描画で繋ぐ（bridge_draw_distance）
#    - これは「移動距離短縮」ではなく「線を足す」トレードオフである点に注意
# 5) move ごとに (canvas -> machine) 変換 → 丸め → bed 範囲検証 → `G1 X.. Y..` を出す
#
# 決定性（同一入力→同一出力）のための工夫:
# - 数値は常に固定小数フォーマット（_fmt_float）
# - bed 検証は「実際に出力する値（丸め後）」に対して行う（_quantize_xy→_validate_bed_xy）
# - 並び替えの距離比較は量子化（整数）し、タイブレーク規則を固定する（_order_strokes_in_layer）


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
    bed_x_range : tuple[float, float] or None
        3D プリンタのベッド X 範囲 [mm]。None で無効。
    bed_y_range : tuple[float, float] or None
        3D プリンタのベッド Y 範囲 [mm]。None で無効。
    bridge_draw_distance : float or None
        ストローク間の移動距離がこの値より小さければ、ペンアップを省略して描画で繋ぐ。
        None の場合は無効。
    optimize_travel : bool
        True の場合、レイヤ内でストローク順を並び替えてペンアップ移動距離を小さくする。
    allow_reverse : bool
        `optimize_travel=True` の場合、ストロークの逆向き描画を許可する。
    canvas_height_mm : float or None
        `y_down=True` 時の厳密反転に使うキャンバス高さ [mm]。
        None の場合、`export_gcode(canvas_size=...)` の高さを使う。
    """

    travel_feed: float = 3000.0
    draw_feed: float = 3000.0
    z_up: float = 3.0
    z_down: float = -1.0
    y_down: bool = True
    origin: tuple[float, float] = (154.019, 14.195)
    # origin: tuple[float, float] = (91.0, -0.75)
    decimals: int = 3
    paper_margin_mm: float = _DEFAULT_PAPER_MARGIN_MM
    bed_x_range: tuple[float, float] | None = None
    bed_y_range: tuple[float, float] | None = None
    bridge_draw_distance: float | None = 0.5
    optimize_travel: bool = True
    allow_reverse: bool = True
    canvas_height_mm: float | None = None


def _fmt_float(value: float, *, decimals: int) -> str:
    """小数を固定桁の文字列にして返す。

    Notes
    -----
    G-code はテキストであり、出力が少しでも揺れると差分比較が難しくなる。
    そのため常に固定桁でフォーマットし、`-0.000` のような表現だけを `0.000` に正規化する。
    """

    # G-code は単なるテキストなので、同じ値でも表記揺れがあると差分が読めなくなる。
    # ここでは「固定小数・固定桁」で文字列化し、出力の決定性を最優先する。
    text = f"{float(value):.{int(decimals)}f}"
    if text.startswith("-0") and float(text) == 0.0:
        # `-0.000` は数値としては 0 なので、見た目だけの符号差を潰して diff を安定させる。
        return text[1:]
    return text


def _is_inside_rect(
    xy: tuple[float, float], rect: tuple[float, float, float, float]
) -> bool:
    """点が矩形（閉区間）に含まれるなら True を返す。"""

    # クリップと整合するよう「閉区間（境界を含む）」で判定する。
    # 紙境界上の点は描画許可としないと、出入口で意図せず途切れやすい。
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
    #
    # 重要: この関数は「交点 1 点だけ」になるような極短線分を None 扱いにする。
    # クリップの境界交点が連続して出るケースで、無意味なゼロ移動 G1 を増やさないため。

    x0, y0 = p0
    x1, y1 = p1
    x_min, x_max, y_min, y_max = rect

    dx = x1 - x0
    dy = y1 - y0

    # 可視区間の u 範囲（最初は線分全体）。
    # 以降の制約更新で、矩形内に残る u の範囲へ狭めていく。
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
        # u の許容範囲を狭めるだけなので、交点座標は最後に 1 回だけ計算する。
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
    # u1==u2 に近い場合は「点」に潰れるので後段で None 扱いにする。
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

    # クリップ処理では境界交点が連続しやすく、
    # そのまま出力すると「同一点へ移動する G1」が増えてファイルが読みにくくなる。
    # ここでは微小差を許容して点を間引き、G-code の冗長さを抑える。
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
            # （紙外を跨いで直線で繋ぐと、紙の外周をショートカットして事故りやすい）
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

    # ここでの矩形は canvas 座標系（= ユーザーが描く座標系）で定義する。
    # y_down/origin などの機械座標変換は「クリップ後」に適用する。
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

    # 注意: 距離（mm）は Y 反転や origin 平行移動では変わらない（等長変換）。
    # そのため「距離評価（最適化）」は canvas 座標系のままでも成立する。
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
    # ここで丸めておくと `move_xy()` が「同一点なら出力しない」判定も安定する。
    x, y = xy
    return (
        float(round(float(x), int(decimals))),
        float(round(float(y), int(decimals))),
    )


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

    # 範囲検証は危険側（機械破損）に倒すので、範囲外は即例外とする。
    # 一方で、検証対象は「紙クリップ + 変換 + 丸め後の出力点」に限定する。
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


@dataclass(frozen=True, slots=True)
class _Stroke:
    """レイヤ内の 1 ストローク（紙内に残る連続区間）を表す。

    Notes
    -----
    points_canvas:
        canvas 座標系の点列（この順に辿ると「描画線」になる）。
    start_q / end_q:
        距離比較のための量子化座標（整数）。
        浮動小数の微小差で順序が揺れないよう、一定の分解能で丸めた値を使う。
    """

    poly_idx: int
    seg_idx: int
    points_canvas: list[tuple[float, float]]
    start_q: tuple[int, int]
    end_q: tuple[int, int]


def _order_strokes_in_layer(
    strokes: list[_Stroke],
    *,
    allow_reverse: bool,
) -> list[tuple[_Stroke, bool]]:
    """レイヤ内のストローク順を決めて返す。

    Notes
    -----
    - 先頭ストロークは入力順の先頭固定（反転もしない）。
    - 以降は貪欲法で、直前ストローク終点からのペンアップ距離が最短となる次ストロークを選ぶ。
    - 距離が同じ場合は `(poly_idx, seg_idx)` の昇順で安定化し、反転同距離なら元向きを優先する。
    """

    # 入力順そのものにも意味がある場合があるため、先頭 stroke は固定する。
    # （例: レイヤの “最初の一筆” を作者が意図的に決めているケース）
    if not strokes:
        return []
    if len(strokes) == 1:
        return [(strokes[0], False)]

    ordered: list[tuple[_Stroke, bool]] = [(strokes[0], False)]
    current_end_q = strokes[0].end_q

    # 以降は「今いる点」から最も近い stroke を貪欲に選ぶ。
    # O(N^2) だが、TSP 厳密解より実装が単純で十分効果がある。
    remaining = list(strokes[1:])
    while remaining:
        best_i = 0
        best_rev = False
        best_key: tuple[int, tuple[int, int], int] | None = None

        for i, st in enumerate(remaining):
            # 距離は平方距離で比較する（sqrt を避け、同時に誤差源を減らす）。
            dx = int(st.start_q[0]) - int(current_end_q[0])
            dy = int(st.start_q[1]) - int(current_end_q[1])
            dist2 = dx * dx + dy * dy
            # key の最後の 0/1 は「同距離なら反転しない向きを優先」するためのタイブレーク。
            key = (int(dist2), (int(st.poly_idx), int(st.seg_idx)), 0)
            if best_key is None or key < best_key:
                best_key = key
                best_i = int(i)
                best_rev = False

            if not allow_reverse:
                continue

            dx_r = int(st.end_q[0]) - int(current_end_q[0])
            dy_r = int(st.end_q[1]) - int(current_end_q[1])
            dist2_r = dx_r * dx_r + dy_r * dy_r
            key_r = (int(dist2_r), (int(st.poly_idx), int(st.seg_idx)), 1)
            if best_key is None or key_r < best_key:
                best_key = key_r
                best_i = int(i)
                best_rev = True

        chosen = remaining.pop(best_i)
        ordered.append((chosen, bool(best_rev)))
        current_end_q = chosen.start_q if best_rev else chosen.end_q

    return ordered


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
        G-code 出力パラメータ。None の場合は `config.yaml`（`export.gcode`）の設定値を使う。

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
    # 3) 各レイヤ内でストローク順を最適化し（任意）、その順に travel/draw を出力する。
    # 4) move ごとに (canvas -> machine) 変換し、丸め、bed 範囲を検証し、G1 X/Y を出力する。
    #
    # 方針の要点:
    # - travel 最適化はペンアップ移動のみを対象とし、描画ジオメトリ（点列）は変えない。
    # - bed 範囲検証は「実際に出力した座標」だけを対象にする。

    _path = Path(path)
    if params is not None:
        p = params
    else:
        cfg = runtime_config().gcode
        p = GCodeParams(
            travel_feed=float(cfg.travel_feed),
            draw_feed=float(cfg.draw_feed),
            z_up=float(cfg.z_up),
            z_down=float(cfg.z_down),
            y_down=bool(cfg.y_down),
            origin=(float(cfg.origin[0]), float(cfg.origin[1])),
            decimals=int(cfg.decimals),
            paper_margin_mm=float(cfg.paper_margin_mm),
            bed_x_range=cfg.bed_x_range,
            bed_y_range=cfg.bed_y_range,
            bridge_draw_distance=cfg.bridge_draw_distance,
            optimize_travel=bool(cfg.optimize_travel),
            allow_reverse=bool(cfg.allow_reverse),
            canvas_height_mm=cfg.canvas_height_mm,
        )

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

    # ここでは「一般的な 3D プリンタ系 G-code」のヘッダをそのまま流用している。
    # プロッタ専用の最適化（例: モータ無効化、加速度の抑制）は行っていない。
    # 重要なのは X/Y の直線移動（G1）と Z の上下（pen up/down 相当）が出ること。

    # set_pen_down()/set_feed()/move_xy() は「同じ命令の連続」を避けるために状態を持つ。
    # - pen_is_down: 現在の Z 状態（ペンが下がっているか）
    # - current_feed: 最後に出力した F 値
    # - current_xy: 最後に出力した XY（丸め後）
    #
    # 初期値に True を置くのは「最初の set_pen_down(False) で必ず Z_up を出す」ため。
    # （ヘッダで Z を明示しない前提なので、travel の前に必ずペンアップしたい）
    pen_is_down = True
    current_feed: int | None = None
    current_xy: tuple[float, float] | None = None

    def set_pen_down(down: bool) -> None:
        nonlocal pen_is_down
        # Z の上げ下げは同じ値を連続で出すと冗長なので、状態で省略する。
        if bool(down) == pen_is_down:
            return
        pen_is_down = bool(down)
        # down=True で z_down、down=False で z_up を出す（どちらも params 由来）。
        # 注意: ここでは Z の移動自体も `G1` にしている（機械側の解釈に依存しにくい）。
        z = float(p.z_down) if pen_is_down else float(p.z_up)
        lines.append(f"G1 Z{_fmt_float(round(z, decimals), decimals=decimals)}")

    def set_feed(feed: int) -> None:
        nonlocal current_feed
        # フィードレートも同値の連続出力を避け、必要なタイミングでだけ切り替える。
        if current_feed == int(feed):
            return
        current_feed = int(feed)
        lines.append(f"G1 F{int(feed)}")

    def move_xy(xy_canvas: tuple[float, float]) -> None:
        nonlocal current_xy
        # move の都度、座標変換→丸め→bed 検証→G1 生成を行う。
        #
        # - 変換: canvas（紙）座標はユーザーの描画座標なので、機械座標へ写像する必要がある
        # - 丸め: “出力値” を正として扱い、以降の重複判定や bed 検証も丸め後で統一する
        # - bed 検証: 実際に出力する X/Y が安全領域内かだけを見る
        # - 重複抑制: 同一点への移動は G-code を読みづらくするので省略する
        xy_machine = _canvas_to_machine_xy(xy_canvas, params=p, canvas_size=canvas)
        xy_q = _quantize_xy(xy_machine, decimals=decimals)
        _validate_bed_xy(xy_q, bed_x_range=p.bed_x_range, bed_y_range=p.bed_y_range)
        if (
            current_xy is not None
            and hypot(xy_q[0] - current_xy[0], xy_q[1] - current_xy[1]) < 1e-12
        ):
            return
        current_xy = xy_q
        x_txt = _fmt_float(xy_q[0], decimals=decimals)
        y_txt = _fmt_float(xy_q[1], decimals=decimals)
        lines.append(f"G1 X{x_txt} Y{y_txt}")

    # ストロークの距離比較は「量子化した整数」で行う。
    # `decimals` と同じ分解能で整数化することで、出力丸めと整合し、タイブレークも安定する。
    scale = 10 ** int(decimals)

    # レイヤは順に処理し、1 レイヤを書き切ってから次のレイヤへ進む。
    # つまり travel 最適化もブリッジ判定も「レイヤ内だけ」で完結する（レイヤ跨ぎはしない）。
    for layer_idx, layer in enumerate(layers):
        coords = np.asarray(layer.realized.coords, dtype=np.float64)
        offsets = np.asarray(layer.realized.offsets, dtype=np.int32)

        lines.append(f"; layer {int(layer_idx)} start")

        # strokes は「紙内に残る連続区間」の集合。
        # 元の polyline は紙外へ出入りしうるため、クリップ後は複数 stroke に分割される。
        strokes: list[_Stroke] = []

        for poly_idx, (start, end) in enumerate(zip(offsets[:-1], offsets[1:])):
            s = int(start)
            e = int(end)
            if e - s < 2:
                continue

            # realized.coords は (x, y, ...) を含みうるが、ここでは XY のみを使う。
            # 1 polyline は offsets の区間 [s:e] で表される。
            polyline = np.ascontiguousarray(coords[s:e, :2], dtype=np.float64)

            # 紙安全化: polyline を安全領域へクリップし、紙内の連続区間に分割する。
            # `clipped` は list[polyline] であり、複数要素になる場合がある（紙外を跨いだ）。
            clipped = _clip_polyline_to_rect(polyline, safe_rect)
            if not clipped:
                continue

            for seg_idx, seg in enumerate(clipped):
                if len(seg) < 2:
                    continue

                start_xy = seg[0]
                end_xy = seg[-1]
                # start_q/end_q は「距離比較用」の量子化点。
                # 距離評価は canvas 座標系で行う（Y 反転や origin 平行移動は距離を変えないため）。
                start_q = (
                    int(round(float(start_xy[0]) * scale)),
                    int(round(float(start_xy[1]) * scale)),
                )
                end_q = (
                    int(round(float(end_xy[0]) * scale)),
                    int(round(float(end_xy[1]) * scale)),
                )
                strokes.append(
                    _Stroke(
                        poly_idx=int(poly_idx),
                        seg_idx=int(seg_idx),
                        points_canvas=list(seg),
                        start_q=start_q,
                        end_q=end_q,
                    )
                )

        if bool(p.optimize_travel):
            # レイヤ内で stroke 順を並び替え、ペンアップ移動（travel）を短くする。
            # 先頭 stroke は入力順固定にして、作者の意図（最初の一筆）を保ちやすくする。
            ordered = _order_strokes_in_layer(
                strokes, allow_reverse=bool(p.allow_reverse)
            )
        else:
            # 並び替えしない場合でも、型を揃えるため (stroke, reversed) 形式にする。
            ordered = [(st, False) for st in strokes]

        bridge_draw_dist = p.bridge_draw_distance
        if bridge_draw_dist is not None and float(bridge_draw_dist) < 0.0:
            raise ValueError("bridge_draw_distance は 0 以上である必要がある")

        # current_end_q は「直前に描いた stroke の終点（量子化）」。
        # レイヤ冒頭で None に戻すので、レイヤを跨いだブリッジ描画は発生しない。
        current_end_q: tuple[int, int] | None = None
        for stroke, reversed_ in ordered:
            pts = stroke.points_canvas
            if len(pts) < 2:
                continue

            lines.append(
                f"; stroke polyline {int(stroke.poly_idx)} seg {int(stroke.seg_idx)}"
                f"{' reversed' if reversed_ else ''}"
            )

            rest: Iterable[tuple[float, float]]
            if reversed_:
                # 反転あり: 終点から描き始め、点列を逆順に辿る。
                # （描画線そのものは同じだが、描画方向は変わる）
                start_xy = pts[-1]
                rest = reversed(pts[:-1])
                start_q = stroke.end_q
                end_q = stroke.start_q
            else:
                # 通常: 始点から描き始め、点列を前から辿る。
                start_xy = pts[0]
                rest = pts[1:]
                start_q = stroke.start_q
                end_q = stroke.end_q

            draw_bridge = False
            if bridge_draw_dist is not None and current_end_q is not None:
                # ブリッジ判定:
                # ペンアップ travel が “十分短い” 場合に限り、ペンアップせずに直線で繋ぐ。
                # 注意: これは「移動距離を減らす」のではなく「線を足す」トレードオフ。
                dx = int(start_q[0]) - int(current_end_q[0])
                dy = int(start_q[1]) - int(current_end_q[1])
                dist2 = dx * dx + dy * dy
                thr_q = float(bridge_draw_dist) * float(scale)
                draw_bridge = float(dist2) < thr_q * thr_q

            if draw_bridge:
                # ペンアップ移動が十分短いなら、ペンを上げずに直線で繋ぐ（最適化）。
                # ここでの move_xy(start_xy) は “描画” なので、短い直線が追加される。
                set_pen_down(True)
                set_feed(draw_feed_i)
                move_xy(start_xy)
            else:
                # 通常は pen up → travel → pen down の順で「移動」と「描画」を分離する。
                set_pen_down(False)
                set_feed(travel_feed_i)
                move_xy(start_xy)
                set_pen_down(True)
                set_feed(draw_feed_i)

            for xy in rest:
                move_xy(xy)
            current_end_q = end_q

        lines.append(f"; layer {int(layer_idx)} end")

    # 最後は安全側に倒してペンアップで終わる。
    # 現状は `z_up` そのままではなく、さらに +20mm 持ち上げた高さを出力する（既存仕様）。
    lines.extend(
        [
            "; ====== Footer ======",
            f"G1 Z{_fmt_float(round(float(p.z_up+20), decimals), decimals=decimals)}",
        ]
    )

    # 末尾の改行は環境差を減らすために常に付ける（POSIX 的なテキストファイルの慣習）。
    _path.parent.mkdir(parents=True, exist_ok=True)
    with _path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return _path


__all__ = ["GCodeParams", "export_gcode"]
