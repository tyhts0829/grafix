# Müller-Brockmann × Generative スケッチ生成 & export（v1）

## ゴール

- `sketch/generated/muller_brockmann_generative.py` に `draw(t)` を実装し、「秩序（グリッド）と生成（ノイズ/揺らぎ）」が同居するポスター風の 1 枚を生成する。
- `python -m grafix export` で `t` 違いの PNG を複数枚書き出し、比較できる状態にする。

## 構成メモ（5 行）

- ベース形状: A4 縦のグリッド + オフセンターの円弧（同心円の断片）
- 変形: 円弧にだけ “生成的な崩れ” を入れる（秩序 vs ノイズの衝突）
- レイヤ: grid（薄）/ type（太）/ arcs（黒）/ accent（赤）
- `t` の使い方: 0→1 で変位強度と円弧区間が変化（0 ではほぼ整列、1 で最も崩れる）
- 計算量: リング数少なめ + 円近似点数控えめ（export を重くしない）

## 使う op 候補（カタログ）

- primitives: `G.line`, `G.polygon`, `G.text`
- effects: `E.trim`, `E.displace`

## 先に確定したい（ユーザー確認）

- canvas: A4 縦で進めて良い？（`210 297`）
- 出力する `t`: 既定 `0 0.25 0.5 0.75 1.0`
- 出力先: 既定 `--out-dir /tmp/mb_gen_v1` / `--run-id mb_gen_v1`
- カラー: 黒 + 赤アクセントで良い？（2〜3 レイヤ）
- 崩れの強さ: “控えめ” から開始で良い？（v1 は破綻しない範囲）

## 実装タスク

- [ ] 仕様（canvas / `t` / 出力先 / カラー / 崩れ強度）を確定する
- [ ] `sketch/generated/muller_brockmann_generative.py` を新規作成して `draw(t)` を実装する
- [ ] `python -m grafix export` を実行して v1 を書き出す（複数フレーム）
- [ ] 良いフレーム（`t`）を選別する
- [ ] 選別結果を元に v2 を改良する（必要なら）

## export コマンド（案 / v1）

```bash
PYTHONPATH=src python -m grafix export \
  --callable sketch.generated.muller_brockmann_generative:draw \
  --t 0 0.25 0.5 0.75 1.0 \
  --canvas 210 297 \
  --out-dir /tmp/mb_gen_v1 \
  --run-id mb_gen_v1
```

