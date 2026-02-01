# API 引数順一覧（primitive / effect / preset）

目的: 引数の命名と順序の一貫性を確認するための一覧。

- generated: 2026-01-30
- source: registry の `param_order`（GUI/永続化の表示順）
- excluded: `activate` / `name` / `key`

## 共通パラメータ（順序ルール用）

- `center`（中心座標。vec3）
- `scale`（倍率。vec3/float）
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

## Primitives（G.* / 8）

### `G.asemic`

> コメント: `*_min`/`*_max` のペア、`*_steps` のペアなどがまとまっていて読みやすい。今後増やすなら「ペアは隣接」のルールを維持すると良い。

- `text`
- `seed`
- `n_nodes`
- `candidates`
- `stroke_min`
- `stroke_max`
- `walk_min_steps`
- `walk_max_steps`
- `stroke_style`
- `bezier_samples`
- `bezier_tension`
- `text_align`
- `glyph_advance_em`
- `space_advance_em`
- `letter_spacing_em`
- `line_height`
- `use_bounding_box`
- `box_width`
- `box_height`
- `show_bounding_box`
- `center`
- `scale`

### `G.grid`

- `nx`
- `ny`
- `center`
- `scale`

### `G.line`

- `center`
- `anchor`
- `length`
- `angle`

### `G.polygon`

- `n_sides`
- `phase`
- `sweep`
- `center`
- `scale`

### `G.polyhedron`

- `type_index`
- `center`
- `scale`

### `G.sphere`

- `subdivisions`
- `type_index`
- `mode`
- `center`
- `scale`

### `G.text`

- `text`
- `font`
- `font_index`
- `text_align`
- `letter_spacing_em`
- `line_height`
- `use_bounding_box`
- `box_width`
- `box_height`
- `show_bounding_box`
- `quality`
- `center`
- `scale`

### `G.torus`

- `major_radius`
- `minor_radius`
- `major_segments`
- `minor_segments`
- `center`
- `scale`

## Effects（E.* / 30）

### `E.affine`

- `auto_center`
- `pivot`
- `rotation`
- `scale`
- `delta`

### `E.bold`

- `count`
- `radius`
- `seed`

### `E.buffer`

- `join`
- `quad_segs`
- `distance`
- `union`
- `keep_original`

### `E.clip` (inputs=2)

- `mode`
- `draw_outline`

### `E.collapse`

> コメント: `auto_center/pivot` を持つ他の transform 系（`rotate/scale/affine/twist`）が先頭寄りなのに対し、ここでは末尾寄り。方針を揃えるなら `auto_center, pivot` を先頭（または `intensity` の直後）へ移動すると横断比較しやすい。

- `intensity`
- `subdivisions`
- `intensity_mask_base`
- `intensity_mask_slope`
- `auto_center`
- `pivot`

### `E.dash`

- `dash_length`
- `gap_length`
- `offset`
- `offset_jitter`

### `E.displace`

> コメント: 周波数は `wobble` が `frequency` なので、`spatial_freq` も `frequency` へ寄せると揃う。時間/位相は `t` より `phase` の方が（`wobble` と）語彙が揃う。

- `amplitude`
- `spatial_freq` -> `frequency`
- `amplitude_gradient`
- `frequency_gradient`
- `gradient_center_offset`
- `gradient_profile`
- `gradient_radius`
- `min_gradient_factor`
- `max_gradient_factor`
- `t` -> `phase`

### `E.drop`

> コメント: `keep_original`（出力に元を混ぜる）と `keep_mode`（条件に一致したものを残す/捨てる）がどちらも「keep」なので混同しやすい。まずは `keep_mode` を `mode` 等へ寄せて衝突しない語彙にするのが分かりやすい。

- `interval`
- `index_offset`
- `min_length`
- `max_length`
- `probability_base`
- `probability_slope`
- `by`
- `seed`
- `keep_mode` -> `mode`

### `E.extrude`

- `delta`
- `scale`
- `subdivisions`
- `center_mode`

### `E.fill`

- `angle_sets`
- `angle`
- `density`
- `spacing_gradient`
- `remove_boundary`

### `E.highpass`

- `step`
- `sigma`
- `gain`
- `closed`

### `E.isocontour`

- `spacing`
- `phase`
- `max_dist`
- `mode`
- `grid_pitch`
- `gamma`
- `level_step`
- `auto_close_threshold`
- `keep_original`

### `E.lowpass`

- `step`
- `sigma`
- `closed`

### `E.metaball`

- `radius`
- `threshold`
- `grid_pitch`
- `auto_close_threshold`
- `output`
- `keep_original`

### `E.mirror`

