from __future__ import annotations

from pathlib import Path

import pytest

import grafix.core.preset_registry as preset_registry_module
from grafix import P
from grafix.api import preset
from grafix.core.geometry import Geometry
from grafix.core.parameters import ParamStore
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.preset_registry import PresetRegistry
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
                "from grafix.core.geometry import Geometry",
                "",
                '@preset(meta={"x": {"kind": "float"}})',
                "def dup_logo(*, x: float = 1.0, name=None, key=None) -> Geometry:",
                "    return Geometry.create(op='concat')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (preset_dir / "b.py").write_text(
        "\n".join(
            [
                "from grafix.api import preset",
                "from grafix.core.geometry import Geometry",
                "",
                '@preset(meta={"x": {"kind": "float"}})',
                "def dup_logo(*, x: float = 2.0, name=None, key=None) -> Geometry:",
                "    return Geometry.create(op='concat')",
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
                "from grafix.core.geometry import Geometry",
                "",
                '@preset(meta={"x": {"kind": "float"}})',
                "def ok_logo(*, x: float = 1.0, name=None, key=None) -> Geometry:",
                "    return Geometry.create(op='concat', params={'x': float(x)})",
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
        out = fn(x=2.0)
        assert isinstance(out, Geometry)
        assert dict(out.args)["x"] == 2.0

        store = ParamStore()
        with parameter_context(store=store, cc_snapshot=None):
            _ = fn(x=3.0)

        snap = store_snapshot(store)
        ok_args = {k.arg for k in snap.keys() if k.op == "preset.ok_logo"}
        assert ok_args == {"activate", "x"}
    finally:
        set_config_path(None)


def test_preset_namespace_supports_p_call_name_without_signature() -> None:
    @preset(meta={"x": {"kind": "float"}})
    def b_only_sample(*, x: float = 1.0) -> Geometry:
        return Geometry.create(op="concat", params={"x": float(x)})

    store = ParamStore()
    with parameter_context(store=store, cc_snapshot=None):
        out = P(name="Custom", key=1).b_only_sample(x=3.0)

    assert isinstance(out, Geometry)
    assert dict(out.args)["x"] == 3.0

    snap = store_snapshot(store)
    labels = {
        label
        for k, (_meta, _state, _ordinal, label) in snap.items()
        if k.op == "preset.b_only_sample"
    }
    assert labels == {"Custom"}

    site_ids = {k.site_id for k in snap.keys() if k.op == "preset.b_only_sample"}
    assert any(str(site_id).endswith("|1") for site_id in site_ids)


def test_preset_registration_is_single_revision_and_duplicate_is_non_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated = PresetRegistry()
    monkeypatch.setattr(preset_registry_module, "preset_registry", isolated)

    @preset(meta={"amount": {"kind": "float"}})
    def duplicate_contract(amount: float = 1.0) -> Geometry:
        return Geometry.create(op="concat", params={"amount": amount})

    original = duplicate_contract
    original_spec = dict(isolated.items())["preset.duplicate_contract"]
    assert isolated.revision == 1
    assert isolated.get("duplicate_contract") is original
    assert P.duplicate_contract is original

    def invalid_duplicate_contract() -> Geometry:
        return Geometry.create(op="concat")

    invalid_duplicate_contract.__name__ = "duplicate_contract"
    with pytest.raises(
        ValueError,
        match=r"^preset 'duplicate_contract' は既に登録されている$",
    ):
        preset(meta={"missing": {"kind": "float"}})(invalid_duplicate_contract)

    assert isolated.revision == 1
    assert dict(isolated.items())["preset.duplicate_contract"] is original_spec
    assert isolated.get("duplicate_contract") is original


def test_preset_namespace_unknown_error_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preset_registry_module,
        "preset_registry",
        PresetRegistry(),
    )

    with pytest.raises(
        AttributeError,
        match=r"^未登録の preset: 'missing_contract'$",
    ):
        _ = P.missing_contract
