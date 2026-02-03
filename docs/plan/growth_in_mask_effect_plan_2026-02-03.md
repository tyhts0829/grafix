# 組み込み effect: `E.growth_in_mask(mask)`（マスク内拘束成長）

作成日: 2026-02-03

参照アイデア:

- `docs/plan/ideas/growth_and_agents_effect_ideas_2026-01-30.md` の「差分成長」アイデア B

## 背景 / 目的

- 形（mask）の**内部だけ**で差分成長を走らせ、境界でぶつかったり滑ったりすることで「内側の襞/皺」の素材を作りたい。
- 生成系なのでパラメータ数は少なく、見た目は豊かにしたい（ただし実装はシンプル優先）。

## ゴール

- 新しい組み込み effect `E.growth_in_mask(mask)` を追加する（`n_inputs=1`）
- `mask` 内に `seed_count` 個の種を自動配置し、反復更新（`iters`）で成長線（ポリライン列）を生成して返す
- 境界での挙動を `boundary_mode`（`"slide"|"bounce"`）で切り替えられるようにする
- `seed` により結果が再現できる（同じ入力 mask + 同じ seed → 同じ出力）

## 非ゴール

- “汎用差分成長フレームワーク” の構築（この effect のための最小実装に留める）
- 3D 非平面入力の完全対応（mask が歪んでいる場合は素直に no-op / 早期 return）
- 高速化のための複雑なデータ構造（必要になったら次段で検討）

## 追加/変更するもの

