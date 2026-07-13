from __future__ import annotations

from grafix.interactive.gl.shader import Shader


def test_line_geometry_shader_uses_pixel_space_normal_and_skips_zero_segments() -> None:
    source = Shader.GEOMETRY_SHADER

    assert "uniform vec2 viewport_size" in source
    assert "uniform float line_width_px" in source
    assert "delta_px" in source
    assert "segment_length_px <= 1e-6" in source
    assert "line_width_px / viewport_size" in source
