# フィールド/写像を核にした effect アイデア（非SDF）

作成日: 2026-01-30

対象:

- ベクトル場（flow field / curl noise / 速度場）
- スカラー場（ノイズ / 高さ場 / ポテンシャル場）
- 座標変換（極座標 / 対数螺旋 / 写像）
- 波の干渉 / 周波数合成（sin 和 / moire）

## 前提（共通）

- ここでいう **field（場）** は、平面上の関数として扱う（例: `v(x,y)` / `s(x,y)`）。実装上は「callable」でも「グリッドにキャッシュ」でもよい。
- Grafix 的には「場から **新しい線を生成**」か「既存の線を **場で変形/マスク**」のどちらかに寄せると気持ちよくまとまる。

## 手法: ベクトル場（Vector Field）

ベクトル場 `v(x,y)` を核に、(1) 積分して線を作る、(2) 既存線を流して変形する、(3) 方向と密度を統一する、の 3 系が強い。

### アイデア A: `E.field_flowlines(field)`（ストリームライン生成）

- ねらい: 形状に“風”や“水流”が通っているような長い連続線を生成する。
- 入出力: 入力=`field`（＋任意で `mask`/範囲）, 出力=開ポリライン（流線）
- パラメータ案: `seed_spacing/seed_count`, `steps`, `step_size`, `min_sep`, `max_turn`, `jitter`, `clip`
- メモ: `min_sep` を入れると「束にならない」見た目が作りやすい（streamline packing）。

### アイデア B: `E.field_advect(base, field)`（アドベクト変形）

- ねらい: 既存の線（文字、等間隔ハッチ、格子）を“流して”質感だけを付ける。
- 入出力: 入力=`base`（任意の線）, 出力=変形後の `base`
- パラメータ案: `strength`, `steps`, `step_size`, `friction`, `clamp`, `anchor`（端点固定）
- メモ: 何度も小さく流すと破綻が少なく、版画っぽい歪みになる。

### アイデア C: `E.field_rake(field)`（短冊ストローク群 / Hair Comb）

- ねらい: ベクトル場に揃った短いストロークを大量に打ち、毛並み/彫り跡/ベルベット感を作る。
- 入出力: 入力=`field`（＋任意で `mask`）, 出力=開ポリライン（短い線分の集合）
- パラメータ案: `spacing`, `length`, `jitter`, `taper`（先細り感）, `min_sep`, `seed`
- メモ: `length` を場の大きさ `|v|` に比例させると、速度の陰影が出る。

### アイデア D: `E.field_dashes(base, field)`（場に同期するダッシュ/点線）

- ねらい: 線の進行方向や速度に応じて「点線のリズム」を変え、機械っぽい表情を付ける。
- 入出力: 入力=`base`, `field`, 出力=点線化された `base`（開ポリライン）
- パラメータ案: `dash_len`, `gap_len`, `phase`, `speed_to_len`（|v|→長さ）, `align`（tangent/field）
- メモ: `phase` を位置依存にすると、モアレ風の“揺れ”が出せる。

### アイデア E: `E.field_crosshatch(field)`（二層の場整列クロスハッチ）

- ねらい: 1 層目= `v` 方向、2 層目= `v` に直交、でクロスハッチの“秩序”を作る。
- 入出力: 入力=`field`（＋任意で `mask`）, 出力=開ポリライン（2 レイヤ相当）
- パラメータ案: `spacing_a`, `spacing_b`, `mix`（比率）, `jitter`, `clip`, `seed`
- メモ: 直交方向は `v` を 90 度回した `v_perp` でよい。2 層の相互干渉が絵になる。

## 手法: スカラー場（Scalar Field）

スカラー場 `s(x,y)` は「等値線」「帯域」「勾配（∇s）」「リッジ/谷」だけで大量に派生できる。SDF の一般化として扱える。

### アイデア A: `E.scalar_isocontours(field)`（等高線/等値線）

- ねらい: “地図/地形”の言語で形を描く。密度とレベル選びだけで強い。
- 入出力: 入力=`field`（＋任意で範囲）, 出力=閉/開ポリライン（等値線）
- パラメータ案: `levels`（配列/間隔）, `grid_pitch`, `smooth`, `cleanup_min_len`
- メモ: 既存の `E.isocontour` の「SDF 以外版」としても使える。

### アイデア B: `E.scalar_band_hatch(field)`（帯域ハッチ / Band-Limited Hatching）

- ねらい: `a < s < b` の“層”だけをハッチで埋め、層状の陰影を作る。
- 入出力: 入力=`field`, 出力=開ポリライン（ハッチ線）
- パラメータ案: `bands`（複数帯）, `spacing`, `angle`（固定 or 勾配整列）, `fade`, `seed`
- メモ: 帯域ごとに角度を変えると、版画のレイヤ感が出る。

### アイデア C: `E.scalar_ridges(field)`（リッジ/谷線の抽出）

- ねらい: “山の稜線”や“しわ”だけを抜いて、情報量の高い線画にする。
- 入出力: 入力=`field`, 出力=開ポリライン（リッジ/バレー）
- パラメータ案: `kind`（ridge/valley/both）, `grid_pitch`, `threshold`, `cleanup`
- メモ: リッジは「勾配が弱いのに曲率が強い場所」なので、抽出は荒くてもそれっぽく見える。

### アイデア D: `E.scalar_gradient_warp(base, field)`（勾配ワープ）

- ねらい: 既存線を `∇s`（または直交方向）に沿って押し出し、地形に沿った歪みを作る。
- 入出力: 入力=`base`, `field`, 出力=変形後の `base`
- パラメータ案: `strength`, `steps`, `step_size`, `dir`（grad/perp）, `clamp`, `anchor`
- メモ: `strength` を `s` の値で変えると、中心だけ強く歪む等ができる。

