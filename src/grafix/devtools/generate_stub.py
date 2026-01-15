"""
どこで: `src/grafix/devtools/generate_stub.py`。
何を: `grafix.api` の IDE 補完用スタブ `grafix/api/__init__.pyi` を自動生成する。
なぜ: `G`/`E` が動的名前空間のため、静的解析が公開 API を把握できる形を用意するため。

主な流れ（読む順）:
- `generate_stubs_str()` が各 registry を初期化し、primitive/effect/preset の一覧を集計する。
- 集計した名前から `_render_*_protocol()` で `Protocol` ベースの API（`G/E/L/P`）を文字列として生成する。
- `main()` が `grafix.api` の隣に `__init__.pyi` を書き出す（既存ファイルは上書き）。

副作用:
- `generate_stubs_str()` は registry 初期化と preset 自動ロードのために import を行う。
- `main()` は `__init__.pyi` をファイル出力する。

補足:
- effect の public param の型アノテーションは「stub 側で解決可能な名前」だけを書く（自動 import 収集はしない）。
- `ParamMeta.kind == "vec3"` の場合、`tuple[float, float, float]` アノテーションでも stub は `Vec3` 表現を優先する。
"""

from __future__ import annotations

import importlib
import inspect
import hashlib
import re
from pathlib import Path
from typing import Any

# `G.<prim>(...)` / `E.<eff>(...)` / `P.<preset>(...)` といった
# スタブ側メソッド名に使える識別子をフィルタするための正規表現。
_VALID_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 実装側の型注釈が `tuple[float, float, float]`（or `Tuple[...]`）でも、
# スタブでは統一して `Vec3` として表現したいので置換する。
_VEC3_TUPLE_RE = re.compile(
    r"(?:tuple|Tuple)\[\s*float\s*,\s*float\s*,\s*float\s*\]"
)

# 型文字列を厳密にパースせず、「識別子っぽいトークン」だけ拾うための正規表現。
# `list[Path]` なら `list` と `Path` が取れる想定。
_TYPE_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# スタブ（`__init__.pyi`）の import / alias だけで解決できる識別子集合。
# ここに無い名前が型注釈に含まれる場合は、保守的に `Any` へフォールバックする。
_RESOLVABLE_TYPE_IDENTS = {
    # builtins
    "bool",
    "dict",
    "float",
    "frozenset",
    "int",
    "list",
    "object",
    "set",
    "str",
    "tuple",
    "None",
    # stub imports / aliases
    "Any",
    "Callable",
    "Geometry",
    "Layer",
    "Path",
    "SceneItem",
    "Sequence",
    "Vec3",
}


def _is_valid_identifier(name: str) -> bool:
    """`name` が Python の識別子として安全（attribute/method 名に使える）かを返す。"""
    return _VALID_IDENT_RE.match(name) is not None


def _shorten(text: str, *, limit: int = 120) -> str:
    """1 行 summary 用にテキストを短縮する。

    - 連続空白を 1 つに畳む
    - 句点 `。` があれば先頭文だけにする
    - `limit` を超える場合は末尾を `…` で切る
    """
    t = " ".join(text.split())
    if "。" in t:
        t = t.split("。", 1)[0]
    if len(t) > limit:
        t = t[: limit - 1] + "…"
    return t


def _parse_numpy_doc(doc: str) -> tuple[str | None, dict[str, str]]:
    """NumPy スタイル docstring から summary と引数説明を抽出する。

    ここでの「NumPy スタイル」は、最低限以下を想定したかなり軽量なパーサ。

    - 先頭の非空行を summary として採用
    - `Parameters` セクション（見出し + 罫線）を探す
    - `name : type` 形式の行をパラメータ開始として扱い、後続のインデント行を説明として連結
    - 次のセクション見出しに到達したら打ち切る

    Returns
    -------
    summary:
        先頭行（見つからない場合は `None`）。
    param_docs:
        `{"param_name": "説明"}` の辞書。説明は `_shorten()` で短縮される。
    """
    if not doc:
        return None, {}

    lines = doc.splitlines()

    summary: str | None = None
    for ln in lines:
        s = ln.strip()
        if s:
            summary = s
            break

    # "Parameters" セクションを探索
    i = 0
    while i < len(lines):
        if lines[i].strip().lower() == "parameters":
            if i + 1 < len(lines) and set(lines[i + 1].strip()) == {"-"}:
                i += 2
                break
        i += 1
    else:
        return summary, {}

    param_docs: dict[str, str] = {}
    current: str | None = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 次セクションに到達したら終了（見出し + 罫線）
        if stripped and not line.startswith((" ", "\t")) and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt and set(nxt) == {"-"}:
                break

        # "name : type" 行を拾う（先頭カラムのみ）
        if stripped and not line.startswith((" ", "\t")):
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", stripped)
            if m:
                name = m.group(1)
                current = name
                param_docs[name] = ""
                i += 1
                continue

        # 説明行（インデント付き想定）
        if current is not None and stripped:
            if param_docs[current]:
                param_docs[current] += " "
            param_docs[current] += stripped

        i += 1

    out: dict[str, str] = {}
    for k, v in param_docs.items():
        v2 = _shorten(v) if v else ""
        if v2:
            out[k] = v2
    return summary, out


