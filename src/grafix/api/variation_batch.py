"""Named variation を headless batch capture する小さな公開 API。"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from typing import Literal

from grafix.api.render import ExportFormat, RenderSession
from grafix.core.parameters.memento import restore_param_store_memento
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.variations import Variation, list_variations
from grafix.core.preview_quality import preview_quality_context
from grafix.export.capture import CaptureService

VariationRenderStatus = Literal["success", "failed"]


@dataclass(frozen=True, slots=True)
class _ExactParamStoreSnapshot:
    """Batch 開始時の ParamStore 全属性を正確に戻す内部 snapshot。"""

    attributes: dict[str, object]
    variation_container: dict[str, Variation]
    variation_items: tuple[tuple[str, Variation], ...]
    snapshot_cache: object | None


@dataclass(frozen=True, slots=True)
class _BatchDirectory:
    """Public generation path と overwrite 用 private staging path。"""

    final: Path
    working: Path
    staged: bool


@dataclass(frozen=True, slots=True)
class VariationRenderResult:
    """1 named variation の capture 結果。"""

    variation_name: str
    seed: int | None
    t: float
    status: VariationRenderStatus
    thumbnail_path: Path | None = None
    manifest_path: Path | None = None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        name = str(self.variation_name).strip()
        if not name:
            raise ValueError("variation_name は空にできません")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise TypeError("seed は int または None である必要があります")
        render_t = float(self.t)
        if not math.isfinite(render_t):
            raise ValueError("t は有限値である必要があります")
        if self.status not in {"success", "failed"}:
            raise ValueError(f"未対応の variation render status: {self.status!r}")
        if self.status == "success" and self.thumbnail_path is None:
            raise ValueError("success result には thumbnail_path が必要です")
        if self.status == "failed" and self.error_type is None:
            raise ValueError("failed result には error_type が必要です")

        object.__setattr__(self, "variation_name", name)
        object.__setattr__(self, "t", render_t)
        if self.thumbnail_path is not None:
            object.__setattr__(self, "thumbnail_path", Path(self.thumbnail_path))
        if self.manifest_path is not None:
            object.__setattr__(self, "manifest_path", Path(self.manifest_path))

    @property
    def succeeded(self) -> bool:
        """capture が成功していれば True。"""

        return self.status == "success"

    def as_dict(self, *, relative_to: Path | None = None) -> dict[str, object]:
        """partial failure summary 用の JSON 互換値を返す。"""

        return {
            "variation_name": self.variation_name,
            "seed": self.seed,
            "t": self.t,
            "status": self.status,
            "thumbnail_path": _summary_path(self.thumbnail_path, relative_to),
            "manifest_path": _summary_path(self.manifest_path, relative_to),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class VariationBatchResult:
    """Named variation batch 全体の immutable summary。"""

    output_directory: Path
    items: tuple[VariationRenderResult, ...]
    contact_sheet_path: Path
    summary_path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_directory", Path(self.output_directory))
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "contact_sheet_path", Path(self.contact_sheet_path))
        object.__setattr__(self, "summary_path", Path(self.summary_path))

    @property
    def success_count(self) -> int:
        """成功 variation 数を返す。"""

        return sum(item.succeeded for item in self.items)

    @property
    def failure_count(self) -> int:
        """失敗 variation 数を返す。"""

        return len(self.items) - self.success_count

    @property
    def ok(self) -> bool:
        """全 variation が成功していれば True。"""

        return self.failure_count == 0

    def as_dict(self) -> dict[str, object]:
        """保存用 structured summary を返す。"""

        directory = self.output_directory
        return {
            "schema": "grafix.variation-batch.v1",
            "output_directory": str(directory),
            "contact_sheet_path": _summary_path(
                self.contact_sheet_path,
                directory,
            ),
            "summary_path": _summary_path(self.summary_path, directory),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "items": [item.as_dict(relative_to=directory) for item in self.items],
        }


def render_variation_batch(
    session: RenderSession,
    output_root: str | Path,
    *,
    variation_names: Sequence[str] | None = None,
    default_t: float = 0.0,
    thumbnail_format: ExportFormat | str = ExportFormat.PNG,
    thumbnail_size: tuple[int, int] = (320, 320),
    columns: int | None = None,
    batch_name: str = "variations",
    overwrite: bool = False,
    capture_service: CaptureService | None = None,
) -> VariationBatchResult:
    """RenderSession 内の named variations を順に復元・capture する。

    Parameters
    ----------
    session : RenderSession
        named variations を持つ ``ParamStore`` と render cache を所有する session。
    output_root : str or Path
        batch directory を作る親 directory。
    variation_names : Sequence[str] or None, optional
        描画順。None は保存順の全 variation。未知名は partial failure として残す。
    default_t : float, optional
        variation に ``t`` が無い場合の評価時刻。
    thumbnail_format : {"png", "svg"} or ExportFormat, optional
        CaptureService へ渡す thumbnail 形式。
    thumbnail_size : tuple[int, int], optional
        PNG thumbnail の出力解像度と、contact sheet 上の表示サイズ。
        SVG は解像度を持たないため表示サイズにだけ使う。
    columns : int or None, optional
        contact sheet 列数。None は件数から決める。
    batch_name : str, optional
        ``output_root`` 内の batch directory 名。
    overwrite : bool, optional
        False は batch directory 自体を連番化する。True の場合だけ既存 generation
        を完成済み staging generation で一括置換する。公開失敗時は旧版へ戻す。
    capture_service : CaptureService or None, optional
        capture backend。省略時は新しい CaptureService を使う。

    Returns
    -------
    VariationBatchResult
        variation 単位の成否、contact sheet、structured summary。

    Notes
    -----
    各 variation の前に batch 呼び出し時の exact store snapshot へ戻して
    variation memento を merge する。そのため、前の render で新たに発見した
    parameter も次の variation へ引き継がない。成否にかかわらず終了時は
    revision/runtime/UI state/named variations を含む呼び出し前の状態へ戻す。
    """

    store = getattr(session, "param_store", None)
    if not isinstance(store, ParamStore):
        raise TypeError("session.param_store は ParamStore である必要があります")
    render_t = float(default_t)
    if not math.isfinite(render_t):
        raise ValueError("default_t は有限値である必要があります")
    image_size = _positive_size(thumbnail_size)
    if columns is not None and (
        isinstance(columns, bool) or not isinstance(columns, int) or columns <= 0
    ):
        raise ValueError("columns は正の整数または None である必要があります")
    column_count = columns
    image_format = _thumbnail_format(thumbnail_format)
    requests = _variation_requests(store, variation_names)
    if not requests:
        raise ValueError("render 対象の named variation がありません")

    batch_directory = _prepare_batch_directory(
        Path(output_root),
        batch_name=batch_name,
        overwrite=bool(overwrite),
    )
    try:
        output_directory = batch_directory.working
        service = CaptureService() if capture_service is None else capture_service
        original = _capture_exact_param_store(store)
        items: list[VariationRenderResult] = []
        try:
            for index, (requested_name, variation) in enumerate(requests, start=1):
                _restore_exact_param_store(store, original)
                if variation is None:
                    items.append(
                        VariationRenderResult(
                            variation_name=requested_name,
                            seed=None,
                            t=render_t,
                            status="failed",
                            error_type="KeyError",
                            error_message=f"unknown variation: {requested_name!r}",
                        )
                    )
                    continue

                item_t = render_t if variation.t is None else float(variation.t)
                try:
                    restore_param_store_memento(store, variation.parameter_snapshot)
                    with preview_quality_context("final"):
                        frame = session.render(
                            item_t,
                            provenance_seed=variation.seed,
                        )
                    requested_thumbnail = output_directory / _thumbnail_name(
                        index,
                        variation,
                        image_format,
                    )
                    captured = service.export(
                        frame,
                        requested_thumbnail,
                        overwrite=False,
                        output_size=(
                            image_size if image_format is ExportFormat.PNG else None
                        ),
                    )
                except Exception as exc:
                    items.append(
                        VariationRenderResult(
                            variation_name=variation.name,
                            seed=variation.seed,
                            t=item_t,
                            status="failed",
                            error_type=type(exc).__name__,
                            error_message=str(exc) or type(exc).__name__,
                        )
                    )
                    continue

                items.append(
                    VariationRenderResult(
                        variation_name=variation.name,
                        seed=variation.seed,
                        t=item_t,
                        status="success",
                        thumbnail_path=captured.path,
                        manifest_path=captured.manifest_path,
                    )
                )
        finally:
            _restore_exact_param_store(store, original)

        _publish_text(
            output_directory / "contact-sheet.svg",
            _contact_sheet_svg(
                tuple(items),
                output_directory=output_directory,
                thumbnail_size=image_size,
                columns=column_count,
            ),
            overwrite=False,
        )
        _relocate_capture_manifests(
            tuple(items),
            source=output_directory,
            destination=batch_directory.final,
        )
        final_items = _relocate_items(
            tuple(items),
            source=output_directory,
            destination=batch_directory.final,
        )
        result = VariationBatchResult(
            output_directory=batch_directory.final,
            items=final_items,
            contact_sheet_path=batch_directory.final / "contact-sheet.svg",
            summary_path=batch_directory.final / "summary.json",
        )
        _publish_text(
            output_directory / "summary.json",
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            overwrite=False,
        )
        _publish_batch_directory(batch_directory)
        return result
    finally:
        if batch_directory.staged and batch_directory.working.exists():
            shutil.rmtree(batch_directory.working)


def _capture_exact_param_store(store: ParamStore) -> _ExactParamStoreSnapshot:
    """Transient batch 用に ParamStore の全属性を独立コピーする。"""

    variations = store._variations_ref()
    snapshot_cache = store._snapshot_cache
    # Variation は immutable で batch が書き換えない。元 container/object を
    # 保つことで、復元時に named variation の identity も不要に壊さない。
    memo: dict[int, object] = {id(variations): variations}
    if snapshot_cache is not None:
        memo[id(snapshot_cache)] = snapshot_cache
    attributes: dict[str, object] = deepcopy(vars(store), memo)
    return _ExactParamStoreSnapshot(
        attributes=attributes,
        variation_container=variations,
        variation_items=tuple(variations.items()),
        snapshot_cache=snapshot_cache,
    )


def _restore_exact_param_store(
    store: ParamStore,
    snapshot: _ExactParamStoreSnapshot,
) -> None:
    """ParamStore identity を保ちつつ batch 開始時の全属性へ戻す。"""

    snapshot.variation_container.clear()
    snapshot.variation_container.update(snapshot.variation_items)
    memo: dict[int, object] = {
        id(snapshot.variation_container): snapshot.variation_container,
    }
    if snapshot.snapshot_cache is not None:
        memo[id(snapshot.snapshot_cache)] = snapshot.snapshot_cache
    restored: dict[str, object] = deepcopy(snapshot.attributes, memo)
    vars(store).clear()
    vars(store).update(restored)


def _thumbnail_format(value: ExportFormat | str) -> ExportFormat:
    if isinstance(value, ExportFormat):
        output = value
    else:
        try:
            output = ExportFormat(str(value).strip().casefold().lstrip("."))
        except ValueError as exc:
            raise ValueError(f"未対応の thumbnail_format: {value!r}") from exc
    if output not in {ExportFormat.PNG, ExportFormat.SVG}:
        raise ValueError("thumbnail_format は 'png' または 'svg' である必要があります")
    return output


def _positive_size(value: tuple[int, int]) -> tuple[int, int]:
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise ValueError("thumbnail_size は (width, height) で指定してください") from exc
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("thumbnail_size は正の整数ペアである必要があります")
    return int(width), int(height)


def _variation_requests(
    store: ParamStore,
    names: Sequence[str] | None,
) -> tuple[tuple[str, Variation | None], ...]:
    variations = list_variations(store)
    if names is None:
        return tuple((variation.name, variation) for variation in variations)
    by_name = {variation.name: variation for variation in variations}
    requests: list[tuple[str, Variation | None]] = []
    for name in names:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("variation_names に空文字は指定できません")
        requests.append((normalized, by_name.get(normalized)))
    return tuple(requests)


def _prepare_batch_directory(
    output_root: Path,
    *,
    batch_name: str,
    overwrite: bool,
) -> _BatchDirectory:
    root = output_root.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    name = str(batch_name).strip()
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError("batch_name は path separator を含まない名前で指定してください")
    base = root / name
    if overwrite:
        if os.path.lexists(base) and (base.is_symlink() or not base.is_dir()):
            raise FileExistsError(
                "overwrite 対象の batch generation が directory ではありません: "
                f"{base}"
            )
        working = Path(
            tempfile.mkdtemp(prefix=f".{name}.batch-", dir=root)
        )
        return _BatchDirectory(final=base, working=working, staged=True)

    index = 0
    while True:
        candidate = (
            base
            if index == 0
            else base.with_name(f"{base.name}_{index:03d}")
        )
        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            index += 1
            continue
        return _BatchDirectory(final=candidate, working=candidate, staged=False)


def _relocate_items(
    items: tuple[VariationRenderResult, ...],
    *,
    source: Path,
    destination: Path,
) -> tuple[VariationRenderResult, ...]:
    """Staging 内の成果物 path を公開後 generation path へ写像する。"""

    def relocate(path: Path | None) -> Path | None:
        if path is None:
            return None
        try:
            relative = path.relative_to(source)
        except ValueError:
            return path
        return destination / relative

    return tuple(
        replace(
            item,
            thumbnail_path=relocate(item.thumbnail_path),
            manifest_path=relocate(item.manifest_path),
        )
        for item in items
    )


def _relocate_capture_manifests(
    items: tuple[VariationRenderResult, ...],
    *,
    source: Path,
    destination: Path,
) -> None:
    """Staging 内 manifest の artifact path を公開後 path へ書き換える。"""

    if source == destination:
        return
    for item in items:
        artifact = item.thumbnail_path
        manifest = item.manifest_path
        if artifact is None or manifest is None:
            continue
        try:
            public_artifact = destination / artifact.relative_to(source)
            manifest.relative_to(source)
        except ValueError:
            continue
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"capture manifest が object ではありません: {manifest}")
        old_path = str(artifact)
        new_path = str(public_artifact)
        artifact_paths = payload.get("artifact_paths")
        if isinstance(artifact_paths, list):
            payload["artifact_paths"] = [
                new_path if value == old_path else value for value in artifact_paths
            ]
        output = payload.get("output")
        if isinstance(output, dict):
            output_paths = output.get("artifact_paths")
            if isinstance(output_paths, list):
                output["artifact_paths"] = [
                    new_path if value == old_path else value for value in output_paths
                ]
        _publish_text(
            manifest,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            overwrite=True,
        )


def _publish_batch_directory(batch: _BatchDirectory) -> None:
    """Staging generation を完成後だけ公開し、失敗時は旧版を戻す。"""

    if not batch.staged:
        return

    backup: Path | None = None
    if os.path.lexists(batch.final):
        backup = Path(
            tempfile.mkdtemp(
                prefix=f".{batch.final.name}.backup-",
                dir=batch.final.parent,
            )
        )
        backup.rmdir()
        os.replace(batch.final, backup)
    try:
        os.replace(batch.working, batch.final)
    except BaseException:
        if backup is not None and os.path.lexists(backup):
            os.replace(backup, batch.final)
        raise
    if backup is not None:
        try:
            shutil.rmtree(backup)
        except OSError:
            # 新 generation は既に公開済み。private backup の後始末失敗を
            # publish failure として誤報し、再実行で新 generation を壊さない。
            pass


def _filename_slug(value: str) -> str:
    slug = re.sub(r"[^\w.-]+", "_", str(value), flags=re.UNICODE).strip("_.-")
    return (slug or "variation")[:64].rstrip("_.-") or "variation"


def _thumbnail_name(
    index: int,
    variation: Variation,
    image_format: ExportFormat,
) -> str:
    seed = "none" if variation.seed is None else str(variation.seed)
    return (
        f"{int(index):03d}_{_filename_slug(variation.name)}_seed-{seed}"
        f"{image_format.suffix}"
    )


def _summary_path(path: Path | None, relative_to: Path | None) -> str | None:
    if path is None:
        return None
    if relative_to is None:
        return str(path)
    return Path(os.path.relpath(path, relative_to)).as_posix()


def _contact_sheet_svg(
    items: tuple[VariationRenderResult, ...],
    *,
    output_directory: Path,
    thumbnail_size: tuple[int, int],
    columns: int | None,
) -> str:
    count = max(1, len(items))
    column_count = (
        min(4, max(1, math.ceil(math.sqrt(count))))
        if columns is None
        else min(int(columns), count)
    )
    row_count = math.ceil(count / column_count)
    thumb_w, thumb_h = thumbnail_size
    padding = 16
    label_height = 58
    cell_w = thumb_w + 2 * padding
    cell_h = thumb_h + label_height + 2 * padding
    sheet_w = cell_w * column_count
    sheet_h = cell_h * row_count
    body: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{sheet_w}" '
            f'height="{sheet_h}" viewBox="0 0 {sheet_w} {sheet_h}">'
        ),
        '<rect width="100%" height="100%" fill="#E8E8E8"/>',
        '<g font-family="-apple-system, BlinkMacSystemFont, sans-serif">',
    ]
    for index, item in enumerate(items):
        column = index % column_count
        row = index // column_count
        x = column * cell_w + padding
        y = row * cell_h + padding
        body.append(
            f'<rect x="{x}" y="{y}" width="{thumb_w}" height="{thumb_h}" '
            'rx="4" fill="#FFFFFF"/>'
        )
        if item.thumbnail_path is not None:
            href = escape(
                _summary_path(item.thumbnail_path, output_directory) or "",
                quote=True,
            )
            body.append(
                f'<image x="{x}" y="{y}" width="{thumb_w}" height="{thumb_h}" '
                f'href="{href}" preserveAspectRatio="xMidYMid meet"/>'
            )
        else:
            body.append(
                f'<text x="{x + 12}" y="{y + thumb_h // 2}" '
                'font-size="14" fill="#B42318">Render failed</text>'
            )
        label_y = y + thumb_h + 24
        seed_text = "—" if item.seed is None else str(item.seed)
        body.append(
            f'<text x="{x}" y="{label_y}" font-size="15" font-weight="600" '
            f'fill="#171717">{escape(item.variation_name)}</text>'
        )
        body.append(
            f'<text x="{x}" y="{label_y + 22}" font-size="12" fill="#555555">'
            f'seed {escape(seed_text)}</text>'
        )
        if item.error_message:
            message = item.error_message.replace("\n", " ")[:80]
            body.append(
                f'<title>{escape(item.error_type or "Error")}: {escape(message)}</title>'
            )
    body.extend(("</g>", "</svg>", ""))
    return "\n".join(body)


def _publish_text(path: Path, text: str, *, overwrite: bool) -> None:
    """完成済み sibling temp を atomic/no-clobber で公開する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(str(text))
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "VariationBatchResult",
    "VariationRenderResult",
    "VariationRenderStatus",
    "render_variation_batch",
]
