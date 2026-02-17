# Primitive: `G.laplace_field_grid(...)`（共形写像ベースの直交ラプラス格子）追加計画

作成日: 2026-02-17  
ステータス: 提案（未実装）  
参考: `l.md`（Primitive「LaplaceFieldGrid」指示書）

## 背景

- `l.md` の指示書は「2D ラプラス場（調和関数）の共役座標系（等ポテンシャル線 / 流線）＝直交網」を、ポリライン群として生成する primitive を追加することを求めている。
- Grafix の primitive は `(coords, offsets)`（複数ポリライン）で返す前提のため、指示書の「lines/boundaries」を **同一ジオメトリ内の複数ポリライン**として表現する方針に寄せる。

## 目的（ゴール）

- 新規 primitive `laplace_field_grid` を追加し、共形写像ベースで直交格子を生成できるようにする（Phase 1）。
- `preset` により少なくとも次の 3 パターンを提供する。
  - `cylinder_uniform`: 円柱まわりの一様場（逆写像で外部解を選択、円内部を除外）
  - `mobius`: モビウス変換による歪み（直交性保持）
  - `exp`: 指数写像（放射状/ログ極座標っぽい網）
- `cylinder_uniform` で、円内部に線が侵入しない（`gap` で余白）。
- 破綻時に “全滅” しにくい（NaN/Inf で壊れない、最悪でも線が荒れる程度）。

## 非目的（やらない）

- Phase 2（数値ラプラスソルバ/任意境界/複数障害物）の実装。
- 1 本ごとの stroke/style の分離（Grafix の単一 Geometry 出力の範囲に留める）。
- 互換ラッパーやシムの追加（必要なら破壊的に整理する方針を維持）。

## 追加/変更するもの（予定）

- `src/grafix/core/primitives/laplace_field_grid.py`（新規）
- `src/grafix/core/builtins.py`（`_BUILTIN_PRIMITIVE_MODULES` へ追加）
- `tests/core/primitives/test_laplace_field_grid.py`（新規）
- `src/grafix/api/__init__.pyi`（`PYTHONPATH=src python -m grafix stub` で更新）
- （任意）`sketch/` に目視確認用スケッチを追加

## API 案（primitive 名/引数）

- op 名: `laplace_field_grid`（Grafix の既存 primitive 名に合わせて snake_case）
- 共通引数（基本）
  - `preset: str`（`"cylinder_uniform" | "mobius" | "exp"`）
  - `u_min/u_max, v_min/v_max: float`（W=u+iv 平面の範囲）
  - `n_u/n_v: int`（縦線/横線の本数）
  - `samples: int`（1 本の線のサンプル点数）
  - `center: tuple[float,float,float]`, `scale: float`（他 primitive と同様の後段変換）
  - `rotate: float`（deg、後段回転。指示書の `angle(rad)` は Grafix 流儀に寄せる）
- `cylinder_uniform` 専用
  - `a: float`, `U: float`, `gap: float`
  - `draw_boundary: bool`, `boundary_samples: int`（円境界の追加描画）
- `mobius` 専用
  - `alpha/beta/gamma/delta` は **complex を直接は GUI に載せづらい**ため、初期案は `*_re/*_im` の 8 float を採用
- `exp` 専用
  - `k` も同様に `k_re/k_im` の 2 float を採用
- `clip`（任意）
  - 指示書に合わせて矩形クリップを提供したいが、GUI 露出は後回しにして
    `clip_rect: tuple[float,float,float,float] | None`（xmin, xmax, ymin, ymax）の形でまず実装する案

## 実装方針（Phase 1）

### 1) 直交格子の生成（W 平面）

- `u=const` 線: `u = linspace(u_min,u_max,n_u)`、`v` を `linspace(v_min,v_max,samples)` で走査
- `v=const` 線: `v = linspace(v_min,v_max,n_v)`、`u` を同様に走査
- 各線は `np.ndarray (samples,)` の複素数 `W` として保持し、写像後に XY へ落とす

### 2) 写像関数の分離

- 内部関数として `map_w_to_z(W: np.ndarray, *, preset: str, params: ...) -> np.ndarray` を用意する
- `preset` switch はここに閉じ込め、外側は「格子生成→写像→マスク分割→pack」に統一する

### 3) `preset` ごとの写像

