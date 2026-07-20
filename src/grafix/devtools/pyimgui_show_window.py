import imgui
import pyglet

from grafix.interactive.parameter_gui.pyglet_backend import (
    create_imgui_pyglet_renderer,
)


def main():
    window = pyglet.window.Window(
        1280, 720, caption="pyimgui + pyglet demo", resizable=True
    )

    imgui.create_context()
    impl = create_imgui_pyglet_renderer(window)

    @window.event
    def on_draw():
        window.clear()

        # 念のため毎フレーム更新（バックエンドが面倒を見てくれる場合もある）
        imgui.get_io().display_size = window.get_size()

        imgui.new_frame()
        imgui.show_demo_window()
        imgui.render()

        impl.render(imgui.get_draw_data())

    try:
        pyglet.app.run()
    finally:
        impl.shutdown()


if __name__ == "__main__":
    main()