- `src/grafix/core/effects/growth_in_mask.py`（新規）
  - `@effect(meta=..., n_inputs=1)`
  - 平面整列（`grafix.core.effects.util`）の利用
  - mask 内 seed 生成 + 反復更新 + RealizedGeometry 化
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に `grafix.core.effects.growth_in_mask` を追加
- 型スタブ更新
  - `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新
- テスト
  - `tests/core/effects/test_growth_in_mask.py`（新規・最小）

## API 案

mask（閉曲線）を入力として渡す。

```python
folds = E.growth_in_mask(
    seed_count=12,
    target_spacing=1.8,
    boundary_avoid=1.0,
    boundary_mode="slide",  # or "bounce"
    iters=250,
    seed=0,
    show_mask=False,
)(mask)
```

## meta（Parameter GUI）案

- `seed_count: int`（ui: 0..64）
- `target_spacing: float`（mm, ui: 0.25..10.0）
- `iters: int`（ui: 0..2000）
- `boundary_avoid: float`（ui: 0.0..4.0）
- `boundary_mode: choice`（`"slide"|"bounce"`）
- `seed: int`（ui: 0..9999）
- `show_mask: bool`（デバッグ用。True のとき mask 輪郭を追加で出力に含める）

※差分成長っぽさの調整が必要なら次を追加候補（まずは入れない）:
`repel`, `smooth`, `subdivide_every`, `max_points`

## 実装方針（中身）

### 1) 入力の取り決め（1 input）

- `inputs[0]` を `mask` として扱う（閉曲線リングが 1 本以上ある想定）
- `mask` が空/リング抽出できない場合は **no-op（`mask` を返す or empty）**のどちらかに統一する
  - 方針: `show_mask=False` のときは empty、`show_mask=True` のときは mask を返す（=「何も生えない」状態が見える）

### 2) 平面整列（既存 util）

- 代表リングを 1 本選び、`transform_to_xy_plane(rep)` で回転 `R` と `z_offset` を得る
- `mask` 全頂点に同じ整列を適用し、z≈0 を簡易チェック
- 出力は最後に `transform_back` で元平面へ戻す

### 3) mask リング抽出 + SDF（点→ signed distance + outward normal）

- `mask` から閉曲線リングを抽出（auto-close threshold あり）
- even-odd（奇偶）で内外判定できる前提を維持（穴あり mask に対応）
- 各点に対して以下を返す関数を用意する（Numba）
  - `d(p)`（signed distance: 内側が負、外側が正）
  - `n(p)`（外向き法線 = 距離増加方向）
- 実装は `warp.py` の SDF 評価と同等の形を採用（必要ならコピペしてこの effect 内に閉じる）

### 4) seed の生成（mask 内）

- `seed` で初期化した RNG（`np.random.default_rng(seed)`）で `seed_count` 点を mask 内へ配置
  - 実装は bbox rejection sampling（seed_count が小さい前提でシンプルに）
- 各 seed 点から初期形状を作る
  - 最小案: 半径 `r0 = target_spacing * 2` の小さな円（例: 12〜24 角形）を 1 ループとして生成
  - ループは閉じる（first==last）

### 5) 成長ループ（差分成長 + 境界拘束）

データ表現は「ポリライン列（list[np.ndarray]）」で持ち、反復ごとに更新する。

各 iteration で行うこと（最小セット）:

1. **点の挿入（subdivide）**
   - 各ポリラインの各セグメント長 `L` を見て、`L > 2*target_spacing` なら中点を挿入
   - `iters` が大きいと点数が爆増するので、`max_points`（上限）や `subdivide_every`（間引き頻度）を後で追加できる余地を残す
2. **局所スムージング（曲率抑制）**
   - 近傍（前後点）平均との差分で小さく移動（Laplacian smoothing 的に）
3. **反発（self + inter-seed）**
   - 全点集合で「一定半径内の反発」をかける
   - 最初は単純な `O(N^2)` でも良いが、重ければ “グリッド分割（binning）” を入れて `O(N)` 近くへ寄せる
4. **境界拘束（boundary_mode）**
   - まず soft:
     - `d(p)` が `>-margin`（境界に近い）なら、内向き（`-n(p)`）へ押し戻す力を加える（`boundary_avoid` 係数）
     - `margin` は `target_spacing` 由来（例: `margin = 2*target_spacing`）
   - 次に hard:
     - 更新後 `d(p) > 0`（外側）になった点は境界へ投影し、`eps` だけ内側へ戻す
   - `"slide"`:
     - 移動ベクトルの “外向き成分” を削る（境界へ沿わせる）
   - `"bounce"`:
     - 外向き成分を反転（反射）して内側へ戻す（簡易で良い）

この 4 つだけで “内側で増殖してぶつかる” 表情が出るかをまず確認する。

### 6) 出力 RealizedGeometry 化

- 生成したポリライン列（2D）を (N,3) に詰め、`transform_back` で元平面へ戻す
- `show_mask=True` のときは `mask` を出力に append する（順序: growth → mask）

## テスト（最小）

- `seed` 再現性:
  - 同じ square mask + 同じ `seed` で 2 回呼んで、`coords` が一致する（少なくとも `np.allclose`）
- 内側拘束:
  - square mask で生成し、全出力点が mask の bbox 外へ出ない（まずは弱いが簡単）
  - 追加で `pyclipper.PointInPolygon`（スケールして int 化）で “inside or on edge” を確認（可能なら）
- `seed_count=0`:
  - `show_mask=False` なら empty、`show_mask=True` なら mask を返す（仕様の固定）

## 実装手順（チェックリスト）

- [ ] effect の I/O と「無効入力時の返し方」を確定（empty/no-op、`seed_count=0` の扱い）
- [ ] `src/grafix/core/effects/growth_in_mask.py` を追加（meta + ui_visible が要るなら追加）
- [ ] 平面整列（util） + リング抽出（auto-close）
- [ ] SDF（distance + normal）評価を実装（Numba）
- [ ] seed の配置（rejection sampling）+ 初期ループ生成
- [ ] 成長ループ（subdivide / smoothing / repel / boundary constraint）
- [ ] 出力 RealizedGeometry 化 + `show_mask`
- [ ] `src/grafix/core/builtins.py` に登録追加
- [ ] `tests/core/effects/test_growth_in_mask.py` を追加
- [ ] `PYTHONPATH=src python -m grafix stub`
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_growth_in_mask.py`

## 追加で決めること（確認したい）

- `n_inputs=1`（mask only）で良い？それとも `n_inputs=2`（seed + mask）にして seed を外部から渡せるようにする？；1で
- 無効入力時の方針:
  - empty を返す vs mask を返す（GUI での “壊れ方” が変わる）；emptyで
- 反発の実装:
  - まず `O(N^2)` で行って、必要になったらグリッド分割を入れる、で良い？; 最初からグリッド分割で
