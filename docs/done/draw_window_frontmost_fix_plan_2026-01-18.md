# どこで: `src/grafix/api/runner.py`（interactive 起動の配線）。
#
# 何を: sketch 起動時に「描画ウィンドウが背面に残る」ことがある問題を、起動直後の `window.activate()` で解消する（対策A）。
#
# なぜ: Parameter GUI は前面に来るのに描画が隠れると作業が止まるため。原因は macOS + pyglet の前面化タイミング/キーウィンドウ順序の可能性が高い。

作成日: 2026-01-18

## ゴール

- `grafix.run(..., parameter_gui=True)` 実行時、描画ウィンドウと Parameter GUI の **両方**が「他アプリの背面に残らず」前面に出る。
- 起動直後のフォーカス（どちらが key window になるか）を意図どおりに決める。

## 非ゴール（今回やらない）

- ウィンドウ位置の自動補正（画面外にはみ出す等）の解消。
- ウィンドウスタイル（tool/utility/always-on-top 等）の変更。
- pyglet 側へのパッチ/フォーク。

## 対策A（採用方針）

`pyglet.app.run()` 開始直後に 1 回だけ、明示的に `window.activate()` を呼ぶ。

- 実装場所: `src/grafix/api/runner.py`
- 実装手段: `pyglet.clock.schedule_once(callback, delay)` で「event loop 開始後」に実行する

### フォーカス順（要決定）

`activate()` を呼ぶ順序で「起動直後にどちらへフォーカスを当てるか」が決まる。

- 案1: GUI → Draw（Draw を最後に activate）
  - 起動直後から描画ショートカット（`S/P/G/V`）が効く（既存の仕様と相性が良い）
  - GUI は開いたまま（必要ならクリックでフォーカス移動）
- 案2: Draw → GUI（GUI を最後に activate）
  - 現状「GUI が手前に来やすい」挙動を維持しやすい
  - ただし描画ショートカットは最初は効かない（クリックでフォーカスが必要）

まずは **案1（GUI→Draw）** を第一候補にする（描画操作を止めないため）。

## 実装チェックリスト

- [x] 再現条件の確認メモを作る（起動時に別アプリが前面/マウスを動かす等）
- [x] `src/grafix/api/runner.py` に「起動直後の activate」を追加
  - [x] `pyglet.clock.schedule_once` で 1 回だけ走らせる
  - [x] `parameter_gui=False` の場合も描画ウィンドウだけ activate する
  - [x] 例外が出ても起動自体は続行できるようにする（activate 失敗は致命ではない）
- [x] 起動直後のフォーカス順を確定（案1/案2）
- [ ] 手動検証
  - [ ] 他アプリ最前面の状態で `python sketch/...py` → 両ウィンドウが前面に来る
  - [ ] 起動直後のフォーカスが意図通り（ショートカットの効き方で確認）
  - [ ] `parameter_gui=False` でも同様に前面に来る

## 変更対象（想定）

- `src/grafix/api/runner.py`

## リスク / 注意点

- `activate()` は OS のフォーカスを奪う（= 仕様としては正しいが、煩わしいと感じる可能性はある）。
- delay の値によっては「一瞬だけ背面→前面」などのチラつきが出る可能性がある。
  - まずは `delay=0.0`（次 tick）で試し、ダメなら `0.05〜0.1` 程度へ調整する。

## 関連メモ

- 調査メモ: `docs/memo/draw_window_frontmost_issue_rootcause_2026-01-18.md`
