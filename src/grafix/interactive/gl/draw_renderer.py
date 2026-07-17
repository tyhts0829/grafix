# どこで: `src/grafix/interactive/gl/draw_renderer.py`。
# 何を: ライブ描画用の ModernGL レンダラーをカプセル化する。
# なぜ: コンテキスト生成・シェーダ設定・メッシュ転送を `run` から分離し、責務を明確にするため。

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import moderngl
import numpy as np

from grafix.core.parameters.style import line_width_for_short_side
from grafix.core.realize import GeometryCacheKey
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.runtime_limits import RuntimeLimits
from grafix.interactive.gl import utils as render_utils
from grafix.interactive.gl.index_buffer import LineIndexStats, build_line_indices_and_stats
from grafix.interactive.gl.line_mesh import LineMesh
from grafix.interactive.render_settings import RenderSettings
from grafix.interactive.gl.shader import Shader
from grafix.interactive.runtime.diagnostics import DiagnosticCenter, DiagnosticEvent

if TYPE_CHECKING:
    from pyglet.window import Window


_CACHED_MESH_INITIAL_RESERVE = 4096
_CACHED_MESH_BUFFER_GROWTH_FACTOR = LineMesh.BUFFER_GROWTH_FACTOR
_MESH_CANDIDATE_ENTRY_BUDGET_BYTES = 256
_MESH_CANDIDATE_MAX_ENTRIES = 4096


def _mesh_candidate_entry_limit(byte_budget: int) -> int:
    """candidate 用 byte 枠を、metadata の明示的な件数上限へ変換する。"""

    return min(
        _MESH_CANDIDATE_MAX_ENTRIES,
        max(0, int(byte_budget)) // _MESH_CANDIDATE_ENTRY_BUDGET_BYTES,
    )


def _new_mesh_buffer_capacity(required: int) -> int:
    """新規 cache mesh が最初の upload 後に確保する buffer byte 数を返す。"""

    required_bytes = int(required)
    if required_bytes <= _CACHED_MESH_INITIAL_RESERVE:
        return _CACHED_MESH_INITIAL_RESERVE
    return max(
        required_bytes,
        _CACHED_MESH_INITIAL_RESERVE * _CACHED_MESH_BUFFER_GROWTH_FACTOR,
    )


