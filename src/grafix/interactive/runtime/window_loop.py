# どこで: `src/grafix/interactive/runtime/window_loop.py`。
# 何を: pyglet の複数ウィンドウを 1 つの app loop（`pyglet.app.run()`）で回すための最小ランナーを提供する。
# なぜ: OS 依存のイベント配送を pyglet に任せ、手動 `dispatch_events()` 由来の入力取りこぼしを避けるため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pyglet


@dataclass(frozen=True, slots=True)
class WindowTask:
    """1つの pyglet window と描画・close の方針を束ねる。"""

    # 注: pyglet の Window 型は環境/バージョン差があるため Any に寄せる。
    window: Any

    # 1フレーム分の描画処理（back buffer へ描くだけ）。
    # `switch_to()` / `flip()` は pyglet（`Window.draw()`）が担当する前提。
    draw_frame: Callable[[], None]

    # OS の close request を受けたときの方針。preview は app exit、
    # Inspector は context を破棄せず hide するなど、配線側が明示する。
    on_close: Callable[[], None]


class MultiWindowLoop:
    """複数ウィンドウを同一ループで回す。

    `draw_frame()` は各ウィンドウの back buffer へ描画するだけにし、`flip()` は pyglet が行う。
    """

    def __init__(
        self,
        tasks: list[WindowTask],
        *,
        fps: float,
        on_frame_start: Callable[[], None] | None = None,
    ) -> None:
        """ループを初期化する。

        Parameters
        ----------
        tasks : list[WindowTask]
            1 フレームごとに描画したいウィンドウと描画処理。
        fps : float
            目標フレームレート。`<=0` の場合はスロットリングしない。
            `>0` の場合、`pyglet.clock.schedule_interval` で描画頻度を制御する。
        on_frame_start : Callable[[], None] | None
            各フレーム冒頭に呼ぶコールバック。計測などの用途を想定する。
        """

        self._tasks = list(tasks)
        self._fps = float(fps)
        self._on_frame_start = on_frame_start

    def run(self) -> None:
        """ウィンドウが閉じられるまでループを実行する。"""

        tasks = list(self._tasks)

        def close_handler(task: WindowTask) -> Callable[..., object]:
            def handle_close(*_: object) -> object:
                # EVENT_HANDLED を返さないと default on_close が context/window を
                # 直ちに破棄し、runner の teardown より先になる場合がある。
                task.on_close()
                return pyglet.event.EVENT_HANDLED

            return handle_close

        # close の結果は task ごとに異なる。default handler には委ねない。
        for task in tasks:
            task.window.push_handlers(on_close=close_handler(task))

        # 各ウィンドウの on_draw で、そのウィンドウの描画処理を行う。
        for task in tasks:
            task.window.push_handlers(on_draw=task.draw_frame)

        # 1フレームは大きく「frame start → Window.draw（on_draw→flip）」の順で進める。
        # Window.draw は switch_to / on_draw / on_refresh / flip をまとめて行う。
        def draw_all(dt: float) -> None:
            on_frame_start = self._on_frame_start
            if on_frame_start is not None:
                on_frame_start()

            for task in tasks:
                # 閉じられた window と hide 中の window は描画しない。
                # test double など visible を持たない window は従来通り表示中とみなす。
                if task.window not in pyglet.app.windows or not bool(
                    getattr(task.window, "visible", True)
                ):
                    continue
                task.window.draw(dt)

        # fps<=0 は「スロットリング無し（可能な限り回す）」として扱う。
        if self._fps <= 0:
            pyglet.clock.schedule(draw_all)
        else:
            pyglet.clock.schedule_interval(draw_all, 1.0 / float(self._fps))

        try:
            pyglet.app.run(interval=None)
        finally:
            pyglet.clock.unschedule(draw_all)
