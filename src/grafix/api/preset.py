# どこで: `src/grafix/api/preset.py`。
# 何を: `@preset` デコレータ（公開引数だけを Parameter GUI に出し、関数本体は自動で mute）を提供する。
# なぜ: 作り込んだ形状を関数として再利用しつつ、GUI を “公開パラメータ” だけに保つため。

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from grafix.core.geometry import Geometry
from grafix.core.parameters import caller_site_id, current_frame_params, current_param_store
from grafix.core.parameters.context import (
    current_param_recording_enabled,
    parameter_recording_muted,
)
from grafix.core.parameters.labels_ops import set_label
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.meta_spec import meta_dict_from_user
from grafix.core.parameters.resolver import resolve_params
from grafix.core.preset_registry import preset_func_registry, preset_registry

_PSpec = ParamSpec("_PSpec")
R = TypeVar("R")

# --- 役割メモ ---
#
# - preset_registry:
#   Parameter GUI/永続化のための「preset の静的仕様（meta / 表示名 / 引数順）」を保持する。
#   ここに登録される op は `ParameterKey(op=..., site_id=..., arg=...)` の op 側にも使われる。
#
# - preset_func_registry:
#   実際に呼び出される preset 関数（ラッパ後）を name -> callable で保持する。
#   `P.<name>(...)` の解決はこのレジストリの内容に依存する。


def _defaults_from_signature(
    func: Callable[..., object],
    meta: dict[str, ParamMeta],
) -> dict[str, Any]:
    # meta に含めた引数は「公開パラメータ」扱いになるため、default を必須にする。
    # 目的: GUI の base 値/初期値が常に決まり、スケッチ側の意図が曖昧にならないようにする。
    #
    # default=None を禁止するのは「未指定/欠損」と区別が付きにくく、UI/永続化の扱いが難しいため。
    sig = inspect.signature(func)
    defaults: dict[str, Any] = {}
    for arg in meta.keys():
        param = sig.parameters.get(arg)
        if param is None:
            raise ValueError(
                f"@preset meta 引数がシグネチャに存在しません: {func.__name__}.{arg}"
            )
        if param.default is inspect._empty:
            raise ValueError(
                f"@preset meta 引数は default 必須です: {func.__name__}.{arg}"
            )
        if param.default is None:
            raise ValueError(
                f"@preset meta 引数 default に None は使えません: {func.__name__}.{arg}"
            )
        defaults[arg] = param.default
    return defaults


def _preset_site_id(base_site_id: str, key: object | None) -> str:
    # preset は「呼び出し箇所（site_id）」で GUI 行を安定化させたい。
    # ただし同一行で preset を複数回呼ぶこともあるため、その場合は key で分岐できるようにする。
    if key is None:
        return str(base_site_id)
    if isinstance(key, (str, int)):
        return f"{base_site_id}|{key}"
    raise TypeError("preset の key は str|int|None である必要があります")


def _maybe_set_label(*, op: str, site_id: str, label: str) -> None:
    # label の設定先は 2 系統ある:
    # - ParamStore がある（メインプロセス）: store に直接 label を保存する
    # - store が無い（mp-draw worker 等）: frame_params 経由で「観測結果」として返す
    store = current_param_store()
    if store is not None:
        set_label(store, op=op, site_id=site_id, label=label)
        return
    frame_params = current_frame_params()
    if frame_params is not None:
        frame_params.set_label(op=op, site_id=site_id, label=label)


