from __future__ import annotations

import sys
from pathlib import Path

import pytest

from grafix.core.font_resolver import (
    DEFAULT_FONT_FILENAME,
    _search_dirs,
    _system_font_dirs,
    default_font_path,
    list_font_choices,
    resolve_font_path,
)
from grafix.core.runtime_config import set_config_path


def test_default_font_path_exists() -> None:
    path = default_font_path()
    assert isinstance(path, Path)
    assert path.is_file()
    assert path.name == DEFAULT_FONT_FILENAME


def test_list_font_choices_contains_default() -> None:
    choices = list_font_choices()
    assert any(value == DEFAULT_FONT_FILENAME for _stem, value, _is_ttc, _search_key in choices)


def test_resolve_font_path_respects_priority_explicit_path_over_config(tmp_path) -> None:
    bundled = default_font_path()

    # config font dir（同名のフォントを置く）
    font_dir = tmp_path / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    copied = font_dir / DEFAULT_FONT_FILENAME
    copied.write_bytes(bundled.read_bytes())

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "version: 1",
                "paths:",
                '  output_dir: "data/output"',
                "  font_dirs:",
                f'    - "{font_dir}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    set_config_path(cfg_path)
    try:
        # 1) name 指定は config の font_dirs が優先される
        assert resolve_font_path(DEFAULT_FONT_FILENAME) == copied.resolve()

        # 2) 実在パスは config より優先される
        assert resolve_font_path(str(bundled)) == bundled.resolve()
    finally:
        set_config_path(None)


def test_system_font_dirs_returns_platform_paths() -> None:
    dirs = _system_font_dirs()
    assert len(dirs) >= 2
    if sys.platform == "darwin":
        assert Path("/System/Library/Fonts") in dirs
        assert Path("/Library/Fonts") in dirs
    elif sys.platform == "win32":
        assert any("Windows" in str(d) for d in dirs)


def test_search_dirs_includes_system_font_dirs() -> None:
    set_config_path(None)
    try:
        dirs = _search_dirs()
        system_dirs = {d for d in _system_font_dirs() if d.is_dir()}
        assert system_dirs.issubset(set(dirs)), (
            f"system font dirs {system_dirs} not found in search dirs {dirs}"
        )
    finally:
        set_config_path(None)


def test_resolve_font_in_system_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A font placed in a system font dir resolves by filename."""
    import grafix.core.font_resolver as fm

    fake_sys = tmp_path / "sys_fonts"
    fake_sys.mkdir()
    font_file = fake_sys / "FakeSystemFont.ttf"
    font_file.write_bytes(b"\x00" * 16)

    monkeypatch.setattr(fm, "_system_font_dirs", lambda: (fake_sys,))
    fm._FONT_FILES_CACHE.clear()
    fm._FONT_CHOICES_CACHE.clear()

    set_config_path(None)
    try:
        resolved = resolve_font_path("FakeSystemFont.ttf")
        assert resolved == font_file.resolve()
    finally:
        fm._FONT_FILES_CACHE.clear()
        fm._FONT_CHOICES_CACHE.clear()
        set_config_path(None)


def test_resolve_font_path_error_message_contains_hints() -> None:
    set_config_path(None)
    try:
        try:
            resolve_font_path("___no_such_font___")
        except FileNotFoundError as exc:
            msg = str(exc)
            assert "searched_dirs=" in msg
            assert "font_dirs:" in msg
        else:  # pragma: no cover
            raise AssertionError("resolve_font_path は FileNotFoundError を送出する必要がある")
    finally:
        set_config_path(None)
