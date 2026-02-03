# 組み込み effect: `E.lsystem(kind)`（L-system 植物/回路）

作成日: 2026-02-03

参照アイデア:

- `docs/plan/ideas/rules_and_image_driven_effect_ideas_2026-01-30.md` の「アイデア D」

## 背景 / 目的

- 樹形/蔓/回路図のような「記号的な線（枝分かれを含むポリライン列）」を、少ないルールで安定して生成したい。
- プロッタ前提なので、最終出力は「線の集合（開ポリライン列）」として素直に扱える形にする。

## ゴール

- 新しい組み込み effect `E.lsystem(kind)` を追加する（`n_inputs=1`）
- `kind` により、少数（1〜2 系統）のプリセット（植物/回路）と `custom` を切り替えられる
- 文字列展開（L-system）→ タートル解釈で「枝ポリライン列」を生成して返す
- `seed` を持ち、同じ入力 + 同じ seed で再現できる（ジッタ含む）

## 非ゴール

- “汎用 L-system エンジン” の提供（文字セット・拡張コマンドを増やしすぎない）
- 3D タートル（傾き/ロール/分岐の 3D 化）
- 高速化のための複雑な最適化（まずはシンプルに）
- GUI 上で dict を編集できる “rules エディタ”（`rules` は文字列で扱う）

## 仕様（I/O と座標系）

### 入力（`n_inputs=1`）

- `inputs[0]` を “seed” として使う（seed の置き場所/向きを入力ジオメトリから取る）
- seed は「複数ポリライン可」
  - 各ポリラインの **先頭点** を開始位置とする
  - 各ポリラインが 2 点以上なら、先頭セグメント方向を初期向き（heading）にする
  - 1 点しかない場合の初期向きは +Y（90°）とする
- 入力が空なら empty を返す（`keep_original=True` のときも empty）

### 出力

- 展開・解釈して得られた “枝” を **開ポリライン列**として返す
- `keep_original=True` のとき、入力 seed を出力末尾へ追加する（デバッグ/配置確認用）

### 平面整列

- seed が「ほぼ平面」なら、その平面を `XY` に整列して 2D タートルで生成し、最後に元平面へ戻す
- 非平面入力は対象外（まずは empty を返す）

## API 案

seed は例えば `P.line(...)` を使う。

```python
seed = P.line(anchor="left", length=1.0, angle=90.0)  # 原点から上向き

plant = E.lsystem(
    kind="plant",
    iters=5,
    angle=25.0,
    step=6.0,
    jitter=0.05,
    seed=0,
    keep_original=False,
)(seed)
```

回路っぽい（直交）プリセット例:

```python
circuit = E.lsystem(
    kind="circuit",
    iters=6,
    angle=90.0,
    step=4.0,
    jitter=0.0,
    seed=0,
)(seed)
```

`custom` の rules は “行ごとに `A=...`” の形式で渡す（空行と `#` コメントは無視）。

```python
custom = E.lsystem(
    kind="custom",
    axiom="X",
    rules="X=F-[[X]+X]+F[+FX]-X\\nF=FF",
    iters=5,
    angle=22.5,
    step=5.0,
    jitter=0.02,
    seed=0,
)(seed)
```

## meta（Parameter GUI）案

- `kind: choice`（`"plant"|"circuit"|"custom"`）
- `iters: int`（ui: 0..10）
- `angle: float`（deg, ui: 0..180）
- `step: float`（mm, ui: 0.1..50）
- `jitter: float`（無次元, ui: 0..0.25）
- `seed: int`（ui: 0..9999）
- `keep_original: bool`
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

乱数は `seed` と seed ポリライン index から決め、再現性を保つ。

## 追加/変更するもの

