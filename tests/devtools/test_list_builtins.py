"""operation list CLI が immutable catalog snapshot だけを読む契約。"""

from __future__ import annotations

from grafix.core.authoring_definitions import RegistrationTarget, registration_scope
from grafix.core.operation_catalog import bind_operation_catalog
from grafix.core.operation_authoring import primitive
from grafix.devtools import list_builtins


def test_list_cli_reads_bound_catalog_without_registry_bootstrap(capsys) -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @primitive(meta={})
        def list_catalog_shape():
            return [], []

    catalog = target.snapshot().operations
    with bind_operation_catalog(catalog):
        assert list_builtins.main(["all"]) == 0

    assert capsys.readouterr().out == ("effects:\n\nprimitives:\nlist_catalog_shape\n")
