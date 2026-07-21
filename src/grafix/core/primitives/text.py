"""
どこで: `src/grafix/core/primitives/text.py`。テキストプリミティブの実体生成。
何を: 同梱フォントと `config.yaml` の `font_dirs` を用い、フォントアウトラインからテキストのポリライン列を生成する。
なぜ: PyPI インストール環境でも確実に動く最小フォント経路を用意しつつ、外部フォントも扱えるようにするため。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from grafix.core.font_resolver import resolve_font_path
from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.primitives._text_layout import (
    aligned_line_origin_em,
    bounding_box_polylines_em,
    measure_line_width_em,
    wrap_line_by_width_em,
)
from grafix.core.realized_geometry import GeomTuple, empty_geom_tuple

DEFAULT_FONT = "NotoSansJP-Regular.ttf"

logger = logging.getLogger(__name__)
_UNSET = object()


class _LRU:
    """単純な上限付き LRU キャッシュ（キー: str）。"""

    def __init__(
        self,
        maxsize: int = 4096,
        *,
        maxbytes: int | None = None,
        size_of: Callable[[Any], int] | None = None,
    ) -> None:
        self.maxsize = int(maxsize)
        self.maxbytes = None if maxbytes is None else int(maxbytes)
        self._size_of = size_of
        self._byte_size = 0
        self._od: "OrderedDict[str, Any]" = OrderedDict()

    def get(self, key: str) -> Any | None:
        value = self._od.get(key)
        if value is not None:
            self._od.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        previous = self._od.pop(key, _UNSET)
        if previous is not _UNSET:
            self._byte_size -= self._value_size(previous)
        self._od[key] = value
        self._byte_size += self._value_size(value)
        self._od.move_to_end(key)
        while len(self._od) > self.maxsize or (
            self.maxbytes is not None and self._byte_size > self.maxbytes
        ):
            _old_key, old_value = self._od.popitem(last=False)
            self._byte_size -= self._value_size(old_value)

    def __len__(self) -> int:
        return len(self._od)

    @property
    def byte_size(self) -> int:
        return self._byte_size

    def clear(self) -> None:
        self._od.clear()
        self._byte_size = 0

    def _value_size(self, value: Any) -> int:
        if self._size_of is None:
            return 0
        return int(self._size_of(value))


def _glyph_polyline_bytes(value: Any) -> int:
    return sum(int(polyline.nbytes) for polyline in value)


class TextRenderer:
    """TTFont とグリフ平坦化コマンドを提供するキャッシュ。"""

    _instance: "TextRenderer | None" = None
    _fonts: dict[str, Any] = {}
    _glyph_cache = _LRU(maxsize=4096)
    _glyph_polyline_cache = _LRU(
        maxsize=256,
        maxbytes=32 * 1024 * 1024,
        size_of=_glyph_polyline_bytes,
    )

    def __new__(cls) -> "TextRenderer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_font(cls, path: Path, font_index: int) -> Any:
        """TTFont を取得する（キャッシュ）。"""
        from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

        idx = font_index
        if idx < 0:
            idx = 0

        resolved = path
        cache_key = f"{resolved}|{idx}"
        cached = cls._fonts.get(cache_key)
        if cached is not None:
            return cached

        if resolved.suffix.lower() == ".ttc":
            font = TTFont(resolved, fontNumber=idx)
        else:
            font = TTFont(resolved)
        cls._fonts[cache_key] = font
        return font

    @classmethod
    def get_glyph_commands(
        cls,
        *,
        char: str,
        font_path: Path,
        font_index: int,
        flat_seg_len_units: float,
        tt_font: Any | None = None,
        cmap: Any = _UNSET,
    ) -> tuple:
        """平坦化済みのグリフコマンド（`RecordingPen.value` 互換タプル）を返す。"""
        from fontTools.pens.recordingPen import (  # type: ignore[import-untyped]
            DecomposingRecordingPen,
        )

        from ._text_flatten import flatten_recording

        resolved = font_path
        key = (
            f"{resolved}|{font_index}|{char}|{round(float(flat_seg_len_units), 6)}"
        )
        cached = cls._glyph_cache.get(key)
        if cached is not None:
            return cached

        font_obj = (
            cls.get_font(resolved, font_index) if tt_font is None else tt_font
        )
        cmap_obj = font_obj.getBestCmap() if cmap is _UNSET else cmap
        if cmap_obj is None:
            cls._glyph_cache.set(key, tuple())
            return tuple()

        glyph_name = cmap_obj.get(ord(char))
        if glyph_name is None:
            if char.isascii() and char.isprintable():
                glyph_name = char
            else:
                logger.warning(
                    "Character '%s' (U+%04X) not found in font '%s'",
                    char,
                    ord(char),
                    str(resolved),
                )
                cls._glyph_cache.set(key, tuple())
                return tuple()

        glyph_set = font_obj.getGlyphSet()
        glyph = glyph_set.get(glyph_name)
        if glyph is None:
            logger.warning(
                "Glyph '%s' not found in font '%s'", glyph_name, str(resolved)
            )
            cls._glyph_cache.set(key, tuple())
            return tuple()

        rec = DecomposingRecordingPen(glyph_set, reverseFlipped=True)
        try:
            glyph.draw(rec)
        except rec.MissingComponentError:  # type: ignore[attr-defined]
            logger.warning(
                "Glyph '%s' has missing components in font '%s'",
                glyph_name,
                str(resolved),
            )
            cls._glyph_cache.set(key, tuple())
            return tuple()

        result = flatten_recording(
            rec,
            approximate_segment_length=int(round(float(flat_seg_len_units))),
        )
        cls._glyph_cache.set(key, result)
        return result

    @classmethod
    def get_glyph_polylines(
        cls,
        *,
        char: str,
        font_path: Path,
        font_index: int,
        flat_seg_len_units: float,
        tt_font: Any,
        cmap: Any,
    ) -> tuple[np.ndarray, ...]:
        """配置前のグリフ輪郭をfont unit座標のまま返す。"""

        resolved = font_path
        key = (
            f"{resolved}|{font_index}|{char}|"
            f"{round(float(flat_seg_len_units), 6)}"
        )
        cached = cls._glyph_polyline_cache.get(key)
        if cached is not None:
            return cached

        commands = cls.get_glyph_commands(
            char=char,
            font_path=resolved,
            font_index=font_index,
            flat_seg_len_units=float(flat_seg_len_units),
            tt_font=tt_font,
            cmap=cmap,
        )
        polylines = _glyph_commands_to_polylines_font_units(commands)
        cls._glyph_polyline_cache.set(key, polylines)
        return polylines

    @classmethod
    def clear_glyph_caches(cls) -> None:
        """font outline由来の二つのbounded cacheを同時に空にする。"""

        cls._glyph_cache.clear()
        cls._glyph_polyline_cache.clear()


TEXT_RENDERER = TextRenderer()


def _get_space_advance_em(tt_font: Any) -> float:
    """1em=1.0 とした space の advance 比率を返す。無ければ 0.25em を返す。"""

    try:
        space_width = tt_font["hmtx"].metrics["space"][0]  # type: ignore[index]
        return float(space_width) / float(tt_font["head"].unitsPerEm)  # type: ignore[index]
    except Exception:
        return 0.25


class _CallLocalFontMetrics:
    """1回のtext生成内でfont metric参照を文字単位に再利用する。"""

    def __init__(self, tt_font: Any) -> None:
        self._tt_font = tt_font
        self._space_advance: float | None = None
        self._cmap: Any = _UNSET
        self._advances: dict[str, float] = {}

    def space_advance_em(self) -> float:
        cached = self._space_advance
        if cached is None:
            cached = _get_space_advance_em(self._tt_font)
            self._space_advance = cached
        return cached

    def cmap(self) -> Any:
        if self._cmap is _UNSET:
            self._cmap = self._tt_font.getBestCmap()
        return self._cmap

    def char_advance_em(self, char: str) -> float:
        cached = self._advances.get(char)
        if cached is not None:
            return cached

        space_advance = self.space_advance_em()
        if char == " ":
            advance = space_advance
        else:
            cmap = self.cmap()
            glyph_name = None if cmap is None else cmap.get(ord(char))
            if glyph_name is None:
                advance = space_advance
            else:
                try:
                    advance_width = self._tt_font["hmtx"].metrics[glyph_name][0]
                    advance = float(advance_width) / float(
                        self._tt_font["head"].unitsPerEm
                    )
                except Exception:
                    advance = space_advance

        self._advances[char] = advance
        return advance


def _get_font_ascent_em(tt_font: Any, *, units_per_em: float) -> float:
    """フォントの ascent を em 比で返す。

    `y=0` を「ボックスの上辺」として扱うための補正に使う。
    """
    ascent_units: float
    try:
        ascent_units = float(tt_font["hhea"].ascent)  # type: ignore[index]
    except Exception:
        try:
            ascent_units = float(tt_font["OS/2"].sTypoAscender)  # type: ignore[index]
        except Exception:
            try:
                ascent_units = float(tt_font["head"].yMax)  # type: ignore[index]
            except Exception:
                return 0.0

    upm = float(units_per_em)
    if not np.isfinite(ascent_units) or not np.isfinite(upm) or upm <= 0.0:
        return 0.0
    return ascent_units / upm


def _glyph_commands_to_polylines_font_units(
    glyph_commands: Iterable,
) -> tuple[np.ndarray, ...]:
    """RecordingPen.valueから配置前のfont unit輪郭を生成する。"""
    polylines: list[np.ndarray] = []
    current: list[list[float]] = []

    def flush(*, close: bool) -> None:
        nonlocal current
        if not current:
            return
        if close and len(current) > 1:
            x0, y0 = current[0]
            x1, y1 = current[-1]
            if x0 != x1 or y0 != y1:
                current.append([x0, y0])

        arr2 = np.asarray(current, dtype=np.float32)
        # フォント座標（Y+上）を描画座標（Y+下）へ反転
        arr2[:, 1] *= -1.0
        arr2.setflags(write=False)
        polylines.append(arr2)
        current = []

    for cmd_type, cmd_values in glyph_commands:
        if cmd_type == "moveTo":
            flush(close=False)
            x, y = cmd_values[0]
            current.append([float(x), float(y)])
            continue
        if cmd_type == "lineTo":
            x, y = cmd_values[0]
            current.append([float(x), float(y)])
            continue
        if cmd_type == "closePath":
            flush(close=True)
            continue

    flush(close=False)
    return tuple(polylines)


def _pack_text_geometry(
    placements: list[tuple[tuple[np.ndarray, ...], float, float]],
    extra_polylines: list[np.ndarray],
    *,
    units_per_em: float,
    center: tuple[float, float, float],
    scale: float,
) -> GeomTuple:
    """配置指定から最終packed geometryへ直接書き込む。"""

    line_count = 0
    vertex_count = 0
    for polylines, _x_em, _y_em in placements:
        for polyline in polylines:
            length = int(polyline.shape[0])
            if length >= 2:
                line_count += 1
                vertex_count += length
    for polyline in extra_polylines:
        length = int(polyline.shape[0])
        if length >= 2:
            line_count += 1
            vertex_count += length

    if line_count == 0:
        return empty_geom_tuple()

    coords = np.empty((vertex_count, 3), dtype=np.float32)
    offsets = np.empty((line_count + 1,), dtype=np.int32)
    offsets[0] = 0

    cursor = 0
    line_index = 0
    if placements:
        unit_scale = np.float32(1.0 / float(units_per_em))
        upm = float(units_per_em)
        for polylines, x_em, y_em in placements:
            x_offset = np.float32(float(x_em) * upm)
            y_offset = np.float32(float(y_em) * upm)
            for polyline in polylines:
                length = int(polyline.shape[0])
                if length < 2:
                    continue
                end = cursor + length
                target = coords[cursor:end]
                target[:, 0] = (polyline[:, 0] + x_offset) * unit_scale
                target[:, 1] = (polyline[:, 1] + y_offset) * unit_scale
                target[:, 2] = 0.0
                cursor = end
                line_index += 1
                offsets[line_index] = cursor

    for polyline in extra_polylines:
        length = int(polyline.shape[0])
        if length < 2:
            continue
        end = cursor + length
        coords[cursor:end] = polyline
        cursor = end
        line_index += 1
        offsets[line_index] = cursor

    if center != (0.0, 0.0, 0.0) or scale != 1.0:
        center_vec = np.asarray(center, dtype=np.float32)
        coords = coords * np.float32(scale) + center_vec

    return coords, offsets


_TEXT_ALIGN_CHOICES = ("left", "center", "right")

text_meta = {
    "text": ParamMeta(
        kind="str",
        description="フォントの輪郭線で描画する文字列を指定し、改行で複数行に分けます。",
    ),
    "font": ParamMeta(
        kind="font",
        description="輪郭の取得に使うフォントファイルまたは登録済みフォント名を指定します。",
    ),
    "font_index": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=32,
        description="TTC コレクション内で使用するサブフォントの番号を指定します。",
    ),
    "text_align": ParamMeta(
        kind="choice",
        choices=_TEXT_ALIGN_CHOICES,
        description="各行の輪郭を左揃え・中央揃え・右揃えのいずれで配置するか選択します。",
    ),
    "letter_spacing_em": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=2.0,
        description="フォント固有の文字送りへ追加する文字間隔を em 単位で指定します。",
    ),
    "line_height": ParamMeta(
        kind="float",
        ui_min=0.8,
        ui_max=3.0,
        description="複数行のベースライン間隔を em 単位で指定します。",
    ),
    "use_bounding_box": ParamMeta(
        kind="bool",
        description="指定幅での自動改行と任意のボックス枠描画を有効にします。",
    ),
    "box_width": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=300.0,
        description="自動改行と枠描画に使うボックス幅を出力座標単位で指定します。",
    ),
    "box_height": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=300.0,
        description="枠描画に使うボックス高さを出力座標単位で指定します。",
    ),
    "show_bounding_box": ParamMeta(
        kind="bool",
        description="指定した幅と高さのボックス枠を文字輪郭へ追加します。",
    ),
    "quality": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=1.0,
        description="曲線輪郭の平坦化精度を指定し、大きいほど頂点数を増やします。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="生成した文字輪郭全体を平行移動する XYZ 座標を指定します。",
    ),
    "scale": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=50.0,
        description="1 em を基準に生成した文字輪郭へ適用する等方スケールを指定します。",
    ),
}

TEXT_UI_VISIBLE = {
    "box_width": lambda v: v.get("use_bounding_box") is True,
    "box_height": lambda v: v.get("use_bounding_box") is True,
    "show_bounding_box": lambda v: v.get("use_bounding_box") is True,
}


@primitive(meta=text_meta, ui_visible=TEXT_UI_VISIBLE)
def text(
    *,
    text: str = "HELLO",
    font: str = DEFAULT_FONT,
    font_index: int = 0,
    text_align: str = "left",
    letter_spacing_em: float = 0.0,
    line_height: float = 1.2,
    use_bounding_box: bool = False,
    box_width: float = -1.0,
    box_height: float = -1.0,
    show_bounding_box: bool = False,
    quality: float = 0.5,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> GeomTuple:
    """フォントアウトラインからテキストのポリライン列を生成する。

    Parameters
    ----------
    text : str, optional
        描画する文字列。`\\n` 区切りで複数行を表す。
    font : str, optional
        フォント指定（実在パス / ファイル名 / ステム / 部分一致）。
        解決順は以下。
        1) `font` が実在パスならそのファイル
        2) config.yaml の `font_dirs`（先頭から）
        3) grafix 同梱フォント（Google Sans / Noto Sans JP）
    font_index : int, optional
        `.ttc` の subfont 番号（0 以上）。`.ttf/.otf` では無視される。
    text_align : str, optional
        行揃え（`left|center|right`）。
    letter_spacing_em : float, optional
        文字間の追加スペーシング（em 比）。
    line_height : float, optional
        行送り（em 比）。
    use_bounding_box : bool, optional
        True のとき `box_width` による自動改行と、`show_bounding_box` による枠描画を有効にする。
    box_width : float, optional
        幅による自動改行を行う際のボックス幅（出力座標系）。0 以下なら無効。
    box_height : float, optional
        デバッグ用ボックス表示の高さ（出力座標系）。0 以下なら無効。
    show_bounding_box : bool, optional
        True のとき、`box_width/box_height` で指定されたボックス枠（4本の線分）を追加で描画する。
    quality : float, optional
        平坦化品質（0..1）。大きいほど精緻（点が増える）。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率 s。縦横比変更は effect を使用する。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        テキスト輪郭をポリライン列として持つ実体ジオメトリ（coords, offsets）。

    Raises
    ------
    ValueError
        `font_index` が負、または `quality` が 0 以上 1 以下の範囲外の場合。
    FileNotFoundError
        フォントを解決できない場合。

    Notes
    -----
    基準の座標系は「1em=1.0」で生成し、最後に `scale` と `center` を適用する。
    `box_width/box_height` は「出力座標系（scale 適用後）」で指定し、内部で em 座標へ換算して折り返し/枠を生成する。
    `y=0` をボックス上辺として扱えるように、1 行目のベースラインは常にフォントの ascent 分だけ下げる。
    """
    text_s = text
    font_s = font
    fi = font_index
    text_align_s = text_align
    use_bb = use_bounding_box
    show_bounding_box_b = show_bounding_box
    if fi < 0:
        raise ValueError("text の font_index は 0 以上である必要がある")
    if not 0.0 <= quality <= 1.0:
        raise ValueError("text の quality は 0 以上 1 以下である必要がある")

    font_path = resolve_font_path(font_s)
    tt_font = TEXT_RENDERER.get_font(font_path, fi)
    units_per_em = float(tt_font["head"].unitsPerEm)  # type: ignore[index]
    metrics = _CallLocalFontMetrics(tt_font)
    q = quality

    tol_min_em = 0.001
    tol_max_em = 0.1
    flat_seg_len_em = tol_max_em * (tol_min_em / tol_max_em) ** q
    seg_len_units = max(1.0, flat_seg_len_em * units_per_em)

    lines = text_s.split("\n")
    s_f = scale
    s_abs = abs(s_f)
    bw = box_width
    bh = box_height
    if use_bb and bw > 0.0 and s_abs > 0.0:
        bw_em = bw / s_abs
        wrapped: list[str] = []
        for line_str in lines:
            wrapped.extend(
                wrap_line_by_width_em(
                    line_str,
                    max_width_em=bw_em,
                    char_advance_em=metrics.char_advance_em,
                    letter_spacing_em=letter_spacing_em,
                )
            )
        lines = wrapped

    placements: list[tuple[tuple[np.ndarray, ...], float, float]] = []
    glyphs_by_char: dict[str, tuple[np.ndarray, ...]] = {}

    y_em = _get_font_ascent_em(tt_font, units_per_em=units_per_em)
    for li, line_str in enumerate(lines):
        width_em = measure_line_width_em(
            line_str,
            char_advance_em=metrics.char_advance_em,
            letter_spacing_em=letter_spacing_em,
        )
        x_em = aligned_line_origin_em(width_em, text_align_s)

        cur_x_em = x_em
        for ch in line_str:
            if ch != " ":
                glyph_polylines = glyphs_by_char.get(ch)
                if glyph_polylines is None:
                    glyph_polylines = TEXT_RENDERER.get_glyph_polylines(
                        char=ch,
                        font_path=font_path,
                        font_index=fi,
                        flat_seg_len_units=seg_len_units,
                        tt_font=tt_font,
                        cmap=metrics.cmap(),
                    )
                    glyphs_by_char[ch] = glyph_polylines
                if glyph_polylines:
                    placements.append((glyph_polylines, cur_x_em, y_em))
            cur_x_em += metrics.char_advance_em(ch) + letter_spacing_em

        if li < len(lines) - 1:
            y_em += line_height

    extra_polylines: list[np.ndarray] = []
    if (
        use_bb
        and show_bounding_box_b
        and bw > 0.0
        and bh > 0.0
        and s_abs > 0.0
    ):
        bw_em = bw / s_abs
        bh_em = bh / s_abs

        extra_polylines.extend(
            bounding_box_polylines_em(
                width_em=bw_em,
                height_em=bh_em,
                align=text_align_s,
            )
        )

    return _pack_text_geometry(
        placements,
        extra_polylines,
        units_per_em=units_per_em,
        center=center,
        scale=scale,
    )
