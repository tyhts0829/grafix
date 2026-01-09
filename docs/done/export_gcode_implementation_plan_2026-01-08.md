# どこで: `docs/plan/export_gcode_implementation_plan_2026-01-08.md`。

# 何を: `src/grafix/export/gcode.py:export_gcode()` の実装計画（チェックリスト）をまとめる。

# なぜ: headless export（G-code）を最小実装で通し、interactive 依存なしにペンプロッタ向け出力を反復できる状態にするため。

# export_gcode 実装計画（2026-01-08）

## 0. 前提（現在地）

- 参照元: `docs/previous_project/gcode.py`
  - `GCodeParams` と `GCodeWriter.write()`（Stage 1/3: 直線補間のみ、Z/Feed 切替、Y 反転、原点オフセット、丸め、近接連結、範囲検証）。
- 入口: `src/grafix/api/export.py:Export` → `src/grafix/export/gcode.py:export_gcode`（現状は NotImplemented）。
- 入力: `Sequence[RealizedLayer]`（`src/grafix/core/pipeline.py`）。
  - `layer.realized.coords: (N,3) float32`
  - `layer.realized.offsets: (M+1,) int32`（polyline 境界）
- 制約: `src/grafix/export` は headless（`src/grafix/interactive` を import しない）。
- 座標系（既存の前提）:
  - `src/grafix/interactive/gl/utils.py:build_projection` は「キャンバス mm」を前提としている。
  - SVG export は `(x 右, y 下)` として扱っている（`src/grafix/export/svg.py`）。

## 1. ゴール（成功条件）

- `export_gcode(layers, path, ...) -> Path` が `.gcode` を保存し、保存先 `Path` を返す。
- 出力が決定的（同入力 → 同出力）で、ユニットテストで検証できる。
- 依存追加なし（標準ライブラリ + 既存の `numpy` + core）。
- 最小仕様として以下を実装する（参照元 `docs/previous_project/gcode.py` 相当）:
  - Header / Body / Footer
  - ペンアップ/ダウン（Z）と travel/draw feed の切替
  - 原点オフセット
  - 数値丸め（decimals）
  - Y 反転（y_down）
  - 紙（canvas_size）を超える描画の安全化（安全マージン込みの紙内クリップ + 紙外は Z up 移動）
  - 近接連結（connect_distance, 任意）
  - 範囲検証（bed_x_range/bed_y_range, 任意。範囲外は raise）

## 2. 最小仕様（今回ここまで）

### 2.1 公開 API（確定）

- `src/grafix/export/gcode.py` に `GCodeParams`（dataclass）と `export_gcode()` を実装する。
- `export_gcode` の形は以下で固定する:
  - `export_gcode(layers, path, *, canvas_size: tuple[float, float], params: GCodeParams | None = None) -> Path`
- `GCodeParams` の既定値は旧仕様を踏襲する（`y_down=False`, `origin=(91.0, -0.75)` など）。
- 現状の `feed_rate` 引数は未使用のため削除する（互換シムは作らない）。

### 2.2 G-code の基本方針

- 単位: `G21`（mm）。
- 入力座標は mm とみなし、そのまま出力する（スケール変換なし）。
- 座標: `G90`（絶対座標）。
- 移動: `G1` のみ（Stage 1 として線形補間のみ）。
- ペン制御: Z 軸（`G1 Z...`）で up/down を表現する（参照元踏襲）。
- フィード: travel/draw の切替時に `G1 F...` を出力する（mm/min）。

### 2.3 入力の走査と polyline 変換

- 各 `RealizedLayer` について、`coords/offsets` から polyline（`(N,2)`）を列挙する。
  - `end-start < 2` はスキップ（描画不能）。
- `coords[:, :2]` のみ使用し、`z` は無視する。

### 2.4 紙（canvas）安全クリップ（soft safety）

- 前提:
  - grafix の座標は mm。
  - ユーザーは紙サイズを `canvas_size=(W, H)` として draw を書く。
- 目的: 紙の外へ（安全マージン込みで）ペン先が到達しないようにする（紙めくれ防止）。
- 安全マージン:
  - `paper_margin_mm` を導入し、安全領域を `paper_safe_rect=[m, W-m]×[m, H-m]` とする（既定 `m=2.0` を想定）。
