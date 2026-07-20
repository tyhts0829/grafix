"""capture/export が共有する公開結果型を定義する。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grafix.core.export_format import ExportFormat


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportResult:
    """保存処理が確定した実出力 path と manifest を表す不変結果。

    Parameters
    ----------
    path : Path
        no-clobber の連番解決後に公開された実 artifact path。
    format : ExportFormat
        path suffix と一致する出力形式。
    manifest_path : Path
        artifact と同じ generation で公開された必須 capture manifest path。

    Notes
    -----
    すべての引数は keyword-only。
    """

    path: Path
    format: ExportFormat
    manifest_path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("path は Path である必要があります")
        if not isinstance(self.manifest_path, Path):
            raise TypeError("manifest_path は Path である必要があります")
        artifact_format = ExportFormat.resolve(self.path, self.format)
        object.__setattr__(self, "format", artifact_format)


__all__ = ["ExportResult"]
