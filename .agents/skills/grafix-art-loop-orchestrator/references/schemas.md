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
  "design_axes": {
    "brief_uniqueness_key": "<string>",
    "topology_key": "<string>",
    "silhouette_key": "<string>",
    "density_key": "<string>",
    "event_key": "<string>",
    "palette_key": "<string>"
  },
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
  "round": "<int>",
  "loop": "<int>",
  "variant_id": "<string>",
  "artist_id": "<string>",
  "artist_profile_ref": "<string|null>",
  "mode": "<independent>",
  "creative_brief": {},
  "critic_feedback_prev": null,
  "prior_loop_artifact_ref": "<string|null>"
}
```

## `Critique`（critic の出力）

```json
{
  "round": "<int>",
  "ranking": [
    { "variant_id": "<string>", "score": "<float>", "reason": "<string>" }
  ]
}
```

## `Artifact`（artist の出力）

```json
{
  "artist_id": "<string>",
  "round": "<int>",
  "loop": "<int>",
  "variant_id": "<string>",
  "mode": "<independent>",
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

## `DiversityLedger`（orchestrator の run 内 family 記録）

```json
{
  "run_id": "<string>",
  "rounds": [
    {
      "round": "<int>",
      "round_identity": "<string>",
      "forbidden_families": ["<string>"],
      "variants": [
        {
          "variant_id": "<string>",
          "brief_uniqueness_key": "<string>",
          "topology_key": "<string>",
          "silhouette_key": "<string>",
          "family_summary": "<string>",
          "forbidden_from_round": "<int>"
        }
      ]
    }
  ]
}
```

備考:

- `CreativeBrief.design_axes` は多様性担保のための必須設計軸。
- `brief_uniqueness_key` は同一 run 内で重複禁止。
- `topology_key` / `silhouette_key` / `density_key` / `event_key` / `palette_key` は「前 round の改善」ではなく「最初から別種を作る」ための識別子。
- `topology_key` / `silhouette_key` は文字列の重複回避だけでは不十分であり、same-run 内で意味レベルの重複も禁止する。
- `ArtistContext.critic_feedback_prev` は独立ラウンド方針では常に `null`。
- `ArtistContext.prior_loop_artifact_ref` は、同一 `round_XX/vYY` の直前 loop がある場合のみ使う。
- `Critique` は各 variant の最終 loop 出力だけを ranking 対象にする。
- `DiversityLedger` は作品評価用ではなく、run 内で採用済み family と `forbidden family` を機械的に残すための管理出力である。
- `forbidden_families` は後続 round で再使用を禁止する構図 family の要約を表す。
- `family_summary` は `brief_uniqueness_key` では表現しきれない構図類型の短い説明を表す。
- 保存先は `run_summary/skill_improvement_report.json` に固定する。
- `improvements` は最低 1 件を推奨する。根拠付きで改善提案が出せない場合は、
  `problem` に「no_actionable_issue」と明記し、その理由を `evidence` に残す。
- `improvements` は推奨 3 件、最大 5 件に制限する。
- `discovery_cost` は「毎回調査している項目」を減らすための欄。
  `how_to_preload` には、次回どの `references/*.md` へ追記するかを明記する。
- `redundant_info` は次回入力から削除/要約すべき情報のみを挙げる。
- `decisions_to_persist` は次回 run で固定適用する値を最小表現で残す。

## 追加出力（orchestrator）

- 各 round で `round_XX/contact_sheet.png`（各 variant の最終 loop 出力タイル）を保存する。
- 最終 round 後に `run_summary/final_contact_sheet_8k.png`（各 round contact sheet を並べた高解像度タイル）を保存する。
- run 内の diversity guardrail 用に `run_summary/diversity_ledger.json` を保存する。
