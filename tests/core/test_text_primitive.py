from __future__ import annotations

from pathlib import Path

import numpy as np

from grafix.api import G
from grafix.core.font_resolver import resolve_font_path
from grafix.core.primitives import text as text_module
from grafix.core.primitives.text import text as text_impl
from grafix.core.realize import realize


def test_text_empty_returns_empty_geometry() -> None:
    g = G.text(text="", font="GoogleSans-Regular.ttf")
    realized = realize(g)
    assert realized.coords.dtype == np.float32
    assert realized.offsets.dtype == np.int32
    assert realized.coords.shape == (0, 3)
    assert realized.offsets.tolist() == [0]


def test_text_align_shifts_x() -> None:
    left = realize(
        G.text(text="A", font="GoogleSans-Regular.ttf", scale=10.0, text_align="left")
    )
    center = realize(
        G.text(text="A", font="GoogleSans-Regular.ttf", scale=10.0, text_align="center")
    )
    right = realize(
        G.text(text="A", font="GoogleSans-Regular.ttf", scale=10.0, text_align="right")
    )

    assert left.coords.shape[0] > 0
    assert center.coords.shape[0] > 0
    assert right.coords.shape[0] > 0

    min_left = float(left.coords[:, 0].min())
    min_center = float(center.coords[:, 0].min())
    min_right = float(right.coords[:, 0].min())

    assert min_center < min_left
    assert min_right < min_center


def test_text_multiline_increases_y_extent() -> None:
    single = realize(G.text(text="A", font="GoogleSans-Regular.ttf", scale=10.0))
    multi = realize(
        G.text(
            text="A\nA",
            font="GoogleSans-Regular.ttf",
            scale=10.0,
            line_height=1.2,
        )
    )

    assert single.coords.shape[0] > 0
    assert multi.coords.shape[0] > 0

    max_y_single = float(single.coords[:, 1].max())
    max_y_multi = float(multi.coords[:, 1].max())
    assert max_y_multi > max_y_single + 5.0


def test_text_center_translates_coords() -> None:
    base = realize(
        G.text(
            text="A",
            font="GoogleSans-Regular.ttf",
            scale=10.0,
            center=(0.0, 0.0, 0.0),
        )
    )
    shifted = realize(
        G.text(
            text="A",
            font="GoogleSans-Regular.ttf",
            scale=10.0,
            center=(12.5, 7.25, 0.0),
        )
    )

    assert shifted.coords.shape == base.coords.shape
    assert np.allclose(shifted.coords[:, 0], base.coords[:, 0] + 12.5, atol=1e-5)
    assert np.allclose(shifted.coords[:, 1], base.coords[:, 1] + 7.25, atol=1e-5)


def test_text_scale_scales_extent() -> None:
    a = realize(G.text(text="A", font="GoogleSans-Regular.ttf", scale=10.0))
    b = realize(G.text(text="A", font="GoogleSans-Regular.ttf", scale=20.0))

    extent_a_x = float(a.coords[:, 0].max() - a.coords[:, 0].min())
    extent_a_y = float(a.coords[:, 1].max() - a.coords[:, 1].min())
    extent_b_x = float(b.coords[:, 0].max() - b.coords[:, 0].min())
    extent_b_y = float(b.coords[:, 1].max() - b.coords[:, 1].min())

    assert extent_b_x > extent_a_x
    assert extent_b_y > extent_a_y
    assert np.isclose(extent_b_x, extent_a_x * 2.0, rtol=1e-3, atol=1e-4)
    assert np.isclose(extent_b_y, extent_a_y * 2.0, rtol=1e-3, atol=1e-4)


def test_text_quality_increases_point_count() -> None:
    low = realize(
        G.text(text="O", font="GoogleSans-Regular.ttf", scale=10.0, quality=0.0)
    )
    high = realize(
        G.text(text="O", font="GoogleSans-Regular.ttf", scale=10.0, quality=1.0)
    )

    assert high.coords.shape[0] > low.coords.shape[0]


def _polyline_count(realized) -> int:
    return int(realized.offsets.size) - 1


def test_text_box_width_wraps_increases_y_extent() -> None:
    base = realize(
        G.text(text="AAAAA", font="GoogleSans-Regular.ttf", scale=10.0, line_height=1.2)
    )
    off = realize(
        G.text(
            text="AAAAA",
            font="GoogleSans-Regular.ttf",
            scale=10.0,
            line_height=1.2,
            box_width=0.1,
        )
    )
    no_wrap = realize(
        G.text(
            text="AAAAA",
            font="GoogleSans-Regular.ttf",
            scale=10.0,
            line_height=1.2,
            use_bounding_box=True,
        )
    )
    wrapped = realize(
        G.text(
            text="AAAAA",
            font="GoogleSans-Regular.ttf",
            scale=10.0,
            line_height=1.2,
            use_bounding_box=True,
            box_width=0.1,
        )
    )

    assert base.coords.shape[0] > 0
    assert off.coords.shape[0] > 0
    assert no_wrap.coords.shape[0] > 0
    assert wrapped.coords.shape[0] > 0
    assert no_wrap.coords.shape == base.coords.shape
    assert no_wrap.offsets.tolist() == base.offsets.tolist()
    assert np.allclose(no_wrap.coords, base.coords, atol=1e-5)
    assert off.coords.shape == base.coords.shape
    assert off.offsets.tolist() == base.offsets.tolist()
    assert np.allclose(off.coords, base.coords, atol=1e-5)
    assert np.isclose(
        float(off.coords[:, 1].max()), float(base.coords[:, 1].max()), atol=1e-5
    )
    assert float(wrapped.coords[:, 1].max()) > float(no_wrap.coords[:, 1].max()) + 30.0


