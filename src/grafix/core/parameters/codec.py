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

Notes
-----
- codec は永続化仕様を 1 箇所へ閉じるため、ParamStore の private な参照へアクセスする。
- decode は壊れた/古い/部分的な JSON を想定し、可能な範囲で復元して不正な要素は捨てる。
  例外で落とすのは「payload が dict ではない」ケースに限定する。
"""

from __future__ import annotations

import json
from typing import Any

from .key import ParameterKey
from .meta import ParamMeta
from .state import ParamState
from .store import ParamStore
from .view import canonicalize_ui_value


def encode_param_store(store: ParamStore) -> dict[str, Any]:
    """ParamStore を JSON 化可能な dict に変換して返す。

    Notes
    -----
    - 返す dict は `json.dumps()` 可能なプリミティブ（dict/list/str/int/float/bool/None）に
      射影した「永続化ペイロード」。
    - `states` は GUI 対象のみに限定するため、`meta` の無い state は含めない。
    - `explicit=True` な key（コード側で明示指定された kwargs）は「起動時はコードが勝つ」前提なので、
      `override=True` を保存せず、次回起動時は `override=False` から開始する。
    """

    # codec は ParamStore の内部表現へ直接アクセスする。
    # 目的: 「永続化の仕様」を 1 箇所に閉じ、ParamStore 本体を “入れ物” に保つ。
    labels = store._labels_ref().as_dict()
    ordinals = store._ordinals_ref().as_dict()
    effects = store._effects_ref()

    return {
        "states": [
            {
                "op": k.op,
                "site_id": k.site_id,
                "arg": k.arg,
                # 明示 kwargs は「起動時はコードが勝つ」が期待値なので、
                # override=True を永続化しない（次回起動で override=False から開始する）。
                "override": (
                    False
                    if store._explicit_by_key.get(k) is True
                    else bool(v.override)
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
                "kind": m.kind,
                "ui_min": m.ui_min,
                "ui_max": m.ui_max,
                "choices": list(m.choices) if m.choices is not None else None,
            }
            for k, m in store._meta.items()
        ],
        "labels": [
            {"op": op, "site_id": site_id, "label": label}
            for (op, site_id), label in labels.items()
        ],
        "ordinals": ordinals,
        "effect_steps": [
            {
                "op": op,
                "site_id": site_id,
                "chain_id": chain_id,
                "step_index": step_index,
            }
            for (op, site_id), (chain_id, step_index) in effects.step_info_by_site().items()
        ],
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
        },
    }


def dumps_param_store(store: ParamStore) -> str:
    """ParamStore を JSON 文字列へ変換して返す。

    Notes
    -----
    - JSON の生成は `json.dumps()` のデフォルト挙動に従う（整形/ソートなどは行わない）。
    - バイナリや圧縮などの「保存形式の選択」は、このレイヤでは扱わない。
    """

    return json.dumps(encode_param_store(store))


def decode_param_store(obj: object) -> ParamStore:
    """JSON 由来の dict から ParamStore を復元して返す。

    Parameters
    ----------
    obj : object
        `json.loads()` の結果（dict）を想定する。
        スキーマが古い/壊れている場合でも、可能な範囲で復元して不正な要素は捨てる。

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
            meta = ParamMeta(
                kind=str(item["kind"]),
                ui_min=item.get("ui_min"),
                ui_max=item.get("ui_max"),
                choices=item.get("choices"),
            )
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
        collapsed = ui_obj.get("collapsed_headers", [])
        if isinstance(collapsed, list):
            for item in collapsed:
                try:
                    store._collapsed_headers_ref().add(str(item))
                except Exception:
                    continue

    # explicit=True のキーは再起動時に override=False から開始する。
    # 目的: explicit=True は「コードが与えた base を優先」するのが自然なので、
    #       既定値として override を False に戻し、起動直後の挙動を安定させる。
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
    return store


def loads_param_store(payload: str) -> ParamStore:
    """JSON 文字列から ParamStore を復元して返す。

    Notes
    -----
    - `json.loads()` の結果を `decode_param_store()` に渡す薄いラッパ。
    - 例外方針や修復ロジックは `decode_param_store()` 側に集約する。
    """

    return decode_param_store(json.loads(payload))


__all__ = [
    "encode_param_store",
    "decode_param_store",
    "dumps_param_store",
    "loads_param_store",
]
