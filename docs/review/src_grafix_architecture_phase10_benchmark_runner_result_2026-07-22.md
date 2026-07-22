# Phase 10 benchmark runner 責務分割 実装結果

## 結論

Phase 9 の read-only snapshot を基準に、benchmark harness を次の一方向構成へ分割した。

```text
schema <- definition
schema <- metrics
schema + definition + metrics <- executor
definition <- workload providers <- catalog
catalog + executor <- runner
```

実際の依存は `runner.py -> catalog.py + executor.py` で composition し、`executor.py` は catalog/workload を知らない。`runner.py` は 76 行で、公開 symbol は `run_case_isolated` だけである。旧 symbol の re-export shim は置いていない。

provider 間の依存は、共有 fixture を持つ次の公開 API 参照だけに限定した。

- `parameter_edit_benchmark -> parameter_hotpath_benchmark`
- `interactive_scenario_benchmark -> parameter_hotpath_benchmark + renderer_benchmark`

それ以外の provider 間依存、provider から sibling private symbol への参照、`system_benchmark.py` への renderer/parameter 責務の逆流は architecture gate で拒否する。

## 実装

### 基盤責務

- `definition.py`
  - immutable `CaseDefinition`
  - source fingerprint と `CaseSpec` 構築
  - 共通 case 定義 helper
- `catalog.py`
  - provider 収集
  - case ID 重複拒否
  - stable sort と suite/case 選択
- `metrics.py`
  - exact checksum
  - typed metric 構築
  - warm/cold output 集約
- `executor.py`
  - in-process measurement
  - calibration
  - fresh-process lifecycle
  - timeout/error/result validation
- `runner.py`
  - catalog と executor の composition
  - `python -m grafix.devtools.benchmarks.runner --child ...` entrypoint

### Workload provider

| provider | case 数 |
|---|---:|
| `effect_benchmark.py` | 44 |
| `remaining_effect_benchmark.py` | 40 |
| `primitive_benchmark.py` | 27 |
| `parameter_hotpath_benchmark.py` | 17 |
| `parameter_edit_benchmark.py` | 3 |
| `perf_hotpath_benchmark.py` | 3 |
| `interactive_scenario_benchmark.py` | 3 |
| `renderer_benchmark.py` | 12 |
| `mp_draw_benchmark.py` | 2 |
| `system_benchmark.py` | 11 |
| **合計** | **162** |

旧 runner 内の system switch は case 実行経路から除き、各 case を直接 setup/workload へ結び付けた。CLI、production callsite、test は canonical module へ更新した。

## Child lifecycle の修正

旧実装は `subprocess.TimeoutExpired` のときだけ process group を kill/reap しており、`KeyboardInterrupt` などの `BaseException` では child/grandchild を残し得た。

新 executor は `communicate()` からの全 `BaseException` で共通 cleanup を通す。

1. `start_new_session=True` で child group を作る。
2. `os.killpg(pid, SIGKILL)` で子孫を停止する。
3. process group の停止に失敗した場合は `process.kill()` を fallback として試す。
4. timeout 付き `communicate()`、必要なら timeout 付き `wait()` で reap を試す。
5. cleanup failure は元例外の note に残し、元の `BaseException` を常に優先して再送出する。

Fake process test では group kill、direct kill、communicate、wait の各失敗と timeout を固定した。加えて別 helper process へ実際に `SIGINT` を送り、child と grandchild が残らない integration test を追加した。

## Test の責務分割

旧 `test_runner.py` 1,298 行を次へ分割した。

- `test_benchmark_definition.py`
- `test_benchmark_catalog.py`
- `test_benchmark_metrics.py`
- `test_benchmark_executor.py`
- `test_benchmark_workloads.py`
- `test_benchmark_environment.py`
- `test_runner.py` は public composition の integration test のみ

`tests/architecture/test_benchmark_dependency_boundaries.py` は import graph の非循環性、layer ごとの禁止依存、provider 間の許可 edge、sibling private symbol 参照の禁止、runner の公開 surface と行数を固定する。

## Phase 9 snapshot との同値検証

### 基準の保全

