from __future__ import annotations

from typing import Any, cast

import pytest

from grafix.core.parameters.meta import ParamMeta
from grafix.devtools.generate_stub import (
    _meta_hint,
    _render_docstring,
    _type_for_kind,
    _type_for_meta,
    generate_stubs_str,
)


def test_meta_hint_includes_semantic_parameter_information() -> None:
    meta = ParamMeta(
        kind="float",
        ui_min=0.1,
        ui_max=10.0,
        display_name="Stroke width",
        description="描画する線の太さ。",
        unit="mm",
        step=0.1,
        format="%.2f",
        scale="log",
        category="Stroke",
        advanced=True,
        recommended_range=(0.2, 5.0),
    )

    assert _meta_hint(meta) == (
        "描画する線の太さ。, display 'Stroke width', float, range [0.1, 10.0], "
        "recommended [0.2, 5.0], unit mm, step 0.1, scale log, format '%.2f', "
        "category 'Stroke', advanced"
    )


def test_meta_helpers_use_canonical_param_meta_contract() -> None:
    assert _meta_hint(None) is None
    assert _type_for_meta(
        ParamMeta(kind="choice", choices=("alpha", "beta"))
    ) == "Literal['alpha', 'beta']"

    with pytest.raises(AssertionError):
        _type_for_kind(cast(Any, "future-kind"))


def test_param_meta_description_takes_priority_over_callable_docstring() -> None:
    lines = _render_docstring(
        summary=None,
        param_order=["amount"],
        parsed_param_docs={"amount": "callable docstring の説明"},
        meta_by_name={
            "amount": ParamMeta(
                kind="float",
                description="metadata の説明",
            )
        },
    )

    assert lines == ["引数:", "    amount: metadata の説明, float"]


def test_callable_docstring_remains_primary_without_meta_description() -> None:
    for description in (None, ""):
        lines = _render_docstring(
            summary=None,
            param_order=["amount"],
            parsed_param_docs={"amount": "callable docstring の説明"},
            meta_by_name={
                "amount": ParamMeta(
                    kind="float",
                    description=description,
                )
            },
        )

        assert lines == ["引数:", "    amount: callable docstring の説明"]


def _method_block(stub: str, *, protocol: str, method: str) -> str:
    protocol_body = stub.split(f"class {protocol}(Protocol):\n", 1)[1]
    protocol_body = protocol_body.split("\nclass ", 1)[0]
    method_body = protocol_body.split(f"    def {method}(", 1)[1]
    return method_body.split("\n    def ", 1)[0]


def test_generated_operation_help_uses_meta_description_as_source_of_truth() -> None:
    line_help = _method_block(
        generate_stubs_str(),
        protocol="_G",
        method="line",
    )

    assert (
        "            length: 線分の始点から終点までの長さを指定します。, "
        "float, range [0.0, 200.0]\n"
        in line_help
    )


def test_generated_operation_help_describes_parameter_identity_controls() -> None:
    stub = generate_stubs_str()
    expected_help = (
        "            key: コード移動後も同じパラメータグループとして扱うための "
        "semantic identity。\n"
        "            instance_key: loop/comprehension の反復ごとにパラメータグループを"
        "分ける identity。\n"
        "            shared: True なら反復呼び出しで同じ semantic parameter group を"
        "意図的に共有する。instance_key とは同時指定できない。\n"
    )

    assert expected_help in _method_block(stub, protocol="_G", method="line")
    assert expected_help in _method_block(stub, protocol="_E", method="scale")
    assert expected_help in _method_block(
        stub,
        protocol="_EffectBuilder",
        method="scale",
    )


def test_generated_primitive_help_describes_code_owned_parameters() -> None:
    stub = generate_stubs_str()
    bezier_help = _method_block(stub, protocol="_G", method="bezier")
    polyline_help = _method_block(stub, protocol="_G", method="polyline")

    assert "            p0: 曲線の始点となる 2 次元または 3 次元座標\n" in bezier_help
    assert (
        "            p1: 始点側の接線方向と曲がり方を定める第 1 制御点\n"
        in bezier_help
    )
    assert (
        "            p2: 終点側の接線方向と曲がり方を定める第 2 制御点\n"
        in bezier_help
    )
    assert "            p3: 曲線の終点となる 2 次元または 3 次元座標\n" in bezier_help
    assert (
        "            points: 入力順に単一ポリラインを構成する 2 次元または 3 次元点列\n"
        in polyline_help
    )
