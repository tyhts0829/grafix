"""first-party parameter の Help Description が欠落しないことを検証する。"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from grafix.core.builtins import ensure_builtin_ops_registered
from grafix.core.effect_registry import effect_registry
from grafix.core.parameters import ParamStore
from grafix.core.parameters.layer_style import (
    LAYER_STYLE_COLOR_META,
    LAYER_STYLE_LINE_COLOR,
    LAYER_STYLE_LINE_THICKNESS,
    LAYER_STYLE_OP,
    LAYER_STYLE_THICKNESS_META,
)
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.style import (
    STYLE_BACKGROUND_COLOR,
    STYLE_GLOBAL_LINE_COLOR,
    STYLE_GLOBAL_THICKNESS,
    STYLE_OP,
    style_key,
)
from grafix.core.parameters.style_ops import ensure_style_entries
from grafix.core.preset_registry import PresetRegistry
from grafix.core.primitive_registry import primitive_registry


def _has_description(meta: ParamMeta | None) -> bool:
    """meta が空でない Description を持つか返す。"""

    return meta is not None and isinstance(meta.description, str) and bool(meta.description.strip())


def test_builtin_operation_parameter_descriptions_are_complete() -> None:
    """組み込み primitive/effect は activate を含む全行に説明を持つ。"""

    ensure_builtin_ops_registered()
    registry_specs = (
        (
            primitive_registry,
            "grafix.core.primitives.",
        ),
        (
            effect_registry,
            "grafix.core.effects.",
        ),
    )

    missing: list[str] = []
    first_party_count = 0
    for registry, provenance_prefix in registry_specs:
        for operation, spec in registry.items():
            if not spec.provenance.startswith(provenance_prefix):
                continue
            first_party_count += 1
            if "activate" not in spec.meta:
                missing.append(f"{operation}.activate (metadata missing)")
            for arg, meta in spec.meta.items():
                if not _has_description(meta):
                    missing.append(f"{operation}.{arg}")

    assert first_party_count > 0, "first-party operation が registry にありません"
    assert not missing, "Description が空の operation.arg: " + ", ".join(missing)


def test_global_style_parameter_descriptions_are_complete() -> None:
    """global Style の3行はすべて説明を持つ。"""

    store = ParamStore()
    ensure_style_entries(
        store,
        background_color_rgb01=(1.0, 1.0, 1.0),
        global_thickness=0.001,
        global_line_color_rgb01=(0.0, 0.0, 0.0),
    )

    missing = [
        f"{STYLE_OP}.{arg}"
        for arg in (
            STYLE_BACKGROUND_COLOR,
            STYLE_GLOBAL_THICKNESS,
            STYLE_GLOBAL_LINE_COLOR,
        )
        if not _has_description(store.get_meta(style_key(arg)))
    ]
    assert not missing, "Description が空の operation.arg: " + ", ".join(missing)


def test_layer_style_parameter_descriptions_are_complete() -> None:
    """Layer Style の2行はすべて説明を持つ。"""

    metas = {
        LAYER_STYLE_LINE_THICKNESS: LAYER_STYLE_THICKNESS_META,
        LAYER_STYLE_LINE_COLOR: LAYER_STYLE_COLOR_META,
    }
    missing = [
        f"{LAYER_STYLE_OP}.{arg}" for arg, meta in metas.items() if not _has_description(meta)
    ]
    assert not missing, "Description が空の operation.arg: " + ", ".join(missing)


def test_preset_activate_description_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """preset の共通 activate metadata も空でない説明を持つ。"""

    preset_module = importlib.import_module("grafix.api.preset")
    preset_registry_module = importlib.import_module("grafix.core.preset_registry")
    isolated = PresetRegistry()
    monkeypatch.setattr(preset_registry_module, "preset_registry", isolated)

    @preset_module.preset(
        meta={
            "value": {
                "kind": "float",
                "description": "Description 注入確認用の公開値。",
            }
        }
    )
    def description_probe(value: float = 1.0) -> object:
        return value

    assert isolated.revision == 1
    assert isolated.get("description_probe") is description_probe
    spec = dict(isolated.items())["preset.description_probe"]
    assert _has_description(spec.meta.get("activate")), (
        "Description が空の operation.arg: preset.description_probe.activate"
    )


def _assigned_mappings(tree: ast.Module) -> dict[str, ast.expr]:
    """module 直下で名前に代入された式を返す。"""

    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                out[node.target.id] = node.value
    return out


def _preset_meta_expression(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.expr | None:
    """@preset の meta keyword に指定された式を返す。"""

    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        decorator_name = decorator.func
        if not isinstance(decorator_name, ast.Name) or decorator_name.id != "preset":
            continue
        return next(
            (keyword.value for keyword in decorator.keywords if keyword.arg == "meta"),
            None,
        )
    return None


def _description_from_meta_expression(expression: ast.expr) -> str | None:
    """dict spec または ParamMeta 呼び出しから Description literal を読む。"""

    description: ast.expr | None = None
    if isinstance(expression, ast.Dict):
        for key, value in zip(expression.keys, expression.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "description":
                description = value
                break
    elif isinstance(expression, ast.Call):
        description = next(
            (keyword.value for keyword in expression.keywords if keyword.arg == "description"),
            None,
        )

    if isinstance(description, ast.Constant) and isinstance(description.value, str):
        return description.value
    return None


def _missing_mapping_descriptions(
    expression: ast.expr,
    *,
    operation: str,
) -> tuple[list[str], int]:
    """静的な metadata mapping に含まれる欠落ラベルと検査件数を返す。"""

    if not isinstance(expression, ast.Dict):
        return [f"{operation}.* (metadata is not a dict literal)"], 0

    missing: list[str] = []
    checked = 0
    for key, value in zip(expression.keys, expression.values, strict=True):
        if key is None:  # **META_COMMON などは定義元の mapping を別途検査する。
            continue
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            missing.append(f"{operation}.* (parameter name is not a string literal)")
            continue
        checked += 1
        description = _description_from_meta_expression(value)
        if description is None or not description.strip():
            missing.append(f"{operation}.{key.value}")
    return missing, checked


def test_first_party_preset_descriptions_are_complete() -> None:
    """sketch/presets の静的 meta と META_COMMON を import せず検証する。"""

    repository_root = Path(__file__).resolve().parents[3]
    preset_root = repository_root / "sketch" / "presets"
    missing: list[str] = []
    checked = 0
    preset_count = 0

    for path in sorted(preset_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assignments = _assigned_mappings(tree)

        common = assignments.get("META_COMMON")
        if common is not None:
            common_missing, common_checked = _missing_mapping_descriptions(
                common,
                operation="META_COMMON",
            )
            missing.extend(common_missing)
            checked += common_checked

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            expression = _preset_meta_expression(node)
            if expression is None:
                continue
            preset_count += 1
            if isinstance(expression, ast.Name):
                resolved = assignments.get(expression.id)
                if resolved is None:
                    missing.append(f"preset.{node.name}.* (metadata assignment is missing)")
                    continue
                expression = resolved
            preset_missing, preset_checked = _missing_mapping_descriptions(
                expression,
                operation=f"preset.{node.name}",
            )
            missing.extend(preset_missing)
            checked += preset_checked

    assert preset_count > 0, "sketch/presets に @preset がありません"
    assert checked > 0, "sketch/presets に検査可能な metadata がありません"
    assert not missing, "Description が空の operation.arg: " + ", ".join(missing)
