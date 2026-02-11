# Art Loop: artist向けGrafixガイド整備 + docstring取得MCP追加 計画（2026-02-11）

作成日: 2026-02-11  
更新日: 2026-02-11  
ステータス: 実施中

## 背景

- `.agents/skills/grafix-art-loop*` 経由で生成される `sketch.py` は、`@primitive` / `@effect` 実装時に `from grafix.core.realized_geometry import RealizedGeometry` へ過度に依存する傾向がある。
- artist が参照する「Grafixの使い方」を role 向けに1枚で示す資料が不足しており、低レベル実装に寄りやすい。
- primitive/effect の仕様をその場で再探索しなくて済むように、指定オペレーションの docstring を取得できる MCP ツールを用意したい。

## ゴール

- art-loop 向けに artist が最初に読む新規ガイドを追加する。
- ガイドには以下を含める。
  - `grafix.core.realized_geometry` 直importを避ける実装方針
  - Layer による `color` / `thickness` 指定方法
  - 組み込み primitives/effects の一覧と各1行説明
- MCP サーバに「指定 primitive/effect の docstring 取得」ツールを追加する。
- artist 単体実行と orchestrator（MCP 経由）で、上記方針を同一にする。

## 0) 合意済み方針（今回確定）

- [x] 禁止レベル: `sketch.py` で `grafix.core.realized_geometry` の import を全面禁止（案A）
- [x] 回避手段: Grafix本体へ新規 public helper を増やさず、skill/guide で高レベル実装へ誘導（案A）
- [x] 受け入れ判定: run 後に `rg "grafix.core.realized_geometry"` が 0 件であることを必須（案A）

## 1) artist向けガイド新規作成

- [x] 新規ファイルを作成する  
  - 候補: `.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md`
- [x] ガイド冒頭に「最短参照順」と「禁止事項」を明記する
  - `grafix.core.realized_geometry` 直import禁止
  - `@primitive` / `@effect` は定義だけでなく実使用必須
- [x] Layer 指定方法を記載する
  - `L(...)` での layer 化
  - `color` 指定（単色・レイヤ分割の基本）
  - `thickness` 指定（plot/export時の使い分け注意点）
- [x] 組み込み primitive/effect 一覧 + 1行説明セクションを作る
  - primitives 全件
  - effects 全件
  - 説明は「何をするオペレーションか」の1行に統一
- [x] 一覧の更新ルール（更新元・更新手順）をガイド末尾に明記する

## 2) スキル文言と参照順の更新

- [x] `.agents/skills/grafix-art-loop-artist/SKILL.md` を更新する
  - 新規ガイドを最初に参照する導線を追加
  - `grafix.core.realized_geometry` 直import禁止を明記
- [x] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` を更新する
  - artist 実行前の参照順に新規ガイドを追加
  - 同じ禁止ポリシーを明記
- [x] `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md` に新規ガイドへのリンクを追加する

## 3) MCP ツール追加（docstring 取得）

- [x] 追加対象  
  - `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py`
- [x] 新規ツール仕様を定義する
  - ツール名候補: `art_loop.get_op_docstrings`
  - 入力: `primitives` / `effects`（それぞれ名前配列）
  - 出力: 指定名ごとの docstring（全文または上限制御付き）と取得可否
- [x] 実装方針
  - `src` を import 可能にした上で registry から対象関数を解決
  - `inspect.getdoc()` で docstring を取得
  - 未登録名はエラーで落とさず結果に `not_found` として返す
- [x] 既存ツールとの整合を確認する
  - `tools/list` / `tools/call` レスポンス形式
  - 既存 `art_loop.run_codex_artist` / `art_loop.read_text_tail` への影響なし

## 4) 組み込み一覧の作成・保守方法

- [x] primitive/effect 名の取得元を固定する
  - 第1優先: `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives/effects`
- [x] 1行説明の取得元を固定する
  - 第1優先: registry 経由で関数 docstring の先頭要約行
  - 欠落時: 短い手動補完（要補完マーク付き）
- [x] 将来更新手順をガイドに記載する
  - 新規 primitive/effect 追加時の更新手順
  - docstring 未整備時の扱い

## 5) 検証計画

- [x] 追加した MCP ツールの単体確認
  - 既存 op 名指定で docstring が返る
  - 未登録名指定で `not_found` が返る
- [ ] 最小スモーク run（小さな N/M）を1回実施し、生成 `sketch.py` を確認
- [ ] `rg -n "grafix.core.realized_geometry|RealizedGeometry" sketch/agent_loop/runs/<new_run_id> -g 'sketch.py'` が 0 件であることを確認
- [x] Layer 指定のサンプルがガイド通り動くことを確認（少なくとも1例）

## 6) 完了条件

- [x] artist向け新規ガイドが追加され、参照導線が skills/quick_map から辿れる
- [x] ガイドに primitives/effects 全件の1行説明が載っている
- [x] docstring 取得 MCP ツールが実装され、名前指定で取得できる
- [ ] 新規 run で `grafix.core.realized_geometry` 直importが再発しない

## 変更対象候補ファイル

- `.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md`（新規）
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`
- `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py`
