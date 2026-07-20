# どこで: `src/grafix/core/runtime_config.py`。
# 何を: config.yaml による実行時設定（探索・ロード・キャッシュ）を提供する。
# なぜ: PyPI 環境でも、外部リソースや出力先をユーザーが指定できるようにするため。

"""実行時設定（`config.yaml`）の探索・ロード・キャッシュを担当する。

このモジュールは、以下を提供する:

- `config.yaml` を「同梱デフォルト → ユーザー設定（任意）」の順に適用して `RuntimeConfig` を構築
- 探索パス（CWD / HOME）と、明示指定（`set_config_path()`）の両方に対応
- merge 前の unknown key 検証と、値・range・MIDI mode の strict validation
- ユーザー config 内の相対 path を config file の親基準に解決
- 1 回ロードした結果をプロセス内でキャッシュ（設定を切り替える場合は `set_config_path()` で破棄）

入出力 / 副作用
----------------
- 入力: 同梱 `grafix/resource/default_config.yaml`、任意でユーザーの `config.yaml`
- 出力: `RuntimeConfig`（不変データ）
- 副作用: ファイル読み取り、YAML パース、モジュールグローバルへのキャッシュ保存

実装メモ
--------
- ユーザー設定は mapping を再帰的にマージし、指定された leaf だけを上書きする。
"""

from __future__ import annotations

import difflib
import math
import os
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from numbers import Real
from pathlib import Path
from typing import Any

from grafix.core.gcode_params import GCodeParams


# parameter_gui の設定が省略された場合のフォールバック値。
_PARAMETER_GUI_FONT_SIZE_BASE_PX_DEFAULT = 14.0
_PARAMETER_GUI_SHORTCUT_ACTIONS = (
    "play_pause",
    "reset_time",
    "step_backward",
    "step_forward",
    "slower",
    "faster",
    "range_shift",
    "range_min",
    "range_max",
    "cancel",
    "undo",
    "redo",
)
_PACKAGED_CONFIG_SOURCE = "grafix/resource/default_config.yaml"
_MIDI_MODES = ("7bit", "14bit")
_PATH_KEYS = frozenset(
    {
        "paths.output_dir",
        "paths.sketch_dir",
        "paths.preset_module_dirs",
        "paths.font_dirs",
    }
)
_PATH_LIST_KEYS = frozenset({"paths.preset_module_dirs", "paths.font_dirs"})


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
    parameter_gui_shortcuts: tuple[tuple[str, str], ...]
    png_scale: float
    gcode: GCodeParams
    midi_inputs: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RuntimeConfigValue:
    """1 つの effective config leaf と出典・path 解決結果。"""

    key: str
    source: str
    effective_value: object
    is_path: bool
    resolved_path: Path | tuple[Path, ...] | None


@dataclass(frozen=True, slots=True)
class RuntimeConfigReport:
    """strict validation 後の config と leaf ごとの provenance。"""

    config: RuntimeConfig
    active_source: str
    values: tuple[RuntimeConfigValue, ...]


@dataclass(frozen=True, slots=True)
class RuntimeConfigFallback:
    """user config失敗後にpackaged defaultへ退避した事実。"""

    summary: str
    details: str
    source: Path | None


@dataclass(frozen=True, slots=True)
class _PathsSection:
    output_dir: Path
    sketch_dir: Path | None
    preset_module_dirs: tuple[Path, ...]
    font_dirs: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _UiSection:
    window_pos_draw: tuple[int, int]
    window_pos_parameter_gui: tuple[int, int]
    parameter_gui_window_size: tuple[int, int]
    parameter_gui_fallback_font_japanese: str | None
    parameter_gui_font_size_base_px: float
    parameter_gui_shortcuts: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _ExportSection:
    png_scale: float
    gcode: GCodeParams


# `set_config_path()` で指定される「明示 config」のパス。
# ここが設定されている場合、探索で見つかった config よりも後に適用される。
_EXPLICIT_CONFIG_PATH: Path | None = None
# `runtime_config()` のプロセス内キャッシュ。設定を切り替える場合は破棄する。
_CONFIG_CACHE: RuntimeConfig | None = None
_CONFIG_REPORT_CACHE: RuntimeConfigReport | None = None


