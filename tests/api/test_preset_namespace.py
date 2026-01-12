from __future__ import annotations

from pathlib import Path

import pytest

from grafix import P
from grafix.core.parameters import ParamStore
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.runtime_config import set_config_path


def _write_config(*, path: Path, preset_module_dir: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "paths:",
                '  output_dir: "data/output"',
                "  preset_module_dirs:",
                f'    - "{preset_module_dir.as_posix()}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_preset_namespace_autoload_raises_on_duplicate_name(tmp_path: Path) -> None:
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir(parents=True, exist_ok=True)

    (preset_dir / "a.py").write_text(
        "\n".join(
            [
                "from grafix.api import preset",
                "",
                '@preset(meta={\"x\": {\"kind\": \"float\"}})',
                "def dup_logo(*, x: float = 1.0, name=None, key=None):",
                "    return float(x)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (preset_dir / "b.py").write_text(
        "\n".join(
            [
                "from grafix.api import preset",
                "",
                '@preset(meta={\"x\": {\"kind\": \"float\"}})',
                "def dup_logo(*, x: float = 2.0, name=None, key=None):",
                "    return float(x)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg_path = tmp_path / "config.yaml"
    _write_config(path=cfg_path, preset_module_dir=preset_dir)

    set_config_path(cfg_path)
    try:
        with pytest.raises(ValueError, match=r"dup_logo"):
            _ = P.dup_logo
    finally:
        set_config_path(None)


def test_preset_namespace_autoload_makes_preset_available(tmp_path: Path) -> None:
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir(parents=True, exist_ok=True)

    (preset_dir / "ok.py").write_text(
        "\n".join(
            [
                "from grafix.api import preset",
                "",
                '@preset(meta={\"x\": {\"kind\": \"float\"}})',
                "def ok_logo(*, x: float = 1.0, name=None, key=None):",
                "    return ('ok', float(x))",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg_path = tmp_path / "config.yaml"
    _write_config(path=cfg_path, preset_module_dir=preset_dir)

    set_config_path(cfg_path)
    try:
        fn = P.ok_logo
        assert fn(x=2.0) == ("ok", 2.0)

        store = ParamStore()
        with parameter_context(store=store, cc_snapshot=None):
            _ = fn(x=3.0)

        snap = store_snapshot(store)
        ok_args = {k.arg for k in snap.keys() if k.op == "preset.ok_logo"}
        assert ok_args == {"bypass", "x"}
    finally:
        set_config_path(None)