def _meta_hint(meta: Any) -> str | None:
    """`ParamMeta` 風オブジェクトから、docstring 用の短いヒント文字列を作る。

    stub 側の docstring は「型」よりも「UI/値の制約」が助けになることが多いので、
    `kind` / `ui_min` / `ui_max` / `choices` を寄せ集めて 1 行にする。
    """
    kind = getattr(meta, "kind", None)
    ui_min = getattr(meta, "ui_min", None)
    ui_max = getattr(meta, "ui_max", None)
    choices = getattr(meta, "choices", None)

    parts: list[str] = []
    if kind:
        parts.append(str(kind))

    if ui_min is not None or ui_max is not None:
        if ui_min is not None and ui_max is not None:
            parts.append(f"range [{ui_min}, {ui_max}]")
        elif ui_min is not None:
            parts.append(f"min {ui_min}")
        elif ui_max is not None:
            parts.append(f"max {ui_max}")

    try:
        seq = list(choices) if choices is not None else []
    except Exception:
        seq = []
    if seq:
        preview = ", ".join(map(repr, seq[:6]))
        parts.append(f"choices {{ {preview}{' …' if len(seq) > 6 else ''} }}")

    return ", ".join(parts) if parts else None


def _type_for_kind(kind: str) -> str:
    """`ParamMeta.kind` から、スタブに書く型名（文字列）を決める。"""
    if kind == "float":
        return "float"
    if kind == "int":
        return "int"
    if kind == "bool":
        return "bool"
    if kind == "str":
        return "str"
    if kind == "font":
        return "str"
    if kind == "choice":
        return "str"
    if kind == "vec3":
        return "Vec3"
    return "Any"


def _type_str_from_annotation(annotation: Any) -> str | None:
    """アノテーション（型オブジェクト/文字列）を `inspect` 経由で文字列化する。"""
    if annotation is inspect._empty:
        return None
    if isinstance(annotation, str):
        s = annotation.strip()
        return s or None
    try:
        return inspect.formatannotation(annotation)
    except Exception:
        s = str(annotation).strip()
        return s or None


def _normalize_type_str(type_str: str) -> str:
    """型文字列をスタブ側の import に寄せて正規化する。

    例: `typing.Callable` -> `Callable` / `pathlib.Path` -> `Path`。
    """
    s = str(type_str).strip()
    s = s.replace("typing.", "")
    s = s.replace("pathlib.Path", "Path")
    s = s.replace("collections.abc.Sequence", "Sequence")
    s = s.replace("collections.abc.Callable", "Callable")
    s = _VEC3_TUPLE_RE.sub("Vec3", s)
    return s


def _is_resolvable_type_str(type_str: str) -> bool:
    """`type_str` がスタブ内の import/alias だけで解決できそうかを判定する。

    厳密な型パーサではなく、識別子っぽいトークンを拾って集合 membership で判定する。
    したがって保守的（false negative はあり得る）だが、unknown name を出力しないために使う。
    """
    for ident in _TYPE_IDENT_RE.findall(type_str):
        if ident not in _RESOLVABLE_TYPE_IDENTS:
            return False
    return True


def _type_str_from_impl_param(impl: Any, param_name: str) -> str | None:
    """実装関数 `impl` のシグネチャから `param_name` の型注釈を取り出す。"""
    try:
        sig = inspect.signature(impl)
    except Exception:
        return None

    p = sig.parameters.get(param_name)
    if p is None:
        return None
    return _type_str_from_annotation(p.annotation)


