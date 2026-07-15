from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from grafix.core.output_paths import VersionedPathAllocator, gcode_layer_output_path


def test_versioned_path_allocator_keeps_existing_and_reserved_paths(tmp_path: Path) -> None:
    base = tmp_path / "capture.png"
    numbered = tmp_path / "capture_001.png"
    base.write_bytes(b"previous-base")
    numbered.write_bytes(b"previous-001")

    allocator = VersionedPathAllocator()
    first = allocator.allocate(base)
    second = allocator.allocate(base)

    assert first == tmp_path / "capture_002.png"
    assert second == tmp_path / "capture_003.png"
    assert base.read_bytes() == b"previous-base"
    assert numbered.read_bytes() == b"previous-001"
    # 予約は export 完了前の衝突だけを防ぎ、偽の成果物は作らない。
    assert not first.exists()
    assert not second.exists()


def test_versioned_path_allocator_is_thread_safe_for_rapid_submit(tmp_path: Path) -> None:
    base = tmp_path / "capture.svg"
    allocator = VersionedPathAllocator()

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(lambda _index: allocator.allocate(base), range(32)))

    assert len(set(paths)) == 32
    assert set(paths) == {
        base,
        *(tmp_path / f"capture_{index:03d}.svg" for index in range(1, 32)),
    }


def test_versioned_path_allocator_normalizes_relative_reservations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    allocator = VersionedPathAllocator()

    relative = allocator.allocate(Path("capture.gcode"))
    absolute = allocator.allocate(tmp_path / "capture.gcode")

    assert relative == Path("capture.gcode")
    assert absolute == tmp_path / "capture_001.gcode"


def test_versioned_path_allocator_validates_configuration() -> None:
    with pytest.raises(ValueError, match="minimum_digits"):
        VersionedPathAllocator(minimum_digits=0)

    allocator = VersionedPathAllocator()
    with pytest.raises(ValueError, match="ファイル名"):
        allocator.allocate(Path("."))


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