def set_config_path(path: str | Path | None) -> None:
    """以降の設定探索で使う明示 config パスを設定する。

    Parameters
    ----------
    path:
        `config.yaml` のパス。None の場合は明示指定を解除する。

    Notes
    -----
    - `path` を None にすると明示指定を解除し、既定の探索に戻る。
    - `path` は `~` を展開し、呼び出し時の CWD で絶対化して保持する。
    - 設定が変わるため、`runtime_config()` のキャッシュを破棄する。
    """

    global _EXPLICIT_CONFIG_PATH, _CONFIG_CACHE, _CONFIG_REPORT_CACHE
    if path is None:
        _EXPLICIT_CONFIG_PATH = None
        _CONFIG_CACHE = None
        _CONFIG_REPORT_CACHE = None
        return
    if type(path) is str:
        p = Path(path)
    elif isinstance(path, Path):
        p = path
    else:
        raise TypeError("config path は str、Path、None のいずれかである必要があります")
    p = p.expanduser().resolve(strict=False)
    _EXPLICIT_CONFIG_PATH = p
    _CONFIG_CACHE = None
    _CONFIG_REPORT_CACHE = None


@contextmanager
def runtime_config_scope(path: str | Path | None) -> Iterator[RuntimeConfig]:
    """明示 config と cache を scope 内だけ切り替える。

    ``RenderSession`` のように評価期間全体で同じ effective config を使う呼び出し元向けの
    process-global scope である。終了時は呼び出し前の明示 path と cache/report をそのまま
    復元する。並列 session の調停は行わず、通常の context manager と同じ LIFO で使う。

    Parameters
    ----------
    path:
        scope 内で使う明示 config path。None は明示指定を解除した探索モード。

    Yields
    ------
    RuntimeConfig
        scope 開始時に一度だけロードし、その期間中 cache に固定する effective config。
    """

    global _EXPLICIT_CONFIG_PATH, _CONFIG_CACHE, _CONFIG_REPORT_CACHE
    previous = (_EXPLICIT_CONFIG_PATH, _CONFIG_CACHE, _CONFIG_REPORT_CACHE)
    try:
        set_config_path(path)
        yield runtime_config()
    finally:
        _EXPLICIT_CONFIG_PATH, _CONFIG_CACHE, _CONFIG_REPORT_CACHE = previous


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

    if type(text) is not str:
        raise TypeError("path text は str である必要があります")
    return os.path.expandvars(os.path.expanduser(text))


def _as_optional_path(value: Any) -> Path | None:
    """None または path 文字列を Path へ変換する。"""

    if value is None:
        return None
    if type(value) is not str:
        raise RuntimeError(f"path は文字列または None である必要があります: got={value!r}")
    s = value.strip()
    if not s:
        return None
    return Path(_expand_path_text(s))


def _as_optional_str(value: Any) -> str | None:
    """None または文字列を、空なら None として返す。"""

    if value is None:
        return None
    if type(value) is not str:
        raise RuntimeError(f"値は文字列または None である必要があります: got={value!r}")
    s = value.strip()
    return None if not s else s


def _as_path_list(value: Any) -> list[Path]:
    """path 文字列だけを含む list を Path 列へ変換する。"""

    if not isinstance(value, list):
        raise RuntimeError(f"path list は文字列の配列である必要があります: got={value!r}")
    out: list[Path] = []
    for index, item in enumerate(value):
        p = _as_optional_path(item)
        if p is None:
            raise RuntimeError(f"path list[{index}] は空でない文字列である必要があります")
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
    if not isinstance(value, list):
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}")
    seq = value
    if len(seq) != 2:
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}")
    x = _as_int(seq[0], key=f"{key}[0]")
    y = _as_int(seq[1], key=f"{key}[1]")
    if x is None or y is None:
        raise RuntimeError(f"{key} は [x, y] の整数配列である必要があります: got={value!r}")
    return (x, y)


