"""ヘッドレス描画の共通データ型と長寿命セッションを提供する。

``RenderSession`` は 1 回の ``draw(t)`` ではなく、作品を評価する期間を所有する。
そのため、複数フレームで ParamStore、style 解決器、設定スナップショット、
Geometry の realize cache を再利用できる。ファイルへの保存はこのモジュールの責務に
含めず、描画結果を immutable な ``Frame`` として返すところで止める。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from numbers import Integral, Real
from pathlib import Path
from typing import Literal, TypeAlias, cast

from grafix.core.capture_provenance import (
    CaptureProvenance,
    CaptureProvenanceBuilder,
    SessionProvenance,
)
from grafix.core.layer import LayerStyleDefaults
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.persistence import (
    default_param_store_path,
    load_param_store,
    load_param_store_with_recovery,
)
from grafix.core.parameters.runtime import LoadProvenance
from grafix.core.parameters.source import ParameterLoadMode
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.style_resolver import FrameStyle, StyleResolver
from grafix.core.pipeline import RealizedLayer, realize_scene
from grafix.core.preview_quality import current_preview_quality, preview_quality_context
from grafix.core.realize import DEFAULT_MAX_CACHE_BYTES, RealizeSession
from grafix.core.resource_budget import DEFAULT_RESOURCE_BUDGET, ResourceBudget
from grafix.core.runtime_limits import RuntimeLimits
from grafix.core.runtime_config import RuntimeConfig, runtime_config_scope
from grafix.core.scene import SceneItem

RGB01: TypeAlias = tuple[float, float, float]
RGB8: TypeAlias = tuple[int, int, int]


# 依存ライブラリや OS の色データベースに結果を左右されない、CSS の基本色名。
# 名前は case-insensitive とし、space / hyphen は入力時に無視する。
_NAMED_COLOR_RGB8: dict[str, RGB8] = {
    "aqua": (0, 255, 255),
    "black": (0, 0, 0),
    "blue": (0, 0, 255),
    "brown": (165, 42, 42),
    "coral": (255, 127, 80),
    "cyan": (0, 255, 255),
    "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169),
    "fuchsia": (255, 0, 255),
    "gold": (255, 215, 0),
    "gray": (128, 128, 128),
    "green": (0, 128, 0),
    "grey": (128, 128, 128),
    "indigo": (75, 0, 130),
    "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211),
    "lime": (0, 255, 0),
    "magenta": (255, 0, 255),
    "maroon": (128, 0, 0),
    "navy": (0, 0, 128),
    "olive": (128, 128, 0),
    "orange": (255, 165, 0),
    "pink": (255, 192, 203),
    "purple": (128, 0, 128),
    "rebeccapurple": (102, 51, 153),
    "red": (255, 0, 0),
    "silver": (192, 192, 192),
    "teal": (0, 128, 128),
    "violet": (238, 130, 238),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
}


def _rgb8_to_rgb01(rgb8: RGB8) -> RGB01:
    return tuple(float(channel) / 255.0 for channel in rgb8)  # type: ignore[return-value]


def _normalize_color(value: object) -> RGB01:
    if isinstance(value, Color):
        return value.rgb01

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#"):
            digits = text[1:]
            if len(digits) == 3:
                digits = "".join(channel * 2 for channel in digits)
            if len(digits) != 6:
                raise ValueError("hex color は #RGB または #RRGGBB で指定してください")
            try:
                rgb8 = tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))
            except ValueError as exc:
                raise ValueError(f"不正な hex color です: {value!r}") from exc
            return _rgb8_to_rgb01(rgb8)  # type: ignore[arg-type]

        name = "".join(character for character in text.casefold() if character not in " -_")
        try:
            return _rgb8_to_rgb01(_NAMED_COLOR_RGB8[name])
        except KeyError as exc:
            raise ValueError(f"未対応の named color です: {value!r}") from exc

    if isinstance(value, (bytes, bytearray)):
        raise TypeError("color は hex、named color、RGB8、RGB01 のいずれかで指定してください")
    try:
        channels: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(
            "color は hex、named color、RGB8、RGB01 のいずれかで指定してください"
        ) from exc
    if len(channels) != 3:
        raise ValueError("RGB color は 3 要素である必要があります")
    if any(isinstance(channel, bool) for channel in channels):
        raise TypeError("RGB channel に bool は使用できません")

    if all(isinstance(channel, Integral) for channel in channels):
        rgb8 = tuple(int(cast(Integral, channel)) for channel in channels)
        if any(channel < 0 or channel > 255 for channel in rgb8):
            raise ValueError("RGB8 channel は 0..255 の範囲で指定してください")
        return _rgb8_to_rgb01(rgb8)  # type: ignore[arg-type]

    if not all(isinstance(channel, Real) for channel in channels):
        raise TypeError("RGB channel はすべて int または float で指定してください")
    rgb01 = tuple(float(cast(Real, channel)) for channel in channels)
    if any(not isfinite(channel) or channel < 0.0 or channel > 1.0 for channel in rgb01):
        raise ValueError("RGB01 channel は有限な 0.0..1.0 の範囲で指定してください")
    return rgb01  # type: ignore[return-value]


@dataclass(frozen=True, slots=True, init=False)
class Color:
    """hex、named color、RGB8、RGB01 を RGB01 へ正規化した不変色。

    Parameters
    ----------
    value : Color, str or Sequence[int | float]
        ``"#09f"`` / ``"#0099ff"``、基本 named color、0..255 の整数 RGB、
        または 0.0..1.0 の float RGB。整数列は RGB8、float 列は RGB01 と解釈する。
    """

    rgb01: RGB01

    def __init__(self, value: ColorInput) -> None:
        object.__setattr__(self, "rgb01", _normalize_color(value))

    def __iter__(self) -> Iterator[float]:
        """RGB01 channel を順に返す。"""

        return iter(self.rgb01)

    def __len__(self) -> int:
        return 3

    def __getitem__(self, index: int) -> float:
        return self.rgb01[index]


ColorInput: TypeAlias = Color | str | Sequence[int | float]

_WHITE = Color("white")
_BLACK = Color("black")


class ExportFormat(StrEnum):
    """path suffix と一対一に対応する出力形式。"""

    SVG = "svg"
    PNG = "png"
    GCODE = "gcode"

    @property
    def suffix(self) -> str:
        """この形式の canonical suffix を返す。"""

        return f".{self.value}"

    @classmethod
    def from_path(cls, path: str | Path) -> ExportFormat:
        """path suffix だけから形式を確定する。"""

        suffix = Path(path).suffix.casefold()
        for item in cls:
            if suffix == item.suffix:
                return item
        raise ValueError(f"未対応または未指定の export suffix です: {suffix!r}")

    @classmethod
    def resolve(
        cls,
        path: str | Path,
        explicit_format: ExportFormat | str | None = None,
    ) -> ExportFormat:
        """suffix を正とし、明示形式があれば一致を検証する。"""

        suffix_format = cls.from_path(path)
        if explicit_format is None:
            return suffix_format
        try:
            requested = (
                explicit_format
                if isinstance(explicit_format, cls)
                else cls(str(explicit_format).strip().casefold().lstrip("."))
            )
        except ValueError as exc:
            raise ValueError(f"未対応の export format です: {explicit_format!r}") from exc
        if requested is not suffix_format:
            raise ValueError(
                "export format と path suffix が一致しません: "
                f"format={requested.value!r}, suffix={Path(path).suffix!r}"
            )
        return suffix_format


@dataclass(frozen=True, slots=True, init=False)
class RenderOptions:
    """preview/export が共有する不変の描画設定。

    Parameters
    ----------
    canvas_size : tuple[int, int]
        論理キャンバスの ``(width, height)``。
    background_color : ColorInput
        背景色。``Color`` と同じ入口で受け、内部では RGB01 に正規化する。
    line_color : ColorInput
        Layer に色指定がない場合の線色。
    line_thickness : float
        Layer に太さ指定がない場合の線幅。値はキャンバス短辺に対する比率であり、
        既定 ``0.001`` は短辺の 0.1% に相当する。
    """

    canvas_size: tuple[int, int]
    background_color: Color
    line_color: Color
    line_thickness: float

    def __init__(
        self,
        *,
        canvas_size: tuple[int, int] = (800, 800),
        background_color: ColorInput = _WHITE,
        line_color: ColorInput = _BLACK,
        line_thickness: float = 0.001,
    ) -> None:
        try:
            width_raw, height_raw = canvas_size
        except (TypeError, ValueError) as exc:
            raise ValueError("canvas_size は (width, height) の 2 要素で指定してください") from exc
        if (
            isinstance(width_raw, bool)
            or isinstance(height_raw, bool)
            or not isinstance(width_raw, Integral)
            or not isinstance(height_raw, Integral)
        ):
            raise TypeError("canvas_size は整数の (width, height) で指定してください")
        normalized_size = (int(width_raw), int(height_raw))
        if normalized_size[0] <= 0 or normalized_size[1] <= 0:
            raise ValueError("canvas_size は正の (width, height) である必要があります")

        if isinstance(line_thickness, bool):
            raise TypeError("line_thickness は正の有限値である必要があります")
        thickness = float(line_thickness)
        if not isfinite(thickness) or thickness <= 0.0:
            raise ValueError("line_thickness は正の有限値である必要があります")

        object.__setattr__(self, "canvas_size", normalized_size)
        object.__setattr__(self, "background_color", Color(background_color))
        object.__setattr__(self, "line_color", Color(line_color))
        object.__setattr__(self, "line_thickness", thickness)


@dataclass(frozen=True, slots=True)
class RenderSessionMetadata:
    """セッション開始時に固定した config と parameter load 情報。"""

    config_path: Path | None
    effective_config: RuntimeConfig
    parameter_source: ParameterLoadMode
    parameter_store_path: Path | None
    parameter_load_provenance: LoadProvenance
    provenance: SessionProvenance

    def __post_init__(self) -> None:
        if self.config_path is not None:
            object.__setattr__(self, "config_path", Path(self.config_path))
        if isinstance(self.parameter_source, Path):
            object.__setattr__(self, "parameter_source", Path(self.parameter_source))
        if self.parameter_store_path is not None:
            object.__setattr__(self, "parameter_store_path", Path(self.parameter_store_path))


@dataclass(frozen=True, slots=True)
class Frame:
    """``RenderSession.render`` が返す 1 フレーム分の不変スナップショット。"""

    t: float
    layers: tuple[RealizedLayer, ...]
    options: RenderOptions
    style: FrameStyle
    metadata: RenderSessionMetadata
    provenance: CaptureProvenance

    def __post_init__(self) -> None:
        t = float(self.t)
        if not isfinite(t):
            raise ValueError("t は有限値である必要があります")
        object.__setattr__(self, "t", t)
        object.__setattr__(self, "layers", tuple(self.layers))

    @property
    def canvas_size(self) -> tuple[int, int]:
        """論理キャンバス寸法を返す。"""

        return self.options.canvas_size

    @property
    def background_color(self) -> Color:
        """ParamStore override 適用後の背景色を返す。"""

        return Color(self.style.bg_color_rgb01)

    @property
    def background_color_rgb01(self) -> RGB01:
        """ParamStore override 適用後の背景色を内部 RGB01 で返す。"""

        return self.style.bg_color_rgb01


@dataclass(frozen=True, slots=True)
class ExportResult:
    """保存処理が確定した実出力 path と manifest を表す不変結果。"""

    path: Path
    format: ExportFormat
    manifest_path: Path | None = None

    def __post_init__(self) -> None:
        path = Path(self.path)
        artifact_format = ExportFormat.resolve(path, self.format)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "format", artifact_format)
        if self.manifest_path is not None:
            object.__setattr__(self, "manifest_path", Path(self.manifest_path))


def _load_parameter_store(
    draw: Callable[[float], SceneItem],
    *,
    parameter_source: ParameterLoadMode,
    run_id: str | None,
) -> tuple[ParamStore, ParameterLoadMode, Path | None]:
    if isinstance(parameter_source, Path):
        source_path = Path(parameter_source).expanduser().resolve(strict=False)
        return load_param_store(source_path), source_path, source_path
    if parameter_source == "code":
        return ParamStore(), "code", None
    if parameter_source not in {"saved", "recovery"}:
        raise ValueError(
            "parameter_source は 'code', 'saved', 'recovery', Path のいずれかです"
        )

    source_path = default_param_store_path(draw, run_id=run_id)
    if parameter_source == "saved":
        return load_param_store(source_path), "saved", source_path
    return load_param_store_with_recovery(source_path), "recovery", source_path


class RenderSession:
    """draw/store/config/style/cache を束ねる長寿命ヘッドレス描画セッション。

    Parameters
    ----------
    draw : Callable[[float], SceneItem]
        フレーム時刻を受け取り SceneItem を返す作品関数。
    options : RenderOptions, optional
        描画設定。省略時は ``RenderOptions()``。
    parameter_source : {"code", "saved", "recovery"} or Path, optional
        ``"code"`` はファイルを読まない空 store（headless の既定）、``"saved"`` は
        通常保存、``"recovery"`` は新しい session recovery を考慮し、``Path`` は
        そのファイルだけを読む。
    config_path : str or Path or None, optional
        明示 config。指定時はセッション作成時に読み、effective config を metadata へ固定する。
    run_id : str or None, optional
        saved/recovery の既定 ParamStore path に使う suffix。
    max_cache_bytes : int, optional
        セッション内 realize cache の byte 上限。
    resource_budget : ResourceBudget, optional
        operation 評価時の resource 上限。
    runtime_limits : RuntimeLimits or None, optional
        final render の operation/scene/cache/capture 上限。指定時は個別 cache/budget
        引数より優先する。
    seed : int or None, optional
        manifest に固定する作品 seed。乱数 global state は変更しない。
    """

    def __init__(
        self,
        draw: Callable[[float], SceneItem],
        *,
        options: RenderOptions | None = None,
        parameter_source: ParameterLoadMode = "code",
        config_path: str | Path | None = None,
        run_id: str | None = None,
        max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
        runtime_limits: RuntimeLimits | None = None,
        seed: int | None = None,
    ) -> None:
        if not callable(draw):
            raise TypeError("draw は callable である必要があります")
        if options is not None and not isinstance(options, RenderOptions):
            raise TypeError("options は RenderOptions である必要があります")

        # Session の評価期間だけ process-global config を固定し、close 時には呼び出し前の
        # explicit path/cache/report を復元する。scope は LIFO の単一 session 契約であり、
        # 並列 session の調停は行わない。
        config_stack = ExitStack()
        try:
            effective_config = config_stack.enter_context(
                runtime_config_scope(config_path)
            )
            store, normalized_source, store_path = _load_parameter_store(
                draw,
                parameter_source=parameter_source,
                run_id=run_id,
            )
            render_options = RenderOptions() if options is None else options
            style_resolver = StyleResolver(
                store,
                base_background_color_rgb01=render_options.background_color.rgb01,
                base_global_thickness=render_options.line_thickness,
                base_global_line_color_rgb01=render_options.line_color.rgb01,
            )

            effective_limits = (
                RuntimeLimits(
                    per_operation=resource_budget,
                    scene=resource_budget,
                    cpu_cache_bytes=max_cache_bytes,
                )
                if runtime_limits is None
                else runtime_limits
            )
            if not isinstance(effective_limits, RuntimeLimits):
                raise TypeError("runtime_limits は RuntimeLimits である必要があります")

            provenance_builder = CaptureProvenanceBuilder(
                draw,
                config=effective_config,
                parameter_source=normalized_source,
                parameter_store_path=store_path,
                parameter_load_provenance=store.load_provenance,
                seed=seed,
            )
            realize_session = RealizeSession(runtime_limits=effective_limits)
            metadata = RenderSessionMetadata(
                config_path=effective_config.config_path,
                effective_config=effective_config,
                parameter_source=normalized_source,
                parameter_store_path=store_path,
                parameter_load_provenance=store.load_provenance,
                provenance=provenance_builder.session,
            )
        except BaseException:
            config_stack.close()
            raise

        self._draw = draw
        self._options = render_options
        self._store = store
        self._config = effective_config
        self._style_resolver = style_resolver
        self._runtime_limits = effective_limits
        self._realize_session = realize_session
        self._config_stack = config_stack
        self._provenance_builder = provenance_builder
        self._frame_index = 0
        self._metadata = metadata
        self._closed = False

    def __enter__(self) -> RenderSession:
        if self._closed:
            raise RuntimeError("close 済みの RenderSession は再利用できません")
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @property
    def options(self) -> RenderOptions:
        return self._options

    @property
    def param_store(self) -> ParamStore:
        return self._store

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def style_resolver(self) -> StyleResolver:
        return self._style_resolver

    @property
    def realize_session(self) -> RealizeSession:
        return self._realize_session

    @property
    def runtime_limits(self) -> RuntimeLimits:
        return self._runtime_limits

    @property
    def metadata(self) -> RenderSessionMetadata:
        return self._metadata

    @property
    def closed(self) -> bool:
        return self._closed

    def render(
        self,
        t: float,
        *,
        provenance_seed: int | None | Literal["session"] = "session",
    ) -> Frame:
        """時刻 ``t`` を評価し、保存処理から独立した ``Frame`` を返す。

        Parameters
        ----------
        t : float
            評価時刻。
        provenance_seed : int, None, or {"session"}, optional
            ``"session"`` は session 構築時の seed を使う。int/None はこの
            Frame/manifest の provenance だけを上書きする。乱数 global state
            や draw の実行環境は変更しない。
        """

        if self._closed:
            raise RuntimeError("close 済みの RenderSession は使用できません")
        if provenance_seed != "session" and provenance_seed is not None and (
            isinstance(provenance_seed, bool)
            or not isinstance(provenance_seed, int)
        ):
            raise TypeError("provenance_seed は int、None、'session' のいずれかです")
        render_t = float(t)
        if not isfinite(render_t):
            raise ValueError("t は有限値である必要があります")

        # RenderSession は headless/final 契約を所有する。呼び出し元が interactive
        # preview の draft context 内にいても、その暗黙状態を session へ漏らさない。
        with preview_quality_context("final"):
            style = self._style_resolver.resolve()
            defaults = LayerStyleDefaults(
                color=style.global_line_color_rgb01,
                thickness=style.global_thickness,
            )
            with parameter_context(self._store):
                layers = tuple(
                    realize_scene(
                        self._draw,
                        render_t,
                        defaults,
                        session=self._realize_session,
                    )
                )
            provenance = self._provenance_builder.frame(
                self._store,
                t=render_t,
                frame_index=self._frame_index,
                quality=current_preview_quality(),
                origin="headless",
                provenance_seed=provenance_seed,
            )
        frame = Frame(
            t=render_t,
            layers=layers,
            options=self._options,
            style=style,
            metadata=self._metadata,
            provenance=provenance,
        )
        self._frame_index += 1
        return frame

    def close(self) -> None:
        """realize cache を解放し、以後の評価を禁止する。"""

        if self._closed:
            return
        self._closed = True
        try:
            self._realize_session.close()
        finally:
            self._config_stack.close()


def render(
    draw: Callable[[float], SceneItem],
    t: float = 0.0,
    *,
    options: RenderOptions | None = None,
    parameter_source: ParameterLoadMode = "code",
    config_path: str | Path | None = None,
    run_id: str | None = None,
    max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
    resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
    runtime_limits: RuntimeLimits | None = None,
    seed: int | None = None,
) -> Frame:
    """``draw(t)`` を final 品質で一度評価し、不変 ``Frame`` を返す。

    ファイル保存は行わない。複数時刻を評価する場合は、store/config/cache を再利用する
    :class:`RenderSession` を直接使用する。

    Parameters
    ----------
    draw : Callable[[float], SceneItem]
        フレーム時刻を受け取り SceneItem を返す作品関数。
    t : float, optional
        評価する時刻。既定は ``0.0``。
    options : RenderOptions or None, optional
        描画設定。省略時は ``RenderOptions()``。
    parameter_source : {"code", "saved", "recovery"} or Path, optional
        parameter の読み込み元。headless 既定の ``"code"`` は暗黙ファイルを読まない。
    config_path : str, Path or None, optional
        明示 config path。指定時は探索より優先する。
    run_id : str or None, optional
        saved/recovery の既定 ParamStore path に使う suffix。
    max_cache_bytes : int, optional
        単発評価中の realize cache 上限。
    resource_budget : ResourceBudget, optional
        operation と scene の resource 上限。
    runtime_limits : RuntimeLimits or None, optional
        final render の統合上限。指定時は個別 cache/budget 引数より優先する。
    seed : int or None, optional
        manifest に固定する作品 seed。乱数 global state は変更しない。

    Returns
    -------
    Frame
        保存処理から独立した final 品質のフレーム。
    """

    with RenderSession(
        draw,
        options=options,
        parameter_source=parameter_source,
        config_path=config_path,
        run_id=run_id,
        max_cache_bytes=max_cache_bytes,
        resource_budget=resource_budget,
        runtime_limits=runtime_limits,
        seed=seed,
    ) as session:
        return session.render(t)


__all__ = [
    "Color",
    "ColorInput",
    "ExportFormat",
    "ExportResult",
    "Frame",
    "ParameterLoadMode",
    "RGB01",
    "RGB8",
    "RenderOptions",
    "RenderSession",
    "RenderSessionMetadata",
    "render",
]