- `cylinder_uniform`
  - `w = W / U`
  - `z^2 - w z + a^2 = 0` の 2 根から **|z| が大きい方**（外部解）を選ぶ
  - principal branch の `sqrt` を使用し、ねじれは「範囲/密度調整」で回避（指示書に従う）
  - mask: `abs(z) >= a * (1 + gap)`
  - boundary: 半径 `a` の円ポリラインを追加（`draw_boundary=True` のとき）
- `mobius`
  - `z = (αW + β) / (γW + δ)`（係数は re/im から複素数へ復元）
  - `αδ-βγ ≈ 0` の場合は例外（ValueError）で早期に気付けるようにする
- `exp`
  - `z = exp(k W)`（k は re/im から複素数へ復元）

### 4) マスク分割（線を止める）

- `mask` が True の連続区間を抽出してポリラインへ分割する
  - 2 点未満の区間は捨てる
- `cylinder_uniform` 以外は mask を全 True とし、分割は no-op

### 5) 後段変換 + pack

- `z`（complex）→ `coords`（float32, shape `(N,3)`）へ変換（z=0）
- `rotate/scale/center` を最終段で適用（rotate は origin 回転→平行移動）
- 分割後の polyline リストを `(coords, offsets)` に pack して返す（既存 primitive の `_lines_to_realized` と同型）

### 6) クリップ（任意）

- `clip_rect` を受けた場合のみ適用（Phase 1 の必須にするかは要確認）
- 実装候補:
  - “外側点を落として分割する” の簡易版（境界での交点補間はしない）
  - もしくは各セグメントを AABB でクリップして交点を補間（品質高いが実装量増）

## テスト方針（最小）

- `test_laplace_field_grid.py`
  - 正常系: `preset` 3 種で例外なく `(coords, offsets)` が返る
  - `coords` に NaN/Inf が含まれない
  - `offsets` が単調非減少、末尾が `coords.shape[0]`
  - `samples < 2` のような明確な不正値は ValueError
  - `cylinder_uniform`（`draw_boundary=False`）で `abs(z) >= a*(1+gap)` を満たす
- 目視（sketch）
  - 円近傍で直交性が破綻しないこと、`preset` 切替で作風が変わることを確認

## 実装タスク（チェックリスト）

### 0) 仕様確定（この計画の合意）

- [ ] primitive 名を `laplace_field_grid` で確定（別名希望があれば反映）
- [ ] `mobius/exp` の複素パラメータ表現を `*_re/*_im` で行くか決める
- [ ] `clip_rect` を Phase 1 の必須にするか（簡易/厳密）を決める

### 1) primitive 追加

- [ ] `src/grafix/core/primitives/laplace_field_grid.py` を追加（meta + ui_visible を含む）
- [ ] 共通骨格（格子生成 → 写像 → mask 分割 → pack）を実装
- [ ] `cylinder_uniform` を実装（逆写像 + 外部解選択 + gap mask + 境界円）
- [ ] `mobius` を実装
- [ ] `exp` を実装
- [ ] 後段変換（rotate/scale/center）を適用
- [ ] `src/grafix/core/builtins.py` に primitive module を登録

### 2) テスト/検証

- [ ] `tests/core/primitives/test_laplace_field_grid.py` を追加
- [ ] `PYTHONPATH=src pytest -q tests/core/primitives/test_laplace_field_grid.py`

### 3) スタブ更新

- [ ] `PYTHONPATH=src python -m grafix stub`（`src/grafix/api/__init__.pyi` 更新）

## 受け入れ条件（DoD）

- [ ] `G.laplace_field_grid(preset="cylinder_uniform", ...)` が例外なく動く
- [ ] 円内部に線が侵入しない（`gap` に応じた余白）
- [ ] `preset` を `mobius/exp` に切り替えると明確に異なるパターンが得られる
- [ ] 出力に NaN/Inf が含まれない（少なくともデフォルト範囲/密度で）

## 追加で決めること（実装前の最終確認）

- `rotate` を primitive 引数として持つか、effect（`E.rotate`）に寄せるか
- 境界円を同一ジオメトリに混ぜるか（`draw_boundary`）/ 目視スケッチへ寄せるか
- `u_min/u_max` 等の引数名を指示書寄り（`u_range`）に戻すか