- snapshot: `/tmp/grafix-architecture-phase9-reference/`
- outer manifest: `/tmp/grafix-architecture-phase9-reference-SHA256SUMS.sha256`
- outer/internal `shasum -a 256 -c` はともに成功した。

### 比較対象

旧 snapshot と working tree をそれぞれ独立した `cwd` / `PYTHONPATH` で実行した。

- 162 case の `benchmark list --json`
- smoke 6 case
- frozen representative 6 case の short / long
- process-cold translate
- compile-cold collapse
- animated renderer
- MP light
- timeout
- deterministic calibration
- compatible pair に対する compare CLI
- 同一 run set に対する report CLI
- cancel / child cleanup

### 結果

- list JSON: **162 件、byte exact**
  - SHA-256: `15df6910b3d00ddd67cb93b0d841a39c0f78628fab273046060c751628e8814e`
- smoke / short / long / cold / renderer / MP / timeout:
  - case ID と順序
  - schema version
  - spec の意味字段
  - status / checksum / checksum kind / error
  - sample 数 / stats の `n`
  - metric identity と非時間 semantic value
  - contract identity/outcome と hard contract 全字段
  - **すべて一致**
- compare CLI: 同じ compatible pair に対する JSON が **byte-equivalent**
- report CLI: HTML が **byte exact**
  - SHA-256: `bb54eb950594b9e128513c6ade98838045242b2c0df46edb94effbbd3293ac66`
- calibration: 旧/new とも `iterations=10`、workload call 11 回
- exception: synthetic setup `ImportError` は旧/new とも status `error`、error text一致
- timeout: 旧/new とも CLI exit 1、case status `timeout`
- cancel:
  - 旧: `BaseException` 時は kill 0 回、reap なし
  - 新: kill 1 回、`communicate` 2 回で reap
  - 実 SIGINT integration test 成功
- 最終 process 一覧: benchmark orphan child **0 件**
- provider 所有権の最終監査後、parameter snapshot、animated soak、draw→realize→indices、multi-layer renderer の stable/changing 5 case を旧 snapshot/new tree で再実行し、同じ意味比較で **5 / 5 一致**した。smoke 6 case も最終 tree で再実行し **6 / 6 一致**した。

時間、RSS、distribution value、時間から導出した ratio、soft performance contract の actual operand は実行ごとに変動するため数値同値から除外した。ただし、それらの metric/contract identity と contract outcome は比較し、hard contract は operand を含めて完全一致させた。

## Source identity の intentional change

`CaseSpec.source_sha256` は implementation の `module.qualname`、source、support source file を hash する。責務移動はこの identity を意図的に変更するため、全 162 case で次が変わった。

- `source_sha256`: 162 / 162
- `compatibility_key`: 162 / 162

これは workload semantic の変更ではなく、source identity contract に従う構造変更である。旧/new run の直接 compare は全 smoke case で `case compatibility key differs` として exit 2 になった。`--allow-incompatible` は使用していない。compare CLI 自体の同値性は、同一の compatible pair を旧/new CLI の双方へ入力して確認した。

## 検証 artifact

全証跡は `/tmp/grafix-phase10-equivalence/` に保存した。

- `semantic-equivalence.json`
- `process-contracts.json`
- `run-files.json`
- `list-reference.json` / `list-current.json` / `list-current-final.json`
- `spec-identities-reference.json` / `spec-identities-current-final.json`
- `compare-reference.json` / `compare-current.json`
- `direct-old-new-compare.log`
- `real-sigint-test.log`
- `orphan-processes.txt`
- `reference-manifest-verify.log`
- `commands/*.json` / `commands/*.log`
- `runs/reference/**` / `runs/current/**`
- `reports/reference/**` / `reports/current/**`
- `final-moved/semantic-audit.json`
- `final-smoke/semantic-audit.json`
- `static-gates-final.txt`

## Gate

- focused benchmark/architecture pytest: **194 passed in 45.60s**
- full pytest: **3,806 passed in 292.62s**
- `ruff check src/grafix tests`: pass
- `mypy src/grafix`: pass（274 source files）
- `git diff --check`: pass
