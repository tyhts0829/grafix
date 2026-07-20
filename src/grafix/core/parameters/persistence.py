# どこで: `src/grafix/core/parameters/persistence.py`。
# 何を: ParamStore の JSON 永続化（path 算出 / load / save）を提供する。
# なぜ: parameter_gui で調整したパラメータを、スクリプト単位で再起動後に復元できるようにするため。

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grafix.core.atomic_write import atomic_write_text
from grafix.core.output_paths import output_path_for_draw

from .codec import (
    ParamStoreDecodeResult,
    ParamStoreSchemaError,
    UnsupportedParamStoreSchemaError,
    dumps_param_store,
    loads_param_store_result,
    param_store_schema_version,
)
from .prune_ops import prune_unknown_args_in_known_ops
from .runtime import LoadProvenance, ParamStoreLoadDiagnostic
from .store import ParamStore

_logger = logging.getLogger(__name__)


def _quarantine_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.corrupt-{os.getpid()}-{time.time_ns()}")


def _set_load_result(
    store: ParamStore,
    *,
    provenance: LoadProvenance,
    diagnostics: tuple[ParamStoreLoadDiagnostic, ...] = (),
) -> ParamStore:
    runtime = store._runtime_ref()
    runtime.load_provenance = provenance
    runtime.load_diagnostics = diagnostics
    return store


def _finish_decoded_store(
    result: ParamStoreDecodeResult,
    *,
    source: Path,
    provenance: LoadProvenance,
    repaired_recovery_path: Path | None = None,
) -> ParamStore:
    diagnostics: list[ParamStoreLoadDiagnostic] = []
    if not result.issues:
        return _set_load_result(
            result.store,
            provenance=provenance,
            diagnostics=tuple(diagnostics),
        )

    backup_path = _quarantine_path(source)
    os.replace(source, backup_path)
    details = "\n".join(issue.describe() for issue in result.issues)
    diagnostics.append(
        ParamStoreLoadDiagnostic(
            code="partial_quarantine",
            summary=(
                f"ParamStore の不正 entry {len(result.issues)} 件を除外し、"
                "原本を退避しました"
            ),
            details=details,
            backup_path=backup_path,
        )
    )
    _logger.warning(
        "部分破損した ParamStore を退避しました: "
        "source=%s backup=%s issues=%d\n%s",
        source,
        backup_path,
        len(result.issues),
        details,
    )
    store = _set_load_result(
        result.store,
        provenance="quarantined",
        diagnostics=tuple(diagnostics),
    )
    if repaired_recovery_path is not None:
        # source はすでに原本 backup へ退避済み。修復済みの有効 entry を
        # user operation/debounce より前に journal 化し、直後の異常終了でも守る。
        try:
            save_param_store_recovery(store, repaired_recovery_path)
        except Exception:
            # journal を作れない状態で原本だけを quarantine に残すと、
            # 次回起動時の自動復旧経路が失われる。元の source を即座に戻す。
            os.replace(backup_path, source)
            raise
    return store


def _quarantine_failure(
    *,
    source: Path,
    error: Exception,
    summary: str,
    code: str,
) -> tuple[Path, ParamStoreLoadDiagnostic]:
    backup_path = _quarantine_path(source)
    os.replace(source, backup_path)
    return backup_path, ParamStoreLoadDiagnostic(
        code=code,
        summary=summary,
        details=str(error),
        backup_path=backup_path,
    )


def _quarantine_primary_and_return_empty(path: Path, error: Exception) -> ParamStore:
    backup_path, diagnostic = _quarantine_failure(
        source=path,
        error=error,
        summary="壊れた ParamStore を退避し、空の状態で起動しました",
        code="load_quarantine",
    )
    _logger.warning(
        "壊れた ParamStore を退避しました: source=%s backup=%s error=%s",
        path,
        backup_path,
        error,
    )
    return _set_load_result(
        ParamStore(),
        provenance="quarantined",
        diagnostics=(diagnostic,),
    )


def _reject_unsupported_schema_file(path: Path) -> None:
    """recovery 選択で上書き得る非現行 schema を先に拒否する。"""

    try:
        payload = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeError):
        return
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError):
        return
    try:
        param_store_schema_version(obj)
    except UnsupportedParamStoreSchemaError:
        raise
    except (ParamStoreSchemaError, TypeError):
        # 選択された場合の通常 load が quarantine と診断を担う。
        return


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
        return _set_load_result(ParamStore(), provenance="primary")
    except UnicodeError as exc:
        return _quarantine_primary_and_return_empty(path, exc)

    try:
        result = loads_param_store_result(payload)
    except UnsupportedParamStoreSchemaError:
        # 非現行 schema を破損と誤認して退避しない。
        # 原本を残したまま caller へ明示的に拒否を返す。
        raise
    except (json.JSONDecodeError, ParamStoreSchemaError, TypeError) as exc:
        return _quarantine_primary_and_return_empty(path, exc)
    return _finish_decoded_store(
        result,
        source=path,
        provenance="primary",
        repaired_recovery_path=param_store_recovery_path(path),
    )


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

    corrupt_path, diagnostic = _quarantine_failure(
        source=recovery,
        error=error,
        summary=(
            "壊れた ParamStore session recovery を退避し、"
            "primary を読み込みました"
        ),
        code="recovery_quarantine",
    )
    _logger.warning(
        "壊れた ParamStore session recovery を退避しました: "
        "source=%s backup=%s error=%s",
        recovery,
        corrupt_path,
        error,
    )
    store = load_param_store(primary)
    return _set_load_result(
        store,
        provenance="quarantined",
        diagnostics=(diagnostic, *store.load_diagnostics),
    )


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
    # どちらかが非現行 schema なら、mtime で古い側も含めて
    # 上書き/削除せず明示的に拒否する。
    _reject_unsupported_schema_file(primary)
    _reject_unsupported_schema_file(recovery)
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
        result = loads_param_store_result(
            payload,
            preserve_explicit_overrides=True,
        )
    except UnsupportedParamStoreSchemaError:
        # 非現行 schema は破損ではない。recovery を保存したまま
        # caller へ拒否を返し、古い primary への黙示 fallback を防ぐ。
        raise
    except (json.JSONDecodeError, ParamStoreSchemaError, TypeError) as exc:
        return _quarantine_recovery_and_load_primary(
            recovery=recovery,
            primary=primary,
            error=exc,
        )

    store = _finish_decoded_store(
        result,
        source=recovery,
        provenance="session_recovery",
        repaired_recovery_path=recovery,
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
