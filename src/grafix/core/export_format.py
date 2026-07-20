"""全 export 層で共有する canonical 出力形式。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class ExportFormat(StrEnum):
    """path suffix と一対一に対応する出力形式。"""

    SVG = "svg"
    PNG = "png"
    GCODE = "gcode"

    @property
    def suffix(self) -> str:
        """この形式の canonical suffix を返す。"""

        return f".{self.value}"

    @classmethod
    def from_path(cls, path: str | Path) -> ExportFormat:
        """path suffix だけから形式を確定する。"""

        suffix = Path(path).suffix.casefold()
        for item in cls:
            if suffix == item.suffix:
                return item
        raise ValueError(f"未対応または未指定の export suffix です: {suffix!r}")

    @classmethod
    def resolve(
        cls,
        path: str | Path,
        explicit_format: ExportFormat | None = None,
    ) -> ExportFormat:
        """suffix を正とし、明示形式があれば一致を検証する。"""

        suffix_format = cls.from_path(path)
        if explicit_format is None:
            return suffix_format
        if not isinstance(explicit_format, cls):
            raise TypeError(
                "explicit_format は ExportFormat または None である必要があります"
            )
        if explicit_format is not suffix_format:
            raise ValueError(
                "export format と path suffix が一致しません: "
                f"format={explicit_format.value!r}, suffix={Path(path).suffix!r}"
            )
        return suffix_format


__all__ = ["ExportFormat"]