- クリップ方針:
  - クリップは **canvas 座標系で**行う（`y_down` / `origin` 前）。
  - polyline を線分列として走査し、各線分を `paper_safe_rect` に対してクリップする。
  - 紙外に出る瞬間:
    - 交点（境界）まで描画して `Z up` にする
    - 次に紙内へ入る交点まで `Z up` のまま直線移動する
    - そこで `Z down` にして描画を再開する
  - 紙外区間を「近接連結でショートカットして紙内に直線で繋ぐ」ことはしない（形状維持を優先し、必ずペンアップ移動にする）。

### 2.5 座標変換（canvas -> machine, 参照元踏襲）

順序は以下を基本とする（すべて mm 単位を前提）:

1. `canvas_size` を `canvas_width_mm/canvas_height_mm` として扱う
2. `y_down=True` の場合、Y 反転を適用（既定は `False`）
   - `y -> canvas_height_mm - y`（旧仕様: `canvas_height_mm` がある場合のみ厳密反転）
   - `canvas_height_mm` 未指定の場合は簡易反転 `y -> -y`
3. `origin=(ox, oy)` を加算（出力座標の原点合わせ）
4. 出力時は `decimals` 桁で丸め、`-0` を `0` に正規化する（決定的出力）

### 2.6 ベッド範囲検証（hard safety）

- `bed_x_range/bed_y_range` は 3D プリンタのベッドサイズを表す。
- 目的: ベッド外へ到達しうる移動は機械破損につながるため、**念のため例外で停止**する。
- 前提:
  - 紙安全クリップ（2.4）により、通常は出力が紙外へ出ない設計とする。
  - ただし入力の頂点/線分がベッド範囲外座標を含むこと自体は許容する（クリップ後に安全であればよい）。
- 方針:
  - 紙安全クリップ（2.4）→ 座標変換（2.5）→ 丸め（2.5）の後、**実際に出力する G-code の移動先座標**だけを対象に検証する。
  - `y_down` / `origin` を適用した **machine 座標系**で検証する。
  - 検証は出力と同じ「丸め後座標」で行う（`decimals` の影響で範囲外にならないことを保証する）。
  - travel（ペンアップ）/ draw（ペンダウン）を含む **すべての XY 移動（G1 X.. Y..）**について、
    `x in bed_x_range` かつ `y in bed_y_range` を満たさない場合は `raise` する。
  - raise 時はファイルを書き出さない（もしくは途中生成物を残さない）。

### 2.7 近接連結（connect_distance）

- 直前 polyline の終点 `prev_last` と次 polyline の始点 `start` の距離が `connect_distance` 未満なら連結扱い。
  - 連結時は、次 polyline 先頭での「ペンアップ/早送り」「2 点目前でのペンダウン/描画」切替を省略する。
  - 結果として `prev_last -> start` の短い線分が描かれる（意図した仕様として扱う）。
- 適用範囲:
  - レイヤ境界で `prev_last` をリセットする。
  - 紙クリップによって分断された箇所は **必ずペンアップ移動**にし、近接連結の対象にしない（2.4）。

### 2.8 Header / Footer（旧仕様踏襲）

- 参照元の出力行を踏襲する（3D プリンタ寄りの `G28`, `M107`, `M420 ...` を含める）。
  - Header:
    - `; ====== Header ======`
    - `G21 ; Set units to millimeters`
    - `G90 ; Absolute positioning`
    - `G28 ; Home all axes`
    - `M107 ; Turn off fan`
    - `M420 S1 Z10; Enable bed leveling matrix`
    - `; ====== Body ======`
  - Footer:
    - `; ====== Footer ======`
    - `G1 Z{z_up}`

## 3. 実装チェックリスト

### 3.1 `src/grafix/export/gcode.py`

- [ ] 1. 公開 API（2.1）でスタブを置換する
- [ ] 2. `GCodeParams` を追加（`frozen=True, slots=True`、NumPy スタイル docstring、型ヒント）
  - [ ] travel_feed / draw_feed
  - [ ] z_up / z_down
  - [ ] y_down（既定 False） / canvas_height_mm（任意、厳密反転用）
  - [ ] origin（既定 `(91.0, -0.75)`） / decimals
  - [ ] paper_margin_mm（安全マージン）
  - [ ] connect_distance（任意）
  - [ ] bed_x_range / bed_y_range（任意）
