# どこで: Codex Skills（`skills/` で管理し `.skill` を生成） + Grafix（`src/grafix/`）。
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

### Grafix: CLI はあり、export も追加済み（2026-01-15）

- `src/grafix/__main__.py` が `python -m grafix ...` のエントリポイント。
- サブコマンド `export` を追加し、`draw(t)` を headless で PNG に書き出せるようにした。
  - 例: `PYTHONPATH=src python -m grafix export --callable sketch.main:draw --t 0 0.5 1.0 --canvas 800 800`
  - 注: PNG 出力時も同名の `.svg` が生成される（PNG は SVG を `resvg` でラスタライズして作る）。

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

### 方針 B: `python -m grafix export ...` を追加（Grafix CLI を拡張）※採用

Grafix 本体に export サブコマンドを追加し、Skill はそれを叩くだけにする。

例（案）:

```bash
PYTHONPATH=src python -m grafix export --callable sketch.foo:draw --t 0 --canvas 800 800
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

## 実装チェックリスト

- [x] Skill のトリガ文言と名前を確定（`grafix-draw-export`）
- [x] 方針 A/B の決定（方針 B）
- [x] Skill のテンプレ生成と `SKILL.md` 作成（`skills/grafix-draw-export/SKILL.md`）
- [x] `python -m grafix export` を実装（PNG 限定、`--t` 複数指定で連番保存）
- [x] `package_skill.py` で `.skill` を生成（`dist/grafix-draw-export.skill`）
- [ ] インストール導線の確定（例: `~/.codex/skills` へ配置。ここは手動で実施）

## 決定事項

- 出力対象: PNG（ただし PNG 生成の都合で `.svg` も同名で生成される）
- draw の保存先（Skill 推奨）: `sketch/generated/<slug>.py`
- CLI: 方針 B（Grafix の `python -m grafix export`）
- `canvas_size`: CLI 既定は `(800, 800)`（Skill 側は明示指定推奨）
