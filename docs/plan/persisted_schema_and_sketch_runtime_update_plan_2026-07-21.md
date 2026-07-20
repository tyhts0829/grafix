# 永続化スキーマ更新と sketch 実行復旧計画

- 作成日: 2026-07-21
- 状態: 実装・自動検証完了
- 対象: ローカルに存在する Grafix 永続化データと、通常保守対象の `sketch/` スクリプト
- 原則: runtime に旧 schema reader、互換 wrapper、shim、暗黙変換を追加しない

## 1. 目的

現行実装は ParamStore schema v3 だけを受理する一方、ローカルの保存データは
すべて versionless、v1、または v2 のままである。この不一致により、
`sketch/readme/grn/6.py` などが GUI を開く前に
`UnsupportedParamStoreSchemaError` で停止する。

旧形式を runtime で受け続けるのではなく、既存データを一度だけ現行形式へ更新する。
同時に、strict API 化で壊れた通常の sketch を現行 API へ直接書き換え、
今後同種の不整合を検出するスモークテストを追加する。

## 2. 監査結果

### 2.1 ParamStore

対象は計 76 ファイルで、現行 v3 は 0 件。

| 保存形式 | 件数 |
|---|---:|
| versionless | 67 |
| schema v1 | 5 |
| schema v2 | 4 |
| schema v3 | 0 |

内訳:

- `data/output/param_store/**/*.json`: 75 件
- `.grafix/data/output/param_store/**/*.json`: 1 件
- session recovery: 1 件
- JSON 破損、JSONL、corrupt backup: 0 件

現行との差分:

- `schema_version` 欠落: 67 件
- `variations` 欠落: 67 件
- `ui` 全体欠落: 4 件
- `ui.effect_order_overrides` 欠落: 72 件
- `ui.locked_parameters` / `favorite_parameters` 欠落: 各 67 件
- state に対応する `explicit` 不足: 計 256 entry
- `effect_steps.n_inputs` 欠落: 367 entry
- 廃止済み `meta.nudge_step`: 112 entry
- 現行では許可しない layer-style MIDI CC: 2 entry

全体で `states` / `meta` は各 5,545 entry、`effect_steps` は 391 entry。
メモリ上の試験変換では、全 entry を保持したまま現行 parser の issue を 0 件にできる。

### 2.2 その他の永続化データ

- Capture manifest:
  - 9 件すべて v2、現行は v3。
  - v2 の重複 top-level field は `frame` / `output` と全件一致し、無損失変換可能。
- WorkspaceState:
  - 11 件すべて現行 v1。
  - 現行 loader と writer の canonical 形式に一致済み。
- MIDI snapshot:
  - 68 件中 67 件は現行の canonical mapping。
  - `data/output/midi/readme/3.json` だけが 0 byte。
- Runtime config:
  - `.grafix/config.yaml` と packaged default は現行 version 1。
- BenchmarkRun:
  - active `data/output/benchmarks/runs/*.json` は 19 件すべて非現行。
  - 16 件は versionless、3 件は v2、現行は strict v4。
  - 旧 run には raw sample、MAD、source/environment fingerprint、
    case source hash 等がないため、値を捏造せず v4 へ変換することはできない。

### 2.3 sketch

通常保守対象は、生成履歴である `sketch/agent_loop/runs/` を除く 65 Python ファイル。
そのうち実行入口を持つものは 52 件。

現時点で確認した現行 API との不一致:

- `sketch/main.py`: scalar 引数へ tuple を渡す `E.fill(angle=...)`
- `sketch/readme/{14,17,18}.py`,
  `sketch/readme/grn/{3,4,17}.py`:
  廃止済み `type_index`、旧 `mode` を使う sphere/polyhedron
- `sketch/work/{1,2,3}.py`: 廃止済み `Layer + Layer`
- `sketch/readme/9.py`: 未対応 `midi_mode="7bit_rel"`
- `sketch/readme/12.py`: 参照先の `layout_intersections` preset が欠落
- `sketch/readme/readme2.py`: preset autoload と重複する未使用 `logo` import

`sketch/presets/logo.py` の tuple 形式 `dash_length` は、現行 effect が明示的に
サポートする sequence 指定であり、旧 API ではなかったため変更しない。

