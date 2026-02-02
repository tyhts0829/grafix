# API 引数順一覧（primitive / effect / preset）

目的: 引数の命名と順序の一貫性を確認するための一覧。

- generated: 2026-01-30
- source: registry の `param_order`（GUI/永続化の表示順）
- excluded: `activate` / `name` / `key`

## 共通パラメータ（順序ルール用）

- `scale`（倍率。vec3/float）
- `center`（中心座標。vec3）
- `rotation` / `angle`（回転。vec3/float）
- `delta`（平行移動 vec3） / `offset`（ずらし。平行移動とスカラー offset が混在しやすい）
- `auto_center` / `pivot`（pivot 指定。effect で頻出）
- `seed`（乱数シード）
- `phase`（位相/時間。`t` を含めて寄せ先候補）
- `mode`（動作モード/分岐）
- `count` / `n_*` / `*_count`（個数）
- `step`（刻み/間隔）

## 優先修正タスク（ランキング）

- [ ] (P0, 破壊的) transform 系の語彙を統一: vec3 平行移動は `delta`、回転は `rotation`、倍率は `scale` に寄せる
  - 対象例: `E.repeat offset -> delta`, `E.repeat rotation_step -> rotation`, `P.layout_* offset -> delta`
- [ ] (P0, 破壊的) ノイズ/揺れ系の語彙を統一: `frequency` / `phase` に寄せる（`spatial_freq` / `t` を廃止）
  - 対象例: `E.displace spatial_freq -> frequency`, `E.displace t -> phase`
- [ ] (P1, 破壊的) 2D 中心座標の語彙を統一: `center_x` / `center_y` に寄せる（`cx/cy` を廃止）
  - 対象例: `E.mirror cx/cy -> center_x/center_y`
- [ ] (P1, 破壊的) `keep_*` の衝突を解消: `keep_mode` を `mode`（または `action`）へ寄せる
  - 対象例: `E.drop keep_mode -> mode`
- [ ] (P2, 主に表示順) 表示順ルールを決めて揃える（API を変えない範囲から始める）
  - 例: `seed` は末尾寄せ / `show_*` は依存パラメータより前 / `*_base` → `*_slope` は隣接

## 全体コメント（改善案）

- 座標系の「中心」系は、可能なら `center`（vec3）に寄せる（`cx/cy` などの分割名は例外扱いにする、など方針化すると比較が速い）。
- 平行移動は `delta` と `offset` が混在しているため、どちらを標準にするか（または役割を分けるか）を決めると迷いが減る。
- 乱数は `seed` の置き場所が op により揺れているので、末尾寄せ等のルールを決めると揃えやすい。
- 「トグル → 依存パラメータ」（例: `show_*` とその値）の順に置くと、GUI 上の操作が自然になる（トグルが先に見える）。
- transform 系は `scale → rotation → translate(delta)` の並びに揃えると読みやすい（`affine` が基準になる）。

## Primitives（G.\* / 8）

### `G.asemic`

> コメント: `*_min`/`*_max` のペア、`*_steps` のペアなどがまとまっていて読みやすい。今後増やすなら「ペアは隣接」のルールを維持すると良い。

- `text`: 3
- `seed`: 4
- `n_nodes`: 5
- `candidates`: 6
- `stroke_min`: 7
- `stroke_max`: 8
- `walk_min_steps`: 9
- `walk_max_steps`: 10
- `stroke_style`: 11
- `bezier_samples`: 12
- `bezier_tension`: 13
- `text_align`: 14
- `glyph_advance_em`: 15
- `space_advance_em`: 16
- `letter_spacing_em`: 17
- `line_height`: 18
- `use_bounding_box`: 19
- `box_width`: 20
- `box_height`: 21
- `show_bounding_box`: 22
- `center`: 1
- `scale`: 2

### `G.grid`

- `nx`: 3
- `ny`: 4
- `center`: 1
- `scale`: 2

### `G.line`

- `center`: 1
- `anchor`: 3
- `length`: 4
- `angle`: 2

### `G.polygon`

- `n_sides`: 3
- `phase`: 4
- `sweep`: 5
- `center`: 1
- `scale`: 2

### `G.polyhedron`

- `type_index`: 3
- `center`: 1
- `scale`: 2

### `G.sphere`

- `subdivisions`: 3
- `type_index`: 4
- `mode`: 5
- `center`: 1
- `scale`: 2

### `G.text`

- `text`: 3
- `font`: 4
- `font_index`: 5
- `text_align`: 6
- `letter_spacing_em`: 7
- `line_height`: 8
- `use_bounding_box`: 9
- `box_width`: 10
- `box_height`: 11
- `show_bounding_box`: 12
- `quality`: 13
- `center`: 1
- `scale`: 2

