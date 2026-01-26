"""
どこで: `src/grafix/devtools/prepare_readme_examples_grn.py`。
何を: README の Examples（grn）用画像を生成し、README のタイルを自動生成する。
なぜ: `data/output/png/readme/grn` に PNG が増えていく前提で、README 更新作業を最小化するため。

Notes
-----
- このスクリプトは「原本（data/output）→README 用アセット（docs/readme）+ README 更新」の後段だけを担当する。
  `sketch/readme/grn` から原本 PNG を一括生成したい場合は
  `src/grafix/devtools/refresh_readme_grn.py` を使う。

前提:
- macOS の `sips` を使う（依存追加なし）。
- 画像は「6 列で割り切れる最大枚数」だけ採用し、余りは末尾（新しい側）を落とす。

使い方:
- `python src/grafix/devtools/prepare_readme_examples_grn.py`
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

###############################################################################
# Parameters
###############################################################################

# 1 行あたりの枚数（README のタイル列数）。
COLUMNS = 3

# リサイズ後の長辺 px（`sips -Z` に渡す）。
MAX_DIM = 600

# README での表示 width（`<img width="...">`）。
IMG_WIDTH = 320

# 画像生成/README 書き換えを行わず、対象枚数だけ表示する。
DRY_RUN = False

_NUM_PREFIX_RE = re.compile(r"^(\d+)")

_README_BEGIN = "<!-- BEGIN:README_EXAMPLES_GRN -->"
_README_END = "<!-- END:README_EXAMPLES_GRN -->"


@dataclass(frozen=True)
class _InputImage:
    """入力ディレクトリ内の PNG と、その番号（ファイル名先頭の数値）を束ねたもの。"""

    num: int
    path: Path


def _find_repo_root() -> Path:
    """リポジトリのルートディレクトリを返す。

    このスクリプトは `data/` や `docs/` を相対的に参照したいので、`pyproject.toml`
    が存在するディレクトリをリポジトリルートとして探索する。

    Returns
    -------
    Path
        リポジトリルート。

    Raises
    ------
    RuntimeError
        祖先ディレクトリを辿っても `pyproject.toml` が見つからない場合。
    """
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError("repo root が見つかりません（pyproject.toml が見つからない）")


def _parse_num(path: Path) -> int | None:
    """ファイル名先頭の連番を抽出する。

    例: `13_1184x1680.png` → `13`

    Parameters
    ----------
    path:
        対象パス（拡張子や suffix は問わないが、`stem` を使う）。

    Returns
    -------
    int | None
        先頭に数値があればその値。無ければ `None`。
    """
    m = _NUM_PREFIX_RE.match(path.stem)
    if m is None:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _collect_inputs(in_dir: Path) -> list[_InputImage]:
    """入力ディレクトリから、採用候補の PNG を列挙する。

    - `*.png` のみ対象
    - ファイル名先頭に数値があるものだけ採用（例: `13_*.png`）
    - 番号の昇順で返す
    - 同じ番号が 2 回以上出たらエラー（例: `1_a.png` と `1_b.png`）

    Parameters
    ----------
    in_dir:
        入力ディレクトリ（例: `data/output/png/readme/grn`）。

    Returns
    -------
    list[_InputImage]
        `_InputImage(num, path)` のリスト（番号で昇順）。

    Raises
    ------
    FileNotFoundError
        `in_dir` が存在しない場合。
    ValueError
        番号の重複が検出された場合。
    """
    if not in_dir.exists():
        raise FileNotFoundError(f"入力ディレクトリが見つかりません: {in_dir}")

    items: list[_InputImage] = []
    for p in sorted(in_dir.glob("*.png")):
        n = _parse_num(p)
        if n is None:
            continue
        items.append(_InputImage(num=n, path=p))

    nums = [it.num for it in items]
    if len(nums) != len(set(nums)):
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        raise ValueError(f"入力画像の番号が重複しています: {dupes}")

    items.sort(key=lambda x: x.num)
    return items


def _select(items: list[_InputImage], *, columns: int) -> list[_InputImage]:
    """README に並べる分だけを選ぶ。

    `columns` で割り切れる最大枚数になるように「先頭から」切り詰める。
    （余りは末尾=新しい側を落とす、という運用ルールをここに反映している）

    Parameters
    ----------
    items:
        入力画像（番号順）。
    columns:
        1 行あたりの枚数。

    Returns
    -------
    list[_InputImage]
        採用する画像のリスト（先頭から N 枚）。

    Raises
    ------
    ValueError
        `columns <= 0` の場合。
    """
    if columns <= 0:
        raise ValueError("columns は 1 以上である必要があります")
    n = (len(items) // columns) * columns
    return items[:n]


def _ensure_sips() -> str:
    """`sips` の実行ファイルパスを解決する。

    このスクリプトは依存追加を避けるため、macOS 標準の `sips` に頼る。

    Returns
    -------
    str
        `sips` の絶対パス。

    Raises
    ------
    RuntimeError
        `sips` が見つからない場合（macOS 以外など）。
    """
    # `sips` は macOS 標準だが、明示チェックしてエラーを分かりやすくする。
    from shutil import which

    exe = which("sips")
    if exe is None:
        raise RuntimeError("`sips` が見つかりません（macOS 以外では動作しません）")
    return exe


def _resize_with_sips(*, sips: str, src: Path, dst: Path, max_dim: int) -> None:
    """`sips` で PNG をリサイズして保存する。

    Parameters
    ----------
    sips:
        `sips` 実行ファイルパス。
    src:
        入力 PNG パス。
    dst:
        出力 PNG パス（親ディレクトリは必要なら作成する）。
    max_dim:
        出力画像の長辺 px（`sips -Z`）。

    Raises
    ------
    subprocess.CalledProcessError
        `sips` の実行に失敗した場合。

    Notes
    -----
    `sips` は `--out` がディレクトリでもファイルでも受け付けるが、
    ここでは「出力ファイル名を固定」したいのでファイルパスを渡している。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sips,
        "-s",
        "format",
        "png",
        "-Z",
        str(int(max_dim)),
        str(src),
        "--out",
        str(dst),
    ]
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _render_table(*, rel_paths: list[str], columns: int, img_width: int) -> str:
    """README に埋め込む HTML table を生成する。

    Parameters
    ----------
    rel_paths:
        README から参照する相対パスのリスト（例: `docs/readme/grn/13.png`）。
    columns:
        1 行あたりの枚数。
    img_width:
        `<img width="...">` に入れる値（px）。

    Returns
    -------
    str
        `<table>...</table>` の文字列。
    """
    rows: list[str] = []
    for i in range(0, len(rel_paths), columns):
        cells = "\n".join(
            [
                f'    <td><img src="{p}" width="{int(img_width)}" alt="grn {Path(p).stem}" /></td>'
                for p in rel_paths[i : i + columns]
            ]
        )
        rows.append(f"  <tr>\n{cells}\n  </tr>")
    rows_str = "\n".join(rows)
    return f"<table>\n{rows_str}\n</table>"