`sketch/agent_loop/runs/` は生成時点の source/provenance を保存する履歴なので、
通常 sketch として一括改変しない。

## 3. 実装方針

### 3.1 runtime は現行 schema 専用のままにする

- v1/v2 reader、起動時自動 migration、互換 wrapper は追加しない。
- 旧データの変換ロジックは一度だけ実行し、恒久的な runtime code として残さない。
- 変換前後の件数、hash、parser 診断を記録し、黙って entry を失わない。

### 3.2 ParamStore は decode → canonical encode で確定する

変換前に次の機械的な構造更新を行い、その後は現行 codec だけで canonical 化する。

1. top-level と `ui` の必須 field を補完し、`schema_version=3` にする。
2. 各 state/meta key に対応する `explicit=False` を補完する。
3. `meta.nudge_step` を削除する。既存 112 entry はすべて `null` であり、値の損失はない。
4. layer-style の旧 MIDI CC 2 entry は、parameter value を保持して `cc_key=null` にする。
5. 欠落した `effect_steps.n_inputs` は現行 effect registry から確定する。
   - unary: 362 entry
   - binary: `clip` 3、`boolean` 1、`warp` 1
6. session recovery では live override を保持する。
7. 現行 codec で decode/encode し、再 decode issue 0、
   2 回目の encode が同一、entry 件数不変を要求する。

### 3.3 履歴データを偽の新 schema にしない

- Capture manifest 9 件は、重複 field の削除だけで v3 に無損失更新する。
- BenchmarkRun 19 件は v4 に偽装変換しない。
  - exact byte を保ったまま legacy archive へ移す。
  - 現行コードで新しい v4 smoke run を作る。
  - active report を v4 run から再生成する。
- 独立した過去分析 JSON は BenchmarkRun ではないため変更しない。

## 4. 実装手順

### Phase 0: 変更前記録

- [x] 対象ファイル一覧、schema 内訳、SHA-256、entry 件数を記録する。
- [x] 既存の大量差分と今回の変更範囲を分離する。
- [x] 変換処理を dry-run し、予定差分と修復項目を確認する。

### Phase 1: 永続化データ更新

- [x] ParamStore 76 件を schema v3 へ無損失更新する。
- [x] 全 ParamStore を現行 strict codec で読み、issue 0 を確認する。
- [x] primary/recovery の選択と live override 保持を確認する。
- [x] Capture manifest 9 件を schema v3 へ更新する。
- [x] 0 byte の MIDI snapshot を canonical な空 snapshot にする。
- [x] WorkspaceState 11 件と runtime config 2 件が現行のまま有効であることを再確認する。
- [x] 旧 BenchmarkRun 19 件を byte-preserving archive へ移す。
- [x] 現行 benchmark v4 smoke run と report を生成する。

### Phase 2: sketch の現行 API 化

- [x] scalar、sphere/polyhedron の旧引数を現行引数へ直接変更する。
- [x] `Layer + Layer` を明示的な scene tuple/list に変更する。
- [x] `midi_mode="7bit_rel"` を現行 mode へ変更する。
- [x] preset autoload を含む正しい config 条件で 52 entrypoint を再監査する。
- [x] 新たに判明した欠落 preset と重複 import を修正する。
- [x] 互換 alias、旧引数受付、値の暗黙変換は追加しない。

### Phase 3: 回帰テスト

- [x] 通常保守対象の全 Python ファイルを AST parse する。
- [x] 52 entrypoint を subprocess で隔離し、GUI を開かずに
  空 ParamStore から `draw(0.0)` を構築・scene 正規化する。
- [x] 52 entrypoint の既定 ParamStore path がすべて schema v3 または missing であることを確認する。
- [x] 保存値を使う headless `RenderSession` で代表 sketch を描画する。
  - `sketch/readme/grn/6.py`
  - `sketch/main.py`
  - `sketch/readme/9.py`
  - `sketch/readme/{14,17,18}.py`
  - `sketch/readme/grn/{3,4,17}.py`
  - `sketch/work/1.py`
  - `sketch/presets/logo.py`
