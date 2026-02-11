## 2026-02-11: `@primitive` / `@effect` のユーザー I/O は `(coords, offsets)` タプル

Grafix の拡張ポイント（`@primitive` / `@effect`）は、スケッチ作者が `RealizedGeometry` を意識しないために、**ユーザー関数の入出力を `(coords, offsets)` タプルに統一**する。

- `coords`: `np.ndarray`（shape `(N,3)` のみ）
- `offsets`: `np.ndarray`（shape `(M+1,)`）
- primitive: `f(*, ...) -> (coords, offsets)`
- effect:
  - `n_inputs=1`: `f(g, *, ...) -> (coords, offsets)`
  - `n_inputs=2`: `f(g1, g2, *, ...) -> (coords, offsets)`
- デコレータは `from grafix import effect, primitive` で import できる（推奨）。

最小例:

```python
from __future__ import annotations

import numpy as np

from grafix import E, G, effect, primitive, run


@primitive(meta={"n": {"kind": "int", "ui_min": 2, "ui_max": 512}})
def user_prim(*, n: int = 64) -> tuple[np.ndarray, np.ndarray]:
    coords = np.zeros((n, 3), dtype=np.float32)
    offsets = np.array([0, n], dtype=np.int32)
    return coords, offsets


@effect(meta={"amount": {"kind": "float", "ui_min": 0.0, "ui_max": 10.0}})
def user_eff(
    g: tuple[np.ndarray, np.ndarray],
    *,
    amount: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    coords, offsets = g
    coords_out = coords.copy()
    coords_out[:, 0] += np.float32(amount)
    return coords_out, offsets
```

---

結論としては「実行後に“本当に足りなかった情報”をAIに棚卸しさせる」のは有効です。ただし、やり方を間違えると逆にコンテキストが肥大化します。効くのは、AIに“欲しい情報”を自由に列挙させることではなく、「今回の出力に至る意思決定で、どこが不確かで、何が原因でブレたか」を根拠付きで回収する運用です。

あなたが言う「コンテキストの無駄遣い」には大きく2種類あります。ひとつは、毎回同じ説明を長文で再投入しているタイプ（本来は固定仕様として外に出して参照すべき）。もうひとつは、必要な情報が欠けていてAIが推測で埋め、その推測が外れてやり直しになるタイプ（本来は“欠けて困った情報”だけを次回に足すべき）。実行後の棚卸しは後者に効きます。前者は棚卸しだけでは減らず、「固定仕様をどこに置くか」「どこまでを毎回入力するか」の設計で減らします。

この手法を成立させるコツは、棚卸しの出力を“要求仕様”にしてしまうことです。つまり「次回にあったら便利な情報を何でも書け」ではなく、「今回、判断が分岐した（迷った／仮定した／失敗した）箇所に限って、不足情報を最大N件、証拠付きで出せ」と縛ります。そうしないと、モデルは安全側に倒れて「もっと情報が欲しい」を無限に増やします。

特に、あなたがGrafixの反復ループ（ideaman/artist/critic/orchestrator）みたいな運用をしているなら、そもそも“次に必要な情報”は `critique` の `next_iteration_directives` や、`design_tokens` の差分として表現されるべきで、散文の追記で増やすべきではありません。つまり棚卸しは、`design_tokens` や `constraints` に落とせない“運用上の不足”だけを拾うのが筋です（例: そもそもキャンバスや制約が不明、利用可能なprimitive/effectの一覧が不明、評価基準が曖昧でcriticが揺れる、など）。この方向性は、オーケストレーターが「比較・選抜・次の指示」を中核にしている設計とも整合します。

実装するなら、実行後にAIへ投げる“監査プロンプト”は、次の3点を必須にするとコンテキストが増えにくくなります。

第一に、「不足情報（Missing）」と「冗長情報（Redundant）」を同時に出させます。不足だけを集めると入力が増える一方で、冗長の圧縮が起きません。冗長は「今回の成果に寄与しなかった／参照されなかった／重複している」ものに限定し、次回は“要約形”か“参照形”に落とさせます。

