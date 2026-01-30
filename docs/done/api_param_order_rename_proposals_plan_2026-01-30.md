# 何を: `docs/review/api_param_order_2026-01-30.md` のコメントに基づき、「現状 -> 変更後」の候補名を本文に追記する。

# なぜ: 命名改善の議論を、具体的な候補名ベースで進められるようにするため。

## 方針

- 既存の引数箇条書きは維持しつつ、変更候補がある行だけ `old -> new` を追記する。
  - 例: `- \`spatial_freq\` -> \`freq\``
- スコープは **既に入れてある `> コメント:` に紐づく命名揺れ** に限定する（順序変更は書かない）。
- 変更候補は各 op につき 1 案に絞る（迷うものはコメントに併記）。

## 対象（現時点）

- `E.displace`: 周波数・時間語彙の統一（例: `spatial_freq` / `frequency_gradient` / `t`）
- `E.drop`: `keep_mode` の語彙整理（`keep_original` と衝突しにくくする）
- `E.mirror`: `cx/cy` の語彙（`center_*` など）
- `E.repeat`: 平行移動語彙（`offset` vs `delta` など、ただし名前だけの提案に留める）
- `P.flow`: `displace_frequency` の語彙（`E.displace` と合わせる）

## 実装チェックリスト

- [x] 1) `docs/review/api_param_order_2026-01-30.md` の対象 op に `old -> new` を追記
- [x] 2) コメント文も、採用した候補名に合わせて更新（矛盾が無いこと）
- [x] 3) 変更候補が多すぎないことを最終確認（重要箇所に限定）
