# どこで: Grafix リポジトリ（Parameter GUI / MIDI / ParamMeta）。
# 何を: `r` / `Shift+r` / `Ctrl+r` + MIDI CC 入力で、割当済みパラメータの min-max（ui_min/ui_max）レンジを編集する。
# なぜ: マウスで min-max セルを触らずに、演奏しながらレンジ調整を素早く行うため。

# MIDI レンジ編集（Rキー）: 実装計画

## ゴール

- `r` 押下中に CC が変化したら、その CC が割当済みのパラメータのレンジ（ui_min/ui_max）を「回した方向」へシフトする。
- `Shift+r` 押下中は ui_max のみを回した方向へ調整する（レンジ上端編集）。
- `Ctrl+r` 押下中は ui_min のみを回した方向へ調整する（レンジ下端編集）。
- 対象は min-max を持つ kind（`float` / `int` / `vec3`）に限定する（`rules.py` と一致）。
- 1 回の CC 更新（`cc_change_seq`）につき 1 回だけ適用し、押しっぱなしで勝手に増え続けない。

## 非ゴール（今回やらない）

- `r` 押下中に CC による実値制御（`resolver.py` の CC 経路）を無効化する。
- どのウィンドウにフォーカスがあっても効く「グローバルキー入力」統合。
- 相対 CC（encoders の “increment/decrement” 表現）を専用に解釈する。

## 仕様（案）

### 発火条件

- Parameter GUI ウィンドウがフォーカスされ、ImGui がキー状態を取得できている。
- `imgui.KEY_R` が押下中。
- `MidiController.last_cc_change = (seq, cc)` が「前回適用した seq」より大きい。

### 対象パラメータ（「アサインされているパラメータ」）

- `store_snapshot_for_gui(store)` を走査し、`state.cc_key` が `cc` を含む `ParameterKey` をターゲットとする。
  - scalar: `state.cc_key == int(cc)` の行
  - vec3/rgb: `state.cc_key == (a,b,c)` のいずれか成分が `cc` の行
- MIDI learn 中（`MidiLearnState.active_target is not None`）はレンジ編集を無効化する（誤操作防止）。

### 方向と量

- CC 値は 0.0–1.0（`MidiController.cc[cc]`）。
- `delta = current - prev` を「回した方向」とし、`delta>0` を増加、`delta<0` を減少と解釈する。
- シフト量は「現在レンジ幅に比例」させて最小実装に寄せる:
  - `width = (ui_max - ui_min)`（未設定なら kind ごとの既定で補完）
  - `shift = delta * width * sensitivity`
  - `sensitivity` は定数（例: 1.0）として導入し、必要なら後から調整可能にする

### 更新ルール

- `r`（修飾なし）: `ui_min += shift`, `ui_max += shift`
- `Shift+r`: `ui_max += shift`
- `Ctrl+r`: `ui_min += shift`
- kind ごとの扱い:
  - `float` / `vec3`: float のまま更新
  - `int`: 更新後に `round()` して int 化
- 更新後に `ui_min > ui_max` になったら swap する（最小限の整合のみ）

### フィードバック（最小）

- Parameter GUI の上部（monitor bar 付近）に 1 行だけ状態表示する（例: `RangeEdit: CC{cc} Δ{delta:+.3f} targets={n}`）。
  - 常時表示ではなく「発火したフレームだけ」表示する（視認性と実装の単純さ優先）。

## 仕様を先に決めたい点（要確認）

- 複数パラメータが同一 CC に割当済みの場合:
  - 案A: 全部に適用（単純・直感的、ただし意図せず複数動く）
  - 案B: 最初の 1 件のみ（安全だが “どれ？” が不透明）
  - 案C: 「最後に操作した行」優先（快適だが状態管理が増える）
- `Ctrl+r` の `Ctrl` 扱い:
  - macOS では `Ctrl` のみ？ それとも `Cmd`（`io.key_super`）も同等に扱う？
- `ui_min/ui_max` が `None` のときの既定値:
  - float/vec3: (0.0, 1.0)
  - int: (0, 1)
  - ※ 現状の `resolver.py` の既定と合わせる
- `sensitivity` の初期値（1.0 で十分か、0.25 等が良いか）

## 実装チェックリスト

- [ ] 現状調査
  - [ ] `src/grafix/core/parameters/resolver.py` の CC→(ui_min, ui_max) 写像を確認する
  - [ ] Parameter GUI のキー取得方法（`imgui.KEY_*` / `io.key_shift` 等）を確認する
- [ ] 実装方針を確定（上の「要確認」を決める）
- [ ] 純粋ロジックを追加（テスト可能にする）
  - [ ] `src/grafix/interactive/parameter_gui/` 配下にレンジ編集の小さな pure 関数を追加する
    - 入力: `meta(kind, ui_min, ui_max)`, `delta`, `mode(shift|min|max)`, `sensitivity`
    - 出力: 更新後の `(ui_min, ui_max)`（必要なら swap 済み）
- [ ] GUI へ接続
  - [ ] `src/grafix/interactive/parameter_gui/gui.py` に「前回 CC 値」と「前回適用 seq」を保持する小さな状態を追加する
  - [ ] `draw_frame()` の中で「キー状態 + last_cc_change の更新」を検出し、対象 `ParameterKey` の `ParamMeta` を `set_meta()` で更新する
  - [ ] learn 中は無効化する
- [ ] 表示（最小）
  - [ ] `src/grafix/interactive/parameter_gui/monitor_bar.py` か `gui.py` 側に、発火フレームだけのテキスト表示を追加する
- [ ] テスト追加
  - [ ] pure 関数に対する `pytest` を追加する（float/int の基本ケース + swap ケース）
- [ ] 最小動作確認（手動）
  - [ ] 1 つのパラメータに CC を割当 → `r` 押下しながら CC を動かし、ui_min/ui_max が動くこと
  - [ ] `Shift+r` / `Ctrl+r` で max/min のみが動くこと
  - [ ] learn 中に動かしてもレンジが変わらないこと

## 追加で気づいた点（提案）

- 将来的に「レンジ幅の拡大/縮小」（例: `Alt+r` で幅変更）も同じ枠組みで追加できるが、今回は入れない。