def preset(
    *,
    meta: Mapping[str, ParamMeta | Mapping[str, object]],
    ui_visible: Mapping[str, Callable[[Mapping[str, Any]], bool]] | None = None,
) -> Callable[[Callable[_PSpec, R]], Callable[_PSpec, R]]:
    """プリセット関数を Parameter GUI 向けにラップするデコレータ。

    Parameters
    ----------
    meta : Mapping[str, ParamMeta | Mapping[str, object]]
        GUI に公開する引数のメタ情報。ここに含めた引数だけが GUI/永続化の対象になる。

        dict spec の形式:
        - kind: str（必須）
        - ui_min/ui_max: object（任意）
        - choices: Sequence[str] | None（任意）
    ui_visible : Mapping[str, Callable[[Mapping[str, Any]], bool]] or None
        GUI 表示向けの “行の可視性” ルール。
        key は引数名（arg）、value は “その preset 呼び出し 1 回” の現在値辞書を受け取り、
        その引数行を表示するかどうかを返す predicate。

    Notes
    -----
    - 公開対象は `meta` に含まれる引数のみ。
    - 関数本体は自動で mute され、内部の `G.*` / `E.*` の観測（GUI/永続化）を行わない。
    - `activate` は予約引数として自動追加され、GUI/永続化の対象になる（meta に含めない）。
    - `name=` と `key=` を予約引数として使える（GUI には出さない）。
      `key` は同一呼び出し箇所から複数回生成する場合の衝突回避に使う。
    """

    meta_norm = meta_dict_from_user(meta)
    reserved = {"name", "key", "activate"}
    # `name`/`key`/`activate` は予約引数:
    # - name: GUI 上のグループ見出し名（label）を差し替える（GUI には出さない）
    # - key: 同一呼び出し箇所で複数回呼ぶときの衝突回避（GUI には出さない）
    # - activate: preset を “有効化” するための公開 bool（GUI/永続化の対象）
    if reserved & set(meta_norm.keys()):
        bad = ", ".join(sorted(reserved & set(meta_norm.keys())))
        raise ValueError(f"@preset meta に予約引数は含められません: {bad}")

    def decorator(func: Callable[_PSpec, R]) -> Callable[_PSpec, R]:
        preset_name = str(func.__name__)
        # name 重複は「P.<name>」の解決が曖昧になるため禁止する。
        if preset_name in preset_func_registry:
            raise ValueError(f"preset '{preset_name}' は既に登録されている")

        # GUI 側で扱う op 名は `preset.<funcname>` に固定する。
        # 目的: preset を「1 種類の op」として分類/表示し、ParameterKey の op にも使う。
        preset_op = f"preset.{preset_name}"
        sig = inspect.signature(func)
        if "activate" in sig.parameters:
            raise ValueError(
                f"@preset の予約引数 'activate' はシグネチャに含められません: {func.__name__}.activate"
            )
        # 公開パラメータは default 必須として、呼び出しごとの base 値が必ず決まるようにする。
        _defaults_from_signature(func, meta_norm)
        meta_keys = set(meta_norm.keys())
        # activate はデコレータ側で自動的に公開する（meta には書かせない）。
        meta_with_activate = {"activate": ParamMeta(kind="bool"), **meta_norm}
        # GUI の行順は「定義したシグネチャ順」を優先する（dict の順序に依存しない）。
        sig_order = [arg_name for arg_name in sig.parameters if arg_name in meta_keys]
        # preset_registry には「GUI 用の静的仕様」を登録する（実関数は preset_func_registry）。
        preset_registry._register(
            preset_op,
            display_op=preset_name,
            meta=meta_with_activate,
            param_order=("activate", *sig_order),
            ui_visible=ui_visible,
            overwrite=False,
        )

        @wraps(func)
        def wrapper(*args: _PSpec.args, **kwargs: _PSpec.kwargs) -> R:
            # activate を kwargs から取り出す。
            # `explicit` 判定が必要なので、pop 前に「明示指定されていたか」を保持する。
            activate_explicit = "activate" in kwargs
            activate_base = bool(kwargs.pop("activate", True))

            # - bind: 呼び出しをシグネチャに当てはめ、引数名で扱えるようにする
            # - explicit_keys: 「ユーザーが明示的に渡した引数名」を記録する（apply_defaults 前）
            #   目的: resolve_params(explicit_args=...) に渡し、初期 override ポリシーへ反映させるため
            bound = sig.bind(*args, **kwargs)
            explicit_keys = set(bound.arguments.keys())
            bound.apply_defaults()

            # GUI 非公開の予約引数（preset の挙動や GUI 表示だけに使い、パラメータ行は増やさない）
            display_name = bound.arguments.get("name", None)
            key = bound.arguments.get("key", None)

            # site_id は「ユーザーの呼び出し箇所」を指すようにする（skip=1）。
            # 同じ行で複数回呼ぶ場合は key で区別する。
            base_site_id = caller_site_id(skip=1)
            site_id = _preset_site_id(base_site_id, key)

            # group header 名は、指定が無ければ関数名を使う（GUI 未使用時は何もしない）。
            if current_param_recording_enabled():
                label = str(func.__name__) if display_name is None else str(display_name)
                _maybe_set_label(op=preset_op, site_id=site_id, label=label)

            # 公開引数だけ解決する:
            # - preset の “公開 UI” を meta に絞り、本体内部の G/E パラメータは GUI/永続化対象外にする。
            # - recording 無効時は resolve をスキップし、コードが渡した base 値をそのまま使う。
            public_params = {"activate": activate_base}
            public_params.update({k: bound.arguments[k] for k in meta_keys})
            resolved_params = public_params
            explicit_public = meta_keys & explicit_keys
            explicit_public_with_activate = set(explicit_public)
            if activate_explicit:
                explicit_public_with_activate.add("activate")
            if (
                current_param_recording_enabled()
                and current_frame_params() is not None
                and meta_with_activate
            ):
                # resolve_params は:
                # - base 値（スケッチ側）/ GUI 値 / CC 値 を統合して effective 値を返す
                # - 同時に frame_params に「観測結果」を記録し、フレーム終端で ParamStore にマージされる
                resolved_params = resolve_params(
                    op=preset_op,
                    params=public_params,
                    meta=meta_with_activate,
                    site_id=site_id,
                    explicit_args=explicit_public_with_activate,
                )

            for k, v in resolved_params.items():
                if k == "activate":
                    continue
                bound.arguments[k] = v

            if not bool(resolved_params.get("activate", True)):
                # activate=False なら「何も描かない Geometry」を返して終了する。
                # （GUI 行としての preset 自体は記録/表示される）
                return cast(R, Geometry.create(op="concat"))

            # 本体は常に mute:
            # preset 内部で生成される Geometry（G.* / E.*）は公開 API の外に置き、
            # GUI/永続化は “preset の公開引数” に限定する。
            with parameter_recording_muted():
                return func(*bound.args, **bound.kwargs)

        # callable として呼べるよう、name -> wrapper を登録する（P.<name> から参照される）。
        preset_func_registry._register(preset_name, wrapper, overwrite=False)
        return wrapper

    return decorator


__all__ = ["preset"]
