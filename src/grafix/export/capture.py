"""render 済み Frame の encode と安全な公開を一つにまとめる。"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Sequence
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Protocol

from grafix.api.render import ExportFormat, ExportResult, Frame, RGB01
from grafix.core.capture_provenance import CaptureProvenance
from grafix.core.capture_manifest import (
    CaptureManifest,
    PublishedCaptureGeneration,
    capture_manifest_path_for,
    publish_capture_generation,
)
from grafix.core.output_paths import VersionedPathAllocator, gcode_layer_output_path
from grafix.core.pipeline import RealizedLayer
from grafix.core.runtime_config import GCodeExportConfig
from grafix.export.gcode import GCodeParams, export_gcode
from grafix.export.image import png_output_size, rasterize_svg_to_png
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
    def background_color_rgb01(self) -> RGB01: ...

    @property
    def t(self) -> float: ...

    @property
    def provenance(self) -> CaptureProvenance | None: ...


class CaptureMode(StrEnum):
    """encoder と manifest を選ぶ内部 capture mode。"""

    SVG = "svg"
    PNG = "png"
    GCODE = "gcode"
    GCODE_LAYERS = "gcode_layers"

    @property
    def export_format(self) -> ExportFormat:
        """この mode が使用する path suffix の形式を返す。"""

        if self is CaptureMode.GCODE_LAYERS:
            return ExportFormat.GCODE
        return ExportFormat(self.value)

    @classmethod
    def from_path(cls, path: str | Path) -> CaptureMode:
        """path suffix から単一成果物の capture mode を返す。"""

        return cls(ExportFormat.from_path(path).value)

    def validate_path(self, path: str | Path) -> Path:
        """mode と path suffix の一致を検証し、Path を返す。"""

        target = Path(path)
        ExportFormat.resolve(target, self.export_format)
        return target


def _coerce_mode(mode: CaptureMode | ExportFormat | str) -> CaptureMode:
    if isinstance(mode, CaptureMode):
        return mode
    if isinstance(mode, ExportFormat):
        return CaptureMode(mode.value)
    try:
        return CaptureMode(str(mode).strip().casefold())
    except ValueError as exc:
        raise ValueError(f"未対応の capture mode です: {mode!r}") from exc


def _gcode_params(config: GCodeExportConfig | None) -> GCodeParams | None:
    """親 process で確定した immutable config を encoder parameter へ写す。"""

    if config is None:
        return None
    if not isinstance(config, GCodeExportConfig):
        raise TypeError("gcode_config は GCodeExportConfig または None である必要があります")
    return GCodeParams(
        travel_feed=config.travel_feed,
        draw_feed=config.draw_feed,
        z_up=config.z_up,
        z_down=config.z_down,
        y_down=config.y_down,
        origin=config.origin,
        decimals=config.decimals,
        paper_margin_mm=config.paper_margin_mm,
        bed_x_range=config.bed_x_range,
        bed_y_range=config.bed_y_range,
        bridge_draw_distance=config.bridge_draw_distance,
        optimize_travel=config.optimize_travel,
        allow_reverse=config.allow_reverse,
        canvas_height_mm=config.canvas_height_mm,
    )


class CaptureService:
    """Frame の形式別 encode、versioning、manifest 付き publish を所有する。

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
        retries = int(max_publish_retries)
        if retries <= 0:
            raise ValueError("max_publish_retries は 1 以上である必要があります")
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
        mode: CaptureMode | ExportFormat | str,
        output_size: tuple[int, int] | None = None,
        timeout_s: float = _DEFAULT_ENCODE_TIMEOUT_S,
        deadline_monotonic: float | None = None,
        gcode_config: GCodeExportConfig | None = None,
    ) -> tuple[Path, ...]:
        """frame を指定 path へ encode し、生成した path 列を返す。

        このメソッドは publish を行わない。呼び出し側は private staging path を渡し、
        完成後に :meth:`publish_staged` で generation を確定する。
        """

        capture_mode = _coerce_mode(mode)
        output_path = capture_mode.validate_path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if capture_mode is CaptureMode.SVG:
            return (
                export_svg(
                    frame.layers,
                    output_path,
                    canvas_size=frame.canvas_size,
                ),
            )

        if capture_mode is CaptureMode.PNG:
            timeout = float(timeout_s)
            if not isfinite(timeout) or timeout <= 0.0:
                raise ValueError("timeout_s は正の有限値である必要があります")
            deadline = None if deadline_monotonic is None else float(deadline_monotonic)
            if deadline is not None and not isfinite(deadline):
                raise ValueError("deadline_monotonic は有限値である必要があります")

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
                    output_size=output_size or png_output_size(frame.canvas_size),
                    background_color_rgb01=frame.background_color_rgb01,
                    timeout_s=remaining,
                )
            return (png_path,)

        if capture_mode is CaptureMode.GCODE:
            params = _gcode_params(gcode_config)
            return (
                export_gcode(
                    frame.layers,
                    output_path,
                    canvas_size=frame.canvas_size,
                    params=params,
                ),
            )

        params = _gcode_params(gcode_config)
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
                params=params,
            )
            paths.append(layer_path)
        return tuple(paths)

    def final_paths(
        self,
        frame: CaptureFrame,
        path: str | Path,
        *,
        mode: CaptureMode | ExportFormat | str,
    ) -> tuple[Path, ...]:
        """mode と layer 構成から正式な成果物 path 列を返す。"""

        capture_mode = _coerce_mode(mode)
        output_path = capture_mode.validate_path(path)
        if capture_mode is not CaptureMode.GCODE_LAYERS:
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
        mode: CaptureMode | ExportFormat | str,
        overwrite: bool = False,
        output_size: tuple[int, int] | None = None,
    ) -> PublishedCaptureGeneration | None:
        """完成済み staging と manifest を一つの generation として公開する。"""

        capture_mode = _coerce_mode(mode)
        output_path = capture_mode.validate_path(path)
        staged = tuple(Path(staged_path) for staged_path in staged_paths)
        finals = self.final_paths(frame, output_path, mode=capture_mode)
        if len(staged) != len(finals):
            raise ValueError(
                "staged artifact 数が期待値と一致しません: "
                f"got={len(staged)}, expected={len(finals)}"
            )
        # layer の無い per-layer G-code は従来どおり成果物も空 manifest も作らない。
        if not finals:
            return None

        dimensions = output_size
        if dimensions is None:
            dimensions = (
                png_output_size(frame.canvas_size)
                if capture_mode is CaptureMode.PNG
                else frame.canvas_size
            )

        manifest = CaptureManifest(
            t=float(frame.t),
            canvas_size=frame.canvas_size,
            format=capture_mode.value,
            artifact_paths=finals,
            provenance=frame.provenance,
            output_size=dimensions,
        )
        return publish_capture_generation(
            staged_artifact_paths=staged,
            artifact_paths=finals,
            manifest_path=capture_manifest_path_for(output_path),
            manifest=manifest,
            overwrite=bool(overwrite),
        )

    def _allocate_path(self, base_path: Path) -> Path:
        """artifact と manifest の双方が未使用の version path を予約する。"""

        while True:
            candidate = self._paths.allocate(base_path)
            if not os.path.lexists(capture_manifest_path_for(candidate)):
                return candidate

    def export(
        self,
        frame: Frame,
        path: str | Path,
        *,
        overwrite: bool = False,
        output_size: tuple[int, int] | None = None,
    ) -> ExportResult:
        """Frame を suffix から推論した形式で安全に保存する。

        ``overwrite=False`` では既存 artifact/manifest を避けて version path を予約し、
        publish 直前の late collision も別 version へ再試行する。encode は一度だけ
        private sibling staging で行い、成功した artifact と manifest だけを公開する。
        """

        if not isinstance(frame, Frame):
            raise TypeError("frame は Frame である必要があります")
        requested_path = Path(path)
        mode = CaptureMode.from_path(requested_path)
        if output_size is not None and mode is not CaptureMode.PNG:
            raise ValueError("output_size は PNG capture だけに指定できます")
        if output_size is not None:
            output_size = (int(output_size[0]), int(output_size[1]))
            if output_size[0] <= 0 or output_size[1] <= 0:
                raise ValueError("output_size は正の (width, height) である必要があります")
        requested_path.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{requested_path.stem}.capture-",
                dir=requested_path.parent,
            )
        )
        staged_output = staging_dir / requested_path.name
        try:
            frame_config = frame.metadata.effective_config
            if mode is CaptureMode.PNG:
                effective_output_size = output_size or png_output_size(
                    frame.canvas_size,
                    scale=frame_config.png_scale,
                )
            else:
                effective_output_size = frame.canvas_size
            staged_paths = self.encode(
                frame,
                staged_output,
                mode=mode,
                output_size=effective_output_size,
                gcode_config=(
                    frame_config.gcode if mode is CaptureMode.GCODE else None
                ),
            )
            if overwrite:
                published = self.publish_staged(
                    frame,
                    requested_path,
                    staged_paths,
                    mode=mode,
                    overwrite=True,
                    output_size=effective_output_size,
                )
                assert published is not None
                return ExportResult(
                    path=published.artifact_paths[0],
                    format=mode.export_format,
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
                        mode=mode,
                        output_size=effective_output_size,
                    )
                except FileExistsError as exc:
                    last_collision = exc
                    continue
                assert published is not None
                return ExportResult(
                    path=published.artifact_paths[0],
                    format=mode.export_format,
                    manifest_path=published.manifest_path,
                )
            raise FileExistsError(
                "capture publish が late collision の再試行上限に達しました: "
                f"retries={self._max_publish_retries}"
            ) from last_collision
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)


__all__ = ["CaptureFrame", "CaptureMode", "CaptureService"]
