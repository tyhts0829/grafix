from __future__ import annotations

from typing import Any

import pytest

from grafix.interactive.gl.line_mesh import LineMesh


class _Buffer:
    def __init__(self, size: int) -> None:
        self.size = int(size)
        self.released = False

    def release(self) -> None:
        self.released = True


class _VertexArray:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _Context:
    def __init__(self) -> None:
        self.buffers: list[_Buffer] = []
        self.vertex_arrays: list[_VertexArray] = []
        self.fail_reserve: int | None = None
        self.primitive_restart = False
        self.primitive_restart_index = 0

    def buffer(self, *, reserve: int, dynamic: bool) -> _Buffer:
        assert dynamic is True
        if self.fail_reserve == reserve:
            raise RuntimeError("allocation failed")
        buffer = _Buffer(reserve)
        self.buffers.append(buffer)
        return buffer

    def simple_vertex_array(
        self,
        program: Any,
        vbo: _Buffer,
        attribute: str,
        *,
        index_buffer: _Buffer,
    ) -> _VertexArray:
        assert program is not None
        assert attribute == "in_vert"
        assert not vbo.released
        assert not index_buffer.released
        vao = _VertexArray()
        self.vertex_arrays.append(vao)
        return vao


def test_line_mesh_uses_geometric_buffer_growth() -> None:
    context = _Context()
    mesh = LineMesh(context, object(), initial_reserve=8)

    mesh._ensure_capacity(9, 9)
    assert mesh.vbo.size == 16
    assert mesh.ibo.size == 16
    mesh._ensure_capacity(10, 10)
    assert mesh.vbo.size == 16
    assert mesh.ibo.size == 16
    mesh._ensure_capacity(17, 17)
    assert mesh.vbo.size == 32
    assert mesh.ibo.size == 32
    mesh._ensure_capacity(33, 33)
    assert mesh.vbo.size == 64
    assert mesh.ibo.size == 64

    assert len(context.buffers) == 8
    assert len(context.vertex_arrays) == 4


def test_line_mesh_rebuilds_vao_once_when_both_buffers_grow() -> None:
    context = _Context()
    mesh = LineMesh(context, object(), initial_reserve=8)
    original_vao = mesh.vao

    mesh._ensure_capacity(9, 9)

    assert original_vao.released is True
    assert len(context.vertex_arrays) == 2


def test_line_mesh_grows_vertex_and_index_buffers_independently() -> None:
    context = _Context()
    mesh = LineMesh(context, object(), initial_reserve=8)

    mesh._ensure_capacity(33, 9)

    assert mesh.vbo.size == 33
    assert mesh.ibo.size == 16
    assert len(context.vertex_arrays) == 2


def test_line_mesh_keeps_old_resources_when_allocation_fails() -> None:
    context = _Context()
    mesh = LineMesh(context, object(), initial_reserve=8)
    original_vbo = mesh.vbo
    original_ibo = mesh.ibo
    original_vao = mesh.vao
    context.fail_reserve = 16

    with pytest.raises(RuntimeError, match="allocation failed"):
        mesh._ensure_capacity(9, 1)

    assert mesh.vbo is original_vbo
    assert mesh.ibo is original_ibo
    assert mesh.vao is original_vao
    assert original_vbo.released is False
    assert original_ibo.released is False
    assert original_vao.released is False
