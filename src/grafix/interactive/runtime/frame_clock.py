# どこで: `src/grafix/interactive/runtime/frame_clock.py`。
# 何を: `draw(t)` に渡すフレーム時刻 `t` の生成規則を提供する。
# なぜ: 「通常は操作可能な実時間」「録画中は固定 fps」を分離するため。

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import time


TimeSource = Callable[[], float]


@dataclass(frozen=True, slots=True)
class TransportSnapshot:
    """プレビューの transport 状態。"""

    t: float
    is_playing: bool
    speed: float
    epoch: int = 0


class TransportClock:
    """プレビュー用の操作可能な実時間クロック。

    `time_source` は単調増加時計を想定し、既定値は `perf_counter`。
    注入した時刻源が逆行した場合も `t` が意図せず戻らないよう、
    直前に観測した値で clamp する。

    Notes
    -----
    `seek` / `reset` / `step_frame` はユーザーが意図した timeline 操作のため、
    それらの呼び出しに限り `t` は戻ることがある。
    """

    def __init__(
        self,
        *,
        start_time: float | None = None,
        time_source: TimeSource = time.perf_counter,
        initial_t: float = 0.0,
        playing: bool = True,
        speed: float = 1.0,
    ) -> None:
        self._time_source = time_source
        source_start = float(time_source()) if start_time is None else float(start_time)
        self._require_finite(source_start, name="start_time")

        timeline_start = float(initial_t)
        self._require_finite(timeline_start, name="initial_t")
        playback_speed = self._validated_speed(speed)

        self._last_source_time = source_start
        self._anchor_source_time = source_start
        self._anchor_t = timeline_start
        self._is_playing = bool(playing)
        self._speed = playback_speed
        # 非同期 draw の結果が timeline の不連続をまたいで採用されないよう、
        # seek/reset/step ごとに単調増加させる generation。
        self._epoch = 0

    @property
    def is_playing(self) -> bool:
        """再生中なら `True`。"""

        return bool(self._is_playing)

    @property
    def speed(self) -> float:
        """現在の再生倍率を返す。"""

        return float(self._speed)

    @property
    def epoch(self) -> int:
        """現在の transport generation を返す。

        連続再生、pause/play、speed 変更では変化せず、timeline を不連続に
        移動する操作でだけ増加する。非同期 evaluator はこの値を task/result
        に結び付け、古い generation の結果を破棄できる。
        """

        return int(self._epoch)

    def t(self) -> float:
        """現在のフレーム時刻 `t`（秒）を返す。"""

        if not self._is_playing:
            return float(self._anchor_t)
        return float(self._timeline_at(self._read_source_time()))

    def snapshot(self) -> TransportSnapshot:
        """時刻と再生状態を同じ観測点の snapshot として返す。"""

        return TransportSnapshot(
            t=self.t(),
            is_playing=self.is_playing,
            speed=self.speed,
            epoch=self.epoch,
        )

    def play(self) -> None:
        """現在の `t` から再生を開始する。"""

        if self._is_playing:
            return
        self._anchor_source_time = self._read_source_time()
        self._is_playing = True

    def pause(self) -> None:
        """現在の `t` で再生を一時停止する。"""

        if not self._is_playing:
            return
        now = self._read_source_time()
        self._anchor_t = self._timeline_at(now)
        self._anchor_source_time = now
        self._is_playing = False

    def toggle(self) -> bool:
        """再生/一時停止を切り替え、切り替え後の再生状態を返す。"""

        if self._is_playing:
            self.pause()
        else:
            self.play()
        return self.is_playing

    def reset(self) -> None:
        """再生/一時停止状態を保ったまま `t = 0` へ戻す。"""

        self.seek(0.0)

    def seek(self, t: float) -> None:
        """再生/一時停止状態を保ったまま `t` を移動する。"""

        self.synchronize(t)
        self.mark_discontinuity()

    def synchronize(self, t: float) -> None:
        """epoch を変えず、外部 fixed timeline の現在時刻へ同期する。

        録画中に `RecordingClock` の時刻を toolbar へ mirror するような、
        同一の不連続区間内での同期専用。ユーザーの seek/scrub には `seek()`
        を使い、録画の開始・終了時は別途 `mark_discontinuity()` を呼ぶ。
        """

        target = float(t)
        self._require_finite(target, name="t")
        self._anchor_t = target
        self._anchor_source_time = self._read_source_time()

    def step_frame(self, *, fps: float = 60.0, frames: int = 1) -> float:
        """一時停止し、`frames / fps` 秒だけ timeline を進める。

        負の `frames` を渡すとフレーム単位で戻せる。
        操作後の `t` を返す。
        """

        frame_rate = float(fps)
        if not math.isfinite(frame_rate) or frame_rate <= 0.0:
            raise ValueError("fps は有限の正の値である必要がある")
        if isinstance(frames, bool) or not isinstance(frames, int):
            raise TypeError("frames は int である必要がある")

        self.pause()
        self._anchor_t += float(frames) / frame_rate
        self.mark_discontinuity()
        return float(self._anchor_t)

    def mark_discontinuity(self) -> int:
        """録画境界など外部の不連続を記録し、新しい epoch を返す。

        `seek` / `reset` / `step_frame` は自動で呼ぶ。録画の開始・終了など、
        clock 自身が観測できない境界では呼び出し側が明示的に利用する。
        """

        self._epoch += 1
        return int(self._epoch)

    def set_speed(self, speed: float) -> None:
        """`t` の連続性を保ったまま再生倍率を変える。"""

        playback_speed = self._validated_speed(speed)
        if playback_speed == self._speed:
            return

        if self._is_playing:
            now = self._read_source_time()
            self._anchor_t = self._timeline_at(now)
            self._anchor_source_time = now
        self._speed = playback_speed

    def tick(self) -> None:
        """フレームを進める（実時間では no-op）。"""

        return

    def _read_source_time(self) -> float:
        now = float(self._time_source())
        self._require_finite(now, name="time_source()")
        now = max(now, self._last_source_time)
        self._last_source_time = now
        return now

    def _timeline_at(self, source_time: float) -> float:
        return float(
            self._anchor_t
            + (float(source_time) - self._anchor_source_time) * float(self._speed)
        )

    @staticmethod
    def _validated_speed(speed: float) -> float:
        playback_speed = float(speed)
        if not math.isfinite(playback_speed) or playback_speed <= 0.0:
            raise ValueError("speed は有限の正の値である必要がある")
        return playback_speed

    @staticmethod
    def _require_finite(value: float, *, name: str) -> None:
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} は有限値である必要がある")


class RealTimeClock(TransportClock):
    """後方互換のための実時間クロック名。

    従来の `RealTimeClock(start_time=...)` はそのまま利用でき、
    transport 操作も `TransportClock` と同様に利用できる。
    """


class RecordingClock:
    """録画タイムラインのフレーム時計。

    Notes
    -----
    `t` は `t0 + frame_index/fps`。
    実時間と切り離し、録画データ側の fps を維持するために使う。
    """

    def __init__(self, *, t0: float, fps: float) -> None:
        _fps = float(fps)
        if _fps <= 0:
            raise ValueError("fps は正の値である必要がある")
        self._t0 = float(t0)
        self._fps = _fps
        self._frame_index = 0

    @property
    def fps(self) -> float:
        """録画 fps を返す。"""

        return float(self._fps)

    @property
    def frame_index(self) -> int:
        """現在のフレーム番号（0-based）を返す。"""

        return int(self._frame_index)

    def t(self) -> float:
        """現在のフレーム時刻 `t`（秒）を返す。"""

        return float(self._t0 + float(self._frame_index) / float(self._fps))

    def tick(self) -> None:
        """フレームを 1 つ進める。"""

        self._frame_index += 1
