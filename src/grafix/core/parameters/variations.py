# どこで: `src/grafix/core/parameters/variations.py`。
# 何を: 名前付き parameter variation と、その編集・差分・復元操作を定義する。
# なぜ: 良い調整状態を失わず、再起動後も比較・再利用できるようにするため。

from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import deepcopy
from hashlib import sha256
import time
from dataclasses import dataclass, replace
from math import ceil, floor, isfinite
from pathlib import Path
from random import Random
from typing import TYPE_CHECKING, Any
from unicodedata import category

from .key import ParameterKey
from .memento import (
    ParamStoreMemento,
    capture_param_store_memento,
    restore_param_store_memento,
)
from .meta import ParamMeta
from .meta_spec import meta_from_record, meta_to_spec
from .state import ParamState
from .view import canonicalize_ui_value

if TYPE_CHECKING:
    from .history import ParamStoreHistory
    from .store import ParamStore


_MAX_VARIATION_NAME_LENGTH = 80


@dataclass(frozen=True, slots=True)
class Variation:
    """名前付きで保存した parameter 調整状態。

    ``parameter_snapshot`` は GUI-owned 値の memento であり、復元時に
    現在の code-owned 構造へ merge される。parameter lock は variation ごとの
    値ではなく現在の探索を守る store-level UI state のため、この snapshot には含めない。
    """

    name: str
    created_at: float
    note: str
    seed: int | None
    t: float | None
    parameter_snapshot: ParamStoreMemento
    thumbnail_path: str | None

    def __post_init__(self) -> None:
        name = _normalize_name(self.name)
        created_at = float(self.created_at)
        if not isfinite(created_at):
            raise ValueError("created_at must be finite")
        if not isinstance(self.note, str):
            raise TypeError("note must be a str")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise TypeError("seed must be an int or None")
        t = None if self.t is None else float(self.t)
        if t is not None and not isfinite(t):
            raise ValueError("t must be finite or None")
        if not isinstance(self.parameter_snapshot, ParamStoreMemento):
            raise TypeError("parameter_snapshot must be a ParamStoreMemento")
        if self.thumbnail_path is not None and not isinstance(self.thumbnail_path, str):
            raise TypeError("thumbnail_path must be a str or None")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "t", t)


@dataclass(frozen=True, slots=True)
class VariationDifference:
    """現在の store と variation 間の 1 parameter 分の差分。"""

    key: ParameterKey
    fields: tuple[str, ...]


def create_variation(
    store: ParamStore,
    name: str,
    *,
    note: str = "",
    seed: int | None = None,
    t: float | None = None,
    thumbnail_path: str | Path | None = None,
    created_at: float | None = None,
) -> Variation:
    """現在の調整状態を名前付き variation として保存する。

    同名 variation は暗黙に上書きしない。
    """

    normalized_name = _normalize_name(name)
    variations = store._variations_ref()
    if normalized_name in variations:
        raise ValueError(f"variation already exists: {normalized_name!r}")

    variation = Variation(
        name=normalized_name,
        created_at=time.time() if created_at is None else created_at,
        note=note,
        seed=seed,
        t=t,
        parameter_snapshot=capture_param_store_memento(store),
        thumbnail_path=(
            None if thumbnail_path is None else str(Path(thumbnail_path))
        ),
    )
    variations[variation.name] = variation
    store._touch()
    return variation


def duplicate_variation(
    store: ParamStore,
    name: str,
    new_name: str,
    *,
    created_at: float | None = None,
) -> Variation:
    """既存 variation の snapshot/metadata を独立した新名称で複製する。"""

    source_name = _normalize_name(name)
    duplicate_name = _normalize_name(new_name)
    variations = store._variations_ref()
    source = _require_variation(variations, source_name)
    if duplicate_name in variations:
        raise ValueError(f"variation already exists: {duplicate_name!r}")

    duplicate = replace(
        source,
        name=duplicate_name,
        created_at=time.time() if created_at is None else float(created_at),
        parameter_snapshot=deepcopy(source.parameter_snapshot),
    )
    variations[duplicate.name] = duplicate
    store._touch()
    return duplicate