def _type_str_for_effect_param(
    *, impl: Any | None, param_name: str, meta: Any
) -> str:
    """effect の param に対する型文字列を決める。

    - 実装関数が見つかれば、その型注釈（文字列化）を優先
    - 取れなければ `ParamMeta.kind` からのフォールバック型
    - `vec3` は `tuple[float, float, float]` でも `Vec3` に寄せる
    """
    kind = str(getattr(meta, "kind", ""))
    fallback = _type_for_kind(kind)
    if impl is None:
        return fallback

    type_str = _type_str_from_impl_param(impl, param_name)
    if type_str is None:
        return fallback

    if kind == "vec3":
        type_str = _VEC3_TUPLE_RE.sub("Vec3", type_str)
    return type_str


def _type_str_for_preset_param(*, impl: Any, param_name: str, meta: Any) -> str:
    """preset 関数の param に対する型文字列を決める。

    preset は user code 由来のため、スタブ側で解決不能な型名を出力しないように
    `_normalize_type_str()` + `_is_resolvable_type_str()` でフィルタし、ダメなら `Any` に倒す。
    """
    kind = str(getattr(meta, "kind", ""))
    fallback = _type_for_kind(kind)

    type_str = _type_str_from_impl_param(impl, param_name)
    if type_str is None:
        return fallback

    type_str_norm = _normalize_type_str(type_str)
    if not _is_resolvable_type_str(type_str_norm):
        return fallback
    return type_str_norm


def _type_str_for_preset_return(*, impl: Any) -> str:
    """preset 関数の戻り値型を（解決可能性を見ながら）文字列として返す。"""
    try:
        sig = inspect.signature(impl)
    except Exception:
        return "Any"

    type_str = _type_str_from_annotation(sig.return_annotation)
    if type_str is None:
        return "Any"

    type_str_norm = _normalize_type_str(type_str)
    if not _is_resolvable_type_str(type_str_norm):
        return "Any"
    return type_str_norm


def _resolve_impl_callable(kind: str, name: str) -> Any | None:
    """built-in 実装関数（docstring ソース）を最善で見つける。

    registry から取れるのは「名前とメタ情報」なので、docstring や型注釈を拾うために
    `grafix.core.primitives.<name>` / `grafix.core.effects.<name>` を import して関数を探す。
    """
    if kind == "primitive":
        module_name = f"grafix.core.primitives.{name}"
    elif kind == "effect":
        module_name = f"grafix.core.effects.{name}"
    else:
        raise ValueError(f"unknown kind: {kind!r}")

    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None

    fn = getattr(mod, name, None)
    return fn if callable(fn) else None


def _render_docstring(
    *,
    summary: str | None,
    param_order: list[str],
    parsed_param_docs: dict[str, str],
    meta_by_name: dict[str, Any],
) -> list[str]:
    """stub のメソッド docstring（複数行）を組み立てる。

    `inspect.getdoc()` からの抽出結果を優先し、無ければ registry meta からのヒントを補う。
    返す行は「インデント無し」。`_render_method()` 側でインデントを付ける。
    """
    lines: list[str] = []
    if summary:
        lines.append(summary)

    arg_lines: list[str] = []
    for p in param_order:
        desc = parsed_param_docs.get(p)
        if desc is None:
            hint = _meta_hint(meta_by_name.get(p))
            desc = hint
        if desc:
            arg_lines.append(f"    {p}: {desc}")

    if arg_lines:
        if lines:
            lines.append("")
        lines.append("引数:")
        lines.extend(arg_lines)

    return lines


def _render_method(
    *,
    indent: str,
    name: str,
    return_type: str,
    params: list[str],
    doc_lines: list[str],
) -> str:
    """`Protocol` の 1 メソッド分のスタブ文字列を生成する。"""
    lines: list[str] = []

    if params:
        # このスタブ API は基本的に keyword-only パラメータ設計（`*, a=..., b=...`）。
        sig_params = "*, " + ", ".join(params)
    else:
        sig_params = ""

    comma = ", " if sig_params else ""
    lines.append(f"{indent}def {name}(self{comma}{sig_params}) -> {return_type}:\n")

    if doc_lines:
        body_indent = indent + " " * 4
        lines.append(f'{body_indent}"""\n')
        for dl in doc_lines:
            if dl:
                lines.append(f"{body_indent}{dl}\n")
            else:
                lines.append("\n")
        lines.append(f'{body_indent}"""\n')

    lines.append(f"{indent}    ...\n")
    return "".join(lines)


