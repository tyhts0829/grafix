# サンプリング/緩和を核にした effect アイデア（非SDF）

作成日: 2026-01-30

対象:

- 点過程（Poisson disk / Blue noise）
- 緩和・最適化（Lloyd / CVT）

## 前提（共通）

- “良い点配置” は、そのまま点描にもなるし、Voronoi/メッシュ/近傍接続で線にできる。
- サンプリング自体が核なので、後段（hatch/flow/warp）に何を繋いでも破綻しにくい。

## 手法: 点過程（Poisson disk / Blue noise）

「最小距離があるランダム」を核にする。秩序と乱れのバランスが良く、密度制御（可変 Poisson）にも拡張しやすい。

### アイデア A: `E.blue_noise_stipple(mask)`（点描/小記号の配置）

- ねらい: 面を“点の集合”で埋める。ペンプロッタなら点を小ループ/十字にして線化できる。
- 入出力: 入力=`mask`, 出力=開ポリライン（点記号列）または点列
- パラメータ案: `spacing`, `glyph`（dot/cross/loop）, `glyph_size`, `seed`
- メモ: `glyph` を変えるだけで印象が大きく変わる。

### アイデア B: `E.poisson_short_strokes(mask, field=None)`（短ストローク・テクスチャ）

- ねらい: Poisson 点を種に、短い線分を打って質感を作る（木目/毛並み/砂目）。
- 入出力: 入力=`mask`（＋任意で `field`）, 出力=開ポリライン（短い線分群）
- パラメータ案: `spacing`, `length`, `angle`（固定 or field）, `jitter`, `seed`
- メモ: “点→短線” は最小コストで強いテクスチャになる。

### アイデア C: `E.circle_packing(mask)`（簡易サークルパッキング輪郭）

- ねらい: 点配置を円に変換し、円の輪郭だけで“泡/細胞”感を出す。
- 入出力: 入力=`mask`, 出力=閉ポリライン（円/楕円の集合）
- パラメータ案: `spacing`（初期半径）, `relax_steps`, `min_radius`, `max_radius`
- メモ: 厳密な最適化ではなく、軽い反発で十分“それっぽく”なる。

### アイデア D: `E.poisson_gap_fill(base, mask=None)`（ネガ空間の埋め草）

- ねらい: 既存線の周りの空白にだけ点（または短線）を足し、密度を均す。
- 入出力: 入力=`base`（＋任意で `mask`）, 出力=`base`＋追加線
- パラメータ案: `spacing`, `avoid_dist`（base から距離を取る）, `glyph`, `seed`
- メモ: 作品の“スカスカ感”を短時間で埋められる。

### アイデア E: `E.poisson_variable_density(mask, density_field)`（可変密度サンプリング）

- ねらい: 濃淡（density）を点密度として素直に表現する。後段の線化にも使える。
- 入出力: 入力=`mask`＋`density_field`, 出力=点列（または記号ポリライン）
- パラメータ案: `base_spacing`, `density_gain`, `clamp`, `seed`
- メモ: “密度場” は画像でもスカラー場でも良い。核が広い。

## 手法: Lloyd / CVT（Centroidal Voronoi Tessellation）

“点→セル→重心→点” を回して、ムラの少ない分布を作る。Poisson より「均質さ」が強く、図面っぽい清潔さに寄る。密度場（重み付き CVT）で陰影にもできる。

### アイデア A: `E.cvt_points(mask, density_field=None)`（CVT 点配置）

- ねらい: 均質な点配置を得る（点描、メッシュ、セル化の起点）。
- 入出力: 入力=`mask`（＋任意で `density_field`）, 出力=点列
- パラメータ案: `n_points`, `iters`, `seed`, `density_gain`
- メモ: 重み付き CVT にすると「暗い場所ほど点が多い」が自然に作れる。

### アイデア B: `E.cvt_voronoi_edges(mask)`（CVT セル境界の線画）

- ねらい: CVT の“良いセル”を境界線として描く。細胞模様が上品になる。
- 入出力: 入力=`mask`, 出力=開ポリライン（セル境界）
- パラメータ案: `n_points`, `iters`, `bounds`, `cleanup`
- メモ: `docs/plan/cells_mesh_skeleton_effect_ideas_2026-01-30.md` の Voronoi と接続しやすい。

### アイデア C: `E.cvt_neighbor_graph(mask)`（近傍接続ネットワーク）

- ねらい: CVT 点を kNN / Delaunay で結び、均質なネットワーク線画を作る。
- 入出力: 入力=`mask`, 出力=開ポリライン（グラフ辺）
- パラメータ案: `k`, `max_edge_len`, `keep_ratio`, `seed`
- メモ: “描く辺を減らす” ほど洗練される。選別がデザイン。

### アイデア D: `E.cvt_centroid_strokes(mask, field=None)`（重心方向ストローク）

- ねらい: 各セル内部に、重心へ向かう/重心を横切る短線を入れて面感を出す。
- 入出力: 入力=`mask`（＋任意で `field`）, 出力=開ポリライン（短線群）
- パラメータ案: `stroke_len`, `count_per_cell`, `jitter`, `align`（to_centroid/field）
- メモ: “セルごとに 1〜数本” だと、過密にならず品が出る。

### アイデア E: `E.cvt_single_path(mask)`（点列を 1 本線に縫う）

- ねらい: 点群を 1 本の連続線で“縫う”ことで、ペンプロッタ向けの単線作品にする。
- 入出力: 入力=`mask`, 出力=開ポリライン（1 本の長い線）
- パラメータ案: `n_points`, `path_kind`（greedy/2opt など）, `smooth`, `seed`
- メモ: 厳密最適化は不要。貪欲＋軽い改善で十分に見えることが多い。