def _replace_readme_block(*, readme_path: Path, replacement: str) -> None:
    """README の自動生成ブロックを置換する。

    `<!-- BEGIN:README_EXAMPLES_GRN -->` と `<!-- END:README_EXAMPLES_GRN -->` の
    2 つのマーカーを探し、その間のテキストだけを差し替える。

    Parameters
    ----------
    readme_path:
        `README.md` のパス。
    replacement:
        マーカー間に差し込む文字列（例: `<table>...</table>`）。

    Raises
    ------
    ValueError
        BEGIN/END のどちらかが見つからない場合。

    Side Effects
    ------------
    置換結果が元と異なる場合に限り、`readme_path` を上書きする。
    """
    text = readme_path.read_text(encoding="utf-8")
    begin = text.find(_README_BEGIN)
    if begin == -1:
        raise ValueError(f"README の BEGIN マーカーが見つかりません: {readme_path}")
    end = text.find(_README_END, begin)
    if end == -1:
        raise ValueError(f"README の END マーカーが見つかりません: {readme_path}")

    begin_end = begin + len(_README_BEGIN)
    new_text = text[:begin_end] + "\n" + replacement.rstrip() + "\n" + text[end:]
    if new_text != text:
        readme_path.write_text(new_text, encoding="utf-8")


def main() -> int:
    """エントリポイント。

    - 入力ディレクトリから PNG を収集
    - 6 枚/行で割り切れる枚数に丸めて採用
    - `docs/readme/grn/<番号>.png` にリサイズ出力
    - README の BEGIN/END ブロックをタイル HTML で更新

    Returns
    -------
    int
        終了コード（0=成功）。

    Side Effects
    ------------
    - `docs/readme/grn/*.png` を生成/上書きする
    - `README.md` の自動生成ブロックを更新する
    - 進捗を標準出力に表示する
    """
    root = _find_repo_root()
    in_dir = root / "data/output/png/readme/grn"
    out_dir = root / "docs/readme/grn"
    readme_path = root / "README.md"

    items = _collect_inputs(in_dir)
    selected = _select(items, columns=int(COLUMNS))

    n_total = len(items)
    n_selected = len(selected)
    print(f"Found: {n_total} images")
    print(f"Use  : {n_selected} images (columns={int(COLUMNS)})")
    if n_selected == 0:
        print("Not enough images to fill a row; nothing to do.")
        return 0

    if DRY_RUN:
        return 0

    sips = _ensure_sips()
    for it in selected:
        dst = out_dir / f"{it.num}.png"
        _resize_with_sips(sips=sips, src=it.path, dst=dst, max_dim=int(MAX_DIM))

    rel_paths = [f"docs/readme/grn/{it.num}.png" for it in selected]
    table = _render_table(
        rel_paths=rel_paths, columns=int(COLUMNS), img_width=int(IMG_WIDTH)
    )
    _replace_readme_block(readme_path=readme_path, replacement=table)

    print(f"Updated: {readme_path}")
    print(f"Saved  : {out_dir}")
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
