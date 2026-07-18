# Parameter GUI レイアウト・操作性改善計画

## 1. 目的

Parameter GUI の横方向の操作性、上部レイアウトの視覚的整理、動的情報による
レイアウト揺れ、文字化け、MIDI learn の一貫性をまとめて改善する。

対象は次の要望である。

- Value 列とスライダーを十分に長くする。
- ウィンドウを横へ広げた分は Value 列だけへ配分する。
- diagnostics / profiler の件数変化で Parameter 行を上下させない。
- 角丸と余白を抑え、シャープで業務用ツールらしい外観にする。
- Style より上の操作・状態・Help の配置を整理する。
- first-party parameter の Description を空のままにしない。
- favorite アイコンの文字化けを直す。
- MIDI learn を X / Y / Z / V という同一系列の操作に見せる。
- 横リサイズを理由に TIME / HISTORY の高さを変えない。

## 2. 調査時点の基準

- [x] `git status --porcelain` が空であることを確認した。
- [x] 既定ウィンドウは `800 x 1000` である。
- [x] 4 列すべてが stretch 指定であり、Value widget 自体は既に列幅いっぱいを使っている。
- [x] 横リサイズ量を `window.width / requested_width` で DPI 倍率と誤認している。
- [x] alerts / profiler / diagnostics / Help が Parameter table より前の通常フロー上にある。
- [x] コア GUI 対象の Description は 359 / 359 件が空である。
- [x] favorite は `★ / ☆` を使っているが、フォント atlas に U+2605 / U+2606 が無く `?` になる。
- [x] vec3 learn は X+ / Y+ / Z+、scalar learn は MIDI + で、scalar button は全幅ではない。

## 3. 実装方針

### 3.1 ウィンドウと列幅

- [x] packaged default と backend の新規ウィンドウ既定を `1100 x 1000` に変更する。
- [x] Source / Parameter、Range、MIDI を logical px の固定列にする。
  - Source / Parameter: 250 px
  - Range: 130 px
  - MIDI: 165 px
- [x] Value だけを stretch 列にし、追加された横幅をすべて受け取らせる。
- [x] 固定列は UI scale / backing scale には追従させるが、OS ウィンドウの横幅には追従させない。
- [x] 意味を失う `table_column_weights` 設定と引数伝播を削除し、互換 shim は作らない。
- [x] 狭い画面での既存 responsive window layout は維持し、保存済み Workspace の
  ユーザー指定 rect は新しい既定値で上書きしない。

### 3.2 横リサイズと DPI の分離

- [x] `_window_content_coordinate_scale()` の requested-width 比率を廃止する。
- [x] toolbar、検索欄、右寄せ余白、drawer の寸法は、安定した
  backing scale と明示 `ui_scale` だけから求める。
- [x] ウィンドウ幅を変更しても TIME / HISTORY / STATUS の高さと button 高さが不変であることを
  regression test にする。
- [x] Retina monitor 間の移動では、従来どおり正しい物理サイズへ追従させる。

### 3.3 Style より上のレイアウト

- [x] TIME / HISTORY に同じ固定幅ラベル列を設け、操作開始位置とベースラインを揃える。
- [x] Controls / Status surface の高さと内側余白を明示し、横幅に関係なく一定にする。
- [x] PARAMETERS toolbar を主操作行と補助情報行の 2 行へ整理する。
  - 主操作行: PARAMETERS、Search、Show inactive、Filters、MIDI
  - 補助情報行: filtered / total、hidden、Expand、Collapse、Shortcuts
- [x] RELINK は対象が 0 件なら独立した空行を描画しない。
- [x] MIDI clear や Range Edit の操作性は維持し、通常時の空白だけを減らす。

### 3.4 レイアウト揺れを止める固定 bottom drawer

- [x] Parameter table を可変長情報より先に配置する。
- [x] table の下に、DPI / UI scale のみに依存する固定高 bottom drawer を常設する。
- [x] drawer を Help と Runtime details の 2 領域に分け、それぞれを独立スクロール領域にする。
- [x] Help の hover / focus / click 連携を維持し、Description の長さが変わっても table を動かさない。
- [x] monitor alerts、profiler、diagnostics を Runtime details へ移す。
- [x] profiler の項目数、diagnostic 件数、details の折り返し、alert の出現・消滅があっても
  Parameter 行の Y 座標を変えない。
