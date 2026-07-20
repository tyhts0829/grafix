# どこで: `src/grafix/interactive/draw_window.py`。
# 何を: ライブ描画用の pyglet ウィンドウ生成を行う。
# なぜ: interactive 依存をこの層に閉じ込め、core/export をヘッドレスに保つため。

from __future__ import annotations

import pyglet
from pyglet.gl import Config
from pyglet.window import Window

from grafix.core.render_options import RenderOptions

MINIMUM_DRAW_WINDOW_WIDTH = 320
MINIMUM_DRAW_WINDOW_HEIGHT = 320


def create_draw_window(options: RenderOptions, *, render_scale: float) -> Window:
    """設定に基づき描画ウィンドウを生成する。"""
    # 線描画を滑らかにするために MSAA を有効化
    config = Config(double_buffer=True, sample_buffers=1, samples=4)  # type: ignore[abstract]
    canvas_w, canvas_h = options.canvas_size
    window = pyglet.window.Window(  # type: ignore[abstract]
        width=int(canvas_w * render_scale),
        height=int(canvas_h * render_scale),
        # viewport は DrawWindowSystem が毎 frame framebuffer size へ同期する。
        # 小さな画面や作業配置に合わせて preview を調整できるようにする。
        resizable=True,
        caption="Grafix",
        config=config,
    )
    window.set_minimum_size(MINIMUM_DRAW_WINDOW_WIDTH, MINIMUM_DRAW_WINDOW_HEIGHT)
    return window
