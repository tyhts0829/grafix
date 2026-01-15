<!--
どこで: `docs/agent_docs/testing.md`。
何を: Grafix のテスト運用（pytest・再現性・markers・スタブ同期）をまとめる。
なぜ: ルート `AGENTS.md` から詳細を分離し、必要なときだけ参照できるようにするため。
-->

# テスト規約

## 基本

- `pytest` を使う。
- `tests/test_*.py` は対象モジュールと対応させる。
- 乱数は固定し再現性を確保する。

## スタブ

- 公開 API を変更したらスタブを再生成し、スタブ同期テストを更新する。
  - 例: `python -m grafix stub`
  - 例: `pytest -q tests/stubs/test_g_stub_sync.py`

## markers 実行例

- 並行処理: `pytest -q -m integration -k worker`
- e2e/perf: `pytest -q -m "e2e or perf"`