def _render_g_protocol(primitive_names: list[str]) -> str:
    """`G`（primitive 名前空間）の `Protocol` 定義を生成する。"""
    lines: list[str] = []
    lines.append("class _G(Protocol):\n")

    lines.append("    def __call__(self, name: str | None = None) -> _G:\n")
    lines.append('        """ラベル付き primitive 名前空間を返す。"""\n')
    lines.append("        ...\n")

    from grafix.core.primitive_registry import primitive_registry  # type: ignore[import]

    for prim in primitive_names:
        meta = primitive_registry.get_meta(prim)
        meta_by_name: dict[str, Any] = dict(meta)
        param_order = list(meta_by_name.keys())

        params: list[str] = []
        if meta_by_name:
            for p in param_order:
                pm = meta_by_name[p]
                kind = str(getattr(pm, "kind", ""))
                params.append(f"{p}: {_type_for_kind(kind)} = ...")
        else:
            params = ["**params: Any"]

        impl = _resolve_impl_callable("primitive", prim)
        if impl is not None:
            parsed_summary, parsed_docs = _parse_numpy_doc(inspect.getdoc(impl) or "")
        else:
            parsed_summary, parsed_docs = (None, {})
        doc_lines = _render_docstring(
            summary=parsed_summary,
            param_order=[p for p in param_order if _is_valid_identifier(p)],
            parsed_param_docs=parsed_docs,
            meta_by_name=meta_by_name,
        )

        lines.append(
            _render_method(
                indent="    ",
                name=prim,
                return_type="Geometry",
                params=params,
                doc_lines=doc_lines,
            )
        )

    lines.append("\n")
    return "".join(lines)


def _render_effect_builder_protocol(effect_names: list[str]) -> str:
    """`E.xxx(...)` の戻り値である builder の `Protocol` 定義を生成する。"""
    lines: list[str] = []
    lines.append("class _EffectBuilder(Protocol):\n")
    lines.append("    def __call__(self, geometry: Geometry, *more_geometries: Geometry) -> Geometry:\n")
    lines.append('        """保持している effect 列を Geometry に適用する。"""\n')
    lines.append("        ...\n")

    from grafix.core.effect_registry import effect_registry  # type: ignore[import]

    for eff in effect_names:
        impl = _resolve_impl_callable("effect", eff)

        meta = effect_registry.get_meta(eff)
        meta_by_name: dict[str, Any] = dict(meta)
        param_order = list(meta_by_name.keys())

        params: list[str] = []
        if meta_by_name:
            for p in param_order:
                pm = meta_by_name[p]
                type_str = _type_str_for_effect_param(impl=impl, param_name=p, meta=pm)
                params.append(f"{p}: {type_str} = ...")
        else:
            params = ["**params: Any"]

        if impl is not None:
            parsed_summary, parsed_docs = _parse_numpy_doc(inspect.getdoc(impl) or "")
        else:
            parsed_summary, parsed_docs = (None, {})
        doc_lines = _render_docstring(
            summary=parsed_summary,
            param_order=[p for p in param_order if _is_valid_identifier(p)],
            parsed_param_docs=parsed_docs,
            meta_by_name=meta_by_name,
        )

        lines.append(
            _render_method(
                indent="    ",
                name=eff,
                return_type="_EffectBuilder",
                params=params,
                doc_lines=doc_lines,
            )
        )

    lines.append("\n")
    return "".join(lines)


def _render_e_protocol(effect_names: list[str]) -> str:
    """`E`（effect 名前空間）の `Protocol` 定義を生成する。"""
    lines: list[str] = []
    lines.append("class _E(Protocol):\n")

    lines.append("    def __call__(self, name: str | None = None) -> _E:\n")
    lines.append('        """ラベル付き effect 名前空間を返す。"""\n')
    lines.append("        ...\n")

    from grafix.core.effect_registry import effect_registry  # type: ignore[import]

    for eff in effect_names:
        impl = _resolve_impl_callable("effect", eff)

        meta = effect_registry.get_meta(eff)
        meta_by_name: dict[str, Any] = dict(meta)
        param_order = list(meta_by_name.keys())

        params: list[str] = []
        if meta_by_name:
            for p in param_order:
                pm = meta_by_name[p]
                type_str = _type_str_for_effect_param(impl=impl, param_name=p, meta=pm)
                params.append(f"{p}: {type_str} = ...")
        else:
            params = ["**params: Any"]

        if impl is not None:
            parsed_summary, parsed_docs = _parse_numpy_doc(inspect.getdoc(impl) or "")
        else:
            parsed_summary, parsed_docs = (None, {})
        doc_lines = _render_docstring(
            summary=parsed_summary,
            param_order=[p for p in param_order if _is_valid_identifier(p)],
            parsed_param_docs=parsed_docs,
            meta_by_name=meta_by_name,
        )

        lines.append(
            _render_method(
                indent="    ",
                name=eff,
                return_type="_EffectBuilder",
                params=params,
                doc_lines=doc_lines,
            )
        )

    lines.append("\n")
    return "".join(lines)


