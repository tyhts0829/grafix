"""
どこで: `src/grafix/core/primitives/lsystem.py`。L-system（植物/回路）プリミティブの実体生成。
何を: 文字列規則の展開（L-system）とタートル解釈で、枝ポリライン列を生成する。
なぜ: 記号的な枝分かれ線（植物/回路）を、少ないパラメータで安定して得るため。
"""

from __future__ import annotations

import math
import warnings

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import RealizedGeometry

_MAX_EXPANDED_CHARS = 500_000

_PRESETS: dict[str, tuple[str, dict[str, str]]] = {
    "plant": (
        "X",
        {
            "X": "F-[[X]+X]+F[+FX]-X",
            "F": "FF",
        },
    ),
    "circuit": (
        "X",
        {
            "X": "F[+X]F[-X]FX",
            "F": "FF",
        },
    ),
}

_DEFAULT_CUSTOM_AXIOM = "X"
_DEFAULT_CUSTOM_RULES = "X=F-[[X]+X]+F[+FX]-X\nF=FF"

lsystem_meta = {
    "kind": ParamMeta(kind="choice", choices=("plant", "circuit", "custom")),
    "iters": ParamMeta(kind="int", ui_min=0, ui_max=8),
    "center": ParamMeta(kind="vec3", ui_min=0.0, ui_max=300.0),
    "heading": ParamMeta(kind="float", ui_min=0.0, ui_max=360.0),
    "angle": ParamMeta(kind="float", ui_min=0.0, ui_max=180.0),
    "step": ParamMeta(kind="float", ui_min=0.1, ui_max=50.0),
    "jitter": ParamMeta(kind="float", ui_min=0.0, ui_max=0.25),
    "seed": ParamMeta(kind="int", ui_min=0, ui_max=9999),
    "axiom": ParamMeta(kind="str"),
    "rules": ParamMeta(kind="str"),
}

LSYSTEM_UI_VISIBLE = {
    "axiom": lambda v: str(v.get("kind", "plant")) == "custom",
    "rules": lambda v: str(v.get("kind", "plant")) == "custom",
}


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _lines_to_realized(lines: list[np.ndarray]) -> RealizedGeometry:
    if not lines:
        return _empty_geometry()
    coords = np.concatenate(lines, axis=0).astype(np.float32, copy=False)
    offsets = np.empty((len(lines) + 1,), dtype=np.int32)
    offsets[0] = 0
    acc = 0
    for i, ln in enumerate(lines):
        acc += int(ln.shape[0])
        offsets[i + 1] = acc
    return RealizedGeometry(coords=coords, offsets=offsets)