def test_text_show_bounding_box_adds_lines_even_if_text_empty() -> None:
    empty = realize(G.text(text="", font="GoogleSans-Regular.ttf"))
    boxed_off = realize(
        G.text(
            text="",
            font="GoogleSans-Regular.ttf",
            box_width=50.0,
            box_height=20.0,
            show_bounding_box=True,
        )
    )
    boxed = realize(
        G.text(
            text="",
            font="GoogleSans-Regular.ttf",
            use_bounding_box=True,
            box_width=50.0,
            box_height=20.0,
            show_bounding_box=True,
        )
    )

    assert _polyline_count(empty) == 0
    assert _polyline_count(boxed_off) == 0
    assert _polyline_count(boxed) == 4


def test_text_baseline_is_shifted_by_ascent() -> None:
    base = realize(G.text(text="A", font="GoogleSans-Regular.ttf", scale=100.0))
    toggled = realize(
        G.text(text="A", font="GoogleSans-Regular.ttf", scale=100.0, use_bounding_box=True)
    )

    assert float(base.coords[:, 1].min()) >= -5.0
    assert np.allclose(toggled.coords, base.coords, atol=1e-5)


def test_text_missing_glyph_is_treated_as_space() -> None:
    spaced = realize(G.text(text="A A", font="GoogleSans-Regular.ttf", scale=10.0))
    missing = realize(G.text(text="A日A", font="GoogleSans-Regular.ttf", scale=10.0))

    assert missing.coords.shape == spaced.coords.shape
    assert missing.offsets.tolist() == spaced.offsets.tolist()
    assert np.allclose(missing.coords, spaced.coords, atol=1e-5)


def test_text_raw_results_are_fresh_writable_and_non_sharing() -> None:
    for value in ("HELLO", ""):
        first_coords, first_offsets = text_impl(
            text=value, font="GoogleSans-Regular.ttf"
        )
        second_coords, second_offsets = text_impl(
            text=value, font="GoogleSans-Regular.ttf"
        )

        assert first_coords.flags.writeable
        assert first_offsets.flags.writeable
        assert second_coords.flags.writeable
        assert second_offsets.flags.writeable
        assert not np.shares_memory(first_coords, second_coords)
        assert not np.shares_memory(first_offsets, second_offsets)
        assert np.array_equal(first_coords, second_coords)
        assert np.array_equal(first_offsets, second_offsets)


def test_text_preplacement_glyph_cache_is_bounded_readonly_and_reused() -> None:
    cache = text_module.TEXT_RENDERER._glyph_polyline_cache
    command_cache = text_module.TEXT_RENDERER._glyph_cache
    text_module.TEXT_RENDERER.clear_glyph_caches()

    text_impl(text="ABBA", font="GoogleSans-Regular.ttf", quality=0.5)
    first_values = tuple(cache._od.values())
    first_ids = tuple(id(value) for value in first_values)
    text_impl(
        text="BAAB",
        font="GoogleSans-Regular.ttf",
        quality=0.5,
        center=(10.0, 20.0, 0.0),
        scale=3.0,
    )
    second_values = tuple(cache._od.values())

    try:
        assert 0 < len(cache) <= cache.maxsize
        assert 0 < len(command_cache) <= command_cache.maxsize
        assert cache.maxbytes is not None
        assert cache.byte_size <= cache.maxbytes
        assert set(first_ids) == {id(value) for value in second_values}
        assert all(
            not polyline.flags.writeable
            for glyph in second_values
            for polyline in glyph
        )
    finally:
        text_module.TEXT_RENDERER.clear_glyph_caches()
    assert len(cache) == 0
    assert cache.byte_size == 0
    assert len(command_cache) == 0


def test_text_resolves_an_already_absolute_font_path_only_once(monkeypatch) -> None:
    font_path = resolve_font_path("GoogleSans-Regular.ttf")
    original_resolve = Path.resolve
    calls: list[Path] = []

    def counting_resolve(self: Path, *args, **kwargs):
        calls.append(self)
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting_resolve)
    text_impl(text="ABBA", font=str(font_path), quality=0.5)

    assert len(calls) == 1
