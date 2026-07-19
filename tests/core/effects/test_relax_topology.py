"""relax の topology 構築を高速化前の走査順と exact 比較する。"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from grafix.core.operation_diagnostics import operation_diagnostic_context

relax_module = importlib.import_module("grafix.core.effects.relax")


def _legacy_build_nodes(coords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    index_by_xyz: dict[tuple[float, float, float], int] = {}
    vertex_to_node = np.empty((coords.shape[0],), dtype=np.int64)
    nodes: list[tuple[float, float, float]] = []
    for i in range(int(coords.shape[0])):
        key = (
            float(coords[i, 0]),
            float(coords[i, 1]),
            float(coords[i, 2]),
        )
        index = index_by_xyz.get(key)
        if index is None:
            index = len(nodes)
            index_by_xyz[key] = index
            nodes.append(key)
        vertex_to_node[i] = index
    return np.asarray(nodes, dtype=np.float64), vertex_to_node


def _legacy_build_edges(
    offsets: np.ndarray,
    vertex_to_node: np.ndarray,
) -> np.ndarray:
    edges: set[tuple[int, int]] = set()
    for line_index in range(int(offsets.size) - 1):
        start = int(offsets[line_index])
        stop = int(offsets[line_index + 1])
        for i in range(start, stop - 1):
            a = int(vertex_to_node[i])
            b = int(vertex_to_node[i + 1])
            if a == b:
                continue
            edges.add((a, b) if a < b else (b, a))
    if not edges:
        return np.zeros((0, 2), dtype=np.int64)
    return np.asarray(sorted(edges), dtype=np.int64)


def _legacy_compute_fixed(
    nodes: np.ndarray,
    edges: np.ndarray,
) -> np.ndarray:
    num_nodes = int(nodes.shape[0])
    degrees = np.zeros((num_nodes,), dtype=np.int64)
    adjacency: list[list[int]] = [[] for _ in range(num_nodes)]
    for edge_index in range(int(edges.shape[0])):
        a = int(edges[edge_index, 0])
        b = int(edges[edge_index, 1])
        degrees[a] += 1
        degrees[b] += 1
        adjacency[a].append(b)
        adjacency[b].append(a)

    fixed = degrees != 2
    visited = np.zeros((num_nodes,), dtype=np.bool_)
    stack: list[int] = []
    for start in range(num_nodes):
        if visited[start]:
            continue
        visited[start] = True
        stack.append(start)
        component: list[int] = []
        while stack:
            node_index = stack.pop()
            component.append(node_index)
            for neighbor in adjacency[node_index]:
                if visited[neighbor]:
                    continue
                visited[neighbor] = True
                stack.append(neighbor)

        component_nodes = nodes[np.asarray(component, dtype=np.int64)]
        if component_nodes.shape[0] == 0:
            continue
        for axis in range(3):
            minimum = int(np.argmin(component_nodes[:, axis]))
            maximum = int(np.argmax(component_nodes[:, axis]))
            fixed[component[minimum]] = True
            fixed[component[maximum]] = True
    return fixed.astype(np.bool_, copy=False)


def _random_geometry(
    rng: np.random.Generator,
    case_index: int,
) -> tuple[np.ndarray, np.ndarray]:
    pool_size = int(rng.integers(0, 14))
    pool = rng.normal(size=(max(1, pool_size), 3)).astype(np.float32)
    if pool_size and case_index % 5 == 0:
        pool[0, 0] = np.float32(-0.0)
    if pool_size > 1 and case_index % 7 == 0:
        pool[1, 0] = np.float32(0.0)
    if pool_size and case_index % 11 == 0:
        pool[0, 1] = np.asarray([0x7FC12345], dtype=np.uint32).view(np.float32)[0]

    line_count = int(rng.integers(0, 8))
    counts = rng.integers(0, 8, size=line_count, dtype=np.int32)
    vertex_count = int(counts.sum())
    if vertex_count and pool_size:
        indices = rng.integers(0, pool_size, size=vertex_count)
        coords = pool[indices].copy()
    else:
        coords = np.zeros((vertex_count, 3), dtype=np.float32)

    if case_index % 3 == 1:
        coords = np.asfortranarray(coords)
    elif case_index % 3 == 2:
        coords.setflags(write=False)

    offsets = np.empty((line_count + 1,), dtype=np.int32)
    offsets[0] = 0
    if line_count:
        np.cumsum(counts, out=offsets[1:])
    if case_index % 4 == 0:
        offsets.setflags(write=False)
    return coords, offsets


def test_relax_topology_helpers_match_legacy_bytes() -> None:
    rng = np.random.default_rng(20260719)
    for case_index in range(256):
        coords, offsets = _random_geometry(rng, case_index)
        input_bytes = (coords.tobytes(), offsets.tobytes())

        expected_nodes, expected_mapping = _legacy_build_nodes(coords)
        actual_nodes, actual_mapping = relax_module._build_nodes(coords)
        assert actual_nodes.tobytes() == expected_nodes.tobytes()
        assert actual_nodes.shape == expected_nodes.shape
        assert actual_mapping.tobytes() == expected_mapping.tobytes()

        expected_edges = _legacy_build_edges(offsets, expected_mapping)
        actual_edges = relax_module._build_edges(offsets, actual_mapping)
        assert actual_edges.tobytes() == expected_edges.tobytes()
        assert actual_edges.shape == expected_edges.shape

        expected_fixed = _legacy_compute_fixed(
            expected_nodes,
            expected_edges,
        )
        actual_fixed = relax_module._compute_fixed(
            actual_nodes,
            actual_edges,
        )
        assert actual_fixed.tobytes() == expected_fixed.tobytes()
        assert (coords.tobytes(), offsets.tobytes()) == input_bytes


def test_relax_python_list_fast_paths_have_explicit_scratch_caps() -> None:
    budget = relax_module._PYTHON_LIST_SCRATCH_BUDGET_BYTES
    assert budget == 8 * 1024 * 1024
    assert (
        relax_module._PYTHON_SCALAR_LIST_ITEM_LIMIT
        * relax_module._PYTHON_SCALAR_LIST_ITEM_BYTES
        <= budget
    )
    assert (
        relax_module._PYTHON_EDGE_LIST_ROW_LIMIT
        * relax_module._PYTHON_EDGE_LIST_ROW_BYTES
        <= budget
    )
    assert 3 * 9_800 <= relax_module._PYTHON_SCALAR_LIST_ITEM_LIMIT


def test_relax_node_builder_switches_at_bounded_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_scan = relax_module._build_nodes_list_scan
    array_scan = relax_module._build_nodes_array_scan
    calls: list[str] = []

    def observed_list_scan(
        coords: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        calls.append("list")
        return list_scan(coords)

    def observed_array_scan(
        coords: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        calls.append("array")
        return array_scan(coords)

    monkeypatch.setattr(relax_module, "_build_nodes_list_scan", observed_list_scan)
    monkeypatch.setattr(relax_module, "_build_nodes_array_scan", observed_array_scan)

    maximum_fast_vertices = (
        relax_module._PYTHON_SCALAR_LIST_ITEM_LIMIT // 3
    )
    for vertex_count, expected_path in (
        (maximum_fast_vertices, "list"),
        (maximum_fast_vertices + 1, "array"),
    ):
        coords = np.zeros((vertex_count, 3), dtype=np.float32)
        expected = _legacy_build_nodes(coords)
        actual = relax_module._build_nodes(coords)
        assert actual[0].tobytes() == expected[0].tobytes()
        assert actual[1].tobytes() == expected[1].tobytes()
        assert calls.pop() == expected_path


def test_relax_edge_builder_switches_at_bounded_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_scan = relax_module._build_edges_list_scan
    array_scan = relax_module._build_edges_array_scan
    calls: list[str] = []

    def observed_list_scan(
        offsets: np.ndarray,
        vertex_to_node: np.ndarray,
    ) -> np.ndarray:
        calls.append("list")
        return list_scan(offsets, vertex_to_node)

    def observed_array_scan(
        offsets: np.ndarray,
        vertex_to_node: np.ndarray,
    ) -> np.ndarray:
        calls.append("array")
        return array_scan(offsets, vertex_to_node)

    monkeypatch.setattr(relax_module, "_build_edges_list_scan", observed_list_scan)
    monkeypatch.setattr(relax_module, "_build_edges_array_scan", observed_array_scan)

    offsets = np.asarray([0, 0], dtype=np.int32)
    maximum_fast_vertices = (
        relax_module._PYTHON_SCALAR_LIST_ITEM_LIMIT - offsets.size
    )
    for vertex_count, expected_path in (
        (maximum_fast_vertices, "list"),
        (maximum_fast_vertices + 1, "array"),
    ):
        mapping = np.arange(vertex_count, dtype=np.int64) % 2
        line_offsets = np.asarray([0, vertex_count], dtype=np.int32)
        expected = _legacy_build_edges(line_offsets, mapping)
        actual = relax_module._build_edges(line_offsets, mapping)
        assert actual.tobytes() == expected.tobytes()
        assert calls.pop() == expected_path


def test_relax_adjacency_and_visited_switch_at_bounded_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_scan = relax_module._build_adjacency_list_scan
    array_scan = relax_module._build_adjacency_array_scan
    calls: list[str] = []

    def observed_list_scan(
        num_nodes: int,
        edges: np.ndarray,
    ) -> list[list[int]]:
        calls.append("list")
        return list_scan(num_nodes, edges)

    def observed_array_scan(
        num_nodes: int,
        edges: np.ndarray,
    ) -> list[list[int]]:
        calls.append("array")
        return array_scan(num_nodes, edges)

    monkeypatch.setattr(
        relax_module,
        "_build_adjacency_list_scan",
        observed_list_scan,
    )
    monkeypatch.setattr(
        relax_module,
        "_build_adjacency_array_scan",
        observed_array_scan,
    )

    limit = relax_module._PYTHON_EDGE_LIST_ROW_LIMIT
    for edge_count, expected_path in ((limit, "list"), (limit + 1, "array")):
        edges = np.column_stack(
            (
                np.arange(edge_count, dtype=np.int64),
                np.arange(1, edge_count + 1, dtype=np.int64),
            )
        )
        adjacency = relax_module._build_adjacency(edge_count + 1, edges)
        assert adjacency[0] == [1]
        assert adjacency[-1] == [edge_count - 1]
        assert calls.pop() == expected_path

    visited_limit = relax_module._PYTHON_VISITED_LIST_NODE_LIMIT
    assert isinstance(relax_module._build_visited(visited_limit), list)
    assert isinstance(
        relax_module._build_visited(visited_limit + 1),
        np.ndarray,
    )


@pytest.mark.parametrize(
    ("coords", "offsets"),
    [
        (
            np.asarray(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 1.0, 0.0],
                    [2.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
            np.asarray([0, 4], dtype=np.int32),
        ),
        (
            np.asarray(
                [
                    [-0.0, 0.0, 0.0],
                    [1.0, 2.0, 0.0],
                    [2.0, 0.0, 0.0],
                    [10.0, 0.0, 0.0],
                    [11.0, -2.0, 0.0],
                    [12.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
            np.asarray([0, 3, 6], dtype=np.int32),
        ),
        (
            np.asarray(
                [[-0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                dtype=np.float32,
            ),
            np.asarray([0, 1, 2], dtype=np.int32),
        ),
        (
            np.asarray(
                [
                    [0x80000000, 0x00000000, 0x7FC12345],
                    [0x00000000, 0x80000000, 0x7FC12345],
                    [0x3F800000, 0x00000000, 0x00000000],
                    [0x40000000, 0x80000000, 0x00000000],
                ],
                dtype=np.uint32,
            ).view(np.float32),
            np.asarray([0, 4], dtype=np.int32),
        ),
    ],
)
def test_relax_end_to_end_matches_legacy_topology(
    monkeypatch: pytest.MonkeyPatch,
    coords: np.ndarray,
    offsets: np.ndarray,
) -> None:
    input_bytes = (coords.tobytes(), offsets.tobytes())
    with operation_diagnostic_context() as actual_diagnostics:
        actual = relax_module.relax(
            (coords, offsets),
            relaxation_iterations=3,
            step=0.125,
        )

    monkeypatch.setattr(relax_module, "_build_nodes", _legacy_build_nodes)
    monkeypatch.setattr(relax_module, "_build_edges", _legacy_build_edges)
    monkeypatch.setattr(relax_module, "_compute_fixed", _legacy_compute_fixed)
    with operation_diagnostic_context() as expected_diagnostics:
        expected = relax_module.relax(
            (coords, offsets),
            relaxation_iterations=3,
            step=0.125,
        )

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()
    assert (actual[0] is coords, actual[1] is offsets) == (
        expected[0] is coords,
        expected[1] is offsets,
    )
    assert actual_diagnostics.snapshot() == expected_diagnostics.snapshot()
    assert (coords.tobytes(), offsets.tobytes()) == input_bytes


def test_relax_duplicate_heavy_fallback_keeps_peak_rss_bounded() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    script = """
import json
import resource
import sys

import numpy as np

from grafix.core.effects.relax import relax

n_vertices = 1_000_000
coords = np.zeros((n_vertices, 3), dtype=np.float32)
offsets = np.arange(n_vertices + 1, dtype=np.int32)

def peak_rss_bytes():
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024

before = peak_rss_bytes()
out_coords, out_offsets = relax(
    (coords, offsets),
    relaxation_iterations=1,
    step=0.125,
)
after = peak_rss_bytes()
print(json.dumps({
    "delta": max(0, after - before),
    "coords_identity": out_coords is coords,
    "offsets_identity": out_offsets is offsets,
}))
"""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(repository_root / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=60.0,
        env=environment,
    )
    payload = json.loads(completed.stdout)
    assert payload["coords_identity"] is True
    assert payload["offsets_identity"] is True
    assert payload["delta"] < 64 * 1024 * 1024
