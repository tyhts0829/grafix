# 組み込み primitive: `G.lsystem(kind)`（L-system 植物/回路）

作成日: 2026-02-03

参照アイデア:

- `docs/plan/ideas/rules_and_image_driven_effect_ideas_2026-01-30.md` の「アイデア D」

## 背景 / 目的

- 樹形/蔓/回路図のような「記号的な線（枝分かれを含むポリライン列）」を、少ないルールで安定して生成したい。
- プロッタ前提なので、最終出力は「線の集合（開ポリライン列）」として素直に扱える形にする。

## ゴール

- 新しい組み込み primitive `G.lsystem(kind)` を追加する
- `kind` により、少数（1〜2 系統）のプリセット（植物/回路）と `custom` を切り替えられる
- 文字列展開（L-system）→ タートル解釈で「枝ポリライン列」を生成して返す
- `seed` を持ち、同じパラメータ + 同じ seed で再現できる（ジッタ含む）

## 非ゴール

- “汎用 L-system エンジン” の提供（文字セット・拡張コマンドを増やしすぎない）
- 3D タートル（傾き/ロール/分岐の 3D 化）
- 高速化のための複雑な最適化（まずはシンプルに）
- GUI 上で dict を編集できる “rules エディタ”（`rules` は文字列で扱う）

## 仕様（座標系）

- 生成は 2D タートル（XY）で行い、Z は `center[2]` で埋める
- 開始点/初期向きは `center` / `heading` で指定する（= seed）
- 出力は “枝” を **開ポリライン列**として返す

## API 案

```python
from grafix.api import G

plant = G.lsystem(
    kind="plant",
    iters=5,
    angle=25.0,
    step=6.0,
    jitter=0.05,
    seed=0,
    center=(150.0, 150.0, 0.0),
    heading=90.0,
)
```

回路っぽい（直交）プリセット例:

```python
circuit = G.lsystem(
    kind="circuit",
    iters=6,
    angle=90.0,
    step=4.0,
    jitter=0.0,
    seed=0,
    center=(150.0, 150.0, 0.0),
    heading=90.0,
)
```

`custom` の rules は “行ごとに `A=...`” の形式で渡す（空行と `#` コメントは無視）。

```python
custom = G.lsystem(
    kind="custom",
    axiom="X",
    rules="X=F-[[X]+X]+F[+FX]-X\\nF=FF",
    iters=5,
    angle=22.5,
    step=5.0,
    jitter=0.02,
    seed=0,
    center=(150.0, 150.0, 0.0),
    heading=90.0,
)
```

## meta（Parameter GUI）案

- `kind: choice`（`"plant"|"circuit"|"custom"`）
- `iters: int`（ui: 0..10）
- `center: vec3`（ui: 0..300）
- `heading: float`（deg, ui: 0..360）
- `angle: float`（deg, ui: 0..180）
- `step: float`（mm, ui: 0.1..50）
- `jitter: float`（無次元, ui: 0..0.25）
- `seed: int`（ui: 0..9999）
- `axiom: str`（`kind=="custom"` のときのみ表示）
- `rules: str`（`kind=="custom"` のときのみ表示）

## ルール仕様（最小）

対応する記号は最小セットに絞る（増やしすぎない）。

- `F`: 前進 + 描画（線分を追加）
- `f`: 前進（描画しない。線を途切れさせる）
- `+`: 左回転（+angle）
- `-`: 右回転（-angle）
- `[`: スタック push（位置・向き）
- `]`: スタック pop（復帰し、新しいポリラインを開始）

（必要なら後で追加候補: `|`=180°、`G` などの別名）

## ジッタ仕様（案）

`jitter` は 0 以上の無次元値とし、各コマンド適用時に小さな乱れを入れる。

- `F/f` の step 長: `step * (1 + U(-jitter, +jitter))`
- `+/-` の回転角: `angle * (1 + U(-jitter, +jitter))`

乱数は `seed` から決め、再現性を保つ。

## 追加/変更するもの

- `src/grafix/core/primitives/lsystem.py`（新規）
  - `@primitive(meta=..., ui_visible=...)`
  - ルール展開 + タートル解釈 + `RealizedGeometry` 化
- `src/grafix/core/builtins.py`
  - `_BUILTIN_PRIMITIVE_MODULES` に `grafix.core.primitives.lsystem` を追加
- 型スタブ更新
  - `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新
- テスト
  - `tests/core/primitives/test_lsystem.py`（新規・最小）

## 実装方針（中身）

### 1) プリセット定義

- `kind!="custom"` のときは内部テーブルから `axiom/rules` を決定する
- プリセットは最小限（例: `plant`, `circuit`）
  - 植物: 代表的な “fractal plant” 系（`X/F`）
  - 回路: 直交（angle=90°）で枝分かれする系

### 2) rules 文字列の parse（`custom`）

- 行単位で `A=...` を読む（`A` は 1 文字想定）
- 空行と `#` コメント行を無視
- 不正行は `ValueError`（行番号つき）にする

### 3) L-system 展開

- `iters` 回だけ文字列を置換（rules に無い文字は保持）
- 展開が爆発し得るので、内部定数 `MAX_EXPANDED_CHARS` を超えたら打ち切って `ValueError`
  - （過度な防御はしないが、GUI フリーズ回避の最低限）

### 4) タートル解釈 → ポリライン列

- 状態: `(pos_xy, heading_rad)` と stack（push/pop）
- “現在のポリライン” を `list[tuple[float,float]]` で持つ
- `F` で前進し点を append、`f` で前進してポリラインを切る
- `]`（pop）で復帰後、**新しいポリラインを開始**（枝を独立した線にする）
- 生成結果は `np.ndarray`（(N,3)）の list に変換して `RealizedGeometry` 化

### 5) 仕上げ（座標・Z）

- `center` を加算して配置し、z は `center[2]` を使う

## テスト（最小）

- 再現性:
  - 同じ params + 同じ `seed` → `coords/offsets` が一致する（`np.array_equal`）
- iters=0:
  - `axiom` のみ解釈される（`F` を含む場合に線が出る）
- `kind="custom"` の parse:
  - 不正行で `ValueError` が出る（行番号を含む）

## 実装手順（チェックリスト）

- [x] 仕様確定（`custom` rules 形式、エラー時挙動、プリセット確定）
- [x] `src/grafix/core/primitives/lsystem.py` を追加（meta/ui_visible 含む）
- [x] プリセット（plant/circuit）を実装
- [x] rules parse（`custom`）を実装
- [x] 展開（iters）と `MAX_EXPANDED_CHARS` の導入
- [x] タートル解釈（`F f + - [ ]`）を実装（枝=開ポリライン列）
- [x] `center/heading` による配置（Z 含む）を実装
- [x] `src/grafix/core/builtins.py` に登録追加
- [x] `tests/core/primitives/test_lsystem.py` を追加
- [x] `PYTHONPATH=src python -m grafix stub`
- [x] `PYTHONPATH=src pytest -q tests/core/primitives/test_lsystem.py`

## 確定事項

- 実装は `G.lsystem(kind)`（組み込み primitive）
- 開始点/初期向き（seed）は `center` / `heading` で指定する
- `custom` rules の不正行は `ValueError`（行番号つき）
- `jitter` は “角度/長さの相対ゆらぎ”
- `plant` は fractal plant 系、`circuit` は直交枝分かれ系
