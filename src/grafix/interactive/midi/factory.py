# どこで: `src/grafix/interactive/midi/factory.py`。
# 何を: port_name/mode に従って MidiController を生成する（auto 接続 / mido 有無を含む）。
# なぜ: `src/grafix/api/runner.py` を配線に寄せ、MIDI 依存ロジックを interactive 側に閉じ込めるため。

"""MIDI 設定を `MidiController` の生成に落とす factory。

このモジュールは「Runner/CLI から渡される MIDI 設定値」を受け取り、状況に応じて
`MidiController` を生成するか、MIDI を無効化（`None` を返す）します。

設計意図
--------
- `mido` は optional dependency なので、`port_name="auto"` のときは未導入でも静かに無効化する。
- 一方で、ユーザーが明示的にポート名を指定したときは意図が強いので、未導入ならエラーにする。

主な入口
--------
- `create_midi_controller()`

副作用
------
- `mido.get_input_names()` により OS の MIDI 入力ポート一覧を取得する。
- `MidiController` を生成した場合、入力ポートの open と CC スナップショットの load（ファイル I/O）が起きる。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .midi_controller import MidiController

# Runner/CLI 側の設定値で使う特別な文字列（自動接続の合図）。
_AUTO_MIDI_PORT = "auto"


def create_midi_controller(
    *,
    port_name: str | None,
    mode: str,
    profile_name: str,
    save_dir: Path | None = None,
    priority_inputs: Sequence[tuple[str, str]] = (),
) -> MidiController | None:
    """設定値に従って `MidiController` を生成する。

    Parameters
    ----------
    port_name
        MIDI 入力ポート名。`None` なら MIDI 無効。`"auto"` なら利用可能な入力ポートから自動選択する。
    mode
        `"7bit"` または `"14bit"`（`MidiController` の `mode`）。
    profile_name
        CC スナップショット永続化ファイル名（stem）に埋め込む profile 名。
    save_dir
        CC スナップショットを保存するディレクトリ。`None` のときは既定の出力先を使う。
    priority_inputs
        `("port_name", "mode")` の候補リスト。`port_name="auto"` のときのみ参照する。

        - 先頭から順に「存在するポート + 指定 mode」で接続を試す。
        - 候補の `port_name` に `"auto"` を含めると「先頭ポート + その mode」を強制できる。
        - どれも接続できなければ従来の挙動（先頭ポートへ接続）に fallback する。

    Returns
    -------
    MidiController | None
        接続できた場合は `MidiController`。MIDI 無効または自動接続に失敗した場合は `None`。

    Raises
    ------
    RuntimeError
        `port_name` が明示指定かつ `mido` が導入されていない場合。

    Notes
    -----
    `MidiController` の生成時に、入力ポートの open と CC スナップショットの load が行われる。
    """

    if port_name is None:
        # ユーザーが明示的に MIDI を無効化したケース。
        return None

    if port_name == _AUTO_MIDI_PORT:
        # optional dependency: 自動接続は mido が無ければ黙って無効化する。
        try:
            import mido  # type: ignore
        except Exception:
            return None

        # 以降で何度も参照するので一度 list 化して固定する。
        names = list(mido.get_input_names())  # type: ignore
        for candidate_port_name, candidate_mode in priority_inputs:
            # 設定値は外部入力なので、軽く正規化（空文字は無視）して扱う。
            port_s = str(candidate_port_name).strip()
            mode_s = str(candidate_mode).strip()
            if not port_s or not mode_s:
                continue
            if port_s == _AUTO_MIDI_PORT:
                # "auto" を候補に含めることで「先頭ポートを、この mode で使う」を表現できる。
                if not names:
                    continue
                return MidiController(
                    names[0], mode=mode_s, profile_name=profile_name, save_dir=save_dir
                )
            if port_s in names:
                return MidiController(
                    port_s, mode=mode_s, profile_name=profile_name, save_dir=save_dir
                )

        if not names:
            return None
        # priority_inputs で決まらなければ、従来の auto 挙動（先頭ポート）にフォールバックする。
        return MidiController(
            names[0], mode=mode, profile_name=profile_name, save_dir=save_dir
        )

    # 明示指定のときは mido が必要。
    # （未導入なら `MidiController` 側で ImportError になるが、ここで意図の分かるエラーメッセージにする）
    try:
        import mido  # type: ignore  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "midi_port_name を指定するには mido が必要です（pip で導入してください）。"
        ) from exc
    return MidiController(port_name, mode=mode, profile_name=profile_name, save_dir=save_dir)
