# Grafix Art Loop JSON Schema（実務用ミニマム）

このファイルは、grafix-art-loop（orchestrator / ideaman / artist / critic）が受け渡す JSON 仕様を固定する。

重要:
- ここに書かれている JSON は **型と構造の例**。値の丸写しは禁止（固定化して作品づくりを壊す）。
- 出力側（ideaman/artist/critic）は、毎回 “作る” こと（特に ideaman の `CreativeBrief`）。

## `CreativeBrief`（ideaman の出力）

```json
{
  "title": "<string>",
  "intent": "<string>",
  "constraints": {
    "canvas": { "w": "<int>", "h": "<int>" },
    "time_budget_sec": "<int>",
    "avoid": ["<string>"]
  },
  "composition_template": "<string>",
  "layers": {
    "hero": { "intent": "<string>", "constraints": ["<string>"] },
    "support": { "intent": "<string>", "constraints": ["<string>"] },
    "texture": { "intent": "<string>", "constraints": ["<string>"] }
  },
  "design_tokens": {
    "vocabulary": { "motifs": ["<string>"], "edges": "<string>" },
    "palette": { "name": "<string>", "colors": ["<hex>"] },
    "stroke": { "widths": ["<float>", "<float>"], "caps": "<string>" },
    "spacing": { "margin": "<float>", "gutter": "<float>", "density": "<float>" },
    "grid_unit": "<int>",
    "noise": { "scale": "<float>", "amount": "<float>", "anisotropy": "<float>" }
  },
  "variation_axes": ["<string>"],
  "aesthetic_targets": "<string>"
}
```

備考:
- `constraints.canvas` は不明なら `"unknown"` でもよい。
- `composition_template` は構図テンプレ（例: `grid` / `thirds` / `diagonal` / `center_focus` / `asym_balance`）。
- `layers` は「主役→副要素→テクスチャ」を必ず分ける（中身は最小でよい）。
- `design_tokens` は “デザインのレバー” を固定する。値は自由だが、キーはなるべく増やし過ぎない。

## `ArtistContext`（orchestrator → artist）

```json
{
  "run_id": "<string>",
  "iteration": "<int>",
  "variant_id": "<string>",
  "artist_id": "<string>",
  "mode": "<exploration|exploitation>",
  "creative_brief": {},
  "baseline_artifact": null,
  "critic_feedback_prev": null,
  "exploration_recipe": {
    "recipe_id": "<string>",
    "primitive_key": "<string>",
    "effect_chain_key": "<string>",
    "primitive_hints": ["<string>"],
    "effect_hints": ["<string>"]
  }
}
```

備考:
- `mode` は `exploration` / `exploitation`。
- `mode="exploration"` のときは `exploration_recipe` を付与する（同一 iteration 内で `primitive_key` と `effect_chain_key` は重複させない）。
- exploration では原則 `baseline_artifact` / `critic_feedback_prev` を渡さない（自由度確保）。

## `Artifact`（artist の出力）

```json
{
  "artist_id": "<string>",
  "iteration": "<int>",
  "variant_id": "<string>",
  "mode": "<exploration|exploitation>",
  "status": "<success|failed>",
  "code_ref": "<path>",
  "callable_ref": "<module:callable>",
  "image_ref": "<path>",
  "seed": "<int>",
  "params": {
    "design_tokens_used": {
      "custom_primitive_name": "<string>",
      "custom_effect_name": "<string>"
    }
  },
  "stdout_ref": "<path>",
  "stderr_ref": "<path>",
  "artist_summary": "<string>"
}
```

備考:
- `status` は `"success"` または `"failed"`。
- `code_ref` / `image_ref` は `variant_dir` 基準の相対パスまたは絶対パス。
- `callable_ref` は任意。未指定時は orchestrator が `code_ref` から `module:draw` を推定する。
- `mode` は `exploration` / `exploitation`。未指定でもよいが、あると差分方針が安定する。
- `params.design_tokens_used` には実際に採用したトークン（最終値）を入れる。
  - exploration のときは `recipe_id` / `primitive_key` / `effect_chain_key` を必ず入れる。
  - 全 mode で `custom_primitive_name` / `custom_effect_name` を必ず入れる。

