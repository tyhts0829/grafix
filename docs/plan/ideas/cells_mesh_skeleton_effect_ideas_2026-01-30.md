# セル/メッシュ/骨格を核にした effect アイデア（非SDF）

作成日: 2026-01-30

対象:

- Voronoi / Power diagram（重み付き）
- Delaunay / 三角メッシュ・四角メッシュ
- Straight skeleton / Medial axis（骨格）

## 前提（共通）

- “分割する構造” を核にすると、線の **生成**（境界線・芯線・ネットワーク）と、線の **制御**（密度・方向・太さ相当）に展開しやすい。
- ここでは「点群→分割」「ポリゴン→骨格」のような起点を想定するが、最終出力はいつも通り **ポリライン列** に落とす。

## 手法: Voronoi / Power diagram（セル分割）

点群から「最近点領域」を作るだけで、セル境界・セル面・距離勾配など、線のネタが無限に出る。Power diagram（重み付き）にすると“セルサイズの制御”が一気に効く。

### アイデア A: `E.voronoi_edges(points)`（セル境界線の生成）

- ねらい: もっとも素朴で強い“細胞/ひび”の骨格線を出す。
- 入出力: 入力=`points`, 出力=開ポリライン（セル境界の線分列）
- パラメータ案: `bounds`（範囲/clip）, `relax`（回数）, `cleanup_min_len`
- メモ: `points` を Poisson/CVT にすると即 “良い絵” になりやすい。

### アイデア B: `E.voronoi_cells(points)`（セル輪郭ループ）

- ねらい: セルを「閉曲線」として出し、層状に重ねる素材にする。
- 入出力: 入力=`points`, 出力=閉ポリライン（各セル輪郭）
- パラメータ案: `keep_unbounded`（捨てる/切る）, `simplify`, `smooth`
- メモ: セル輪郭はオフセットやダッシュ等の後処理との相性が良い。

### アイデア C: `E.voronoi_crackle(mask)`（マスク内クラック）

- ねらい: 形（mask）の内部だけを“ひび割れ”で埋める。背景にも主役にもできる。
- 入出力: 入力=`mask`（閉曲線群）, 出力=開ポリライン（境界線）
- パラメータ案: `seed_density`, `seed`（配置）, `bounds_margin`, `clip`
- メモ: ひびの太さ感は「二重線（buffer）」や「破線化」で作れる。

### アイデア D: `E.power_cells(points, weights)`（重み付きセルでサイズ制御）

- ねらい: セルの大きさを場（スカラー）や属性で制御し、中心が細かく外側が粗い等を作る。
- 入出力: 入力=`points`（＋ `weights` or `weight_field`）, 出力=セル境界/輪郭
- パラメータ案: `weight_gain`, `clamp`, `relax`, `bounds`
- メモ: “密度の遠近” を一撃で作れるのが power の旨味。

### アイデア E: `E.voronoi_distance_relief(points)`（最近点距離のレリーフ線）

- ねらい: `d(p)=dist(p, nearest_site)` をスカラー場として扱い、等値線/帯域で模様化する。
- 入出力: 入力=`points`, 出力=閉/開ポリライン（等値線/帯）
- パラメータ案: `levels` or `band`, `grid_pitch`, `smooth`, `cleanup`
- メモ: “セルっぽさ” を残しつつ、より有機的にできる（境界線より柔らかい）。

## 手法: Delaunay / メッシュ（トライアングル/クアッド）

メッシュは「線素材」そのもの。ワイヤーフレームで描くだけでも成立し、さらに “どの辺を描くか” を規則化すると表情が出る。変形の足場（piecewise affine）にもなる。

### アイデア A: `E.delaunay_wire(points)`（三角ワイヤーフレーム）

- ねらい: 点群から最小構造のネットワークを作る。抽象的で強い。
- 入出力: 入力=`points`, 出力=開ポリライン（三角形の辺集合）
- パラメータ案: `bounds`, `max_edge_len`（長辺のカット）, `cleanup`
- メモ: `max_edge_len` を入れると“飛び辺”が消え、密度が整う。

### アイデア B: `E.mesh_edge_select(mesh)`（辺の選別描画）