- [ ] 3. polyline 列挙ユーティリティを追加（`coords/offsets` から）
- [ ] 4. 紙安全クリップ（2.4）を実装（分断時は Z up 移動）
- [ ] 5. 座標変換（2.5）を実装（Y 反転 → origin）
- [ ] 6. ベッド範囲検証（2.6）を実装（範囲外は raise）
  - [ ] 入力頂点ではなく、出力予定の `G1 X.. Y..` 座標のみ検証する
- [ ] 7. G-code の組み立てを実装
  - [ ] header/body/footer の生成
  - [ ] Z/Feed 切替（参照元の「ライン開始前 Z up + travel」「2 点目前 Z down + draw」）
  - [ ] 連結判定（connect_distance。紙クリップ分断は除外）
  - [ ] コメント（layer 名 / polyline index を含めるか）
- [ ] 8. ファイル保存を実装（親ディレクトリ作成、UTF-8、改行 `\n`）

### 3.2 周辺導線（必要なら）

- [ ] 9. `src/grafix/api/export.py` から `canvas_size` を `export_gcode(..., canvas_size=...)` に渡す

### 3.3 テスト

- [ ] 10. `tests/export/test_gcode.py` を追加
  - [ ] 保存される・Path が返る
  - [ ] 決定的出力（2 回出力の一致）
  - [ ] 1 polyline の最小出力（header/body/footer の存在）
  - [ ] Y 反転（`canvas_height_mm` あり/なし）
  - [ ] origin と decimals の反映
  - [ ] 紙安全クリップ（紙外に出る区間で Z up になり、紙内復帰で Z down になる）
  - [ ] connect_distance の効き（polyline 境界では省略され、紙クリップ分断では省略されない）
  - [ ] 入力が bed 範囲外でも、クリップ後の出力が bed 範囲内なら例外にならない
  - [ ] bed_x_range/bed_y_range 範囲外（出力座標）で例外

### 3.4 最低限の確認コマンド

- [ ] 11. `ruff check src/grafix/export/gcode.py tests/export/test_gcode.py`
- [ ] 12. `mypy src/grafix/export/gcode.py`
- [ ] 13. `PYTHONPATH=src pytest -q tests/export/test_gcode.py`

## 4. 非ゴール（今回やらない）

- パス最適化（並び替え、最短化、TSP）
- 曲線（G2/G3）やスプライン、加減速制御
- レイヤ別の工具/ペン/色切替
- サーボ式ペン制御（Z 以外の M-code 等）
- 3D（Z）ジオメトリの反映

## 5. 事前確認（回答反映済み）

1. 座標単位は「grafix 座標 = mm」としてそのまま `G21` で出力してよい？；はい
2. `y_down` の既定はどうする？（例: 既定 True + `canvas_size` 必須で `y -> H - y` を使う / 既定 False で無変換）；旧仕様を踏襲して
3. Header/Footer は最小（`G21`,`G90`）でよい？ それとも参照元の `G28`/`M420` 等を含めたい？；旧仕様を踏襲して
4. ペン制御は参照元どおり Z 軸（`G1 Z...`）で進めてよい？（サーボ等が前提なら命令セットを決めたい）；はい
5. `origin` の既定値は参照元（`(91.0, -0.75)`）を採用する？ それとも `0,0`？；参照元である旧仕様を踏襲して
6. `connect_distance` を有効にした場合、レイヤ境界で連結判定をリセットする？（事故線の抑制）；はい
7. 範囲検証は参照元同様「共通 min/max」を採用する？ それとも `bed_x_range/bed_y_range` を分ける？；分ける。
8. 紙（canvas）を超える描画はどうする？；安全マージン込みでクリップし、紙外は Z up で移動する。
9. ベッド外へ到達する出力移動（G-code）はどうする？；機械破損リスクがあるため raise する。
10. 近接連結は紙クリップ分断にも適用する？；しない（紙外区間は必ずペンアップ移動）。

## 6. Interactive 連携（非ブロッキング案）

- 目的: 線数が多いケースでも、G キー押下で描画が固まらないようにする。
- 方針:
  - 「生 G-code を先に書いて後処理」は避け、最初から最終形（紙安全クリップ + ベッド検証 + 近接連結）を生成する。
  - G キー押下時は export をジョブ化し、別プロセスで `export_gcode` を実行する（メインは即 return）。
  - 結果（成功/失敗）だけをメインに通知する（進捗 UI は必要なら後で）。
