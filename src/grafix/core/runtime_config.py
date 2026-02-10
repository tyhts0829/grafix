# どこで: `src/grafix/core/runtime_config.py`。
# 何を: config.yaml による実行時設定（探索・ロード・キャッシュ）を提供する。
# なぜ: PyPI 環境でも、外部リソースや出力先をユーザーが指定できるようにするため。

"""実行時設定（`config.yaml`）の探索・ロード・キャッシュを担当する。

このモジュールは、以下を提供する:

- `config.yaml` を「同梱デフォルト → ユーザー設定（任意）」の順に適用して `RuntimeConfig` を構築
- 探索パス（CWD / HOME）と、明示指定（`set_config_path()`）の両方に対応
- 1 回ロードした結果をプロセス内でキャッシュ（設定を切り替える場合は `set_config_path()` で破棄）

入出力 / 副作用
----------------
- 入力: 同梱 `grafix/resource/default_config.yaml`、任意でユーザーの `config.yaml`
- 出力: `RuntimeConfig`（不変データ）
- 副作用: ファイル読み取り、YAML パース、モジュールグローバルへのキャッシュ保存

実装メモ
--------
- ユーザー設定の適用は `dict.update()`（トップレベルの浅い上書き）で行う。
  ネストした mapping は「部分的にマージ」されず「丸ごと置換」される。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


# parameter_gui の設定が省略された場合のフォールバック値。
_PARAMETER_GUI_FONT_SIZE_BASE_PX_DEFAULT = 12.0
# 重みは合計 1.0 を要求しない（ここでは正の値であることだけを検証する）。
_PARAMETER_GUI_TABLE_COLUMN_WEIGHTS_DEFAULT = (0.20, 0.60, 0.15, 0.20)


@dataclass(frozen=True, slots=True)
class GCodeExportConfig:
    """G-code 出力設定（`config.yaml` の `export.gcode`）。"""

    travel_feed: float
    draw_feed: float
    z_up: float
    z_down: float
    y_down: bool
    origin: tuple[float, float]
    decimals: int
    paper_margin_mm: float
    bed_x_range: tuple[float, float] | None
    bed_y_range: tuple[float, float] | None
    bridge_draw_distance: float | None
    optimize_travel: bool
    allow_reverse: bool
    canvas_height_mm: float | None


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """grafix の実行時設定。

    `runtime_config()` が `config.yaml` を解釈して構築する不変オブジェクト。
    実行時に参照される「ファイルパス」「UI の配置」「書き出し設定」などを集約する。

    Attributes
    ----------
    config_path:
        実際に採用されたユーザー設定ファイルのパス。
        明示指定（`set_config_path()`）または探索で見つかった 1 ファイルのどちらか。
        ユーザー設定が無い場合は None（同梱デフォルトのみで動作）。
    output_dir:
        生成物（PNG 等）の出力先ディレクトリ。
    sketch_dir:
        スケッチ検索用のベースディレクトリ（任意）。
    preset_module_dirs:
        preset モジュール探索用のディレクトリ列。
    font_dirs:
        フォント探索用のディレクトリ列。
    window_pos_draw:
        描画ウィンドウの左上座標 (x, y)。
    window_pos_parameter_gui:
        パラメータ GUI ウィンドウの左上座標 (x, y)。
    parameter_gui_window_size:
        パラメータ GUI のウィンドウサイズ (w, h)。
    parameter_gui_fallback_font_japanese:
        日本語表示時のフォールバックフォント名（任意）。
    parameter_gui_font_size_base_px:
        パラメータ GUI の基準フォントサイズ（px）。
    parameter_gui_table_column_weights:
        パラメータ GUI テーブル列の重み (name, value, min, max)。
        各要素は正の値である必要がある。
    png_scale:
        `python -m grafix export` における PNG の拡大率。
    gcode:
        `python -m grafix export` における G-code 出力設定。
    midi_inputs:
        MIDI 入力の設定。各要素は (port_name, mode)。
    """

    config_path: Path | None
    output_dir: Path
    sketch_dir: Path | None
    preset_module_dirs: tuple[Path, ...]
    font_dirs: tuple[Path, ...]
    window_pos_draw: tuple[int, int]
    window_pos_parameter_gui: tuple[int, int]
    parameter_gui_window_size: tuple[int, int]
    parameter_gui_fallback_font_japanese: str | None
    parameter_gui_font_size_base_px: float
    parameter_gui_table_column_weights: tuple[float, float, float, float]
    png_scale: float
    gcode: GCodeExportConfig
    midi_inputs: tuple[tuple[str, str], ...]


# `set_config_path()` で指定される「明示 config」のパス。
# ここが設定されている場合、探索で見つかった config よりも後に適用される。
_EXPLICIT_CONFIG_PATH: Path | None = None
# `runtime_config()` のプロセス内キャッシュ。設定を切り替える場合は破棄する。
_CONFIG_CACHE: RuntimeConfig | None = None


def set_config_path(path: str | Path | None) -> None:
    """以降の設定探索で使う明示 config パスを設定する。

    Parameters
    ----------
    path:
        `config.yaml` のパス。None の場合は明示指定を解除する。

    Notes
    -----
    - `path` を None にすると明示指定を解除し、既定の探索に戻る。
    - `path` は `~` を展開して保持する（環境変数の展開はしない）。
    - 設定が変わるため、`runtime_config()` のキャッシュを破棄する。
    """

    global _EXPLICIT_CONFIG_PATH, _CONFIG_CACHE
    if path is None:
        _EXPLICIT_CONFIG_PATH = None
        _CONFIG_CACHE = None
        return
    p = Path(str(path)).expanduser()
    _EXPLICIT_CONFIG_PATH = p
    _CONFIG_CACHE = None


def _default_config_candidates() -> tuple[Path, ...]:
    """既定の `config.yaml` 探索候補を返す。

    探索順（先勝ち）:
    - `./.grafix/config.yaml`
    - `~/.config/grafix/config.yaml`
    """

    cwd = Path.cwd()
    home = Path.home()
    return (
        cwd / ".grafix" / "config.yaml",
        home / ".config" / "grafix" / "config.yaml",
    )


def _expand_path_text(text: str) -> str:
    """パス文字列内の `~` と環境変数を展開して返す。"""

    return os.path.expandvars(os.path.expanduser(str(text)))


def _as_optional_path(value: Any) -> Path | None:
    """任意値を「空なら None / それ以外は Path」へ変換する。"""

    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return Path(_expand_path_text(s))


def _as_optional_str(value: Any) -> str | None:
    """任意値を「空なら None / それ以外は str」へ変換する。"""

    if value is None:
        return None
    s = str(value).strip()
    return None if not s else s


def _as_path_list(value: Any) -> list[Path]:
    """任意値を Path の list に変換する。

    - None → `[]`
    - str → `os.pathsep`（macOS/Linux なら `:`）区切りで分解
    - iterable → 各要素を `_as_optional_path()` で変換（空要素は捨てる）
    """

    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        parts = [p for p in s.split(os.pathsep) if p]
        return [Path(_expand_path_text(p)) for p in parts]

    try:
        seq = list(value)
    except Exception:
        return []

    out: list[Path] = []
    for item in seq:
        p = _as_optional_path(item)
        if p is not None:
            out.append(p)
    return out


def _as_mapping(value: Any, *, key: str) -> dict[str, Any]:
    """任意値を mapping として解釈し、dict に正規化して返す。"""

    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise RuntimeError(f"{key} は mapping である必要があります: got={value!r}")


def _as_int_pair(value: Any, *, key: str) -> tuple[int, int] | None:
    """任意値を (x, y) の整数ペアとして解釈して返す。"""

    if value is None:
        return None
    try:
        seq = list(value)
    except Exception as exc:
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}") from exc
    if len(seq) != 2:
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}")
    try:
        x = int(seq[0])
        y = int(seq[1])
    except Exception as exc:
        raise RuntimeError(f"{key} は [x, y] の整数配列である必要があります: got={value!r}") from exc
    return (x, y)


def _as_float_pair(value: Any, *, key: str) -> tuple[float, float] | None:
    """任意値を (x, y) の float ペアとして解釈して返す。"""

    if value is None:
        return None
    try:
        seq = list(value)
    except Exception as exc:
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}") from exc
    if len(seq) != 2:
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}")
    try:
        x = float(seq[0])
        y = float(seq[1])
    except Exception as exc:
        raise RuntimeError(f"{key} は [x, y] の数値配列である必要があります: got={value!r}") from exc
    return (float(x), float(y))


def _as_int(value: Any, *, key: str) -> int | None:
    """任意値を int として解釈して返す。"""

    if value is None:
        return None
    try:
        return int(value)
    except Exception as exc:
        raise RuntimeError(f"{key} は整数である必要があります: got={value!r}") from exc


def _as_bool(value: Any, *, key: str) -> bool | None:
    """任意値を bool として解釈して返す。"""

    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int) and int(value) in (0, 1):
        return bool(int(value))
    raise RuntimeError(f"{key} は bool である必要があります: got={value!r}")


def _as_float(value: Any, *, key: str) -> float | None:
    """任意値を float として解釈して返す。"""

    if value is None:
        return None
    try:
        return float(value)
    except Exception as exc:
        raise RuntimeError(f"{key} は数値である必要があります: got={value!r}") from exc


def _as_midi_inputs(value: Any) -> list[tuple[str, str]]:
    """midi.inputs を (port_name, mode) の list として解釈して返す。

    期待する形:
    - `[{port_name: "...", mode: "..."}, ...]`

    パース方針:
    - 不正な要素（dict でない / key が不足 / 空文字）は無視する
    - mode の妥当性チェックはこの層では行わない（上位層で解釈する前提）
    """

    if value is None:
        return []
    try:
        seq = list(value)
    except Exception:
        return []

    out: list[tuple[str, str]] = []
    for item in seq:
        if not isinstance(item, dict):
            continue
        port_name = item.get("port_name")
        mode = item.get("mode")
        if port_name is None or mode is None:
            continue
        port_s = str(port_name).strip()
        mode_s = str(mode).strip()
        if not port_s or not mode_s:
            continue
        out.append((port_s, mode_s))
    return out


def _as_float_quad(
    value: Any,
    *,
    key: str,
) -> tuple[float, float, float, float] | None:
    """任意値を 4 要素の float タプルとして解釈して返す。"""

    if value is None:
        return None
    try:
        seq = list(value)
    except Exception as exc:
        raise RuntimeError(f"{key} は [a, b, c, d] の配列である必要があります: got={value!r}") from exc
    if len(seq) != 4:
        raise RuntimeError(f"{key} は [a, b, c, d] の配列である必要があります: got={value!r}")
    try:
        a = float(seq[0])
        b = float(seq[1])
        c = float(seq[2])
        d = float(seq[3])
    except Exception as exc:
        raise RuntimeError(f"{key} は [a, b, c, d] の数値配列である必要があります: got={value!r}") from exc
    return (float(a), float(b), float(c), float(d))


def _load_yaml_text(text: str, *, source: str) -> dict[str, Any]:
    """YAML テキストを読み、トップレベル mapping を dict として返す。

    Parameters
    ----------
    text:
        YAML 本文。
    source:
        エラーメッセージ用の識別子（パス等）。

    Returns
    -------
    dict[str, Any]
        YAML のトップレベル mapping。空（`null`）なら `{}`。
    """

    try:
        import yaml  # type: ignore[import-untyped]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PyYAML を import できません: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise RuntimeError(f"config.yaml の読み込みに失敗しました: source={source}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"config.yaml は mapping である必要があります: source={source}")

    return dict(data)


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """UTF-8 の YAML ファイルを読み、dict を返す。"""

    text = path.read_text(encoding="utf-8")
    return _load_yaml_text(text, source=str(path))


def _load_packaged_default_config() -> dict[str, Any]:
    """同梱デフォルト config をロードして dict を返す。

    パッケージ配布（wheel/sdist）でも動作するように、`importlib.resources` を使って
    `grafix/resource/default_config.yaml` を読み込む。
    """

    try:
        blob = (
            resources.files("grafix")
            .joinpath("resource", "default_config.yaml")
            .read_text(encoding="utf-8")
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "同梱 default_config.yaml の読み込みに失敗しました"
            "（パッケージ配布物の package-data を確認してください）"
        ) from exc

    return _load_yaml_text(blob, source="grafix/resource/default_config.yaml")


def runtime_config() -> RuntimeConfig:
    """実行時設定をロードして返す（キャッシュ）。

    読み込み元の優先順位（後勝ち）:
    1) 同梱 `grafix/resource/default_config.yaml`
    2) 探索で見つかった `config.yaml`（任意）
    3) `set_config_path()` で明示指定された `config.yaml`（任意）

    Notes
    -----
    - 一度ロードした結果はモジュール内にキャッシュされる。
      `set_config_path()` はキャッシュを破棄するため、次回呼び出しで再ロードされる。
    - ユーザー設定の適用はトップレベルの浅い上書きである（ネストの部分マージはしない）。
    """

    global _CONFIG_CACHE
    # キャッシュがあれば即返す。設定の切り替えは `set_config_path()` で行う。
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    explicit_path = _EXPLICIT_CONFIG_PATH
    if explicit_path is not None and not explicit_path.is_file():
        raise FileNotFoundError(f"config.yaml が見つかりません: {explicit_path}")

    discovered_path: Path | None = None
    # 既定の探索は「CWD → HOME」の順。最初に見つかった 1 つのみを採用する。
    for p in _default_config_candidates():
        if p.is_file():
            discovered_path = p
            break

    # 同梱デフォルトをベースにし、ユーザー設定で上書きする。
    # `dict.update()` はトップレベルの浅い上書きなので、ネストした mapping は丸ごと置換になる。
    payload = _load_packaged_default_config()
    if discovered_path is not None:
        payload.update(_load_yaml_config(discovered_path))
    if explicit_path is not None:
        payload.update(_load_yaml_config(explicit_path))

    version = payload.get("version")
    if version is None:
        raise RuntimeError(
            "config.yaml の version が未設定です（同梱 default_config.yaml を確認してください）"
        )
    try:
        version_i = int(version)
    except Exception as exc:
        raise RuntimeError(f"config.yaml の version は整数である必要があります: got={version!r}") from exc
    if version_i != 1:
        raise RuntimeError(f"未対応の config.yaml version です: got={version_i}")

    paths = _as_mapping(payload.get("paths"), key="paths")
    output_dir = _as_optional_path(paths.get("output_dir"))
    if output_dir is None:
        raise RuntimeError(
            "paths.output_dir が未設定です（同梱 default_config.yaml を確認してください）"
        )
    sketch_dir = _as_optional_path(paths.get("sketch_dir"))
    preset_module_dirs = _as_path_list(paths.get("preset_module_dirs"))
    font_dirs = _as_path_list(paths.get("font_dirs"))

    ui = _as_mapping(payload.get("ui"), key="ui")
    window_positions = _as_mapping(ui.get("window_positions"), key="ui.window_positions")

    window_pos_draw = _as_int_pair(
        window_positions.get("draw"),
        key="ui.window_positions.draw",
    )
    if window_pos_draw is None:
        raise RuntimeError(
            "ui.window_positions.draw が未設定です（同梱 default_config.yaml を確認してください）"
        )

    window_pos_parameter_gui = _as_int_pair(
        window_positions.get("parameter_gui"),
        key="ui.window_positions.parameter_gui",
    )
    if window_pos_parameter_gui is None:
        raise RuntimeError(
            "ui.window_positions.parameter_gui が未設定です（同梱 default_config.yaml を確認してください）"
        )

    parameter_gui = _as_mapping(ui.get("parameter_gui"), key="ui.parameter_gui")
    parameter_gui_window_size = _as_int_pair(
        parameter_gui.get("window_size"),
        key="ui.parameter_gui.window_size",
    )
    if parameter_gui_window_size is None:
        raise RuntimeError(
            "ui.parameter_gui.window_size が未設定です（同梱 default_config.yaml を確認してください）"
        )

    parameter_gui_fallback_font_japanese = _as_optional_str(
        parameter_gui.get("fallback_font_japanese")
    )

    parameter_gui_font_size_base_px = _as_float(
        parameter_gui.get("font_size_base_px"),
        key="ui.parameter_gui.font_size_base_px",
    )
    if parameter_gui_font_size_base_px is None:
        parameter_gui_font_size_base_px = float(_PARAMETER_GUI_FONT_SIZE_BASE_PX_DEFAULT)
    if parameter_gui_font_size_base_px <= 0.0:
        raise ValueError(
            "ui.parameter_gui.font_size_base_px は正の値である必要があります"
            f": got={parameter_gui_font_size_base_px}"
        )

    parameter_gui_table_column_weights = _as_float_quad(
        parameter_gui.get("table_column_weights"),
        key="ui.parameter_gui.table_column_weights",
    )
    if parameter_gui_table_column_weights is None:
        parameter_gui_table_column_weights = _PARAMETER_GUI_TABLE_COLUMN_WEIGHTS_DEFAULT
    if any(float(w) <= 0.0 for w in parameter_gui_table_column_weights):
        raise ValueError(
            "ui.parameter_gui.table_column_weights は全要素が正である必要があります"
            f": got={parameter_gui_table_column_weights}"
        )

    export = _as_mapping(payload.get("export"), key="export")
    png = _as_mapping(export.get("png"), key="export.png")
    png_scale = _as_float(png.get("scale"), key="export.png.scale")
    if png_scale is None:
        raise RuntimeError(
            "export.png.scale が未設定です（同梱 default_config.yaml を確認してください）"
        )
    if png_scale <= 0:
        raise ValueError(f"export.png.scale は正の値である必要があります: got={png_scale}")

    gcode = _as_mapping(export.get("gcode"), key="export.gcode")
    required_gcode_keys = (
        "travel_feed",
        "draw_feed",
        "z_up",
        "z_down",
        "y_down",
        "origin",
        "decimals",
        "paper_margin_mm",
        "bed_x_range",
        "bed_y_range",
        "bridge_draw_distance",
        "optimize_travel",
        "allow_reverse",
        "canvas_height_mm",
    )
    missing_gcode_keys = [k for k in required_gcode_keys if k not in gcode]
    if missing_gcode_keys:
        raise RuntimeError(
            "export.gcode が未設定、または必須キーが不足しています"
            "（config.yaml はトップレベル浅い上書きのため、export: を上書きする場合は"
            " 同梱 default_config.yaml をコピーして export.gcode も含めてください）"
            f": missing={missing_gcode_keys}"
        )

    travel_feed = _as_float(gcode.get("travel_feed"), key="export.gcode.travel_feed")
    if travel_feed is None:
        raise RuntimeError(
            "export.gcode.travel_feed が未設定です（同梱 default_config.yaml を確認してください）"
        )
    draw_feed = _as_float(gcode.get("draw_feed"), key="export.gcode.draw_feed")
    if draw_feed is None:
        raise RuntimeError(
            "export.gcode.draw_feed が未設定です（同梱 default_config.yaml を確認してください）"
        )

    z_up = _as_float(gcode.get("z_up"), key="export.gcode.z_up")
    if z_up is None:
        raise RuntimeError(
            "export.gcode.z_up が未設定です（同梱 default_config.yaml を確認してください）"
        )
    z_down = _as_float(gcode.get("z_down"), key="export.gcode.z_down")
    if z_down is None:
        raise RuntimeError(
            "export.gcode.z_down が未設定です（同梱 default_config.yaml を確認してください）"
        )

    y_down = _as_bool(gcode.get("y_down"), key="export.gcode.y_down")
    if y_down is None:
        raise RuntimeError(
            "export.gcode.y_down が未設定です（同梱 default_config.yaml を確認してください）"
        )

    origin = _as_float_pair(gcode.get("origin"), key="export.gcode.origin")
    if origin is None:
        raise RuntimeError(
            "export.gcode.origin が未設定です（同梱 default_config.yaml を確認してください）"
        )

    decimals = _as_int(gcode.get("decimals"), key="export.gcode.decimals")
    if decimals is None:
        raise RuntimeError(
            "export.gcode.decimals が未設定です（同梱 default_config.yaml を確認してください）"
        )
    if int(decimals) < 0:
        raise ValueError(f"export.gcode.decimals は 0 以上である必要があります: got={decimals}")

    paper_margin_mm = _as_float(gcode.get("paper_margin_mm"), key="export.gcode.paper_margin_mm")
    if paper_margin_mm is None:
        raise RuntimeError(
            "export.gcode.paper_margin_mm が未設定です（同梱 default_config.yaml を確認してください）"
        )
    if float(paper_margin_mm) < 0.0:
        raise ValueError(
            "export.gcode.paper_margin_mm は 0 以上である必要があります"
            f": got={paper_margin_mm}"
        )

    bed_x_range = _as_float_pair(gcode.get("bed_x_range"), key="export.gcode.bed_x_range")
    bed_y_range = _as_float_pair(gcode.get("bed_y_range"), key="export.gcode.bed_y_range")

    bridge_draw_distance = _as_float(
        gcode.get("bridge_draw_distance"),
        key="export.gcode.bridge_draw_distance",
    )
    if bridge_draw_distance is not None and float(bridge_draw_distance) < 0.0:
        raise ValueError(
            "export.gcode.bridge_draw_distance は 0 以上である必要があります"
            f": got={bridge_draw_distance}"
        )

    optimize_travel = _as_bool(
        gcode.get("optimize_travel"),
        key="export.gcode.optimize_travel",
    )
    if optimize_travel is None:
        raise RuntimeError(
            "export.gcode.optimize_travel が未設定です（同梱 default_config.yaml を確認してください）"
        )

    allow_reverse = _as_bool(
        gcode.get("allow_reverse"),
        key="export.gcode.allow_reverse",
    )
    if allow_reverse is None:
        raise RuntimeError(
            "export.gcode.allow_reverse が未設定です（同梱 default_config.yaml を確認してください）"
        )

    canvas_height_mm = _as_float(
        gcode.get("canvas_height_mm"),
        key="export.gcode.canvas_height_mm",
    )

    gcode_cfg = GCodeExportConfig(
        travel_feed=float(travel_feed),
        draw_feed=float(draw_feed),
        z_up=float(z_up),
        z_down=float(z_down),
        y_down=bool(y_down),
        origin=(float(origin[0]), float(origin[1])),
        decimals=int(decimals),
        paper_margin_mm=float(paper_margin_mm),
        bed_x_range=bed_x_range,
        bed_y_range=bed_y_range,
        bridge_draw_distance=bridge_draw_distance,
        optimize_travel=bool(optimize_travel),
        allow_reverse=bool(allow_reverse),
        canvas_height_mm=canvas_height_mm,
    )

    midi = _as_mapping(payload.get("midi"), key="midi")
    midi_inputs = _as_midi_inputs(midi.get("inputs"))

    cfg = RuntimeConfig(
        # config_path は「ユーザー設定の出典」を記録する用途（同梱デフォルトにはパスが無い）。
        config_path=explicit_path or discovered_path,
        output_dir=output_dir,
        sketch_dir=sketch_dir,
        preset_module_dirs=tuple(preset_module_dirs),
        font_dirs=tuple(font_dirs),
        window_pos_draw=window_pos_draw,
        window_pos_parameter_gui=window_pos_parameter_gui,
        parameter_gui_window_size=parameter_gui_window_size,
        parameter_gui_fallback_font_japanese=parameter_gui_fallback_font_japanese,
        parameter_gui_font_size_base_px=float(parameter_gui_font_size_base_px),
        parameter_gui_table_column_weights=parameter_gui_table_column_weights,
        png_scale=float(png_scale),
        gcode=gcode_cfg,
        midi_inputs=tuple(midi_inputs),
    )
    _CONFIG_CACHE = cfg
    return cfg


def output_root_dir() -> Path:
    """出力ファイルを保存する既定ルートディレクトリを返す。

    実体は `runtime_config().output_dir` の薄いショートカット。
    探索/上書きルールは `runtime_config()` を参照。
    """

    cfg = runtime_config()
    return Path(cfg.output_dir)


__all__ = [
    "GCodeExportConfig",
    "RuntimeConfig",
    "output_root_dir",
    "runtime_config",
    "set_config_path",
]
