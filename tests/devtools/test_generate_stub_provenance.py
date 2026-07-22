from __future__ import annotations

from dataclasses import replace

import pytest

from grafix.core.builtins import builtin_operation_catalog
from grafix.core.operation_catalog import OperationCatalogBuilder
from grafix.devtools.generate_stub import _resolve_impl_callable


def test_resolve_impl_callable_rejects_missing_provenance_without_name_fallback(
) -> None:
    source = builtin_operation_catalog()
    builder = OperationCatalogBuilder(source)
    builder.register(
        replace(
            source.resolve("primitive", "line").declaration,
            provenance="invalid",
        ),
        overwrite=True,
    )

    with pytest.raises(ValueError, match="provenance"):
        _resolve_impl_callable("primitive", "line", catalog=builder.freeze())