def _as_float_pair(value: Any, *, key: str) -> tuple[float, float] | None:
    """任意値を (x, y) の float ペアとして解釈して返す。"""

    if value is None:
        return None
    if not isinstance(value, list):
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}")
    seq = value
    if len(seq) != 2:
        raise RuntimeError(f"{key} は [x, y] の配列である必要があります: got={value!r}")
    x = _as_float(seq[0], key=f"{key}[0]")
    y = _as_float(seq[1], key=f"{key}[1]")
    if x is None or y is None:
        raise RuntimeError(f"{key} は [x, y] の数値配列である必要があります: got={value!r}")
    return (x, y)


def _as_int(value: Any, *, key: str) -> int | None:
    """bool や他型を変換せず int を返す。"""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{key} は整数である必要があります: got={value!r}")
    return value


def _as_bool(value: Any, *, key: str) -> bool | None:
    """暗黙 truthiness 変換を行わず bool を返す。"""

    if value is None:
        return None
    if type(value) is not bool:
        raise RuntimeError(f"{key} は bool である必要があります: got={value!r}")
    return value


def _as_float(value: Any, *, key: str) -> float | None:
    """bool/文字列を変換せず有限実数を float で返す。"""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RuntimeError(f"{key} は数値である必要があります: got={value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} は finite な数値である必要があります: got={value!r}")
    return number


def _as_midi_inputs(value: Any) -> list[tuple[str, str]]:
    """midi.inputs を (port_name, mode) の list として解釈して返す。

    期待する形:
    - `[{port_name: "...", mode: "..."}, ...]`

    不正な要素は無視せず、index を含むエラーとして報告する。
    """

    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"midi.inputs は mapping の配列である必要があります: got={value!r}")

    out: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RuntimeError(f"midi.inputs[{index}] は mapping である必要があります")
        port_name = item.get("port_name")
        mode = item.get("mode")
        if port_name is None or mode is None:
            raise RuntimeError(
                f"midi.inputs[{index}] に port_name と mode が必要です"
            )
        if not isinstance(port_name, str) or not isinstance(mode, str):
            raise RuntimeError(
                f"midi.inputs[{index}].port_name/mode は文字列である必要があります"
            )
        port_s = port_name.strip()
        mode_s = mode.strip()
        if not port_s or not mode_s:
            raise RuntimeError(
                f"midi.inputs[{index}].port_name/mode に空文字は使えません"
            )
        if mode_s not in _MIDI_MODES:
            raise ValueError(
                f"midi.inputs[{index}].mode は {_MIDI_MODES} のいずれかである必要があります"
                f": got={mode_s!r}"
            )
        out.append((port_s, mode_s))
    return out


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
            .joinpath("resource")
            .joinpath("default_config.yaml")
            .read_text(encoding="utf-8")
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "同梱 default_config.yaml の読み込みに失敗しました"
            "（パッケージ配布物の package-data を確認してください）"
        ) from exc

    return _load_yaml_text(blob, source="grafix/resource/default_config.yaml")


def _unknown_key_message(
    *,
    key: object,
    parent: tuple[str, ...],
    known_keys: tuple[str, ...],
    source: str,
) -> str:
    """unknown key と同じ階層の近似候補を含むエラー文を作る。"""

    key_s = str(key)
    full_key = ".".join((*parent, key_s))
    matches = difflib.get_close_matches(key_s, known_keys, n=1, cutoff=0.55)
    suggestion = ""
    if matches:
        suggested_key = ".".join((*parent, matches[0]))
        suggestion = f"; 候補: {suggested_key!r}"
    return f"未定義の config key: {full_key!r} (source={source}){suggestion}"


def _validate_midi_item_keys(value: Any, *, source: str) -> None:
    """``midi.inputs`` の item key を merge 前に検証する。"""

    if not isinstance(value, list):
        return
    known_keys = ("port_name", "mode")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        for key in item:
            if key not in known_keys:
                raise RuntimeError(
                    _unknown_key_message(
                        key=key,
                        parent=("midi", "inputs", str(index)),
                        known_keys=known_keys,
                        source=source,
                    )
                )


