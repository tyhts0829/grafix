# src/grafix/core/geometry.py
# Grafix コアの Geometry ノード定義。
# 幾何レシピ DAG の中核モデルと署名生成を実装する。

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import blake2b
from math import isfinite
from struct import Struct
from types import NotImplementedType
from typing import Any, Mapping, Sequence

GeometryId = str

DEFAULT_SCHEMA_VERSION = 2

_SIGNATURE_DOMAIN = b"grafix.geometry.v2\x00"
_UINT64 = Struct(">Q")
_FLOAT64 = Struct(">d")
_PACK_UINT64 = _UINT64.pack
_PACK_FLOAT64 = _FLOAT64.pack
_REPR_PERSON = b"grafix.geom.v2r"
_TAG_ENUM = ord("e")
_TAG_FLOAT = ord("f")
_TAG_INT = ord("i")
_TAG_NONE = ord("n")
_TAG_STR = ord("s")
_TAG_TUPLE = ord("t")


def _append_frame(buffer: bytearray, payload: bytes) -> None:
    """可変長 payload を長さ付きで buffer へ追加する。"""

    buffer.extend(_PACK_UINT64(len(payload)))
    buffer.extend(payload)


def _append_signature_value(buffer: bytearray, value: Any) -> None:
    """正規化済み値の型付き表現を buffer へ追加する。

    実行関数へ渡す値そのものは変更せず、buffer に追加する表現だけを
    GeometryId の計算に使用する。
    """

    if value is None:
        buffer.append(_TAG_NONE)
        return

    value_type = type(value)
    if value_type is bool:
        buffer.extend(b"b\x01" if value else b"b\x00")
        return
    if value_type is int:
        buffer.append(_TAG_INT)
        _append_frame(buffer, str(value).encode("ascii"))
        return
    if value_type is float:
        if not isfinite(value):
            raise ValueError("非有限の float は Geometry 引数に使用できない")
        normalized = 0.0 if value == 0.0 else value
        buffer.append(_TAG_FLOAT)
        buffer.extend(_PACK_FLOAT64(normalized))
        return
    if value_type is str:
        buffer.append(_TAG_STR)
        _append_frame(buffer, value.encode("utf-8"))
        return
    if value_type is tuple:
        buffer.append(_TAG_TUPLE)
        buffer.extend(_PACK_UINT64(len(value)))
        for item in value:
            _append_signature_value(buffer, item)
        return
    if isinstance(value, Enum):
        buffer.append(_TAG_ENUM)
        _append_frame(buffer, value_type.__module__.encode("utf-8"))
        _append_frame(buffer, value_type.__qualname__.encode("utf-8"))
        _append_frame(buffer, value.name.encode("utf-8"))
        return
    raise TypeError(f"署名に使用できない値型: {type(value)!r}")


def _encode_signature_value(value: Any) -> bytes:
    """正規化済み値を型付きの署名用 bytes に変換する。"""

    buffer = bytearray()
    _append_signature_value(buffer, value)
    return bytes(buffer)


def _normalize_value(value: Any) -> Any:
    """引数値を evaluator が受け取る不変な値へ正規化する。

    Parameters
    ----------
    value : Any
        元の値。

    Returns
    -------
    Any
        正規化済み値。

    Raises
    ------
    TypeError
        サポートされない型が渡された場合。
    ValueError
        float の値が NaN/inf の場合。
    """
    value_type = type(value)
    if value is None:
        return None
    if value_type is bool or value_type is int or value_type is str:
        return value
    if value_type is float:
        if not isfinite(value):
            raise ValueError("非有限の float は Geometry 引数に使用できない")
        return 0.0 if value == 0.0 else value
    if value_type is tuple or value_type is list:
        return tuple(map(_normalize_value, value))

    # IntEnum / str Enum は underlying built-in より先に判定する。
    if isinstance(value, Enum):
        return value
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        normalized = float(value)
        if not isfinite(normalized):
            raise ValueError("非有限の float は Geometry 引数に使用できない")
        return 0.0 if normalized == 0.0 else normalized
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple)):
        return tuple(map(_normalize_value, value))
    if isinstance(value, Mapping):
        items = [(_normalize_value(k), _normalize_value(v)) for k, v in value.items()]
        items.sort(key=lambda item: _encode_signature_value(item[0]))
        return tuple(items)
    raise TypeError(f"正規化できない引数型: {type(value)!r}")


def _contains_enum(value: Any) -> bool:
    """正規化済み tuple tree に Enum が含まれるかを調べる。"""

    if type(value) is not tuple:
        return isinstance(value, Enum)
    for item in value:
        if _contains_enum(item):
            return True
    return False


