# 成長/エージェントを核にした effect アイデア（非SDF）

作成日: 2026-01-30

対象:

- 差分成長（Differential growth）
- Physarum / スライムモールド（エージェント堆積）
- 反応拡散（Gray-Scott など）
- 粒子系（advection + 反発 + 境界）

## 前提（共通）

- “生成プロセス” を核にすると、パラメータ数が少なくても表情が豊かになる（ただし計算は重くなりやすい）。
- 最終的には「軌跡を線として出す」か「密度場→等値線/帯域で線化する」の 2 ルートに落とすと、Grafix に馴染む。

## 手法: 差分成長（Differential growth）

曲線上の点を増やし、局所ルール（曲率/反発/目標距離）で更新することで、有機的なフリル/襞/触手を生成する。線の“生き物感”が強い核。

### アイデア A: `E.differential_growth(seed)`（単一ループ成長）

- ねらい: 円や単純形から、コーラル/脳みそっぽい輪郭線へ育てる。
- 入出力: 入力=`seed`（閉ポリライン）, 出力=成長後の閉ポリライン
- パラメータ案: `target_spacing`, `repel`, `step`, `iters`, `noise`
- メモ: 成長途中のスナップショットを等間隔で残すと“層”が作れる。

### アイデア B: `E.growth_in_mask(mask)`（マスク内拘束成長）

- ねらい: 形の内部で成長させ、境界でぶつかって折れ曲がる“内側の襞”を作る。
- 入出力: 入力=`mask`（＋初期 seed）, 出力=開/閉ポリライン（成長線）
- パラメータ案: `seed_count`, `boundary_avoid`, `target_spacing`, `iters`, `seed`
- メモ: 境界で “滑らせる/跳ね返す” のルールだけで表情が変わる。

### アイデア C: `E.growth_from_base(base)`（既存線からの成長装飾）

- ねらい: 文字や輪郭線から、縁飾り（フリンジ/トゲ/波打ち）を生やす。
- 入出力: 入力=`base`, 出力=装飾後の `base`（または追加線）
- パラメータ案: `outward`（方向）, `amplitude`, `target_spacing`, `iters`, `jitter`
- メモ: “元の線は保持＋追加線だけ出す” とレイヤ設計がしやすい。

### アイデア D: `E.growth_guided_by_field(seed, field)`（場で誘導する成長）

- ねらい: 成長の法線方向をベクトル場でねじり、風に煽られたような成長を作る。
- 入出力: 入力=`seed`＋`field`, 出力=成長後のポリライン
- パラメータ案: `field_gain`, `repel`, `step`, `iters`, `max_turn`
- メモ: “成長” と “flow” のハイブリッド。動きが説明的になりやすい。

### アイデア E: `E.growth_multi_layer(seed)`（多層成長・衝突で皺を作る）

- ねらい: 複数の成長線を同時に走らせ、衝突で層状の皺/境界線を作る。
- 入出力: 入力=`seed` 群, 出力=ポリライン列
- パラメータ案: `n_seeds`, `repel_inter`, `repel_self`, `iters`, `seed`
- メモ: 層が増えすぎると黒くなるので、早めに間引き規則を入れる。

## 手法: Physarum / スライムモールド（エージェント堆積）

エージェントが移動しながら “フェロモン” のような場を更新し、それをまた参照することでネットワークが生える。道路/血管/根っこの核。

### アイデア A: `E.physarum_network(attractors)`（点群を結ぶネットワーク）

- ねらい: 与えた点（街/星/島）を、それっぽい“路線図”で結ぶ。
- 入出力: 入力=`points`（attractors）, 出力=開ポリライン（ネットワーク）
- パラメータ案: `n_agents`, `sensor_angle`, `turn_rate`, `deposit`, `decay`, `iters`
- メモ: 出力は「密度場→等値線」か「軌跡の間引き」のどちらかで線化する。

### アイデア B: `E.physarum_between_shapes(shapes)`（形と形の“橋”）

- ねらい: 複数形状を引力源にして、有機的なブリッジ/ケーブルを生やす。
- 入出力: 入力=`mask` 群（または閉曲線群）, 出力=開ポリライン
- パラメータ案: `attract_gain`, `repel_gain`, `iters`, `seed`
- メモ: “橋” は少数で良い。多すぎると情報が散る。

### アイデア C: `E.physarum_avoid(obstacles)`（障害物回避の迷路）

- ねらい: 障害物を避けて流れるネットワークを作り、迷路っぽい動線を得る。
- 入出力: 入力=`obstacles`（mask）, 出力=開ポリライン
- パラメータ案: `repel_gain`, `wall_margin`, `iters`, `seed`
- メモ: 反発（repel）を少し強めるだけで “壁沿い” の表情が出る。

### アイデア D: `E.physarum_edge_track(mask)`（境界沿いの路）

- ねらい: 境界を弱い引力源にして、輪郭に沿う“巡回路”を生やす。
- 入出力: 入力=`mask`, 出力=開ポリライン（周縁ネットワーク）
- パラメータ案: `edge_attract`, `edge_decay`, `iters`, `seed`
- メモ: 境界の “凹み” に入り込む挙動が出ると面白い。

### アイデア E: `E.physarum_density_isocontours(...)`（堆積場の等値線化）

