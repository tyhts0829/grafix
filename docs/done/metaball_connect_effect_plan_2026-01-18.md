# effect: 閉曲線メタボール接続（metaball connect）実装チェックリスト（2026-01-18）

目的: 複数の閉曲線（ポリライン）を「メタボール的」に滑らかに接続・統合し、出力を閉曲線（輪郭）として返す新規 effect を追加する。

想定ユースケース:

- 離れたリング同士を“生物っぽく”つなぐ（距離が近いほど接続が太くなる/繋がりやすくなる）
- 既存の `buffer` や単純 union では出しづらい「柔らかいブレンド輪郭」を作る

背景:

- Grafix は線（ポリライン）を基本にしているが、「閉曲線の塊」を扱う場面（マスク、輪郭、シルエット）も多い。
- `buffer` はオフセット輪郭生成には強いが、閉曲線同士を“有機的に”接続する表現は別途欲しい。

方針（案）:

- 入力ジオメトリ内の「閉曲線ポリライン列」を 2D 平面に射影し、面（領域）として統合 → “メタボール的な接続”を行った後、輪郭をポリラインとして返す。
- effect モジュールは他 effect へ依存しない（`src/grafix/core/effects/AGENTS.md` に従う）。共通ユーティリティは `src/grafix/core/effects/util.py` のみ利用可。

非目的:

- 3D（非平面）な閉曲線群の“正しい”メタボール（今回は平面前提で no-op）
- すべての自己交差・不正ポリゴンを救う（過度に防御的な実装はしない）
- “点メタボール”の汎用実装（今回は閉曲線同士の接続に集中）

## 0) 事前に決める（あなたの確認が必要）

- [x] effect 名（どれにする？）；案 A を採用
  - 案 A: `metaball`（短い、覚えやすい）
  - 案 B: `metaball_connect`（用途が明確、長い）
  - 案 C: `blob` / `soft_union`（メタボール語を避ける）
- [x] 入力の取り方；案 A を採用（face 数は事前に決めない）
  - 案 A: `n_inputs=1`。`inputs[0]` 内の **全ての face（閉曲線ポリライン）** を検知して対象にする（数は事前に決めない）
    - 補足: 複数 Geometry をまとめて対象にしたい場合は、呼び出し側で `g1 + g2 + ...`（= `concat`）にして 1 入力へ束ねる
  - 案 B: `n_inputs=2`（`inputs[0]` と `inputs[1]` を接続して返す）も同時に対応（将来検討）
- [x] アルゴリズム（どちらで行く？）；案 B を採用
  - 案 A: Shapely による“形態学的 closing”でメタボール風接続（実装が最小で堅い、推奨）
    - 手順: `union(polygons)` → `buffer(+r)` → `buffer(-r)` → exterior 抽出
    - 直感パラメータ: `radius=r`（大きいほど繋がりやすい）
  - 案 B: 距離場/スカラー場 + Marching Squares（よりメタボールっぽいが実装量が増える）
    - 手順: 2D グリッドで場を計算 → 等値線抽出 → ポリライン化
    - 直感パラメータ: `radius` + `threshold` + `grid_pitch`
- [x] 閉曲線判定/自動クローズ；案 A を採用
  - 案 A: 端点距離 `<= auto_close_threshold` なら閉じる（`buffer` と同様の体験）；こちらで（face 定義）
  - 案 B: 完全一致のみ閉曲線扱い（単純だが使いにくい）
- [x] 開曲線の扱い（入力に混ざっていた場合）；案 A を採用
  - 案 A: 無視（閉曲線だけを処理して出力、推奨）
  - 案 B: `keep_original` とは別に、開曲線はそのまま出力へ pass-through
- [x] 出力の扱い；案 B を採用
  - 案 A: exterior（外輪郭）のみ出力（ペンプロ用途で分かりやすい、推奨）
  - 案 B: holes（内側輪郭）も出力（`output="exterior|both"` などで切替）
- [x] 平面性のチェック（非平面のとき）；案 A を採用
  - 案 A: 代表リングで平面へ整列し、z ブレが閾値超なら no-op で元を返す（`clip` と同系）
  - 案 B: チェックなしで強制 2D 化（意図しない潰れが起きやすい）

## 1) 受け入れ条件（完了の定義）

