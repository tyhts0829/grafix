from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import grafix.api.presets as presets_module
import grafix.core.preset_registry as preset_registry_module
from grafix import P
from grafix.api import preset
from grafix.core.geometry import Geometry
from grafix.core.parameters import ParamStore
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.preset_registry import PresetRegistry
from grafix.core.runtime_config import runtime_config, set_config_path


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
                "def dup_logo(*, x: float = 1.0) -> Geometry:",
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
                "def dup_logo(*, x: float = 2.0) -> Geometry:",
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
                "def ok_logo(*, x: float = 1.0) -> Geometry:",
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


def test_preset_autoload_skips_source_already_loaded_under_an_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir(parents=True, exist_ok=True)
    module_path = preset_dir / "direct_demo.py"
    module_path.write_text(
        "\n".join(
            [
                "from grafix.api import preset",
                "from grafix.core.geometry import Geometry",
                "",
                '@preset(meta={"x": {"kind": "float"}})',
                "def direct_demo(*, x: float = 1.0) -> Geometry:",
                "    return Geometry.create(op='concat', params={'x': float(x)})",
                "",
            ]
        ),
        encoding="utf-8",
    )

    isolated = PresetRegistry()
    monkeypatch.setattr(preset_registry_module, "preset_registry", isolated)
    monkeypatch.setattr(presets_module, "_AUTOLOAD_KEY", None)

    spec = importlib.util.spec_from_file_location(
        "direct_preset_demo",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert isolated.revision == 1

    cfg_path = tmp_path / "config.yaml"
    _write_config(path=cfg_path, preset_module_dir=preset_dir)
    set_config_path(cfg_path)
    try:
        presets_module._autoload_preset_modules(runtime_config())
    finally:
        set_config_path(None)

    assert isolated.revision == 1
    assert isolated["preset.direct_demo"].func is module.direct_demo


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
    assert any(site_id.endswith("|int:1") for site_id in site_ids)


def test_preset_namespace_rejects_positional_identity() -> None:
    with pytest.raises(TypeError, match="positional"):
        P("Custom")  # type: ignore[misc]


@pytest.mark.parametrize("reserved_name", ["name", "key", "instance_key", "shared"])
def test_preset_namespace_rejects_identity_as_direct_preset_kwargs(
    reserved_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preset_registry_module,
        "preset_registry",
        PresetRegistry(),
    )

    @preset(meta={"x": {"kind": "float"}})
    def b_only_direct_rejection(*, x: float = 1.0) -> Geometry:
        return Geometry.create(op="concat", params={"x": float(x)})

    with pytest.raises(
        TypeError,
        match=f"unexpected keyword argument '{reserved_name}'",
    ):
        P.b_only_direct_rejection(x=2.0, **{reserved_name: "reserved"})


@pytest.mark.parametrize("reserved_name", ["name", "key", "instance_key", "shared", "activate"])
def test_preset_rejects_every_reserved_name_in_original_signature(
    reserved_name: str,
) -> None:
    namespace: dict[str, object] = {}
    exec(
        "def invalid_reserved(*, " + reserved_name + "=None):\n"
        "    return Geometry.create(op='concat')\n",
        {"Geometry": Geometry},
        namespace,
    )

    with pytest.raises(ValueError, match=reserved_name):
        preset(meta={})(namespace["invalid_reserved"])  # type: ignore[arg-type]


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
    assert isolated["preset.duplicate_contract"].func is original
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
    assert isolated["preset.duplicate_contract"].func is original


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


def test_preset_decorator_rejects_empty_callable_name() -> None:
    def unnamed() -> Geometry:
        return Geometry.create(op="concat")

    unnamed.__name__ = ""
    with pytest.raises(ValueError, match="空でない文字列"):
        preset(meta={})(unnamed)


def test_preset_namespace_passes_one_resolved_config_to_autoload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = object()
    observed: list[object] = []
    monkeypatch.setattr(
        preset_registry_module,
        "preset_registry",
        PresetRegistry(),
    )
    monkeypatch.setattr(presets_module, "runtime_config", lambda: config)
    monkeypatch.setattr(
        presets_module,
        "_autoload_preset_modules",
        lambda cfg: observed.append(cfg),
    )

    with pytest.raises(AttributeError, match="missing_config_contract"):
        _ = P.missing_config_contract

    assert observed == [config]