def rename_variation(store: ParamStore, name: str, new_name: str) -> Variation:
    """variation の名前を変更し、内容と並び順は保つ。"""

    current_name = _normalize_name(name)
    normalized_new_name = _normalize_name(new_name)
    variations = store._variations_ref()
    variation = _require_variation(variations, current_name)
    if normalized_new_name == current_name:
        return variation
    if normalized_new_name in variations:
        raise ValueError(f"variation already exists: {normalized_new_name!r}")

    renamed = replace(variation, name=normalized_new_name)
    items = [
        (normalized_new_name, renamed) if key == current_name else (key, value)
        for key, value in variations.items()
    ]
    variations.clear()
    variations.update(items)
    store._touch()
    return renamed


def delete_variation(store: ParamStore, name: str) -> bool:
    """variation を削除する。存在しなければ False を返す。"""

    normalized_name = _normalize_name(name)
    variations = store._variations_ref()
    if normalized_name not in variations:
        return False
    del variations[normalized_name]
    store._touch()
    return True


def list_variations(store: ParamStore) -> tuple[Variation, ...]:
    """作成順の variation を読み取り専用 tuple で返す。"""

    return tuple(store._variations_ref().values())


def diff_variation(
    store: ParamStore,
    name: str,
) -> tuple[VariationDifference, ...]:
    """現在の parameter 状態と variation の差分を返す。"""

    variation = _require_variation(store._variations_ref(), _normalize_name(name))
    saved_states = variation.parameter_snapshot._states
    saved_meta = variation.parameter_snapshot._meta
    current_states = store._states
    current_meta = store._meta

    differences: list[VariationDifference] = []
    keys = set(saved_states) | set(current_states)
    for key in sorted(keys, key=lambda item: (item.op, item.site_id, item.arg)):
        saved_state = saved_states.get(key)
        saved_parameter_meta = saved_meta.get(key)
        current_state = current_states.get(key)
        current_parameter_meta = current_meta.get(key)
        fields: list[str] = []
        if saved_state is None or saved_parameter_meta is None:
            fields.append("added")
        elif current_state is None or current_parameter_meta is None:
            fields.append("missing")
        elif saved_parameter_meta.kind != current_parameter_meta.kind:
            fields.append("kind")
        else:
            if saved_state.override != current_state.override:
                fields.append("override")
            if saved_state.ui_value != current_state.ui_value:
                fields.append("ui_value")
            if saved_state.cc_key != current_state.cc_key:
                fields.append("cc_key")
            if saved_parameter_meta.ui_min != current_parameter_meta.ui_min:
                fields.append("ui_min")
            if saved_parameter_meta.ui_max != current_parameter_meta.ui_max:
                fields.append("ui_max")
        if fields:
            differences.append(VariationDifference(key=key, fields=tuple(fields)))
    return tuple(differences)


def restore_variation(
    store: ParamStore,
    name: str,
    *,
    history: ParamStoreHistory | None = None,
) -> bool:
    """variation を現在の code-owned 構造へ merge 復元する。

    ``history`` を渡した場合は、1 回の Undo 操作として記録する。
    variation 作成後に発見された parameter は削除しない。
    """

    normalized_name = _normalize_name(name)
    variation = _require_variation(store._variations_ref(), normalized_name)
    if history is None:
        return restore_param_store_memento(store, variation.parameter_snapshot)
    if history._store is not store:
        raise ValueError("history must belong to the same ParamStore")

    changed = False
    with history.transaction(source=("variation", normalized_name)):
        changed = restore_param_store_memento(store, variation.parameter_snapshot)
    return changed


def locked_parameter_keys(store: ParamStore) -> tuple[ParameterKey, ...]:
    """現在 lock されている parameter key を安定順の tuple で返す。"""

    return tuple(
        sorted(
            store._locked_keys_ref(),
            key=lambda key: (key.op, key.site_id, key.arg),
        )
    )


def is_parameter_locked(store: ParamStore, key: ParameterKey) -> bool:
    """``key`` が exploration 操作から保護されていれば True。"""

    if not isinstance(key, ParameterKey):
        raise TypeError("key must be a ParameterKey")
    return key in store._locked_keys_ref()