### `G.torus`

- `major_radius`: 3
- `minor_radius`: 4
- `major_segments`: 5
- `minor_segments`: 6
- `center`: 1
- `scale`: 2

## Effects（E.\* / 30）

### `E.affine`

- `auto_center`: 3
- `pivot`: 4
- `rotation`: 2
- `scale`: 1
- `delta`: 5

### `E.bold`

- `count`: 1
- `radius`: 2
- `seed`: 3

### `E.buffer`

- `join`: 1
- `quad_segs`: 2
- `distance`: 3
- `union`: 4
- `keep_original`: 5

### `E.clip` (inputs=2)

- `mode`: 1
- `draw_outline`: 2

### `E.collapse`

> コメント: `auto_center/pivot` を持つ他の transform 系（`rotate/scale/affine/twist`）が先頭寄りなのに対し、ここでは末尾寄り。方針を揃えるなら `auto_center, pivot` を先頭（または `intensity` の直後）へ移動すると横断比較しやすい。

- `intensity`: 1
- `subdivisions`: 2
- `intensity_mask_base`: 3
- `intensity_mask_slope`: 4
- `auto_center`: 5
- `pivot`: 6

### `E.dash`

- `dash_length`: 1
- `gap_length`: 2
- `offset`: 3
- `offset_jitter`: 4

### `E.displace`

> コメント: 周波数は `wobble` が `frequency` なので、`spatial_freq` も `frequency` へ寄せると揃う。時間/位相は `t` より `phase` の方が（`wobble` と）語彙が揃う。

- `amplitude`: 1
- `spatial_freq` -> `frequency`: 2
- `amplitude_gradient`: 3
- `frequency_gradient`: 4
- `gradient_center_offset`: 5
- `gradient_profile`: 6
- `gradient_radius`: 7
- `min_gradient_factor`: 8
- `max_gradient_factor`: 9
- `t` -> `phase`: 10

### `E.drop`

> コメント: `keep_original`（出力に元を混ぜる）と `keep_mode`（条件に一致したものを残す/捨てる）がどちらも「keep」なので混同しやすい。まずは `keep_mode` を `mode` 等へ寄せて衝突しない語彙にするのが分かりやすい。

- `interval`: 1
- `index_offset`: 2
- `min_length`: 3
- `max_length`: 4
- `probability_base`: 5
- `probability_slope`: 6
- `by`: 7
- `seed`: 8
- `keep_mode` -> `mode`: 9

### `E.extrude`

- `delta`: 2
- `scale`: 1
- `subdivisions`: 3
- `center_mode`: 4

### `E.fill`

- `angle_sets`: 2
- `angle`: 1
- `density`: 3
- `spacing_gradient`: 4
- `remove_boundary`: 5

### `E.highpass`

- `step`: 1
- `sigma`: 2
- `gain`: 3
- `closed`: 4

### `E.isocontour`

- `spacing`: 1
- `phase`: 2
- `max_dist`: 3
- `mode`: 4
- `grid_pitch`: 5
- `gamma`: 6
- `level_step`: 7
- `auto_close_threshold`: 8
- `keep_original`: 9

### `E.lowpass`

- `step`: 1
- `sigma`: 2
- `closed`: 3

### `E.metaball`

- `radius`: 1
- `threshold`: 2
- `grid_pitch`: 3
- `auto_close_threshold`: 4
- `output`: 5
- `keep_original`: 6

### `E.mirror`

> コメント: 中心が `cx/cy` になっているが、他の多くが `center`（vec3）なので語彙が分かれている。2D を分割名で持つなら `center_x/center_y` のように揃えると一貫性が上がる。

- `n_mirror`: 1
- `cx` -> `center_x`: 2
- `cy` -> `center_y`: 3
- `source_positive_x`: 4
- `source_positive_y`: 5
- `show_planes`: 6

### `E.mirror3d`

- `mode`: 2
- `n_azimuth`: 3
- `center`: 1
- `axis`: 4
- `phi0`: 5
- `mirror_equator`: 6
- `source_side`: 7
- `group`: 8
- `use_reflection`: 9
- `show_planes`: 10

### `E.partition`

> コメント: `seed` の位置が中盤にあり、他 op の「末尾寄せ」案とずれる。`mode` が先頭にあるのは良いので、揃えるなら `seed` の配置ルールだけ決めると良さそう。

- `mode`: 1
- `site_count`: 2
- `seed`: 3
- `site_density_base`: 4
- `site_density_slope`: 5
- `auto_center`: 6
- `pivot`: 7

### `E.pixelate`

- `step`: 1
- `corner`: 2

