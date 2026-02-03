# 組み込み effect: `E.growth_from_base(base)`（既存線からの成長装飾）

作成日: 2026-02-03

参照: `docs/plan/ideas/growth_and_agents_effect_ideas_2026-01-30.md` の「差分成長（Differential growth）」> **アイデア C**

> 注: 同ファイル内には「Physarum / RD / Particles」にも **アイデア C** があるが、本計画は **差分成長のアイデア C**（`growth_from_base`）を対象にする。

## 背景 / 目的

- 既存の線（文字・輪郭線・図形のアウトライン等）を「素材」として、縁飾り（フリンジ/トゲ/うねり）を少パラメータで生成したい。
- “元の線を保持しつつ、追加線だけ別レイヤとして出す” ことで、作品のレイヤ設計/合成がしやすい。

## ゴール

- 新しい組み込み effect `E.growth_from_base(...)` を追加する（1 input）
- 入力 `base`（ポリライン列）から、**外側へ成長した装飾線**を生成して返す
- 出力は `keep_original` で「元の線も含める/含めない」を切替可能にする
- `seed` により決定論的（同入力・同パラメータなら同出力）にする

## 非ゴール

- 厳密な衝突回避（自己交差の完全防止）
- 3D の非平面入力をうまく扱う（2D 前提。非平面は最小限の扱いで no-op 寄り）
- マスク拘束や障害物回避（別アイデア）

## 追加/変更するもの

- `src/grafix/core/effects/growth_from_base.py`（新規）
  - `@effect(meta=...)` で登録
  - `effects/AGENTS.md` の「effects 間依存禁止」を守り、依存は `grafix.core.effects.util` のみ（平面整列が必要なら）
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に `grafix.core.effects.growth_from_base` を追加
- 型スタブ更新
  - `PYTHONPATH=src python -m grafix stub`（生成結果で `src/grafix/api/__init__.pyi` が更新される想定）
- テスト
  - `tests/core/effects/test_growth_from_base.py`（新規・最小）

## API 案（仮）

```python
out = E.growth_from_base(
    outward="auto",          # "auto" | "left" | "right"
    amplitude=6.0,           # [mm]
    target_spacing=1.5,      # [mm]
    iters=40,
    jitter=0.15,             # 0..1（ノイズ/ゆらぎ）
    keep_original=True,
    mode="fringe",           # "fringe" | "outline"（まずは 2 択に絞る）
    seed=0,
)(base)
```

### meta（Parameter GUI）案

- `outward: choice`（`"auto" | "left" | "right"`）
- `amplitude: float`（ui: 0..20）
- `target_spacing: float`（ui: 0.2..10）
- `iters: int`（ui: 0..200）
- `jitter: float`（ui: 0..1）
- `keep_original: bool`
- `mode: choice`（`"fringe" | "outline"`）
- `seed: int`（ui: 0..9999）

## 実装方針（中身）

### 1) 2D 前提の整列

- `base` の代表ポリラインを使って `transform_to_xy_plane` で XY 平面へ整列（必要な場合のみ）
- z ずれが大きい（非平面）なら **no-op**（`keep_original` を考慮して base を返す）
- 出力は最後に `transform_back` で元の姿勢へ戻す

※ 可能なら、既存の多くの effect と同様に「入力が元々 z=0 付近なら変換せず素通し」にして簡潔に。

### 2) ポリラインの前処理（等間隔化）

- 各ポリラインを `target_spacing` で等間隔サンプルにする
  - open/closed で経路を分ける（`lowpass/highpass` の resample 実装を最小コピーして内製する）
- “閉曲線判定” は厳密でなくてよい（例: 先頭末尾の距離が閾値以下なら closed）

### 3) 法線（外側方向）の決定

- 各点の接線 `t` を差分で推定し、2D 法線 `n = normalize(rotate90(t))` を作る
- `outward="auto"` のとき:
  - closed: 符号付き面積（shoelace）で向きを判定し、外側になる符号へ揃える
  - open: `left` と同義（まずはルール固定でシンプルに）
- `outward="left/right"` は open/closed ともに強制

### 4) 成長点の生成（v1: “装飾線を作る” に集中）

初期状態:

- `anchor[i] = base_pts[i]`
- `grow[i] = anchor[i] + amplitude * n[i]`（必要なら jitter を長さ・角度に少しだけ乗せる）

反復（`iters`）の更新は、**過度に物理っぽくしない**範囲で最小にする:

- (A) なめらかさ: `grow[i]` にラプラシアン（`prev + next - 2*cur`）を加える
- (B) うねり/トゲ: `anchor->grow` の方向へ、低周波ノイズ（seed 由来）を混ぜる
- (C) 破綻防止: `grow[i]` が anchor に近づき過ぎないよう最小距離だけは守る（クランプ程度）

この 3 つで「波打ち + 少し有機的」までは到達できる見込み。まずここで止める。

### 5) 出力モード

- `mode="fringe"`: 各 i について 2 点ポリライン `[anchor[i], grow[i]]` を出力（フリンジ/毛）
- `mode="outline"`: `grow` 点列を 1 本のポリラインとして出力（輪郭のうねり/トゲ）
- `keep_original=True` のときは `concat_realized_geometries(base, growth)` で連結して返す

## テスト（最小）

- 空入力: `E.growth_from_base()(G.empty())` が空を返す
- 決定論: 同じ `seed` で 2 回実行して一致（realize_cache 回避のため no-op ノードを挟む）
- outward:
  - open な水平線に対して `left/right` で `y` の符号が反転する（大まかな不変条件で検証）
- keep_original:
  - `keep_original=False` で出力のポリライン数が減る（offsets の本数で検証）

## 実装手順（チェックリスト）

- [x] `src/grafix/core/effects/growth_from_base.py` を追加（meta + effect 本体）
- [x] resample（open/closed）と tangent/normal 推定を実装
- [x] outward 判定（auto/left/right）を実装
- [x] 成長点生成（初期化 + iters 更新）を実装
- [x] `mode="fringe" | "outline"` の出力を実装
- [x] `keep_original` の合成を実装
- [x] `src/grafix/core/builtins.py` に登録
- [x] `tests/core/effects/test_growth_from_base.py` を追加
- [x] `PYTHONPATH=src python -m grafix stub`
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_growth_from_base.py`

## 追加で決めること（実装前に確認）

- `mode` のデフォルト: `"fringe"`（素材として強い）/ `"outline"`（線として綺麗）どちらを優先するか；outline
- `outward="auto"` の open 扱い: とりあえず `left` 固定で良いか（将来拡張で `"both"` 等を追加する余地はある）;これで
