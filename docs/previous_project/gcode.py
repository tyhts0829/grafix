"""
どこで: `engine.export.gcode`。
何を: G-code 出力のパラメータ定義と書き出しクラスのスケルトンを提供する。
なぜ: ランタイムから非ブロッキングで G-code を保存するための土台を分離するため。

本段階（Stage 1/3）では直線補間の最小実装を提供する。
ヘッダ/ボディ/フッタの出力、Z/Feed の切替、オフセット・丸め、
簡易 Y 反転（y -> -y）をサポートする。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO, Tuple

import numpy as np


@dataclass(frozen=True)
class GCodeParams:
    """G-code 生成パラメータ。

    属性:
        travel_feed: ペンアップ移動のフィードレート [mm/min]。
        draw_feed: ペンダウン描画のフィードレート [mm/min]。
        z_up: ペンアップ時の Z 高さ [mm]。
        z_down: ペンダウン時の Z 高さ [mm]。
        y_down: True で Y 反転を行う。
            - `canvas_height_mm` が指定されていれば厳密反転（y -> canvas_height_mm - y）。
            - 未指定時は簡易反転（y -> -y）。
        origin: 出力座標の原点 [mm]（X, Y）。旧実装の既定 (91, -0.75)。
        decimals: 小数点以下の桁数（出力の丸め）。
        connect_distance: 近接連結のしきい値 [mm]。None で無効。
        bed_range: 出力座標の範囲検証 [min, max]。None で無効。
        canvas_height_mm: キャンバスの高さ [mm]。Y 反転の厳密化に使用（任意）。
        canvas_width_mm: キャンバスの幅 [mm]。ファイル名生成や将来の変換補助に使用（任意）。
    """

    travel_feed: float = 1500.0
    draw_feed: float = 1000.0
    z_up: float = 3.0
    z_down: float = -2.0
    y_down: bool = False
    origin: Tuple[float, float] = (91.0, -0.75)
    decimals: int = 3
    connect_distance: float | None = None
    bed_range: Tuple[float, float] | None = None
    canvas_height_mm: float | None = None
    canvas_width_mm: float | None = None


class GCodeWriter:
    """G-code 書き出しクラス（最小実装）。

    `coords` と `offsets` から 2D パスを走査し、`fp` へ G-code をテキスト出力する。
    - ヘッダ/フッタの最小生成
    - ライン開始前の Z/Feed 切替（ペンアップ/早送り → 2点目前でペンダウン/描画）
    - `origin` 適用、`decimals` 丸め、簡易 Y 反転（`y_down=True` で y -> -y）
    - 近接連結（`connect_distance`）と範囲検証（`bed_range`）のオプション対応
    """

    def write(
        self,
        coords: np.ndarray,
        offsets: np.ndarray,
        params: GCodeParams,
        fp: IO[str],
    ) -> None:
        """与えられたジオメトリを G-code として `fp` に書き出す。

        引数:
            coords: 形状座標の連結配列。形状は `offsets` で区切られる想定。
            offsets: 各ラインの開始インデックス群（終端を含む累積オフセット）。
            params: G-code 出力パラメータ。
            fp: テキスト書き出し先（開かれたファイルオブジェクト）。
        """
        # --- 前処理: 次元/座標系/オフセット/範囲 ---
        xy = np.ascontiguousarray(coords[:, :2], dtype=np.float64)
        if params.y_down:
            xy = xy.copy()
            if params.canvas_height_mm is not None:
                xy[:, 1] = float(params.canvas_height_mm) - xy[:, 1]
            else:
                xy[:, 1] = -xy[:, 1]
        # 原点オフセットを加算
        ox, oy = params.origin
        if ox != 0 or oy != 0:
            xy = xy + np.array([ox, oy], dtype=np.float64)
        # 範囲検証（オプトイン）: オフセット後の実座標で検証
        if params.bed_range is not None:
            rmin, rmax = params.bed_range
            if not (
                np.all((xy[:, 0] >= rmin) & (xy[:, 0] <= rmax))
                and np.all((xy[:, 1] >= rmin) & (xy[:, 1] <= rmax))
            ):
                raise ValueError("vertex is out of bed_range")

        # 出力補助
        def fmt_xy(x: float, y: float) -> str:
            nd = int(params.decimals)
            return f"G1 X{round(x, nd)} Y{round(y, nd)}"

        def f_travel() -> list[str]:
            return [
                f"G1 Z{round(params.z_up, params.decimals)}",
                f"G1 F{int(round(params.travel_feed))}",
            ]

        def f_draw() -> list[str]:
            return [
                f"G1 Z{round(params.z_down, params.decimals)}",
                f"G1 F{int(round(params.draw_feed))}",
            ]

        # --- Header ---
        header = [
            "; ====== Header ======",
            "G21 ; Set units to millimeters",
            "G90 ; Absolute positioning",
            "G28 ; Home all axes",
            "M107 ; Turn off fan",
            "M420 S1 Z10; Enable bed leveling matrix",
            "; ====== Body ======",
        ]
        fp.write("\n".join(header) + "\n")

        # --- Body ---
        decimals = int(params.decimals)
        connect = params.connect_distance
        prev_last: tuple[float, float] | None = None
        n_lines = int(len(offsets) - 1)
        for li in range(n_lines):
            s = int(offsets[li])
            e = int(offsets[li + 1])
            if e <= s:
                continue
            verts = xy[s:e]
            # 近接連結の判定（オプトイン）
            start = (float(verts[0, 0]), float(verts[0, 1]))
            end = (float(verts[-1, 0]), float(verts[-1, 1]))
            connected = False
            if connect is not None and prev_last is not None:
                dx = start[0] - prev_last[0]
                dy = start[1] - prev_last[1]
                connected = (dx * dx + dy * dy) ** 0.5 < float(connect)

            fp.write(f"; line {li} start\n")
            # 頂点列を走査
            for vi in range(verts.shape[0]):
                x = float(round(verts[vi, 0], decimals))
                y = float(round(verts[vi, 1], decimals))
                if vi == 0:
                    if not connected:
                        # ライン開始: ペンアップ・早送り
                        fp.write("\n".join(f_travel()) + "\n")
                elif vi == 1:
                    if not connected:
                        # 2点目前: ペンダウン・描画
                        fp.write("\n".join(f_draw()) + "\n")
                fp.write(fmt_xy(x, y) + "\n")
            fp.write(f"; line {li} end\n")
            prev_last = end

        # --- Footer ---
        footer = [
            "; ====== Footer ======",
            f"G1 Z{round(params.z_up, params.decimals)}",
        ]
        fp.write("\n".join(footer) + "\n")
