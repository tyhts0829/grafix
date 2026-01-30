# ui_visible 対応漏れチェックリスト（2026-01-30）

目的: `docs/memo/ui_visible.md` の仕組み（Parameter GUI で “いま効いている引数だけ” を表示）を、既存の built-in primitive/effect/preset に反映する。

前提:
- ルールは `@preset/@primitive/@effect(..., ui_visible=...)` で registry に登録する（永続化しない）
- `ui_visible` は表示制御のみ（値や MIDI 割当などは変更しない）
- “スイッチ役” の引数（例: `mode`, `show_*`）は基本は常時表示（隠さない）

このファイルは「対応が必要そうな箇所の列挙」だけを目的とし、実装は別タスクで行う。

---

## primitives

### `src/grafix/core/primitives/sphere.py`

- [x] `mode` が `type_index` によって無効になるのに常時表示される
  - 現状: `type_index` が `zigzag/icosphere` のとき `mode` は未使用
  - 対応案（例）: `mode` は `type_index in {0(latlon),3(rings)}` のときだけ表示

### `src/grafix/core/primitives/asemic.py`

- [x] `stroke_style="line"` のとき `bezier_samples/bezier_tension` が無効なのに常時表示される
  - 現状: `bezier_*` は `style == "bezier"` のときのみ参照
  - 対応案（例）: `bezier_samples`, `bezier_tension` を `stroke_style == "bezier"` のときだけ表示
  - 既存の `use_bounding_box -> box_*` 可視制御は維持

---

## effects

### auto_center / pivot 系

典型例: `auto_center=True` のとき `pivot` は効かないのに常時表示される。

- [x] `src/grafix/core/effects/rotate.py`
  - `pivot` を `auto_center=False` のときのみ表示

- [x] `src/grafix/core/effects/twist.py`
  - `pivot` を `auto_center=False` のときのみ表示

- [x] `src/grafix/core/effects/collapse.py`
  - `pivot` を `auto_center=False` のときのみ表示

- [x] `src/grafix/core/effects/affine.py`
  - `pivot` を `auto_center=False` のときのみ表示

- [x] `src/grafix/core/effects/partition.py`
  - `pivot` を `auto_center=False` のときのみ表示

- [x] `src/grafix/core/effects/repeat.py`
  - 既存 `repeat_ui_visible` に追加:
    - `pivot` を `auto_center=False` のときのみ表示

### `src/grafix/core/effects/scale.py`（mode による枝分かれ）

- [x] `mode != "all"` のとき `auto_center/pivot` が無効なのに常時表示される
  - 現状: `mode="by_line"/"by_face"` は各ポリラインの中心を使うため `auto_center/pivot` は未参照
  - 対応案（例）:
    - `auto_center` を `mode == "all"` のときのみ表示
    - `pivot` を `mode == "all" and auto_center == False` のときのみ表示

### `src/grafix/core/effects/repeat.py`（cumulative_* と curve）

- [x] `cumulative_*` が全て False のとき `curve` が無効なのに常時表示される
  - 現状: `cumulative_scale/offset/rotate` のいずれも True でない場合、`curve` は参照されず `t_curve=t`
  - 対応案（例）: `curve` は `cumulative_*` のいずれかが True のときのみ表示

### `src/grafix/core/effects/mirror.py`（n_mirror による枝分かれ）

- [x] `n_mirror >= 3` のとき `source_positive_x/source_positive_y` が無効なのに常時表示される
  - 現状:
    - `source_positive_x` は `n_mirror in {1,2}` のときのみ参照
    - `source_positive_y` は `n_mirror == 2` のときのみ参照
  - 対応案（例）:
    - `source_positive_x` を `n_mirror in {1,2}` のときのみ表示
    - `source_positive_y` を `n_mirror == 2` のときのみ表示
- [x] `n_mirror == 1` のとき `cy` が無効なのに常時表示される（`cx` のみ参照）

### `src/grafix/core/effects/mirror3d.py`（mode + mirror_equator による枝分かれ）

- [x] `mode` により無効な引数が常時表示される
  - 現状:
    - `mode="azimuth"` だけで使用: `n_azimuth`, `axis`, `phi0`, `mirror_equator`, `source_side`
    - `mode="polyhedral"` だけで使用: `group`, `use_reflection`
    - `source_side` は `mirror_equator=True` のときだけ使用
  - 対応案（例）:
    - `mode=="azimuth"` のときだけ `n_azimuth/axis/phi0/mirror_equator` を表示
    - `mode=="azimuth" and mirror_equator==True` のときだけ `source_side` を表示
    - `mode=="polyhedral"` のときだけ `group/use_reflection` を表示

### `src/grafix/core/effects/displace.py`（gradient_profile による枝分かれ）

- [x] `gradient_profile="linear"` のとき `gradient_radius` が無効なのに常時表示される
  - 現状: `gradient_radius` は `"radial"` の距離 `d` 計算でのみ使用
  - 対応案（例）: `gradient_radius` を `gradient_profile=="radial"` のときのみ表示

---

## presets

### `sketch/presets/layout/grid_system.py`

- [x] `show_baseline=False` のとき `baseline_step/baseline_offset` が無効なのに常時表示される
  - 対応案（例）: `baseline_step/baseline_offset` を `show_baseline=True` のときのみ表示

### `sketch/presets/layout/bounds.py`

- [x] `show_trim=False` のとき `trim` が無効なのに常時表示される
  - 対応案（例）: `trim` を `show_trim=True` のときのみ表示

### `sketch/presets/grn/a5_frame.py`

- [x] `show_layout=False` のとき `layout_color_rgb255` が無効なのに常時表示される
  - 対応案（例）: `layout_color_rgb255` を `show_layout=True` のときのみ表示
