# どこで: `src/grafix/interactive/parameter_gui/snippet.py`。
# 何を: Parameter GUI の状態から「コピペ可能な Python スニペット文字列」を生成する純粋関数を提供する。
# なぜ: UI（imgui）から分離し、出力仕様をユニットテストで担保するため。

"""Parameter GUI の状態から「コピペ可能な Python スニペット」を生成する。

このモジュールは、UI（imgui など）の描画やイベント処理から切り離した **純粋関数** を提供する。
入力は Parameter GUI が持つブロック表現（`GroupBlock` / `ParameterRow`）で、出力は
`P.` / `G.` / `E.` などの呼び出しを組み立てた **Python コード断片（文字列）**。

生成されるスニペットは「関数内へ貼る」用途を想定し、全行が `_CODE_INDENT` だけインデントされている。
（返り値が空文字の場合は、そのブロックからは出力しない）

副作用
------
なし。入力から文字列を組み立てて返すだけ。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.layer_style import (
    LAYER_STYLE_LINE_COLOR,
    LAYER_STYLE_LINE_THICKNESS,
    LAYER_STYLE_OP,
)
from grafix.core.parameters.style import (
    STYLE_BACKGROUND_COLOR,
    STYLE_GLOBAL_LINE_COLOR,
    STYLE_GLOBAL_THICKNESS,
    STYLE_OP,
    coerce_rgb255,
    rgb255_to_rgb01,
)
from grafix.core.parameters.view import ParameterRow
from grafix.core.preset_registry import preset_registry

from .group_blocks import GroupBlock


_CODE_INDENT = "    "


def _indent_code(code: str) -> str:
    """コード文字列を “全行” インデントして返す。

    Parameters
    ----------
    code:
        インデントしたいコード文字列（複数行可）。

    Returns
    -------
    str
        各行の先頭に `_CODE_INDENT` を付与した文字列。
        入力が末尾改行で終わる場合は、その改行を保持する。

    Notes
    -----
    `splitlines()` は末尾の空行（トレーリング改行）を落とすため、
    改行の有無を別途保持してから組み立てる。
    """

    if not code:
        return ""
    has_trailing_newline = code.endswith("\n")
    lines = code.splitlines()
    out = "\n".join(_CODE_INDENT + line for line in lines)
    return out + ("\n" if has_trailing_newline else "")


def _effective_or_ui_value(
    row: ParameterRow,
    *,
    last_effective_by_key: Mapping[ParameterKey, object] | None,
) -> object:
    """スニペットに埋め込む値（実効値 or UI 値）を返す。

    Parameter GUI では、表示・編集用の値（`row.ui_value`）と、内部で確定した実効値が
    ずれることがある（入力正規化、型変換、choice の丸めなど）。
    `last_effective_by_key` が渡されていれば、その実効値を優先してスニペットへ出力する。

    Parameters
    ----------
    row:
        GUI の 1 行（op/site_id/arg/ui_value など）。
    last_effective_by_key:
        `ParameterKey(op, site_id, arg)` -> 実効値 のマップ。未指定なら常に UI 値を使う。

    Returns
    -------
    object
        スニペットに埋め込む値。
    """

    # `ParameterRow` 自体はキーではないので、(op, site_id, arg) から ParameterKey を復元して照合する。
    key = ParameterKey(op=row.op, site_id=row.site_id, arg=row.arg)
    if last_effective_by_key is not None and key in last_effective_by_key:
        return last_effective_by_key[key]
    return row.ui_value


def _py_literal(value: object) -> str:
    """任意の値を「Python のリテラルっぽい」文字列へ変換する。

    スニペットは「コピペしてそのまま実行できる」ことが最優先のため、まずは代表的な型だけを
    明示的にハンドリングし、それ以外は `repr()` に寄せる。

    Parameters
    ----------
    value:
        変換対象。

    Returns
    -------
    str
        Python ソースコードとして埋め込める見た目の文字列。
    """

    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        # `str(0.1)` は丸めが入り得るので、基本は `repr(float)` で “再現可能な表現” を優先する。
        return repr(float(value))
    if isinstance(value, str):
        return repr(str(value))
    if isinstance(value, tuple):
        # 1 要素タプルは末尾カンマが無いとただの括弧式になるため、必ず付ける。
        return "(" + ", ".join(_py_literal(v) for v in value) + (")" if len(value) != 1 else ",)")
    if isinstance(value, list):
        return "[" + ", ".join(_py_literal(v) for v in value) + "]"
    # numpy scalar などは repr が長くなりやすいので、まずは str に寄せる。
    try:
        return repr(value)
    except Exception:
        return repr(str(value))


def _format_kwargs_call(prefix: str, *, op: str, kwargs: Sequence[tuple[str, str]]) -> str:
    """`prefix + op` の呼び出し（kwargs）を、読みやすい複数行形式で整形する。

    Parameters
    ----------
    prefix:
        先頭に付ける接頭辞（例: `"G."` / `"E(name='foo')."`）。
    op:
        呼び出し名（例: `"circle"` / `"blur"`）。
    kwargs:
        `(key, value_literal)` の列。`value_literal` は `_py_literal()` 済みを想定する。

    Returns
    -------
    str
        `prefix + op(...)` のコード文字列（まだ `_indent_code` は掛けない）。

    Notes
    -----
    ここでのインデントは「括弧の内側」を 4 スペースで揃えるだけ。
    最終的な貼り付け用インデントは `_indent_code()` が担う。
    """

    if not kwargs:
        return f"{prefix}{op}()"
    lines = [f"{prefix}{op}("]
    for k, v in kwargs:
        lines.append(f"    {k}={v},")
    lines.append(")")
    return "\n".join(lines)


def snippet_for_block(
    block: GroupBlock,
    *,
    last_effective_by_key: Mapping[ParameterKey, object] | None = None,
    layer_style_name_by_site_id: Mapping[str, str] | None = None,
    step_info_by_site: Mapping[tuple[str, str], tuple[str, int]] | None = None,
    raw_label_by_site: Mapping[tuple[str, str], str] | None = None,
) -> str:
    """1 ブロック（collapsing header 1 つ相当）のスニペットを返す。

    Parameters
    ----------
    block:
        `GroupBlock`（連続する group を 1 つにまとめたもの）。
    last_effective_by_key:
        UI 値ではなく実効値で出したい場合の参照マップ。
    layer_style_name_by_site_id:
        将来用の引数（現在は未使用）。
    step_info_by_site:
        effect_chain の「並び順」を安定させるための補助情報。
        `((op, site_id) -> (chain_id, step_index))` を想定する。
    raw_label_by_site:
        GUI 上でユーザーが付けた “生のラベル”。
        `((op, site_id) -> label)` の形で渡すと、`P(name=...)` / `G(name=...)` / `E(name=...)` などに反映される。

    Returns
    -------
    str
        貼り付け用に `_CODE_INDENT` でインデント済みのコード断片。
        生成対象が無い場合は空文字。

    Notes
    -----
    - `group_type` ごとに出力フォーマットが異なる（style / preset / primitive / effect_chain）。
    - 返り値は **末尾改行あり**（空文字を除く）。
    """

    group_type = str(block.group_id[0])
    rows = [it.row for it in block.items]

    if group_type == "style":
        # Style は 1 ヘッダ内に「global + layer_style」が混ざるので、出力は中で分割する。
        style_rows = [r for r in rows if r.op == STYLE_OP]
        layer_rows = [r for r in rows if r.op == LAYER_STYLE_OP]

        # --- global style ---
        global_items: list[tuple[str, str]] = []
        by_arg = {str(r.arg): r for r in style_rows}
        if STYLE_BACKGROUND_COLOR in by_arg:
            # UI は 0-255 の RGB を持つので、スニペットでは 0-1 の浮動小数へ変換して貼れる形にする。
            bg255 = coerce_rgb255(
                _effective_or_ui_value(by_arg[STYLE_BACKGROUND_COLOR], last_effective_by_key=last_effective_by_key)
            )
            global_items.append(("background_color", _py_literal(rgb255_to_rgb01(bg255))))
        if STYLE_GLOBAL_THICKNESS in by_arg:
            thickness = _effective_or_ui_value(by_arg[STYLE_GLOBAL_THICKNESS], last_effective_by_key=last_effective_by_key)
            global_items.append(("line_thickness", _py_literal(thickness)))
        if STYLE_GLOBAL_LINE_COLOR in by_arg:
            line255 = coerce_rgb255(
                _effective_or_ui_value(by_arg[STYLE_GLOBAL_LINE_COLOR], last_effective_by_key=last_effective_by_key)
            )
            global_items.append(("line_color", _py_literal(rgb255_to_rgb01(line255))))

        # --- layer style (site_id ごと) ---
        layer_by_site: dict[str, list[ParameterRow]] = {}
        for r in layer_rows:
            layer_by_site.setdefault(str(r.site_id), []).append(r)

        out_lines: list[str] = []

        if global_items:
            # `run(..., background_color=..., line_thickness=..., line_color=...)` の引数部分だけを出す。
            out_lines.append("# --- run(...) ---")
            out_lines.extend(f"{k}={v}," for k, v in global_items)

        named_layer_blocks: list[list[str]] = []
        unnamed_layer_site_ids: list[str] = []

        for site_id, site_rows in layer_by_site.items():
            layer_raw_name = ""
            if raw_label_by_site is not None:
                # layer_style は op が固定（LAYER_STYLE_OP）で、site_id ごとにラベルが付く。
                raw_label = raw_label_by_site.get((LAYER_STYLE_OP, str(site_id)))
                if raw_label is not None:
                    layer_raw_name = str(raw_label).strip()

            if not layer_raw_name:
                unnamed_layer_site_ids.append(str(site_id))
                continue

            # 行は (arg の並び) が欲しいので明示で揃える。
            by_arg2 = {str(r.arg): r for r in site_rows}

            layer_items: list[tuple[str, str]] = []
            if LAYER_STYLE_LINE_COLOR in by_arg2:
                # layer_style の color/thickness も 0-1 の RGB に寄せて出す。
                rgb255 = coerce_rgb255(
                    _effective_or_ui_value(by_arg2[LAYER_STYLE_LINE_COLOR], last_effective_by_key=last_effective_by_key)
                )
                layer_items.append(("color", _py_literal(rgb255_to_rgb01(rgb255))))
            if LAYER_STYLE_LINE_THICKNESS in by_arg2:
                th = _effective_or_ui_value(by_arg2[LAYER_STYLE_LINE_THICKNESS], last_effective_by_key=last_effective_by_key)
                layer_items.append(("thickness", _py_literal(th)))

            if layer_items:
                named_layer_blocks.append(
                    [
                        "# --- L(name=...).layer(..., color/thickness) ---",
                        f"# {layer_raw_name}: paste into `L(name={_py_literal(layer_raw_name)}).layer(...)`",
                        *[f"{k}={v}," for k, v in layer_items],
                    ]
                )

        if named_layer_blocks:
            if out_lines:
                out_lines.append("")
            # 先頭ブロックだけ “セクション見出し” を付けて、以降の繰り返しを減らす。
            out_lines.extend(named_layer_blocks[0])
            for block_lines in named_layer_blocks[1:]:
                out_lines.append("")
                out_lines.extend(block_lines[1:])

        if unnamed_layer_site_ids:
            if out_lines:
                out_lines.append("")
            out_lines.append(
                "# NOTE: 名前の無い layer_style は snippet に出しません。"
                "（`L(name=...).layer(...)` でラベル付けすると出ます）"
            )

        if not out_lines:
            return ""
        return _indent_code("\n".join(out_lines).rstrip() + "\n")

    if group_type == "preset":
        row0 = rows[0]
        op = str(row0.op)
        # preset は “表示名” と実装 op が一致しないケースがあるため、registry で表示名へ寄せる。
        call_name = preset_registry.get_display_op(op)
        prefix = "P."
        if raw_label_by_site is not None:
            raw_label = raw_label_by_site.get((op, str(row0.site_id)))
            if raw_label is not None:
                raw_label_s = str(raw_label).strip()
                if raw_label_s and raw_label_s != str(call_name):
                    prefix = f"P(name={_py_literal(raw_label_s)})."
        kwargs = [
            (str(r.arg), _py_literal(_effective_or_ui_value(r, last_effective_by_key=last_effective_by_key)))
            for r in rows
        ]
        return _indent_code(_format_kwargs_call(prefix, op=call_name, kwargs=kwargs).rstrip() + "\n")

    if group_type == "primitive":
        row0 = rows[0]
        op = str(row0.op)
        prefix = "G."
        if raw_label_by_site is not None:
            raw_label = raw_label_by_site.get((op, str(row0.site_id)))
            if raw_label is not None:
                raw_label_s = str(raw_label).strip()
                if raw_label_s:
                    prefix = f"G(name={_py_literal(raw_label_s)})."
        kwargs = [
            (str(r.arg), _py_literal(_effective_or_ui_value(r, last_effective_by_key=last_effective_by_key)))
            for r in rows
        ]
        return _indent_code(_format_kwargs_call(prefix, op=op, kwargs=kwargs).rstrip() + "\n")

    if group_type == "effect_chain":
        prefix = "E."
        if raw_label_by_site is not None:
            # effect_chain は “チェーン全体” に対する名前として、最初に見つかったラベルを採用する。
            for r in rows:
                raw_label = raw_label_by_site.get((str(r.op), str(r.site_id)))
                if raw_label is None:
                    continue
                raw_label_s = str(raw_label).strip()
                if not raw_label_s:
                    continue
                prefix = f"E(name={_py_literal(raw_label_s)})."
                break

        steps: dict[tuple[int, str, str], list[ParameterRow]] = {}
        for r in rows:
            # step_info が無い場合でも決定的に並ぶよう、未指定は大きい index に寄せて末尾へ回す。
            step_index = 10**9
            if step_info_by_site is not None:
                info = step_info_by_site.get((str(r.op), str(r.site_id)))
                if info is not None:
                    _cid, idx = info
                    step_index = int(idx)
            key = (int(step_index), str(r.op), str(r.site_id))
            steps.setdefault(key, []).append(r)

        if not steps:
            return ""

        out_lines: list[str] = []
        for i, ((_step_index, op, _site_id), step_rows) in enumerate(
            sorted(steps.items(), key=lambda x: x[0])
        ):
            kwargs = [
                (
                    str(r.arg),
                    _py_literal(
                        _effective_or_ui_value(
                            r, last_effective_by_key=last_effective_by_key
                        )
                    ),
                )
                for r in step_rows
            ]
            if i == 0:
                call = _format_kwargs_call(prefix, op=op, kwargs=kwargs)
                out_lines.extend(call.splitlines())
                continue

            # 2 ステップ目以降は `.op(` を行末へ足して “メソッドチェーン” にする。
            # `kwargs` が空のときは `.op()` に置き換える（括弧の対応を崩さないため）。
            out_lines[-1] = out_lines[-1] + f".{op}("
            call_lines = _format_kwargs_call("", op=op, kwargs=kwargs).splitlines()
            if len(call_lines) == 1:
                out_lines[-1] = out_lines[-1].rstrip("(") + "()"
                continue
            out_lines.extend(call_lines[1:])

        return _indent_code("\n".join(out_lines).rstrip() + "\n")

    # fallback
    if rows:
        # 未知 group_type のときも “何かは貼れる” 形で返しておく（デバッグ・テスト用の最終手段）。
        row0 = rows[0]
        op = str(row0.op)
        kwargs = [
            (str(r.arg), _py_literal(_effective_or_ui_value(r, last_effective_by_key=last_effective_by_key)))
            for r in rows
        ]
        return _indent_code(
            ("dict(\n" + "\n".join(f"    {k}={v}," for k, v in kwargs) + "\n)")
            .rstrip()
            + "\n"
        )
    return ""


__all__ = ["snippet_for_block"]