def _aspect_fit_viewport(
    framebuffer_size: tuple[int, int],
    canvas_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """canvas の縦横比を保って framebuffer 中央へ収める viewport を返す。"""

    framebuffer_w = max(1, int(framebuffer_size[0]))
    framebuffer_h = max(1, int(framebuffer_size[1]))
    canvas_w = max(1, int(canvas_size[0]))
    canvas_h = max(1, int(canvas_size[1]))

    # float の aspect 比較ではなく交差積で判定し、
    # 同一 aspect で 1 px の不要な bar が出るのを防ぐ。
    if framebuffer_w * canvas_h >= framebuffer_h * canvas_w:
        viewport_h = framebuffer_h
        viewport_w = max(
            1,
            min(
                framebuffer_w,
                int(round(framebuffer_h * canvas_w / canvas_h)),
            ),
        )
    else:
        viewport_w = framebuffer_w
        viewport_h = max(
            1,
            min(
                framebuffer_h,
                int(round(framebuffer_w * canvas_h / canvas_w)),
            ),
        )

    viewport_x = (framebuffer_w - viewport_w) // 2
    viewport_y = (framebuffer_h - viewport_h) // 2
    return viewport_x, viewport_y, viewport_w, viewport_h


class DrawRenderer:
    """リアルタイム描画を担うシンプルなレンダラー。"""

    def __init__(
        self,
        window: Window,
        settings: RenderSettings,
        *,
        runtime_limits: RuntimeLimits | None = None,
        diagnostic_center: DiagnosticCenter | None = None,
    ) -> None:
        window.switch_to()
        self.ctx = moderngl.create_context(require=410)
        self.program = Shader.create_shader(self.ctx)
        # 動的更新用（キャッシュに乗らないケース）に 1 つだけ使い回す。
        self._scratch_mesh = LineMesh(self.ctx, self.program)
        # 静的ジオメトリ用の GPU メッシュキャッシュ（byte-budget LRU）。
        self._mesh_cache: OrderedDict[GeometryCacheKey, _MeshCacheEntry] = OrderedDict()
        # 初見を即キャッシュすると「毎フレーム別 id」ケースで逆効果になりうるため、
        # 2 回目以降にキャッシュへ昇格させる。
        self._mesh_candidates: OrderedDict[GeometryCacheKey, None] = OrderedDict()
        # scratch IBO に現在入っている topology。offsets を strong reference で
        # 保持し、object identity が一致する場合に限って再利用する。
        self._scratch_topology: _ScratchTopology | None = None
        self._mesh_cache_bytes = 0
        limits = RuntimeLimits() if runtime_limits is None else runtime_limits
        if not isinstance(limits, RuntimeLimits):
            raise TypeError("runtime_limits は RuntimeLimits である必要があります")
        self._diagnostic_center = diagnostic_center
        self._mesh_cache_max_bytes = int(limits.gpu_cache_bytes)
        self._mesh_candidates_max_entries = _mesh_candidate_entry_limit(
            limits.gpu_candidate_cache_bytes
        )
        self._canvas_w, self._canvas_h = settings.canvas_size
        self._framebuffer_size = (1, 1)
        self._viewport = (0, 0, 1, 1)
        self._viewport_size = (1, 1)
        self.program["viewport_size"].value = (1.0, 1.0)
        # 射影行列はキャンバス寸法にのみ依存するため初期化時に一度設定する。
        projection = render_utils.build_projection(
            float(self._canvas_w),
            float(self._canvas_h),
        )
        self.program["projection"].write(projection.tobytes())

    @property
    def mesh_cache_max_bytes(self) -> int:
        """GPU mesh cache の byte 上限を返す。"""

        return int(self._mesh_cache_max_bytes)

    @property
    def mesh_candidate_cache_max_entries(self) -> int:
        """mesh admission candidate の件数上限を返す。"""

        return int(self._mesh_candidates_max_entries)

    def apply_runtime_limits(self, limits: RuntimeLimits) -> None:
        """quality 切替時に GPU cache 上限を適用する。"""

        if not isinstance(limits, RuntimeLimits):
            raise TypeError("limits は RuntimeLimits である必要があります")
        self._mesh_cache_max_bytes = int(limits.gpu_cache_bytes)
        self._mesh_candidates_max_entries = _mesh_candidate_entry_limit(
            limits.gpu_candidate_cache_bytes
        )
        self._evict_meshes_to_budget()
        self._evict_candidates_to_budget()

    def _publish_gpu_cache_limit(
        self,
        *,
        requested: int,
        limit: int,
        reason: str,
        unit: str = "bytes",
    ) -> None:
        center = getattr(self, "_diagnostic_center", None)
        if center is None:
            return
        requested_label = f"requested_{unit}"
        limit_label = f"limit_{unit}"
        center.publish(
            DiagnosticEvent(
                category="resource",
                severity="warning",
                summary=f"GPU cache limit reached: {reason}",
                details=(
                    f"{requested_label}={int(requested)}\n"
                    f"{limit_label}={int(limit)}"
                ),
                dedupe_key=(
                    f"gpu-cache:{reason}:{unit}:{int(requested)}:{int(limit)}"
                ),
            )
        )

    def viewport(self, width: int, height: int) -> None:
        """canvas 比率を保った viewport を framebuffer 中央へ設定する。"""

        framebuffer_size = (max(1, int(width)), max(1, int(height)))
        viewport = _aspect_fit_viewport(
            framebuffer_size,
            (int(self._canvas_w), int(self._canvas_h)),
        )
        size = (int(viewport[2]), int(viewport[3]))
        self._framebuffer_size = framebuffer_size
        self._viewport = viewport
        self.ctx.viewport = viewport
        if size != self._viewport_size:
            self._viewport_size = size
            self.program["viewport_size"].value = (float(size[0]), float(size[1]))

    def clear(self, color: tuple[float, float, float]) -> None:
        """letterbox/pillarbox 領域を含む framebuffer 全体を背景色でクリアする。"""

        framebuffer_w, framebuffer_h = self._framebuffer_size
        self.ctx.clear(
            *color,
            1.0,
            viewport=(0, 0, int(framebuffer_w), int(framebuffer_h)),
        )
        # backend によって clear(viewport=...) が GL viewport を変えても、
        # 後続の mesh draw は aspect-fit 領域に限定する。
        self.ctx.viewport = self._viewport

    def render_layer(
        self,
        realized: RealizedGeometry,
        *,
        cache_key: GeometryCacheKey,
        color: tuple[float, float, float],
        thickness: float,
    ) -> LineIndexStats:
        """RealizedGeometry をライン描画する。"""
        mesh, stats = self.prepare_layer_mesh(realized, cache_key=cache_key)
        if mesh is None:
            return stats
        self.draw_prepared_mesh(mesh, color=color, thickness=thickness)
        return stats

    def prepare_layer_mesh(
        self,
        realized: RealizedGeometry,
        *,
        cache_key: GeometryCacheKey,
    ) -> tuple[LineMesh | None, LineIndexStats]:
        """upload（必要なら）を行い、描画に使う LineMesh を返す。"""
        entry = self._mesh_cache.get(cache_key)
        if entry is not None:
            self._mesh_cache.move_to_end(cache_key)
            return entry.mesh, entry.stats

        was_candidate = cache_key in self._mesh_candidates
        if was_candidate:
            del self._mesh_candidates[cache_key]

        scratch_topology = self._scratch_topology
        topology_hit = (
            scratch_topology is not None
            and scratch_topology.offsets is realized.offsets
        )
        if topology_hit:
            assert scratch_topology is not None
            indices = scratch_topology.indices
            stats = scratch_topology.stats
        else:
            indices, stats = build_line_indices_and_stats(realized.offsets)

        if indices.size == 0:
            if not topology_hit:
                self._scratch_topology = _ScratchTopology(
                    offsets=realized.offsets,
                    indices=indices,
                    stats=stats,
                )
            return None, stats

        if was_candidate:
            mesh = self._promote_mesh(
                realized=realized,
                cache_key=cache_key,
                indices=indices,
                stats=stats,
            )
            if mesh is not None:
                return mesh, stats

        if topology_hit:
            self._scratch_mesh.upload_vertices(realized.coords)
        else:
            self._scratch_mesh.upload(vertices=realized.coords, indices=indices)
            self._scratch_topology = _ScratchTopology(
                offsets=realized.offsets,
                indices=indices,
                stats=stats,
            )

        if not was_candidate:
            self._remember_mesh_candidate(
                cache_key,
                vertices_nbytes=int(realized.coords.nbytes),
                indices_nbytes=int(indices.nbytes),
            )
        return self._scratch_mesh, stats

    def _promote_mesh(
        self,
        *,
        realized: RealizedGeometry,
        cache_key: GeometryCacheKey,
        indices: np.ndarray,
        stats: LineIndexStats,
    ) -> LineMesh | None:
        """2 回目の geometry を専用 GPU mesh へ昇格する。"""

        estimated_bytes = self._new_mesh_byte_size(
            vertices_nbytes=int(realized.coords.nbytes),
            indices_nbytes=int(indices.nbytes),
        )
        if estimated_bytes > self._mesh_cache_max_bytes:
            self._publish_gpu_cache_limit(
                requested=estimated_bytes,
                limit=self._mesh_cache_max_bytes,
                reason="mesh was not cached",
            )
            return None

        # VBO/IBO は別々に必要量まで成長させる。両方を大きい側の
        # サイズで予約すると、頂点だけ巨大な geometry で budget を浪費する。
        mesh = LineMesh(
            self.ctx,
            self.program,
            initial_reserve=_CACHED_MESH_INITIAL_RESERVE,
        )
        mesh.upload(vertices=realized.coords, indices=indices)
        byte_size = int(mesh.vbo.size + mesh.ibo.size)
        if byte_size <= self._mesh_cache_max_bytes:
            self._mesh_cache[cache_key] = _MeshCacheEntry(
                mesh=mesh,
                stats=stats,
                byte_size=byte_size,
            )
            self._mesh_cache_bytes += byte_size
            self._evict_meshes_to_budget()
            return mesh

        self._publish_gpu_cache_limit(
            requested=byte_size,
            limit=self._mesh_cache_max_bytes,
            reason="mesh was not cached",
        )
        mesh.release()
        return None

    def _remember_mesh_candidate(
        self,
        cache_key: GeometryCacheKey,
        *,
        vertices_nbytes: int,
        indices_nbytes: int,
    ) -> None:
        """初見 key だけを、件数上限付き admission set へ記録する。"""

        estimated_bytes = self._new_mesh_byte_size(
            vertices_nbytes=vertices_nbytes,
            indices_nbytes=indices_nbytes,
        )
        if estimated_bytes > self._mesh_cache_max_bytes:
            self._publish_gpu_cache_limit(
                requested=estimated_bytes,
                limit=self._mesh_cache_max_bytes,
                reason="mesh was not cached",
            )
            return
        if self._mesh_candidates_max_entries <= 0:
            return
        self._mesh_candidates[cache_key] = None
        self._evict_candidates_to_budget()

    @staticmethod
    def _new_mesh_byte_size(*, vertices_nbytes: int, indices_nbytes: int) -> int:
        """新規専用 mesh の初回 upload 後の GPU 確保量を見積もる。"""

        return _new_mesh_buffer_capacity(vertices_nbytes) + _new_mesh_buffer_capacity(
            indices_nbytes
        )

    def _evict_meshes_to_budget(self) -> None:
        requested_bytes = self._mesh_cache_bytes
        evicted = 0
        while self._mesh_cache_bytes > self._mesh_cache_max_bytes and self._mesh_cache:
            _, entry = self._mesh_cache.popitem(last=False)
            self._mesh_cache_bytes -= entry.byte_size
            entry.mesh.release()
            evicted += 1
        if evicted:
            self._publish_gpu_cache_limit(
                requested=requested_bytes,
                limit=self._mesh_cache_max_bytes,
                reason=f"evicted {evicted} mesh entrie(s)",
            )

    def _evict_candidates_to_budget(self) -> None:
        while (
            len(self._mesh_candidates) > self._mesh_candidates_max_entries
            and self._mesh_candidates
        ):
            self._mesh_candidates.popitem(last=False)

    def draw_prepared_mesh(
        self,
        mesh: LineMesh,
        *,
        color: tuple[float, float, float],
        thickness: float,
    ) -> None:
        """LineMesh を draw call で描画する。"""
        self.program["line_width_px"].value = line_width_for_short_side(
            thickness,
            (float(self._viewport_size[0]), float(self._viewport_size[1])),
        )
        self.program["color"].value = (*color, 1.0)

        # ボトルネックになりやすい: 多レイヤー/多 draw call 時はここ（ドライバ/GL 呼び出し）が支配しやすい。
        mesh.vao.render(mode=self.ctx.LINE_STRIP, vertices=mesh.index_count)

    def release(self) -> None:
        """GPU リソースを解放する。"""
        self._scratch_topology = None
        self._scratch_mesh.release()
        for entry in self._mesh_cache.values():
            entry.mesh.release()
        self._mesh_cache.clear()
        self._mesh_candidates.clear()
        self._mesh_cache_bytes = 0
        self.program.release()
        self.ctx.release()

    def finish(self) -> None:
        """GPU の完了を待つ（計測用）。"""
        self.ctx.finish()


@dataclass(frozen=True, slots=True)
class _ScratchTopology:
    offsets: np.ndarray
    indices: np.ndarray
    stats: LineIndexStats


@dataclass(frozen=True, slots=True)
class _MeshCacheEntry:
    mesh: LineMesh
    stats: LineIndexStats
    byte_size: int
