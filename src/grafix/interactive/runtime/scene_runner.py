# どこで: `src/grafix/interactive/runtime/scene_runner.py`。
# 何を: parameter_context + (sync / mp-draw) で `realize_scene()` を実行し realized_layers を返す。
# なぜ: draw の実行戦略（mp/sync/録画中の例外）を 1 箇所に固定するため。

from __future__ import annotations

from collections.abc import Callable

from grafix.core.layer import LayerStyleDefaults
from grafix.core.operation_diagnostics import (
    OperationDiagnostic,
    OperationDiagnosticBuffer,
    extend_operation_diagnostics,
)
from grafix.core.parameters import (
    MidiFrameSnapshot,
    ParamStore,
    current_frame_params,
    current_param_snapshot,
    parameter_context,
)
from grafix.core.pipeline import RealizedLayer, realize_scene
from grafix.core.realize import RealizeSession
from grafix.core.preview_quality import PreviewQuality, preview_quality_context
from grafix.core.resource_budget import (
    DEFAULT_RESOURCE_BUDGET,
    ResourceBudget,
    ResourceLimitError,
)
from grafix.core.runtime_limits import (
    RuntimeLimitProfiles,
    profiles_for_resource_budget,
)
from grafix.core.scene import SceneItem
from grafix.interactive.runtime.mp_draw import MpDraw
from grafix.interactive.runtime.perf import PerfCollector
from grafix.interactive.runtime.diagnostics import DiagnosticCenter, DiagnosticEvent


