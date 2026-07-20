"""ParamStore の現行 schema に限定した JSON codec。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .codec_parser import (
    PARAM_STORE_SCHEMA_VERSION,
    ParamStoreDecodeIssue,
    ParamStoreSchemaError,
    ParsedParamStore,
    UnsupportedParamStoreSchemaError,
    param_store_schema_version,
    parse_param_store_payload,
)
from .meta_spec import meta_to_spec
from .state import ParamState
from .store import ParamStore
from .variations import _encode_variation


@dataclass(frozen=True, slots=True)
class ParamStoreDecodeResult:
    """復元した store と、除外・修復した entry の診断。"""

    store: ParamStore
    issues: tuple[ParamStoreDecodeIssue, ...] = ()


def encode_param_store(
    store: ParamStore,
    *,
    preserve_explicit_overrides: bool = False,
) -> dict[str, Any]:
    """ParamStore を現行 schema の JSON 化可能な dict へ変換する。"""

    labels = store._labels_ref().as_dict()
    effects = store._effects_ref()
    persisted_keys = tuple(
        key for key in store._states if key in store._meta
    )
    return {
        "schema_version": PARAM_STORE_SCHEMA_VERSION,
        "states": [
            {
                "op": key.op,
                "site_id": key.site_id,
                "arg": key.arg,
                "override": (
                    bool(store._states[key].override)
                    if preserve_explicit_overrides
                    else (
                        False
                        if store._explicit_by_key[key]
                        else bool(store._states[key].override)
                    )
                ),
                "ui_value": _json_array(store._states[key].ui_value),
                "cc_key": _json_array(store._states[key].cc_key),
            }
            for key in persisted_keys
        ],
        "meta": [
            {
                "op": key.op,
                "site_id": key.site_id,
                "arg": key.arg,
                **meta_to_spec(store._meta[key]),
            }
            for key in persisted_keys
        ],
        "labels": [
            {"op": op, "site_id": site_id, "label": label}
            for (op, site_id), label in labels.items()
        ],
        "ordinals": store._ordinals_ref().as_dict(),
        "effect_steps": [
            {
                "op": step.op,
                "site_id": step.site_id,
                "chain_id": chain_id,
                "step_index": step.code_index,
                "n_inputs": step.n_inputs,
            }
            for chain_id, steps in effects.topologies().items()
            for step in steps
        ],
        "chain_ordinals": effects.chain_ordinals(),
        "explicit": [
            {
                "op": key.op,
                "site_id": key.site_id,
                "arg": key.arg,
                "explicit": bool(store._explicit_by_key[key]),
            }
            for key in persisted_keys
        ],
        "ui": {
            "collapsed_headers": sorted(store._collapsed_headers_ref()),
            "effect_order_overrides": [
                {
                    "chain_id": chain_id,
                    "steps": [
                        {"op": op, "site_id": site_id}
                        for op, site_id in step_keys
                    ],
                }
                for chain_id, step_keys in sorted(
                    effects.order_overrides().items(),
                    key=lambda item: item[0],
                )
            ],
            "locked_parameters": [
                {"op": key.op, "site_id": key.site_id, "arg": key.arg}
                for key in sorted(
                    store._locked_keys_ref(),
                    key=lambda item: (item.op, item.site_id, item.arg),
                )
            ],
            "favorite_parameters": [
                {"op": key.op, "site_id": key.site_id, "arg": key.arg}
                for key in sorted(
                    store._favorite_keys_ref(),
                    key=lambda item: (item.op, item.site_id, item.arg),
                )
            ],
        },
        "variations": [
            _encode_variation(variation)
            for variation in store._variations_ref().values()
        ],
    }


def _json_array(value: Any) -> Any:
    """canonical tuple を JSON-native な array へ射影する。"""

    return list(value) if isinstance(value, tuple) else value


def dumps_param_store(
    store: ParamStore,
    *,
    preserve_explicit_overrides: bool = False,
) -> str:
    """ParamStore を JSON 文字列へ変換する。"""

    return json.dumps(
        encode_param_store(
            store,
            preserve_explicit_overrides=preserve_explicit_overrides,
        )
    )


def _store_from_parsed(
    parsed: ParsedParamStore,
    *,
    preserve_explicit_overrides: bool,
) -> ParamStore:
    """typed intermediate を追加検証せず ParamStore へ一度だけ適用する。"""

    store = ParamStore()
    store._meta.update(parsed.meta)
    store._states.update(
        {
            key: ParamState(
                override=entry.value.override,
                ui_value=entry.value.ui_value,
                cc_key=entry.value.cc_key,
            )
            for key, entry in parsed.states.items()
        }
    )
    store._explicit_by_key.update(parsed.explicit_by_key)
    store._labels_ref().replace(parsed.labels)
    store._ordinals_ref().replace(parsed.ordinals)
    store._effects_ref().replace_persisted_state(
        topologies=parsed.topologies,
        chain_ordinals=parsed.chain_ordinals,
        order_overrides=parsed.effect_order_overrides,
    )
    store._collapsed_headers_ref().update(parsed.collapsed_headers)
    store._locked_keys_ref().update(parsed.locked_parameters)
    store._replace_favorite_keys(parsed.favorite_parameters)
    store._variations_ref().update(
        {variation.name: variation for variation in parsed.variations}
    )

    if not preserve_explicit_overrides:
        for key, is_explicit in store._explicit_by_key.items():
            if is_explicit:
                store._states[key].override = False

    store._runtime_ref().loaded_groups = {
        (key.op, key.site_id) for key in store._states
    }
    store._touch()
    return store


def decode_param_store_result(
    obj: object,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStoreDecodeResult:
    """現行 schema の payload を一度 parse して復元する。"""

    parsed = parse_param_store_payload(obj)
    return ParamStoreDecodeResult(
        store=_store_from_parsed(
            parsed,
            preserve_explicit_overrides=preserve_explicit_overrides,
        ),
        issues=parsed.issues,
    )


def loads_param_store_result(
    payload: str,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStoreDecodeResult:
    """JSON 文字列を部分破損診断付きで復元する。"""

    return decode_param_store_result(
        json.loads(payload),
        preserve_explicit_overrides=preserve_explicit_overrides,
    )


__all__ = [
    "PARAM_STORE_SCHEMA_VERSION",
    "ParamStoreDecodeIssue",
    "ParamStoreDecodeResult",
    "ParamStoreSchemaError",
    "UnsupportedParamStoreSchemaError",
    "decode_param_store_result",
    "dumps_param_store",
    "encode_param_store",
    "loads_param_store_result",
    "param_store_schema_version",
]