### アイデア E: `E.scalar_descent_lines(field)`（勾配降下/上昇ライン）

- ねらい: 等高線ではなく、山頂→谷へ落ちる“水系”のような線を作る。
- 入出力: 入力=`field`（＋任意で `mask`）, 出力=開ポリライン（降下線）
- パラメータ案: `seed_spacing`, `steps`, `step_size`, `mode`（descent/ascent）, `min_sep`
- メモ: `min_sep` と `seed_spacing` だけで絵の密度が決まるので、調整が簡単。

## 手法: 座標変換（Coordinate Mapping）

座標の写像 `p -> f(p)` を核に、既存線を“別の幾何”に移す。効果が一撃で出るので、軽い変換でも強い。

### アイデア A: `E.map_polar(base, center)`（極座標マップ）

- ねらい: 直線を放射状に、格子を円環に変換して「円形の世界」を作る。
- 入出力: 入力=`base`, 出力=変換後の `base`
- パラメータ案: `center`, `r_scale`, `theta_scale`, `wrap`（角の折返し/連続化）
- メモ: 変換の後に `E.clip`/`E.trim` を掛けると収まりが良い。

### アイデア B: `E.map_log_spiral(base, center)`（対数螺旋/回転スケール）

- ねらい: “吸い込まれる/広がる”感じを持つ、螺旋的な歪みを与える。
- 入出力: 入力=`base`, 出力=変換後の `base`
- パラメータ案: `center`, `twist`, `radial_gain`, `falloff`
- メモ: スケールと回転が距離で連動するだけで、素材が急に有機っぽくなる。

### アイデア C: `E.map_circle_inversion(base, center, radius)`（円反転）

- ねらい: 近傍が遠方へ“飛ぶ”写像で、奇妙な伸び/絡みを作る。
- 入出力: 入力=`base`, 出力=変換後の `base`
- パラメータ案: `center`, `radius`, `clamp_far`, `inside_only`
- メモ: 極（中心付近）が暴れるので `clamp_far` があると扱いやすい。

### アイデア D: `E.map_kaleidoscope(base, center)`（万華鏡 / 角度折返し）

- ねらい: 1 つの線素材を対称回転で増殖し、短時間で“密な構図”を作る。
- 入出力: 入力=`base`, 出力=対称複製された `base`
- パラメータ案: `center`, `n`（分割数）, `mirror`（鏡像の有無）, `phase`
- メモ: 既存の `E.mirror` 系と違い、角度方向の折返しを核にする。

### アイデア E: `E.map_blended_lenses(base, lenses)`（複数レンズのブレンド写像）

- ねらい: 局所的な写像（レンズ）を複数置き、空間に“歪みの島”を点在させる。
- 入出力: 入力=`base`, 出力=変換後の `base`
- パラメータ案: `lenses`（中心/半径/強度/種類）, `blend`（加算/最大/滑らか）
- メモ: `lens` は「写像」なので、スカラー場で重みを付けて混ぜると綺麗に繋がる。

## 手法: 波の干渉 / 周波数合成（Interference / Moire）

単純な周期関数の合成でも、輪郭化（等値線）や帯域抽出でプロッタ向けの線にできる。視覚的な“うねり”が強い核。

### アイデア A: `E.interference_contours()`（干渉場の等値線）

- ねらい: `s=sin(k1·p)+sin(k2·p)` のような場から、等値線だけを抜いて模様化する。
- 入出力: 入力=（内部で生成する `field`）, 出力=閉/開ポリライン（等値線）
- パラメータ案: `k1`, `k2`, `phase1`, `phase2`, `levels`, `grid_pitch`
- メモ: `k` を近い値にすると大きいビート（モアレ）になる。

### アイデア B: `E.moire_hatch(mask=None)`（二重ハッチのビート）

- ねらい: 2 つのハッチ層（角度/間隔が僅かに違う）を重ね、干渉縞を“線として”出す。
- 入出力: 入力=任意で `mask`, 出力=開ポリライン（2 層＋抽出版）
- パラメータ案: `angle_a`, `angle_b`, `spacing_a`, `spacing_b`, `extract`（帯域/差分）
- メモ: 「重ねる」だけでも効くが、差分抽出（帯域）すると一段プロッタ向けになる。

### アイデア C: `E.phase_warp_stripes(field)`（位相ワープ縞）

- ねらい: 縞模様の位相を別のスカラー場で歪ませて“流体っぽい縞”を作る。
- 入出力: 入力=`field`（位相用）, 出力=等値線/帯域のポリライン
- パラメータ案: `freq`, `phase_gain`, `levels`, `grid_pitch`, `smooth`
- メモ: 位相だけを動かすので、線密度を保ったまま“うねり”が出る。

### アイデア D: `E.beat_node_loops()`（ビート節点の小ループ群）

- ねらい: 干渉場の“節点”（変化が遅い点）周りに小さな輪を置き、点描よりリッチにする。
- 入出力: 入力=（内部で生成する `field`）, 出力=小さな閉ポリライン（輪/楕円）
- パラメータ案: `k1/k2`, `threshold`, `loop_size`, `count`, `seed`
- メモ: 「節点だけ」抽出すると空白が多く取れて、上品な飾りになる。

### アイデア E: `E.interference_mask(base)`（干渉場マスク/密度変調）

- ねらい: 既存線を、干渉場 `s(p)` の帯域/確率で残したり消したりして“波の影”を乗せる。
- 入出力: 入力=`base`, 出力=間引き/分割された `base`
- パラメータ案: `mode`（keep/drop/prob）, `a/b`（帯域）, `seed`, `min_seg_len`
- メモ: `E.scalar_band_hatch` の「base を対象にした」版。素材を選ばず効く。

