from __future__ import annotations

from pathlib import Path

from grafix.core.runtime_config import set_config_path
from grafix.devtools.generate_stub import generate_stubs_str


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


def test_generate_stub_lists_user_presets_on_p(tmp_path: Path) -> None:
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir(parents=True, exist_ok=True)

    (preset_dir / "user.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from pathlib import Path",
                "",
                "from grafix.api import preset",
                "",
                "meta = {\"out\": {\"kind\": \"str\"}}",
                "",
                "@preset(meta=meta)",
                "def stubgen_path(*, out: Path = Path('out'), name=None, key=None) -> Path:",
                "    return out",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cfg_path = tmp_path / "config.yaml"
    _write_config(path=cfg_path, preset_module_dir=preset_dir)

    set_config_path(cfg_path)
    try:
        stub = generate_stubs_str()
    finally:
        set_config_path(None)

    assert (
        "def stubgen_path(self, *, bypass: bool = ..., out: Path = ...) -> Path:"
        in stub
    )
