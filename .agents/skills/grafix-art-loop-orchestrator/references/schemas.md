# Grafix Art Loop JSON Schema（実務用ミニマム）

このファイルは、`run_one_iter.py` / `run_loop.py` と `ideaman` / `artist` / `critic` が受け渡す JSON 仕様を固定する。

## `CreativeBrief`（ideaman の出力）

```json
{
  "title": "string",
  "intent": "string",
  "constraints": {
    "canvas": { "w": 800, "h": 800 },
    "time_budget_sec": 30,
    "avoid": ["string"]
  },
  "variation_axes": ["string"],
  "aesthetic_targets": "string"
}
```

備考:
- `constraints.canvas` は不明なら `"unknown"` でもよい。

## `Artifact`（artist の出力）

```json
{
  "artist_id": "artist-01",
  "iteration": 1,
  "variant_id": "v1",
  "status": "success",
  "code_ref": "sketch.py",
  "callable_ref": "sketch:draw",
  "image_ref": "out.png",
  "seed": 12345,
  "params": {},
  "stdout_ref": "stdout.txt",
  "stderr_ref": "stderr.txt",
  "artist_summary": "変更内容の要約"
}
```

備考:
- `status` は `"success"` または `"failed"`。
- `code_ref` / `image_ref` は `variant_dir` 基準の相対パスまたは絶対パス。
- `callable_ref` は任意。未指定時は orchestrator が `code_ref` から `module:draw` を推定する。

## `Critique`（critic の出力）

```json
{
  "iteration": 1,
  "ranking": [
    { "variant_id": "v2", "score": 8.8, "reason": "..." },
    { "variant_id": "v1", "score": 7.9, "reason": "..." }
  ],
  "winner": {
    "variant_id": "v2",
    "why_best": "...",
    "what_to_preserve": "...",
    "what_to_fix_next": "...",
    "next_iteration_directives": [
      { "priority": 1, "directive": "...", "rationale": "..." }
    ]
  }
}
```

備考:
- `winner.variant_id` は `ranking` に存在し、かつ候補一覧に存在する ID にする。
