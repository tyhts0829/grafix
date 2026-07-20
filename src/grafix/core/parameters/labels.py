# どこで: `src/grafix/core/parameters/labels.py`。
# 何を: (op, site_id) -> label の管理を提供する。
# なぜ: ParamStore から label 管理の責務を分離し、変更の波及を減らすため。

from __future__ import annotations

from .identity import identity_string

MAX_LABEL_LENGTH = 64


class ParamLabels:
    """(op, site_id) -> label の薄い辞書ラッパ。"""

    def __init__(self) -> None:
        self._by_group: dict[tuple[str, str], str] = {}

    def get(self, op: str, site_id: str) -> str | None:
        """ラベルを返す。未登録なら None。"""

        return self._by_group.get(
            (
                identity_string(op, name="op"),
                identity_string(site_id, name="site_id"),
            )
        )

    def set(self, op: str, site_id: str, label: str) -> None:
        """ラベルを設定（上書き可）する。"""

        if not isinstance(label, str):
            raise TypeError("label は文字列である必要があります")
        self._by_group[
            (
                identity_string(op, name="op"),
                identity_string(site_id, name="site_id"),
            )
        ] = self._trim(label)

    def delete(self, op: str, site_id: str) -> None:
        """指定グループのラベルを削除する。"""

        self._by_group.pop(
            (
                identity_string(op, name="op"),
                identity_string(site_id, name="site_id"),
            ),
            None,
        )

    def as_dict(self) -> dict[tuple[str, str], str]:
        """内部辞書のコピーを返す。"""

        return dict(self._by_group)

    def replace(self, labels: dict[tuple[str, str], str]) -> None:
        """検証済みラベルのコピーで内部辞書を置き換える。"""

        self._by_group = dict(labels)

    @staticmethod
    def _trim(label: str) -> str:
        return label if len(label) <= MAX_LABEL_LENGTH else label[:MAX_LABEL_LENGTH]


__all__ = ["ParamLabels", "MAX_LABEL_LENGTH"]
