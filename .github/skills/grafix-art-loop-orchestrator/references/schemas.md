# Grafix Art Loop JSON Schema（実務用ミニマム）

このファイルは、grafix-art-loop（orchestrator / ideaman / artist / critic）が受け渡す JSON 仕様を固定する。

重要:

- ここに書かれている JSON は **型と構造の例**。値の丸写しは禁止（固定化して作品づくりを壊す）。
- 出力側（ideaman/artist/critic）は、毎回 “作る” こと（特に ideaman の `CreativeBrief`）。

## `CreativeBrief`（ideaman の出力）

```json
{
  "title": "<string>",
  "context": "<string>",
  "intent": "<string>",
  "canvas": { "w": "<int>", "h": "<int>" },
  "colors": {
    "primary": "<string>",
    "secondary": "<string>",
    "tertiary": "<string>"
  }
}
```

## `ArtistContext`（orchestrator → artist）

```json
{
  "run_id": "<string>",
  "iteration": "<int>",
  "variant_id": "<string>",
  "artist_id": "<string>",
  "mode": "<exploration|exploitation>",
  "creative_brief": {},
  "critic_feedback_prev": null
}
```

## `Critique`（critic の出力）

```json
{
  "iteration": "<int>",
  "ranking": [
    { "variant_id": "<string>", "score": "<float>", "reason": "<string>" }
  ]
}
```

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
  "seed": "<int>"
}
```

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
