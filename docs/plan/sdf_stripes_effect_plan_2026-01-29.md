# SDF を取り入れた新規 effect アイデア集（案）

作成日: 2026-01-29

## 前提（共通）

- **Signed Distance Function（SDF）** は、平面上で `SDF(x,y)=境界までの最短距離` を表すスカラー場（内側負 / 外側正）。
- Grafix 的には「閉曲線群（外周＋穴）」を入力に、SDF を介して **新しい線（ポリライン列）を生成**したり、線密度/方向を **SDF 由来の場で制御**する effect が相性が良い。
- ここでは “アイデア段階” として、API 形・パラメータ候補・得られる見た目の方向性だけを列挙する（実装手順・テスト詳細は別途）。

## アイデア A: `E.sdf_stripes(mask)`（SDF等高線彫刻 / Isocontour Engraving）

閉曲線（複数形状可）から SDF を作り、`SDF = k*spacing + phase` の等値線を複数本抽出してポリライン化する。見た目は「オフセット輪郭の束」で、地形図 / 木版画 / 彫金のような輪郭起点の“塗り”向き。

SDF 由来だと、自己交差しやすい形でも「距離場」としては連続になりやすく、さらにノイズや smooth min/max で“溶ける”輪郭にも寄せられる。

### 入出力
- 入力: `mask`（平面上の閉曲線群。開曲線は無視）
- 出力: 等値線（基本は閉ループ）

### パラメータ案
- `spacing`（間隔）, `phase`（ずらし）, `max_dist`（生成範囲）, `mode`（inside/outside/both）
- `smooth_k`（スムーズ度）, `level_keep`（レベルごとの間引き率）
- `gamma`（距離の非線形）, `grid_pitch`（解像度）, `keep_original`

## アイデア B: `E.sdf_normals(mask)`（境界法線ストローク）

SDF の勾配（境界の法線方向）を利用して、境界から内側（または外側）へ向かうストローク群を生成する。毛並み / 彫り跡 / 版画の“掻き”のようなテクスチャを作りやすい。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開ポリライン（境界発のストロークが中心）

### パラメータ案
- `seed_spacing`（境界上の種密度）, `length`（長さ）, `direction`（in/out/both）
- `jitter`（ゆらぎ）, `curl`（流れの回転量）, `min_sep`（密集抑制）

## アイデア C: `E.sdf_tangent_flow(mask)`（等距離線に沿うフロー線）

等距離線そのもの（閉ループ）ではなく、SDF 由来の“接線方向の場”に沿って、長い連続線（開曲線）を走らせる。輪郭をなぞり続ける帯状の流れや、渦っぽい回り込みを作れる。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開ポリライン（ストリームライン）

### パラメータ案
- `seed_count/seed_spacing`（種の置き方）, `steps/step_size`（長さ）
- `avoid_boundary`（境界への当たり方）, `noise`（揺れ）, `max_turn`（急旋回の抑制）

## アイデア D: `E.sdf_attract(base, mask)`（SDF 吸着/反発ディスプレイス）

既存の線（`base`）を、マスク境界へ吸着させたり、逆に境界から離すように変形する。輪郭の“磁力”で、文字・ハッチ・流線を形に沿わせる用途。

### 入出力
- 入力: `base`（任意の線）, `mask`（閉曲線群）
- 出力: 変形後の `base`（開曲線中心）

### パラメータ案
- `strength`（強さ）, `falloff`（距離減衰）, `bias`（オフセット）
- `snap_band`（効く距離範囲）, `preserve_length`（伸び縮み抑制）

## アイデア E: `E.sdf_boolean(a, b)`（SDF ブーリアン/スムース合成）

2 つの閉曲線群を SDF で合成し、union/intersection/difference を **滑らかに**つなぐ（スムース union など）。プロッタ向けには「輪郭を 1 本の有機形状にまとめる」効果が大きい。

### 入出力
- 入力: `a`（閉曲線群）, `b`（閉曲線群）
- 出力: 合成後の閉曲線群（輪郭）

### パラメータ案
- `op`（union/intersection/difference/smooth_union/...）
- `k`（スムース半径）, `grid_pitch`（解像度）, `keep_original`

## アイデア F: `E.sdf_band_lines(mask)`（境界帯域の線化）

`|SDF|` がある範囲に入る“帯”だけに線を発生させる。輪郭の周りだけを濃く描き、中心は空ける、あるいは外側だけを飾る、といった使い方がしやすい。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開/閉ポリライン（帯の表現次第）

### パラメータ案
- `band_inner/band_outer`（距離帯）, `style`（contour/flow/hatch など）
- `density`（本数）, `phase`（ずらし）, `keep_original`

## アイデア G: `E.sdf_gradient_hatching(mask)`（勾配整列ハッチング / Gradient-Aligned Hatching）

SDF の勾配 `∇d` が「境界法線方向」を持つことを利用し、ハッチ線の方向を「勾配に平行（法線方向）」「勾配に直交（等高線方向）」に揃える。さらに `|d|` に応じて密度を変えたり、特定の距離帯だけ強調することで、彫金っぽい陰影が作れる。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開ポリライン（ハッチ線）

### パラメータ案
- `align`（"parallel" | "perpendicular"）, `spacing`（基本間隔）, `band`（距離帯）
- `density_curve`（|d|→密度）, `seed`（乱数）, `min_sep`（線同士の最小間隔）

