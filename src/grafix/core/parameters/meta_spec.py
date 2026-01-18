"""ユーザー入力の meta spec（辞書）を `ParamMeta` に正規化する。

このモジュールは、外部（sketch / 公開 API）から渡される「軽量な辞書 spec」を、
内部の統一表現である :class:`grafix.core.parameters.meta.ParamMeta` に変換する責務を持つ。

ポイント
--------
- 公開 API 側で `ParamMeta` を import しなくても meta を渡せるようにする。
- 一方で内部は `ParamMeta` に統一し、型・キーの揺れをここで吸収する。
- 正規化は「検証 + 最小限の変換」に留める（ui_min/ui_max は値の意味解釈をしない）。

副作用
------
- なし（入力を検証し、新しい `ParamMeta` / dict を返すだけ）
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .meta import ParamMeta

# dict spec として受理するキーを固定し、入力仕様を小さく保つ。
_ALLOWED_META_SPEC_KEYS = {"kind", "ui_min", "ui_max", "choices"}


def meta_from_spec(spec: ParamMeta | Mapping[str, object]) -> ParamMeta:
    """dict spec または `ParamMeta` から `ParamMeta` を返す。

    公開 API で扱いやすい「辞書の meta spec」を受け取り、内部表現 `ParamMeta` に変換する。
    すでに `ParamMeta` が渡された場合はそのまま返す（コピーしない）。

    Parameters
    ----------
    spec : ParamMeta | Mapping[str, object]
        `ParamMeta` または dict spec。

        dict spec の形式:
        - kind: str（必須）
        - ui_min/ui_max: object（任意）
        - choices: Sequence[str] | None（任意）

        注意:
        - ui_min/ui_max の型・大小関係などはここでは検証しない（UI 側の都合があるため）。
        - choices の要素は `str(...)` で文字列化して格納する。

    Raises
    ------
    TypeError
        spec の型が不正な場合。
    ValueError
        必須キー欠落や未知キーなど、spec の内容が不正な場合。
    """

    # `ParamMeta` を受け取った場合は、そのまま内部表現として採用する。
    if isinstance(spec, ParamMeta):
        return spec
    # 外部入力は dict 相当（Mapping）だけを受ける。list などはここでは許可しない。
    if not isinstance(spec, Mapping):
        raise TypeError("meta spec は ParamMeta または dict である必要があります")

    # 入力キーの「typo」や「意図しない追加」を早期に検出するため、許可キー以外は弾く。
    unknown = set(spec.keys()) - _ALLOWED_META_SPEC_KEYS
    if unknown:
        names = ", ".join(sorted(str(k) for k in unknown))
        raise ValueError(f"meta spec に未知キーがあります: {names}")

    # kind は必須。ここが `ParamMeta` の識別子（UI/表示のためのカテゴリ）になる。
    if "kind" not in spec:
        raise ValueError("meta spec には 'kind' が必要です")
    kind = spec["kind"]
    if not isinstance(kind, str):
        raise TypeError("meta spec の 'kind' は str である必要があります")

    # ui_min/ui_max は UI ヒント用の生値を保持するだけ（型や整合性の解釈はしない）。
    ui_min = spec.get("ui_min", None)
    ui_max = spec.get("ui_max", None)

    raw_choices = spec.get("choices", None)
    choices: Sequence[str] | None
    if raw_choices is None:
        choices = None
    else:
        # str/bytes は Sequence として扱えるが、文字列を「選択肢の列」と誤認しやすいので弾く。
        if isinstance(raw_choices, (str, bytes)):
            raise TypeError("meta spec の 'choices' は Sequence[str] である必要があります")
        if not isinstance(raw_choices, Sequence):
            raise TypeError("meta spec の 'choices' は Sequence[str] である必要があります")
        # list など可変の可能性があるため、ここで tuple にして安定化する。
        choices = tuple(str(x) for x in raw_choices)

    return ParamMeta(kind=str(kind), ui_min=ui_min, ui_max=ui_max, choices=choices)


def meta_dict_from_user(
    meta: Mapping[str, ParamMeta | Mapping[str, object]],
) -> dict[str, ParamMeta]:
    """ユーザー入力 meta を `dict[str, ParamMeta]` へ正規化して返す。

    `meta` は「引数名 -> meta spec」の辞書を想定する。
    各値は `ParamMeta` そのもの、または :func:`meta_from_spec` が受理する dict spec。

    Parameters
    ----------
    meta : Mapping[str, ParamMeta | Mapping[str, object]]
        正規化前の meta 辞書。

    Returns
    -------
    dict[str, ParamMeta]
        引数名をキーに、値を `ParamMeta` に統一した辞書。

    Raises
    ------
    TypeError
        キーが str でない場合。
        値が `meta_from_spec` の受理範囲でない場合。
    ValueError
        値の dict spec に未知キー・必須キー欠落などがある場合。
    """

    out: dict[str, ParamMeta] = {}
    for arg, spec in meta.items():
        # 引数名は API の外側から来るので型を厳密に揃える（str 以外は許可しない）。
        if not isinstance(arg, str):
            raise TypeError("meta のキー（引数名）は str である必要があります")
        out[arg] = meta_from_spec(spec)
    return out


__all__ = ["meta_from_spec", "meta_dict_from_user"]
