# どこで: `src/grafix/interactive/runtime/monitor.py`。
# 何を: interactive 実行中の軽量メトリクス（FPS/CPU/RSS/頂点/ライン）を計測し、GUI 表示用スナップショットを提供する。
# なぜ: Parameter GUI 上で描画負荷を即座に把握できるようにするため。

from __future__ import annotations

from dataclasses import dataclass
import os
import time


@dataclass(frozen=True, slots=True)
class MonitorSnapshot:
    """Parameter GUI に表示する監視値のスナップショット。"""

    fps: float
    cpu_percent: float
    rss_mb: float
    vertices: int
    lines: int
    frame_error: str | None = None
    transport_t: float = 0.0
    transport_requested_t: float = 0.0
    transport_waiting: bool = False
    transport_playing: bool = True
    transport_speed: float = 1.0
    transport_recording: bool = False
    capture_request_count: int = 0
    capture_request_limit: int = 0
    capture_retained_bytes: int = 0
    capture_byte_limit: int = 0
    capture_notice: str | None = None


class RuntimeMonitor:
    """interactive 実行中のメトリクスを軽量に集計する。"""

    def __init__(
        self,
        *,
        cpu_mem_sample_interval_s: float = 0.5,
        fps_sample_interval_s: float = 0.5,
    ) -> None:
        """監視を初期化する。

        Parameters
        ----------
        cpu_mem_sample_interval_s : float
            cpu/memory を psutil でサンプリングする最小間隔（秒）。
        fps_sample_interval_s : float
            FPS を更新する最小間隔（秒）。
        """

        self._cpu_mem_sample_interval_s = float(cpu_mem_sample_interval_s)

        self._fps_sample_interval_s = float(fps_sample_interval_s)
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
        self._transport_playing = True
        self._transport_speed = 1.0
        self._transport_recording = False
        self._capture_request_count = 0
        self._capture_request_limit = 0
        self._capture_retained_bytes = 0
        self._capture_byte_limit = 0
        self._capture_notice: str | None = None

        try:
            import psutil  # type: ignore[import-untyped]
        except Exception as exc:
            raise RuntimeError("RuntimeMonitor には psutil が必要です") from exc

        self._process = psutil.Process(int(os.getpid()))

    def tick_frame(self) -> None:
        """フレーム境界を通知し、FPS/CPU/Mem を更新する。"""

        now = time.perf_counter()

        # --- FPS ---
        if self._fps_window_t0 is None:
            self._fps_window_t0 = float(now)
            self._fps_window_frames = 0

        self._fps_window_frames += 1
        dt = float(now - float(self._fps_window_t0))
        if dt >= float(self._fps_sample_interval_s) and dt > 0.0:
            self._fps = float(self._fps_window_frames) / float(dt)
            self._fps_window_t0 = float(now)
            self._fps_window_frames = 0

        # --- CPU / Mem（一定周期）---
        last = self._last_sample_t
        if last is None:
            self._last_sample_t = float(now)
            self._last_cpu_total_s = float(self._cpu_total_s())
            self._rss_mb = float(self._rss_bytes()) / (1024.0 * 1024.0)
            return

        if float(now - last) < float(self._cpu_mem_sample_interval_s):
            return

        cpu_total_s = float(self._cpu_total_s())
        prev_cpu_total_s = float(self._last_cpu_total_s or 0.0)
        wall_dt = float(now - last)

        # 子プロセスが終了すると合算値が減ることがあるため、負の Δ は “リセット” 扱いにする。
        if cpu_total_s < prev_cpu_total_s:
            self._last_sample_t = float(now)
            self._last_cpu_total_s = float(cpu_total_s)
            self._rss_mb = float(self._rss_bytes()) / (1024.0 * 1024.0)
            return

        cpu_dt = float(cpu_total_s - prev_cpu_total_s)
        if wall_dt > 0.0:
            self._cpu_percent = 100.0 * cpu_dt / wall_dt

        self._rss_mb = float(self._rss_bytes()) / (1024.0 * 1024.0)
        self._last_sample_t = float(now)
        self._last_cpu_total_s = float(cpu_total_s)

    def set_draw_counts(self, *, vertices: int, lines: int) -> None:
        """描画対象の頂点数/ライン数（polyline 本数）を設定する。"""

        self._vertices = int(vertices)
        self._lines = int(lines)

    def set_frame_error(self, message: str | None) -> None:
        """user scene の直近 error を設定する。成功 frame では None に戻す。"""

        self._frame_error = None if message is None else str(message)

    def set_transport(
        self,
        *,
        t: float,
        requested_t: float | None = None,
        waiting: bool = False,
        playing: bool,
        speed: float,
        recording: bool = False,
    ) -> None:
        """preview transport の現在状態を設定する。"""

        self._transport_t = float(t)
        self._transport_requested_t = float(
            t if requested_t is None else requested_t
        )
        self._transport_waiting = bool(waiting)
        self._transport_playing = bool(playing)
        self._transport_speed = float(speed)
        self._transport_recording = bool(recording)

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

        self._capture_request_count = max(0, int(request_count))
        self._capture_request_limit = max(0, int(request_limit))
        self._capture_retained_bytes = max(0, int(retained_bytes))
        self._capture_byte_limit = max(0, int(byte_limit))
        self._capture_notice = None if notice is None else str(notice)

    def snapshot(self) -> MonitorSnapshot:
        """現在の監視値をスナップショットとして返す。"""

        return MonitorSnapshot(
            fps=float(self._fps),
            cpu_percent=float(self._cpu_percent),
            rss_mb=float(self._rss_mb),
            vertices=int(self._vertices),
            lines=int(self._lines),
            frame_error=self._frame_error,
            transport_t=float(self._transport_t),
            transport_requested_t=float(self._transport_requested_t),
            transport_waiting=bool(self._transport_waiting),
            transport_playing=bool(self._transport_playing),
            transport_speed=float(self._transport_speed),
            transport_recording=bool(self._transport_recording),
            capture_request_count=int(self._capture_request_count),
            capture_request_limit=int(self._capture_request_limit),
            capture_retained_bytes=int(self._capture_retained_bytes),
            capture_byte_limit=int(self._capture_byte_limit),
            capture_notice=self._capture_notice,
        )

    def _cpu_times_s(self, proc) -> float:
        t = proc.cpu_times()
        user = float(getattr(t, "user", 0.0))
        system = float(getattr(t, "system", 0.0))
        return float(user + system)

    def _cpu_total_s(self) -> float:
        total = float(self._cpu_times_s(self._process))
        for child in self._process.children(recursive=True):
            try:
                total += float(self._cpu_times_s(child))
            except Exception:
                continue
        return float(total)

    def _rss_bytes(self) -> int:
        total = int(self._process.memory_info().rss)
        for child in self._process.children(recursive=True):
            try:
                total += int(child.memory_info().rss)
            except Exception:
                continue
        return int(total)