第二に、各不足情報に「根拠（evidence）」を必須にします。根拠とは、実際にAIが迷った判断点、エラー、仮定した前提、出力のブレを生んだ要因です。根拠が書けない項目は、だいたい“あったら嬉しい一般論”で、コンテキストを増やすだけです。

第三に、「どう渡すと最も安いか（how_to_provide）」まで書かせます。たとえば「長文で説明」ではなく、「固定仕様ファイルの1行」「design_tokensのleaf 1つ」「禁止リストの単語列」など、最小表現に落とすのが目的だからです。Grafix系なら、`design_tokens.*` のleafに落とせるか、`constraints` に落とせるか、`variation_axes` に落とせるか、という観点が分かりやすいです。

具体的には、実行後に次のような“固定フォーマット”で返させるのが実用的です（これ自体は短いのに、回収できる情報が濃いので、次回の入力を削れます）。

```json
{
  "missing_info": [
    {
      "item": "不足していた情報（最小表現で）",
      "reason": "これが無いと何が決められず、どんな仮定を置いたか",
      "evidence": "迷った点/エラー/曖昧さ（具体）",
      "how_to_provide": "次回はどう渡すと最も短く済むか（例: design_tokensのleaf、制約の一文、参照ファイル名など）",
      "expected_impact": "期待される改善（再試行削減、品質の安定など）",
      "priority": 1
    }
  ],
  "redundant_info": [
    {
      "item": "次回は省ける/圧縮できる情報",
      "reason": "今回の成果に寄与しなかった理由",
      "suggested_rewrite": "次回はこの短さに圧縮、または参照に置換"
    }
  ],
  "decisions_to_persist": [
    {
      "decision": "今回固定化すべき決定（例: 評価基準の重み、禁止事項、作品の狙いの一文）",
      "value": "最小表現",
      "where_to_store": "次回の入力のどこに置くべきか（固定仕様/brief/design_tokensなど）"
    }
  ],
  "questions_to_ask_next_time": [
    {
      "question": "次回の最初に聞くべき1問",
      "why": "これで分岐が潰れて試行回数が減る"
    }
  ]
}
```

ここで重要なのは、`missing_info` の件数上限（たとえば最大3〜5件）と、`priority` の強制です。件数上限が無いと、モデルは「保険」で際限なく追加します。逆に上限があると、「最も痛かった欠落」だけが抽出され、次回の入力が増えにくくなります。

あなたが目指している「もっと優れた作品を書かせたい」という目的に対しては、棚卸しの“対象”を間違えないほうがいいです。作品品質を上げるのに効く不足情報は、だいたい次のどれかに分類されます。評価基準（何を良しとするか）の優先順位が曖昧、禁止事項（やってほしくない表現や破綻）が曖昧、出力形式（どこに何を保存するか、何をJSONで返すか等）が曖昧、そして「可変レバー」が散文で書かれていて構造化されていない、の4つです。Grafixのループ設計では、これらを `constraints` / `design_tokens` / `variation_axes` / `next_iteration_directives` に落とす思想が明確なので、棚卸しで出てきたものは可能な限りそこへ“圧縮して移す”のが正攻法です。

逆に、棚卸しに向かないのは「参考になるから入れておくと安心」系の情報です。例示が多すぎる、似た制約を言い換えて重ねる、背景説明を毎回全文貼る、みたいなものは、モデルの注意資源を散らし、作品の一貫性を壊しがちです。棚卸しの `redundant_info` で、それらを“参照形”に追い出していくのが、コンテキスト削減としては効きます。

最終的な提案としては、あなたのアイデア（実行後にAIが必要情報を吐く）自体は採用してよいです。ただし「実行後に自由作文で振り返らせる」のではなく、「不足・冗長・固定化すべき決定」を根拠付きで、最大件数を絞ってJSONで返させ、次回はそれを機械的に取り込む、という形にしてください。そうすると、コンテキストは増えるどころか、反復が進むほど“短くても強い入力”に収束します。