- ねらい: すべての辺を描かず、規則（長さ/角度/方向）で“抜く”ことで陰影を作る。
- 入出力: 入力=`mesh`（または points→内部で生成）, 出力=開ポリライン（選別後の辺）
- パラメータ案: `mode`（length/angle/orient/random）, `threshold`, `seed`, `keep_ratio`
- メモ: 1 つのメッシュから複数レイヤを作りやすい（閾値違い）。

### アイデア C: `E.mesh_contours(mesh, values)`（メッシュ上の等値線）

- ねらい: 頂点スカラー（高さ/距離/画像サンプル）から、三角形内線形補間で等値線を出す。
- 入出力: 入力=`mesh`＋`values`, 出力=開ポリライン（等値線）
- パラメータ案: `levels`, `smooth`, `cleanup_min_len`
- メモ: 画像駆動（輝度）と相性が良い。“面”を使うのがポイント。

### アイデア D: `E.mesh_warp(base, control_points)`（三角分割ワープ）

- ねらい: 制御点の前後対応で三角形を作り、線素材を piecewise affine に歪ませる。
- 入出力: 入力=`base`＋`control_points`（before/after）, 出力=変形後の `base`
- パラメータ案: `triangulation`（方式）, `clamp`, `blend`（境界の滑らかさ）
- メモ: 画像ワープやレンズと違い、“折れ”を許すことでグラフィックっぽい歪みになる。

### アイデア E: `E.quad_mesh(field)`（方向場整列クアッドメッシュ）

- ねらい: 方向場に沿う格子（2 方向）を作り、布/織物/地図投影のような規則性を出す。
- 入出力: 入力=`field`（方向）＋範囲, 出力=開ポリライン（格子線）
- パラメータ案: `spacing_u`, `spacing_v`, `steps`, `clip`, `seed`
- メモ: ベクトル場（tangent/normal）とも相互変換でき、派生が多い。

## 手法: Straight skeleton / Medial axis（骨格）

ポリゴン形状の “内側の骨” を取り出す。SDF ベースのスケルトンと同じ見た目領域を狙えるが、オフセット由来のイベント（分岐/消滅）が扱いやすいのが利点。

### アイデア A: `E.straight_skeleton(mask)`（骨格線の抽出）

- ねらい: 形の中心線だけで成立する線画（ロゴ/文字/キャラ）を作る。
- 入出力: 入力=`mask`（閉曲線群）, 出力=開ポリライン（骨格）
- パラメータ案: `cleanup_min_len`, `smooth`, `keep_junctions`
- メモ: 出力を “グラフ” として扱えると、後段の派生が増える。

### アイデア B: `E.offset_collapse_events(mask)`（内側オフセットのイベント線）

- ねらい: 等距離オフセットを進めたときの「衝突/合流/消滅」イベントを可視化して線にする。
- 入出力: 入力=`mask`, 出力=開ポリライン（イベントの軌跡）
- パラメータ案: `step`, `max_steps`, `event_kind`（merge/split/vanish）
- メモ: 骨格より“説明的”で、技術図面っぽい表情になる。

### アイデア C: `E.skeleton_ribs(mask)`（リブ/肋骨ストローク）

- ねらい: 骨格→境界へ向けて短い“肋骨”を生成し、彫り/陰影の基礎にする。
- 入出力: 入力=`mask`（＋内部で skeleton）, 出力=開ポリライン（肋骨）
- パラメータ案: `rib_spacing`, `rib_length`, `jitter`, `direction`（in/out）
- メモ: “骨格の各枝に垂直” を守るだけで、かなり版画っぽい。

### アイデア D: `E.skeleton_guided_hatch(mask)`（骨格誘導ハッチ）

- ねらい: 骨格からの距離や枝方向に応じて、ハッチの向き/密度を変える。
- 入出力: 入力=`mask`, 出力=開ポリライン（ハッチ線）
- パラメータ案: `spacing`, `align`（branch/perp）, `density_curve`, `min_sep`
- メモ: “骨格距離” は SDF と同じ役割を果たせる（ただし計算起点が違う）。

### アイデア E: `E.skeleton_truss(mask)`（骨格トラス/補強線）

- ねらい: 骨格のノード間を斜材で結び、建築図面っぽい“構造線”を作る。
- 入出力: 入力=`mask`, 出力=開ポリライン（グラフ辺＋斜材）
- パラメータ案: `mode`（kNN/angle）, `keep_ratio`, `seed`, `cleanup`
- メモ: “描きすぎない” のが肝。選別ルールが見た目を決める。

