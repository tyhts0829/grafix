from __future__ import annotations

import numpy as np

from grafix.devtools.benchmarks.cases import build_default_cases, describe_geometry


def test_default_cases_use_tuple_inputs_and_arity_tags() -> None:
    cases = build_default_cases(seed=7)

    assert len({case.case_id for case in cases}) == len(cases)
    assert any(case.n_inputs == 1 for case in cases)
    assert any(case.n_inputs == 2 for case in cases)

    for case in cases:
        assert isinstance(case.inputs, tuple)
        assert case.n_inputs == len(case.inputs)
        assert ("unary" in case.tags) == (case.n_inputs == 1)
        assert ("binary" in case.tags) == (case.n_inputs == 2)

        for geometry in case.inputs:
            assert geometry.coords.dtype == np.float32
            assert geometry.offsets.dtype == np.int32
            assert geometry.offsets[0] == 0
            assert geometry.offsets[-1] == geometry.coords.shape[0]


def test_binary_mask_case_has_source_and_closed_mask() -> None:
    binary = next(case for case in build_default_cases(seed=0) if case.case_id == "binary_mask")

    assert binary.n_inputs == 2
    source, mask = binary.inputs
    source_stats = describe_geometry(source)
    mask_stats = describe_geometry(mask)

    assert source_stats["n_lines"] > 1
    assert source_stats["all_closed"] is False
    assert mask_stats["n_lines"] == 2
    assert mask_stats["all_closed"] is True
