# どこで: `src/grafix/core/parameters/persistence.py`。
# 何を: ParamStore の JSON 永続化（path 算出 / load / save）を提供する。
# なぜ: parameter_gui で調整したパラメータを、スクリプト単位で再起動後に復元できるようにするため。

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grafix.core.atomic_write import atomic_write_text
from grafix.core.output_paths import output_path_for_draw

from .codec import dumps_param_store, loads_param_store
from .prune_ops import prune_unknown_args_in_known_ops
from .store import ParamStore

_logger = logging.getLogger(__name__)


def default_param_store_path(draw: Callable[[float], Any], *, run_id: str | None = None) -> Path:
    """draw の定義元（sketch_dir）に基づく ParamStore の既定保存パスを返す。

    Notes
    -----
    パスは `output/{kind}/` 配下で sketch_dir のサブディレクトリ構造をミラーする。
    - sketch_dir 配下なら: `{output_root}/param_store/<sketch 相対 dir>/<stem>[_run_id].json`
    - それ以外なら: `{output_root}/param_store/misc/<stem>[_run_id].json`
    """

    return output_path_for_draw(kind="param_store", ext="json", draw=draw, run_id=run_id)


def load_param_store(path: Path) -> ParamStore:
    """JSON ファイルから ParamStore をロードして返す。無ければ空の ParamStore を返す。"""

    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ParamStore()

    try:
        return loads_param_store(payload)
    except Exception as exc:
        corrupt_path = path.with_name(
            f"{path.name}.corrupt-{os.getpid()}-{time.time_ns()}"
        )
        os.replace(path, corrupt_path)
        _logger.warning(
            "壊れた ParamStore を退避しました: source=%s backup=%s error=%s",
            path,
            corrupt_path,
            exc,
        )
        return ParamStore()


def param_store_recovery_path(path: Path) -> Path:
    """通常保存と分離した live session recovery path を返す。"""

    target = Path(path)
    return target.with_name(f"{target.stem}.session{target.suffix}")


def _quarantine_recovery_and_load_primary(
    *,
    recovery: Path,
    primary: Path,
    error: Exception,
) -> ParamStore:
    """壊れた recovery を退避し、primary へ安全にフォールバックする。"""

    corrupt_path = recovery.with_name(
        f"{recovery.name}.corrupt-{os.getpid()}-{time.time_ns()}"
    )
    os.replace(recovery, corrupt_path)
    _logger.warning(
        "壊れた ParamStore session recovery を退避しました: "
        "source=%s backup=%s error=%s",
        recovery,
        corrupt_path,
        error,
    )
    return load_param_store(primary)


def load_param_store_with_recovery(path: Path) -> ParamStore:
    """未完了 session の autosave が通常保存より新しければ、それを復元する。"""

    primary = Path(path)
    recovery = param_store_recovery_path(primary)
    try:
        recovery_mtime = recovery.stat().st_mtime_ns
    except FileNotFoundError:
        return load_param_store(primary)
    try:
        primary_mtime = primary.stat().st_mtime_ns
    except FileNotFoundError:
        primary_mtime = -1
    if recovery_mtime <= primary_mtime:
        return load_param_store(primary)

    try:
        payload = recovery.read_text(encoding="utf-8")
    except FileNotFoundError:
        # stat 後に別 process の clean finalize が完了した場合など。
        return load_param_store(primary)
    except UnicodeError as exc:
        return _quarantine_recovery_and_load_primary(
            recovery=recovery,
            primary=primary,
            error=exc,
        )

    try:
        store = loads_param_store(payload, preserve_explicit_overrides=True)
    except Exception as exc:
        return _quarantine_recovery_and_load_primary(
            recovery=recovery,
            primary=primary,
            error=exc,
        )

    _logger.warning("未完了 session の ParamStore を復元しました: %s", recovery)
    return store


def save_param_store(store: ParamStore, path: Path) -> None:
    """ParamStore を JSON として path に保存する（親ディレクトリは作成する）。

    Notes
    -----
    この関数は「この実行で観測されなかった」という理由だけで、ロード済みの
    group を削除しない。初回 frame 前の終了・失敗 frame・条件分岐は、
    どれも「不要になった」ことの証明にならないためである。不要 group の削除は
    ``prune_stale_loaded_groups`` または ``prune_groups`` を明示的に呼び出す。
    """

    removed_unknown = prune_unknown_args_in_known_ops(store)
    if removed_unknown:
        pairs = sorted({(str(k.op), str(k.arg)) for k in removed_unknown})
        preview = ", ".join(f"{op}.{arg}" for op, arg in pairs[:10])
        suffix = "" if len(pairs) <= 10 else ", ..."
        _logger.warning(
            "未登録引数を永続化から削除しました: count=%d pairs=%d [%s%s]",
            len(removed_unknown),
            len(pairs),
            preview,
            suffix,
        )
    atomic_write_text(path, dumps_param_store(store) + "\n")


def save_param_store_recovery(store: ParamStore, path: Path) -> None:
    """live override を保持した recovery journal を atomic に保存する。"""

    atomic_write_text(
        path,
        dumps_param_store(store, preserve_explicit_overrides=True) + "\n",
    )


def finalize_param_store_session(store: ParamStore, path: Path) -> None:
    """通常状態を保存し、成功した場合だけ session recovery を削除する。"""

    primary = Path(path)
    save_param_store(store, primary)
    param_store_recovery_path(primary).unlink(missing_ok=True)


__all__ = [
    "default_param_store_path",
    "finalize_param_store_session",
    "load_param_store",
    "load_param_store_with_recovery",
    "param_store_recovery_path",
    "save_param_store",
    "save_param_store_recovery",
]