def _render_l_protocol() -> str:
    """`L`（Layer 生成）の `Protocol` 定義を生成する。"""
    lines: list[str] = []
    lines.append("class _L(Protocol):\n")
    lines.append(
        "    def __call__(\n"
        "        self,\n"
        "        geometry_or_list: Geometry | Sequence[Geometry],\n"
        "        *,\n"
        "        color: Vec3 | None = ...,\n"
        "        thickness: float | None = ...,\n"
        "        name: str | None = ...,\n"
        "    ) -> list[Layer]:\n"
    )
    lines.append('        """単体/複数の Geometry から Layer を生成する。"""\n')
    lines.append("        ...\n\n")
    return "".join(lines)


def _render_p_protocol(preset_names: list[str]) -> str:
    """`P`（preset 名前空間）の `Protocol` 定義を生成する。"""
    lines: list[str] = []
    lines.append("class _P(Protocol):\n")
    lines.append("    def __getattr__(self, name: str) -> Callable[..., Any]:\n")
    lines.append('        """preset を `P.<name>(...)` で呼び出す。"""\n')
    lines.append("        ...\n\n")

    from grafix.core.preset_registry import preset_func_registry, preset_registry  # type: ignore[import]

    for preset_name in preset_names:
        impl = preset_func_registry.get(preset_name)
        if impl is None:
            continue

        op = f"preset.{preset_name}"
        if op not in preset_registry:
            continue

        meta_by_name: dict[str, Any] = dict(preset_registry.get_meta(op))
        param_order = [p for p in preset_registry.get_param_order(op) if _is_valid_identifier(p)]

        params: list[str] = []
        if meta_by_name:
            for p in param_order:
                pm = meta_by_name[p]
                type_str = _type_str_for_preset_param(impl=impl, param_name=p, meta=pm)
                params.append(f"{p}: {type_str} = ...")

        parsed_summary, parsed_docs = _parse_numpy_doc(inspect.getdoc(impl) or "")
        doc_lines = _render_docstring(
            summary=parsed_summary,
            param_order=param_order,
            parsed_param_docs=parsed_docs,
            meta_by_name=meta_by_name,
        )

        return_type = _type_str_for_preset_return(impl=impl)
        lines.append(
            _render_method(
                indent="    ",
                name=preset_name,
                return_type=return_type,
                params=params,
                doc_lines=doc_lines,
            )
        )

    return "".join(lines)