### `E.quantize`

- `step`: 1

### `E.reaction_diffusion`

- `grid_pitch`: 1
- `steps`: 2
- `du`: 3
- `dv`: 4
- `feed`: 5
- `kill`: 6
- `dt`: 7
- `seed`: 8
- `seed_radius`: 9
- `noise`: 10
- `level`: 11
- `min_points`: 12
- `boundary`: 13

### `E.relax`

- `relaxation_iterations`: 1
- `step`: 2

### `E.repeat`

> コメント: 平行移動は `translate/affine` が `delta` なので `offset` も `delta` に寄せると語彙が揃う。回転も `rotation` へ寄せると transform 群の見通しが良くなる。

- `layout`: 3
- `count`: 4
- `radius`: 5
- `theta`: 6
- `n_theta`: 7
- `n_radius`: 8
- `cumulative_scale`: 9
- `cumulative_offset`: 10
- `cumulative_rotate`: 11
- `offset` -> `delta`: 12
- `rotation_step` -> `rotation`: 2
- `scale`: 1
- `curve`: 13
- `auto_center`: 14
- `pivot`: 15

### `E.rotate`

- `auto_center`: 2
- `pivot`: 3
- `rotation`: 1

### `E.scale`

- `mode`: 2
- `auto_center`: 3
- `pivot`: 4
- `scale`: 1

### `E.subdivide`

- `subdivisions`: 1

### `E.translate`

- `delta`: 1

### `E.trim`

- `start_param`: 1
- `end_param`: 2

### `E.twist`

- `auto_center`: 2
- `pivot`: 3
- `angle`: 1
- `axis_dir`: 4

### `E.weave`

- `num_candidate_lines`: 1
- `relaxation_iterations`: 2
- `step`: 3

### `E.wobble`

- `amplitude`: 1
- `frequency`: 2
- `phase`: 3

## Presets（P.\* / 13）

- `.grafix/config.yaml` の `paths.preset_module_dirs` を autoload した結果

### `P.axes`

- `center`: 1
- `axis_length`: 2
- `axis_visible_ratio`: 3
- `axis_visible_anchor`: 4
- `tick_count_x`: 5
- `tick_length`: 6
- `tick_offset`: 7
- `tick_log`: 8

### `P.dot_matrix`

- `center`: 1
- `matrix_size`: 2
- `dot_size`: 3
- `fill_density_coef`: 4
- `repeat_count_x`: 5
- `repeat_count_y`: 6

### `P.flow`

> コメント: `E.displace` 側を `spatial_freq -> frequency` に寄せると、preset 側の `displace_frequency` との対応が自然になる（引数名の “翻訳” が減る）。

- `center`: 1
- `scale`: 2
- `fill_density_coef`: 3
- `fill_angle`: 4
- `subdivide_levels`: 5
- `displace_amplitude`: 6
- `displace_frequency`: 7

### `P.grn_a5_frame`

- `show_layout`: 1
- `layout_color_rgb255`: 2
- `number_text`: 3
- `explanation_text`: 4
- `explanation_density`: 5
- `template_color_rgb255`: 6

### `P.layout_bounds`

> コメント: `show_trim` が `trim` の後にあるが、`show_trim` がトグルで `trim` が値なので、GUI 操作の自然さ重視なら `show_trim → trim` の順にする案がある（他の `show_baseline → baseline_*` と揃う）。

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `border`: 9
- `show_margin`: 10
- `trim`: 11
- `show_trim`: 12
- `offset`: 13

### `P.layout_diagonals`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `offset`: 9

### `P.layout_golden_ratio`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `levels`: 9
- `offset`: 10

### `P.layout_grid_system`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `cols`: 9
- `rows`: 10
- `gutter_x`: 11
- `gutter_y`: 12
- `show_column_centers`: 13
- `show_baseline`: 14
- `baseline_step`: 15
- `baseline_offset`: 16
- `offset`: 17

### `P.layout_metallic_rectangles`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `metallic_n`: 9
- `levels`: 10
- `corner`: 11
- `clockwise`: 12
- `offset`: 13

### `P.layout_ratio_lines`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `ratio`: 9
- `levels`: 10
- `min_spacing`: 11
- `max_lines`: 12
- `offset`: 13

### `P.layout_square_grid`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `cell_size`: 9
- `offset`: 10

### `P.layout_thirds`

- `canvas_w`: 1
- `canvas_h`: 2
- `axes`: 3
- `margin_l`: 4
- `margin_r`: 5
- `margin_t`: 6
- `margin_b`: 7
- `show_center`: 8
- `offset`: 9

### `P.logo`

- `center`: 1
- `scale`: 2
- `fill_density_coef`: 3