def set_parameters_locked(
    store: ParamStore,
    keys: Iterable[ParameterKey],
    *,
    locked: bool,
) -> tuple[ParameterKey, ...]:
    """scope 内の parameter lock を一括変更し、実際に変わった key を返す。

    lock 追加は現在の state/meta の両方に存在する key だけへ適用する。
    unlock は、code reload 後の stale key も明示的に除去できる。
    複数 key を変更しても store revision は 1 回だけ進む。
    """

    if not isinstance(locked, bool):
        raise TypeError("locked must be a bool")
    ordered_keys = _ordered_scope(keys)
    locked_keys = store._locked_keys_ref()
    changed: list[ParameterKey] = []
    for key in ordered_keys:
        if locked:
            if key not in store._states or key not in store._meta or key in locked_keys:
                continue
            locked_keys.add(key)
            changed.append(key)
        elif key in locked_keys:
            locked_keys.discard(key)
            changed.append(key)
    if changed:
        store._touch()
    return tuple(changed)


def randomize_parameters(
    store: ParamStore,
    keys: Iterable[ParameterKey],
    *,
    seed: int,
    history: ParamStoreHistory | None = None,
) -> tuple[ParameterKey, ...]:
    """scope 内の numeric parameter を seed 付きで randomize する。

    ``float`` / ``int`` / ``vec3`` / ``rgb`` だけが対象で、lock 済み key と
    range を持たない key は変更しない。range は ``recommended_range`` を
    優先し、未指定なら ``ui_min`` / ``ui_max`` を使う。vec3/rgb の scalar
    range は 3 成分すべてへ適用する。

    乱数列は ``seed + ParameterKey`` から key ごとに導出するため、scope の順序や
    他 key の追加・lock に左右されない。同じ seed/key/range は常に同じ値になる。
    変更値は UI override として有効化し、MIDI assignment は維持する。
    ``history`` を渡した場合、全変更を 1 回の Undo 操作として記録する。
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    _validate_history(store, history)
    ordered_keys = _ordered_scope(keys)

    def apply() -> tuple[ParameterKey, ...]:
        changed: list[ParameterKey] = []
        locked = store._locked_keys_ref()
        for key in ordered_keys:
            if key in locked:
                continue
            state = store._states.get(key)
            meta = store._meta.get(key)
            if state is None or meta is None:
                continue
            randomized = _randomized_value(meta, seed=seed, key=key)
            if randomized is _UNSUPPORTED:
                continue
            if state.ui_value == randomized and state.override:
                continue
            state.ui_value = randomized
            state.override = True
            changed.append(key)
        if changed:
            store._touch(structure=False, value_keys=changed)
        return tuple(changed)

    if history is None:
        return apply()
    history.break_coalescing()
    with history.transaction(source=("variation-randomize", int(seed))):
        return apply()


def morph_variations(
    store: ParamStore,
    a_name: str,
    b_name: str,
    amount: float,
    *,
    keys: Iterable[ParameterKey],
    history: ParamStoreHistory | None = None,
) -> tuple[ParameterKey, ...]:
    """2 variation の共通 parameter を ``amount`` で現在 store へ適用する。

    ``amount`` は 0..1。A/B 両 snapshot と現在 store で key/kind が共通する
    scope 内 parameter だけを対象とし、lock 済み key は変更しない。

    Policy
    ------
    - ``float`` / ``vec3``: 線形補間。
    - ``int`` / ``rgb``: 線形補間後に .5 を 0 から遠い整数へ丸める。
    - ``bool`` / ``choice`` / ``str`` / ``font``: ``amount < 0.5`` は A、
      ``amount >= 0.5`` は B。
    - UI ownership (``override``) と MIDI assignment (``cc_key``) も同じ
      0.5 境界の離散 policy で A/B を選ぶ。

    UI range や code-owned metadata は変更しない。``history`` を渡した場合、
    scope 全体の適用を 1 回の Undo 操作として記録する。
    """

    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise TypeError("amount must be a finite number in [0, 1]")
    normalized_amount = float(amount)
    if not isfinite(normalized_amount) or not 0.0 <= normalized_amount <= 1.0:
        raise ValueError("amount must be a finite number in [0, 1]")
    _validate_history(store, history)
    variation_a = _require_variation(store._variations_ref(), _normalize_name(a_name))
    variation_b = _require_variation(store._variations_ref(), _normalize_name(b_name))
    ordered_keys = _ordered_scope(keys)
    states_a = variation_a.parameter_snapshot._states
    states_b = variation_b.parameter_snapshot._states
    meta_a = variation_a.parameter_snapshot._meta
    meta_b = variation_b.parameter_snapshot._meta

    def apply() -> tuple[ParameterKey, ...]:
        changed: list[ParameterKey] = []
        locked = store._locked_keys_ref()
        use_b = normalized_amount >= 0.5
        for key in ordered_keys:
            if key in locked:
                continue
            current_state = store._states.get(key)
            current_meta = store._meta.get(key)
            state_a = states_a.get(key)
            state_b = states_b.get(key)
            saved_meta_a = meta_a.get(key)
            saved_meta_b = meta_b.get(key)
            if any(
                item is None
                for item in (
                    current_state,
                    current_meta,
                    state_a,
                    state_b,
                    saved_meta_a,
                    saved_meta_b,
                )
            ):
                continue
            assert current_state is not None
            assert current_meta is not None
            assert state_a is not None
            assert state_b is not None
            assert saved_meta_a is not None
            assert saved_meta_b is not None
            if not (
                current_meta.kind == saved_meta_a.kind == saved_meta_b.kind
            ):
                continue
            value = _morphed_value(
                current_meta,
                state_a.ui_value,
                state_b.ui_value,
                normalized_amount,
            )
            if value is _UNSUPPORTED:
                continue
            selected_state = state_b if use_b else state_a
            selected_cc = selected_state.cc_key
            if (
                current_state.ui_value == value
                and current_state.override == selected_state.override
                and current_state.cc_key == selected_cc
            ):
                continue
            current_state.ui_value = value
            current_state.override = bool(selected_state.override)
            current_state.cc_key = selected_cc
            changed.append(key)
        if changed:
            store._touch(structure=False, value_keys=changed)
        return tuple(changed)

    if history is None:
        return apply()
    history.break_coalescing()
    with history.transaction(
        source=("variation-morph", variation_a.name, variation_b.name)
    ):
        return apply()


_UNSUPPORTED = object()
_NUMERIC_KINDS = frozenset({"float", "int", "vec3", "rgb"})
_DISCRETE_KINDS = frozenset({"bool", "choice", "str", "font"})


def _ordered_scope(keys: Iterable[ParameterKey]) -> tuple[ParameterKey, ...]:
    if isinstance(keys, (str, bytes)) or not isinstance(keys, Iterable):
        raise TypeError("keys must be an iterable of ParameterKey")
    unique: set[ParameterKey] = set()
    for key in keys:
        if not isinstance(key, ParameterKey):
            raise TypeError("keys must contain only ParameterKey")
        unique.add(key)
    return tuple(sorted(unique, key=lambda key: (key.op, key.site_id, key.arg)))


def _validate_history(
    store: ParamStore,
    history: ParamStoreHistory | None,
) -> None:
    if history is not None and history._store is not store:
        raise ValueError("history must belong to the same ParamStore")


def _key_random(seed: int, key: ParameterKey) -> Random:
    payload = f"{int(seed)}\0{key.op}\0{key.site_id}\0{key.arg}".encode("utf-8")
    digest = sha256(payload).digest()
    return Random(int.from_bytes(digest[:16], "big"))


def _numeric_components(value: object, count: int) -> tuple[float, ...] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        normalized = float(value)
        if not isfinite(normalized):
            return None
        return (normalized,) * count
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return None
    if len(value) != count:
        return None
    out: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            return None
        normalized = float(component)
        if not isfinite(normalized):
            return None
        out.append(normalized)
    return tuple(out)


def _ranges_for_meta(
    meta: ParamMeta,
    *,
    count: int,
) -> tuple[tuple[float, float], ...] | None:
    recommended = meta.recommended_range
    lowers: tuple[float, ...]
    uppers: tuple[float, ...]
    if recommended is not None:
        lowers = (float(recommended[0]),) * count
        uppers = (float(recommended[1]),) * count
    else:
        ui_lowers = _numeric_components(meta.ui_min, count)
        ui_uppers = _numeric_components(meta.ui_max, count)
        if ui_lowers is None or ui_uppers is None:
            return None
        lowers = ui_lowers
        uppers = ui_uppers
    ranges = tuple(zip(lowers, uppers, strict=True))
    if any(lower > upper for lower, upper in ranges):
        return None
    return ranges


def _randomized_value(
    meta: ParamMeta,
    *,
    seed: int,
    key: ParameterKey,
) -> object:
    kind = str(meta.kind)
    if kind not in _NUMERIC_KINDS:
        return _UNSUPPORTED
    count = 3 if kind in {"vec3", "rgb"} else 1
    ranges = _ranges_for_meta(meta, count=count)
    if ranges is None:
        return _UNSUPPORTED
    rng = _key_random(seed, key)
    if kind == "float":
        lower, upper = ranges[0]
        return rng.uniform(lower, upper)
    if kind == "int":
        lower, upper = ranges[0]
        integer_lower = ceil(lower)
        integer_upper = floor(upper)
        if integer_lower > integer_upper:
            return _UNSUPPORTED
        return rng.randint(integer_lower, integer_upper)
    if kind == "vec3":
        return tuple(rng.uniform(lower, upper) for lower, upper in ranges)

    rgb_ranges = tuple(
        (max(0, ceil(lower)), min(255, floor(upper)))
        for lower, upper in ranges
    )
    if any(lower > upper for lower, upper in rgb_ranges):
        return _UNSUPPORTED
    return tuple(rng.randint(lower, upper) for lower, upper in rgb_ranges)


def _round_half_away_from_zero(value: float) -> int:
    return floor(value + 0.5) if value >= 0.0 else ceil(value - 0.5)


def _vector3(value: object) -> tuple[float, float, float] | None:
    components = _numeric_components(value, 3)
    if components is None:
        return None
    return components[0], components[1], components[2]


def _morphed_value(
    meta: ParamMeta,
    value_a: object,
    value_b: object,
    amount: float,
) -> object:
    kind = str(meta.kind)
    if kind in _DISCRETE_KINDS:
        selected = value_b if amount >= 0.5 else value_a
        return canonicalize_ui_value(selected, meta)
    if kind == "float":
        components_a = _numeric_components(value_a, 1)
        components_b = _numeric_components(value_b, 1)
        if components_a is None or components_b is None:
            return _UNSUPPORTED
        float_a = components_a[0]
        float_b = components_b[0]
        if not isfinite(float_a) or not isfinite(float_b):
            return _UNSUPPORTED
        return float_a + (float_b - float_a) * amount
    if kind == "int":
        components_a = _numeric_components(value_a, 1)
        components_b = _numeric_components(value_b, 1)
        if components_a is None or components_b is None:
            return _UNSUPPORTED
        int_a = components_a[0]
        int_b = components_b[0]
        return _round_half_away_from_zero(int_a + (int_b - int_a) * amount)
    if kind in {"vec3", "rgb"}:
        vector_a = _vector3(value_a)
        vector_b = _vector3(value_b)
        if vector_a is None or vector_b is None:
            return _UNSUPPORTED
        interpolated = tuple(
            component_a + (component_b - component_a) * amount
            for component_a, component_b in zip(vector_a, vector_b, strict=True)
        )
        if kind == "vec3":
            return interpolated
        return tuple(
            max(0, min(255, _round_half_away_from_zero(component)))
            for component in interpolated
        )
    return _UNSUPPORTED


def _normalize_name(name: object) -> str:
    if not isinstance(name, str):
        raise TypeError("variation name must be a str")
    if any(category(character) in {"Cc", "Cs", "Zl", "Zp"} for character in name):
        raise ValueError(
            "variation name must not contain line breaks or control characters"
        )
    normalized = name.strip()
    if not normalized:
        raise ValueError("variation name must not be empty")
    if len(normalized) > _MAX_VARIATION_NAME_LENGTH:
        raise ValueError(
            "variation name must be at most "
            f"{_MAX_VARIATION_NAME_LENGTH} characters"
        )
    return normalized


def _require_variation(
    variations: dict[str, Variation],
    name: str,
) -> Variation:
    try:
        return variations[name]
    except KeyError:
        raise KeyError(f"unknown variation: {name!r}") from None


def _encode_variation(variation: Variation) -> dict[str, Any]:
    """codec 向けに variation を JSON 化可能な dict へ射影する。"""

    snapshot = variation.parameter_snapshot
    return {
        "name": variation.name,
        "created_at": variation.created_at,
        "note": variation.note,
        "seed": variation.seed,
        "t": variation.t,
        "thumbnail_path": variation.thumbnail_path,
        "parameter_snapshot": {
            "states": [
                {
                    "op": key.op,
                    "site_id": key.site_id,
                    "arg": key.arg,
                    "override": bool(state.override),
                    "ui_value": state.ui_value,
                    "cc_key": state.cc_key,
                }
                for key, state in snapshot._states.items()
                if key in snapshot._meta
            ],
            "meta": [
                {
                    "op": key.op,
                    "site_id": key.site_id,
                    "arg": key.arg,
                    **meta_to_spec(meta),
                }
                for key, meta in snapshot._meta.items()
            ],
            "collapsed_by_header": dict(snapshot._collapsed_by_header),
        },
    }


def _decode_variation(obj: object) -> Variation | None:
    """JSON 由来の 1 entry を復元する。不正 entry は None。"""

    if not isinstance(obj, dict):
        return None
    snapshot_obj = obj.get("parameter_snapshot")
    if not isinstance(snapshot_obj, dict):
        return None

    meta_by_key: dict[ParameterKey, ParamMeta] = {}
    meta_items = snapshot_obj.get("meta", [])
    if isinstance(meta_items, list):
        for item in meta_items:
            if not isinstance(item, dict):
                continue
            try:
                key = _decode_key(item)
                meta_by_key[key] = meta_from_record(item)
            except Exception:
                continue

    states: dict[ParameterKey, ParamState] = {}
    state_items = snapshot_obj.get("states", [])
    if isinstance(state_items, list):
        for item in state_items:
            if not isinstance(item, dict):
                continue
            try:
                key = _decode_key(item)
                meta = meta_by_key[key]
                states[key] = ParamState(
                    override=bool(item.get("override", True)),
                    ui_value=canonicalize_ui_value(item.get("ui_value"), meta),
                    cc_key=_decode_cc_key(item.get("cc_key")),
                )
            except Exception:
                continue

    raw_collapsed = snapshot_obj.get("collapsed_by_header", {})
    collapsed_by_header = (
        {str(key): bool(value) for key, value in raw_collapsed.items()}
        if isinstance(raw_collapsed, dict)
        else {}
    )
    try:
        memento = ParamStoreMemento._from_gui_owned_parts(
            states=states,
            meta={key: meta_by_key[key] for key in states},
            collapsed_by_header=collapsed_by_header,
        )
        raw_seed = obj.get("seed")
        seed = raw_seed if isinstance(raw_seed, int) and not isinstance(raw_seed, bool) else None
        raw_thumbnail = obj.get("thumbnail_path")
        thumbnail_path = raw_thumbnail if isinstance(raw_thumbnail, str) else None
        return Variation(
            name=obj["name"],
            created_at=obj["created_at"],
            note=obj.get("note", ""),
            seed=seed,
            t=obj.get("t"),
            parameter_snapshot=memento,
            thumbnail_path=thumbnail_path,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _decode_key(item: dict[str, Any]) -> ParameterKey:
    return ParameterKey(
        op=str(item["op"]),
        site_id=str(item["site_id"]),
        arg=str(item["arg"]),
    )


def _decode_cc_key(
    value: object,
) -> int | tuple[int | None, int | None, int | None] | None:
    def to_int(item: object) -> int | None:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            return None
        try:
            return int(item)
        except ValueError:
            return None

    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        decoded = (to_int(value[0]), to_int(value[1]), to_int(value[2]))
        return None if decoded == (None, None, None) else decoded
    return to_int(value)


__all__ = [
    "Variation",
    "VariationDifference",
    "create_variation",
    "delete_variation",
    "diff_variation",
    "duplicate_variation",
    "is_parameter_locked",
    "list_variations",
    "locked_parameter_keys",
    "morph_variations",
    "randomize_parameters",
    "rename_variation",
    "restore_variation",
    "set_parameters_locked",
]
