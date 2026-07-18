"""
どこで: `src/grafix/core/primitives/text.py`。テキストプリミティブの実体生成。
何を: 同梱フォントと `config.yaml` の `font_dirs` を用い、フォントアウトラインからテキストのポリライン列を生成する。
なぜ: PyPI インストール環境でも確実に動く最小フォント経路を用意しつつ、外部フォントも扱えるようにするため。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from grafix.core.font_resolver import resolve_font_path
from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple, empty_geom_tuple

DEFAULT_FONT = "NotoSansJP-Regular.ttf"

logger = logging.getLogger(__name__)


class _LRU:
    """単純な上限付き LRU キャッシュ（キー: str）。"""

    def __init__(self, maxsize: int = 4096) -> None:
        self.maxsize = int(maxsize)
        self._od: "OrderedDict[str, Any]" = OrderedDict()

    def get(self, key: str) -> Any | None:
        value = self._od.get(key)
        if value is not None:
            self._od.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._od[key] = value
        self._od.move_to_end(key)
        if len(self._od) > self.maxsize:
            self._od.popitem(last=False)


class TextRenderer:
    """TTFont とグリフ平坦化コマンドを提供するキャッシュ。"""

    _instance: "TextRenderer | None" = None
    _fonts: dict[str, Any] = {}
    _glyph_cache = _LRU(maxsize=4096)

    def __new__(cls) -> "TextRenderer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_font(cls, path: Path, font_index: int) -> Any:
        """TTFont を取得する（キャッシュ）。"""
        from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

        idx = int(font_index)
        if idx < 0:
            idx = 0

        resolved = path.resolve()
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
    ) -> tuple:
        """平坦化済みのグリフコマンド（`RecordingPen.value` 互換タプル）を返す。"""
        from fontPens.flattenPen import FlattenPen  # type: ignore[import-untyped]
        from fontTools.pens.recordingPen import (  # type: ignore[import-untyped]
            DecomposingRecordingPen,
            RecordingPen,
        )

        resolved = font_path.resolve()
        key = (
            f"{resolved}|{int(font_index)}|{char}|{round(float(flat_seg_len_units), 6)}"
        )
        cached = cls._glyph_cache.get(key)
        if cached is not None:
            return cached

        tt_font = cls.get_font(resolved, int(font_index))
        cmap = tt_font.getBestCmap()
        if cmap is None:
            cls._glyph_cache.set(key, tuple())
            return tuple()

        glyph_name = cmap.get(ord(char))
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

        glyph_set = tt_font.getGlyphSet()
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

        flat = RecordingPen()
        flatten_pen = FlattenPen(
            flat,
            approximateSegmentLength=int(round(float(flat_seg_len_units))),
            segmentLines=True,
        )
        rec.replay(flatten_pen)

        result = tuple(flat.value)
        cls._glyph_cache.set(key, result)
        return result


TEXT_RENDERER = TextRenderer()


def _get_space_advance_em(tt_font: Any) -> float:
    """1em=1.0 とした space の advance 比率を返す。無ければ 0.25em を返す。"""

    try:
        space_width = tt_font["hmtx"].metrics["space"][0]  # type: ignore[index]
        return float(space_width) / float(tt_font["head"].unitsPerEm)  # type: ignore[index]
    except Exception:
        return 0.25


def _get_char_advance_em(char: str, tt_font: Any) -> float:
    """1em を 1.0 とした advance の比率を返す。"""
    space_advance = _get_space_advance_em(tt_font)
    if char == " ":
        return space_advance

    cmap = tt_font.getBestCmap()
    if cmap is None:
        return space_advance
    glyph_name = cmap.get(ord(char))
    if glyph_name is None:
        return space_advance
    try:
        advance_width = tt_font["hmtx"].metrics[glyph_name][0]  # type: ignore[index]
        return float(advance_width) / float(tt_font["head"].unitsPerEm)  # type: ignore[index]
    except Exception:
        return space_advance


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


def _wrap_line_by_width_em(
    line_str: str,
    *,
    max_width_em: float,
    tt_font: Any,
    letter_spacing_em: float,
) -> list[str]:
    """1 行分の文字列を指定幅（em）で折り返して返す。

    空白がある場合は直近の空白で折り、無い場合は文字単位で折る。
    折り返し直後の行頭空白は落とす（`" "` の連続をスキップ）。
    """
    if max_width_em <= 0.0:
        return [line_str]
    if not line_str:
        return [""]

    s_em = float(letter_spacing_em)
    n = int(len(line_str))

    out: list[str] = []
    i = 0
    segment_start = 0
    segment_width_em = 0.0
    segment_len = 0
    last_space: int | None = None

    while i < n:
        ch = line_str[i]
        adv = _get_char_advance_em(ch, tt_font)
        inc = adv + (s_em if segment_len > 0 else 0.0)

        if segment_len > 0 and (segment_width_em + inc) > float(max_width_em):
            if last_space is not None and last_space > segment_start:
                out.append(line_str[segment_start:last_space])
                segment_start = last_space + 1
                while segment_start < n and line_str[segment_start] == " ":
                    segment_start += 1
                i = segment_start
            else:
                out.append(line_str[segment_start:i])
                segment_start = i
                while segment_start < n and line_str[segment_start] == " ":
                    segment_start += 1
                i = segment_start

            segment_width_em = 0.0
            segment_len = 0
            last_space = None
            continue

        if ch == " ":
            last_space = i
        segment_width_em += inc
        segment_len += 1
        i += 1

    if segment_start < n:
        out.append(line_str[segment_start:])
    return out


def _glyph_commands_to_polylines_em(
    glyph_commands: Iterable,
    *,
    units_per_em: float,
    x_em: float,
    y_em: float,
) -> list[np.ndarray]:
    """RecordingPen.value から「1em=1」の座標系でポリライン列へ変換して返す。"""
    scale = 1.0 / float(units_per_em)
    x_offset = float(x_em) * float(units_per_em)
    y_offset = float(y_em) * float(units_per_em)

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
        arr2[:, 0] = (arr2[:, 0] + np.float32(x_offset)) * np.float32(scale)
        arr2[:, 1] = (arr2[:, 1] + np.float32(y_offset)) * np.float32(scale)

        arr3 = np.zeros((arr2.shape[0], 3), dtype=np.float32)
        arr3[:, :2] = arr2
        polylines.append(arr3)
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
    return polylines


def _polylines_to_realized(
    polylines: list[np.ndarray],
    *,
    center: tuple[float, float, float],
    scale: float,
) -> GeomTuple:
    """ポリライン列を (coords, offsets) へ変換して返す。"""
    filtered = [
        p.astype(np.float32, copy=False) for p in polylines if int(p.shape[0]) >= 2
    ]
    if not filtered:
        return empty_geom_tuple()

    coords = np.concatenate(filtered, axis=0).astype(np.float32, copy=False)

    offsets = np.zeros(len(filtered) + 1, dtype=np.int32)
    acc = 0
    for i, line in enumerate(filtered):
        acc += int(line.shape[0])
        offsets[i + 1] = acc

    try:
        cx, cy, cz = center
    except Exception as exc:
        raise ValueError(
            "text の center は長さ 3 のシーケンスである必要がある"
        ) from exc
    try:
        s_f = float(scale)
    except Exception as exc:
        raise ValueError("text の scale は float である必要がある") from exc

    cx_f, cy_f, cz_f = float(cx), float(cy), float(cz)
    if (cx_f, cy_f, cz_f) != (0.0, 0.0, 0.0) or s_f != 1.0:
        center_vec = np.array([cx_f, cy_f, cz_f], dtype=np.float32)
        coords = coords * np.float32(s_f) + center_vec

    return coords, offsets


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
        choices=("left", "center", "right"),
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
    "box_width": lambda v: bool(v.get("use_bounding_box")),
    "box_height": lambda v: bool(v.get("use_bounding_box")),
    "show_bounding_box": lambda v: bool(v.get("use_bounding_box")),
}


@primitive(meta=text_meta, ui_visible=TEXT_UI_VISIBLE)
def text(
    *,
    text: str = "HELLO",
    font: str = DEFAULT_FONT,
    font_index: int | float = 0,
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
    font_index : int | float, optional
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
    FileNotFoundError
        フォントを解決できない場合。

    Notes
    -----
    基準の座標系は「1em=1.0」で生成し、最後に `scale` と `center` を適用する。
    `box_width/box_height` は「出力座標系（scale 適用後）」で指定し、内部で em 座標へ換算して折り返し/枠を生成する。
    `y=0` をボックス上辺として扱えるように、1 行目のベースラインは常にフォントの ascent 分だけ下げる。
    """
    fi = int(font_index)
    if fi < 0:
        fi = 0

    font_path = resolve_font_path(font)
    tt_font = TEXT_RENDERER.get_font(font_path, fi)
    units_per_em = float(tt_font["head"].unitsPerEm)  # type: ignore[index]
    q = float(quality)
    if q < 0.0:
        q = 0.0
    elif q > 1.0:
        q = 1.0

    tol_min_em = 0.001
    tol_max_em = 0.1
    flat_seg_len_em = tol_max_em * (tol_min_em / tol_max_em) ** q
    seg_len_units = max(1.0, flat_seg_len_em * units_per_em)

    lines = str(text).split("\n")
    use_bb = bool(use_bounding_box)
    s_f = float(scale)
    s_abs = abs(s_f)
    bw = float(box_width)
    bh = float(box_height)
    if use_bb and bw > 0.0 and s_abs > 0.0:
        bw_em = bw / s_abs
        wrapped: list[str] = []
        for line_str in lines:
            wrapped.extend(
                _wrap_line_by_width_em(
                    line_str,
                    max_width_em=bw_em,
                    tt_font=tt_font,
                    letter_spacing_em=float(letter_spacing_em),
                )
            )
        lines = wrapped

    polylines: list[np.ndarray] = []

    y_em = _get_font_ascent_em(tt_font, units_per_em=units_per_em)
    for li, line_str in enumerate(lines):
        width_em = 0.0
        for ch in line_str:
            width_em += _get_char_advance_em(ch, tt_font) + float(letter_spacing_em)
        if line_str:
            width_em -= float(letter_spacing_em)

        if text_align == "center":
            x_em = -width_em / 2.0
        elif text_align == "right":
            x_em = -width_em
        else:
            x_em = 0.0

        cur_x_em = x_em
        for ch in line_str:
            if ch != " ":
                cmds = TEXT_RENDERER.get_glyph_commands(
                    char=ch,
                    font_path=font_path,
                    font_index=fi,
                    flat_seg_len_units=seg_len_units,
                )
                if cmds:
                    polylines.extend(
                        _glyph_commands_to_polylines_em(
                            cmds,
                            units_per_em=units_per_em,
                            x_em=cur_x_em,
                            y_em=y_em,
                        )
                    )
            cur_x_em += _get_char_advance_em(ch, tt_font) + float(letter_spacing_em)

        if li < len(lines) - 1:
            y_em += float(line_height)

    if use_bb and bool(show_bounding_box) and bw > 0.0 and bh > 0.0 and s_abs > 0.0:
        bw_em = bw / s_abs
        bh_em = bh / s_abs

        if text_align == "center":
            x0 = -bw_em / 2.0
            x1 = bw_em / 2.0
        elif text_align == "right":
            x0 = -bw_em
            x1 = 0.0
        else:
            x0 = 0.0
            x1 = bw_em

        y0 = 0.0
        y1 = bh_em
        z0 = 0.0
        polylines.extend(
            [
                np.asarray([[x0, y0, z0], [x1, y0, z0]], dtype=np.float32),
                np.asarray([[x1, y0, z0], [x1, y1, z0]], dtype=np.float32),
                np.asarray([[x1, y1, z0], [x0, y1, z0]], dtype=np.float32),
                np.asarray([[x0, y1, z0], [x0, y0, z0]], dtype=np.float32),
            ]
        )

    return _polylines_to_realized(polylines, center=center, scale=scale)