## `Critique`（critic の出力）

```json
{
  "iteration": "<int>",
  "ranking": [
    { "variant_id": "<string>", "score": "<float>", "reason": "<string>" }
  ],
  "winner": {
    "variant_id": "<string>",
    "why_best": "<string>",
    "what_to_preserve": "<string>",
    "what_to_fix_next": "<string>",
    "locked_tokens": ["<design_tokens.<group>.<leaf>>"],
    "mutable_tokens": ["<design_tokens.<group>.<leaf>>"],
    "next_iteration_directives": [
      {
        "priority": "<int>",
        "token_keys": ["<design_tokens.<group>.<leaf>>"],
        "directive": "<string>",
        "success_criteria": "<string>",
        "rationale": "<string>"
      }
    ]
  },
  "skill_findings": [
    {
      "priority": "<int>",
      "problem": "<string>",
      "evidence": "<string>",
      "proposed_change": "<string>",
      "target_files": ["<path>"]
    }
  ]
}
```

備考:
- `winner.variant_id` は `ranking` に存在し、かつ候補一覧に存在する ID にする。
- `locked_tokens` / `mutable_tokens` で「保持/変更」を明示する（critic の最重要アウトプット）。
- `locked_tokens` / `mutable_tokens` / `token_keys` は `design_tokens.` で始まる
  **フルパスの leaf キーのみ**を許可する。
  - 例: `design_tokens.spacing.margin` / `design_tokens.noise.scale`
  - 非許可: `spacing` / `vocabulary.motifs` / `design_tokens.spacing`
- `next_iteration_directives` は最大 3 件程度に絞る。
- winner の正本は `critique.json` の `winner` とし、`winner_feedback.json` は作らない。
- `skill_findings` は任意。作品改善（`next_iteration_directives`）とは分離し、
  skill 運用改善に限定する。
- `skill_findings` を出す場合は推奨 3 件、最大 5 件に絞る。
- `skill_findings[].evidence` は run 内生成物（`Artifact` / `critique` / ログ）への参照を必須にする。

## `SkillImprovementReport`（run 末尾の改善レポート）

```json
{
  "run_id": "<string>",
  "generated_at": "<ISO8601>",
  "improvements": [
    {
      "priority": "<int>",
      "skill": "<orchestrator|critic|ideaman|artist>",
      "problem": "<string>",
      "evidence": "<string>",
      "proposed_change": "<string>",
      "target_files": ["<path>"],
      "expected_impact": "<string>"
    }
  ],
  "discovery_cost": [
    {
      "lookup": "<string>",
      "why_needed": "<string>",
      "how_to_preload": "<string>"
    }
  ],
  "redundant_info": [
    {
      "item": "<string>",
      "reason": "<string>",
      "suggested_rewrite": "<string>"
    }
  ],
  "decisions_to_persist": [
    {
      "decision": "<string>",
      "value": "<string|number|bool|object|array>",
      "where_to_store": "<constraints|design_tokens.*|variation_axes|references/*.md>"
    }
  ]
}
```

備考:
- 保存先は `run_summary/skill_improvement_report.json` に固定する。
- `improvements` は最低 1 件を推奨する。根拠付きで改善提案が出せない場合は、
  `problem` に「no_actionable_issue」と明記し、その理由を `evidence` に残す。
- `improvements` は推奨 3 件、最大 5 件に制限する。
- `discovery_cost` は「毎回調査している項目」を減らすための欄。
  `how_to_preload` には、次回どの `references/*.md` へ追記するかを明記する。
- `redundant_info` は次回入力から削除/要約すべき情報のみを挙げる。
- `decisions_to_persist` は次回 run で固定適用する値を最小表現で残す。

## 追加出力（orchestrator）

- 各 iteration で `iter_XX/contact_sheet.png`（全 variant タイル）を保存する。
- 最終 iteration 後に `run_summary/final_contact_sheet_8k.png`（各 iteration contact sheet を並べた高解像度タイル）を保存する。
