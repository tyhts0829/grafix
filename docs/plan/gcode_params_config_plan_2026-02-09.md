# GCodeParams を config.yaml で制御する計画（2026-02-09）

目的:

- `src/grafix/export/gcode.py` の `GCodeParams`（フィード、Z、原点、Y 反転、最適化など）を `config.yaml` で設定できるようにする。
- `export_gcode(..., params=None)` でも **プロジェクトごとの設定**（`./.grafix/config.yaml`）が効く状態にする。

背景 / 現状:

- `src/grafix/export/gcode.py` は `params is None` の場合に `GCodeParams()` をそのまま使うため、既定値がコードに固定されている。
- `src/grafix/core/runtime_config.py` は同梱 `src/grafix/resource/default_config.yaml` をベースに、`./.grafix/config.yaml` 等で上書きできる。
  - ただしマージは **トップレベルの浅い上書き**（ネストは部分マージされない）なので、`export:` を上書きする場合は `export:` 配下を丸ごと持つ運用が前提。

---

## 0) 事前に決める（あなたの確認が必要）

- [x] 設定キーの置き場所: `export.gcode` 配下にまとめる
  - 例: `export.png.scale` と同じ名前空間に寄せる
- [x] `params` の優先順位: `export_gcode(..., params=...)` を最優先し、`params=None` のときだけ config を使う
- [ ] `./.grafix/config.yaml` が `export:` を上書きしている場合の扱い:
  - A. 省略された `export.gcode` は **エラー**にする（設定の真実を YAML に寄せる / 実装が単純）
  - B. 省略された `export.gcode` は **コード側既定**へフォールバック（古い config でも動く）

→ 採用: A（エラー）

---

## 1) 変更後の仕様（挙動の約束）

- `config.yaml` に `export.gcode` を追加し、値が `GCodeParams` に対応する。
- `export_gcode(..., params=None)` の場合:
  - `runtime_config()` から `export.gcode` を読み、`GCodeParams` の既定値を **config 由来**で決める。
- `export_gcode(..., params=GCodeParams(...))` の場合:
  - config は参照せず、渡された `params` をそのまま使う。

### 1.1 config スキーマ案（例）

```yaml
export:
  png:
    scale: 8.0

  gcode:
    travel_feed: 3000.0          # [mm/min]
    draw_feed: 3000.0            # [mm/min]
    z_up: 3.0                    # [mm]
    z_down: -1.0                 # [mm]
    y_down: true                 # bool
    origin: [154.019, 14.195]    # [mm] (x, y)
    decimals: 3                  # int
    paper_margin_mm: 2.0         # [mm]
    bed_x_range: null            # null or [min, max]
    bed_y_range: null            # null or [min, max]
    bridge_draw_distance: 0.5    # null to disable
    optimize_travel: true
    allow_reverse: true
    canvas_height_mm: null       # null -> export_gcode(canvas_size=...) の高さを使う
```

---

## 2) 実装タスク（チェックリスト）

### 2.1 同梱 default_config.yaml の拡張

- [x] `src/grafix/resource/default_config.yaml` に `export.gcode` を追加（上記スキーマで全キーを明示）

### 2.2 プロジェクトローカル config の更新

- [x] `./.grafix/config.yaml` にも `export.gcode` を追加（浅い上書きで `export` が置換されるため）

### 2.3 runtime_config に読み取りを追加

- [x] `src/grafix/core/runtime_config.py`:
  - [x] `RuntimeConfig` に G-code 設定の格納先を追加（`gcode: GCodeExportConfig`）
  - [x] `export.gcode` を読み取り、型を正規化する（`origin` や `bed_*_range` は 2 要素配列→タプル）
  - [x] `y_down/optimize_travel/allow_reverse` は bool として解釈する

### 2.4 export_gcode の既定 params を config 由来に変更

- [x] `src/grafix/export/gcode.py`:
  - [x] `params is None` の場合に `runtime_config()` から値を取り、`GCodeParams(...)` を構築する
  - [x] `params` が明示されている場合は現状通りそれを使う

### 2.5 テスト

- [x] `tests/core/test_runtime_config.py`:
  - [x] 同梱 defaults で `export.gcode` が読み取れることを最低限確認（値の一部だけでよい）
- [x] `tests/export/test_gcode.py`:
  - [x] `set_config_path(tmp_config)` を使い、`params=None` で `export.gcode` が反映されることを 1 ケース追加
    - 例: `origin=[0,0]`, `y_down=false`, `decimals=3`, `paper_margin_mm=0` を設定し、出力座標が期待通りになること

### 2.6 ドキュメント

- [x] `README.md` の Configuration に `export.gcode` の例（最小）を追記
  - 併せて「`export:` を上書きするとネストは部分マージされない」注意を短く入れる

---

## 3) 変更箇所（ファイル単位）

- [x] `src/grafix/resource/default_config.yaml`
- [x] `.grafix/config.yaml`
- [x] `src/grafix/core/runtime_config.py`
- [x] `src/grafix/export/gcode.py`
- [x] `tests/core/test_runtime_config.py`
- [x] `tests/export/test_gcode.py`
- [x] `README.md`