> コメント: 中心が `cx/cy` になっているが、他の多くが `center`（vec3）なので語彙が分かれている。2D を分割名で持つなら `center_x/center_y` のように揃えると一貫性が上がる。

- `n_mirror`
- `cx` -> `center_x`
- `cy` -> `center_y`
- `source_positive_x`
- `source_positive_y`
- `show_planes`

### `E.mirror3d`

- `mode`
- `n_azimuth`
- `center`
- `axis`
- `phi0`
- `mirror_equator`
- `source_side`
- `group`
- `use_reflection`
- `show_planes`

### `E.partition`

> コメント: `seed` の位置が中盤にあり、他 op の「末尾寄せ」案とずれる。`mode` が先頭にあるのは良いので、揃えるなら `seed` の配置ルールだけ決めると良さそう。

- `mode`
- `site_count`
- `seed`
- `site_density_base`
- `site_density_slope`
- `auto_center`
- `pivot`

### `E.pixelate`

- `step`
- `corner`

### `E.quantize`

- `step`

### `E.reaction_diffusion`

- `grid_pitch`
- `steps`
- `du`
- `dv`
- `feed`
- `kill`
- `dt`
- `seed`
- `seed_radius`
- `noise`
- `level`
- `min_points`
- `boundary`

### `E.relax`

- `relaxation_iterations`
- `step`

### `E.repeat`

> コメント: 平行移動は `translate/affine` が `delta` なので `offset` も `delta` に寄せると語彙が揃う。回転も `rotation` へ寄せると transform 群の見通しが良くなる。

- `layout`
- `count`
- `radius`
- `theta`
- `n_theta`
- `n_radius`
- `cumulative_scale`
- `cumulative_offset`
- `cumulative_rotate`
- `offset` -> `delta`
- `rotation_step` -> `rotation`
- `scale`
- `curve`
- `auto_center`
- `pivot`

### `E.rotate`

- `auto_center`
- `pivot`
- `rotation`

### `E.scale`

- `mode`
- `auto_center`
- `pivot`
- `scale`

### `E.subdivide`

- `subdivisions`

### `E.translate`

- `delta`

### `E.trim`

- `start_param`
- `end_param`

### `E.twist`

- `auto_center`
- `pivot`
- `angle`
- `axis_dir`

### `E.weave`

- `num_candidate_lines`
- `relaxation_iterations`
- `step`

### `E.wobble`

- `amplitude`
- `frequency`
- `phase`

## Presets（P.* / 13）

- `.grafix/config.yaml` の `paths.preset_module_dirs` を autoload した結果

### `P.axes`

- `center`
- `axis_length`
- `axis_visible_ratio`
- `axis_visible_anchor`
- `tick_count_x`
- `tick_length`
- `tick_offset`
- `tick_log`

### `P.dot_matrix`

- `center`
- `matrix_size`
- `dot_size`
- `fill_density_coef`
- `repeat_count_x`
- `repeat_count_y`

### `P.flow`

> コメント: `E.displace` 側を `spatial_freq -> frequency` に寄せると、preset 側の `displace_frequency` との対応が自然になる（引数名の “翻訳” が減る）。

- `center`
- `scale`
- `fill_density_coef`
- `fill_angle`
- `subdivide_levels`
- `displace_amplitude`
- `displace_frequency`

### `P.grn_a5_frame`

- `show_layout`
- `layout_color_rgb255`
- `number_text`
- `explanation_text`
- `explanation_density`
- `template_color_rgb255`

### `P.layout_bounds`

> コメント: `show_trim` が `trim` の後にあるが、`show_trim` がトグルで `trim` が値なので、GUI 操作の自然さ重視なら `show_trim → trim` の順にする案がある（他の `show_baseline → baseline_*` と揃う）。

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `border`
- `show_margin`
- `trim`
- `show_trim`
- `offset`

### `P.layout_diagonals`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `offset`

### `P.layout_golden_ratio`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `levels`
- `offset`

### `P.layout_grid_system`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `cols`
- `rows`
- `gutter_x`
- `gutter_y`
- `show_column_centers`
- `show_baseline`
- `baseline_step`
- `baseline_offset`
- `offset`

### `P.layout_metallic_rectangles`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `metallic_n`
- `levels`
- `corner`
- `clockwise`
- `offset`

### `P.layout_ratio_lines`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `ratio`
- `levels`
- `min_spacing`
- `max_lines`
- `offset`

### `P.layout_square_grid`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `cell_size`
- `offset`

### `P.layout_thirds`

- `canvas_w`
- `canvas_h`
- `axes`
- `margin_l`
- `margin_r`
- `margin_t`
- `margin_b`
- `show_center`
- `offset`

### `P.logo`

- `center`
- `scale`
- `fill_density_coef`
