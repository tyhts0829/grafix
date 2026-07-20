# どこで: `src/grafix/interactive/parameter_gui/pyglet_backend.py`。
# 何を: pyglet + imgui の backend（window 生成 / renderer 作成 / IO 同期）を提供する。
# なぜ: GUI の描画ループ（ParameterGUI）から、backend 固有の処理を分離するため。

from __future__ import annotations

from typing import Any, Protocol

DEFAULT_WINDOW_WIDTH = 1100
DEFAULT_WINDOW_HEIGHT = 1000
# 3 固定列を保ったまま Value slider に約 175 px を残せる下限。
MINIMUM_PARAMETER_GUI_WINDOW_WIDTH = 760
MINIMUM_PARAMETER_GUI_WINDOW_HEIGHT = 480


class ImguiPygletRenderer(Protocol):
    """Grafix の pyglet 描画ループが使う renderer 契約。"""

    def process_inputs(self) -> None: ...

    def render(self, draw_data: Any) -> None: ...

    def refresh_font_texture(self) -> None: ...

    def shutdown(self) -> None: ...


class ImguiContentRegion(Protocol):
    """利用可能な ImGui content 幅を公開する最小契約。"""

    def get_content_region_available_width(self) -> float: ...


def _install_imgui_clipboard_callbacks(imgui_mod: Any) -> None:
    """ImGui の clipboard callback を OS と接続する。"""

    io = imgui_mod.get_io()
    if io.get_clipboard_text_fn is not None or io.set_clipboard_text_fn is not None:
        return

    import sys

    if sys.platform == "darwin":
        import subprocess

        def _set_clipboard_text(text: str) -> None:
            subprocess.run(["pbcopy"], input=str(text), text=True, check=False)

        def _get_clipboard_text() -> str:
            result = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, check=False
            )
            return str(result.stdout)

        io.set_clipboard_text_fn = _set_clipboard_text
        io.get_clipboard_text_fn = _get_clipboard_text


def create_imgui_pyglet_renderer(gui_window: Any) -> ImguiPygletRenderer:
    """pyimgui 2 の programmable pyglet renderer を作成する。"""

    from imgui.integrations.pyglet import PygletProgrammablePipelineRenderer

    return PygletProgrammablePipelineRenderer(gui_window)


def content_region_available_width(imgui_mod: ImguiContentRegion) -> float:
    """現在の ImGui window/table cell で利用可能な幅を返す。"""

    return max(0.0, float(imgui_mod.get_content_region_available_width()))


def _sync_imgui_io_for_window(imgui_mod: Any, gui_window: Any, *, dt: float) -> None:
    """ImGui IO をウィンドウ状態（サイズ/Retina スケール/Δt）に同期する。"""

    io = imgui_mod.get_io()
    io.delta_time = max(float(dt), 1e-4)

    fb_w, fb_h = gui_window.get_framebuffer_size()
    win_w, win_h = gui_window.width, gui_window.height
    io.display_size = (float(win_w), float(win_h))
    io.display_fb_scale = (
        float(fb_w) / float(max(1, win_w)),
        float(fb_h) / float(max(1, win_h)),
    )


def create_parameter_gui_window(
    *,
    width: int = DEFAULT_WINDOW_WIDTH,
    height: int = DEFAULT_WINDOW_HEIGHT,
    caption: str = "Grafix Inspector",
    vsync: bool = False,
) -> Any:
    """Parameter GUI 用の pyglet ウィンドウを生成する。"""

    import pyglet

    gl_cfg = pyglet.gl.Config(  # type: ignore[abstract]
        double_buffer=True,
        sample_buffers=1,
        samples=4,
    )
    window = pyglet.window.Window(  # type: ignore[abstract]
        width=int(width),
        height=int(height),
        caption=str(caption),
        # logical window size はユーザーが調整できる状態を保つ。
        # Retina 対応は framebuffer scale / font atlas 側で行い、
        # backing scale によって logical width を縮めない。
        resizable=True,
        vsync=bool(vsync),
        config=gl_cfg,
    )
    window.set_minimum_size(
        MINIMUM_PARAMETER_GUI_WINDOW_WIDTH,
        MINIMUM_PARAMETER_GUI_WINDOW_HEIGHT,
    )
    return window
