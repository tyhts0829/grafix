# ui_visible 変更のスモークテスト用スケッチ（2026-01-30）

目的: `ui_visible` を追加した primitive/effect/preset を実際に呼び出し、Parameter GUI 上で表示切替が動くことを手早く確認できるようにする。

対象:
- primitives: `sphere`, `asemic`
- effects: `rotate`, `twist`, `collapse`, `affine`, `partition`, `repeat`, `scale`, `mirror`, `mirror3d`, `displace`
- presets: `layout_grid_system`, `layout_bounds`, `grn_a5_frame`

方針:
- 既存の `sketch/readme/16.py` をスモークテスト用に更新する
- 上記 op を **1 回ずつ** 呼び出して `draw(t)` の戻り値に含める（＝フレーム実行される）
- 引数は基本デフォルト（空）で呼ぶ（見やすさのための入力プリミティブ生成だけ最小限の座標指定は許容）

チェックリスト:
- [x] `sketch/readme/16.py` で対象 primitive/effect/preset を呼び出す
- [x] `draw(t)` の戻り値に含めてランタイムで実行されるようにする

実行例:
- `python sketch/readme/16.py`

