"""Parameter identity の exact string 契約を確認する。"""

from __future__ import annotations

import pytest

from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.labels import ParamLabels
from grafix.core.parameters.ordinals import GroupOrdinals
from grafix.core.parameters.effects import (
    EffectChainIndex,
    EffectStepTopology,
    normalize_effect_order,
)
from grafix.core.parameters.frame_params import (
    FrameEffectChainRecord,
    FrameLabelRecord,
)


class _StringSubclass(str):
    pass


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("op", 1, TypeError),
        ("site_id", 2, TypeError),
        ("arg", 3, TypeError),
        ("op", "", ValueError),
        ("site_id", "", ValueError),
        ("arg", "", ValueError),
    ],
)
def test_parameter_key_requires_nonempty_string_identity(
    field: str,
    value: object,
    error: type[Exception],
) -> None:
    values: dict[str, object] = {"op": "line", "site_id": "site", "arg": "length"}
    values[field] = value

    with pytest.raises(error):
        ParameterKey(**values)  # type: ignore[arg-type]


def test_parameter_key_rejects_string_subclass_identity() -> None:
    with pytest.raises(TypeError):
        ParameterKey(
            op=_StringSubclass("line"),
            site_id="site",
            arg="length",
        )


def test_labels_do_not_merge_integer_and_string_identity() -> None:
    labels = ParamLabels()
    labels.set("line", "1", "string site")

    with pytest.raises(TypeError):
        labels.get("line", 1)  # type: ignore[arg-type]


def test_ordinals_do_not_merge_integer_and_string_identity() -> None:
    ordinals = GroupOrdinals()
    assert ordinals.get_or_assign("line", "1") == 1

    with pytest.raises(TypeError):
        ordinals.get_or_assign("line", 1)  # type: ignore[arg-type]


def test_effect_topology_requires_exact_identity_and_integer_counts() -> None:
    with pytest.raises(TypeError):
        EffectStepTopology(op=1, site_id="site", n_inputs=1, code_index=0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        EffectStepTopology(
            op="scale",
            site_id="site",
            n_inputs=1.5,  # type: ignore[arg-type]
            code_index=0,
        )


def test_effect_order_rejects_identity_stringification() -> None:
    with pytest.raises(TypeError):
        normalize_effect_order(((1, "site"),))  # type: ignore[arg-type]


def test_effect_chain_lookup_rejects_non_string_identity() -> None:
    index = EffectChainIndex()
    index.record_chain(
        chain_id="chain",
        steps=(
            EffectStepTopology(
                op="scale",
                site_id="site",
                n_inputs=1,
                code_index=0,
            ),
        ),
    )

    with pytest.raises(TypeError):
        index.get_step("scale", 1)  # type: ignore[arg-type]


def test_frame_identity_records_do_not_stringify_values() -> None:
    with pytest.raises(TypeError):
        FrameLabelRecord(op=1, site_id="site", label="label")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FrameEffectChainRecord(chain_id=1, steps=())  # type: ignore[arg-type]