def _parse_rules_text(rules: str) -> dict[str, str]:
    """`custom` 用の rules 文字列（`A=...`）を辞書に変換する。"""
    out: dict[str, str] = {}

    for line_no, raw in enumerate(rules.splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            warnings.warn(
                f"lsystem rules の {line_no} 行目を無視しました（'=' がありません）: {raw!r}",
                UserWarning,
                stacklevel=3,
            )
            continue
        lhs, rhs = s.split("=", 1)
        lhs = lhs.strip()
        if len(lhs) != 1:
            warnings.warn(
                f"lsystem rules の {line_no} 行目を無視しました（左辺は 1 文字が必要）: {raw!r}",
                UserWarning,
                stacklevel=3,
            )
            continue
        out[lhs] = rhs
    return out


def _expand_lsystem(axiom: str, rules: dict[str, str], *, iters: int) -> str:
    """L-system を展開して最終文字列を返す。"""
    s = str(axiom)
    n = int(iters)
    if n <= 0:
        return s

    for _ in range(n):
        parts: list[str] = []
        for ch in s:
            parts.append(rules.get(ch, ch))
        s = "".join(parts)
        if len(s) > _MAX_EXPANDED_CHARS:
            raise ValueError(
                "lsystem の展開結果が大きすぎます（iters/rules を下げてください）"
            )
    return s


def _turtle_to_polylines(
    program: str,
    *,
    start_xy: tuple[float, float],
    heading_deg: float,
    angle_deg: float,
    step: float,
    jitter: float,
    seed: int,
    z: float,
) -> list[np.ndarray]:
    """タートル解釈で開ポリライン列（(N,3) float32 配列の list）を返す。"""
    x, y = float(start_xy[0]), float(start_xy[1])
    heading = math.radians(float(heading_deg))
    angle_base = math.radians(float(angle_deg))
    step_base = float(step)

    jitter_f = float(jitter)
    if jitter_f < 0.0:
        jitter_f = 0.0

    rng = np.random.default_rng(int(seed))

    lines_xy: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = [(x, y)]
    stack: list[tuple[float, float, float, list[tuple[float, float]]]] = []

    def finish_current() -> None:
        nonlocal current
        if len(current) >= 2:
            lines_xy.append(current)

    def jitter_scale() -> float:
        if jitter_f <= 0.0:
            return 1.0
        return 1.0 + float(rng.uniform(-jitter_f, jitter_f))

    for ch in program:
        if ch == "F" or ch == "f":
            dist = step_base * jitter_scale()
            x += dist * math.cos(heading)
            y += dist * math.sin(heading)
            if ch == "F":
                current.append((x, y))
            else:
                finish_current()
                current = [(x, y)]
            continue

        if ch == "+" or ch == "-":
            d = angle_base * jitter_scale()
            heading = heading + d if ch == "+" else heading - d
            continue

        if ch == "[":
            stack.append((x, y, heading, current))
            current = [(x, y)]
            continue

        if ch == "]":
            if not stack:
                warnings.warn(
                    "lsystem のプログラムに余分な ']' があるため無視します",
                    UserWarning,
                    stacklevel=3,
                )
                continue
            finish_current()
            x, y, heading, current = stack.pop()
            continue

        # 未知の記号（例: X）は no-op とする。

    if stack:
        warnings.warn(
            "lsystem のプログラムに閉じていない '[' があるため、残りを無視します",
            UserWarning,
            stacklevel=3,
        )

    finish_current()
    while stack:
        _x, _y, _heading, prev = stack.pop()
        if len(prev) >= 2:
            lines_xy.append(prev)

    out: list[np.ndarray] = []
    zf = float(z)
    for poly in lines_xy:
        xy = np.asarray(poly, dtype=np.float32)
        if int(xy.shape[0]) < 2:
            continue
        arr3 = np.zeros((xy.shape[0], 3), dtype=np.float32)
        arr3[:, :2] = xy
        arr3[:, 2] = zf
        out.append(arr3)
    return out


@primitive(meta=lsystem_meta, ui_visible=LSYSTEM_UI_VISIBLE)
def lsystem(
    *,
    kind: str = "plant",
    iters: int = 5,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    heading: float = 90.0,
    angle: float = 25.0,
    step: float = 6.0,
    jitter: float = 0.0,
    seed: int = 0,
    axiom: str = _DEFAULT_CUSTOM_AXIOM,
    rules: str = _DEFAULT_CUSTOM_RULES,
) -> RealizedGeometry:
    """L-system を展開し、枝分かれした線（開ポリライン列）を生成する。

    L-system は「文字列の置換規則」で形を作る手法で、
    `axiom`（初期文字列）から始めて `rules`（置換規則）を `iters` 回だけ適用し、
    得られた最終文字列をタートル（Turtle）として解釈して線を描く。

    - 展開: 文字ごとに `rules` を適用して文字列を更新する
    - 描画: `F f + - [ ]` だけが意味を持つ（それ以外の文字は no-op）

    `X` のような「描画しない記号」を `rules` の中間シンボルとして使うのが典型。
    例えば、fractal plant では `X` を展開のために使い、描画は `F` だけで行う。

    入力が多少壊れていても試行錯誤しやすいように、次は例外にせず warning にする。

    - `rules` の不正行: warning を出して無視する
    - `[`/`]` の不整合: warning を出して可能な範囲で解釈する

    記号（最小セット）
    ----------------
    - `F`: 前進 + 描画
    - `f`: 前進（描画しない）
    - `+`: 左回転（+angle）
    - `-`: 右回転（-angle）
    - `[`: push（位置・向き）
    - `]`: pop（復帰）

    Parameters
    ----------
    kind : {"plant","circuit","custom"}, default "plant"
        プリセット種別。
        `"custom"` の場合は `axiom` と `rules` を使用する。
    iters : int, default 5
        展開回数（0 で axiom をそのまま解釈する）。
    center : tuple[float, float, float], default (0,0,0)
        開始点の座標 (cx, cy, cz)。
    heading : float, default 90.0
        初期向き [deg]。0° で +X 方向、90° で +Y 方向。
    angle : float, default 25.0
        回転角 [deg]（`+/-`）。
    step : float, default 6.0
        前進距離（`F/f`）。
    jitter : float, default 0.0
        角度/距離の相対ゆらぎ（0 以上）。
        `jitter>0` のとき、各 `F/f` と `+/-` ごとに `U(-jitter, +jitter)` を掛ける。
    seed : int, default 0
        乱数 seed（決定性）。
    axiom : str, default "X"
        初期文字列（展開の出発点）。`kind="custom"` のときのみ使用する。

        例: `axiom="F"`, `rules="F=FF"`, `iters=3` のとき、展開結果は `FFFFFFFF` になり、
        それをタートルとして解釈して線を描く。

        もう少し複雑な例（分岐と「変数」）:

        - 分岐は `[` と `]` で作る（`[` で位置/向きを保存し、`]` でそこへ戻る）
        - `X` のような文字は「描画しない変数」として扱い、展開のために使う（タートル解釈では no-op）

        例えば次のように書くと、`X` が毎回同じ形に展開されて「枝の先端が伸びる」ような挙動になる。

        - `axiom="X"`
        - `rules="X=F[+X]F[-X]FX\\nF=FF"`
        - `iters=5`

        ※最終文字列に `X` が残っていても、その `X` 自体は描画されない（次の世代の“芽”として残る）。
    rules : str, default "X=...\\nF=..."
        置換規則（行ごとに `A=...` 形式）。`kind="custom"` のときのみ使用する。

        - 左辺 `A` は 1 文字（シンボル）
        - 右辺は置換後の文字列（空でもよい。例: `X=` で X を消す）
        - 空行と `#` コメント行は無視する
        - 不正行は warning を出して無視する

    Returns
    -------
    RealizedGeometry
        生成された枝ポリライン列。
    """
    try:
        cx, cy, cz = center
    except Exception as exc:
        raise ValueError(
            "lsystem の center は長さ 3 のシーケンスである必要がある"
        ) from exc

    kind_s = str(kind)
    if kind_s == "custom":
        ax = str(axiom)
        rules_map = _parse_rules_text(str(rules))
    else:
        if kind_s not in _PRESETS:
            kind_s = "plant"
        ax, rules_map = _PRESETS[kind_s]

    program = _expand_lsystem(ax, rules_map, iters=int(iters))
    if not program:
        return _empty_geometry()

    lines = _turtle_to_polylines(
        program,
        start_xy=(float(cx), float(cy)),
        heading_deg=float(heading),
        angle_deg=float(angle),
        step=float(step),
        jitter=float(jitter),
        seed=int(seed),
        z=float(cz),
    )
    return _lines_to_realized(lines)