- `src/grafix/core/effects/lsystem.py`（新規）
  - `@effect(meta=..., ui_visible=..., n_inputs=1)`
  - ルール展開 + タートル解釈 + `RealizedGeometry` 化
  - 平面整列（`grafix.core.effects.util`）の利用
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に `grafix.core.effects.lsystem` を追加
- 型スタブ更新
  - `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新
- テスト
  - `tests/core/effects/test_lsystem.py`（新規・最小）

## 実装方針（中身）

### 1) seed の抽出（入力ジオメトリ→開始点/向き）

- `RealizedGeometry` の各ポリラインから
  - `p0`（開始点）
  - `heading0`（`p0->p1` の atan2。無ければ 90°）
  を取り出す
- seed が多すぎる場合の扱いは入れない（必要なら次段）

### 2) プリセット定義

- `kind!="custom"` のときは内部テーブルから `axiom/rules` を決定する
- プリセットは最小限（例: `plant`, `circuit`）
  - 植物: 代表的な “fractal plant” 系（`X/F`）
  - 回路: 直交（angle=90°）で枝分かれする系

### 3) rules 文字列の parse（`custom`）

- 行単位で `A=...` を読む（`A` は 1 文字想定）
- 空行と `#` コメント行を無視
- 不正行は無視（もしくは `ValueError`。どちらが良いかは確認事項）

### 4) L-system 展開

- `iters` 回だけ文字列を置換（rules に無い文字は保持）
- 展開が爆発し得るので、内部定数 `MAX_EXPANDED_CHARS` を超えたら打ち切って `ValueError`
  - （過度な防御はしないが、GUI フリーズ回避の最低限）

### 5) タートル解釈 → ポリライン列

- 状態: `(pos_xy, heading_rad)` と stack（push/pop）
- “現在のポリライン” を `list[tuple[float,float]]` で持つ
- `F` で前進し点を append、`f` で前進してポリラインを切る
- `]`（pop）で復帰後、**新しいポリラインを開始**（枝を独立した線にする）
- 生成結果は `np.ndarray`（(N,3)）の list に変換して `RealizedGeometry` 化

### 6) 合成・座標復帰

- seed ごとに生成した枝をまとめ、必要なら `keep_original` で入力を append
- 整列していた場合は `transform_back` で元座標へ戻す

## テスト（最小）

- 再現性:
  - 同じ seed 入力 + 同じ `seed` → `coords/offsets` が一致する（`np.array_equal`）
- iters=0:
  - `axiom` のみ解釈される（`F` を含む場合に線が出る）
- `kind="custom"` の parse:
  - 1 行だけの rules でも動く（例: `F=FF`）
- `keep_original=True`:
  - 出力末尾に入力と同じジオメトリが含まれる（`concat` のテストでも良い）

## 実装手順（チェックリスト）

- [ ] 仕様確定（入力 seed の定義、`custom` rules の形式、エラー時挙動）
- [ ] `src/grafix/core/effects/lsystem.py` を追加（meta/ui_visible 含む）
- [ ] プリセット（plant/circuit）を実装
- [ ] rules parse（`custom`）を実装
- [ ] 展開（iters）と `MAX_EXPANDED_CHARS` の導入
- [ ] タートル解釈（`F f + - [ ]`）を実装（枝=開ポリライン列）
- [ ] 平面整列（util）と planarity チェックを追加
- [ ] `keep_original` の合成を実装
- [ ] `src/grafix/core/builtins.py` に登録追加
- [ ] `tests/core/effects/test_lsystem.py` を追加
- [ ] `PYTHONPATH=src python -m grafix stub`
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_lsystem.py`

## 追加で決めること（確認したい）

- `E.lsystem` の入力は “seed（開始点/向き）” で良い？（代案: primitive `P.lsystem` として入力無しにする）
- `custom` の rules 不正行の扱い:
  - 無視する（壊れにくい） vs `ValueError`（気づきやすい）
- `jitter` の定義は上の “角度/長さの相対ゆらぎ” で良い？
- プリセットの具体:
  - `plant` は fractal plant 系で確定で良い？
  - `circuit` は直交枝分かれ系で良い？（別案: Hilbert/dragon 等の “単線” 系）
