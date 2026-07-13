# どこで: `src/grafix/interactive/runtime/draw_window_system.py`。
# 何を: `draw(t)` が返すシーンを描画ウィンドウへ描画するサブシステムを提供する。
# なぜ: `src/grafix/api/runner.py` の `run()` を「配線」に寄せ、描画責務を独立させるため。

"""
描画ウィンドウ（pyglet + ModernGL）に対して、1 フレームの「入力 → scene 実行 → GL 描画 →
書き出し/録画」を束ねるサブシステム。

このモジュールは interactive ランタイムの中でも副作用が多い（window / GL / ファイル I/O /
別プロセス）ため、責務を `DrawWindowSystem` に寄せ、`runner.run()` は配線だけにする。

読む順番（主要な入口）
----------------------
1. `DrawWindowSystem.__init__()` : window/renderer と各種サブシステムの組み立て
2. `DrawWindowSystem.draw_frame()` : 1 フレーム分の処理（※ flip は呼ばない）
3. `DrawWindowSystem.close()` : teardown（GL コンテキストが生きているうちに release する）

副作用の一覧（把握しておくと読みやすい）
--------------------------------------
- ウィンドウ生成: `create_draw_window()`（pyglet）
- GPU 描画: `DrawRenderer`（ModernGL）
- ファイル書き出し: SVG / PNG / G-code / 動画
- 別プロセス: PNG/G-code を共通の `ExportJobSystem` worker で非同期化
- 標準出力: 保存完了などの通知を `print()` で出す（ログではなく軽い UI フィードバック）
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, cast

from pyglet.window import key

from grafix.core.parameters import ParamStore
from grafix.core.layer import LayerStyleDefaults
from grafix.core.pipeline import RealizedLayer
from grafix.core.output_paths import output_path_for_draw
from grafix.export.svg import export_svg
from grafix.export.image import default_png_output_path, png_output_size
from grafix.interactive.draw_window import create_draw_window
from grafix.interactive.gl.draw_renderer import DrawRenderer
from grafix.interactive.render_settings import RenderSettings
from grafix.core.scene import SceneItem
from grafix.interactive.runtime.perf import PerfCollector
from grafix.interactive.midi import MidiController
from grafix.interactive.runtime.frame_clock import RealTimeClock
from grafix.interactive.runtime.export_job_system import (
    ExportJobStatus,
    ExportJobSystem,
    ExportKind,
    FrameExportSnapshot,
)
from grafix.interactive.runtime.recording_system import VideoRecordingSystem
from grafix.interactive.runtime.scene_runner import SceneRunner
from grafix.core.parameters.style_resolver import StyleResolver
from grafix.interactive.runtime.video_recorder import default_video_output_path

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from grafix.interactive.runtime.monitor import RuntimeMonitor


class DrawWindowSystem:
    """描画（メインウィンドウ）のサブシステム。

    `draw(t)`（ユーザーのコールバック）を `SceneRunner` 経由で評価し、
    得られた `RealizedLayer` 群を `DrawRenderer` で描画する。

    追加で面倒を見るもの（フレームループの横にぶら下がる副作用）
    --------------------------------------------------------
    - キー入力による書き出し:
      - `S`: SVG 保存（同期）
      - `P`: PNG 保存（非同期: 共通 export worker）
      - `G`: G-code 保存（非同期: 共通 export worker）
      - `Shift+G`: G-code をレイヤ別に保存（非同期: 共通 export worker）
      - `V`: 動画録画の開始/停止
    - MIDI: 毎フレーム CC を取り込み（未接続時は frozen snapshot を使う）
    - style: ParamStore から背景色/線幅/線色を解決して反映する
    """

    def __init__(
        self,
        draw: Callable[[float], SceneItem],
        *,
        settings: RenderSettings,
        defaults: LayerStyleDefaults,
        store: ParamStore,
        midi_controller: MidiController | None = None,
        frozen_cc_snapshot: dict[int, float] | None = None,
        monitor: RuntimeMonitor | None = None,
        fps: float = 60.0,
        n_worker: int = 0,
        run_id: str | None = None,
    ) -> None:
        """描画用の window/renderer と各種状態を初期化する。

        初期化で行うこと
        --------------
        - pyglet window 作成 + `DrawRenderer` の初期化（GL コンテキストに紐づく）
        - export 先パスの決定（SVG/G-code/PNG/動画）
        - 録画・PNG/G-code export subsystem の用意
        - `draw(t)` に渡す `t` の基準となる clock の開始
        """

        # 設定/既定スタイル/draw 関数/ParamStore は 1 フレームごとに参照するため保持しておく。
        self._settings = settings
        self._store = store
        self._midi_controller = midi_controller
        self._frozen_cc_snapshot: dict[int, float] = (
            dict(frozen_cc_snapshot) if frozen_cc_snapshot is not None else {}
        )
        self._monitor = monitor

        self._style = StyleResolver(
            self._store,
            base_background_color_rgb01=settings.background_color,
            base_global_thickness=float(defaults.thickness),
            base_global_line_color_rgb01=defaults.color,
        )

        # 描画用の pyglet window を作成し、その window の OpenGL コンテキストに紐づく renderer を作る。
        self.window = create_draw_window(settings)
        self._renderer = DrawRenderer(self.window, settings)

        self._svg_output_path = output_path_for_draw(
            kind="svg", ext="svg", draw=draw, run_id=run_id, canvas_size=settings.canvas_size
        )
        self._gcode_output_path = output_path_for_draw(
            kind="gcode", ext="gcode", draw=draw, run_id=run_id, canvas_size=settings.canvas_size
        )
        self._png_output_path = default_png_output_path(
            draw, run_id=run_id, canvas_size=settings.canvas_size
        )
        video_output_path = default_video_output_path(draw, run_id=run_id, ext="mp4")
        self._recording = VideoRecordingSystem(output_path=video_output_path, fps=float(fps))
        self._last_realized_layers: list[RealizedLayer] = []
        self._pending_png_save = False
        self._pending_gcode_save_mode: str | None = None
        self._export_jobs = ExportJobSystem()
        self.window.push_handlers(on_key_press=self._on_key_press)

        # draw(t) に渡す t の基準時刻。
        start_time = time.perf_counter()
        self._clock = RealTimeClock(start_time=start_time)
        self._perf = PerfCollector.from_env()
        self._scene_runner = SceneRunner(draw, perf=self._perf, n_worker=int(n_worker))

    def _on_key_press(self, symbol: int, modifiers: int) -> None:
        """キーボードショートカットのハンドラ。

        重い処理（PNG/G-code の書き出し）は、イベントコールバック内で実行せず
        フラグを立てて `draw_frame()` 側で処理する（イベント処理を詰まらせないため）。
        """

        if symbol == key.S:
            path = self.save_svg()
            print(f"Saved SVG: {path}")
            return
        if symbol == key.P:
            self._pending_png_save = True
            return
        if symbol == key.G:
            # `G`: 全レイヤ一括
            # `Shift+G`: レイヤごとに分割して保存
            self._pending_gcode_save_mode = (
                "layers" if (int(modifiers) & int(key.MOD_SHIFT)) else "all"
            )
            return
        if symbol == key.V:
            if not self._recording.is_recording:
                self.start_video_recording()
            else:
                self.stop_video_recording()

    def save_svg(self) -> Path:
        """最後に描画したフレームを SVG として保存し、保存先パスを返す。"""
        return export_svg(
            self._last_realized_layers,
            self._svg_output_path,
            canvas_size=self._settings.canvas_size,
        )

    @staticmethod
    def _export_label(kind: ExportKind) -> str:
        if kind is ExportKind.PNG:
            return "PNG"
        return "G-code"

    def _poll_export_results(self) -> None:
        """export worker の終端結果を回収して表示する。"""

        for result in self._export_jobs.poll():
            label = self._export_label(result.kind)
            if result.status is ExportJobStatus.SUCCESS:
                if result.kind is ExportKind.GCODE_LAYERS and not result.paths:
                    print("No layers to export")
                for path in result.paths:
                    print(f"Saved {label}: {path}")
                continue
            if result.status is ExportJobStatus.CANCELLED:
                print(f"Cancelled {label}: {result.output_path}")
                continue
            _logger.error(
                "Failed to save %s (%s): %s",
                label,
                result.status.value,
                result.output_path,
            )
            print(
                f"Failed to save {label} ({result.status.value}): "
                f"{result.output_path}\n{result.error or ''}"
            )

    def _submit_pending_exports(self, snapshot: FrameExportSnapshot) -> None:
        """キー入力で予約された export を immutable snapshot として投入する。"""

        if self._pending_png_save:
            self._pending_png_save = False
            self._export_jobs.submit(
                kind=ExportKind.PNG,
                snapshot=snapshot,
                output_path=self._png_output_path,
                svg_output_path=self._svg_output_path,
                output_size=png_output_size(self._settings.canvas_size),
            )
            print(f"Exporting PNG: {self._png_output_path}")

        pending_mode = self._pending_gcode_save_mode
        if pending_mode is None:
            return
        self._pending_gcode_save_mode = None
        kind = (
            ExportKind.GCODE_LAYERS
            if str(pending_mode).strip().lower() == "layers"
            else ExportKind.GCODE
        )
        self._export_jobs.submit(
            kind=kind,
            snapshot=snapshot,
            output_path=self._gcode_output_path,
        )
        if kind is ExportKind.GCODE_LAYERS:
            print(f"Exporting G-code per layer: {self._gcode_output_path.parent}")
        else:
            print(f"Exporting G-code: {self._gcode_output_path}")

    def start_video_recording(self) -> None:
        """動画録画を開始する。"""

        fb_w, fb_h = self._framebuffer_size()
        self._recording.start(framebuffer_size=(int(fb_w), int(fb_h)), t0=self._clock.t())

    def stop_video_recording(self) -> None:
        """動画録画を終了する。"""

        self._recording.stop()

    def _framebuffer_size(self) -> tuple[int, int]:
        """現在の framebuffer の実ピクセル寸法を返す。

        環境によっては（HiDPI など）`window.width/height` と framebuffer 実寸が一致しないため、
        可能なら pyglet の `get_framebuffer_size()` を使う。
        """

        getter = getattr(self.window, "get_framebuffer_size", None)
        if callable(getter):
            get_framebuffer_size = cast(Callable[[], tuple[int, int]], getter)
            w, h = get_framebuffer_size()
            return int(w), int(h)
        return int(self.window.width), int(self.window.height)

    def draw_frame(self) -> None:
        """1 フレーム分の描画を行う（`flip()` は呼ばない）。"""

        perf = self._perf
        with perf.frame():
            # --- 0) フレーム冒頭での軽い housekeeping ---
            # 非同期 PNG/G-code export の通知回収だけを行う。重い backend は worker 内で走る。
            self._poll_export_results()

            midi = self._midi_controller
            if midi is not None:
                midi.poll_pending()
                cc_snapshot = midi.snapshot()
            else:
                cc_snapshot = self._frozen_cc_snapshot

            # 注: 呼び出し側（pyglet.window.Window.draw）が事前に self.window.switch_to() 済みである前提。
            # その前提が崩れると、別 window のコンテキストへ描いてしまう可能性がある。
            #
            # さらに、録画の read などで framebuffer binding が揺れるケースに備え、
            # 毎フレーム「screen」を明示的に bind してから描画を始める。
            self._renderer.ctx.screen.use()

            # --- 1) ビューポート更新 ---
            #
            # ウィンドウの論理解像度（width/height）はフレームごとに参照し、
            # 現在のサイズに合わせて OpenGL の viewport を更新する。
            # （resizable=False でも、内部事情や将来の変更に備えて毎フレーム更新している）
            fb_w, fb_h = self._framebuffer_size()
            self._renderer.viewport(fb_w, fb_h)

            # --- 2) Style（背景色 / グローバル線幅 / グローバル線色）の確定 ---
            style = self._style.resolve()

            # --- 3) 背景クリア ---
            #
            # まず背景色でクリアしてから、このフレームのシーンを描く。
            self._renderer.clear(style.bg_color_rgb01)

            # --- 4) 時刻 t の算出 ---
            #
            # draw(t) は “開始時刻からの経過秒” を受け取る。
            # これを使ってユーザー側でアニメーション等を表現できる。
            recording = self._recording.is_recording
            t = self._recording.t() if recording else self._clock.t()

            # --- 5) Geometry の param 解決 + 描画 ---
            #
            effective_defaults = LayerStyleDefaults(
                color=style.global_line_color_rgb01,
                thickness=style.global_thickness,
            )
            realized_layers = self._scene_runner.run(
                t,
                store=self._store,
                cc_snapshot=cc_snapshot,
                defaults=effective_defaults,
                recording=recording,
            )
            self._last_realized_layers = realized_layers
            frame_vertices = 0
            frame_lines = 0
            for item in realized_layers:
                with perf.section("render_layer"):
                    stats = self._renderer.render_layer(
                        realized=item.realized,
                        cache_key=item.cache_key,
                        color=item.color,
                        thickness=item.thickness,
                    )
                frame_vertices += int(stats.draw_vertices)
                frame_lines += int(stats.draw_lines)

            monitor = self._monitor
            if monitor is not None:
                monitor.set_draw_counts(vertices=int(frame_vertices), lines=int(frame_lines))

            if recording:
                with perf.section("video"):
                    # GPU からの readback が入るため、perf では明示セクションに分ける。
                    self._recording.write_frame(self._renderer.ctx.screen)

            if self._pending_png_save or self._pending_gcode_save_mode is not None:
                snapshot = FrameExportSnapshot(
                    layers=tuple(realized_layers),
                    canvas_size=self._settings.canvas_size,
                    background_color_rgb01=style.bg_color_rgb01,
                )
                self._submit_pending_exports(snapshot)

            if perf.enabled and perf.gpu_finish:
                with perf.section("gpu_finish"):
                    self._renderer.finish()

    def close(self) -> None:
        """GPU / window 資源を解放する。"""

        # --- PNG/G-code export ---
        self._poll_export_results()
        self._export_jobs.close()
        self._poll_export_results()

        # --- 録画 ---
        if self._recording.is_recording:
            try:
                self.stop_video_recording()
            except Exception:
                _logger.exception("Failed to stop video recording")

        # --- MIDI ---
        # MIDI controller はこのサブシステムが所有しているので、保存と close まで面倒を見る。
        midi = self._midi_controller
        self._midi_controller = None
        if midi is not None:
            try:
                midi.save()
            except Exception:
                _logger.exception("Failed to save MIDI CC snapshot: %s", midi.path)
            finally:
                midi.close()

        # --- mp-draw worker / scene 実行器 ---
        self._scene_runner.close()

        # renderer が保持している GPU リソースを破棄してから window を閉じる。
        self._renderer.release()
        self.window.close()
