"""DrawWindowSystem を実初期化する headless test factory。"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from grafix.api.render import RenderOptions
from grafix.core.parameters import ParamStore
from grafix.core.pipeline import RealizedLayer
from grafix.core.runtime_config import runtime_config
from grafix.core.runtime_limits import RuntimeLimits
from grafix.interactive.gl.index_buffer import LineIndexStats
from grafix.interactive.runtime import draw_window_system as draw_window_module
from grafix.interactive.runtime.draw_window_system import DrawWindowSystem
from grafix.interactive.runtime.export_job_system import (
    ExportJobResult,
    ExportQueueStatus,
    FrameExportSnapshot,
)
from grafix.interactive.runtime.monitor import RuntimeMonitor

def _draw(_t: float) -> list[object]:
    return []


class FakeWindow:
    """DrawWindowSystem が所有する draw window の必須 contract。"""

    def __init__(self, *, width: int = 800, height: int = 800) -> None:
        self.width = int(width)
        self.height = int(height)
        self.visible = True
        self.handlers: dict[str, object] = {}

    def push_handlers(self, **handlers: object) -> None:
        self.handlers.update(handlers)

    def switch_to(self) -> None:
        return None

    def close(self) -> None:
        return None

    def clear(self) -> None:
        return None

    def get_size(self) -> tuple[int, int]:
        return self.width, self.height

    def get_framebuffer_size(self) -> tuple[int, int]:
        return self.width, self.height

    def set_minimum_size(self, _width: int, _height: int) -> None:
        return None

    def set_maximum_size(self, _width: int, _height: int) -> None:
        return None


class _FakeScreen:
    def use(self) -> None:
        return None


class FakeRenderer:
    """DrawRenderer の必須描画/lifecycle contract。"""

    def __init__(self) -> None:
        self.ctx = SimpleNamespace(screen=_FakeScreen())
        self.mesh_upload_count = 0

    def apply_runtime_limits(self, _limits: RuntimeLimits) -> None:
        return None

    def viewport(self, _width: int, _height: int) -> None:
        return None

    def clear(self, _color: tuple[float, float, float]) -> None:
        return None

    def render_layer(self, *_args: object, **_kwargs: object) -> LineIndexStats:
        return LineIndexStats(draw_vertices=0, draw_lines=0)

    def finish_dynamic_frame(self, _slot_count: int) -> None:
        return None

    def finish(self) -> None:
        return None

    def release(self) -> None:
        return None


class FakeExportJobs:
    """ExportJobSystem の必須 admission/lifecycle contract。"""

    def __init__(self) -> None:
        self._next_job_id = 1
        self.has_work = False

    def ensure_can_submit(self, _snapshot: FrameExportSnapshot) -> None:
        return None

    @property
    def queue_status(self) -> ExportQueueStatus:
        return ExportQueueStatus(
            request_count=0,
            request_limit=1,
            retained_bytes=0,
            byte_limit=1,
        )

    def submit(self, **_kwargs: object) -> Any:
        job = SimpleNamespace(job_id=self._next_job_id)
        self._next_job_id += 1
        return job

    def poll(self) -> list[ExportJobResult]:
        return []

    def cancel(self, _job_id: int | None = None) -> bool:
        return False

    def close(self) -> None:
        return None


class FakeRecording:
    """VideoRecordingSystem の必須 capture/lifecycle contract。"""

    def __init__(self) -> None:
        self.is_recording = False
        self._t = 0.0
        self._path: Path | None = None

    def start(
        self,
        *,
        output_path: Path,
        framebuffer_size: tuple[int, int],
        t0: float,
        **_kwargs: object,
    ) -> None:
        del framebuffer_size
        self._path = Path(output_path)
        self._t = float(t0)
        self.is_recording = True

    def t(self) -> float:
        return float(self._t)

    def write_frame(self, _screen: object) -> None:
        return None

    def pause_frame(self, _message: str) -> None:
        return None

    def stop(self, *, timeout_s: float | None = None) -> object:
        del timeout_s
        self.is_recording = False
        return SimpleNamespace(
            path=self._path,
            t0=self._t,
            t1=self._t,
            frame_count=0,
            framebuffer_size=(800, 800),
        )


class FakeSceneRunner:
    """SceneRunner の必須 evaluation/lifecycle contract。"""

    def __init__(self) -> None:
        self.last_evaluation_succeeded: bool | None = None
        self.last_evaluation_t: float | None = None
        self.last_realized_t: float | None = None
        self.last_realized_snapshot_revision: int | None = None
        self.last_realized_frame_id: int | None = None
        self.last_output_updated = False
        self.is_waiting_for_fresh_result = False

    def run(self, *args: object, **kwargs: object) -> list[RealizedLayer]:
        t = float(args[0])
        store = kwargs["store"]
        assert isinstance(store, ParamStore)
        self.last_evaluation_succeeded = True
        self.last_evaluation_t = t
        self.last_realized_t = t
        self.last_realized_snapshot_revision = int(store.revision)
        self.last_realized_frame_id = None
        self.last_output_updated = True
        self.is_waiting_for_fresh_result = False
        return []

    def replace_draw(self, _draw_callback: object) -> None:
        return None

    def close(self) -> None:
        return None


def make_draw_window_system(
    *,
    store: ParamStore | None = None,
    monitor: RuntimeMonitor | None = None,
) -> DrawWindowSystem:
    """外部 resource constructorだけを fake にし、実 ``__init__`` を通す。"""

    target_store = ParamStore() if store is None else store
    window = FakeWindow()
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                draw_window_module,
                "create_draw_window",
                return_value=window,
            )
        )
        stack.enter_context(
            patch.object(
                draw_window_module,
                "DrawRenderer",
                side_effect=lambda *_args, **_kwargs: FakeRenderer(),
            )
        )
        stack.enter_context(
            patch.object(
                draw_window_module,
                "ExportJobSystem",
                side_effect=lambda *_args, **_kwargs: FakeExportJobs(),
            )
        )
        stack.enter_context(
            patch.object(
                draw_window_module,
                "VideoRecordingSystem",
                side_effect=lambda *_args, **_kwargs: FakeRecording(),
            )
        )
        stack.enter_context(
            patch.object(
                draw_window_module,
                "SceneRunner",
                side_effect=lambda *_args, **_kwargs: FakeSceneRunner(),
            )
        )
        return DrawWindowSystem(
            _draw,
            options=RenderOptions(),
            render_scale=1.0,
            store=target_store,
            monitor=monitor,
            effective_config=runtime_config(),
        )