- [ ] `sketch/readme/grn/6.py` の通常 GUI 起動で schema error が出ないことを確認する。
  - 実行環境に macOS display がなく、Computer Use 側の Mac も lock 中だったため、
    実ウィンドウだけは未確認。通常起動と同じ recovery load、および保存値を使う
    1 frame 描画は成功している。
- [x] schema/capture/MIDI/sketch の回帰テストを実行し、sketch smoke を追加する。

### Phase 4: 全体検証と記録

- [x] 対象 pytest を実行する。
- [x] 全 pytest を実行する。
- [x] `mypy src/grafix` を実行する。
- [x] 変更対象の Ruff を実行する。
- [x] `git diff --check` を実行する。
- [x] 変換件数、保持件数、修復内容、sketch smoke 結果を本書へ追記する。

## 5. 完了条件

- ローカルの ParamStore 76 件がすべて schema v3 で、strict decode issue が 0 件。
- Capture manifest 9 件がすべて schema v3。
- active benchmark run がすべて schema v4。
- Workspace/config/MIDI を含む起動時永続化データが現行 reader で有効。
- 通常保守対象の 52 sketch entrypoint が旧 API を使わず、GUI なしスモークを通過。
- `sketch/readme/grn/6.py` が通常起動して、提示された schema error が再発しない。
- runtime に後方互換 shim や旧 schema fallback が追加されていない。

## 6. 実装対象外

- `sketch/agent_loop/runs/` 内の生成履歴 source の一括書き換え。
- 欠落した raw sample を合成して旧 benchmark を v4 に見せかけること。
- 今回の依頼と無関係な既存 Ruff 違反や既存差分の整理。
- commit、push、依存追加。

## 7. 実施結果

### 7.1 永続化データ

- ParamStore:
  - 76/76 件を schema v3 へ更新。
  - strict decode issue 0、二重 encode 安定 76/76。
  - `states` 5,545、`meta` 5,545、`effect_steps` 391 を保持。
  - `explicit` 256 件を補完し、`nudge_step=null` 112 件を削除。
  - 旧 layer-style CC 2 件を `null` 化。
  - recovery の mtime と選択順を保持。
  - `readme/grn/6.json` は 139 state を primary から正常ロード。
- Capture manifest:
  - 9/9 件を schema v3 へ更新。
  - 現行 dataclass との往復一致、config hash 一致。
- MIDI / Workspace / config:
  - MIDI 68/68 件、計 377 assignment を現行 loader で確認。
  - 空だった `readme/3.json` は canonical な `{}\n` に修復。
  - Workspace 11/11 件、config 2/2 件を現行 strict loader で確認。
- Benchmark:
  - 旧 19 run、計 697,796 byte を exact-byte のまま `legacy/` へ移動。
  - active v4 run を 1 件生成し、162/162 case が `ok`、warning 0。
  - `report.html` と `warnings.json` を現行 run から再生成。

### 7.2 sketch と preset autoload

- 通常保守対象 65 Python file の AST parse に成功。
- 52/52 entrypoint が、実際の preset autoload 順序を再現する独立 subprocess
  で 1 frame 描画に成功。
- `type_index` / `mode`、旧 MIDI mode、`Layer + Layer`、scalar 不一致を
  現行 API へ直接変更。
- 欠落していた `layout_intersections` を正式な project preset として実装し、
  API stub も再生成結果と同期。
- 同じ preset source を `__main__` と autoload package の別名で二重実行しないよう、
  autoload は既ロードの同一 source path を一度だけ扱う。別ファイルで同名の
  preset は従来通り拒否し、duplicate 許容や互換 shim は追加していない。
- 保存値を使う代表 11 sketch と `readme/grn/6.py` を headless 描画し、全件成功。

### 7.3 検証

- 対象 pytest: 255 passed。
- 全 pytest: 3,311 passed、1 skipped。
  - multiprocessing resource tracker の既知 warning 6 件のみ。
- mypy: 238 source file、issue 0。
- 変更対象 Ruff: pass。
- stub sync: pass。
- `git diff --check`: pass。
- repo 全体 Ruff は今回対象外の既存 25 件
  （`.agents` 3 件、未変更 sketch の unused import 22 件）のため非 0。
