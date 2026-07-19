<!--
どこで: `docs/agent_docs/documentation.md`。
何を: Grafix のドキュメンテーション（docstring/コメント/型/ADR）の運用規約。
なぜ: ルート `AGENTS.md` を短く保ちつつ、必要時に参照できる詳細を分離するため。
-->

# ドキュメンテーション規約

## 原則

- What/How はコードと型で表現し、Why/Trade-off はコメントに残す。
- 明確で単純な説明を優先し、直感的でないロジックにはコメントを書く。
- 各ファイル先頭に簡潔なヘッダ（どこで・何を・なぜ）を書く。

## 公開 API の docstring

- すべての公開 API に NumPy スタイル docstring + 型ヒントを付ける。
- docstring は日本語の事実記述（主語省略・終止形、絵文字不可）で書く。
- 目的・設計意図・既知のトレードオフのみを短く記し、逐語説明や重複は避ける。

## Operation 引数の説明

- first-party の Parameter GUI 対象引数は、対応する `ParamMeta.description` に
  空でない具体的な説明を書く。GUI Help と生成 stub はこれを説明の
  source of truth とする。
- `ParamMeta` を持たない code-owned の公開引数は、公開 callable の NumPy スタイル
  docstring に `Parameters` 節を設け、各引数を具体的に説明する。
- ユーザー定義 primitive / effect / preset の `description` は任意とする。
  互換性のため必須にはしないが、GUI Help と生成 stub へ用途を伝えるため記述を推奨する。

## 型ヒント

- `dict[str, Any]` 等の組込みジェネリックで統一する。
- `typing` 由来は最小限（`Callable`, `Mapping`, `Sequence`）。

## ADR（影響大の判断）

- 影響が大きい判断は ADR（背景 → 決定 → 根拠 → 結果）で残す。

## ツール

- lint: `ruff`
- 型: `mypy` + pylance