- ねらい: 生成した密度場から “等値線だけ” を抜き、プロッタ向けにクリーンにする。
- 入出力: 入力=（physarum の内部状態）, 出力=閉/開ポリライン（等値線）
- パラメータ案: `levels`, `grid_pitch`, `smooth`, `cleanup_min_len`
- メモ: “ネットワーク” が少し抽象化され、デザインに寄る。

## 手法: 反応拡散（Reaction-Diffusion）

2 変数の拡散＋反応で斑点/縞が出る。既に `reaction_diffusion` effect がある前提でも、初期条件と線化ルールで派生が多い核。

### アイデア A: `E.reaction_diffusion_init_mask(mask)`（マスク由来の初期条件）

- ねらい: 形（mask）を初期染みとして置き、そこから RD を育てて模様を“形に従属”させる。
- 入出力: 入力=`mask`, 出力=線化されたポリライン（等値線/帯域）
- パラメータ案: `feed`, `kill`, `diff_u`, `diff_v`, `iters`, `grid_pitch`
- メモ: 初期条件が強いほど “意味のある模様” になる。

### アイデア B: `E.reaction_diffusion_stripes(mask=None)`（縞チューニング）

- ねらい: 斑点ではなく縞に寄せ、版画のストライプ素材として使う。
- 入出力: 入力=任意で `mask`, 出力=等値線/帯域ポリライン
- パラメータ案: `preset`（spots/stripes）, `levels`, `smooth`, `cleanup`
- メモ: 縞を “帯域抽出” で線にすると、紙面が汚れにくい。

### アイデア C: `E.reaction_diffusion_mask(base)`（RD による線のマスク/欠け）

- ねらい: 既存線を RD 場で「欠く/残す」ことで、表面が侵食されたような質感にする。
- 入出力: 入力=`base`（＋内部で RD field）, 出力=分割/間引きされた `base`
- パラメータ案: `mode`（keep/drop/prob）, `threshold`, `seed`, `min_seg_len`
- メモ: RD を “pattern generator” としてだけ使うと扱いやすい。

### アイデア D: `E.reaction_diffusion_cell_edges()`（相境界をクラック線に）

- ねらい: 2 状態の境界（濃淡の境目）だけを抽出し、ひび割れ/細胞境界として描く。
- 入出力: 入力=（RD field）, 出力=開ポリライン（境界線）
- パラメータ案: `threshold`, `cleanup`, `simplify`, `smooth`
- メモ: 斑点より “輪郭線” に寄るので、プロッタ向けに強い。

### アイデア E: `E.reaction_diffusion_flowfield()`（RD から方向場→流線）

- ねらい: RD の勾配/構造テンソルから方向場を作り、流線/ハッチに繋げる。
- 入出力: 入力=（RD field）, 出力=開ポリライン（流線/ハッチ）
- パラメータ案: `field_kind`（grad/tangent）, `seed_spacing`, `steps`, `min_sep`
- メモ: “模様の方向性” を取り出せると、RD が素材として一段強くなる。

## 手法: 粒子系（Particles）

粒子は「軌跡が線になる」ので、最短でペンプロッタに落ちる。粒子の相互作用（反発/吸引）で密度が整い、境界条件で構図が決まる。

### アイデア A: `E.particle_trails(field)`（場に流される粒子の軌跡）

- ねらい: 風の場/渦の場を見せる。ストリームラインより “粒っぽさ” が出る。
- 入出力: 入力=`field`（＋任意で `mask`）, 出力=開ポリライン（軌跡）
- パラメータ案: `n_particles`, `steps`, `step_size`, `spawn`（初期配置）, `wrap/clip`
- メモ: 粒子の寿命を短くして “毛” に、長くして “流線” に寄せられる。

### アイデア B: `E.particle_bounce_hatch(mask)`（バウンス・ハッチ）

- ねらい: マスク内で粒子を反射させ、均一に面をなぞる“回遊線”を作る。
- 入出力: 入力=`mask`, 出力=開ポリライン
- パラメータ案: `n_particles`, `steps`, `bounce`（反射/滑走）, `min_sep`, `seed`
- メモ: “完全反射” より “少し滑る” のが版画っぽい。

### アイデア C: `E.particle_orbits(attractors)`（吸引点まわりの軌道）

- ねらい: 星図/重力のような軌道線で、中心性のある構図を作る。
- 入出力: 入力=`points`（attractors）, 出力=開ポリライン
- パラメータ案: `strength`, `falloff`, `damping`, `steps`, `seed`
- メモ: 減衰を入れると “収束する渦” になり、紙面がまとまる。

### アイデア D: `E.particle_deposit_isocontours(...)`（堆積→等値線）

- ねらい: 粒子の通過回数を密度場にして、等値線/帯域で線化する（軌跡より抽象的）。
- 入出力: 入力=粒子系（内部状態）, 出力=閉/開ポリライン
- パラメータ案: `grid_pitch`, `levels`, `smooth`, `cleanup`
- メモ: “密度場で表現する” と、線数をコントロールしやすい。

### アイデア E: `E.particle_string_art(targets)`（糸かけ風の接続線）

- ねらい: 粒子の位置やターゲット点を逐次接続し、糸かけ/ストリングアートの質感を作る。
- 入出力: 入力=`points`（targets）または `mask`, 出力=開ポリライン（接続線）
- パラメータ案: `choose`（nearest/random/weighted）, `max_len`, `steps`, `seed`
- メモ: “線が長くなりすぎない” ルール（`max_len`）が絵を守る。

