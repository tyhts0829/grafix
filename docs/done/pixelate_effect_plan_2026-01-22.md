# effect: ピクセル化（pixelate）実装チェックリスト（2026-01-22）

目的: 入力ポリラインをグリッド上の「1 ステップ階段」に変換し、出力が必ず水平/垂直セグメントのみになる新規 effect `pixelate` を追加する。

背景:

- `quantize` は頂点をグリッドへスナップするだけなので、連続頂点の x,y が同時に変わると、点と点を結ぶセグメントが斜めのまま残る。
- “ピクセル化”としては「長い斜めを格子 1 ステップごとの階段（頂点増加）にしたい」。

方針（案）:

- `pixelate` は `quantize` を内包する（= 入力頂点を `step` 格子へスナップしてから階段化する）。
- 各入力セグメントを 4-connected（上下左右）格子経路へ展開する（Bresenham をベースに 8-connected の対角移動を 2 手に分解）。
- 出力は頂点数・offsets が変わる（`quantize` とは別 effect として扱う）。
- effect モジュールは他 effect へ依存しない（`src/grafix/core/effects/AGENTS.md` に従う）。共通ユーティリティは `src/grafix/core/effects/util.py` のみ利用可。

非目的:

- 斜め線を残す/アンチエイリアス/滑らか化
- 自己交差解消や「最短経路」の最適化
- 自動のジオメトリ簡略化（不要頂点削除など）

## 0) 事前に決める（あなたの確認が必要）

- [x] effect 名: `pixelate` で確定してよい？；OK
- [x] 期待挙動: 「長い斜めは格子 1 ステップごとの階段（頂点が増える）」を採用
- [x] Z の扱い（提案）
  - [x] 案 A: XY のみ階段化し、z は入力頂点を `step[2]` でスナップした後に線形補間（推奨）；これで
  - [ ] 案 B: XY のみ階段化し、z は入力のまま（スナップなし）
  - [ ] 案 C: 3D も含めて 6-connected（x/y/z のどれか 1 軸だけ動く）で階段化（実装増、将来）
- [x] 対角分解の順序（8-connected の対角移動を 2 手に分けるとき）
  - [x] 案 A: major axis を先に進める（`abs(dx) >= abs(dy)` なら x→y、逆なら y→x、推奨）；これで
  - [ ] 案 B: 常に x→y（スタイル固定）
  - [ ] 案 C: 常に y→x（スタイル固定）
- [x] 出力頂点数の上限ガード
  - [x] 上限値: 案 A: `MAX_TOTAL_VERTICES = 10_000_000`（`subdivide` と同じ） / 案 B: 小さめ（例: 2_000_000）；Aで
  - [x] 超過時の挙動: 案 A: そこで打ち切り（残りポリラインは出さない） / 案 B: no-op で入力を返す / 案 C: 例外；Aで

## 1) 受け入れ条件（完了の定義）

- [x] 出力の各セグメントで `dx==0 or dy==0`（XY で斜めが出ない）
- [x] 各セグメント長は `sx` または `sy` の 1 ステップ（0 長セグメントは許容/要確認）
- [x] `step<=0` を含む場合は no-op（`quantize` と同様）
- [x] 空/頂点 0/ポリライン長 <2 で落ちない
- [x] 負方向（右下/左上）や非等方 step でも期待どおり
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_pixelate.py` が通る
- [x] `PYTHONPATH=src python -m grafix stub` 後、`PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py` が通る

## 2) 仕様案（API/パラメータ）

- effect シグネチャ（案: 最小）
  - `pixelate(inputs, *, step=(1.0, 1.0, 1.0)) -> RealizedGeometry`
- ParamMeta（案）
  - `step`: `kind="vec3"`, `ui_min=0.0`, `ui_max=10.0`（`quantize` と揃える）

## 3) 実装設計（アルゴリズム）

### 3.1 グリッドへのスナップ（内部で実施）

- `sx,sy,sz` を float 化。いずれか `<=0` なら no-op
- `q = coords / step_vec`
- `q_rounded = sign(q) * floor(abs(q) + 0.5)`（half away from zero）
- `ix,iy,iz` を整数格子座標として扱う（以後は整数演算中心）
  - 補足: `quantize` 実装への import 依存はできないため（effects 同士の依存禁止）、同等の丸めロジックは `pixelate.py` 内で実装するか、`effects/util.py` へ共通化して両方から使う（後者は既存 `quantize` の変更を伴う）。

### 3.2 4-connected 階段化（1 セグメント）

入力: `(x0,y0)` → `(x1,y1)` の整数格子。

- Bresenham で 8-connected の点列を生成する（major axis を 1 ずつ進め、必要時に minor も 1 進める）
- 連続点が対角（`x` と `y` が同時に変化）になった場合:
  - 中間点 `p_mid` を 1 個挿入して 2 手に分解（0) の順序仕様に従う）
- 生成点列は「始点・終点を含む」設計にして、ポリライン結合時は重複（前セグメント終点=次セグメント始点）を 1 点にする

### 3.3 ポリライン全体

- offsets を走査し、各ポリラインを独立に処理
- 各ポリライン:
  - 先頭点を追加
  - 連続頂点ペアごとに 3.2 を適用し、生成列の先頭（重複）を除いて append
- 合計頂点数が上限を超えないようにガード（0) の仕様に従う）

### 3.4 出力（RealizedGeometry）

- 生成した coords（float32）と offsets（int32）から `RealizedGeometry` を構築

## 4) 変更箇所（ファイル単位）

（※実装フェーズに入ってから着手）

- [x] `src/grafix/core/effects/pixelate.py`（新規）
  - [x] `pixelate_meta` 定義（`step`）
  - [x] `@effect(meta=...)` で登録
  - [x] スナップ + 階段化 + vertex 上限ガード
- [x] `src/grafix/api/effects.py`
  - [x] import 1 行追加（レジストリ登録）
- [x] `tests/core/effects/test_pixelate.py`（新規）
  - [x] 斜め入力が階段化される（全セグメントで `dx==0 or dy==0` を検証）
  - [x] 非等方 step（例: `(2.0, 0.5, 1.0)`）でも 1 ステップ移動になる
  - [x] 負方向（右下/左上）でも崩れない
  - [x] `step<=0` の no-op
- [x] スタブ再生成（手編集しない）
  - [x] `PYTHONPATH=src python -m grafix stub`

## 5) 実行コマンド（ローカル確認）

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_pixelate.py`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] `ruff check src/grafix/core/effects/pixelate.py tests/core/effects/test_pixelate.py`
- [ ] `mypy src/grafix`（任意）

## 追加で事前確認したほうがいい点（気づいたら追記）

- [ ] 0 長セグメント（同一点連続）を残す/消す（現状は残す想定）
- [ ] “階段の角”の見た目を変えるオプションが欲しいか（今回は入れない想定）
