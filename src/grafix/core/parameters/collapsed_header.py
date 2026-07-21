"""Parameter GUI の折りたたみヘッダを表す canonical identity。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from .identity import GroupKey, group_key, identity_string

CollapsedHeaderKind = Literal[
    "style",
    "primitive",
    "preset",
    "effect_chain",
]

_COLLAPSED_HEADER_KINDS = frozenset(
    {"style", "primitive", "preset", "effect_chain"}
)
_OPERATION_HEADER_KINDS = frozenset({"primitive", "preset"})


@dataclass(frozen=True, slots=True)
class CollapsedHeaderKey:
    """折りたたみ対象を曖昧な prefix 文字列を使わず識別する値。"""

    kind: CollapsedHeaderKind
    op: str | None = None
    site_id: str | None = None
    chain_id: str | None = None

    def __post_init__(self) -> None:
        kind = self.kind
        if type(kind) is not str:
            raise TypeError("collapsed header kind must be an exact string")
        if kind not in _COLLAPSED_HEADER_KINDS:
            raise ValueError(f"unsupported collapsed header kind: {kind!r}")
        object.__setattr__(self, "kind", cast(CollapsedHeaderKind, kind))

        if kind == "style":
            if (
                self.op is not None
                or self.site_id is not None
                or self.chain_id is not None
            ):
                raise ValueError(
                    "style collapsed header cannot have an owner identity"
                )
            return

        if kind in _OPERATION_HEADER_KINDS:
            identity_string(self.op, name="collapsed header op")
            identity_string(self.site_id, name="collapsed header site_id")
            if self.chain_id is not None:
                raise ValueError("operation collapsed header cannot have chain_id")
            return

        identity_string(self.chain_id, name="collapsed header chain_id")
        if self.op is not None or self.site_id is not None:
            raise ValueError("effect-chain collapsed header cannot have op/site_id")

    def sort_key(self) -> tuple[str, str, str]:
        """永続化で使う安定ソートキーを返す。"""

        return (
            self.kind,
            "" if self.op is None else self.op,
            (
                self.chain_id
                if self.chain_id is not None
                else "" if self.site_id is None else self.site_id
            ),
        )


STYLE_COLLAPSED_HEADER_KEY = CollapsedHeaderKey(kind="style")


def primitive_collapsed_header_key(group: GroupKey) -> CollapsedHeaderKey:
    """primitive group の折りたたみキーを返す。"""

    op, site_id = group_key(group, name="primitive collapsed header group")
    return CollapsedHeaderKey(kind="primitive", op=op, site_id=site_id)


def preset_collapsed_header_key(group: GroupKey) -> CollapsedHeaderKey:
    """preset group の折りたたみキーを返す。"""

    op, site_id = group_key(group, name="preset collapsed header group")
    return CollapsedHeaderKey(kind="preset", op=op, site_id=site_id)


def group_collapsed_header_keys(
    group: GroupKey,
) -> tuple[CollapsedHeaderKey, ...]:
    """registry 非依存で group が取り得る primitive/preset キーを返す。"""

    normalized = group_key(group, name="collapsed header group")
    return (
        primitive_collapsed_header_key(normalized),
        preset_collapsed_header_key(normalized),
    )


def effect_chain_collapsed_header_key(chain_id: str) -> CollapsedHeaderKey:
    """effect chain の折りたたみキーを返す。"""

    return CollapsedHeaderKey(
        kind="effect_chain",
        chain_id=identity_string(chain_id, name="effect chain id"),
    )


def encode_collapsed_header_key(key: CollapsedHeaderKey) -> dict[str, str]:
    """折りたたみキーを ParamStore v4 の tagged record へ変換する。"""

    if type(key) is not CollapsedHeaderKey:
        raise TypeError("collapsed header key must be a CollapsedHeaderKey")
    if key.kind == "style":
        return {"kind": "style"}
    if key.kind in _OPERATION_HEADER_KINDS:
        assert key.op is not None and key.site_id is not None
        return {"kind": key.kind, "op": key.op, "site_id": key.site_id}
    assert key.chain_id is not None
    return {"kind": "effect_chain", "chain_id": key.chain_id}


def decode_collapsed_header_key(value: object) -> CollapsedHeaderKey:
    """ParamStore v4 の tagged record を strict に検証して返す。"""

    if type(value) is not dict:
        raise TypeError("collapsed header must be an object")
    record = cast(dict[object, Any], value)
    if any(type(field) is not str for field in record):
        raise TypeError("collapsed header fields must be strings")
    kind = record.get("kind")
    if type(kind) is not str:
        raise TypeError("collapsed header kind must be an exact string")

    if kind == "style":
        _require_fields(record, {"kind"})
        return STYLE_COLLAPSED_HEADER_KEY
    if kind in _OPERATION_HEADER_KINDS:
        _require_fields(record, {"kind", "op", "site_id"})
        return CollapsedHeaderKey(
            kind=cast(CollapsedHeaderKind, kind),
            op=record["op"],
            site_id=record["site_id"],
        )
    if kind == "effect_chain":
        _require_fields(record, {"kind", "chain_id"})
        return CollapsedHeaderKey(
            kind="effect_chain",
            chain_id=record["chain_id"],
        )
    raise ValueError(f"unsupported collapsed header kind: {kind!r}")


def _require_fields(record: dict[object, Any], expected: set[str]) -> None:
    fields = set(cast(str, field) for field in record)
    missing = sorted(expected - fields)
    unknown = sorted(fields - expected)
    if not missing and not unknown:
        return
    details: list[str] = []
    if missing:
        details.append(f"missing fields: {', '.join(missing)}")
    if unknown:
        details.append(f"unknown fields: {', '.join(unknown)}")
    raise ValueError("; ".join(details))


__all__ = [
    "CollapsedHeaderKey",
    "CollapsedHeaderKind",
    "STYLE_COLLAPSED_HEADER_KEY",
    "decode_collapsed_header_key",
    "effect_chain_collapsed_header_key",
    "encode_collapsed_header_key",
    "group_collapsed_header_keys",
    "preset_collapsed_header_key",
    "primitive_collapsed_header_key",
]
