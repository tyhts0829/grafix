# どこで: Codex Skills（`~/.codex/skills`） + Grafix（`src/grafix/`）。
#
# 何を: 「エージェントが `draw(t)` を生成し、CLI 経由で画像（主に PNG）を export する」Skill を実装可能か、現状の機能で確認する。
#
# なぜ: 対話ウィンドウを立ち上げずに 1 フレームの成果物（PNG/SVG）を確実に出力できる導線を作るため。

## 結論（可否）

- **可能**（Grafix 側に headless export API と PNG 変換が既にある）。
- ただし現状の `python -m grafix` CLI には export サブコマンドが無いので、Skill 側で CLI スクリプトを同梱するか、Grafix 本体に `export` サブコマンドを追加する必要がある。

## 現状調査（根拠）

### Grafix: headless export は用意済み

- `src/grafix/api/export.py` に `Export(draw, t, fmt, path, ...)` があり、`fmt="svg"|"png(image)"|"gcode"` を扱う。
- `src/grafix/export/image.py` で PNG 出力を提供している（`.svg` を生成 → `resvg` で `.png` へラスタライズ）。
- `canvas_size=None` は現状未対応（SVG/PNG の両方で必須）。
- ルートの `grafix` パッケージは `Export` を再公開していない（`from grafix import Export` は失敗する）。Skill 側は `from grafix.api import Export` を使う必要がある。

### Grafix: CLI はあるが export はまだ無い

- `src/grafix/__main__.py` が `python -m grafix ...` のエントリポイント。
- 現状サブコマンドは `benchmark/stub/list` のみ（export は未実装）。

### 動作確認（2026-01-15）

以下を実行し、headless で PNG を生成できることを確認した（出力先は repo 外の `/tmp` を使用）。

```bash
PYTHONPATH=src python - <<'PY'
from grafix.api import G, Export

def draw(t: float):
    return G.line(center=(400.0, 400.0, 0.0), length=600.0, angle=45.0)

Export(draw, t=0.0, fmt="png", path="/tmp/grafix_skill_check.png", canvas_size=(800, 800))
print("wrote /tmp/grafix_skill_check.png")
PY
```

補足:
- `resvg` はこの環境では `command -v resvg` で検出でき、PNG 生成も成功した。

## Skill 実装の方針案（CLI export 前提）

### 方針 A: Grafix 本体は変更しない（Skill に export 用 CLI スクリプトを同梱）

Skill 側に `scripts/export_frame.py` のような最小 CLI を持たせる。

- 入力: `module:function`（例: `sketch.foo:draw`）、`--t`、`--canvas 800 800`、`--fmt png|svg`、`--out`。
- 実装: `importlib.import_module` で draw をロード → `grafix.api.Export(...)` を呼ぶだけ。

メリット:
- Grafix 本体へパッチ不要。
- Skill のスコープに閉じるので実装/迭代が速い。

デメリット:
- 「Grafix の標準 CLI」としては残らない（Skill 依存のコマンドになる）。

### 方針 B: `python -m grafix export ...` を追加（Grafix CLI を拡張）

Grafix 本体に export サブコマンドを追加し、Skill はそれを叩くだけにする。

例（案）:

```bash
PYTHONPATH=src python -m grafix export --module sketch.foo --fn draw --t 0 --fmt png --out /tmp/out.png --canvas 800 800
```

メリット:
- ワークフローが Grafix 側へ集約され、Skill が薄くなる。
- 将来、ドキュメントや外部利用にも流用しやすい。

デメリット:
- Grafix 本体の変更が必要（仕様決め・最小テスト・README 更新などが発生）。

## 前提/制約（Skill 実行時に効くもの）

- PNG 出力は外部コマンド `resvg` に依存（PATH に無い場合は `RuntimeError`）。
- Python 依存（`numpy` 等）が import できる環境が必要（`PYTHONPATH=src` は Grafix 本体の import を助けるだけ）。
- 現状、SVG/PNG の headless export は `canvas_size` 必須（bbox 自動推定は未実装）。

## 実装チェックリスト（あなたの OK 後に着手）

- [ ] Skill のトリガ文言と名前（例: `grafix-draw-export`）を確定
- [ ] 方針 A/B の決定
- [ ] Skill のテンプレ生成（`init_skill.py`）と `SKILL.md` の設計
- [ ] （A の場合）`scripts/export_frame.py` を実装して `/tmp` と `data/output` で動作確認
- [ ] （B の場合）`src/grafix/__main__.py` に `export` サブコマンド追加（最小実装）+ 動作確認
- [ ] `package_skill.py` で `.skill` を生成
- [ ] インストール導線の確定（`~/.codex/skills` への配置。必要なら承認が要る）

## 要確認（あなたに質問）

- 出力対象は PNG のみで良い？（SVG も常に一緒に残す？）
- Skill が生成する `draw` の保存先は `sketch/` 配下で良い？（例: `sketch/generated/<name>.py`）
- CLI は方針 A（Skill 同梱スクリプト）と方針 B（Grafix の `python -m grafix export`）どちらを優先する？
- デフォルトの `canvas_size` / `png scale` は固定にする？それとも引数で可変にする？

