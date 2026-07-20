from pathlib import Path
from typing import Any

import pytest

from grafix.core.runtime_config import (
    output_root_dir,
    runtime_config,
    runtime_config_report,
    runtime_config_with_fallback,
    set_config_path,
)


@pytest.fixture(autouse=True)
def _reset_runtime_config() -> None:
    set_config_path(None)
    yield
    set_config_path(None)


def _isolate_config_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.mark.parametrize("value", (0, 1.0, object()))
def test_set_config_path_rejects_implicit_path_conversion(value: Any) -> None:
    with pytest.raises(TypeError, match="str、Path、None"):
        set_config_path(value)


def test_output_root_dir_uses_packaged_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    assert output_root_dir() == Path("data") / "output"
    cfg = runtime_config()
    assert cfg.config_path is None
    assert cfg.output_dir == Path("data") / "output"
    assert cfg.sketch_dir == Path("sketch")
    assert cfg.font_dirs == (Path("data") / "input" / "font",)
    assert cfg.window_pos_draw == (25, 25)
    assert cfg.window_pos_parameter_gui == (950, 25)
    assert cfg.parameter_gui_window_size == (1100, 1000)
    assert cfg.parameter_gui_fallback_font_japanese is None
    assert cfg.parameter_gui_font_size_base_px == 14.0
    assert dict(cfg.parameter_gui_shortcuts)["play_pause"] == "SPACE"
    assert cfg.png_scale == 8.0
    assert cfg.gcode.travel_feed == 3000.0
    assert cfg.gcode.draw_feed == 3000.0
    assert cfg.gcode.z_up == 3.0
    assert cfg.gcode.z_down == -1.0
    assert cfg.gcode.y_down is True
    assert cfg.gcode.origin == (154.019, 14.195)
    assert cfg.gcode.decimals == 3
    assert cfg.gcode.paper_margin_mm == 2.0
    assert cfg.gcode.bed_x_range is None
    assert cfg.gcode.bed_y_range is None
    assert cfg.gcode.bridge_draw_distance == 0.5
    assert cfg.gcode.optimize_travel is True
    assert cfg.gcode.allow_reverse is True
    assert cfg.gcode.canvas_height_mm is None
    assert cfg.midi_inputs == ()


def test_discovered_config_overrides_packaged_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        'paths:\n  output_dir: "./out_discovered"\n  font_dirs:\n    - "./fonts_discovered"\n',
        encoding="utf-8",
    )

    assert output_root_dir() == discovered.parent / "out_discovered"
    cfg = runtime_config()
    assert cfg.config_path == discovered
    assert cfg.output_dir == discovered.parent / "out_discovered"
    assert cfg.sketch_dir == Path("sketch")
    assert cfg.font_dirs == (discovered.parent / "fonts_discovered",)


def test_discovered_sketch_dir_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        'paths:\n  output_dir: "./out_discovered"\n  sketch_dir: "./sketch"\n  font_dirs:\n    - "./fonts_discovered"\n',
        encoding="utf-8",
    )

    cfg = runtime_config()
    assert cfg.sketch_dir == discovered.parent / "sketch"


def test_discovered_midi_inputs_are_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        'midi:\n  inputs:\n    - port_name: "Grid"\n      mode: "14bit"\n',
        encoding="utf-8",
    )

    cfg = runtime_config()
    assert cfg.midi_inputs == (("Grid", "14bit"),)


