# 新規 primitive: 相対近傍グラフ + ランダムウォークで「字形っぽいストローク」を生成（G.asemic）

作成日: 2026-01-29

## 元アイデア（`asemic.md` の要約）

- 正方領域にノードを「そこそこ均一」にランダム配置（Mitchell の best-candidate 系）
- そのノードから **Relative Neighborhood Graph (RNG)** を構築
- 1 glyph は 2〜5 本のストロークで構成
  - ストローク同士は交差しない（ノード共有は許可）
  - 1 本のストロークは「開始ノードから 2〜4 ステップのランダムウォーク」で得たノード列
  - 辺は 1 度通ったらグラフから削除（再利用不可）
- 描画は折れ線 or （合成）Bézier

## ゴール

- `G.asemic(...)` を **組み込み primitive** として追加し、上記アルゴリズムで「字形っぽいポリライン列」を生成できるようにする
- `seed` を与えれば **決定的** に同じ出力を得られる（プレビュー/エクスポートの再現性）
- 出力は `RealizedGeometry(coords: float32[N,3], offsets: int32[M])` で、XY 平面上のポリライン列を返す

## スコープ

- やる:
  - ノード生成（best-candidate）
  - RNG 構築
  - エッジ削除付きランダムウォークでストローク生成
  - `center`/`scale` による配置（他 primitive と同様）
  - 最小限のテスト（非空・決定性・型/shape）
- やらない（別タスク）:
  - Bézier を「曲線として保持」する表現（Grafix の幾何はポリラインなので、やるならサンプル点列化になる）
  - 「文章」レイアウト（行組み・カーニング等）。まずは 1 glyph を生成する primitive にする

## 追加/変更するもの

- `src/grafix/core/primitives/asemic.py`（新規）
  - `@primitive(meta=...)` で `asemic` を登録
- `src/grafix/core/builtins.py`
  - `_BUILTIN_PRIMITIVE_MODULES` に `grafix.core.primitives.asemic` を追加
- `src/grafix/api/__init__.pyi`
  - `python -m grafix stub` で更新（`tests/stubs/test_api_stub_sync.py` を通す）
- `tests/core/test_asemic_primitive.py`（新規・最小）

## API 案（仮）

```python
from grafix.api import G

g = G.asemic(
    seed=0,
    n_nodes=28,
    candidates=12,
    stroke_min=2,
    stroke_max=5,
    walk_min_steps=2,
    walk_max_steps=4,
    stroke_style="bezier",
    bezier_samples=12,
    bezier_tension=0.5,
    center=(150.0, 150.0, 0.0),
    scale=120.0,
)
```

## meta（Parameter GUI）案

- `seed: int`（決定性）
  - UI range: 0..999999
- `n_nodes: int`
  - UI range: 3..200
- `candidates: int`（best-candidate の候補数）
  - UI range: 1..50
- `stroke_min: int`, `stroke_max: int`
  - UI range: 0..20（`stroke_min <= stroke_max` を前提に簡潔に扱う）
- `walk_min_steps: int`, `walk_max_steps: int`
  - UI range: 1..20
- `stroke_style: choice`
  - `"line"|"bezier"`
- `bezier_samples: int`
  - UI range: 2..64
- `bezier_tension: float`
  - UI range: 0.0..1.0
- `center: vec3`
  - UI range: 0..300
- `scale: float`
  - UI range: 0..200

## 実装方針（中身）

### 1) ノード生成（best-candidate）

- 領域は primitive 内部では正規化して `[-0.5, +0.5]^2`（他 primitive と合わせる）
- `np.random.default_rng(seed)` を使い、
  - 最初の点は一様乱数
  - 以降は `candidates` 個の候補点を生成し、既存点への最近距離が最大の候補を採用
- 出力は `points: float64[n_nodes, 2]`（最後に float32 へ落とす）

### 2) RNG（Relative Neighborhood Graph）構築

- ペア距離 `D[i,j]` を作り、`i<j` ごとに以下を満たすとき辺を張る:
  - `k != i,j` のどれについても `D[i,k] < D[i,j]` かつ `D[j,k] < D[i,j]` が同時に成立しない
- 実装はシンプルに
  - `D` を `float64` で計算
  - ループで edge list / adjacency（`list[list[int]]`）を作る

### 3) ストローク生成（エッジ削除付きランダムウォーク）

- `stroke_count` は `[stroke_min, stroke_max]` から乱数で選ぶ（seed により決定的）
- ストロークごとに:
  - 開始ノードは「次数 > 0」から選ぶ（残エッジが無ければ終了）
  - 歩数 `steps` は `[walk_min_steps, walk_max_steps]` から乱数で選ぶ
  - 各ステップで隣接ノードを 1 つ選んで移動し、そのエッジをグラフから削除（両方向）
  - 途中で行き止まりになったら早期終了
- ストローク（ノード列）が 2 点未満なら破棄（空線を作らない）

### 4) RealizedGeometry 化

- ストロークは `stroke_style="bezier"` のとき、折れ線を合成 Bézier としてサンプル点列化する（primitive 内で完結）
- 各ストロークのノード列を XY 座標へ変換し、z は `center[2]` で埋める
- `coords` はストロークを連結した 1 本の配列、`offsets` は各ストローク開始 index の配列（最後に終端）
- `scale` と `center` を最後に適用（`coords = coords * scale + center`）

## テスト（最小）

- `G.asemic(seed=0, ...)` が
  - `coords.dtype == float32` / `offsets.dtype == int32`
  - `offsets[0] == 0` / 単調増加 / `offsets[-1] == len(coords)`
  - `coords` が有限値のみ
  - 同一パラメータで 2 回呼ぶと完全一致（決定性）

## 実装手順（チェックリスト）

- [x] primitive 名・パラメータ名（`asemic` / `stroke_min` など）を確定
- [x] `src/grafix/core/primitives/asemic.py` 追加（module docstring + `@primitive(meta=...)` + docstring）
- [x] best-candidate 実装（`seed` 決定性）
- [x] RNG 構築（adjacency）
- [x] ランダムウォーク + エッジ削除でストローク生成
- [x] 合成 Bézier のサンプル点列化（primitive 内で完結）
- [x] `RealizedGeometry(coords, offsets)` に詰める（scale/center）
- [x] `src/grafix/core/builtins.py` へ登録追加
- [x] `python -m grafix stub` で `src/grafix/api/__init__.pyi` 更新
- [x] `tests/core/test_asemic_primitive.py` 追加
- [x] `PYTHONPATH=src pytest -q tests/core/test_asemic_primitive.py tests/stubs/test_api_stub_sync.py`

## 確定事項

- primitive 名は `asemic`
- 滑らかさは `stroke_style="bezier"` + `bezier_samples`/`bezier_tension` で primitive 内に閉じる（外部 effect は不要/不使用）
- `stroke_min/max` と `walk_min/max` はパラメータ化し、初期値は `asemic.md` 参考（2–5 / 2–4）