def generate_stubs_str() -> str:
    """`grafix/api/__init__.pyi` の生成結果を文字列として返す。

    Notes
    -----
    - registry を初期化するために `grafix.api.*` を import する（副作用あり）。
    - primitives/effects は「実装関数が import できるもの」だけを採用する。
    - presets は `runtime_config().preset_module_dirs` 配下からロードされたものだけを採用する。
    """

    # public API 起点で import し、registry を初期化する。
    importlib.import_module("grafix.api.primitives")
    importlib.import_module("grafix.api.effects")
    importlib.import_module("grafix.api.layers")
    presets = importlib.import_module("grafix.api.presets")
    presets._autoload_preset_modules()  # type: ignore[attr-defined]

    from grafix.core.primitive_registry import primitive_registry  # type: ignore[import]
    from grafix.core.effect_registry import effect_registry  # type: ignore[import]
    from grafix.core.preset_registry import preset_func_registry, preset_registry  # type: ignore[import]
    from grafix.core.runtime_config import runtime_config  # type: ignore[import]

    # IDE 補完に載せたい public 名だけ抽出する。
    # - 先頭が `_` の名前は除外
    # - method 名に使えない識別子は除外
    # - 実装関数が見つからないものは除外（docstring/型注釈を拾えないため）
    primitive_names = sorted(
        name
        for name, _ in primitive_registry.items()
        if _is_valid_identifier(name)
        and not name.startswith("_")
        and _resolve_impl_callable("primitive", name) is not None
    )
    effect_names = sorted(
        name
        for name, _ in effect_registry.items()
        if _is_valid_identifier(name)
        and not name.startswith("_")
        and _resolve_impl_callable("effect", name) is not None
    )

    # user presets は、preset dir ごとに「パス由来のハッシュで作った擬似パッケージ名」
    # (`grafix_user_presets_<hash>`) 以下に import される設計。
    # ここではその prefix と一致する関数だけをスタブ対象にする。
    cfg = runtime_config()
    preset_pkg_prefixes: tuple[str, ...] = tuple(
        f"grafix_user_presets_{hashlib.sha256(str(Path(d).resolve(strict=False)).encode('utf-8')).hexdigest()[:10]}."
        for d in cfg.preset_module_dirs
        if Path(d).resolve(strict=False).is_dir()
    )
    preset_names = sorted(
        name
        for name, fn in preset_func_registry.items()
        if _is_valid_identifier(name)
        and not name.startswith("_")
        and f"preset.{name}" in preset_registry
        and any(
            str(getattr(fn, "__module__", "")).startswith(pref)
            for pref in preset_pkg_prefixes
        )
    )

    # 生成物の先頭には「自動生成」ヘッダと lint 抑制を入れる。
    # `from __future__ import annotations` 以降は、型文字列化を簡単にするため固定の import を並べる。
    header = (
        "# This file is auto-generated by grafix.devtools.generate_stub. DO NOT EDIT.\n"
        "# Regenerate with: python -m grafix stub\n\n"
        "# ruff: noqa: F401, E402\n\n"
    )

    lines: list[str] = [header]
    lines.append("from __future__ import annotations\n\n")
    lines.append("from collections.abc import Callable, Sequence\n")
    lines.append("from pathlib import Path\n")
    lines.append("from typing import Any, Protocol, TypeAlias\n\n")

    lines.append("from grafix.core.geometry import Geometry\n")
    lines.append("from grafix.core.layer import Layer\n")
    lines.append("from grafix.core.scene import SceneItem\n\n")

    lines.append("Vec3: TypeAlias = tuple[float, float, float]\n\n")

    lines.append(_render_g_protocol(primitive_names))
    lines.append(_render_effect_builder_protocol(effect_names))
    lines.append(_render_e_protocol(effect_names))
    lines.append(_render_l_protocol())
    lines.append(_render_p_protocol(preset_names))

    lines.append("G: _G\n")
    lines.append("E: _E\n")
    lines.append("L: _L\n\n")
    lines.append("P: _P\n\n")

    # 実行時 API と整合する再エクスポート
    lines.append("from grafix.api.export import Export as Export\n")
    lines.append("from grafix.api.preset import preset as preset\n")
    lines.append("from grafix.core.effect_registry import effect as effect\n")
    lines.append("from grafix.core.primitive_registry import primitive as primitive\n\n")

    # `grafix.api.__init__.py` は遅延 import だが、型はここで固定する。
    lines.append(
        "def run(\n"
        "    draw: Callable[[float], SceneItem],\n"
        "    *,\n"
        "    config_path: str | Path | None = ...,\n"
        "    run_id: str | None = ...,\n"
        "    background_color: Vec3 = ...,\n"
        "    line_thickness: float = ...,\n"
        "    line_color: Vec3 = ...,\n"
        "    render_scale: float = ...,\n"
        "    canvas_size: tuple[int, int] = ...,\n"
        "    parameter_gui: bool = ...,\n"
        "    parameter_persistence: bool = ...,\n"
        "    midi_port_name: str | None = ...,\n"
        "    midi_mode: str = ...,\n"
        "    n_worker: int = ...,\n"
        "    fps: float = ...,\n"
        ") -> None:\n"
        '    """pyglet ウィンドウを生成し `draw(t)` のシーンをリアルタイム描画する。"""\n'
        "    ...\n\n"
    )

    lines.append(
        "__all__ = ['E', 'Export', 'G', 'L', 'P', 'effect', 'preset', 'primitive', 'run']\n"
    )
    return "".join(lines)


def main() -> None:
    """`grafix/api/__init__.pyi` を生成してファイルに書き出す。"""
    content = generate_stubs_str()
    import grafix.api

    api_init = Path(grafix.api.__file__).resolve()
    out_path = api_init.with_name("__init__.pyi")
    out_path.write_text(content, encoding="utf-8")
    print(f"Wrote {out_path}")  # noqa: T201


if __name__ == "__main__":
    main()
