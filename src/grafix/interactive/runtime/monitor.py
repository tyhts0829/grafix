# どこで: `src/grafix/interactive/runtime/monitor.py`。
# 何を: interactive 実行中の軽量メトリクス（FPS/CPU/RSS/頂点/ライン）を計測し、GUI 表示用スナップショットを提供する。
# なぜ: Parameter GUI 上で描画負荷を即座に把握できるようにするため。

from __future__ import annotations

import os
import time

import psutil  # type: ignore[import-untyped]

from grafix.core.value_validation import (
    exact_bool,
    exact_integer,
    exact_string,
    exact_string_choice,
    finite_real,
)

from grafix.interactive.diagnostics import (
    DiagnosticAction,
    DiagnosticCenter,
    DiagnosticEvent,
)
from grafix.interactive.telemetry import MonitorSnapshot, PerfSnapshot


def _optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return exact_string(value, name=name)


class RuntimeMonitor:
    """interactive 実行中のメトリクスを軽量に集計する。"""

    def __init__(
        self,
        *,
        cpu_mem_sample_interval_s: float = 0.5,
        fps_sample_interval_s: float = 0.5,
        diagnostic_center: DiagnosticCenter | None = None,
    ) -> None:
        """監視を初期化する。

        Parameters
        ----------
        cpu_mem_sample_interval_s : float
            cpu/memory を psutil でサンプリングする最小間隔（秒）。
        fps_sample_interval_s : float
            FPS を更新する最小間隔（秒）。
        """

        self._cpu_mem_sample_interval_s = finite_real(
            cpu_mem_sample_interval_s,
            name="cpu_mem_sample_interval_s",
            minimum=0.0,
            minimum_inclusive=False,
        )

        self._fps_sample_interval_s = finite_real(
            fps_sample_interval_s,
            name="fps_sample_interval_s",
            minimum=0.0,
            minimum_inclusive=False,
        )
        self._fps = 0.0
        self._fps_window_t0: float | None = None
        self._fps_window_frames = 0

        self._last_sample_t: float | None = None
        self._last_cpu_total_s: float | None = None
        self._cpu_percent = 0.0
        self._rss_mb = 0.0

        self._vertices = 0
        self._lines = 0
        self._frame_error: str | None = None
        self._transport_t = 0.0
        self._transport_requested_t = 0.0
        self._transport_waiting = False
        self._transport_speed = 1.0
        self._transport_recording = False
        self._capture_request_count = 0
        self._capture_request_limit = 0
        self._capture_retained_bytes = 0
        self._capture_byte_limit = 0
        self._capture_notice: str | None = None
        if diagnostic_center is not None and not isinstance(
            diagnostic_center,
            DiagnosticCenter,
        ):
            raise TypeError(
                "diagnostic_center は DiagnosticCenter または None である必要があります"
            )
        self._diagnostic_center = (
            DiagnosticCenter()
            if diagnostic_center is None
            else diagnostic_center
        )
        self._autosave_status = "clean"
        self._autosave_error: str | None = None
        self._recovered_session = False
        self._profiler: PerfSnapshot | None = None

        self._process = psutil.Process(os.getpid())

    def tick_frame(self) -> None:
        """フレーム境界を通知し、FPS/CPU/Mem を更新する。"""

        now = time.perf_counter()

        # --- FPS ---
        if self._fps_window_t0 is None:
            self._fps_window_t0 = now
            self._fps_window_frames = 0

        self._fps_window_frames += 1
        dt = now - self._fps_window_t0
        if dt >= self._fps_sample_interval_s and dt > 0.0:
            self._fps = self._fps_window_frames / dt
            self._fps_window_t0 = now
            self._fps_window_frames = 0

        # --- CPU / Mem（一定周期）---
        last = self._last_sample_t
        if last is None:
            self._last_sample_t = now
            self._last_cpu_total_s = self._cpu_total_s()
            self._rss_mb = self._rss_bytes() / (1024.0 * 1024.0)
            return

        if now - last < self._cpu_mem_sample_interval_s:
            return

        cpu_total_s = self._cpu_total_s()
        prev_cpu_total_s = self._last_cpu_total_s or 0.0
        wall_dt = now - last

        # 子プロセスが終了すると合算値が減ることがあるため、負の Δ は “リセット” 扱いにする。
        if cpu_total_s < prev_cpu_total_s:
            self._last_sample_t = now
            self._last_cpu_total_s = cpu_total_s
            self._rss_mb = self._rss_bytes() / (1024.0 * 1024.0)
            return

        cpu_dt = cpu_total_s - prev_cpu_total_s
        if wall_dt > 0.0:
            self._cpu_percent = 100.0 * cpu_dt / wall_dt

        self._rss_mb = self._rss_bytes() / (1024.0 * 1024.0)
        self._last_sample_t = now
        self._last_cpu_total_s = cpu_total_s

    def set_draw_counts(self, *, vertices: int, lines: int) -> None:
        """描画対象の頂点数/ライン数（polyline 本数）を設定する。"""

        self._vertices = exact_integer(vertices, name="vertices", minimum=0)
        self._lines = exact_integer(lines, name="lines", minimum=0)

    @property
    def diagnostic_center(self) -> DiagnosticCenter:
        """user-facing 診断の共有 center を返す。"""

        return self._diagnostic_center

    def publish_diagnostic(self, event: DiagnosticEvent) -> DiagnosticEvent:
        """診断を共有 center へ追加して返す。"""

        return self._diagnostic_center.publish(event)

    def set_frame_error(
        self,
        message: str | None,
        *,
        details: str = "",
        source: str | None = None,
    ) -> None:
        """user scene の直近 error を設定する。成功 frame では None に戻す。"""

        normalized_message = _optional_string(message, name="message")
        normalized_details = exact_string(details, name="details")
        normalized_source = _optional_string(source, name="source")
        previous = self._frame_error
        self._frame_error = normalized_message
        if normalized_message is not None and previous != normalized_message:
            actions = [DiagnosticAction("copy", "Copy details")]
            if normalized_source is not None:
                actions.append(DiagnosticAction("open", "Open source"))
            self.publish_diagnostic(
                DiagnosticEvent(
                    category="scene",
                    severity="error",
                    summary=normalized_message,
                    details=normalized_details,
                    source=normalized_source,
                    actions=tuple(actions),
                    dedupe_key=f"frame-error:{normalized_message}",
                )
            )

    def set_transport(
        self,
        *,
        t: float,
        requested_t: float | None = None,
        waiting: bool = False,
        speed: float,
        recording: bool = False,
    ) -> None:
        """preview transport の現在状態を設定する。"""

        self._transport_t = finite_real(t, name="t")
        self._transport_requested_t = finite_real(
            t if requested_t is None else requested_t,
            name="requested_t",
        )
        self._transport_waiting = exact_bool(waiting, name="waiting")
        self._transport_speed = finite_real(
            speed,
            name="speed",
            minimum=0.0,
            minimum_inclusive=False,
        )
        self._transport_recording = exact_bool(recording, name="recording")

    def set_capture_queue(
        self,
        *,
        request_count: int,
        request_limit: int,
        retained_bytes: int,
        byte_limit: int,
        notice: str | None = None,
    ) -> None:
        """capture queue の count/byte pressure と直近の明示拒否を設定する。"""

        self._capture_request_count = exact_integer(
            request_count,
            name="request_count",
            minimum=0,
        )
        self._capture_request_limit = exact_integer(
            request_limit,
            name="request_limit",
            minimum=0,
        )
        self._capture_retained_bytes = exact_integer(
            retained_bytes,
            name="retained_bytes",
            minimum=0,
        )
        self._capture_byte_limit = exact_integer(
            byte_limit,
            name="byte_limit",
            minimum=0,
        )
        normalized_notice = _optional_string(notice, name="notice")
        previous_notice = self._capture_notice
        self._capture_notice = normalized_notice
        if normalized_notice is not None and previous_notice != normalized_notice:
            self.publish_diagnostic(
                DiagnosticEvent(
                    category="export",
                    severity="warning",
                    summary=normalized_notice,
                    dedupe_key=f"capture-notice:{normalized_notice}",
                )
            )

    def set_autosave(
        self,
        *,
        status: str,
        error: str | None = None,
        source: str | None = None,
    ) -> None:
        """ParamStore autosave の user-facing 状態を設定する。"""

        status_s = exact_string_choice(
            status,
            name="status",
            choices=("clean", "dirty", "saving", "failed"),
        )
        normalized_error = _optional_string(error, name="error")
        normalized_source = _optional_string(source, name="source")
        previous = self._autosave_status
        previous_error = self._autosave_error
        self._autosave_status = status_s
        self._autosave_error = normalized_error
        if status_s == "failed" and (
            previous != "failed" or previous_error != self._autosave_error
        ):
            summary = "Parameter autosave failed"
            self.publish_diagnostic(
                DiagnosticEvent(
                    category="save",
                    severity="error",
                    summary=summary,
                    details=self._autosave_error or "",
                    source=normalized_source,
                    actions=(DiagnosticAction("retry", "Retry"),),
                    dedupe_key=f"autosave:{self._autosave_error}",
                )
            )

    def set_recovered_session(self, active: bool) -> None:
        """未確定の session recovery があるかを status surface へ反映する。"""

        self._recovered_session = exact_bool(active, name="active")

    def set_profiler(self, snapshot: PerfSnapshot) -> None:
        """Inspector へ渡す直近の bounded profiler snapshot を設定する。"""

        if not isinstance(snapshot, PerfSnapshot):
            raise TypeError("snapshot は PerfSnapshot である必要があります")
        self._profiler = snapshot

    def snapshot(self) -> MonitorSnapshot:
        """現在の監視値をスナップショットとして返す。"""

        return MonitorSnapshot(
            fps=self._fps,
            cpu_percent=self._cpu_percent,
            rss_mb=self._rss_mb,
            vertices=self._vertices,
            lines=self._lines,
            frame_error=self._frame_error,
            transport_t=self._transport_t,
            transport_requested_t=self._transport_requested_t,
            transport_waiting=self._transport_waiting,
            transport_speed=self._transport_speed,
            transport_recording=self._transport_recording,
            capture_request_count=self._capture_request_count,
            capture_request_limit=self._capture_request_limit,
            capture_retained_bytes=self._capture_retained_bytes,
            capture_byte_limit=self._capture_byte_limit,
            capture_notice=self._capture_notice,
            diagnostics=self._diagnostic_center.snapshot(),
            autosave_status=self._autosave_status,
            autosave_error=self._autosave_error,
            recovered_session=self._recovered_session,
            profiler=self._profiler,
        )

    def _cpu_times_s(self, proc: psutil.Process) -> float:
        t = proc.cpu_times()
        user = float(t.user)
        system = float(t.system)
        return float(user + system)

    def _cpu_total_s(self) -> float:
        total = float(self._cpu_times_s(self._process))
        try:
            children = self._process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            children = ()
        for child in children:
            try:
                total += float(self._cpu_times_s(child))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return float(total)

    def _rss_bytes(self) -> int:
        total = int(self._process.memory_info().rss)
        try:
            children = self._process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            children = ()
        for child in children:
            try:
                total += int(child.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return int(total)
