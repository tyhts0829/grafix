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

from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
import logging
from math import isfinite
import shutil
import tempfile
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TypeAlias, cast

from pyglet.window import key

from grafix.api.render import (
    Frame,
    ParameterLoadMode,
    RenderOptions,
    RenderSessionMetadata,
)
from grafix.core.parameters import ParamStore
from grafix.core.layer import LayerStyleDefaults
from grafix.core.pipeline import RealizedLayer
from grafix.core.capture_provenance import (
    CaptureProvenance,
    CaptureProvenanceBuilder,
)
from grafix.core.capture_manifest import (
    CaptureManifest,
    capture_manifest_path_for,
    publish_capture_generation,
)
from grafix.core.output_paths import (
    VersionedPathAllocator,
    output_path_for_draw,
)
from grafix.core.runtime_config import GCodeExportConfig, RuntimeConfig, runtime_config
from grafix.export.capture import CaptureMode, CaptureService
from grafix.export.image import default_png_output_path, png_output_size
from grafix.interactive.draw_window import (
    MINIMUM_DRAW_WINDOW_HEIGHT,
    MINIMUM_DRAW_WINDOW_WIDTH,
    create_draw_window,
)
from grafix.interactive.gl.draw_renderer import DrawRenderer
from grafix.interactive.render_settings import RenderSettings
from grafix.core.scene import SceneItem
from grafix.core.resource_budget import DEFAULT_RESOURCE_BUDGET, ResourceBudget
from grafix.core.runtime_limits import (
    DEFAULT_RUNTIME_LIMIT_PROFILES,
    RuntimeLimitProfiles,
    profiles_for_resource_budget,
)
from grafix.interactive.runtime.perf import PerfCollector
from grafix.interactive.midi import MidiSession
from grafix.interactive.runtime.frame_clock import RealTimeClock, TransportClock
from grafix.interactive.runtime.diagnostics import (
    DiagnosticAction,
    DiagnosticEvent,
    DiagnosticSeverity,
)
from grafix.interactive.runtime.export_job_system import (
    ExportJobStatus,
    ExportJobSystem,
    ExportQueueFullError,
    ExportKind,
    FrameExportSnapshot,
)
from grafix.interactive.runtime.recording_system import VideoRecordingSystem
from grafix.interactive.runtime.scene_runner import SceneRunner
from grafix.core.parameters.style_resolver import StyleResolver
from grafix.core.parameters.source import MidiFrameSnapshot
from grafix.core.preview_quality import PreviewQuality
from grafix.interactive.runtime.video_recorder import default_video_output_path

_logger = logging.getLogger(__name__)
_MAX_PRE_FRAME_CAPTURE_REQUESTS = 17
_MAX_CAPTURE_PUBLISH_RETRIES = 8
_CAPTURE_SHUTDOWN_TIMEOUT_S = 30.0
_EXPORT_SHUTDOWN_POLL_S = 0.01
# pyglet には「maximum constraint 未設定」へ戻す共通 API が無いため、
# 実用上到達しない十分大きな値を上限解除として使う。
_RESTORED_DRAW_WINDOW_MAX_SIZE = 1_000_000

if TYPE_CHECKING:
    from grafix.interactive.runtime.monitor import RuntimeMonitor
    from grafix.interactive.runtime.source_reload import SourceReloadController


class _SynchronousCaptureKind(Enum):
    """UI thread で完了する capture の内部識別子。"""

    SVG = "svg"


_CaptureKind: TypeAlias = ExportKind | _SynchronousCaptureKind


@dataclass(slots=True)
class _PendingExportRequest:
    """key press と、その時点で表示していた immutable frame を結び付ける。"""

    kind: _CaptureKind
    snapshot: FrameExportSnapshot | None = None


@dataclass(slots=True)
class _RecordingCaptureState:
    """recording artifact と開始 frame provenance を同じ寿命で保持する。"""

    path: Path
    t0: float
    framebuffer_size: tuple[int, int]
    provenance: CaptureProvenance | None = None


