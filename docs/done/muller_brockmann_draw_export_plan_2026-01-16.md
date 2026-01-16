# Müller-Brockmann 風スケッチ生成 & export（v1）

## ゴール

- `sketch/generated/muller_brockmann.py` に `draw(t)` を実装し、Müller-Brockmann（スイス・インターナショナル・タイポグラフィ）を想起させる幾何学グリッド作品を生成する。
- `python -m grafix export` で `t` 違いの PNG を複数枚書き出して比較できる状態にする。

## 先に決めたいこと（ユーザー確認）

- キャンバス: 例 `800 800` / `1024 1024` / 用紙比率（A4 など）
- 出力する `t`: 例 `0 0.25 0.5 0.75 1.0`
- 出力先: `--out-dir` と `--run-id`（例 `mb_v1`）
- 作品の寄せ方:
  - 直線グリッド中心（情報デザイン寄り）
  - 円弧/同心円中心（Musica viva 風）
  - “文字っぽさ”を線で表現（塊・余白・ベースライン感）
- カラー: ペンプロッタ前提で基本は単色線＋アクセント（赤など）を線密度で表現するか、完全単色にするか

## 実装タスク

- [x] 仕様（キャンバス / `t` / 方向性 / カラー方針）を確定する
- [x] `sketch/generated/muller_brockmann.py` を新規作成して `draw(t)` を実装する
- [x] `python -m grafix export` のコマンド（複数フレーム）を用意する
- [x] v1 を書き出す（複数フレーム生成）
- [ ] 良いフレーム（`t`）を選別する
- [ ] 選別結果を元に v2 以降を改良する（必要なら）

## 今回の決定（v1）

- canvas: A4 縦（`210 297`）
- `t`: `0 0.25 0.5 0.75 1.0`
- 方向性: 同心円/円弧（Musica viva の抽象）＋グリッド＋タイポ
- カラー: 黒＋赤アクセント（2 レイヤ）
- 出力: `--out-dir /tmp/mb_v1` / `--run-id mb_v1`

## export コマンド（v1）

```bash
PYTHONPATH=src python -m grafix export \
  --callable sketch.generated.muller_brockmann:draw \
  --t 0 0.25 0.5 0.75 1.0 \
  --canvas 210 297 \
  --out-dir /tmp/mb_v1 \
  --run-id mb_v1
```

出力（PNG）:

- `/tmp/mb_v1/muller_brockmann_1680x2376_mb_v1_f001.png`（t=0.0）
- `/tmp/mb_v1/muller_brockmann_1680x2376_mb_v1_f002.png`（t=0.25）
- `/tmp/mb_v1/muller_brockmann_1680x2376_mb_v1_f003.png`（t=0.5）
- `/tmp/mb_v1/muller_brockmann_1680x2376_mb_v1_f004.png`（t=0.75）
- `/tmp/mb_v1/muller_brockmann_1680x2376_mb_v1_f005.png`（t=1.0）