- [x] 2 つの円（別ポリライン）を近づけると、`radius` に応じて 1 つの滑らかな輪郭へ統合される
- [x] 離れている場合は統合されず、複数輪郭のまま出力される（テストで固定）
- [x] `inputs[0]` 内に 3 本以上の閉曲線があっても、全てを検知して処理対象にする（少なくとも落ちない）
- [x] `radius == 0`（または十分小さい）で no-op（入力を返す）
- [x] 入力が空/頂点 0 のときに落ちない
- [x] 平面性チェックにより、非平面入力は no-op（仕様として固定する）
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_metaball.py` が通る
- [x] `PYTHONPATH=src python -m grafix stub` 後に `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py` が通る

## 2) 仕様案（API/パラメータ）

（※ 0) の決定が先）

- effect シグネチャ（案）
  - `metaball(inputs, *, radius=3.0, threshold=1.0, grid_pitch=0.5, auto_close_threshold=1e-3, output="both", keep_original=False)`
- 入力仕様
  - `n_inputs=1`。`inputs[0]` 内の全ポリラインを走査し、「閉曲線になったもの（face）」を全て対象とする
- `radius : float`
  - 接続の“柔らかさ/届く距離” [mm]。大きいほど繋がりやすい。
- `threshold : float`
  - 等値線レベル（大きいほど“溶けにくい/繋がりにくい”）。
- `grid_pitch : float`
  - 距離場を評価する 2D グリッドのピッチ [mm]（小さいほど高精細）。
- `auto_close_threshold : float`
  - 閉曲線扱いの自動クローズ距離 [mm]（端点が近いなら閉じる）。
- `output : str`
  - `"both"`（外周＋穴） / `"exterior"`（外周のみ）
- `keep_original : bool`
  - True のとき、生成結果に加えて元のポリラインも出力に含める。

## 3) 実装設計（アルゴリズム）

### 3.1 前処理（共通）

- [x] `inputs` / `base` の空チェック（空なら空ジオメトリ）
- [x] 代表リング（`>=3` 点のポリライン）を 1 本選ぶ（なければ no-op）
- [x] `util.transform_to_xy_plane` で XY へ整列する回転 `R` と `z_offset` を得る
- [x] base 全頂点を整列し、z ブレが閾値以内かチェック（超えるなら no-op）

### 3.2 閉曲線抽出

- [x] offsets を走査し、各ポリラインを取り出す
- [x] `auto_close_threshold` により閉じる/閉じないを判定（0) の仕様に従う）
- [x] 閉曲線のみ 2D (x,y) を取り出して“リング”として保持

### 3.3 “メタボール的接続”本体（案 B: 距離場 + Marching Squares）

- [x] 処理対象リング群の bbox を求め、評価範囲（margin を含む）とグリッド解像度を決める
- [x] 距離場（スカラー場）をグリッドで評価する
  - [x] 各リングに対して `exp(-d^2/r^2)` を足し合わせる
  - [x] even-odd の inside 項を加え、holes を含む面を表現する
  - [x] 重い部分は `numba.njit` で高速化する
- [x] Marching Squares で等値線レベル `threshold` の線分列を抽出する（5/10 は center decider）
- [x] 線分列をループへ stitch し、外周＋穴として出力する（向き分類はしない）
- [x] 2D -> 3D（z=0）へ戻し、`util.transform_back` で元座標系へ復元

### 3.4 出力（RealizedGeometry）

- [x] 複数輪郭（複数ポリライン）を `coords`/`offsets` へまとめる
- [x] `keep_original` の扱いを仕様どおりに実装

## 4) 変更箇所（ファイル単位）

（※実装フェーズに入ってから着手）

- [x] `src/grafix/core/effects/metaball.py`（新規）
  - [x] `ParamMeta` 定義
  - [x] `@effect(meta=..., n_inputs=1)` の追加
  - [x] 平面整列、距離場評価、Marching Squares、輪郭抽出、復元
  - [x] Numba による距離場評価の高速化（`njit(cache=True)`）
- [x] `src/grafix/api/effects.py`
  - [x] effect 実装モジュール import を 1 行追加（レジストリ登録のため）
- [x] `tests/core/effects/test_metaball.py`（新規）
  - [x] 2 円が接続される/されない境界のテスト
  - [x] `radius==0` の no-op
  - [x] 非平面入力の no-op
  - [x] holes を出力する（ドーナツ形状）
- [x] スタブ再生成（手編集しない）
  - [x] `PYTHONPATH=src python -m grafix stub`

## 5) 実行コマンド（ローカル確認）

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_metaball.py`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] `mypy src/grafix`（任意）
- [x] `ruff check src/grafix/core/effects/metaball.py tests/core/effects/test_metaball.py`（任意）

## 追加で事前確認したほうがいい点（気づいたら追記）

- [ ] `radius` の UI レンジ（例: `0..50mm`）はどれくらいが体感に合うか
- [ ] 入出力が複数リングになる場合の“順序”は気にするか（基本は気にしない）
- [ ] holes を出す場合、ペンプロでの塗り順（外 → 内など）を規定するか（今回は規定しない、必要なら別 effect）
