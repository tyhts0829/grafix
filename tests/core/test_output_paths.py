from __future__ import annotations

from pathlib import Path

import pytest

from grafix.core.output_paths import gcode_layer_output_path


def test_gcode_layer_output_path_without_name() -> None:
    base = Path("output/gcode/foo_800x600_v1.gcode")
    assert gcode_layer_output_path(base, layer_index=1, n_layers=12) == Path(
        "output/gcode/foo_800x600_v1_layer001.gcode"
    )
    assert gcode_layer_output_path(base, layer_index=12, n_layers=12) == Path(
        "output/gcode/foo_800x600_v1_layer012.gcode"
    )


def test_gcode_layer_output_path_with_name_sanitize_and_truncate() -> None:
    base = Path("output/gcode/foo.gcode")
    assert gcode_layer_output_path(
        base, layer_index=3, n_layers=3, layer_name="Layer A/B"
    ) == Path("output/gcode/foo_layer003_Layer_A_B.gcode")

    long_name = "a" * 100
    out = gcode_layer_output_path(base, layer_index=1, n_layers=1, layer_name=long_name)
    assert out.name == f"foo_layer001_{'a' * 32}.gcode"


def test_gcode_layer_output_path_name_can_be_omitted_after_sanitize() -> None:
    base = Path("output/gcode/foo.gcode")
    # ASCII 以外は `_` に潰れるため、最終的に空になり得る（その場合は name suffix を省略する）。
    assert gcode_layer_output_path(
        base, layer_index=1, n_layers=1, layer_name="日本語"
    ) == Path("output/gcode/foo_layer001.gcode")


def test_gcode_layer_output_path_index_validation() -> None:
    with pytest.raises(ValueError):
        gcode_layer_output_path(Path("x.gcode"), layer_index=0, n_layers=1)


def test_gcode_layer_output_path_width_grows_for_large_layer_counts() -> None:
    base = Path("output/gcode/foo.gcode")
    assert gcode_layer_output_path(base, layer_index=1, n_layers=1000) == Path(
        "output/gcode/foo_layer0001.gcode"
    )
