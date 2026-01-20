# MIDI ポート優先接続を config.yaml で管理する（2026-01-20）

目的: `sketch/readme/14.py` のように `run(..., midi_port_name=..., midi_mode=...)` をスケッチ側へ埋め込まず、**config.yaml 側で「接続優先リスト（port_name + mode）」を定義**しておき、`run()` 実行時に **上から順に接続を試す**ことで「機器を変えるたびにコードを書き換える」手間を無くす。

## 調査結果（現状）

- `grafix.api.run()`（実体: `src/grafix/api/runner.py`）は `midi_port_name: str|None = "auto"` と `midi_mode: str = "7bit"` を受け取る。
  - `"auto"` は利用可能な入力ポートの **先頭 1 つ目**へ自動接続する（`src/grafix/interactive/midi/factory.py:create_midi_controller`）。
  - 明示ポート名はそのポートへ接続するが、ポート名が存在しない場合は `InvalidPortError` で落ちる（`src/grafix/interactive/midi/midi_controller.py`）。
- `config.yaml` は `src/grafix/core/runtime_config.py` でロードされ、`run()` でもすでに `runtime_config()` が参照されている（ウィンドウ位置など）。
- `src/grafix/resource/default_config.yaml` / `./.grafix/config.yaml` には **現状 MIDI 関連のキーが無い**。

結論: `config.yaml` に MIDI 設定を追加し、`midi_port_name="auto"` のときに限り「優先リスト」を参照するようにすれば、要件は素直に実現できる。

## 方針（提案）

- `run()` のシグネチャは維持する（既存スケッチの大半が `midi_port_name` を省略できるため）。
- `midi_port_name="auto"` の解釈を拡張する:
  - config に `midi.inputs`（接続優先リスト）があれば、**その順に接続を試す**
  - どれも見つからなければ、従来通り `mido.get_input_names()` の 1 つ目へ（または無しなら MIDI 無効）
  - `midi_port_name` が `"auto"` 以外（明示ポート名）のときは、従来通り「そのポートへ接続」を優先する

## config.yaml 仕様案

`src/grafix/resource/default_config.yaml` に追加し、ユーザー側は `./.grafix/config.yaml` で上書きする。

```yaml
midi:
  # `run(..., midi_port_name="auto")` のときに上から順に接続を試す。
  # port_name が利用可能ならそのポートへ、port_name="auto" なら「入力ポートの1つ目」へ接続する。
  inputs: []
  # 例:
  # inputs:
  #   - port_name: "Grid"
  #     mode: "14bit"
  #   - port_name: "TX-6 Bluetooth"
  #     mode: "7bit"
  #   - port_name: "auto"
  #     mode: "7bit"
```

Notes:

- `mode` は現状 `MidiController` が受け付ける文字列（例: `"7bit"`, `"14bit"`）をそのまま通す。
- `inputs` を空にした場合は **現状の挙動のまま**（= `"auto"` は 1 つ目へ接続）にする。

## 0) 事前に決める（あなたの確認が必要）

- [x] キー名: `midi.inputs` で良いか（別案: `midi.input_priority` / `midi.connect_priority`）;ok
- [x] 優先順位の適用範囲: `midi_port_name="auto"` のときだけ参照（提案）で良いか;ok
- [ ] 明示ポート指定が存在しない場合の扱い
  - [x] 従来通り例外で落とす（現状維持・おすすめ）;ok
  - [ ] config の `midi.inputs` へフォールバックする（利便性重視）

## 1) 受け入れ条件（完了の定義）

- [x] `./.grafix/config.yaml` に `midi.inputs` を書くと、その順で接続が試される
- [x] `midi.inputs` の各要素で `mode` を指定でき、接続したポートに対してその mode が使われる
- [x] `midi.inputs=[]`（未設定）なら従来通り（`"auto"` は 1 つ目へ）の挙動が維持される
- [x] `midi_port_name=None`（明示無効）は従来通り MIDI 無効のまま
- [x] `PYTHONPATH=src pytest -q tests/interactive/midi/test_midi_factory.py` が通る（必要ならテスト追加/更新）
- [x] `PYTHONPATH=src pytest -q tests/core/test_runtime_config.py` が通る（config の新キー追加に追従）

## 2) 実装（チェックリスト）

- [x] `src/grafix/resource/default_config.yaml` に `midi:` セクションを追加（既定は `inputs: []`）
- [x] `src/grafix/core/runtime_config.py` に `midi.inputs` の読み取りを追加
  - [x] `RuntimeConfig` に `midi_inputs`（例: `tuple[tuple[str, str], ...]`）を追加
  - [x] `inputs` の要素を `{port_name, mode}` として解釈し、空/欠損は無視する
- [x] `src/grafix/interactive/midi/factory.py` を拡張
  - [x] `create_midi_controller(..., port_name="auto")` のとき `midi_inputs` を受け取れ、順に試せるようにする
  - [x] `inputs` に `port_name: "auto"` が含まれる場合、それを「最後のフォールバック」として扱える
- [x] `src/grafix/api/runner.py` で config 由来の `midi_inputs` を `create_midi_controller` に渡す
- [x] テスト更新/追加
  - [x] `tests/interactive/midi/test_midi_factory.py` に「優先リストで 2 番目が選ばれる」「mode が反映される」ケースを追加
  - [x] `tests/core/test_runtime_config.py` に `midi.inputs` が読み込めることの最小テストを追加
- [x] ドキュメント更新
  - [x] `README.md` の Configuration に `midi.inputs` の説明と例を追加
  - [x] `src/grafix/api/runner.py` の `midi_port_name="auto"` の説明を更新（config 優先を明記）

## 3) スケッチ側の運用（任意）

- [ ] 既存スケッチの `midi_port_name="Grid"` のような固定指定を削除し、`midi_port_name` を省略（= `"auto"`）へ寄せる
  - 以後は `.grafix/config.yaml` の `midi.inputs` を編集するだけで機器変更できる
