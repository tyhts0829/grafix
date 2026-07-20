"""interactive.gl.index_buffer の index と統計の同時計算をテスト。"""

from __future__ import annotations

import numpy as np

from grafix.interactive.gl.index_buffer import build_line_indices_and_stats
from grafix.interactive.gl.line_mesh import LineMesh


def test_build_line_indices_empty() -> None:
    offsets = np.array([0], dtype=np.int32)
    indices, stats = build_line_indices_and_stats(offsets)
    assert indices.dtype == np.uint32
    assert indices.size == 0
    assert stats.draw_vertices == 0
    assert stats.draw_lines == 0


def test_build_line_indices_single_polyline() -> None:
    # 3 vertices => 3 indices
    offsets = np.array([0, 3], dtype=np.int32)
    indices, stats = build_line_indices_and_stats(offsets)
    assert indices.tolist() == [0, 1, 2]
    assert stats.draw_vertices == 3
    assert stats.draw_lines == 1


def test_build_line_indices_multiple_polylines_with_restart() -> None:
    offsets = np.array([0, 3, 5], dtype=np.int32)
    indices, stats = build_line_indices_and_stats(offsets)
    assert indices.tolist() == [
        0,
        1,
        2,
        LineMesh.PRIMITIVE_RESTART_INDEX,
        3,
        4,
    ]
    assert stats.draw_vertices == 5
    assert stats.draw_lines == 2


def test_build_line_indices_skips_short_polylines() -> None:
    # [0, 1) は 1 頂点なのでスキップし、[1, 4) のみ出力される
    offsets = np.array([0, 1, 4], dtype=np.int32)
    indices, stats = build_line_indices_and_stats(offsets)
    assert indices.tolist() == [1, 2, 3]
    assert stats.draw_vertices == 3
    assert stats.draw_lines == 1


def test_build_line_indices_returns_immutable_arrays() -> None:
    offsets1 = np.array([0, 3, 5], dtype=np.int32)
    offsets2 = np.array([0, 3, 5], dtype=np.int32)
    indices1, stats1 = build_line_indices_and_stats(offsets1)
    indices2, stats2 = build_line_indices_and_stats(offsets2)
    np.testing.assert_array_equal(indices1, indices2)
    assert stats1 == stats2
    assert indices1.flags.writeable is False
    assert indices2.flags.writeable is False