- [x] FRAME ERROR、WAIT、SAVE FAILED などの短い要約は上段 STATUS に残し、通知性を失わない。

新しい native window は作らない。第三ウィンドウ化には別 ImGui context / renderer、
window lifecycle、初期配置、WorkspaceState の拡張が必要で、今回の揺れ解消には過大である。

### 3.5 シャープな theme

- [x] window rounding は 0 のまま維持する。
- [x] child / frame / popup / scrollbar / grab / tab の rounding を概ね現在の半分へ下げる。
- [x] frame、cell、section の縦余白を少し詰め、文字と control のベースラインを揃える。
- [x] クリック領域を過度に小さくせず、既存 contrast と keyboard focus 表示を維持する。

### 3.6 Description の完全化

- [x] 17 primitive の明示 parameter 129 件へ、日本語の具体的な Description を記述する。
- [x] 32 effect の明示 parameter 176 件へ、日本語の具体的な Description を記述する。
- [x] primitive / effect / preset の自動 `activate` には、種類ごとの共通 Description を与える。
- [x] global Style 3 件と Layer Style 2 件へ Description を記述する。
- [x] `sketch/presets/` の first-party preset metadata にも Description を記述する。
- [x] 既存 NumPy docstring と意味が食い違わない 1〜2 文にし、単なる引数名の言い換えにしない。
- [x] 複雑な docstring parser は追加せず、`ParamMeta` / meta spec に明示して source of truth を保つ。
- [x] first-party metadata の Description が空なら失敗する coverage test を追加する。
- [x] 外部ユーザー定義 operation では Description を optional のまま保ち、既存 fallback を維持する。

### 3.7 Favorite icon

- [x] bundled Noto Sans JP から U+2605 / U+2606 だけを追加 merge し、
  `★ / ☆` をフォント依存の `?` にしない。
- [x] favorite の選択状態、tooltip、永続化の既存挙動は変えない。
- [x] font atlas へ追加 glyph range が渡ることを test する。

### 3.8 MIDI learn

- [x] 未割当 vec3 を X / Y / Z、RGB を R / G / B と表示し、`+` を除く。
- [x] scalar を V と表示し、`MIDI +` を廃止する。
- [x] learn 待機中も X… / Y… / Z… / V… の同じ系列で表示し、`?` を使わない。
- [x] 割当済み表示も component 名と CC 番号の関係を保ちつつ、同じ系列へ統一する。
- [x] X / Y / Z と R / G / B は MIDI cell を厳密に等幅 3 分割する。
- [x] V button は MIDI cell の利用可能幅いっぱいを使う。
- [x] learn、cancel、assign、unassign、LIVE / FROZEN の意味と tooltip は維持する。

## 4. 主な変更対象

