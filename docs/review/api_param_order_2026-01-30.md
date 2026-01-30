# API 引数順一覧（primitive / effect / preset）

目的: 引数の命名と順序の一貫性を確認するための一覧。

- generated: 2026-01-30
- source: registry の `param_order`（GUI/永続化の表示順）
- excluded: `activate` / `name` / `key`

## Primitives（G.* / 8）

### `G.asemic`

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

- `amplitude`
- `spatial_freq`
- `amplitude_gradient`
- `frequency_gradient`
- `gradient_center_offset`
- `gradient_profile`
- `gradient_radius`
- `min_gradient_factor`
- `max_gradient_factor`
- `t`

### `E.drop`

- `interval`
- `index_offset`
- `min_length`
- `max_length`
- `probability_base`
- `probability_slope`
- `by`
- `seed`
- `keep_mode`

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

- `n_mirror`
- `cx`
- `cy`
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

- `layout`
- `count`
- `radius`
- `theta`
- `n_theta`
- `n_radius`
- `cumulative_scale`
- `cumulative_offset`
- `cumulative_rotate`
- `offset`
- `rotation_step`
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
