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

- [ ] effect 名（どれにする？）；A で
  - 案 A: `metaball`（短い、覚えやすい）
  - 案 B: `metaball_connect`（用途が明確、長い）
  - 案 C: `blob` / `soft_union`（メタボール語を避ける）
- [ ] 入力の取り方；案 A で（face 数は事前に決めない）
  - 案 A: `n_inputs=1`。`inputs[0]` 内の **全ての face（閉曲線ポリライン）** を検知して対象にする（数は事前に決めない）
    - 補足: 複数 Geometry をまとめて対象にしたい場合は、呼び出し側で `g1 + g2 + ...`（= `concat`）にして 1 入力へ束ねる
  - 案 B: `n_inputs=2`（`inputs[0]` と `inputs[1]` を接続して返す）も同時に対応（将来検討）
- [ ] アルゴリズム（どちらで行く？）；案 B で
  - 案 A: Shapely による“形態学的 closing”でメタボール風接続（実装が最小で堅い、推奨）
    - 手順: `union(polygons)` → `buffer(+r)` → `buffer(-r)` → exterior 抽出
    - 直感パラメータ: `radius=r`（大きいほど繋がりやすい）
  - 案 B: 距離場/スカラー場 + Marching Squares（よりメタボールっぽいが実装量が増える）
    - 手順: 2D グリッドで場を計算 → 等値線抽出 → ポリライン化
    - 直感パラメータ: `radius` + `threshold` + `grid_pitch`
- [ ] 閉曲線判定/自動クローズ；案 A で
  - 案 A: 端点距離 `<= auto_close_threshold` なら閉じる（`buffer` と同様の体験）；こちらで（face 定義）
  - 案 B: 完全一致のみ閉曲線扱い（単純だが使いにくい）
- [ ] 開曲線の扱い（入力に混ざっていた場合）；案 A で
  - 案 A: 無視（閉曲線だけを処理して出力、推奨）
  - 案 B: `keep_original` とは別に、開曲線はそのまま出力へ pass-through
- [ ] 出力の扱い；案 B で
  - 案 A: exterior（外輪郭）のみ出力（ペンプロ用途で分かりやすい、推奨）
  - 案 B: holes（内側輪郭）も出力（`output="exterior|both"` などで切替）
- [ ] 平面性のチェック（非平面のとき）；案 A で
  - 案 A: 代表リングで平面へ整列し、z ブレが閾値超なら no-op で元を返す（`clip` と同系）
  - 案 B: チェックなしで強制 2D 化（意図しない潰れが起きやすい）

## 1) 受け入れ条件（完了の定義）

- [ ] 2 つの円（別ポリライン）を近づけると、`radius` に応じて 1 つの滑らかな輪郭へ統合される
- [ ] 離れている場合は統合されず、複数輪郭のまま出力される（または no-op。仕様に合わせてテストで固定）
- [ ] `inputs[0]` 内に 3 本以上の閉曲線があっても、全てを検知して処理対象にする（少なくとも落ちない）
- [ ] `radius == 0`（または十分小さい）で no-op（入力を返す）
- [ ] 入力が空/頂点 0 のときに落ちない
- [ ] 平面性チェックにより、非平面入力は no-op（仕様として固定する）
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_<effect>.py` が通る
- [ ] `python -m tools.gen_g_stubs` 後に `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py` が通る

## 2) 仕様案（API/パラメータ）

（※ 0) の決定が先）

- effect シグネチャ（案）
  - `metaball(inputs, *, radius=5.0, quad_segs=12, auto_close_threshold=1e-3, keep_original=False, output="exterior")`
- 入力仕様
  - `n_inputs=1`。`inputs[0]` 内の全ポリラインを走査し、「閉曲線になったもの（face）」を全て対象とする
- `radius : float`
  - 接続の“柔らかさ/届く距離” [mm]。大きいほど繋がりやすい。
- `quad_segs : int`
  - Shapely `buffer` の円弧近似分割数（`buffer` と揃える）。
- `auto_close_threshold : float`
  - 閉曲線扱いの自動クローズ距離 [mm]（端点が近いなら閉じる）。
- `output : str`
  - `"exterior"` / `"both"`（holes も含める）など（0) で決める）。
- `keep_original : bool`
  - True のとき、生成結果に加えて元のポリラインも出力に含める。

## 3) 実装設計（アルゴリズム）

### 3.1 前処理（共通）

- [ ] `inputs` / `base` の空チェック（空なら空ジオメトリ）
- [ ] 代表リング（`>=3` 点のポリライン）を 1 本選ぶ（なければ no-op）
- [ ] `util.transform_to_xy_plane` で XY へ整列する回転 `R` と `z_offset` を得る
- [ ] base 全頂点を整列し、z ブレが閾値以内かチェック（超えるなら no-op）

### 3.2 閉曲線抽出

- [ ] offsets を走査し、各ポリラインを取り出す
- [ ] `auto_close_threshold` により閉じる/閉じないを判定（0) の仕様に従う）
- [ ] 閉曲線のみ 2D (x,y) を取り出して“リング”として保持

### 3.3 “メタボール的接続”本体（案 A: Shapely closing）

- [ ] 各リングを Shapely `Polygon` へ変換してリスト化
- [ ] `unary_union` で統合
- [ ] closing:
  - [ ] `dilated = geom.buffer(+radius, join_style="round", quad_segs=quad_segs)`
  - [ ] `closed = dilated.buffer(-radius, join_style="round", quad_segs=quad_segs)`
- [ ] `closed` から輪郭（exterior / holes）座標列を抽出
- [ ] 2D -> 3D（z=0）へ戻し、`util.transform_back` で元座標系へ復元

（案 B: Marching Squares を採用する場合は、この節を差し替え）

### 3.4 出力（RealizedGeometry）

- [ ] 複数輪郭（複数ポリライン）を `coords`/`offsets` へまとめる
- [ ] `keep_original` の扱いを仕様どおりに実装

## 4) 変更箇所（ファイル単位）

（※実装フェーズに入ってから着手）

- [ ] `src/grafix/core/effects/<effect_name>.py`（新規）
  - [ ] `ParamMeta` 定義
  - [ ] `@effect(meta=..., n_inputs=...)` の追加
  - [ ] 平面整列、Shapely closing、輪郭抽出、復元
- [ ] `src/grafix/api/effects.py`
  - [ ] effect 実装モジュール import を 1 行追加（レジストリ登録のため）
- [ ] `tests/core/effects/test_<effect_name>.py`（新規）
  - [ ] 2 円が接続される/されない境界のテスト
  - [ ] `radius==0` の no-op
  - [ ] 非平面入力の no-op
- [ ] スタブ再生成（手編集しない）
  - [ ] `python -m tools.gen_g_stubs`

## 5) 実行コマンド（ローカル確認）

- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_<effect_name>.py`
- [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] `mypy src/grafix`（任意）
- [ ] `ruff check .`（任意）

## 追加で事前確認したほうがいい点（気づいたら追記）

- [ ] `radius` の UI レンジ（例: `0..50mm`）はどれくらいが体感に合うか
- [ ] 入出力が複数リングになる場合の“順序”は気にするか（基本は気にしない）
- [ ] holes を出す場合、ペンプロでの塗り順（外 → 内など）を規定するか（今回は規定しない、必要なら別 effect）
