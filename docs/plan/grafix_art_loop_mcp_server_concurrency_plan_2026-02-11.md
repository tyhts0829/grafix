# Grafix Art Loop: MCPサーバ並列実行（tools/call）対応計画（2026-02-11）

作成日: 2026-02-11  
ステータス: 提案（未実装）

## 背景 / 問題

- 現状の MCP サーバ（`.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py`）は **単一プロセス・単一ループ**で `tools/call` を処理している。
- `art_loop.run_codex_artist` は内部で `subprocess.run()` により `codex exec` を同期実行しており、1 リクエスト実行中は次の `tools/call` を処理できない。
- orchestrator が `v01〜v04` を **同一 MCP サーバへ並列に投げる**と、2〜4件目はサーバ側で待ち行列になり、クライアント側の待ち時間（例: 60 秒）が尽きて **“4件ともタイムアウト”** し得る。

## 目的

- `tools/call` を複数同時に受けても、`art_loop.run_codex_artist` が **最大 N 並列**で実行開始できるようにする（待ち行列起因のタイムアウトを減らす）。
- stdout/stderr/成果物の出力境界（`variant_dir` 配下のみ）は維持する。
- まずは **ツール契約（同期レスポンス）を維持**して改善し、必要なら次段で非同期ジョブ化へ進む。

## 非目的

- `codex exec` 自体の速度改善（モデル・ネットワーク・生成品質の最適化）はこの計画の対象外。
- すべての MCP メソッドをフル実装すること（必要最小限に留める）。

## 方針（段階的）

### A) 同期契約のまま並列化（第一候補）

- `tools/call` を受けたら、処理本体（`subprocess.run()`）を **ワーカースレッド**へ投げ、サーバ本体は次のリクエスト受付へ戻る。
- レスポンスは JSON-RPC の `id` で紐付けられるので、**完了順に out-of-order 返信**して問題ない（stdout への書き込みは 1 箇所に直列化）。
- 最大並列数は環境変数等で制御し、過負荷時は **即時に “busy” エラー**を返してクライアント側でリトライ/並列数調整できるようにする。

### B) それでもタイムアウトする場合はジョブ型へ（第二候補）

- `art_loop.run_codex_artist` を「開始」ツールと「結果取得」ツールに分割する。
- `start` は即時に `job_id` を返し、`poll/wait` で状態と成果物パスを取得する（クライアントの単発待ち時間に依存しない）。
- orchestrator 側の呼び出しフロー変更が必要。

## 実装タスク（チェックリスト）

### 0) 現状確認と再現

- [ ] orchestrator の並列呼び出し点を特定する（同一 MCP サーバへ同時 `tools/call` している箇所）。
- [ ] `v01〜v04` 並列時のタイムアウト再現条件を固定する（クライアント側 timeout 値・再現手順）。

### 1) サーバ側: 並列実行の基盤（A案）

- [ ] `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py` を **リクエスト受付**と **実処理**に分離する。
- [ ] `ThreadPoolExecutor`（または同等）を導入し、`art_loop.run_codex_artist` を executor に投げる。
- [ ] stdout への JSON Lines 書き込みを **単一 writer** に直列化する（lock/queue どちらでもよいが、メッセージのバイト列が混ざらないこと）。
- [ ] 例外時も JSON-RPC error を返す（既存と同等のエラーハンドリングを維持）。

### 2) 資源競合の抑制

- [ ] 最大並列数 `ART_LOOP_MAX_CONCURRENCY`（仮）を導入し、デフォルトを `4`（orchestrator の v01〜v04 想定）にする。
- [ ] 受付済みの実行数が上限に達したら、`tools/call` に対して **即時エラー**（例: `server busy`）を返す。
- [ ] `codex exec` の状態衝突を避けるため、`CODEX_HOME` を `variant_dir/.codex_home` に固定する（`TMPDIR` は既に `variant_dir/.tmp`）。

### 3) 観測性（最小）

- [ ] `run_codex_artist` の返却 JSON に `server_received_ms` / `server_started_ms` / `server_finished_ms`（仮）を追加し、待ち行列時間が見えるようにする（既存フィールドは維持）。

### 4) ドキュメント更新

- [ ] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` に「並列数」「busy 時の扱い」「推奨 timeout」を追記する。
- [ ] 必要なら `docs/plan/grafix_art_loop_codex_child_artist_mcp_plan_2026-02-10.md` の関連箇所へリンクを追記する（仕様の所在を一本化）。

### 5) 検証

- [ ] `v01〜v04` を同時に投げても、サーバ側で **4件が即時に開始**されること（開始時刻が近接）。
- [ ] クライアントの単発 timeout より前に「処理開始が遅延する」状況が解消していること（待ち行列起因のタイムアウトが消える）。
- [ ] `variant_dir` 境界が破られないこと（成果物/ログが混ざらない）。

## 受け入れ条件（DoD）

- [ ] `M=4` の並列 `tools/call` で、待ち行列起因のタイムアウトが発生しない（orchestrator の再現条件下）。
- [ ] 出力境界（`variant_dir`）と tool 契約（同期レスポンス）は維持される。
- [ ] 最大並列数を設定でき、過負荷時は “busy” が即時に返る。

## 追加メモ（B案に進む判断）

- A案でも「1 件あたりの実行時間がクライアント timeout を超える」場合は、B案（ジョブ型）へ移行する。
- その場合の追加ツール案: `art_loop.start_codex_artist` / `art_loop.poll_job` / `art_loop.cancel_job`。
