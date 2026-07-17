from __future__ import annotations

from grafix.core.parameters.meta import ParamMeta
from grafix.devtools.generate_stub import _meta_hint


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
