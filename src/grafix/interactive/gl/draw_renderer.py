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
from grafix.interactive.gl import utils as render_utils
from grafix.interactive.gl.index_buffer import LineIndexStats, build_line_indices_and_stats
from grafix.interactive.gl.line_mesh import LineMesh
from grafix.interactive.render_settings import RenderSettings
from grafix.interactive.gl.shader import Shader

if TYPE_CHECKING:
    from pyglet.window import Window


class DrawRenderer:
    """リアルタイム描画を担うシンプルなレンダラー。"""

    def __init__(self, window: Window, settings: RenderSettings) -> None:
        window.switch_to()
        self.ctx = moderngl.create_context(require=410)
        self.program = Shader.create_shader(self.ctx)
        # 動的更新用（キャッシュに乗らないケース）に 1 つだけ使い回す。
        self._scratch_mesh = LineMesh(self.ctx, self.program)
        # 静的ジオメトリ用の GPU メッシュキャッシュ（byte-budget LRU）。
        self._mesh_cache: OrderedDict[GeometryCacheKey, _MeshCacheEntry] = OrderedDict()
        # 初見を即キャッシュすると「毎フレーム別 id」ケースで逆効果になりうるため、
        # 2 回目以降にキャッシュへ昇格させる。
        self._mesh_candidates: OrderedDict[GeometryCacheKey, _IndexCandidate] = OrderedDict()
        self._mesh_cache_bytes = 0
        self._mesh_candidates_bytes = 0
        self._mesh_cache_max_bytes = 256 * 1024 * 1024
        self._mesh_candidates_max_bytes = 64 * 1024 * 1024
        self._canvas_w, self._canvas_h = settings.canvas_size
        self._viewport_size = (1, 1)
        self.program["viewport_size"].value = (1.0, 1.0)
        # 射影行列はキャンバス寸法にのみ依存するため初期化時に一度設定する。
        projection = render_utils.build_projection(
            float(self._canvas_w),
            float(self._canvas_h),
        )
        self.program["projection"].write(projection.tobytes())

    def viewport(self, width: int, height: int) -> None:
        """ビューポートをウィンドウサイズに合わせて更新する。"""
        size = (max(1, int(width)), max(1, int(height)))
        self.ctx.viewport = (0, 0, *size)
        if size != self._viewport_size:
            self._viewport_size = size
            self.program["viewport_size"].value = (float(size[0]), float(size[1]))

    def clear(self, color: tuple[float, float, float]) -> None:
        """背景色でクリアする。"""
        self.ctx.clear(*color, 1.0)

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

        candidate = self._mesh_candidates.pop(cache_key, None)
        if candidate is not None:
            self._mesh_candidates_bytes -= candidate.byte_size
            indices = candidate.indices
            stats = candidate.stats
            # 小さく作って upload 時に VBO/IBO を別々に必要量まで成長させる。
            # 両方を大きい側のサイズで予約すると、頂点だけ巨大な geometry で IBO も
            # 同量確保され、統合 byte budget を無駄に消費する。
            mesh = LineMesh(self.ctx, self.program, initial_reserve=4096)
            mesh.upload(vertices=realized.coords, indices=indices)
            byte_size = int(indices.nbytes + mesh.vbo.size + mesh.ibo.size)
            if byte_size <= self._mesh_cache_max_bytes:
                self._mesh_cache[cache_key] = _MeshCacheEntry(
                    mesh=mesh,
                    indices=indices,
                    stats=stats,
                    byte_size=byte_size,
                )
                self._mesh_cache_bytes += byte_size
                self._evict_meshes_to_budget()
                return mesh, stats

            mesh.release()
            self._scratch_mesh.upload(vertices=realized.coords, indices=indices)
            return self._scratch_mesh, stats

        indices, stats = build_line_indices_and_stats(realized.offsets)
        if indices.size == 0:
            return None, stats

        candidate = _IndexCandidate(
            indices=indices,
            stats=stats,
            byte_size=int(indices.nbytes),
        )
        if candidate.byte_size <= self._mesh_candidates_max_bytes:
            self._mesh_candidates[cache_key] = candidate
            self._mesh_candidates_bytes += candidate.byte_size
            self._evict_candidates_to_budget()

        self._scratch_mesh.upload(vertices=realized.coords, indices=indices)
        return self._scratch_mesh, stats

    def _evict_meshes_to_budget(self) -> None:
        while self._mesh_cache_bytes > self._mesh_cache_max_bytes and self._mesh_cache:
            _, entry = self._mesh_cache.popitem(last=False)
            self._mesh_cache_bytes -= entry.byte_size
            entry.mesh.release()

    def _evict_candidates_to_budget(self) -> None:
        while (
            self._mesh_candidates_bytes > self._mesh_candidates_max_bytes
            and self._mesh_candidates
        ):
            _, candidate = self._mesh_candidates.popitem(last=False)
            self._mesh_candidates_bytes -= candidate.byte_size

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
        self._scratch_mesh.release()
        for entry in self._mesh_cache.values():
            entry.mesh.release()
        self._mesh_cache.clear()
        self._mesh_candidates.clear()
        self._mesh_cache_bytes = 0
        self._mesh_candidates_bytes = 0
        self.program.release()
        self.ctx.release()

    def finish(self) -> None:
        """GPU の完了を待つ（計測用）。"""
        self.ctx.finish()


@dataclass(frozen=True, slots=True)
class _IndexCandidate:
    indices: np.ndarray
    stats: LineIndexStats
    byte_size: int


@dataclass(frozen=True, slots=True)
class _MeshCacheEntry:
    mesh: LineMesh
    indices: np.ndarray
    stats: LineIndexStats
    byte_size: int