def _validate_known_key_tree(
    payload: dict[str, Any],
    *,
    schema: dict[str, Any],
    source: str,
    parent: tuple[str, ...] = (),
) -> None:
    """override の key が packaged default の既知 tree 内にあるか検証する。"""

    known_keys = tuple(str(key) for key in schema)
    for key, value in payload.items():
        if key not in schema:
            raise RuntimeError(
                _unknown_key_message(
                    key=key,
                    parent=parent,
                    known_keys=known_keys,
                    source=source,
                )
            )

        key_s = str(key)
        path = (*parent, key_s)
        schema_value = schema[key]
        if isinstance(value, dict) and isinstance(schema_value, dict):
            _validate_known_key_tree(
                value,
                schema=schema_value,
                source=source,
                parent=path,
            )
        elif path == ("midi", "inputs"):
            _validate_midi_item_keys(value, source=source)


def _resolve_path_text(value: Any, *, base_dir: Path, key: str) -> str | None:
    """config path 文字列を ``base_dir`` 基準の絶対 path にする。"""

    if value is None:
        return None
    if type(value) is not str:
        raise RuntimeError(f"{key} は path 文字列である必要があります: got={value!r}")
    text = value.strip()
    if not text:
        return ""
    path = Path(_expand_path_text(text))
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve(strict=False))


def _resolve_path_list(value: Any, *, base_dir: Path, key: str) -> list[str]:
    """config path 配列を ``base_dir`` 基準の絶対 path 配列にする。"""

    if not isinstance(value, list):
        raise RuntimeError(f"{key} は path 文字列の配列である必要があります: got={value!r}")

    resolved: list[str] = []
    for index, item in enumerate(value):
        path = _resolve_path_text(item, base_dir=base_dir, key=f"{key}[{index}]")
        if not path:
            raise RuntimeError(f"{key}[{index}] は空でない path 文字列である必要があります")
        resolved.append(path)
    return resolved


def _resolve_layer_paths(
    payload: dict[str, Any],
    *,
    base_dir: Path,
    parent: tuple[str, ...] = (),
) -> dict[str, Any]:
    """1 config file に含まれる path leaf だけを絶対化する。"""

    resolved: dict[str, Any] = {}
    for key, value in payload.items():
        path = (*parent, str(key))
        dotted = ".".join(path)
        if dotted in _PATH_LIST_KEYS:
            resolved[key] = _resolve_path_list(value, base_dir=base_dir, key=dotted)
        elif dotted in _PATH_KEYS:
            resolved[key] = _resolve_path_text(value, base_dir=base_dir, key=dotted)
        elif isinstance(value, dict):
            resolved[key] = _resolve_layer_paths(value, base_dir=base_dir, parent=path)
        else:
            resolved[key] = value
    return resolved


def _flatten_config_leaves(
    payload: dict[str, Any],
    *,
    parent: tuple[str, ...] = (),
) -> dict[str, Any]:
    """nested config mapping を dotted leaf mapping にする。"""

    leaves: dict[str, Any] = {}
    for key, value in payload.items():
        path = (*parent, str(key))
        if isinstance(value, dict):
            leaves.update(_flatten_config_leaves(value, parent=path))
        else:
            leaves[".".join(path)] = value
    return leaves


def _freeze_report_value(value: Any) -> object:
    """report が mutable YAML 値を保持しないようにする。"""

    if isinstance(value, dict):
        return tuple((str(key), _freeze_report_value(item)) for key, item in value.items())
    if isinstance(value, list):
        return tuple(_freeze_report_value(item) for item in value)
    return value


def _resolved_report_path(
    *,
    key: str,
    value: Any,
    base_dir: Path,
) -> Path | tuple[Path, ...] | None:
    """raw effective path を show 用に絶対化する。"""

    if key in _PATH_LIST_KEYS:
        return tuple(Path(path) for path in _resolve_path_list(value, base_dir=base_dir, key=key))
    resolved = _resolve_path_text(value, base_dir=base_dir, key=key)
    return None if not resolved else Path(resolved)


