# どこで: `src/grafix/core/parameters/codec.py`。
# 何を: ParamStore の JSON encode/decode を提供する。
# なぜ: 永続化仕様を ParamStore 本体から分離し、スキーマ変更の影響範囲を局所化するため。

"""ParamStore の永続化用 JSON codec。

このモジュールは、ParamStore の内部状態を JSON 化可能な形（dict/list など）に変換し、
その逆（JSON デコード結果から ParamStore を復元）も提供する。

永続化仕様（どの情報を保存するか / 互換の扱い / ロード時の修復）を ParamStore 本体から分離し、
スキーマ変更の影響範囲をこのファイルに閉じることが目的。

読み方（入口）
---------------
- `encode_param_store()` / `dumps_param_store()`: 保存側（store -> dict/JSON）
- `decode_param_store()` / `loads_param_store()`: 復元側（dict/JSON -> store）
- `decode_param_store_result()` / `loads_param_store_result()`: migration/部分破損診断付き復元

Notes
-----
- codec は永続化仕様を 1 箇所へ閉じるため、ParamStore の private な参照へアクセスする。
- version 無しは legacy として現行 schema へ移行する。future version は原本保護のため拒否する。
- 部分的に壊れた entry は可能な範囲で復元し、result API が破棄内容を返す。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .effects import EffectChainIndex, EffectStepTopology
from .key import ParameterKey
from .meta_spec import meta_from_record, meta_to_spec
from .state import ParamState
from .store import ParamStore
from .variations import _decode_variation, _encode_variation
from .view import canonicalize_ui_value

PARAM_STORE_SCHEMA_VERSION = 2


class ParamStoreSchemaError(ValueError):
    """ParamStore payload の schema version が無効な場合の例外。"""


class UnsupportedParamStoreSchemaError(ParamStoreSchemaError):
    """現在の Grafix より新しい schema を読もうとした場合の例外。"""

    def __init__(self, found_version: int) -> None:
        self.found_version = int(found_version)
        self.supported_version = PARAM_STORE_SCHEMA_VERSION
        super().__init__(
            "ParamStore schema_version "
            f"{self.found_version} is newer than supported version "
            f"{self.supported_version}"
        )


@dataclass(frozen=True, slots=True)
class ParamStoreDecodeIssue:
    """部分復元のために破棄した 1 entry の診断。"""

    section: str
    index: int | None
    reason: str

    def describe(self) -> str:
        """log/診断表示用の安定文字列を返す。"""

        location = self.section if self.index is None else f"{self.section}[{self.index}]"
        return f"{location}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ParamStoreDecodeResult:
    """codec の復元結果と migration/部分破損情報。"""

    store: ParamStore
    issues: tuple[ParamStoreDecodeIssue, ...] = ()
    migrated_legacy: bool = False


def encode_param_store(
    store: ParamStore,
    *,
    preserve_explicit_overrides: bool = False,
) -> dict[str, Any]:
    """ParamStore を JSON 化可能な dict に変換して返す。

    Notes
    -----
    - 返す dict は `json.dumps()` 可能なプリミティブ（dict/list/str/int/float/bool/None）に
      射影した「永続化ペイロード」。
    - `states` は GUI 対象のみに限定するため、`meta` の無い state は含めない。
    - `explicit=True` な key（コード側で明示指定された kwargs）は「起動時はコードが勝つ」前提なので、
      通常保存では `override=True` を保存せず、次回起動時は
      `override=False` から開始する。
    - `preserve_explicit_overrides=True` は未完了 session の recovery 用。
      この場合は explicit key も live override をそのまま保持する。
    """

    # codec は ParamStore の内部表現へ直接アクセスする。
    # 目的: 「永続化の仕様」を 1 箇所に閉じ、ParamStore 本体を “入れ物” に保つ。
    labels = store._labels_ref().as_dict()
    ordinals = store._ordinals_ref().as_dict()
    effects = store._effects_ref()
    topology_keys = {
        step.key
        for steps in effects.topologies().values()
        for step in steps
    }
    effect_steps = [
        {
            "op": step.op,
            "site_id": step.site_id,
            "chain_id": chain_id,
            "step_index": step.code_index,
            "n_inputs": step.n_inputs,
        }
        for chain_id, steps in effects.topologies().items()
        for step in steps
    ]
    # topology観測導入前と同じくparameter recordだけで作られたstepや、
    # 移行途中にtopologyと混在するlegacy stepも落とさず保存する。
    effect_steps.extend(
        {
            "op": op,
            "site_id": site_id,
            "chain_id": chain_id,
            "step_index": step_index,
            "n_inputs": 1,
        }
        for (op, site_id), (
            chain_id,
            step_index,
        ) in effects.step_info_by_site().items()
        if (op, site_id) not in topology_keys
    )

    return {
        "schema_version": PARAM_STORE_SCHEMA_VERSION,
        "states": [
            {
                "op": k.op,
                "site_id": k.site_id,
                "arg": k.arg,
                # 通常保存では明示 kwargs はコードを優先する。
                # recovery だけはクラッシュ直前の live override を保持する。
                "override": (
                    bool(v.override)
                    if preserve_explicit_overrides
                    else (
                        False
                        if store._explicit_by_key.get(k) is True
                        else bool(v.override)
                    )
                ),
                "ui_value": v.ui_value,
                # ui_value/cc_key は JSON では list 化されることがある（tuple -> list）。
                # decode 側で meta.kind に従って canonicalize し、想定する型/不変形へ戻す。
                "cc_key": v.cc_key,
            }
            # meta が無い state は GUI 対象外なので永続化しない（ゴミ state の残留防止）。
            for k, v in store._states.items()
            if k in store._meta
        ],
        "meta": [
            {
                "op": k.op,
                "site_id": k.site_id,
                "arg": k.arg,
                **meta_to_spec(m),
            }
            for k, m in store._meta.items()
        ],
        "labels": [
            {"op": op, "site_id": site_id, "label": label}
            for (op, site_id), label in labels.items()
        ],
        "ordinals": ordinals,
        "effect_steps": effect_steps,
        "chain_ordinals": effects.chain_ordinals(),
        "explicit": [
            {
                "op": k.op,
                "site_id": k.site_id,
                "arg": k.arg,
                "explicit": bool(v),
            }
            for k, v in store._explicit_by_key.items()
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


def dumps_param_store(
    store: ParamStore,
    *,
    preserve_explicit_overrides: bool = False,
) -> str:
    """ParamStore を JSON 文字列へ変換して返す。

    Notes
    -----
    - JSON の生成は `json.dumps()` のデフォルト挙動に従う（整形/ソートなどは行わない）。
    - バイナリや圧縮などの「保存形式の選択」は、このレイヤでは扱わない。
    """

    return json.dumps(
        encode_param_store(
            store,
            preserve_explicit_overrides=preserve_explicit_overrides,
        )
    )


def _decode_param_store_current(
    obj: object,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStore:
    """schema 確認済みの dict から ParamStore を復元する。

    Parameters
    ----------
    obj : object
        `json.loads()` の結果（dict）を想定する。
        スキーマが古い/壊れている場合でも、可能な範囲で復元して不正な要素は捨てる。
    preserve_explicit_overrides : bool
        True なら recovery に記録した explicit key の live override を保持する。
        通常ファイルのロードでは False のままとし、コードを優先する。

    Returns
    -------
    ParamStore
        復元されたストア。

    Raises
    ------
    TypeError
        obj が dict でない場合。

    Notes
    -----
    - `states` と `meta` は別々に読み、最後に「meta がある state だけ」を残す。
      目的: 古い JSON や部分保存からの復元でも、GUI 対象外データの混入を止める。
    - `ui_value` は `meta.kind` に従って canonicalize し、想定する型/不変形へ戻す。
    """

    if not isinstance(obj, dict):
        raise TypeError("ParamStore payload must be a dict")

    store = ParamStore()

    def _to_int_or_none(v: Any) -> int | None:
        # JSON は型がゆるくなりがちなので「CC 番号っぽいもの」を安全に int へ寄せる。
        # bool は int の subclass だが、True/False を 1/0 とみなすのは事故りやすいので除外する。
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return None
        return None

    for item in obj.get("states", []):
        if not isinstance(item, dict):
            continue
        try:
            key = ParameterKey(op=str(item["op"]), site_id=str(item["site_id"]), arg=str(item["arg"]))
        except Exception:
            continue

        cc_key: int | tuple[int | None, int | None, int | None] | None
        raw_cc = item.get("cc_key")
        if raw_cc is None:
            cc_key = None
        elif isinstance(raw_cc, list):
            # json 由来の tuple は list になっている想定。
            # （encode -> decode を dict のまま直結すると tuple になり得るが、この関数は JSON 復元用。）
            if len(raw_cc) == 3:
                a, b, c = raw_cc
                cc_tuple = (_to_int_or_none(a), _to_int_or_none(b), _to_int_or_none(c))
                cc_key = None if cc_tuple == (None, None, None) else cc_tuple
            else:
                cc_key = None
        else:
            cc_key = _to_int_or_none(raw_cc)

        state = ParamState(ui_value=item.get("ui_value"), cc_key=cc_key)
        if "override" in item:
            state.override = bool(item["override"])
        store._states[key] = state

    for item in obj.get("meta", []):
        if not isinstance(item, dict):
            continue
        try:
            key = ParameterKey(op=str(item["op"]), site_id=str(item["site_id"]), arg=str(item["arg"]))
            meta = meta_from_record(item)
        except Exception:
            continue
        store._meta[key] = meta

    # meta が無い state は GUI 対象外なので drop する（永続化/復元の双方で汚染を止める）。
    for key, state in list(store._states.items()):
        stored_meta = store._meta.get(key)
        if stored_meta is None:
            del store._states[key]
            continue
        # JSON は list/str などに崩れている可能性があるので、meta.kind に従って正規化する。
        state.ui_value = canonicalize_ui_value(state.ui_value, stored_meta)

    labels_items: list[tuple[tuple[str, str], str]] = []
    for item in obj.get("labels", []):
        if not isinstance(item, dict):
            continue
        try:
            group = (str(item["op"]), str(item["site_id"]))
            label = str(item["label"])
        except Exception:
            continue
        labels_items.append((group, label))
    store._labels_ref().replace_from_items(labels_items)

    store._ordinals_ref().replace_from_dict(obj.get("ordinals", {}))
    # 古い JSON や手編集で ordinal が欠けたり穴あきになった場合でも、GUI 並びを崩しにくくする。
    store._ordinals_ref().compact_all()

    store._effects_ref().replace_from_json(
        effect_steps=obj.get("effect_steps", []),
        chain_ordinals=obj.get("chain_ordinals", {}),
    )

    for item in obj.get("explicit", []):
        if not isinstance(item, dict):
            continue
        try:
            key = ParameterKey(op=str(item["op"]), site_id=str(item["site_id"]), arg=str(item["arg"]))
        except Exception:
            continue
        store._explicit_by_key[key] = bool(item.get("explicit", False))

    ui_obj = obj.get("ui")
    if isinstance(ui_obj, dict):
        store._effects_ref().replace_order_overrides_from_json(
            _valid_effect_order_override_entries(
                ui_obj.get("effect_order_overrides", [])
            )
        )
        collapsed = ui_obj.get("collapsed_headers", [])
        if isinstance(collapsed, list):
            for item in collapsed:
                try:
                    store._collapsed_headers_ref().add(str(item))
                except Exception:
                    continue
        locked_parameters = ui_obj.get("locked_parameters", [])
        if isinstance(locked_parameters, list):
            for item in locked_parameters:
                if not isinstance(item, dict):
                    continue
                try:
                    key = ParameterKey(
                        op=str(item["op"]),
                        site_id=str(item["site_id"]),
                        arg=str(item["arg"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                # 壊れた/古い UI entry だけを残さない。通常の stale site は
                # states/meta も一緒にロードされるため reconcile 可能である。
                if key in store._states and key in store._meta:
                    store._locked_keys_ref().add(key)

        favorite_parameters = ui_obj.get("favorite_parameters", [])
        favorite_keys: set[ParameterKey] = set()
        if isinstance(favorite_parameters, list):
            for item in favorite_parameters:
                if not isinstance(item, dict):
                    continue
                try:
                    key = ParameterKey(
                        op=str(item["op"]),
                        site_id=str(item["site_id"]),
                        arg=str(item["arg"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                # UI state 単独の孤児を作らず、reconcile 可能な parameter だけ残す。
                if key in store._states and key in store._meta:
                    favorite_keys.add(key)
        store._replace_favorite_keys(favorite_keys)

    variations_obj = obj.get("variations", [])
    if isinstance(variations_obj, list):
        for item in variations_obj:
            variation = _decode_variation(item)
            if variation is None or variation.name in store._variations_ref():
                continue
            store._variations_ref()[variation.name] = variation

    # 通常ロードでは explicit key のコード値を優先する。
    # recovery ロードでは未完了 session の実効状態を復元するため触らない。
    if not preserve_explicit_overrides:
        for key, is_explicit in store._explicit_by_key.items():
            if is_explicit is True and key in store._states:
                store._states[key].override = False

    # reconcile の材料として「ロード時点で存在していた group」を runtime に記録する。
    # これがあることで、次フレームの observed_groups と比較して site_id の揺れを吸収できる。
    store._runtime_ref().loaded_groups = {
        (str(k.op), str(k.site_id)) for k in set(store._states) | set(store._meta)
    }

    # store_snapshot が “pure” 前提なので、ロード直後に ordinal の不足を補完する。
    # （store_snapshot は ordinal 未割当を例外とみなすため、decode の責務で不変条件を満たす。）
    ordinals = store._ordinals_ref()
    for key in store._states.keys():
        ordinals.get_or_assign(key.op, key.site_id)
    for key in store._meta.keys():
        ordinals.get_or_assign(key.op, key.site_id)
    store._touch()
    return store


def param_store_schema_version(obj: object) -> int | None:
    """payload の schema version を返し、version 無しは None とする。"""

    if not isinstance(obj, dict):
        raise TypeError("ParamStore payload must be a dict")
    if "schema_version" not in obj:
        return None

    raw_version = obj["schema_version"]
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise ParamStoreSchemaError("schema_version must be an int")
    if raw_version > PARAM_STORE_SCHEMA_VERSION:
        raise UnsupportedParamStoreSchemaError(raw_version)
    if raw_version not in {1, PARAM_STORE_SCHEMA_VERSION}:
        raise ParamStoreSchemaError(
            f"unsupported ParamStore schema_version: {raw_version}"
        )
    return raw_version


def _migrate_param_store_payload(obj: object) -> tuple[dict[str, Any], bool]:
    """legacy payload を現行 schema へ明示的に移行する。"""

    version = param_store_schema_version(obj)
    assert isinstance(obj, dict)
    if version is None or version == 1:
        migrated = dict(obj)
        ui_obj = migrated.get("ui")
        if isinstance(ui_obj, dict):
            migrated_ui = dict(ui_obj)
            migrated_ui.setdefault("effect_order_overrides", [])
            migrated["ui"] = migrated_ui
        migrated["schema_version"] = PARAM_STORE_SCHEMA_VERSION
        return migrated, version is None
    return obj, False


def _effect_order_override_entry_error(
    item: object,
    *,
    seen_chain_ids: set[str],
    allow_code_order: bool = False,
    require_topology_signature: bool = False,
) -> str | None:
    """effect 順序 entry の破損理由を返し、有効なら None を返す。"""

    if not isinstance(item, dict):
        return "expected an object"
    chain_id = item.get("chain_id")
    steps_obj = item.get("steps")
    if not isinstance(chain_id, str) or not chain_id.strip():
        return "chain_id must be a non-empty string"
    if chain_id in seen_chain_ids:
        return "duplicate chain_id"
    if require_topology_signature:
        topology_obj = item.get("topology")
        if not isinstance(topology_obj, list) or not topology_obj:
            return "topology must be a non-empty list"
        for step in topology_obj:
            if not isinstance(step, dict):
                return "each topology step must be an object"
            op = step.get("op")
            site_id = step.get("site_id")
            n_inputs = step.get("n_inputs")
            if not isinstance(op, str) or not op.strip():
                return "topology step op must be a non-empty string"
            if not isinstance(site_id, str) or not site_id.strip():
                return "topology step site_id must be a non-empty string"
            if (
                isinstance(n_inputs, bool)
                or not isinstance(n_inputs, int)
                or n_inputs < 1
            ):
                return "topology step n_inputs must be an int >= 1"
    if steps_obj is None and allow_code_order:
        return None
    if not isinstance(steps_obj, list) or not steps_obj:
        return "steps must be a non-empty list"

    seen_steps: set[tuple[str, str]] = set()
    for step in steps_obj:
        if not isinstance(step, dict):
            return "each step must be an object"
        op = step.get("op")
        site_id = step.get("site_id")
        if not isinstance(op, str) or not op.strip():
            return "step op must be a non-empty string"
        if not isinstance(site_id, str) or not site_id.strip():
            return "step site_id must be a non-empty string"
        key = (op, site_id)
        if key in seen_steps:
            return "duplicate step"
        seen_steps.add(key)
    return None


def _valid_effect_order_override_entries(obj: object) -> list[dict[str, Any]]:
    """有効な effect 順序 entry だけを正規化して返す。"""

    if not isinstance(obj, list):
        return []

    valid: list[dict[str, Any]] = []
    seen_chain_ids: set[str] = set()
    for item in obj:
        error = _effect_order_override_entry_error(
            item,
            seen_chain_ids=seen_chain_ids,
        )
        if error is not None:
            continue
        assert isinstance(item, dict)
        chain_id = item["chain_id"]
        steps_obj = item["steps"]
        assert isinstance(chain_id, str)
        assert isinstance(steps_obj, list)
        steps = [
            {"op": step["op"], "site_id": step["site_id"]}
            for step in steps_obj
            if isinstance(step, dict)
        ]
        seen_chain_ids.add(chain_id)
        valid.append({"chain_id": chain_id, "steps": steps})
    return valid


def _effect_order_topology_error(
    item: dict[str, Any],
    topologies: dict[str, tuple[EffectStepTopology, ...]],
) -> str | None:
    """同じpayload内のtopologyに対するorder不整合理由を返す。"""

    chain_id = str(item["chain_id"])
    topology = topologies.get(chain_id)
    if topology is None:
        # topology未保存のoverrideは、最初の成功frameで検証する。
        return None
    code_order = tuple(step.key for step in topology)
    if len(set(code_order)) != len(code_order):
        return "effect topology has duplicate step identity"

    raw_steps = item["steps"]
    assert isinstance(raw_steps, list)
    order = tuple(
        (str(step["op"]), str(step["site_id"]))
        for step in raw_steps
        if isinstance(step, dict)
    )
    if len(order) != len(code_order) or set(order) != set(code_order):
        return "steps must be an exact permutation of the effect topology"

    n_inputs_by_step = {
        step.key: int(step.n_inputs)
        for step in topology
    }
    if any(
        n_inputs_by_step[step] > 1 and index != 0
        for index, step in enumerate(order)
    ):
        return "multi-input effect must remain at the start of its chain"
    return None


def _find_decode_issues(obj: dict[str, Any]) -> tuple[ParamStoreDecodeIssue, ...]:
    """現行 decoder が破棄・空値化する不正 entry を列挙する。"""

    issues: list[ParamStoreDecodeIssue] = []
    required_by_section = {
        "states": ("op", "site_id", "arg"),
        "meta": ("op", "site_id", "arg", "kind"),
        "labels": ("op", "site_id", "label"),
        "effect_steps": ("op", "site_id", "chain_id", "step_index"),
        "explicit": ("op", "site_id", "arg"),
        "variations": ("name", "created_at", "parameter_snapshot"),
    }
    entries_by_section: dict[str, list[object]] = {}
    variation_names: set[str] = set()
    for section, required_fields in required_by_section.items():
        raw_entries = obj.get(section, [])
        if not isinstance(raw_entries, list):
            issues.append(ParamStoreDecodeIssue(section, None, "expected a list"))
            entries_by_section[section] = []
            continue
        entries_by_section[section] = raw_entries
        for index, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                issues.append(
                    ParamStoreDecodeIssue(section, index, "expected an object")
                )
                continue
            missing = [field for field in required_fields if field not in item]
            if missing:
                issues.append(
                    ParamStoreDecodeIssue(
                        section,
                        index,
                        f"missing fields: {', '.join(missing)}",
                    )
                )
                continue
            try:
                if section == "meta":
                    meta_from_record(item)
                elif section == "effect_steps":
                    int(item["step_index"])
                elif section == "variations":
                    variation = _decode_variation(item)
                    if variation is None or variation.name in variation_names:
                        raise ValueError
                    variation_names.add(variation.name)
                    snapshot = item["parameter_snapshot"]
                    assert isinstance(snapshot, dict)
                    for nested in _find_decode_issues(
                        {
                            "states": snapshot.get("states", []),
                            "meta": snapshot.get("meta", []),
                        }
                    ):
                        location = nested.section
                        if nested.index is not None:
                            location += f"[{nested.index}]"
                        issues.append(
                            ParamStoreDecodeIssue(
                                section,
                                index,
                                f"parameter_snapshot.{location}: {nested.reason}",
                            )
                        )
                    if not isinstance(snapshot.get("collapsed_by_header", {}), dict):
                        issues.append(
                            ParamStoreDecodeIssue(
                                section,
                                index,
                                "parameter_snapshot.collapsed_by_header "
                                "must be an object",
                            )
                        )
                    raw_order_state = snapshot.get("effect_order_state", [])
                    if not isinstance(raw_order_state, list):
                        issues.append(
                            ParamStoreDecodeIssue(
                                section,
                                index,
                                "parameter_snapshot.effect_order_state "
                                "must be a list",
                            )
                        )
                    else:
                        variation_seen_chain_ids: set[str] = set()
                        for order_index, order_item in enumerate(raw_order_state):
                            reason = _effect_order_override_entry_error(
                                order_item,
                                seen_chain_ids=variation_seen_chain_ids,
                                allow_code_order=True,
                                require_topology_signature=True,
                            )
                            if reason is not None:
                                issues.append(
                                    ParamStoreDecodeIssue(
                                        section,
                                        index,
                                        "parameter_snapshot.effect_order_state"
                                        f"[{order_index}]: {reason}",
                                    )
                                )
                                continue
                            assert isinstance(order_item, dict)
                            variation_seen_chain_ids.add(str(order_item["chain_id"]))
            except Exception:
                issues.append(
                    ParamStoreDecodeIssue(section, index, "invalid entry")
                )

    def entry_key(item: object) -> tuple[str, str, str] | None:
        if not isinstance(item, dict):
            return None
        if not all(field in item for field in ("op", "site_id", "arg")):
            return None
        return str(item["op"]), str(item["site_id"]), str(item["arg"])

    meta_keys = {
        key
        for item in entries_by_section["meta"]
        if (key := entry_key(item)) is not None
    }
    state_keys = {
        key
        for item in entries_by_section["states"]
        if (key := entry_key(item)) is not None
    }
    for index, item in enumerate(entries_by_section["states"]):
        key = entry_key(item)
        if key is not None and key not in meta_keys:
            issues.append(
                ParamStoreDecodeIssue("states", index, "matching meta is missing")
            )

    for section, is_nested in (("ordinals", True), ("chain_ordinals", False)):
        raw_mapping = obj.get(section, {})
        if not isinstance(raw_mapping, dict):
            issues.append(ParamStoreDecodeIssue(section, None, "expected an object"))
            continue
        values: list[object] = []
        for index, value in enumerate(raw_mapping.values()):
            if is_nested:
                if not isinstance(value, dict):
                    issues.append(
                        ParamStoreDecodeIssue(section, index, "expected an object")
                    )
                    continue
                values.extend(value.values())
            else:
                values.append(value)
        for index, value in enumerate(values):
            try:
                int(value)  # type: ignore[call-overload]
            except Exception:
                issues.append(
                    ParamStoreDecodeIssue(section, index, "ordinal must be an int")
                )

    effect_index = EffectChainIndex()
    effect_index.replace_from_json(
        effect_steps=entries_by_section["effect_steps"],
        chain_ordinals=obj.get("chain_ordinals", {}),
    )
    effect_topologies = effect_index.topologies()

    ui_obj = obj.get("ui", {})
    if not isinstance(ui_obj, dict):
        issues.append(ParamStoreDecodeIssue("ui", None, "expected an object"))
    else:
        if not isinstance(ui_obj.get("collapsed_headers", []), list):
            issues.append(
                ParamStoreDecodeIssue(
                    "ui.collapsed_headers",
                    None,
                    "expected a list",
                )
            )
        effect_order_overrides = ui_obj.get("effect_order_overrides", [])
        if not isinstance(effect_order_overrides, list):
            issues.append(
                ParamStoreDecodeIssue(
                    "ui.effect_order_overrides",
                    None,
                    "expected a list",
                )
            )
        else:
            ui_seen_chain_ids: set[str] = set()
            for index, item in enumerate(effect_order_overrides):
                reason = _effect_order_override_entry_error(
                    item,
                    seen_chain_ids=ui_seen_chain_ids,
                )
                if reason is not None:
                    issues.append(
                        ParamStoreDecodeIssue(
                            "ui.effect_order_overrides",
                            index,
                            reason,
                        )
                    )
                    continue
                assert isinstance(item, dict)
                topology_reason = _effect_order_topology_error(
                    item,
                    effect_topologies,
                )
                if topology_reason is not None:
                    issues.append(
                        ParamStoreDecodeIssue(
                            "ui.effect_order_overrides",
                            index,
                            topology_reason,
                        )
                    )
                ui_seen_chain_ids.add(str(item["chain_id"]))
        for field in ("locked_parameters", "favorite_parameters"):
            entries = ui_obj.get(field, [])
            section = f"ui.{field}"
            if not isinstance(entries, list):
                issues.append(
                    ParamStoreDecodeIssue(
                        section,
                        None,
                        "expected a list",
                    )
                )
                continue
            for index, item in enumerate(entries):
                key = entry_key(item)
                if key is None:
                    issues.append(
                        ParamStoreDecodeIssue(
                            section,
                            index,
                            "expected op/site_id/arg object",
                        )
                    )
                elif key not in state_keys or key not in meta_keys:
                    issues.append(
                        ParamStoreDecodeIssue(
                            section,
                            index,
                            "matching state/meta is missing",
                        )
                    )
    return tuple(issues)


def decode_param_store_result(
    obj: object,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStoreDecodeResult:
    """JSON 由来 payload を schema migration/診断付きで復元する。"""

    migrated, migrated_legacy = _migrate_param_store_payload(obj)
    issues = _find_decode_issues(migrated)
    decodable = dict(migrated)
    for section in ("states", "meta", "labels", "effect_steps", "explicit", "variations"):
        if not isinstance(decodable.get(section, []), list):
            decodable[section] = []
    store = _decode_param_store_current(
        decodable,
        preserve_explicit_overrides=preserve_explicit_overrides,
    )
    return ParamStoreDecodeResult(
        store=store,
        issues=issues,
        migrated_legacy=migrated_legacy,
    )


def decode_param_store(
    obj: object,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStore:
    """JSON 由来 payload を復元し、読み取れた store を返す。"""

    return decode_param_store_result(
        obj,
        preserve_explicit_overrides=preserve_explicit_overrides,
    ).store


def loads_param_store(
    payload: str,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStore:
    """JSON 文字列から ParamStore を復元して返す。

    Notes
    -----
    - `json.loads()` の結果を `decode_param_store()` に渡す薄いラッパ。
    - 例外方針や修復ロジックは `decode_param_store()` 側に集約する。
    """

    return decode_param_store(
        json.loads(payload),
        preserve_explicit_overrides=preserve_explicit_overrides,
    )


def loads_param_store_result(
    payload: str,
    *,
    preserve_explicit_overrides: bool = False,
) -> ParamStoreDecodeResult:
    """JSON 文字列を migration/部分破損情報付きで復元する。"""

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
    "encode_param_store",
    "decode_param_store",
    "decode_param_store_result",
    "dumps_param_store",
    "loads_param_store",
    "loads_param_store_result",
    "param_store_schema_version",
]
