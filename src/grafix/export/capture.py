"""render 済み frame snapshot の encode と安全な公開を一つにまとめる。"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from grafix.core.capture_manifest import (
    CaptureManifest,
    PublishedCaptureGeneration,
    capture_manifest_path_for,
    publish_capture_generation,
)
from grafix.core.capture_provenance import CaptureProvenance
from grafix.core.export_format import ExportFormat
from grafix.core.export_result import ExportResult
from grafix.core.gcode_params import GCodeParams
from grafix.core.output_paths import VersionedPathAllocator, gcode_layer_output_path
from grafix.core.pipeline import RealizedLayer
from grafix.core.value_validation import (
    exact_integer,
    finite_real,
    positive_integer_pair,
)
from grafix.export.gcode import export_gcode
from grafix.export.image import rasterize_svg_to_png
from grafix.export.svg import export_svg

_DEFAULT_ENCODE_TIMEOUT_S = 30.0
_DEFAULT_PUBLISH_RETRIES = 16


class CaptureFrame(Protocol):
    """CaptureService が必要とする immutable frame の最小 read-only 契約。"""

    @property
    def layers(self) -> Sequence[RealizedLayer]: ...

    @property
    def canvas_size(self) -> tuple[int, int]: ...

    @property
    def background_color_rgb01(self) -> tuple[float, float, float]: ...

    @property
    def t(self) -> float: ...

    @property
    def provenance(self) -> CaptureProvenance: ...


def _validate_split_gcode_layers(
    format: ExportFormat,
    split_gcode_layers: bool,
) -> None:
    """layer 分割 option と export format の組み合わせを検査する。"""

    if type(split_gcode_layers) is not bool:
        raise TypeError("split_gcode_layers は bool である必要があります")
    if split_gcode_layers and format is not ExportFormat.GCODE:
        raise ValueError(
            "split_gcode_layers は G-code export にのみ指定できます"
        )


class CaptureService:
    """CaptureFrame の形式別 encode、versioning、manifest 付き publish を所有する。

    Parameters
    ----------
    path_allocator : VersionedPathAllocator or None, optional
        ``overwrite=False`` の保存先予約に使う session-local allocator。
    max_publish_retries : int, optional
        allocation 後の外部 late collision を別 version へ再試行する上限。
    """

    def __init__(
        self,
        *,
        path_allocator: VersionedPathAllocator | None = None,
        max_publish_retries: int = _DEFAULT_PUBLISH_RETRIES,
    ) -> None:
        retries = exact_integer(
            max_publish_retries,
            name="max_publish_retries",
            minimum=1,
        )
        if path_allocator is not None and not isinstance(
            path_allocator, VersionedPathAllocator
        ):
            raise TypeError("path_allocator は VersionedPathAllocator である必要があります")
        self._paths = VersionedPathAllocator() if path_allocator is None else path_allocator
        self._max_publish_retries = retries

    def encode(
        self,
        frame: CaptureFrame,
        path: str | Path,
        *,
        format: ExportFormat,
        split_gcode_layers: bool = False,
        output_size: tuple[int, int] | None = None,
        timeout_s: float = _DEFAULT_ENCODE_TIMEOUT_S,
        deadline_monotonic: float | None = None,
        gcode_params: GCodeParams | None = None,
    ) -> tuple[Path, ...]:
        """frame を指定 path へ encode し、生成した path 列を返す。

        このメソッドは publish を行わない。呼び出し側は private staging path を渡し、
        完成後に :meth:`publish_staged` で generation を確定する。
        """

        if not isinstance(format, ExportFormat):
            raise TypeError("format は ExportFormat である必要があります")
        _validate_split_gcode_layers(format, split_gcode_layers)
        ExportFormat.resolve(path, format)
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format is ExportFormat.SVG:
            if output_size is not None or gcode_params is not None:
                raise ValueError("SVG encode に形式外の出力設定は指定できません")
            return (
                export_svg(
                    frame.layers,
                    output_path,
                    canvas_size=frame.canvas_size,
                ),
            )

        if format is ExportFormat.PNG:
            if gcode_params is not None:
                raise ValueError("PNG encode に gcode_params は指定できません")
            if output_size is None:
                raise ValueError("PNG encode には output_size が必要です")
            output_size = positive_integer_pair(output_size, name="output_size")
            timeout = finite_real(
                timeout_s,
                name="timeout_s",
                minimum=0.0,
                minimum_inclusive=False,
            )
            deadline = (
                None
                if deadline_monotonic is None
                else finite_real(deadline_monotonic, name="deadline_monotonic")
            )

            with tempfile.TemporaryDirectory(
                prefix=f".{output_path.stem}.png-intermediate-",
                dir=output_path.parent,
            ) as temp_dir:
                svg_path = Path(temp_dir) / "intermediate.svg"
                export_svg(frame.layers, svg_path, canvas_size=frame.canvas_size)
                remaining = timeout if deadline is None else deadline - time.monotonic()
                if remaining <= 0.0:
                    raise TimeoutError("PNG export deadline exceeded before resvg")
                png_path = rasterize_svg_to_png(
                    svg_path,
                    output_path,
                    output_size=output_size,
                    background_color_rgb01=frame.background_color_rgb01,
                    timeout_s=remaining,
                )
            return (png_path,)

        if not split_gcode_layers:
            if output_size is not None:
                raise ValueError("G-code encode に output_size は指定できません")
            if gcode_params is None:
                raise ValueError("G-code encode には gcode_params が必要です")
            if not isinstance(gcode_params, GCodeParams):
                raise TypeError("gcode_params は GCodeParams である必要があります")
            return (
                export_gcode(
                    frame.layers,
                    output_path,
                    canvas_size=frame.canvas_size,
                    params=gcode_params,
                ),
            )

        if output_size is not None:
            raise ValueError("layer 別 G-code encode に output_size は指定できません")
        if gcode_params is None:
            raise ValueError("layer 別 G-code encode には gcode_params が必要です")
        if not isinstance(gcode_params, GCodeParams):
            raise TypeError("gcode_params は GCodeParams である必要があります")
        paths: list[Path] = []
        for index, layer in enumerate(frame.layers, start=1):
            layer_path = gcode_layer_output_path(
                output_path,
                layer_index=index,
                n_layers=len(frame.layers),
                layer_name=layer.layer.name,
            )
            export_gcode(
                [layer],
                layer_path,
                canvas_size=frame.canvas_size,
                params=gcode_params,
            )
            paths.append(layer_path)
        return tuple(paths)

    def final_paths(
        self,
        frame: CaptureFrame,
        path: str | Path,
        *,
        format: ExportFormat,
        split_gcode_layers: bool = False,
    ) -> tuple[Path, ...]:
        """format と layer 構成から正式な成果物 path 列を返す。"""

        if not isinstance(format, ExportFormat):
            raise TypeError("format は ExportFormat である必要があります")
        _validate_split_gcode_layers(format, split_gcode_layers)
        ExportFormat.resolve(path, format)
        output_path = Path(path)
        if not split_gcode_layers:
            return (output_path,)
        return tuple(
            gcode_layer_output_path(
                output_path,
                layer_index=index,
                n_layers=len(frame.layers),
                layer_name=layer.layer.name,
            )
            for index, layer in enumerate(frame.layers, start=1)
        )

    def publish_staged(
        self,
        frame: CaptureFrame,
        path: str | Path,
        staged_paths: Sequence[str | Path],
        *,
        format: ExportFormat,
        split_gcode_layers: bool = False,
        overwrite: bool = False,
        output_size: tuple[int, int] | None = None,
    ) -> PublishedCaptureGeneration:
        """完成済み staging と manifest を一つの generation として公開する。"""

        if not isinstance(format, ExportFormat):
            raise TypeError("format は ExportFormat である必要があります")
        _validate_split_gcode_layers(format, split_gcode_layers)
        if type(overwrite) is not bool:
            raise TypeError("overwrite は bool である必要があります")
        ExportFormat.resolve(path, format)
        output_path = Path(path)
        staged = tuple(Path(staged_path) for staged_path in staged_paths)
        finals = self.final_paths(
            frame,
            output_path,
            format=format,
            split_gcode_layers=split_gcode_layers,
        )
        if len(staged) != len(finals):
            raise ValueError(
                "staged artifact 数が期待値と一致しません: "
                f"got={len(staged)}, expected={len(finals)}"
            )
        if not finals:
            raise ValueError("layer 別 G-code capture には 1 layer 以上必要です")

        if format is ExportFormat.PNG:
            if output_size is None:
                raise ValueError("PNG publish には output_size が必要です")
            dimensions = positive_integer_pair(output_size, name="output_size")
        else:
            if output_size is not None:
                raise ValueError("output_size は PNG publish にのみ指定できます")
            dimensions = frame.canvas_size

        manifest = CaptureManifest(
            t=frame.t,
            canvas_size=frame.canvas_size,
            format=format.value,
            artifact_paths=finals,
            provenance=frame.provenance,
            output_size=dimensions,
        )
        return publish_capture_generation(
            staged_artifact_paths=staged,
            artifact_paths=finals,
            manifest_path=capture_manifest_path_for(output_path),
            manifest=manifest,
            overwrite=overwrite,
        )

    def _allocate_path(self, base_path: Path) -> Path:
        """artifact と manifest の双方が未使用の version path を予約する。"""

        while True:
            candidate = self._paths.allocate(base_path)
            if not os.path.lexists(capture_manifest_path_for(candidate)):
                return candidate

    def export(
        self,
        frame: CaptureFrame,
        path: str | Path,
        *,
        overwrite: bool = False,
        split_gcode_layers: bool = False,
        output_size: tuple[int, int] | None = None,
        gcode_params: GCodeParams | None = None,
    ) -> ExportResult:
        """CaptureFrame を suffix から推論した形式で安全に保存する。

        ``overwrite=False`` では既存 artifact/manifest を避けて version path を予約し、
        publish 直前の late collision も別 version へ再試行する。encode は一度だけ
        private sibling staging で行い、成功した artifact と manifest だけを公開する。
        """

        if type(overwrite) is not bool:
            raise TypeError("overwrite は bool である必要があります")
        requested_path = Path(path)
        format = ExportFormat.from_path(requested_path)
        _validate_split_gcode_layers(format, split_gcode_layers)
        if output_size is not None and format is not ExportFormat.PNG:
            raise ValueError("output_size は PNG capture だけに指定できます")
        if gcode_params is not None and format is not ExportFormat.GCODE:
            raise ValueError("gcode_params は G-code capture だけに指定できます")
        if gcode_params is not None and not isinstance(gcode_params, GCodeParams):
            raise TypeError("gcode_params は GCodeParams である必要があります")
        if output_size is not None:
            output_size = positive_integer_pair(output_size, name="output_size")
        requested_path.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{requested_path.stem}.capture-",
                dir=requested_path.parent,
            )
        )
        staged_output = staging_dir / requested_path.name
        try:
            if format is ExportFormat.PNG:
                if output_size is None:
                    raise ValueError("PNG export には output_size が必要です")
            if format is ExportFormat.GCODE and gcode_params is None:
                raise ValueError("G-code export には gcode_params が必要です")
            staged_paths = self.encode(
                frame,
                staged_output,
                format=format,
                split_gcode_layers=split_gcode_layers,
                output_size=output_size,
                gcode_params=(
                    gcode_params if format is ExportFormat.GCODE else None
                ),
            )
            if overwrite:
                published = self.publish_staged(
                    frame,
                    requested_path,
                    staged_paths,
                    format=format,
                    split_gcode_layers=split_gcode_layers,
                    overwrite=True,
                    output_size=output_size,
                )
                return ExportResult(
                    path=published.artifact_paths[0],
                    format=format,
                    manifest_path=published.manifest_path,
                )

            last_collision: FileExistsError | None = None
            for _attempt in range(self._max_publish_retries):
                output_path = self._allocate_path(requested_path)
                try:
                    published = self.publish_staged(
                        frame,
                        output_path,
                        staged_paths,
                        format=format,
                        split_gcode_layers=split_gcode_layers,
                        output_size=output_size,
                    )
                except FileExistsError as exc:
                    last_collision = exc
                    continue
                return ExportResult(
                    path=published.artifact_paths[0],
                    format=format,
                    manifest_path=published.manifest_path,
                )
            raise FileExistsError(
                "capture publish が late collision の再試行上限に達しました: "
                f"retries={self._max_publish_retries}"
            ) from last_collision
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)


__all__ = ["CaptureFrame", "CaptureService"]
