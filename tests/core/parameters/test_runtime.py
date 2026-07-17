from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.runtime import ParamStoreRuntime


def test_new_runtime_field_preserves_legacy_positional_argument_order() -> None:
    loaded = {("line", "loaded")}
    observed = {("line", "observed")}
    reconciled = {(("line", "old"), ("line", "new"))}
    display_order = {("line", "site"): 7}
    key = ParameterKey(op="line", site_id="site", arg="length")
    effective = {key: 12.5}
    warned = {("line", "unknown")}

    # last_source_by_key 追加前の 7 positional fields をそのまま使う。
    runtime = ParamStoreRuntime(
        loaded,
        observed,
        reconciled,
        display_order,
        8,
        effective,
        warned,
    )

    assert runtime.loaded_groups is loaded
    assert runtime.observed_groups is observed
    assert runtime.reconcile_applied is reconciled
    assert runtime.display_order_by_group is display_order
    assert runtime.next_display_order == 8
    assert runtime.last_effective_by_key is effective
    assert runtime.warned_unknown_args is warned
    assert runtime.last_source_by_key == {}
    assert runtime.effective_revision == 0
