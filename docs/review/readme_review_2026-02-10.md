# README.md / readme.md レビュー（2026-02-10）

## 対象

- `README.md`（リポジトリルート）
- `readme.md`：このリポジトリ内に見当たりませんでした（macOS のデフォルトファイルシステムは大小文字を区別しないため、`README.md` と別ファイルとして共存できない環境が多いです）。別のファイルを想定している場合はパス指定してください。

## 総評

現状の README は情報量が多く、機能の幅も伝わります。一方で「初見が最短で成功するための導線（前提条件 → 動かす → 出力を見る → つまずき回避）」と、「内部設計（Geometry/RealizedGeometry）」と、「依存関係の羅列」が同じ優先度で並んでいて、読む人の目的に対して焦点が散ります。全体としては良い内容なので、**“誰に向けた章か” を分離**すると読みやすさが上がります。

## 仕様との乖離（要修正）

### 1) `config.yaml` のオーバーレイ順（README と実装が不一致）

README 記載（後勝ちの列挙）:

- packaged defaults → `./.grafix/config.yaml` → `~/.config/grafix/config.yaml` → `run(..., config_path=...)`

実装（`src/grafix/core/runtime_config.py: runtime_config()`）:

- 1) packaged defaults（`grafix/resource/default_config.yaml`）
- 2) 探索で見つかった `config.yaml`（任意、**CWD → HOME の先勝ちで “1 つだけ”** 採用）
  - `./.grafix/config.yaml` があればそれを採用し、`~/.config/...` は見ない
  - `./.grafix/config.yaml` が無い場合のみ `~/.config/...` を見る
- 3) `set_config_path()`（= `run(..., config_path=...)` / `python -m grafix export --config`）の明示指定があれば、それで上書き

つまり、README の「両方を順に重ねて later wins」という説明は現状とズレています。

提案:

- README を「探索は先勝ちで 1 つだけ採用」と明記し、後勝ちの列挙を修正する。
- もしくは実装を README に寄せて **両方を読む（後勝ち）** にする（ただし仕様変更になるので、README 側の修正が無難）。

### 2) Dependencies の列挙が `pyproject.toml` と一致していない

`pyproject.toml` の `dependencies` に含まれる `PyOpenGL` / `PyOpenGL_accelerate` が README の依存一覧には出てきません（逆に、README の External で挙げている `resvg` / `ffmpeg` は “pip 依存ではない” ので性質が異なりますが、こちらは妥当です）。

提案:

- README の Dependencies は「ユーザーが手で入れる必要があるもの」に寄せる（例: `resvg`, `ffmpeg`）。
- Python パッケージ群は詳細列挙せず、`pyproject.toml` を参照する構成に寄せる（列挙を続けるなら `pyproject.toml` と同期する運用が必要）。

### 3) `Export` の導線が曖昧（import パスの誤解余地）

README の Optional features に `Export` とだけ出てきますが、`grafix` 直下（`from grafix import ...`）には `Export` は公開されていません（`from grafix.api import Export` か、`python -m grafix export` が導線）。

提案:

- README に import パス（`from grafix.api import Export`）を明示する。
- もしくは README では `python -m grafix export` を主導線にして、`Export` クラスは開発者向けに退避する。

## 冗長/重複

- 冒頭の「Press `G` ...」と、後半の「Keyboard shortcuts」節で G-code 保存の説明が重複しています。どちらかに集約するとスッキリします（個人的には “Keyboard shortcuts” 側だけで十分）。
- `Core API` と `Optional features` の境界がやや曖昧です。`L` / `P` / `preset` / `cc` は `from grafix import ...` で同列に import できるため、読者視点では “optional” ではなく “主要 API の一部” に見えます。

## 不要/移動候補（README でなくてもよい）

- `Development` の Geometry/RealizedGeometry 詳細は内容が良い一方、README に置くと初見の主導線を阻害しがちです。`architecture.md` へ寄せて、README は 3〜5 行の要約＋リンクにすると読みやすくなります。
- `Dependencies` の長い列挙はメンテが割れやすいので、README では縮めるのが安全です（特に `pyproject.toml` が “真実” になっているため）。

## 追加すると良い項目（初見の成功率が上がる）

- **前提条件**: `Python >= 3.11`（`pyproject.toml` にあるので README にも明記すると親切）。
- **外部コマンドの導入**: `resvg` / `ffmpeg` の役割と、macOS の導入例（例: `brew install resvg ffmpeg`）。
- **出力先の説明**: デフォルト出力先（`data/output`）と、`P/S/V/G` で何がどこに出るかの一覧。
- **ショートカット補足**: `Shift+G` でレイヤ別に G-code を分割保存できる（実装あり）。
- **2D 最小例**: ペンプロッタ用途の最短理解として、3D ポリヘドロン＋ fill より「2D の線 → 変形 → レイヤ → G-code」の例があると強いです。
- **Troubleshooting**: `resvg が見つかりません` / `ffmpeg が見つかりません` / OpenGL/ウィンドウ生成周りの典型エラーと対処（README に 5 行程度でもあると効果が大きい）。

## 表現/構成の提案（任意）

- README を「(1) Install/Requirements (2) Quick start (3) Export & shortcuts (4) Config (5) Extending (6) Dev notes」くらいに整理すると迷いが減ります。
- Examples の大量画像は `<details>` で折りたたむと “スクロールが地獄” を避けられます（維持したい場合）。
- “Not implemented yet” は、継続的に更新するロードマップが無いなら削るか、別ドキュメントへ移すと README の焦点が保てます。