@dataclass(frozen=True, slots=True)
class _FrameProvenanceToken:
    """preview frame と provenance の生成条件を O(1) で結び付ける。"""

    builder: CaptureProvenanceBuilder
    store: ParamStore
    frame_index: int
    quality: PreviewQuality
    store_revision: int
    effective_revision: int


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
      - `Space` / `Home` / `Left` / `Right`: 再生、一時停止、reset、frame step
      - `[` / `]`: 再生速度の変更
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
        midi_session: MidiSession | None = None,
        monitor: RuntimeMonitor | None = None,
        fps: float = 60.0,
        n_worker: int = 0,
        evaluation_timeout: float | None = 5.0,
        run_id: str | None = None,
        resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
        runtime_limit_profiles: RuntimeLimitProfiles | None = None,
        source_reload: SourceReloadController | None = None,
        effective_config: RuntimeConfig | None = None,
        parameter_source: ParameterLoadMode = "code",
        parameter_store_path: Path | None = None,
        seed: int | None = None,
    ) -> None:
        """描画用の window/renderer と各種状態を初期化する。

        初期化で行うこと
        --------------
        - pyglet window 作成 + `DrawRenderer` の初期化（GL コンテキストに紐づく）
        - export 先パスの決定（SVG/G-code/PNG/動画）
        - 録画・PNG/G-code export subsystem の用意
        - `draw(t)` に渡す `t` の基準となる clock の開始
        """

        profiles = (
            profiles_for_resource_budget(resource_budget)
            if runtime_limit_profiles is None
            else runtime_limit_profiles
        )
        if not isinstance(profiles, RuntimeLimitProfiles):
            raise TypeError(
                "runtime_limit_profiles は RuntimeLimitProfiles である必要があります"
            )

        # 設定/既定スタイル/draw 関数/ParamStore は 1 フレームごとに参照するため保持しておく。
        self._settings = settings
        self._store = store
        self._midi_session = midi_session
        self._monitor = monitor
        self._source_reload = source_reload
        self._runtime_limit_profiles = profiles
        self._capture_request_limit = (
            int(profiles.final.capture_queue_pending_jobs) + 1
        )
        self._fps = float(fps)
        self._effective_config = (
            runtime_config() if effective_config is None else effective_config
        )
        if not isinstance(self._effective_config, RuntimeConfig):
            raise TypeError("effective_config は RuntimeConfig である必要があります")
        self._parameter_source = parameter_source
        self._parameter_store_path = (
            None if parameter_store_path is None else Path(parameter_store_path)
        )
        self._seed = seed
        self._provenance_builder = CaptureProvenanceBuilder(
            draw,
            config=self._effective_config,
            parameter_source=self._parameter_source,
            parameter_store_path=self._parameter_store_path,
            parameter_load_provenance=store.load_provenance,
            seed=seed,
        )
        self._provenance_frame_index = 0
        self._render_options = RenderOptions(
            canvas_size=settings.canvas_size,
            background_color=settings.background_color,
            line_color=settings.line_color,
            line_thickness=settings.line_thickness,
        )

        self._style = StyleResolver(
            self._store,
            base_background_color_rgb01=settings.background_color,
            base_global_thickness=float(defaults.thickness),
            base_global_line_color_rgb01=defaults.color,
        )

        self._closed = False
        window = None
        renderer = None
        export_jobs = None
        scene_runner = None
        try:
            # 描画用の pyglet window と、その OpenGL context に紐づく renderer。
            window = create_draw_window(settings)
            self.window = window
            diagnostic_center = (
                None if monitor is None else monitor.diagnostic_center
            )
            renderer = DrawRenderer(
                window,
                settings,
                runtime_limits=profiles.preview,
                diagnostic_center=diagnostic_center,
            )
            self._renderer = renderer

            self._svg_output_path = output_path_for_draw(
                kind="svg",
                ext="svg",
                draw=draw,
                run_id=run_id,
                canvas_size=settings.canvas_size,
            )
            self._gcode_output_path = output_path_for_draw(
                kind="gcode",
                ext="gcode",
                draw=draw,
                run_id=run_id,
                canvas_size=settings.canvas_size,
            )
            self._png_output_path = default_png_output_path(
                draw, run_id=run_id, canvas_size=settings.canvas_size
            )
            video_output_path = default_video_output_path(
                draw, run_id=run_id, ext="mp4"
            )
            self._recording = VideoRecordingSystem(
                output_path=video_output_path,
                fps=float(fps),
            )
            self._video_output_path = video_output_path
            self._capture_paths = VersionedPathAllocator()
            self._capture_service = CaptureService(path_allocator=self._capture_paths)
            self._pending_capture_by_job: dict[int, tuple[float, str]] = {}
            self._recording_capture: _RecordingCaptureState | None = None
            self._preview_was_playing_before_recording: bool | None = None
            self._recording_window_constraints_locked = False
            self._last_realized_layers: list[RealizedLayer] = []
            self._last_frame_t = 0.0
            self._fresh_scene_serial = 0
            self._presented_snapshot_revision: int | None = None
            self._last_export_snapshot: FrameExportSnapshot | None = None
            self._last_export_provenance_token: _FrameProvenanceToken | None = None
            self._last_frame_error: str | None = None
            self._last_capture_queue_notice: str | None = None
            # 初回frame前intent以外は直接 ExportJobSystem の bounded admissionへ渡す。
            self._pending_export_requests: deque[_PendingExportRequest] = deque()
            export_jobs = ExportJobSystem(
                runtime_limits=profiles.final,
            )
            self._export_jobs = export_jobs
            window.push_handlers(on_key_press=self._on_key_press)

            # draw(t) に渡す t の基準時刻。
            start_time = time.perf_counter()
            self._clock = RealTimeClock(start_time=start_time)
            self._perf = PerfCollector.from_env(
                enabled_by_default=monitor is not None,
                snapshot_callback=(
                    None if monitor is None else monitor.set_profiler
                ),
            )
            scene_runner = SceneRunner(
                draw,
                perf=self._perf,
                n_worker=int(n_worker),
                evaluation_timeout=evaluation_timeout,
                resource_budget=resource_budget,
                runtime_limit_profiles=profiles,
                diagnostic_center=(
                    None if monitor is None else monitor.diagnostic_center
                ),
            )
            self._scene_runner = scene_runner
            if source_reload is not None and diagnostic_center is not None:
                diagnostic_center.register_action(
                    "retry",
                    self._retry_source_reload,
                    category="reload",
                )
        except BaseException:
            # constructor が return しない場合、runner は部分構築 object を close
            # できない。ここで取得済み resource を全て逆順に試す。MIDI ownership は
            # 正常構築後にだけ移るため、失敗時は caller が close する。
            cleanup_steps: list[tuple[str, Callable[[], object]]] = []
            if scene_runner is not None:
                cleanup_steps.append(("scene runner", scene_runner.close))
            if export_jobs is not None:
                cleanup_steps.append(("export jobs", export_jobs.close))
            if window is not None:
                switch_to = getattr(window, "switch_to", None)
                if callable(switch_to):
                    cleanup_steps.append(("draw GL context", switch_to))
            if renderer is not None:
                cleanup_steps.append(("renderer", renderer.release))
            if window is not None:
                cleanup_steps.append(("draw window", window.close))
            for label, cleanup in cleanup_steps:
                try:
                    cleanup()
                except BaseException:
                    _logger.exception(
                        "DrawWindowSystem initialization cleanup failed: %s",
                        label,
                    )
            raise

    def _on_key_press(self, symbol: int, modifiers: int) -> None:
        """キーボードショートカットのハンドラ。

        重い処理（PNG/G-code の書き出し）は、イベントコールバック内で実行せず
        フラグを立てて `draw_frame()` 側で処理する（イベント処理を詰まらせないため）。
        """

        if symbol == key.S:
            # 初回 draw 前だけは空 scene を即保存せず、PNG/G-code と同じ bounded
            # intent queue で最初に実際に表示できた frame を待つ。初回 draw 後は
            # keypress 時点の snapshot を使い、この UI thread 内で同期保存する。
            self._queue_export_request(_SynchronousCaptureKind.SVG)
            return
        if symbol == key.P:
            self._queue_export_request(ExportKind.PNG)
            return
        if symbol == key.G:
            # `G`: 全レイヤ一括
            # `Shift+G`: レイヤごとに分割して保存
            self._queue_export_request(
                ExportKind.GCODE_LAYERS
                if (int(modifiers) & int(key.MOD_SHIFT))
                else ExportKind.GCODE
            )
            return
        if symbol == key.V:
            if not self._recording.is_recording:
                self.start_video_recording()
            else:
                self.stop_video_recording()
            return
        if self._recording.is_recording:
            # 録画 timeline は fixed-fps で確定するため、途中の preview 操作は受け付けない。
            return
        if symbol == key.SPACE:
            self._clock.toggle()
            return
        if symbol == key.HOME:
            self._clock.reset()
            return
        if symbol == key.LEFT:
            self._clock.step_frame(fps=self._transport_step_fps(), frames=-1)
            return
        if symbol == key.RIGHT:
            self._clock.step_frame(fps=self._transport_step_fps(), frames=1)
            return
        if symbol == key.BRACKETLEFT:
            self._clock.set_speed(max(0.125, self._clock.speed / 2.0))
            return
        if symbol == key.BRACKETRIGHT:
            self._clock.set_speed(min(8.0, self._clock.speed * 2.0))

    def _transport_step_fps(self) -> float:
        """1 frame step に使う fps を返す。無制限実行時は 60 fps とする。"""

        return self._fps if self._fps > 0.0 else 60.0

    def _queue_export_request(self, kind: _CaptureKind) -> bool:
        """keypress 時点の表示 snapshot を一つの bounded queue 契約へ投入する。"""

        snapshot = getattr(self, "_last_export_snapshot", None)
        if snapshot is not None and hasattr(self, "_scene_runner"):
            # previewはdraftでも、artifactは同じt/parameterをfinal品質で再評価する。
            try:
                snapshot = self._final_capture_snapshot()
            except Exception as exc:
                self._publish_export_diagnostic(
                    summary=f"Final capture evaluation failed: {self._export_label(kind)}",
                    details="".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    ),
                    severity="error",
                )
                return False
        request = _PendingExportRequest(kind=kind, snapshot=snapshot)
        if snapshot is not None:
            # 初回 draw 後は UI 側に第2 queueを作らず、ExportJobSystem の件数/byte
            # budgetへ直接 admission する。重い export 本体は引き続き worker 内で走る。
            return self._submit_export_request(request)

        # 初回 draw より前だけは geometry が存在せず byte 見積もりができないため、
        # 最初の表示 frame へ結合する小さな intent queue を許す。
        request_limit = int(
            getattr(
                self,
                "_capture_request_limit",
                _MAX_PRE_FRAME_CAPTURE_REQUESTS,
            )
        )
        if len(self._pending_export_requests) >= request_limit:
            label = self._export_label(kind)
            notice = (
                f"Capture rejected: {label}; before-first-frame requests="
                f"{len(self._pending_export_requests)}/{request_limit}"
            )
            self._last_capture_queue_notice = notice
            print(notice)
            self._publish_export_diagnostic(
                summary=notice,
                details=notice,
                severity="warning",
            )
            self._update_capture_queue_monitor()
            return False
        self._pending_export_requests.append(request)
        self._update_capture_queue_monitor()
        return True

    @property
    def transport(self) -> TransportClock:
        """Parameter GUI と共有する preview transport を返す。"""

        return self._clock

    @property
    def is_recording(self) -> bool:
        """動画録画中なら True を返す。"""

        return bool(self._recording.is_recording)

    @property
    def capture_service(self) -> CaptureService:
        """Inspector callback と keyboard capture が共有する service を返す。"""

        return self._capture_service

    def _new_provenance_builder(
        self,
        draw: Callable[[float], SceneItem],
    ) -> CaptureProvenanceBuilder:
        """同じ interactive session 設定で新しい source 世代を固定する。"""

        return CaptureProvenanceBuilder(
            draw,
            config=self._effective_config,
            parameter_source=self._parameter_source,
            parameter_store_path=self._parameter_store_path,
            parameter_load_provenance=self._store.load_provenance,
            seed=self._seed,
        )

    def _frame_provenance(
        self,
        *,
        t: float,
        quality: PreviewQuality,
    ) -> CaptureProvenance | None:
        """main process の確定 store を 1 frame の provenance へ固定する。"""

        token = self._new_frame_provenance_token(quality=quality)
        if token is None:
            return None
        provenance = self._materialize_frame_provenance(token, t=t)
        if provenance is None:
            raise RuntimeError("provenance token no longer matches the parameter store")
        self._commit_frame_provenance_token(token)
        return provenance

    def _new_frame_provenance_token(
        self,
        *,
        quality: PreviewQuality,
        snapshot_revision: int | None = None,
    ) -> _FrameProvenanceToken | None:
        """fresh frame の provenance 条件を hash 未生成のまま固定する。"""

        builder = getattr(self, "_provenance_builder", None)
        if builder is None:
            # constructor を経由しない小さい runtime test double では provenance
            # source が存在しない。production instance は必ず builder を持つ。
            return None
        store = self._store
        runtime = store._runtime_ref()
        frame_index = int(getattr(self, "_provenance_frame_index", 0))
        return _FrameProvenanceToken(
            builder=builder,
            store=store,
            frame_index=frame_index,
            quality=quality,
            store_revision=(
                int(store.revision)
                if snapshot_revision is None
                else int(snapshot_revision)
            ),
            effective_revision=int(runtime.effective_revision),
        )

    def _materialize_frame_provenance(
        self,
        token: _FrameProvenanceToken,
        *,
        t: float,
    ) -> CaptureProvenance | None:
        """token と同じ parameter 世代なら完全な provenance を生成する。"""

        if not self._frame_provenance_token_is_current(token):
            return None
        store = token.store
        return token.builder.frame(
            store,
            t=float(t),
            frame_index=token.frame_index,
            quality=token.quality,
            origin="interactive",
        )

    def _frame_provenance_token_is_current(
        self,
        token: _FrameProvenanceToken,
    ) -> bool:
        """token の parameter 世代がまだ保持されているか返す。"""

        store = token.store
        if store is not self._store:
            return False
        runtime = store._runtime_ref()
        return (
            int(store.revision) == token.store_revision
            and int(runtime.effective_revision) == token.effective_revision
        )

    def _commit_frame_provenance_token(self, token: _FrameProvenanceToken) -> None:
        """fresh frame として確定した token の次へ frame index を進める。"""

        self._provenance_frame_index = max(
            int(getattr(self, "_provenance_frame_index", 0)),
            token.frame_index + 1,
        )

    def _snapshot_with_provenance(
        self,
        snapshot: FrameExportSnapshot,
        *,
        quality: PreviewQuality,
        token: _FrameProvenanceToken | None = None,
    ) -> FrameExportSnapshot:
        """capture 境界でだけ snapshot の provenance を具体化する。"""

        if snapshot.provenance is not None:
            return snapshot
        provenance = (
            self._frame_provenance(t=snapshot.t, quality=quality)
            if token is None
            else self._materialize_frame_provenance(token, t=snapshot.t)
        )
        if token is not None and provenance is None:
            raise RuntimeError(
                "preview snapshot parameters changed before provenance materialization"
            )
        if provenance is None:
            return snapshot
        return replace(snapshot, provenance=provenance)

    def _token_for_snapshot(
        self,
        snapshot: FrameExportSnapshot,
    ) -> _FrameProvenanceToken | None:
        """最新 preview snapshot に対応する token だけを返す。"""

        if snapshot is not getattr(self, "_last_export_snapshot", None):
            return None
        return getattr(self, "_last_export_provenance_token", None)

    def _capture_gcode_config(self) -> GCodeExportConfig | None:
        """production session の effective G-code 設定を worker payload 用に返す。"""

        config = getattr(self, "_effective_config", None)
        return config.gcode if isinstance(config, RuntimeConfig) else None

    def _capture_png_output_size(
        self,
        canvas_size: tuple[int, int],
    ) -> tuple[int, int]:
        """production session の effective PNG scale で出力寸法を固定する。"""

        config = getattr(self, "_effective_config", None)
        scale = config.png_scale if isinstance(config, RuntimeConfig) else None
        return png_output_size(canvas_size, scale=scale)

    def save_svg(self, *, snapshot: FrameExportSnapshot | None = None) -> Path:
        """最後に描画したフレームを SVG として保存し、保存先パスを返す。

        ``snapshot`` は初回 draw 前に受け付けた S intent を、最初に表示した frame
        へ固定して保存する内部用途である。引数なしの既存 API は従来どおり最後の
        表示 snapshot（まだ無ければ現在の空/last-good scene）を保存する。
        """

        visible = (
            snapshot
            if snapshot is not None
            else getattr(self, "_last_export_snapshot", None)
        )
        provenance_token = (
            None if visible is None else self._token_for_snapshot(visible)
        )
        if visible is None:
            visible = FrameExportSnapshot(
                layers=tuple(self._last_realized_layers),
                canvas_size=self._settings.canvas_size,
                background_color_rgb01=self._style.resolve().bg_color_rgb01,
                t=float(self._last_frame_t),
                gcode_config=self._capture_gcode_config(),
            )
        if visible.provenance is None:
            if (
                provenance_token is not None
                and not self._frame_provenance_token_is_current(provenance_token)
                and snapshot is None
                and hasattr(self, "_scene_runner")
            ):
                # preview 後に parameter が変わった場合、古い geometry と現在値を
                # 誤って結び付けず、明示 capture と同じ final 再評価へ寄せる。
                visible = self._final_capture_snapshot()
            else:
                visible = self._snapshot_with_provenance(
                    visible,
                    quality="final",
                    token=provenance_token,
                )
        canvas_size = visible.canvas_size

        # SVG writer に正式 path を渡すと late collision を os.replace 等で上書きし得る。
        # 一度だけ private sibling へ完成させ、artifact + manifest を共通 transaction で
        # publish する。競合時は同じ staged SVG を次 version へ再利用する。
        self._svg_output_path.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{self._svg_output_path.stem}.capture-",
                dir=self._svg_output_path.parent,
            )
        )
        staged_path = staging_dir / self._svg_output_path.name
        try:
            staged_paths = self._capture_service.encode(
                visible,
                staged_path,
                mode=CaptureMode.SVG,
            )
            last_collision: FileExistsError | None = None
            for _attempt in range(_MAX_CAPTURE_PUBLISH_RETRIES):
                path = self._allocate_capture_path(self._svg_output_path)
                try:
                    published = self._capture_service.publish_staged(
                        visible,
                        path,
                        staged_paths,
                        mode=CaptureMode.SVG,
                        output_size=canvas_size,
                    )
                except FileExistsError as exc:
                    # allocation 後の late collision は外部 file を保持し、次 versionへ。
                    last_collision = exc
                    continue
                assert published is not None
                return published.artifact_paths[0]
            raise FileExistsError(
                "SVG capture publish が late collision の再試行上限に達しました: "
                f"retries={_MAX_CAPTURE_PUBLISH_RETRIES}"
            ) from last_collision
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _allocate_capture_path(self, base_path: Path) -> Path:
        """成果物と既存 manifest のどちらも上書きしない path を予約する。"""

        while True:
            candidate = self._capture_paths.allocate(base_path)
            manifest_path = capture_manifest_path_for(candidate)
            if not manifest_path.exists() and not manifest_path.is_symlink():
                return candidate

    def _allocate_gcode_layers_path(self, snapshot: FrameExportSnapshot) -> Path:
        """既存の layer 別成果物とも衝突しない G-code base path を予約する。"""

        while True:
            candidate = self._allocate_capture_path(self._gcode_output_path)
            # 現 snapshot の layer 数/名前だけを検査すると、失敗した旧 capture の
            # `_layer002_old-name.gcode` などを見落とし、同じ version family へ新旧を
            # 混在させ得る。stem + `_layer<digits>` に属する全 entry（broken symlink や
            # 想定外の追加 layer も含む）を occupation として扱う。
            family_prefix = f"{candidate.stem}_layer"

            def belongs_to_candidate_family(path: Path) -> bool:
                path_stem = path.stem.casefold()
                prefix = family_prefix.casefold()
                if (
                    path.suffix.casefold() != candidate.suffix.casefold()
                    or not path_stem.startswith(prefix)
                ):
                    return False
                remainder = path_stem[len(prefix) :]
                return bool(remainder) and remainder[0].isdigit()

            parent = candidate.parent
            family_is_occupied = parent.exists() and any(
                belongs_to_candidate_family(path) for path in parent.iterdir()
            )
            if not family_is_occupied:
                return candidate

    @staticmethod
    def _export_label(kind: _CaptureKind) -> str:
        if kind is _SynchronousCaptureKind.SVG:
            return "SVG"
        if kind is ExportKind.PNG:
            return "PNG"
        if kind is ExportKind.GCODE_LAYERS:
            return "G-code layers"
        return "G-code"

    def _update_capture_queue_monitor(self) -> None:
        """ExportJobSystem と初回 frame intent の合算状態を GUI へ渡す。"""

        monitor = getattr(self, "_monitor", None)
        setter = getattr(monitor, "set_capture_queue", None)
        if not callable(setter):
            return
        export_jobs = self._export_jobs
        status = getattr(export_jobs, "queue_status", None)
        if status is None:
            request_count = len(self._pending_export_requests)
            request_limit = int(
                getattr(
                    self,
                    "_capture_request_limit",
                    _MAX_PRE_FRAME_CAPTURE_REQUESTS,
                )
            )
            retained_bytes = 0
            byte_limit = 0
        else:
            request_count = int(status.request_count) + len(
                self._pending_export_requests
            )
            request_limit = int(status.request_limit)
            retained_bytes = int(status.retained_bytes)
            byte_limit = int(status.byte_limit)
        setter(
            request_count=request_count,
            request_limit=request_limit,
            retained_bytes=retained_bytes,
            byte_limit=byte_limit,
            notice=getattr(self, "_last_capture_queue_notice", None),
        )

    def _report_capture_rejection(
        self,
        kind: _CaptureKind,
        error: ExportQueueFullError | None = None,
    ) -> None:
        """拒否を黙って置換せず、console と GUI の双方へ同じ理由を出す。"""

        detail = (
            str(error)
            if error is not None
            else "capture queue rejected: no admission slot available"
        )
        notice = f"Capture rejected: {self._export_label(kind)}; {detail}"
        self._last_capture_queue_notice = notice
        print(notice)
        self._publish_export_diagnostic(
            summary=notice,
            details=detail,
            severity="warning",
        )
        self._update_capture_queue_monitor()

    def _publish_export_diagnostic(
        self,
        *,
        summary: str,
        details: str,
        severity: DiagnosticSeverity,
        source: str | Path | None = None,
    ) -> None:
        """capture/export failureを共通DiagnosticCenterへpublishする。"""

        monitor = getattr(self, "_monitor", None)
        if monitor is None:
            return
        monitor.publish_diagnostic(
            DiagnosticEvent(
                category="export",
                severity=severity,
                summary=summary,
                details=details,
                source=None if source is None else str(source),
                actions=(DiagnosticAction("copy", "Copy details"),),
                dedupe_key=f"export:{summary}:{source}",
            )
        )

    def _poll_export_results(self) -> None:
        """export worker の終端結果を回収して表示する。"""

        for result in self._export_jobs.poll():
            self._pending_capture_by_job.pop(result.job_id, None)
            label = self._export_label(result.kind)
            if result.status is ExportJobStatus.SUCCESS:
                if result.kind is ExportKind.GCODE_LAYERS and not result.paths:
                    print("No layers to export")
                for path in result.paths:
                    print(f"Saved {label}: {path}")
                continue
            if result.status is ExportJobStatus.CANCELLED:
                print(f"Cancelled {label}: {result.output_path}")
                self._publish_export_diagnostic(
                    summary=f"Cancelled {label} export",
                    details=f"output_path={result.output_path}",
                    severity="info",
                    source=result.output_path,
                )
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
            self._publish_export_diagnostic(
                summary=f"Failed to save {label} ({result.status.value})",
                details=result.error or "export worker returned no error details",
                severity="error",
                source=result.output_path,
            )
        self._update_capture_queue_monitor()

    def _submit_export_request(self, request: _PendingExportRequest) -> bool:
        """1 request を唯一の count/byte admission 契約へ投入する。"""

        captured_snapshot = request.snapshot
        assert captured_snapshot is not None
        if captured_snapshot.provenance is None:
            captured_snapshot = self._snapshot_with_provenance(
                captured_snapshot,
                quality="final",
                token=self._token_for_snapshot(captured_snapshot),
            )
            request.snapshot = captured_snapshot

        if request.kind is _SynchronousCaptureKind.SVG:
            try:
                path = self.save_svg(snapshot=captured_snapshot)
            except Exception as exc:
                self._publish_export_diagnostic(
                    summary="Failed to save SVG",
                    details="".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    ),
                    severity="error",
                    source=getattr(self, "_svg_output_path", None),
                )
                return False
            self._last_capture_queue_notice = None
            self._update_capture_queue_monitor()
            print(f"Saved SVG: {path}")
            return True

        kind = cast(ExportKind, request.kind)

        ensure_can_submit = getattr(self._export_jobs, "ensure_can_submit", None)
        if callable(ensure_can_submit):
            try:
                ensure_can_submit(captured_snapshot)
            except ExportQueueFullError as exc:
                self._report_capture_rejection(kind, exc)
                return False
        elif not bool(getattr(self._export_jobs, "can_submit", True)):
            self._report_capture_rejection(kind)
            return False

        output_path = (
            self._allocate_gcode_layers_path(captured_snapshot)
            if kind is ExportKind.GCODE_LAYERS
            else self._allocate_capture_path(
                self._png_output_path
                if kind is ExportKind.PNG
                else self._gcode_output_path
            )
        )
        try:
            if kind is ExportKind.PNG:
                job = self._export_jobs.submit(
                    kind=kind,
                    snapshot=captured_snapshot,
                    output_path=output_path,
                    output_size=self._capture_png_output_size(
                        captured_snapshot.canvas_size
                    ),
                )
            else:
                job = self._export_jobs.submit(
                    kind=kind,
                    snapshot=captured_snapshot,
                    output_path=output_path,
                )
        except ExportQueueFullError as exc:
            # preflight と submit は同じ UI thread だが custom implementation にも
            # 明示的な最終 admission を要求する。予約済 version の欠番は安全側の代償。
            self._report_capture_rejection(kind, exc)
            return False
        except Exception as exc:
            self._publish_export_diagnostic(
                summary=f"Failed to start {self._export_label(kind)} export",
                details="".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
                severity="error",
                source=output_path,
            )
            return False

        self._pending_capture_by_job[job.job_id] = (
            float(captured_snapshot.t),
            kind.value,
        )
        self._last_capture_queue_notice = None
        self._update_capture_queue_monitor()
        if kind is ExportKind.PNG:
            print(f"Exporting PNG: {output_path}")
        elif kind is ExportKind.GCODE_LAYERS:
            print(f"Exporting G-code per layer: {output_path.parent}")
        else:
            print(f"Exporting G-code: {output_path}")
        return True

    def _submit_pending_exports(
        self,
        snapshot: FrameExportSnapshot,
        *,
        provenance_token: _FrameProvenanceToken | None = None,
    ) -> int:
        """初回 draw 前の intent を表示 snapshot へ固定して順に admission する。"""

        if (
            snapshot.provenance is None
            and any(request.snapshot is None for request in self._pending_export_requests)
        ):
            snapshot = self._snapshot_with_provenance(
                snapshot,
                quality="final",
                token=provenance_token,
            )
        # request はこの時点で必ず snapshot を持ち、待機中に後続 frame へ差し替えない。
        for request in self._pending_export_requests:
            if request.snapshot is None:
                request.snapshot = snapshot

        accepted = 0
        while self._pending_export_requests:
            request = self._pending_export_requests.popleft()
            accepted += int(self._submit_export_request(request))
        self._update_capture_queue_monitor()
        return accepted

    def start_video_recording(self) -> None:
        """動画録画を開始する。"""

        if self._recording.is_recording:
            return
        was_playing = bool(self._clock.is_playing)
        try:
            self._lock_draw_window_size_for_recording()
            fb_w, fb_h = self._framebuffer_size()
            self._clock.pause()
            t0 = float(self._clock.t())
            path = self._allocate_capture_path(self._video_output_path)
            self._recording.start(
                framebuffer_size=(int(fb_w), int(fb_h)),
                t0=t0,
                output_path=path,
            )
        except BaseException:
            if was_playing:
                try:
                    self._clock.play()
                except BaseException:
                    _logger.exception(
                        "Failed to restore transport after recording start failure"
                    )
            try:
                self._restore_draw_window_resize_constraints()
            except BaseException:
                # encoder/start の根本例外を優先するが、制約は全step復元を試みる。
                _logger.exception(
                    "Failed to restore draw window constraints after recording start failure"
                )
            raise
        # 録画は同期 fixed-fps timeline へ切り替わる不連続境界。
        self._clock.mark_discontinuity()
        self._preview_was_playing_before_recording = was_playing
        self._recording_capture = _RecordingCaptureState(
            path=path,
            t0=t0,
            framebuffer_size=(int(fb_w), int(fb_h)),
        )

    def _lock_draw_window_size_for_recording(self) -> None:
        """録画開始時のlogical sizeでdraw windowを固定する。"""

        window = getattr(self, "window", None)
        set_minimum_size = getattr(window, "set_minimum_size", None)
        set_maximum_size = getattr(window, "set_maximum_size", None)
        if (
            window is None
            or not callable(set_minimum_size)
            or not callable(set_maximum_size)
        ):
            # unit-test double / 旧 backend との互換。実 pyglet Window は両 API を持つ。
            return

        width = max(1, int(window.width))
        height = max(1, int(window.height))
        self._recording_window_constraints_locked = True
        try:
            set_minimum_size(width, height)
            set_maximum_size(width, height)
        except BaseException:
            try:
                self._restore_draw_window_resize_constraints()
            except BaseException:
                _logger.exception(
                    "Failed to restore partially applied recording window constraints"
                )
            raise

    def _restore_draw_window_resize_constraints(self) -> None:
        """録画用の固定サイズ制約を通常preview用へ戻す。"""

        if not bool(getattr(self, "_recording_window_constraints_locked", False)):
            return

        window = getattr(self, "window", None)
        set_minimum_size = getattr(window, "set_minimum_size", None)
        set_maximum_size = getattr(window, "set_maximum_size", None)
        first_error: BaseException | None = None

        # maximum を先に緩めれば、現在サイズと復元minimumの中間状態で
        # platform が不要にwindowをresizeするのを避けられる。
        if callable(set_maximum_size):
            try:
                set_maximum_size(
                    _RESTORED_DRAW_WINDOW_MAX_SIZE,
                    _RESTORED_DRAW_WINDOW_MAX_SIZE,
                )
            except BaseException as exc:
                first_error = exc
        if callable(set_minimum_size):
            try:
                set_minimum_size(
                    MINIMUM_DRAW_WINDOW_WIDTH,
                    MINIMUM_DRAW_WINDOW_HEIGHT,
                )
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            # 次回stop/cleanupで復元を再試行できるようlockedを保つ。
            raise first_error
        self._recording_window_constraints_locked = False

    def stop_video_recording(
        self,
        *,
        timeout_s: float = _CAPTURE_SHUTDOWN_TIMEOUT_S,
        stop_reason: str = "user_stop",
        abort_reason: str | None = None,
    ) -> None:
        """動画録画を終了する。"""

        capture = self._recording_capture
        was_playing = bool(self._preview_was_playing_before_recording)
        end_t = (
            float(self._recording.t())
            if self._recording.is_recording
            else float(self._clock.t())
        )
        staged_capture = None
        stop_error: BaseException | None = None
        try:
            staged_capture = self._recording.stop_to_staging(
                timeout_s=timeout_s,
                stop_reason=stop_reason,
                abort_reason=abort_reason,
            )
        except BaseException as exc:
            stop_error = exc
        finally:
            self._recording_capture = None
            self._preview_was_playing_before_recording = None
            try:
                # seek は録画終了という不連続境界の epoch も進める。
                self._clock.seek(end_t)
                if was_playing:
                    self._clock.play()
            except BaseException as exc:
                if stop_error is None:
                    stop_error = exc
                else:
                    _logger.exception(
                        "Failed to restore transport after recording stop failure"
                    )
            try:
                self._restore_draw_window_resize_constraints()
            except BaseException as exc:
                if stop_error is None:
                    stop_error = exc
                else:
                    _logger.exception(
                        "Failed to restore draw window constraints after recording stop failure"
                    )
        if stop_error is not None:
            raise stop_error
        if staged_capture is None:
            return
        if capture is None:
            staging_path = Path(staged_capture.staging_path)
            raise RuntimeError(
                "録画metadataが失われたため公開できません。完成動画は回収可能です: "
                f"recovery={staging_path}"
            )

        staging_path = Path(staged_capture.staging_path)
        candidate = Path(capture.path)
        published = False
        last_collision: FileExistsError | None = None
        try:
            for _attempt in range(_MAX_CAPTURE_PUBLISH_RETRIES):
                manifest = CaptureManifest(
                    t=float(capture.t0),
                    canvas_size=self._settings.canvas_size,
                    format=candidate.suffix.lstrip(".") or "video",
                    artifact_paths=(candidate,),
                    provenance=capture.provenance,
                    output_size=capture.framebuffer_size,
                    recording=staged_capture.recording,
                )
                try:
                    publish_capture_generation(
                        staged_artifact_paths=(staging_path,),
                        artifact_paths=(candidate,),
                        manifest_path=capture_manifest_path_for(candidate),
                        manifest=manifest,
                    )
                except FileExistsError as exc:
                    # 録画自体は完成済みなので、再 encode せず同じ staging を
                    # 次の version へ publish する。外部 file には触れない。
                    last_collision = exc
                    candidate = self._allocate_capture_path(self._video_output_path)
                    continue
                published = True
                print(f"Saved video: {candidate}")
                return
            raise FileExistsError(
                "Video capture publish が late collision の再試行上限に達しました: "
                f"retries={_MAX_CAPTURE_PUBLISH_RETRIES}, recovery={staging_path}"
            ) from last_collision
        except BaseException:
            # encode 済み動画を失わない。予期しない publish 障害では recovery
            # staging を残し、その path を log/例外から回収できるようにする。
            _logger.exception(
                "Video capture publish failed; completed staging retained: %s",
                staging_path,
            )
            raise
        finally:
            if published:
                try:
                    staging_path.unlink(missing_ok=True)
                except OSError:
                    # generation は既に fsync 済みで公開済み。dot staging の
                    # cleanup failure で成功した capture を失敗扱いにしない。
                    _logger.exception(
                        "Failed to remove published video staging: %s",
                        staging_path,
                    )

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

    @staticmethod
    def _frame_error_summary(exc: Exception, *, max_chars: int = 180) -> str:
        """GUI に出す user-frame error を 1 行へ短縮する。"""

        # RealizeError のような境界 error は、ユーザーが直せる詳細を __cause__ に持つ。
        # 最深の Exception を選び、ResourceLimitError の推奨値などを GUI に残す。
        detail_error = exc
        seen: set[int] = set()
        while isinstance(detail_error.__cause__, Exception):
            if id(detail_error) in seen:
                break
            seen.add(id(detail_error))
            detail_error = detail_error.__cause__

        lines = [
            line.strip() for line in str(detail_error).splitlines() if line.strip()
        ]
        detail = lines[-1] if lines else "(no message)"
        # mp-draw の RuntimeError は末尾に元例外の `ValueError: ...` などを含む。
        # その場合は wrapper 名を重ねず、ユーザーに近い原因を表示する。
        head = detail.partition(":")[0]
        if not head.endswith(("Error", "Exception")):
            detail = f"{type(detail_error).__name__}: {detail}"
        detail = " ".join(detail.split())
        limit = max(16, int(max_chars))
        if len(detail) > limit:
            return f"{detail[: limit - 1]}…"
        return detail

    def _report_frame_error(self, exc: Exception) -> None:
        """scene 評価失敗を通知し、同じ失敗の traceback spam を避ける。"""

        summary = self._frame_error_summary(exc)
        # 同じ失敗が毎 frame 続いても console を埋めない。正常 frame を挟んだ場合は
        # _clear_frame_error() により次回の失敗を改めて記録する。
        if self._last_frame_error != summary:
            _logger.exception(
                "Scene evaluation failed; rendering the last successful frame"
            )
        self._last_frame_error = summary
        monitor = self._monitor
        if monitor is not None:
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            source: str | None = None
            tb = exc.__traceback__
            while tb is not None:
                source = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}"
                tb = tb.tb_next
            monitor.set_frame_error(summary, details=details, source=source)

    def _clear_frame_error(self) -> None:
        """新しい scene 評価が成功したときだけ error 状態を解除する。"""

        if self._last_frame_error is None:
            return
        self._last_frame_error = None
        monitor = self._monitor
        if monitor is not None:
            monitor.set_frame_error(None)

    def _publish_reload_failure(
        self,
        *,
        summary: str,
        details: str,
        source: str | None,
    ) -> None:
        """reload failureを共通診断へ出し、GUI無しならlogへ残す。"""

        monitor = self._monitor
        if monitor is None:
            _logger.error("Sketch reload failed: %s\n%s", summary, details)
            return
        actions: list[DiagnosticAction] = [
            DiagnosticAction("retry", "Retry reload"),
            DiagnosticAction("copy", "Copy details"),
        ]
        if source is not None:
            actions.append(DiagnosticAction("open", "Open source"))
        monitor.publish_diagnostic(
            DiagnosticEvent(
                category="reload",
                severity="error",
                summary=f"Sketch reload failed: {summary}",
                details=details,
                source=source,
                actions=tuple(actions),
                dedupe_key=f"source-reload:{summary}:{source}",
            )
        )

    def _poll_source_reload(self, *, force: bool = False) -> bool:
        """source更新を検査し、registry/draw/workerを同じframe境界で交換する。"""

        controller = getattr(self, "_source_reload", None)
        if controller is None:
            return False
        result = controller.poll(force=force, retain_rollback=True)
        if result.status == "unchanged":
            return False
        if result.status == "failed":
            self._publish_reload_failure(
                summary=result.summary or "unknown reload error",
                details=result.details or result.summary or "unknown reload error",
                source=result.source,
            )
            return False

        replacement_provenance = None
        try:
            if hasattr(self, "_provenance_builder"):
                replacement_provenance = self._new_provenance_builder(result.draw)
            self._scene_runner.replace_draw(result.draw)
        except Exception as exc:
            rollback_details = ""
            try:
                controller.rollback_generation(result.generation)
            except Exception as rollback_error:
                rollback_details = (
                    "\n\nRegistry rollback also failed:\n"
                    + "".join(
                        traceback.format_exception(
                            type(rollback_error),
                            rollback_error,
                            rollback_error.__traceback__,
                        )
                    )
                )
            details = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            self._publish_reload_failure(
                summary=f"{type(exc).__name__}: {exc}",
                details=details + rollback_details,
                source=result.source,
            )
            return False

        controller.accept_generation(result.generation)
        if replacement_provenance is not None:
            self._provenance_builder = replacement_provenance
        monitor = self._monitor
        if monitor is not None:
            monitor.diagnostic_center.clear(category="reload")
        return True

    def _retry_source_reload(self, event: DiagnosticEvent) -> None:
        """DiagnosticCenterのRetry actionから同じsourceを明示再評価する。"""

        if self._poll_source_reload(force=True):
            monitor = self._monitor
            if monitor is not None:
                monitor.diagnostic_center.dismiss(event)

    def _evaluate_scene(
        self,
        t: float,
        *,
        cc_snapshot: MidiFrameSnapshot | None,
        defaults: LayerStyleDefaults,
        recording: bool,
        quality: PreviewQuality = "draft",
    ) -> list[RealizedLayer]:
        """user scene を評価し、失敗時は直近成功 frame を返す。

        例外境界は意図的に `SceneRunner.run()` だけを囲む。GL context 操作や
        `render_layer()`、録画、export の障害はここで user-code error と誤認して
        握りつぶさず、従来どおり呼び出し側へ伝播させる。
        """

        try:
            realized_layers = self._scene_runner.run(
                t,
                store=self._store,
                cc_snapshot=cc_snapshot,
                defaults=defaults,
                recording=recording,
                quality=quality,
                transport_epoch=int(
                    getattr(getattr(self, "_clock", None), "epoch", 0)
                ),
            )
        except Exception as exc:
            self._report_frame_error(exc)
            return self._last_realized_layers

        self._last_realized_layers = realized_layers
        # manifest/export の `t` は、現在の transport 時刻ではなく、
        # この run で実際に realize された出力と結び付ける。
        # mp-draw で success と後続 error が同時に drain された場合は、
        # error 表示を残したまま、次の run が実際に返した success の
        # `t` だけを取り込む。
        realized_t = getattr(self._scene_runner, "last_realized_t", None)
        if realized_t is not None:
            self._last_frame_t = float(realized_t)
        # mp-draw の result 未到着時は前回 scene の再利用で正常 return する。
        # それを user draw の回復とは数えず、新しい成功結果まで表示を残す。
        if self._scene_runner.last_evaluation_succeeded is True:
            # `last_realized_t` を持たない test double/旧実装との互換用 fallback。
            if realized_t is None:
                evaluated_t = getattr(self._scene_runner, "last_evaluation_t", None)
                self._last_frame_t = float(t if evaluated_t is None else evaluated_t)
            self._clear_frame_error()
        return realized_layers

    def _final_capture_snapshot(self) -> FrameExportSnapshot:
        """現在時刻をfinal品質で再評価し、artifact用snapshotを返す。"""

        recording = bool(self._recording.is_recording)
        t = float(self._recording.t()) if recording else float(self._clock.t())
        style = self._style.resolve()
        layers = self._evaluate_scene(
            t,
            cc_snapshot=self._midi_frame_snapshot(),
            defaults=LayerStyleDefaults(
                color=style.global_line_color_rgb01,
                thickness=style.global_thickness,
            ),
            recording=recording,
            quality="final",
        )
        if self._scene_runner.last_evaluation_succeeded is not True:
            raise RuntimeError("Final capture evaluation did not produce a fresh frame")
        return FrameExportSnapshot(
            layers=tuple(layers),
            canvas_size=self._settings.canvas_size,
            background_color_rgb01=style.bg_color_rgb01,
            t=float(self._last_frame_t),
            provenance=self._frame_provenance(
                t=float(self._last_frame_t),
                quality="final",
            ),
            gcode_config=self._capture_gcode_config(),
        )

    def final_capture_frame(self) -> Frame:
        """現在時刻を final 品質で評価し、thumbnail用の immutable Frame を返す。"""

        snapshot = self._final_capture_snapshot()
        provenance = snapshot.provenance
        if provenance is None:
            raise RuntimeError("capture provenance is unavailable")
        style = self._style.resolve()
        metadata = RenderSessionMetadata(
            config_path=self._effective_config.config_path,
            effective_config=self._effective_config,
            parameter_source=self._parameter_source,
            parameter_store_path=self._parameter_store_path,
            parameter_load_provenance=self._store.load_provenance,
            provenance=provenance.session,
        )
        return Frame(
            t=snapshot.t,
            layers=snapshot.layers,
            options=self._render_options,
            style=style,
            metadata=metadata,
            provenance=provenance,
        )

    def _midi_frame_snapshot(self) -> MidiFrameSnapshot | None:
        """現在frameのMIDI値とlive/frozen由来を一つのsnapshotへ固定する。"""

        session = self._midi_session
        return None if session is None else session.frame_snapshot()

    def draw_frame(self) -> None:
        """1 フレーム分の描画を行う（`flip()` は呼ばない）。"""

        perf = self._perf
        with perf.frame():
            # --- 0) フレーム冒頭での軽い housekeeping ---
            # source watchはstatだけを毎frame確認し、変更時だけtransactional loadする。
            # recording generation 内では code provenance を一つに保つため、停止後の
            # 最初の frame 境界まで swap を遅延する。
            if not self._recording.is_recording:
                self._poll_source_reload()
            # 非同期 PNG/G-code export の通知回収だけを行う。重い backend は worker 内で走る。
            self._poll_export_results()

            cc_snapshot = self._midi_frame_snapshot()

            # 注: 呼び出し側（pyglet.window.Window.draw）が事前に self.window.switch_to() 済みである前提。
            # その前提が崩れると、別 window のコンテキストへ描いてしまう可能性がある。
            #
            # さらに、録画の read などで framebuffer binding が揺れるケースに備え、
            # 毎フレーム「screen」を明示的に bind してから描画を始める。
            self._renderer.ctx.screen.use()

            # --- 1) ビューポート更新 ---
            #
            # 現在の framebuffer size を毎 frame 参照し、リサイズ後も
            # canvas の縦横比を保つ aspect-fit viewport へ更新する。
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
            if recording:
                # GUI toolbar と録画 monitor が同じ timeline を示すよう mirror する。
                # seek() は毎frame epochを進めるため、連続同期専用APIを使う。
                self._clock.synchronize(float(t))
            monitor = self._monitor

            # --- 5) Geometry の param 解決 + 描画 ---
            #
            effective_defaults = LayerStyleDefaults(
                color=style.global_line_color_rgb01,
                thickness=style.global_thickness,
            )
            quality: PreviewQuality = (
                "final"
                if recording
                or any(
                    request.snapshot is None
                    for request in self._pending_export_requests
                )
                else "draft"
            )
            profiles = getattr(
                self,
                "_runtime_limit_profiles",
                DEFAULT_RUNTIME_LIMIT_PROFILES,
            )
            apply_limits = getattr(self._renderer, "apply_runtime_limits", None)
            if callable(apply_limits):
                apply_limits(profiles.for_quality(quality))
            realized_layers = self._evaluate_scene(
                t,
                cc_snapshot=cc_snapshot,
                defaults=effective_defaults,
                recording=recording,
                quality=quality,
            )
            fresh_frame = self._scene_runner.last_evaluation_succeeded is True
            runner_revision = getattr(
                self._scene_runner,
                "last_realized_snapshot_revision",
                None,
            )
            if runner_revision is not None:
                presented_snapshot_revision: int | None = int(runner_revision)
                self._presented_snapshot_revision = presented_snapshot_revision
            else:
                presented_snapshot_revision = getattr(
                    self,
                    "_presented_snapshot_revision",
                    None,
                )
                if fresh_frame:
                    # constructor を経由しない旧 test double は表示 revision を
                    # 公開しないため、同期成功と同じ current revision を使う。
                    presented_snapshot_revision = int(self._store.revision)
                    self._presented_snapshot_revision = presented_snapshot_revision

            fresh_scene_serial = int(
                getattr(self, "_fresh_scene_serial", 0)
            )
            if fresh_frame:
                fresh_scene_serial += 1
                self._fresh_scene_serial = fresh_scene_serial
            perf.record_preview_result(
                requested_revision=int(self._store.revision),
                presented_revision=presented_snapshot_revision,
                fresh=fresh_frame,
            )
            if monitor is not None:
                waiting = bool(
                    getattr(self._scene_runner, "is_waiting_for_fresh_result", False)
                )
                monitor.set_transport(
                    # monitor は実際に表示する frame の時刻を示す。toolbar の
                    # clock 時刻との差は waiting/target として明示する。
                    t=float(self._last_frame_t),
                    requested_t=float(t),
                    waiting=waiting,
                    playing=bool(recording or self._clock.is_playing),
                    speed=(1.0 if recording else float(self._clock.speed)),
                    recording=bool(recording),
                )
            frame_vertices = 0
            frame_lines = 0
            for item in realized_layers:
                with perf.section("render_layer"):
                    stats = self._renderer.render_layer(
                        realized=item.realized,
                        cache_key=item.cache_key,
                        color=item.color,
                        thickness=item.thickness,
                        scene_serial=(
                            fresh_scene_serial
                            if presented_snapshot_revision is not None
                            else None
                        ),
                        snapshot_revision=presented_snapshot_revision,
                    )
                frame_vertices += int(stats.draw_vertices)
                frame_lines += int(stats.draw_lines)

            if monitor is not None:
                monitor.set_draw_counts(vertices=int(frame_vertices), lines=int(frame_lines))

            provenance_token: _FrameProvenanceToken | None = None
            frame_provenance: CaptureProvenance | None = None
            if fresh_frame:
                provenance_token = self._new_frame_provenance_token(
                    quality=quality,
                    snapshot_revision=presented_snapshot_revision,
                )
                recording_capture = getattr(self, "_recording_capture", None)
                if provenance_token is not None and (
                    bool(self._pending_export_requests)
                    or (
                        recording
                        and recording_capture is not None
                        and recording_capture.provenance is None
                    )
                ):
                    frame_provenance = self._materialize_frame_provenance(
                        provenance_token,
                        t=float(self._last_frame_t),
                    )
                    if frame_provenance is None:
                        raise RuntimeError(
                            "fresh frame parameters changed before provenance materialization"
                        )
                if provenance_token is not None:
                    # 通常 preview は hash を作らないが、従来の frame.index は保つ。
                    self._commit_frame_provenance_token(provenance_token)

            if recording:
                if fresh_frame:
                    with perf.section("video"):
                        # GPU からの readback が入るため、perf では明示セクションに分ける。
                        self._recording.write_frame(self._renderer.ctx.screen)
                    capture = getattr(self, "_recording_capture", None)
                    if capture is not None and capture.provenance is None:
                        capture.provenance = frame_provenance
                else:
                    # preview は last-good を表示しても、動画には重複書込みせず、同じ
                    # recording t を fresh scene が得られるまで再試行する。
                    self._recording.pause_frame(
                        self._last_frame_error or "Scene evaluation did not produce a fresh frame"
                    )

            if fresh_frame:
                # 通常 preview は immutable geometry/style/t だけを保持する。provenance は
                # pending capture、recording first frame、明示 export の境界で具体化する。
                snapshot = FrameExportSnapshot(
                    layers=tuple(realized_layers),
                    canvas_size=self._settings.canvas_size,
                    background_color_rgb01=style.bg_color_rgb01,
                    t=float(self._last_frame_t),
                    provenance=None,
                    gcode_config=self._capture_gcode_config(),
                )
                self._last_export_snapshot = snapshot
                self._last_export_provenance_token = provenance_token
                if self._pending_export_requests:
                    capture_snapshot = (
                        snapshot
                        if frame_provenance is None
                        else replace(snapshot, provenance=frame_provenance)
                    )
                    self._submit_pending_exports(
                        capture_snapshot,
                        provenance_token=provenance_token,
                    )

            if perf.enabled and perf.gpu_finish:
                with perf.section("gpu_finish"):
                    self._renderer.finish()

    def _shutdown_export_snapshot(self) -> FrameExportSnapshot:
        """close 直前の未結合 request に使う、最後の表示 frame を返す。"""

        snapshot = self._last_export_snapshot
        if snapshot is not None:
            token = self._token_for_snapshot(snapshot)
            if (
                token is not None
                and not self._frame_provenance_token_is_current(token)
                and hasattr(self, "_scene_runner")
            ):
                return self._final_capture_snapshot()
            return self._snapshot_with_provenance(
                snapshot,
                quality="final",
                token=token,
            )
        # 初回 draw 前の key event にも空 scene の明示的な capture を与える。
        style = self._style.resolve()
        fallback = FrameExportSnapshot(
            layers=tuple(self._last_realized_layers),
            canvas_size=self._settings.canvas_size,
            background_color_rgb01=style.bg_color_rgb01,
            t=float(self._last_frame_t),
            gcode_config=self._capture_gcode_config(),
        )
        return self._snapshot_with_provenance(fallback, quality="final")

    def _drain_exports_on_close(
        self,
        *,
        timeout_s: float = _CAPTURE_SHUTDOWN_TIMEOUT_S,
    ) -> bool:
        """accepted captureを全体deadlineまでdrainし、完走したか返す。"""

        timeout = float(timeout_s)
        if not isfinite(timeout) or timeout < 0.0:
            raise ValueError("timeout_s は有限の 0 以上である必要があります")
        deadline = time.monotonic() + timeout

        shutdown_snapshot: FrameExportSnapshot | None = None
        if self._pending_export_requests:
            first_bound = next(
                (
                    request.snapshot
                    for request in self._pending_export_requests
                    if request.snapshot is not None
                ),
                None,
            )
            shutdown_snapshot = (
                self._shutdown_export_snapshot()
                if any(request.snapshot is None for request in self._pending_export_requests)
                else first_bound
            )
        while True:
            self._poll_export_results()
            if self._pending_export_requests:
                assert shutdown_snapshot is not None
                self._submit_pending_exports(shutdown_snapshot)
            if not self._pending_export_requests and not self._export_jobs.has_work:
                return True
            if time.monotonic() >= deadline:
                unsubmitted = len(self._pending_export_requests)
                self._pending_export_requests.clear()
                notice = (
                    "Capture shutdown deadline reached; cancelling remaining exports: "
                    f"unsubmitted={unsubmitted}, timeout={timeout:g}s"
                )
                self._last_capture_queue_notice = notice
                print(notice)
                cancel = getattr(self._export_jobs, "cancel", None)
                if callable(cancel):
                    cancel()
                self._poll_export_results()
                self._update_capture_queue_monitor()
                return False
            # backend は worker process で進む。UI thread での busy spin を避ける。
            time.sleep(_EXPORT_SHUTDOWN_POLL_S)

    def close(
        self,
        *,
        timeout_s: float = _CAPTURE_SHUTDOWN_TIMEOUT_S,
    ) -> None:
        """accepted capture を確定し、GPU / window 資源を全て解放する。"""

        if bool(getattr(self, "_closed", False)):
            return
        timeout = float(timeout_s)
        if not isfinite(timeout) or timeout < 0.0:
            raise ValueError("timeout_s は有限の 0 以上である必要があります")
        capture_deadline = time.monotonic() + timeout

        def capture_time_remaining() -> float:
            return max(0.0, capture_deadline - time.monotonic())

        self._closed = True
        first_error: BaseException | None = None

        def attempt(label: str, action: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                action()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                else:
                    _logger.exception(
                        "Cleanup step failed after an earlier error: %s",
                        label,
                    )

        # --- 録画 ---
        # completed video temp を最初に artifact+manifest transaction へ確定する。
        # export backlog より後にすると、強制終了時に録画を失い得る。
        def stop_recording() -> None:
            if self._recording.is_recording:
                self.stop_video_recording(
                    timeout_s=capture_time_remaining(),
                    stop_reason="shutdown",
                )

        attempt("stop video recording", stop_recording)

        # --- PNG/G-code export ---
        # normal close は deadline 内でdrainし、超過時は明示cancelする。
        # drain 自体が失敗した場合も worker close/poll は必ず試す。
        attempt(
            "drain PNG/G-code exports",
            lambda: self._drain_exports_on_close(
                timeout_s=capture_time_remaining()
            ),
        )
        attempt("close PNG/G-code export worker", self._export_jobs.close)
        attempt("poll terminal export results", self._poll_export_results)

        # --- MIDI ---
        # session は controller と frozen state を一体で所有する。
        midi = self._midi_session
        self._midi_session = None
        if midi is not None:
            attempt("close MIDI session", midi.close)

        # --- mp-draw worker / scene 実行器 ---
        attempt("close scene runner", self._scene_runner.close)

        # renderer が保持している GPU リソースの所有 context を current にしてから解放する。
        switch_to = getattr(self.window, "switch_to", None)
        if callable(switch_to):
            attempt("activate draw GL context", switch_to)
        attempt("release renderer", self._renderer.release)
        attempt("close draw window", self.window.close)

        if first_error is not None:
            raise first_error