def test_parameter_gui_config_values_are_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        "\n".join(
            [
                "paths:",
                '  output_dir: "./out_discovered"',
                "ui:",
                "  window_positions:",
                "    draw: [10, 20]",
                "    parameter_gui: [30, 40]",
                "  parameter_gui:",
                "    window_size: [123, 456]",
                "    fallback_font_japanese: null",
                "    font_size_base_px: 15.0",
                "    shortcuts:",
                "      play_pause: P",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = runtime_config()
    assert cfg.parameter_gui_font_size_base_px == 15.0
    assert dict(cfg.parameter_gui_shortcuts)["play_pause"] == "P"


def test_removed_parameter_table_column_weights_key_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "ui:\n  parameter_gui:\n    table_column_weights: [0.1, 0.2, 0.3, 0.4]\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match="ui\\.parameter_gui\\.table_column_weights"):
        runtime_config()


def test_explicit_config_overrides_discovered_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        'paths:\n  output_dir: "./out_discovered"\n  font_dirs:\n    - "./fonts_discovered"\n',
        encoding="utf-8",
    )

    explicit = tmp_path / "explicit.yaml"
    explicit.write_text(
        'paths:\n  output_dir: "./out_explicit"\n  font_dirs:\n    - "./fonts_discovered"\n',
        encoding="utf-8",
    )
    set_config_path(explicit)

    assert output_root_dir() == explicit.parent / "out_explicit"
    cfg = runtime_config()
    assert cfg.config_path == explicit
    assert cfg.output_dir == explicit.parent / "out_explicit"
    assert cfg.sketch_dir == Path("sketch")
    assert cfg.font_dirs == (explicit.parent / "fonts_discovered",)


def test_environment_variables_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    monkeypatch.setenv("GRAFIX_OUTPUT_DIR", str(tmp_path / "out_env"))
    monkeypatch.setenv("GRAFIX_FONT_DIRS", str(tmp_path / "fonts_env"))

    assert output_root_dir() == Path("data") / "output"
    cfg = runtime_config()
    assert cfg.output_dir == Path("data") / "output"
    assert cfg.sketch_dir == Path("sketch")
    assert cfg.font_dirs == (Path("data") / "input" / "font",)


def test_explicit_config_path_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    missing = tmp_path / "missing.yaml"
    set_config_path(missing)

    with pytest.raises(FileNotFoundError):
        output_root_dir()


def test_partial_export_override_keeps_packaged_gcode_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        "\n".join(
            [
                "export:",
                "  png:",
                "    scale: 8.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg = runtime_config()

    assert cfg.png_scale == 8.0
    assert cfg.gcode.travel_feed == 3000.0
    assert cfg.gcode.optimize_travel is True


def test_partial_gcode_override_keeps_other_packaged_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        "export:\n  gcode:\n    travel_feed: 4321.0\n",
        encoding="utf-8",
    )

    cfg = runtime_config()

    assert cfg.gcode.travel_feed == 4321.0
    assert cfg.gcode.draw_feed == 3000.0
    assert cfg.gcode.optimize_travel is True


def test_missing_gcode_error_matches_recursive_merge_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text("export:\n  gcode: null\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="再帰 merge") as exc_info:
        runtime_config()

    assert "浅い上書き" not in str(exc_info.value)


def test_unknown_key_is_rejected_before_merge_with_nearest_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "paths:\n  outpt_dir: ./renders\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match="paths\\.outpt_dir") as exc_info:
        runtime_config()

    assert "paths.output_dir" in str(exc_info.value)
    assert str(config_path) in str(exc_info.value)


@pytest.mark.parametrize(
    ("yaml_text", "error_match"),
    [
        ("paths:\n  font_dirs: ./fonts\n", "paths\\.font_dirs.*配列"),
        ("paths:\n  font_dirs: [123]\n", "paths\\.font_dirs\\[0\\].*文字列"),
        ('paths:\n  font_dirs: [""]\n', "paths\\.font_dirs\\[0\\].*空でない"),
    ],
)
def test_path_lists_reject_non_list_or_non_string_values(
    yaml_text: str,
    error_match: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match=error_match):
        runtime_config()


@pytest.mark.parametrize("yaml_value", ("1.0", '"1"', "true"))
def test_schema_version_requires_an_integer_without_coercion(
    yaml_value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"version: {yaml_value}\n", encoding="utf-8")
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match="config\\.yaml\\.version.*整数"):
        runtime_config()


@pytest.mark.parametrize("yaml_value", ("3.0", '"3"', "true"))
def test_gcode_decimals_requires_an_integer_without_coercion(
    yaml_value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"export:\n  gcode:\n    decimals: {yaml_value}\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match="export\\.gcode\\.decimals.*整数"):
        runtime_config()


@pytest.mark.parametrize("yaml_value", ("1", '"true"'))
def test_gcode_boolean_requires_a_boolean_without_coercion(
    yaml_value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"export:\n  gcode:\n    y_down: {yaml_value}\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match="export\\.gcode\\.y_down.*bool"):
        runtime_config()


@pytest.mark.parametrize("yaml_value", ('"8.0"', "true"))
def test_float_config_requires_a_real_number_without_coercion(
    yaml_value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"export:\n  png:\n    scale: {yaml_value}\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(RuntimeError, match="export\\.png\\.scale.*数値"):
        runtime_config()


@pytest.mark.parametrize(
    ("yaml_text", "error_match"),
    [
        ("paths:\n  output_dir: 123\n", "paths\\.output_dir.*path 文字列"),
        (
            "ui:\n  parameter_gui:\n    fallback_font_japanese: 123\n",
            "文字列または None",
        ),
        (
            "ui:\n  parameter_gui:\n    shortcuts:\n      play_pause: 1\n",
            "shortcuts\\.play_pause.*pyglet key名",
        ),
    ],
)
def test_path_string_and_shortcut_values_reject_implicit_string_conversion(
    yaml_text: str,
    error_match: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")
    set_config_path(config_path)

    with pytest.raises((RuntimeError, ValueError), match=error_match):
        runtime_config()


def test_integer_yaml_value_is_valid_for_a_real_config_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("export:\n  png:\n    scale: 8\n", encoding="utf-8")
    set_config_path(config_path)

    assert runtime_config().png_scale == 8.0


def test_interactive_fallback_is_explicit_and_cached_for_all_consumers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("paths:\n  outpt_dir: ./renders\n", encoding="utf-8")
    set_config_path(config_path)

    cfg, fallback = runtime_config_with_fallback()

    assert fallback is not None
    assert fallback.source == config_path
    assert "paths.outpt_dir" in fallback.summary
    assert "paths.output_dir" in fallback.details
    assert cfg.config_path is None
    assert cfg.output_dir == Path("data") / "output"
    assert runtime_config() is cfg
    assert runtime_config_report().active_source == "grafix/resource/default_config.yaml"


@pytest.mark.parametrize("value", (".nan", ".inf", "-.inf"))
def test_non_finite_float_is_rejected(
    value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"export:\n  png:\n    scale: {value}\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(ValueError, match="finite"):
        runtime_config()


def test_gcode_range_must_be_in_ascending_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "export:\n  gcode:\n    bed_x_range: [200.0, 10.0]\n",
        encoding="utf-8",
    )
    set_config_path(config_path)

    with pytest.raises(ValueError, match="bed_x_range.*昇順"):
        runtime_config()


def test_positive_float_and_midi_mode_are_strictly_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "export:\n  gcode:\n    travel_feed: 0.0\n",
        encoding="utf-8",
    )
    set_config_path(config_path)
    with pytest.raises(ValueError, match="travel_feed.*正"):
        runtime_config()

    config_path.write_text(
        "midi:\n  inputs:\n    - port_name: Grid\n      mode: 16bit\n",
        encoding="utf-8",
    )
    set_config_path(config_path)
    with pytest.raises(ValueError, match="midi\\.inputs\\[0\\]\\.mode"):
        runtime_config()


def test_config_relative_paths_are_resolved_against_config_parent_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_config_discovery(tmp_path, monkeypatch)
    config_dir = tmp_path / "project" / "settings"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        "paths:\n"
        "  output_dir: ../renders\n"
        "  sketch_dir: ./sketches\n"
        "  preset_module_dirs: [./presets]\n"
        "  font_dirs: [./fonts]\n",
        encoding="utf-8",
    )

    set_config_path(config_path)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    cfg = runtime_config()

    assert cfg.output_dir == config_dir.parent / "renders"
    assert cfg.sketch_dir == config_dir / "sketches"
    assert cfg.preset_module_dirs == (config_dir / "presets",)
    assert cfg.font_dirs == (config_dir / "fonts",)

    output_value = next(
        value for value in runtime_config_report().values if value.key == "paths.output_dir"
    )
    assert output_value.source == str(config_path)
    assert output_value.effective_value == "../renders"
    assert output_value.resolved_path == config_dir.parent / "renders"