def normalize_args(params: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    """パラメータ辞書を evaluator 用の不変な引数タプルに変換する。

    Parameters
    ----------
    params : Mapping[str, Any]
        元の引数辞書。

    Returns
    -------
    tuple[tuple[str, Any], ...]
        キーでソートされた (名前, 正規化値) のタプル列。
    """
    names = tuple(params.keys())
    if any(not isinstance(name, str) for name in names):
        raise TypeError("Geometry 引数名は str である必要がある")

    items: list[tuple[str, Any]] = []
    for name in sorted(names):
        raw_value = params[name]
        normalized = _normalize_value(raw_value)
        items.append((str(name), normalized))
    return tuple(items)


def compute_geometry_id(
    op: str,
    inputs: Sequence["Geometry"],
    args: tuple[tuple[str, Any], ...],
    *,
    schema_version: int = DEFAULT_SCHEMA_VERSION,
) -> GeometryId:
    """GeometryId（内容署名）を計算する。

    Parameters
    ----------
    op : str
        演算子名。
    inputs : Sequence[Geometry]
        子ノード列。
    args : tuple[tuple[str, Any], ...]
        正規化済み引数タプル。
    schema_version : int, optional
        署名スキーマのバージョン。

    Returns
    -------
    GeometryId
        内容署名に基づく ID。
    """
    signature = (
        int(schema_version),
        op,
        tuple(g.id for g in inputs),
        args,
    )
    if not _contains_enum(args):
        # 正規化後の閉じた built-in 型集合では repr が型と境界を保持する。
        # Python 実装の tuple serializer にまとめて任せ、再帰的な bytearray
        # 追記を典型パスから外す。
        payload = repr(signature).encode("utf-8")
        return blake2b(
            payload,
            digest_size=16,
            person=_REPR_PERSON,
        ).hexdigest()

    # Enum の repr はユーザーが上書きできるため、canonical identity
    # (module, qualname, member name) を明示する型付き encoder を使う。
    payload = bytearray(_SIGNATURE_DOMAIN)
    _append_signature_value(payload, signature)
    return blake2b(payload, digest_size=16).hexdigest()


@dataclass(frozen=True, slots=True)
class Geometry:
    """幾何レシピを表す不変 Geometry ノード。

    Parameters
    ----------
    id : GeometryId
        内容署名に基づく GeometryId。
    op : str
        演算子名。primitive/effect/combine を区別せず保存する。
    inputs : tuple[Geometry, ...]
        子ノード列。primitive の場合は空タプル。
    args : tuple[tuple[str, Any], ...]
        正規化済み引数の (名前, 値) タプル列。

    Notes
    -----
    インスタンスは不変とし、内容が同じであれば同じ id になる設計とする。
    """

    id: GeometryId
    op: str
    inputs: tuple["Geometry", ...]
    args: tuple[tuple[str, Any], ...]

    @classmethod
    def create(
        cls,
        op: str,
        *,
        inputs: Sequence["Geometry"] | None = None,
        params: Mapping[str, Any] | None = None,
        schema_version: int = DEFAULT_SCHEMA_VERSION,
    ) -> "Geometry":
        """演算子名とパラメータから Geometry ノードを生成する。

        Parameters
        ----------
        op : str
            演算子名。
        inputs : Sequence[Geometry] or None, optional
            子ノード列。省略時は空とみなす。
        params : Mapping[str, Any] or None, optional
            元の引数辞書。None の場合は空辞書とみなす。
        schema_version : int, optional
            署名スキーマのバージョン。

        Returns
        -------
        Geometry
            生成された Geometry ノード。
        """
        if inputs is None:
            inputs_seq: Sequence["Geometry"] = ()
        else:
            inputs_seq = inputs
        if params is None:
            params = {}

        normalized_args = normalize_args(
            params,
        )
        inputs_tuple = tuple(inputs_seq)
        geometry_id = compute_geometry_id(
            op=op,
            inputs=inputs_tuple,
            args=normalized_args,
            schema_version=schema_version,
        )
        return cls(
            id=geometry_id,
            op=op,
            inputs=inputs_tuple,
            args=normalized_args,
        )

    @staticmethod
    def _concat(*geometries: "Geometry") -> "Geometry":
        """Geometry を `concat` としてまとめる。"""
        inputs: list[Geometry] = []
        for g in geometries:
            if g.op == "concat" and not g.args:
                inputs.extend(g.inputs)
            else:
                inputs.append(g)

        if len(inputs) == 1:
            return inputs[0]
        return Geometry.create(op="concat", inputs=tuple(inputs), params={})

    def __add__(self, other: object) -> "Geometry | NotImplementedType":
        """`g1 + g2` を `concat` として表現する。"""
        if not isinstance(other, Geometry):
            return NotImplemented
        return Geometry._concat(self, other)

    def __radd__(self, other: object) -> "Geometry | NotImplementedType":
        """`sum([...])` のために `0 + Geometry` を許可する。"""
        if other == 0:
            return self
        if not isinstance(other, Geometry):
            return NotImplemented
        return Geometry._concat(other, self)