def _merge_mappings(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """``override`` で指定された leaf だけを再帰的に上書きする。"""

    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_mappings(current, value)
        else:
            merged[key] = value
    return merged


def _validate_version(payload: dict[str, Any]) -> None:
    """設定 schema version を検証する。"""

    version = payload.get("version")
    if version is None:
        raise RuntimeError(
            "config.yaml の version が未設定です（同梱 default_config.yaml を確認してください）"
        )
    version_i = _as_int(version, key="config.yaml.version")
    assert version_i is not None
    if version_i != 1:
        raise RuntimeError(f"未対応の config.yaml version です: got={version_i}")


def _parse_paths_section(payload: dict[str, Any]) -> _PathsSection:
    """``paths`` section を検証して返す。"""

    paths = _as_mapping(payload.get("paths"), key="paths")
    output_dir = _as_optional_path(paths.get("output_dir"))
    if output_dir is None:
        raise RuntimeError(
            "paths.output_dir が未設定です（同梱 default_config.yaml を確認してください）"
        )
    return _PathsSection(
        output_dir=output_dir,
        sketch_dir=_as_optional_path(paths.get("sketch_dir")),
        preset_module_dirs=tuple(_as_path_list(paths.get("preset_module_dirs"))),
        font_dirs=tuple(_as_path_list(paths.get("font_dirs"))),
    )


def _parse_ui_section(payload: dict[str, Any]) -> _UiSection:
    """``ui`` section を検証して返す。"""

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
            "ui.window_positions.parameter_gui が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )

    parameter_gui = _as_mapping(ui.get("parameter_gui"), key="ui.parameter_gui")
    window_size = _as_int_pair(
        parameter_gui.get("window_size"),
        key="ui.parameter_gui.window_size",
    )
    if window_size is None:
        raise RuntimeError(
            "ui.parameter_gui.window_size が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )
    if window_size[0] <= 0 or window_size[1] <= 0:
        raise ValueError(
            "ui.parameter_gui.window_size は正の整数ペアである必要があります"
            f": got={window_size}"
        )

    font_size = _as_float(
        parameter_gui.get("font_size_base_px"),
        key="ui.parameter_gui.font_size_base_px",
    )
    if font_size is None:
        font_size = float(_PARAMETER_GUI_FONT_SIZE_BASE_PX_DEFAULT)
    if font_size <= 0.0:
        raise ValueError(
            "ui.parameter_gui.font_size_base_px は正の値である必要があります"
            f": got={font_size}"
        )

    shortcut_values = _as_mapping(
        parameter_gui.get("shortcuts"),
        key="ui.parameter_gui.shortcuts",
    )
    shortcuts: list[tuple[str, str]] = []
    for action in _PARAMETER_GUI_SHORTCUT_ACTIONS:
        raw_key_name = shortcut_values.get(action)
        if type(raw_key_name) is not str:
            raise ValueError(
                f"ui.parameter_gui.shortcuts.{action} はpyglet key名である必要があります"
            )
        key_name = raw_key_name.strip().upper()
        if not key_name or not key_name.replace("_", "").isalnum():
            raise ValueError(
                f"ui.parameter_gui.shortcuts.{action} はpyglet key名である必要があります"
            )
        shortcuts.append((action, key_name))

    return _UiSection(
        window_pos_draw=window_pos_draw,
        window_pos_parameter_gui=window_pos_parameter_gui,
        parameter_gui_window_size=window_size,
        parameter_gui_fallback_font_japanese=_as_optional_str(
            parameter_gui.get("fallback_font_japanese")
        ),
        parameter_gui_font_size_base_px=float(font_size),
        parameter_gui_shortcuts=tuple(shortcuts),
    )


def _parse_gcode_section(gcode: dict[str, Any]) -> GCodeParams:
    """``export.gcode`` section を検証して返す。"""

    required_keys = (
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
    missing_keys = [key for key in required_keys if key not in gcode]
    if missing_keys:
        raise RuntimeError(
            "export.gcode が未設定、または必須キーが不足しています"
            "（再帰 merge 後の config.yaml を確認してください）"
            f": missing={missing_keys}"
        )

    travel_feed = _as_float(gcode.get("travel_feed"), key="export.gcode.travel_feed")
    if travel_feed is None:
        raise RuntimeError(
            "export.gcode.travel_feed が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )
    draw_feed = _as_float(gcode.get("draw_feed"), key="export.gcode.draw_feed")
    if draw_feed is None:
        raise RuntimeError(
            "export.gcode.draw_feed が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )
    if travel_feed <= 0.0:
        raise ValueError(
            "export.gcode.travel_feed は正の値である必要があります"
            f": got={travel_feed}"
        )
    if draw_feed <= 0.0:
        raise ValueError(
            "export.gcode.draw_feed は正の値である必要があります"
            f": got={draw_feed}"
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
    if decimals < 0:
        raise ValueError(f"export.gcode.decimals は 0 以上である必要があります: got={decimals}")

    paper_margin_mm = _as_float(
        gcode.get("paper_margin_mm"),
        key="export.gcode.paper_margin_mm",
    )
    if paper_margin_mm is None:
        raise RuntimeError(
            "export.gcode.paper_margin_mm が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )
    if paper_margin_mm < 0.0:
        raise ValueError(
            "export.gcode.paper_margin_mm は 0 以上である必要があります"
            f": got={paper_margin_mm}"
        )

    bridge_draw_distance = _as_float(
        gcode.get("bridge_draw_distance"),
        key="export.gcode.bridge_draw_distance",
    )
    if bridge_draw_distance is not None and bridge_draw_distance < 0.0:
        raise ValueError(
            "export.gcode.bridge_draw_distance は 0 以上である必要があります"
            f": got={bridge_draw_distance}"
        )

    bed_x_range = _as_float_pair(
        gcode.get("bed_x_range"),
        key="export.gcode.bed_x_range",
    )
    if bed_x_range is not None and bed_x_range[0] >= bed_x_range[1]:
        raise ValueError(
            "export.gcode.bed_x_range は [min, max] の昇順である必要があります"
            f": got={bed_x_range}"
        )
    bed_y_range = _as_float_pair(
        gcode.get("bed_y_range"),
        key="export.gcode.bed_y_range",
    )
    if bed_y_range is not None and bed_y_range[0] >= bed_y_range[1]:
        raise ValueError(
            "export.gcode.bed_y_range は [min, max] の昇順である必要があります"
            f": got={bed_y_range}"
        )

    canvas_height_mm = _as_float(
        gcode.get("canvas_height_mm"),
        key="export.gcode.canvas_height_mm",
    )
    if canvas_height_mm is not None and canvas_height_mm <= 0.0:
        raise ValueError(
            "export.gcode.canvas_height_mm は正の値である必要があります"
            f": got={canvas_height_mm}"
        )

    optimize_travel = _as_bool(
        gcode.get("optimize_travel"),
        key="export.gcode.optimize_travel",
    )
    if optimize_travel is None:
        raise RuntimeError(
            "export.gcode.optimize_travel が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )
    allow_reverse = _as_bool(
        gcode.get("allow_reverse"),
        key="export.gcode.allow_reverse",
    )
    if allow_reverse is None:
        raise RuntimeError(
            "export.gcode.allow_reverse が未設定です"
            "（同梱 default_config.yaml を確認してください）"
        )

    return GCodeParams(
        travel_feed=travel_feed,
        draw_feed=draw_feed,
        z_up=z_up,
        z_down=z_down,
        y_down=y_down,
        origin=origin,
        decimals=decimals,
        paper_margin_mm=paper_margin_mm,
        bed_x_range=bed_x_range,
        bed_y_range=bed_y_range,
        bridge_draw_distance=bridge_draw_distance,
        optimize_travel=optimize_travel,
        allow_reverse=allow_reverse,
        canvas_height_mm=canvas_height_mm,
    )


def _parse_export_section(payload: dict[str, Any]) -> _ExportSection:
    """``export`` section を検証して返す。"""

    export = _as_mapping(payload.get("export"), key="export")
    png = _as_mapping(export.get("png"), key="export.png")
    png_scale = _as_float(png.get("scale"), key="export.png.scale")
    if png_scale is None:
        raise RuntimeError(
            "export.png.scale が未設定です（同梱 default_config.yaml を確認してください）"
        )
    if png_scale <= 0.0:
        raise ValueError(f"export.png.scale は正の値である必要があります: got={png_scale}")

    gcode = _as_mapping(export.get("gcode"), key="export.gcode")
    return _ExportSection(
        png_scale=float(png_scale),
        gcode=_parse_gcode_section(gcode),
    )


def _parse_midi_section(payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """``midi`` section を検証して入力設定を返す。"""

    midi = _as_mapping(payload.get("midi"), key="midi")
    return tuple(_as_midi_inputs(midi.get("inputs")))


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
    - ユーザー設定は mapping を再帰的にマージし、未指定の同梱既定値を維持する。
    - ユーザー設定の key tree は merge 前に検証され、unknown key は近似候補とともに拒否される。
    """

    global _CONFIG_CACHE, _CONFIG_REPORT_CACHE
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

    # 各 layer を merge する前に key tree を検証し、user config 内の path は
    # その config file の親を基準に絶対化する。packaged default は従来どおり
    # project CWD 相対を維持する。
    packaged_payload = _load_packaged_default_config()
    layers: list[tuple[dict[str, Any], str, Path, bool]] = [
        (packaged_payload, _PACKAGED_CONFIG_SOURCE, Path.cwd().resolve(), False)
    ]
    if discovered_path is not None:
        discovered_payload = _load_yaml_config(discovered_path)
        discovered_source = str(discovered_path.resolve(strict=False))
        _validate_known_key_tree(
            discovered_payload,
            schema=packaged_payload,
            source=discovered_source,
        )
        layers.append(
            (
                discovered_payload,
                discovered_source,
                discovered_path.resolve(strict=False).parent,
                True,
            )
        )
    if explicit_path is not None:
        explicit_payload = _load_yaml_config(explicit_path)
        explicit_source = str(explicit_path.resolve(strict=False))
        _validate_known_key_tree(
            explicit_payload,
            schema=packaged_payload,
            source=explicit_source,
        )
        layers.append(
            (
                explicit_payload,
                explicit_source,
                explicit_path.resolve(strict=False).parent,
                True,
            )
        )

    raw_effective: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    source_by_key: dict[str, str] = {}
    base_dir_by_key: dict[str, Path] = {}
    for layer, source, base_dir, resolve_paths in layers:
        raw_effective = _merge_mappings(raw_effective, layer)
        runtime_layer = (
            _resolve_layer_paths(layer, base_dir=base_dir) if resolve_paths else layer
        )
        payload = _merge_mappings(payload, runtime_layer)
        for key in _flatten_config_leaves(layer):
            source_by_key[key] = source
            base_dir_by_key[key] = base_dir

    _validate_version(payload)
    paths = _parse_paths_section(payload)
    ui = _parse_ui_section(payload)
    export = _parse_export_section(payload)
    midi_inputs = _parse_midi_section(payload)

    cfg = RuntimeConfig(
        # config_path は「ユーザー設定の出典」を記録する用途（同梱デフォルトにはパスが無い）。
        config_path=explicit_path or discovered_path,
        output_dir=paths.output_dir,
        sketch_dir=paths.sketch_dir,
        preset_module_dirs=paths.preset_module_dirs,
        font_dirs=paths.font_dirs,
        window_pos_draw=ui.window_pos_draw,
        window_pos_parameter_gui=ui.window_pos_parameter_gui,
        parameter_gui_window_size=ui.parameter_gui_window_size,
        parameter_gui_fallback_font_japanese=ui.parameter_gui_fallback_font_japanese,
        parameter_gui_font_size_base_px=ui.parameter_gui_font_size_base_px,
        parameter_gui_shortcuts=ui.parameter_gui_shortcuts,
        png_scale=export.png_scale,
        gcode=export.gcode,
        midi_inputs=midi_inputs,
    )
    raw_leaves = _flatten_config_leaves(raw_effective)
    report_values: list[RuntimeConfigValue] = []
    for key in sorted(raw_leaves):
        is_path = key in _PATH_KEYS
        resolved_path = None
        if is_path:
            resolved_path = _resolved_report_path(
                key=key,
                value=raw_leaves[key],
                base_dir=base_dir_by_key[key],
            )
        report_values.append(
            RuntimeConfigValue(
                key=key,
                source=source_by_key[key],
                effective_value=_freeze_report_value(raw_leaves[key]),
                is_path=is_path,
                resolved_path=resolved_path,
            )
        )

    _CONFIG_CACHE = cfg
    _CONFIG_REPORT_CACHE = RuntimeConfigReport(
        config=cfg,
        active_source=str(cfg.config_path) if cfg.config_path is not None else _PACKAGED_CONFIG_SOURCE,
        values=tuple(report_values),
    )
    return cfg


def runtime_config_report() -> RuntimeConfigReport:
    """strict validation 後の config と leaf ごとの出典を返す（キャッシュ）。"""

    if _CONFIG_REPORT_CACHE is None:
        runtime_config()
    assert _CONFIG_REPORT_CACHE is not None
    return _CONFIG_REPORT_CACHE


def _packaged_runtime_config_report() -> RuntimeConfigReport:
    """user layerを読まず、同梱defaultだけからstrict configを構築する。"""

    payload = _load_packaged_default_config()
    _validate_version(payload)
    paths = _parse_paths_section(payload)
    ui = _parse_ui_section(payload)
    export = _parse_export_section(payload)
    midi_inputs = _parse_midi_section(payload)
    cfg = RuntimeConfig(
        config_path=None,
        output_dir=paths.output_dir,
        sketch_dir=paths.sketch_dir,
        preset_module_dirs=paths.preset_module_dirs,
        font_dirs=paths.font_dirs,
        window_pos_draw=ui.window_pos_draw,
        window_pos_parameter_gui=ui.window_pos_parameter_gui,
        parameter_gui_window_size=ui.parameter_gui_window_size,
        parameter_gui_fallback_font_japanese=ui.parameter_gui_fallback_font_japanese,
        parameter_gui_font_size_base_px=ui.parameter_gui_font_size_base_px,
        parameter_gui_shortcuts=ui.parameter_gui_shortcuts,
        png_scale=export.png_scale,
        gcode=export.gcode,
        midi_inputs=midi_inputs,
    )
    values: list[RuntimeConfigValue] = []
    base_dir = Path.cwd().resolve()
    for key, value in sorted(_flatten_config_leaves(payload).items()):
        is_path = key in _PATH_KEYS
        values.append(
            RuntimeConfigValue(
                key=key,
                source=_PACKAGED_CONFIG_SOURCE,
                effective_value=_freeze_report_value(value),
                is_path=is_path,
                resolved_path=(
                    _resolved_report_path(key=key, value=value, base_dir=base_dir)
                    if is_path
                    else None
                ),
            )
        )
    return RuntimeConfigReport(
        config=cfg,
        active_source=_PACKAGED_CONFIG_SOURCE,
        values=tuple(values),
    )


def runtime_config_with_fallback() -> tuple[RuntimeConfig, RuntimeConfigFallback | None]:
    """strict user configを試し、失敗時だけ通知情報付きでdefaultへ退避する。

    CLI validationは従来どおり :func:`runtime_config_report` を直接呼び、失敗を
    exit codeへ変換する。interactive runnerだけがこの明示fallbackを使用する。
    fallback後は同一session内の全consumerが同じconfigを見るようcacheへ固定する。
    """

    global _CONFIG_CACHE, _CONFIG_REPORT_CACHE
    try:
        return runtime_config(), None
    except (OSError, RuntimeError, ValueError) as exc:
        source = _EXPLICIT_CONFIG_PATH
        if source is None:
            source = next(
                (path for path in _default_config_candidates() if path.is_file()),
                None,
            )
        report = _packaged_runtime_config_report()
        _CONFIG_CACHE = report.config
        _CONFIG_REPORT_CACHE = report
        return report.config, RuntimeConfigFallback(
            summary=f"{type(exc).__name__}: {exc}",
            details="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            source=None if source is None else source.resolve(strict=False),
        )


def output_root_dir() -> Path:
    """出力ファイルを保存する既定ルートディレクトリを返す。

    実体は `runtime_config().output_dir` の薄いショートカット。
    探索/上書きルールは `runtime_config()` を参照。
    """

    cfg = runtime_config()
    return Path(cfg.output_dir)


__all__ = [
    "RuntimeConfig",
    "RuntimeConfigReport",
    "RuntimeConfigFallback",
    "RuntimeConfigValue",
    "output_root_dir",
    "runtime_config",
    "runtime_config_report",
    "runtime_config_scope",
    "runtime_config_with_fallback",
    "set_config_path",
]