- `src/grafix/resource/default_config.yaml`
- `src/grafix/core/runtime_config.py`
- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/interactive/parameter_gui/table.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/theme.py`
- `src/grafix/interactive/parameter_gui/help_pane.py`
- `src/grafix/interactive/parameter_gui/monitor_bar.py`
- `src/grafix/interactive/parameter_gui/diagnostics_panel.py`
- `src/grafix/interactive/parameter_gui/profiler_panel.py`
- `src/grafix/interactive/parameter_gui/pyglet_backend.py`
- `src/grafix/core/primitive_registry.py`
- `src/grafix/core/effect_registry.py`
- `src/grafix/api/preset.py`
- `src/grafix/core/primitives/*.py`
- `src/grafix/core/effects/*.py`
- `src/grafix/core/parameters/style_ops.py`
- `src/grafix/core/parameters/layer_style.py`
- `sketch/presets/**/*.py`
- 関連する `tests/core/`、`tests/interactive/parameter_gui/`、`tests/interactive/`

## 5. 検証

### 5.1 自動テスト

- [x] default config と削除した column weight 契約を検証する。
- [x] 2 種類以上のウィンドウ幅で、3 固定列が不変かつ Value だけが伸びることを検証する。
- [x] 横リサイズ前後で toolbar / drawer の高さが不変であることを検証する。
- [x] profiler なし / 多行、diagnostics 0 件 / 多件、Help 未選択 / 長文で
  table の予約領域が不変であることを検証する。
- [x] favorite glyph range、MIDI の表示文字と button 幅を検証する。
- [x] first-party Description completeness を検証する。
- [x] diagnostics の Copy / Dismiss / action dispatch、profiler 内容、Help 選択連携の既存テストを維持する。
- [x] `ruff check src/grafix tests sketch/presets` を実行する。
- [x] `mypy src/grafix` を実行する。
- [x] `PYTHONPATH=src pytest -q` を実行する。

### 5.2 実機確認

- [x] 新規既定幅 1100 px で Value slider が十分に長いことを確認する。
- [x] 1100 px からさらに横へ広げ、Value 以外の 3 列幅が変わらないことを確認する。
- [x] 横へ広げても TIME / HISTORY / STATUS と bottom drawer の高さが変わらないことを確認する。
- [x] diagnostics / profiler の行数を変え、Parameter 行が上下しないことを確認する。
- [x] Help の短文 / 長文を切り替え、Parameter 行が上下しないことを確認する。
- [x] favorite が `★ / ☆` で表示され、`?` にならないことを確認する。
- [x] X / Y / Z、R / G / B、V の learn / cancel / unassign と幅を確認する。
- [x] Retina と通常 DPI で clipping、文字化け、過剰な余白がないことを確認する。

## 6. ローカル設定と保存済み Workspace

このリポジトリの ignored `.grafix/config.yaml` にも旧 `800 x 1000` がある。
実機確認時には、承認を得たうえでこのローカル設定だけを `1100 x 1000` へ合わせる。
これは Git 管理対象ではないため、最終差分には含まれない。

`data/output/workspace/**/*.json` の保存済み `inspector_rect` はユーザーの明示的な
workspace state とみなし、削除・上書きしない。保存済み Workspace を開いた場合はその幅を尊重し、
新規 Workspace に新しい既定値を適用する。

## 7. 完了条件

- [x] 要望 8 項目を実機で確認できる。
- [x] first-party parameter の Help に `No description...` が出ない。
- [x] Parameter table の通常時の上端と bottom drawer の高さが動的 telemetry で変化しない。
- [x] focused test、ruff、mypy、full pytest が成功する。
- [x] 完了項目と未完了項目を本計画へ反映し、実施結果を記録する。

## 8. 実施結果

2026-07-18 に全項目を実装した。

- 既定幅を 1100 px、実用最小幅を 760 px とし、Source / Parameter 250 px、
  Range 130 px、MIDI 165 px を固定した。1100 px から 1400 px への実機リサイズで、
  追加幅が Value だけへ入ることを確認した。
- Help と Runtime details を 176 px の固定 bottom drawer へ移した。実 ImGui を
  3 frame 描画し、Help なし / 長文、profiler なし / 50 行、diagnostics 0 / 40 件、
  alert 0 / 20 件を切り替えても table rect、root content 幅、root scroll が
  変化しない回帰テストを追加した。
- 実装レビューで検出した通常 DPI 時の drawer 2 px 超過も修正した。style の
  item spacing を予約高へ使い、root scrollbar が後発しないことを検証した。
- primitive 129 件、effect 176 件、共通 activate、Global Style 3 件、
  Layer Style 2 件、first-party preset metadata を補完した。生成 stub も同期した。
- `★ / ☆` の専用 glyph range を bundled Noto Sans JP から merge し、
  X / Y / Z、R / G / B、V の MIDI learn 表示と幅を統一した。
- 通常 DPI の実機で既定幅と 1400 px 幅を確認し、DPR 2 相当の実 ImGui test で
  固定列、toolbar、drawer、font atlas の backing-scale 追従を確認した。

検証結果:

- focused GUI / config / Description tests: 225 passed
- full pytest: 1433 passed、既存 multiprocessing resource tracker warning 6 件
- `ruff check src/grafix tests sketch/presets`: success
- `mypy src/grafix`: success
- `git diff --check`: success

未完了項目: なし。