## アイデア H: `E.sdf_band_mask(base, mask)`（距離帯マスキング / Signed Band Mask / Soft Clip）

SDF の符号と距離帯条件（例: `a < d < b`）で、入力レイヤの線分を「境界からの距離」で切り出す。通常のクリップ（二値）より、版画的な「縁だけ残す」「縁から一定幅は消す」「境界に向かってフェード」がやりやすい。

### 入出力
- 入力: `base`（任意の線）, `mask`（閉曲線群）
- 出力: 切り出し後の `base`（開曲線中心）

### パラメータ案
- `a/b`（距離帯）, `mode`（keep/drop/invert）
- `fade`（距離→残す確率）, `seed`（乱数）, `min_seg_len`（短片の除去）

## アイデア I: `E.sdf_lens(base, lens)`（SDF レンズ / Refraction / Magnifier）

レンズ形状の SDF を用意し、`d<0`（レンズ内）だけ座標変換をかけ、外側は素通しにする。距離に応じたスケール・回転・シアー・渦（swirl）などで、境界付近だけ歪む“光学っぽさ”を作れる。

### 入出力
- 入力: `base`（任意の線）, `lens`（閉曲線群）
- 出力: 変形後の `base`

### パラメータ案
- `kind`（scale/rotate/shear/swirl/...）, `strength`（強さ）, `falloff`（距離減衰）
- `inside_only`（内側のみ適用）, `keep_original`

## アイデア J: `E.sdf_smooth_union_bridges(geom)`（メタボール接続 / Smooth Union Bridges）

複数形状の SDF を smooth min（スムース union）で合成すると、近接した形状が“ぷにっと”繋がる連結部（ブリッジ）を自動で生成できる。そこから等高線を抜くと、有機的なブリッジやチューブ状の線が得られる。

### 入出力
- 入力: `geom`（複数形状。閉曲線中心、点/線を許すなら“太さ付き”扱いも）
- 出力: 閉曲線群（輪郭）または等高線群（複数レベル）

### パラメータ案
- `k`（スムース半径）, `select`（近いものだけ合成する等の選別）
- `threshold/spacing`（輪郭/等高線の出し方）, `grid_pitch`

## アイデア K: `E.sdf_flowlines(mask)`（距離場アドベクション / Distance-Field Flowline）

距離場から作った方向場（例: `∇d` を 90 度回した等高線方向、または `∇d` 自体）に沿って、多数のシード点を積分して流線（streamlines）を描く。シード密度を `|d|` で変えたり、符号で流れを反転させると、形状の周りに“流体の回り込み”のような線が生成できる。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開ポリライン（流線）

### パラメータ案
- `field`（tangent/normal/...）, `seed_density`（|d| 依存も可）, `steps/step_size`
- `min_sep`（Poisson disk 的な最小間隔）, `noise`（揺れ）, `keep_original`

## アイデア L: `E.sdf_skeleton(mask)`（SDF スケルトン／芯線抽出 / Ridge/Skeleton Sketch）

距離場の“リッジ”（境界から等距離になる中心線）を近似して線として出す。形状の骨格だけが描けるので、下絵として他の effect（ハッチ、等高線、オフセット等）に繋ぐと階層感が出る。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開ポリライン（芯線）

### パラメータ案
- `grid_pitch`（解像度）, `cleanup`（短片除去/平滑）, `min_length`
- `keep_original`

## アイデア M: `E.sdf_shadow_hatch(mask)`（シャドウキャスト線 / 2D Ray-marched Shadow）

SDF は 2D レイマーチに使えるので、ある光方向に対して“遮蔽される領域”を推定し、影部分だけにハッチ（または等高線）を入れる。線画の陰影として強力で、入力形状が複雑でも距離場さえあれば動く。

### 入出力
- 入力: `mask`（閉曲線群）
- 出力: 開ポリライン（影のハッチ/線）

### パラメータ案
- `light_angle`（光方向）, `shadow_steps`（影判定の粗さ）, `softness`（滑らかさ）
- `hatch_angle/spacing`（影の線密度）, `band`（影を出す距離帯）, `keep_original`

## 補足メモ（共通の設計観点）

- SDF の扱いは大きく「(1) callable な連続関数」「(2) グリッドにキャッシュしてサンプル」の二択になりやすい。
- 任意ポリライン由来の SDF を現実的に回すなら、(2) が素直（`grid_pitch` と、描画範囲外に取る `margin` をパラメータ化すると使い回しが効く）。
- 符号は閉曲線なら point-in-polygon（even-odd）で決められる。開曲線も扱いたい場合は“太さ `t` のチューブ”として `d = distance_to_polyline - t` の形にして擬似的に符号付きにする手がある。

## 次に決めたいこと

- まずどれを “組み込み effect” として実装するか（1 つに絞る）
- まず “線の生成” として映えやすいのは `E.sdf_stripes` / `E.sdf_gradient_hatching` / `E.sdf_flowlines` の系
- 入出力を `n_inputs=1` に寄せるか、`base+mask` の 2 入力を許すか
- 既存 effect（`E.fill`, `E.metaball`, `E.buffer`, `E.clip`）との差別化ポイントをどれに置くか