class SceneRunner:
    """このフレームで描くべき realized_layers を生成する。"""

    def __init__(
        self,
        draw: Callable[[float], SceneItem],
        *,
        perf: PerfCollector,
        n_worker: int,
        evaluation_timeout: float | None = 5.0,
        resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
        runtime_limit_profiles: RuntimeLimitProfiles | None = None,
        diagnostic_center: DiagnosticCenter | None = None,
    ) -> None:
        worker_count = int(n_worker)
        if worker_count < 0:
            raise ValueError("n_worker は 0 以上である必要があります")

        profiles = (
            profiles_for_resource_budget(resource_budget)
            if runtime_limit_profiles is None
            else runtime_limit_profiles
        )
        if not isinstance(profiles, RuntimeLimitProfiles):
            raise TypeError(
                "runtime_limit_profiles は RuntimeLimitProfiles である必要があります"
            )

        self._draw = draw
        self._perf = perf
        self._worker_count = worker_count
        self._evaluation_timeout = evaluation_timeout
        self._runtime_limit_profiles = profiles
        self._realize_sessions = {
            "draft": RealizeSession(runtime_limits=profiles.preview, profiler=perf),
            "final": RealizeSession(runtime_limits=profiles.final, profiler=perf),
        }
        # 既存の計測・test が参照する preview session alias。
        self._realize_session = self._realize_sessions["draft"]
        self._diagnostic_center = diagnostic_center
        self._last_operation_diagnostics: tuple[OperationDiagnostic, ...] = ()
        self._mp_draw: MpDraw | None = (
            MpDraw(
                draw,
                n_worker=worker_count,
                evaluation_timeout=evaluation_timeout,
            )
            if worker_count >= 1
            else None
        )
        # mp-draw は結果未到着の frame でも前回 scene を再利用して返すため、単なる
        # run() の正常 return だけでは user draw の回復を判定できない。None は
        # 「この呼び出しでは新しい評価結果が無い」を表す。
        self._last_evaluation_succeeded: bool | None = None
        self._last_evaluation_t: float | None = None
        # `last_evaluation_*` は worker から新しい終端結果を受け取ったかを
        # 表す。一方、後続 error と同時に drain された成功 frame は、
        # error 通知の次の run で初めて realize される。その出力時刻を
        # manifest と結び付けるため、終端 status とは別に保持する。
        self._last_realized_t: float | None = None
        self._last_merged_mp_success_frame_id: int | None = None
        self._last_merged_mp_success_epoch: int | None = None
        # transport discontinuity 後に fresh mp result を待つ間も、実際に
        # 画面へ出していた frame とその時刻を対で維持する。
        self._retained_realized_layers: list[RealizedLayer] = []
        self._retained_realized_t: float | None = None
        self._waiting_for_fresh_result = False
        self._mp_epoch = 0
        self._last_transport_epoch: int | None = None
        self._last_recording: bool | None = None
        self._last_quality: PreviewQuality | None = None

    def replace_draw(self, draw: Callable[[float], SceneItem]) -> None:
        """draw callable と background worker 世代を一つの境界で交換する。

        新 worker の構築に失敗した場合は現在の callable/worker/last-good frame を
        変更しない。成功時は旧 worker の結果を無効化し、次の fresh result までは
        直近の表示を維持する。ParamStore と realize cache の寿命は変えない。
        """

        if not callable(draw):
            raise TypeError("draw は callable である必要があります")

        next_epoch = self._mp_epoch + 1
        replacement: MpDraw | None = None
        if self._worker_count >= 1:
            replacement = MpDraw(
                draw,
                n_worker=self._worker_count,
                evaluation_timeout=self._evaluation_timeout,
            )
            try:
                replacement.begin_epoch(next_epoch)
            except BaseException:
                replacement.close()
                raise

        previous = self._mp_draw
        self._draw = draw
        self._mp_draw = replacement
        self._mp_epoch = next_epoch
        self._last_merged_mp_success_frame_id = None
        self._last_merged_mp_success_epoch = None
        self._last_evaluation_succeeded = None
        self._last_evaluation_t = None
        self._last_realized_t = self._retained_realized_t
        self._waiting_for_fresh_result = replacement is not None

        if previous is None:
            return
        try:
            previous.close()
        except Exception as exc:
            center = self._diagnostic_center
            if center is not None:
                center.publish(
                    DiagnosticEvent(
                        category="reload",
                        severity="warning",
                        summary="旧 draw worker の終了に失敗しました",
                        details=f"{type(exc).__name__}: {exc}",
                        dedupe_key=(
                            "reload-old-worker-close:"
                            f"{type(exc).__name__}:{exc}"
                        ),
                    )
                )

    @property
    def last_evaluation_succeeded(self) -> bool | None:
        """直近 `run()` で新しい scene 評価が成功したかを返す。

        `None` は mp-draw の結果待ちなど、この frame で新しい評価結果が無かった状態。
        DrawWindowSystem はこの値を使い、error 表示を本当の成功結果まで保持する。
        """

        return self._last_evaluation_succeeded

    @property
    def last_evaluation_t(self) -> float | None:
        """直近に新しく成功した scene が評価された `t` を返す。"""

        return self._last_evaluation_t

    @property
    def last_realized_t(self) -> float | None:
        """直近の `run()` が実際に realize して返した成功 frame の `t`。

        mp-draw で成功 frame とより新しい error frame が同時に
        drain された場合、`last_evaluation_succeeded` は error 表示を
        維持するため `True` にしない。それでも、次の `run()` で
        実際に描画出力となった成功 frame の時刻はこの値で返す。
        """

        return self._last_realized_t

    @property
    def is_waiting_for_fresh_result(self) -> bool:
        """不連続操作後の current-epoch mp result を待っているか。"""

        return bool(self._waiting_for_fresh_result)

    @property
    def last_operation_diagnostics(self) -> tuple[OperationDiagnostic, ...]:
        """直近 evaluation で収集した immutable operation 診断を返す。"""

        return self._last_operation_diagnostics

    def _commit_operation_diagnostics(
        self,
        buffer: OperationDiagnosticBuffer | None,
    ) -> None:
        diagnostics = () if buffer is None else buffer.snapshot()
        self._last_operation_diagnostics = diagnostics
        center = self._diagnostic_center
        if center is None:
            return
        for diagnostic in diagnostics:
            center.publish(
                DiagnosticEvent(
                    category="operation",
                    severity=diagnostic.severity,
                    summary=f"{diagnostic.op}: {diagnostic.reason}",
                    details=(
                        f"original={diagnostic.original_value!r}\n"
                        f"effective={diagnostic.effective_value!r}\n"
                        f"reason={diagnostic.reason}"
                    ),
                    dedupe_key=f"operation:{diagnostic.identity()!r}",
                )
            )

    def _publish_resource_limit(self, error: Exception) -> None:
        center = self._diagnostic_center
        if center is None:
            return
        current: BaseException | None = error
        seen: set[int] = set()
        resource_error: ResourceLimitError | None = None
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ResourceLimitError):
                resource_error = current
                break
            current = current.__cause__
        if resource_error is None:
            return
        message = str(resource_error)
        center.publish(
            DiagnosticEvent(
                category="resource",
                severity="error",
                summary=message,
                details=message,
                dedupe_key=f"resource-limit:{message}",
            )
        )

    def run(
        self,
        t: float,
        *,
        store: ParamStore,
        cc_snapshot: MidiFrameSnapshot | None,
        defaults: LayerStyleDefaults,
        recording: bool,
        transport_epoch: int | None = None,
        quality: PreviewQuality = "draft",
    ) -> list[RealizedLayer]:
        """シーンを実行して realized_layers を返す。

        Raises
        ------
        MpDrawWorkerError
            mp-draw worker が予期せず終了した場合。同期実行には切り替えない。
        """

        if quality not in {"draft", "final"}:
            raise ValueError(f"unknown preview quality: {quality!r}")
        self._last_evaluation_succeeded = None
        self._last_evaluation_t = None
        self._last_realized_t = None
        self._waiting_for_fresh_result = False
        operation_diagnostics: OperationDiagnosticBuffer | None = None
        effective_quality: PreviewQuality = "final" if recording else quality
        try:
            self._update_epoch(
                recording=bool(recording),
                transport_epoch=transport_epoch,
                quality=effective_quality,
            )
            with preview_quality_context(effective_quality):
                with parameter_context(
                    store, cc_snapshot=cc_snapshot
                ) as operation_diagnostics:
                    if effective_quality == "final" or self._mp_draw is None:
                        realized_layers = self._run_sync(
                            t,
                            defaults=defaults,
                            quality=effective_quality,
                        )
                        self._last_evaluation_succeeded = True
                        self._last_evaluation_t = float(t)
                        self._last_realized_t = float(t)
                        self._retain_output(realized_layers, t=float(t))
                        return realized_layers
                    return self._run_mp(
                        t,
                        snapshot_revision=store.revision,
                        cc_snapshot=cc_snapshot,
                        defaults=defaults,
                        quality=effective_quality,
                    )
        except Exception as exc:
            self._last_evaluation_succeeded = False
            self._last_evaluation_t = None
            self._publish_resource_limit(exc)
            raise
        finally:
            self._commit_operation_diagnostics(operation_diagnostics)

    def _update_epoch(
        self,
        *,
        recording: bool,
        transport_epoch: int | None,
        quality: PreviewQuality,
    ) -> None:
        """transport/recording の不連続を mp generation へ写像する。"""

        discontinuity = False
        if transport_epoch is not None:
            requested = int(transport_epoch)
            if requested < 0:
                raise ValueError("transport_epoch は 0 以上である必要があります")
            previous = self._last_transport_epoch
            if previous is not None and requested < previous:
                raise ValueError(
                    "transport_epoch は単調増加である必要があります: "
                    f"previous={previous}, got={requested}"
                )
            if previous is None:
                # SceneRunner 作成前に seek 済みの場合も、epoch=0 の既定 task と
                # 混同しない。ただし初期値 0 は通常の連続開始として扱う。
                discontinuity = requested > 0
            elif requested != previous:
                discontinuity = True
            self._last_transport_epoch = requested

        previous_recording = self._last_recording
        if previous_recording is not None and recording != previous_recording:
            # 録画中は同期 draw に切り替わる。開始・終了の両側で旧 preview
            # task/result を無効化し、終了後に録画前へ巻き戻らないようにする。
            discontinuity = True
        self._last_recording = bool(recording)

        previous_quality = self._last_quality
        if previous_quality is not None and quality != previous_quality:
            discontinuity = True
        self._last_quality = quality

        if not discontinuity or self._mp_draw is None:
            return
        self._mp_epoch += 1
        self._mp_draw.begin_epoch(self._mp_epoch)
        self._last_merged_mp_success_frame_id = None
        self._last_merged_mp_success_epoch = None

    def _retain_output(self, layers: list[RealizedLayer], *, t: float) -> None:
        """実表示として採用できた layers/t を同時に更新する。"""

        self._retained_realized_layers = list(layers)
        self._retained_realized_t = float(t)

    def _fresh_result_pending_output(self) -> list[RealizedLayer]:
        """fresh mp result 待ち中に直近の実表示 frame を返す。"""

        self._waiting_for_fresh_result = True
        self._last_realized_t = self._retained_realized_t
        return list(self._retained_realized_layers)

    def _run_sync(
        self,
        t: float,
        *,
        defaults: LayerStyleDefaults,
        quality: PreviewQuality,
    ) -> list[RealizedLayer]:
        perf = self._perf

        draw_fn = self._draw
        if perf.enabled:

            def draw_fn_timed(t_arg: float) -> SceneItem:
                with perf.section("draw"):
                    return self._draw(t_arg)

            draw_fn = draw_fn_timed

        with perf.section("scene"):
            return realize_scene(
                draw_fn,
                t,
                defaults,
                session=self._realize_sessions[quality],
            )

    def _run_mp(
        self,
        t: float,
        *,
        snapshot_revision: int,
        cc_snapshot: MidiFrameSnapshot | None,
        defaults: LayerStyleDefaults,
        quality: PreviewQuality,
    ) -> list[RealizedLayer]:
        perf = self._perf
        mp_draw = self._mp_draw
        assert mp_draw is not None

        # 1) draw（worker 側）: 入力を投げて、届いた観測結果だけ main のバッファへマージする。
        # submit/poll の worker health error は意図的に伝播させる。worker 数を減らした継続や
        # sync draw への暗黙 fallback は、処理量と結果順序を実行中に変えるため行わない。
        mp_draw.submit(
            t=t,
            snapshot_revision=int(snapshot_revision),
            snapshot=current_param_snapshot(),
            cc_snapshot=cc_snapshot,
            epoch=int(self._mp_epoch),
            quality=quality,
        )

        new_result = mp_draw.poll_latest()
        if new_result is not None:
            if new_result.worker_lag_ms is not None:
                perf.record_worker_lag(new_result.worker_lag_ms)
            if new_result.error is not None:
                extend_operation_diagnostics(new_result.diagnostics)
                raise RuntimeError(f"mp-draw worker で例外が発生しました:\n{new_result.error}")

        latest_successful = mp_draw.latest_successful_result()
        if latest_successful is None:
            return self._fresh_result_pending_output()

        # worker は ParamStore を触れないので、実際に preview 候補となる
        # 最新成功 frame の観測を main 側で 1 回だけ反映する。
        # success と後続 error が同時に drain されると poll_latest() は
        # error だけを返すため、new_result ではなく latest_successful を基準にする。
        latest_success_frame_id = int(latest_successful.frame_id)
        latest_success_epoch = int(latest_successful.epoch)
        should_merge_success = (
            self._last_merged_mp_success_frame_id != latest_success_frame_id
            or self._last_merged_mp_success_epoch != latest_success_epoch
        )
        if should_merge_success:
            frame_params = current_frame_params()
            if frame_params is not None:
                frame_params.records.extend(latest_successful.records)
                frame_params.labels.extend(latest_successful.labels)
            extend_operation_diagnostics(latest_successful.diagnostics)

        # 2) realize（main 側）: 最新の layers を通常パイプラインへ流して表示/出力する。
        def draw_from_mp(_t_arg: float) -> SceneItem:
            return latest_successful.layers

        with perf.section("scene"):
            realized_layers = realize_scene(
                draw_from_mp,
                t,
                defaults,
                session=self._realize_sessions[quality],
            )
        # worker 成功だけではなく、main 側の realize が成功した後にだけ
        # output time を更新する。error result や realize 失敗の t を manifest へ
        # 誤って記録しないための順序。
        if should_merge_success:
            # parameter_context は例外 frame の records/labels を rollback する。
            # realize 成功前に consumed 扱いすると、次回 retry で観測を
            # 再マージできないため、成功後にだけ frame id を進める。
            self._last_merged_mp_success_frame_id = latest_success_frame_id
            self._last_merged_mp_success_epoch = latest_success_epoch
        self._last_realized_t = float(latest_successful.t)
        self._retain_output(realized_layers, t=float(latest_successful.t))
        if new_result is not None:
            # ここに到達する new_result は error=None。新しい成功結果が
            # 終端結果である場合のみ、既存 error 表示を解除する。
            self._last_evaluation_succeeded = True
            self._last_evaluation_t = float(latest_successful.t)
        return realized_layers

    def close(self) -> None:
        """mp-draw worker と realize session を終了する。"""

        mp_draw = self._mp_draw
        self._mp_draw = None
        sessions = tuple(dict.fromkeys(self._realize_sessions.values()))
        try:
            if mp_draw is not None:
                mp_draw.close()
        finally:
            for session in sessions:
                session.close()
