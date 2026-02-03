# 組み込み effect: `E.differential_growth(seed)`（単一ループ成長 / Differential growth）

作成日: 2026-02-03

参照:

- `docs/plan/ideas/growth_and_agents_effect_ideas_2026-01-30.md` の「手法: 差分成長 / アイデア A」

## 背景 / 目的

- 閉ポリライン（円/多角形/ラフな輪郭）を “有機的なフリル/襞” に育てる核として、差分成長を組み込み effect にしたい。
- Grafix の得意領域（線の変形・レイヤ・プロッタ出力）に直結していて、少数パラメータでも表情が出る。

## ゴール

- 新しい組み込み effect `E.differential_growth(seed)` を追加する（`n_inputs=1`）
- 入力: 閉ポリライン（複数本も可だが、基本は 1 本）
- 出力: 成長後の閉ポリライン（オプションで “途中経過レイヤ” を同時出力）
- 少数パラメータで実用になる挙動（UI で触って破綻しにくい）

## 非ゴール

- 差分成長の “正確な” 物理モデル化（ここでは絵作り優先の簡易ルールでよい）
- マスク拘束・場誘導・複数シード同時衝突（アイデア B/D/E に分離）
- 3D 面上での厳密成長（入力は平面に整列して 2D として扱う）

## API 案

```python
out = E.differential_growth(
    target_spacing=2.0,  # mm: 目標点間隔
    repel=1.0,           # 反発の強さ
    step=0.15,           # 1 iter の更新係数
    iters=200,           # 反復回数
    noise=0.0,           # 0 なら決定論（seed 不要）
    seed=0,              # 乱数 seed（noise 用）
    record_every=0,      # 0: 最終のみ / >0: N iter ごとにレイヤ出力
)(seed)
```

### `record_every` の狙い（レイヤ）

アイデアメモの「成長途中のスナップショットを等間隔で残すと“層”が作れる」を effect の 1 パラメータで回収する。

- `record_every=0`: これまで通り “1 本の出力” として扱える
- `record_every>0`: 出力は複数ポリライン（`RealizedGeometry` の offsets が増える）
  - 例: `iters=200, record_every=25` → 8 レイヤ（25,50,75,...,200）

## meta（Parameter GUI）案

- `target_spacing: float`（ui: 0.2..20.0）
- `repel: float`（ui: 0.0..3.0）
- `step: float`（ui: 0.0..0.5）
- `iters: int`（ui: 0..2000）
- `noise: float`（ui: 0.0..1.0）
- `seed: int`（ui: 0..9999）
- `record_every: int`（ui: 0..200）

※ `record_every` は 0 を “無効” として扱う。

## 実装方針（中身）

### 入力の扱い（閉曲線）

- 各ポリラインについて
  - 頂点数が 3 未満は no-op（リングとして成立しない）
  - `pts[0]==pts[-1]` なら末尾複製を落として “リング（重複なし）” として処理
  - そうでない場合もリングとして扱い、出力で必ず閉じる（この effect は閉曲線が前提のため）
- 生成結果は必ず `first` を末尾へ複製して閉じる（`polygon` primitive と同じ表現）

### 平面整列

- 各ポリラインの代表点から `transform_to_xy_plane` で XY へ整列
- 成長計算は XY（z=0）で行い、最後に `transform_back` で復元する

### コアループ（簡易 differential growth）

1. **点の追加（リサンプリング）**
   - 各セグメント長 `d` に対して `m = ceil(d / target_spacing)` とし、中間点を `m-1` 個挿入して等間隔に分割する
   - 点数爆発を避けるため上限 `MAX_POINTS` を設け、超えたら挿入を停止
2. **力の計算**
   - 近傍（前後 2 点）: 目標間隔へ寄せる “スプリング”
   - 反発: 非近傍点の近接を押し返す（`repel`）
     - 最初は実装簡単な O(N^2) で開始し、必要が出たら spatial hash を入れる
       - ただし初版から Numba（`@njit`）で回して実用速度を確保する
3. **更新**
   - `p[i] += step * force[i]`（端点無しのリングなので全点更新）
   - `noise>0` のときだけ、`seed` から生成した乱数で微小ランダムを足す
4. **レイヤ記録（オプション）**
   - `record_every>0` の場合、`(iter+1)` が `record_every` の倍数でスナップショットを push
   - `iters` が倍数で終わらない場合は最終状態も push（最後が欠けない）

### パラメータの意味（感覚）

- `target_spacing` が “線密度/細さ” を決める（小さいほど点が増え、細かい襞）
- `repel` が “膨らみ/シワの自己衝突” を決める（大きいほど広がりやすい）
- `step` が “勢い”（大きすぎると破綻しやすいので UI 上限は低め）
- `iters` は “育ち具合”
- `noise` は “生物っぽさ”（0 なら決定論で扱いやすい）

## 追加/変更するもの（予定）

- `src/grafix/core/effects/differential_growth.py`（新規）
  - `@effect(meta=..., n_inputs=1)` で登録
  - 主要ループは Numba 実装（`float64` 計算 → `float32` へ戻す）
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に `grafix.core.effects.differential_growth` を追加
- 型スタブ更新
  - `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新
- テスト
  - `tests/core/effects/test_differential_growth.py`（新規）

## テスト（最小）

- 形状/閉曲線
  - seed（正方形/六角形）を入れると、出力が `first==last` の閉曲線になる
  - `iters=0` は no-op（少なくとも頂点配列が一致）
- 点追加
  - `target_spacing` を小さくすると頂点数が増える（`N_out > N_in`）
- レイヤ
  - `record_every>0` で offsets が増え、複数ポリラインとして返る
- 平面整列
  - z が一定の seed を入れても、出力の z がほぼ一定である（復元できている）

## 実装手順（チェックリスト）

- [x] `src/grafix/core/effects/differential_growth.py` を追加（meta + docstring）
- [x] 入力の閉曲線化（末尾複製の扱い）と XY 整列/復元を実装
- [x] 点追加（target spacing）を実装（`MAX_POINTS` 付き）
- [x] 力（近傍スプリング + 反発）を Numba で実装
- [x] `noise/seed` を実装（`noise==0` は決定論）
- [x] `record_every` を実装（0 は無効）
- [x] `src/grafix/core/builtins.py` に追加
- [x] `tests/core/effects/test_differential_growth.py` を追加
- [x] `PYTHONPATH=src python -m grafix stub`
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_differential_growth.py`

## 実装前に決めたこと（確定）

- 反発の近接範囲: `repel_radius = target_spacing * 2.0`（固定比）
- 点追加: `m = ceil(d / target_spacing)` で分割（等間隔）
