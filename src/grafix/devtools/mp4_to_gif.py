from __future__ import annotations

"""動画（mp4/mov 等）を GIF に変換する。

`python tools/mp4_to_gif.py` を実行するとファイル選択ダイアログが開く。
変換設定はこのファイル冒頭の定数で調整する。

必要:
- ffmpeg（例: `brew install ffmpeg`）
"""

import shutil
import subprocess
import sys
from pathlib import Path

SCALE = 0.5
FPS = 50
SPEED = 2.0  # 再生速度倍率（2.0=2倍速 / 0.5=半速）
START_SEC: float | None = None
DURATION_SEC: float | None = None
LOOP = 0  # 0=無限ループ


def _select_input_video() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    path = filedialog.askopenfilename(
        title="GIF に変換する動画を選択",
        filetypes=[
            ("Video files", "*.mp4 *.mov *.m4v *.webm"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()

    if not path:
        return None
    return Path(path)


def _select_output_gif(*, initial_dir: Path, initial_stem: str) -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    path = filedialog.asksaveasfilename(
        title="GIF の保存先を選択",
        initialdir=str(initial_dir),
        initialfile=f"{initial_stem}.gif",
        defaultextension=".gif",
        filetypes=[("GIF", "*.gif")],
    )
    root.destroy()

    if not path:
        return None

    out_path = Path(path)
    if out_path.suffix.lower() != ".gif":
        out_path = out_path.with_suffix(".gif")
    return out_path


def _run_ffmpeg(*, ffmpeg: str, input_path: Path, output_path: Path) -> None:
    filter_complex = (
        f"setpts=(PTS-STARTPTS)/{SPEED},"
        f"fps={FPS},scale=iw*{SCALE}:ih*{SCALE}:flags=lanczos,split[s0][s1];"
        "[s0]palettegen=stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer"
    )

    cmd: list[str] = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if START_SEC is not None:
        cmd += ["-ss", str(START_SEC)]
    cmd += ["-i", str(input_path)]
    if DURATION_SEC is not None:
        cmd += ["-t", str(DURATION_SEC)]
    cmd += [
        "-an",
        "-filter_complex",
        filter_complex,
        "-loop",
        str(LOOP),
        str(output_path),
    ]

    subprocess.run(cmd, check=True)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print(
            "ffmpeg が見つかりません。`brew install ffmpeg` などでインストールしてください。",
            file=sys.stderr,
        )
        raise SystemExit(2)

    input_path = _select_input_video()
    if input_path is None:
        raise SystemExit(0)

    output_path = _select_output_gif(
        initial_dir=input_path.parent, initial_stem=input_path.stem
    )
    if output_path is None:
        raise SystemExit(0)
    if output_path.exists():
        print(f"出力ファイルが既に存在します: {output_path}", file=sys.stderr)
        print(
            "別名で保存するか、既存ファイルを削除してから再実行してください。",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        _run_ffmpeg(ffmpeg=ffmpeg, input_path=input_path, output_path=output_path)
    except subprocess.CalledProcessError as e:
        print("ffmpeg の実行に失敗しました。", file=sys.stderr)
        print(f"終了コード: {e.returncode}", file=sys.stderr)
        raise SystemExit(2) from e

    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
