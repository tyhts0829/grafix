"""(op, site_id) の GUI 用 ordinal（連番）を管理する。

主に UI 表示の都合で、同一 op 内の複数 site を 1..N の番号で区別したい。
そのために (op, site_id) -> ordinal を保持し、採番・移設・欠番の圧縮(compact)を提供する。

Notes
-----
- ordinal は表示用であり値自体に意味はないが、ユーザーの認知が崩れないよう
  できるだけ安定させることを意図する。
- `migrate` は site_id の変更（移設/リネーム）を想定し、新 site_id に旧 ordinal を引き継がせる。
  ただし stale な old_site_id も prune されるまで残る前提があるため、old 側も ordinal を保持する。
"""

from __future__ import annotations

from .identity import identity_string


class GroupOrdinals:
    """op ごとの (site_id -> ordinal) を管理する。

    UI 上で「同じ op の複数 site」を見分けるための連番を、op 単位で保持する。
    値は純粋に表示用だが、追加・移設のたびに番号が大きく揺れないような挙動を意図している。

    Attributes
    ----------
    _by_op : dict[str, dict[str, int]]
        op -> {site_id: ordinal} の内部テーブル。
        キーは canonical な空でない文字列だけを保持する。

    Notes
    -----
    - `as_dict` / `replace` は永続化用の値をコピーする。
    - ordinal の欠番を詰めて 1..N にしたい場合は `compact` を呼ぶ。
    """

    def __init__(self) -> None:
        # op ごとに "site_id -> ordinal" の辞書を持つ。
        self._by_op: dict[str, dict[str, int]] = {}

    def get(self, op: str, site_id: str) -> int | None:
        """既存 ordinal を返す。

        Parameters
        ----------
        op
            op 識別子（effect / primitive など）。
        site_id
            op 内の site 識別子。

        Returns
        -------
        int | None
            登録済みなら ordinal、未登録なら None。
        """

        mapping = self._by_op.get(identity_string(op, name="op"))
        if mapping is None:
            return None
        return mapping.get(identity_string(site_id, name="site_id"))

    def get_or_assign(self, op: str, site_id: str) -> int:
        """既存 ordinal を返し、未登録なら採番して返す。

        採番は「その op 内の現在の要素数 + 1」で行う。
        欠番（削除や外部入力によるギャップ）を詰めたい場合は `compact` を使う。

        Parameters
        ----------
        op
            op 識別子。
        site_id
            op 内の site 識別子。

        Returns
        -------
        int
            既存または新規に割り当てた ordinal（1 始まり）。
        """

        op = identity_string(op, name="op")
        site_id = identity_string(site_id, name="site_id")
        mapping = self._by_op.setdefault(op, {})
        if site_id in mapping:
            return int(mapping[site_id])
        # 追加は末尾に割り当てる。相対順の安定性を優先し、欠番はここでは詰めない。
        ordinal = len(mapping) + 1
        mapping[site_id] = int(ordinal)
        return int(ordinal)

    def migrate(self, op: str, old_site_id: str, new_site_id: str) -> None:
        """site_id 変更を想定して ordinal を移す（old 側も ordinal を保つ）。

        同一 op 内で old_site_id の ordinal を new_site_id に引き継がせる。
        old_site_id は prune まで残る前提があるため、移設後も何らかの ordinal を保持する。

        - new_site_id がすでに存在する場合: old と new の ordinal を入れ替える。
        - new_site_id が未登録の場合: new は old の ordinal を引き継ぎ、old は末尾へ回す。

        Parameters
        ----------
        op
            op 識別子。
        old_site_id
            変更前の site_id。
        new_site_id
            変更後の site_id。
        """

        op = identity_string(op, name="op")
        old_site_id = identity_string(old_site_id, name="old_site_id")
        new_site_id = identity_string(new_site_id, name="new_site_id")

        mapping = self._by_op.get(op)
        if mapping is None:
            return
        old_ordinal = mapping.get(old_site_id)
        if old_ordinal is None:
            return

        # new が既に番号を持っている場合は swap にする（両方の ordinal を保持したまま整合させる）。
        new_ordinal = mapping.get(new_site_id)
        mapping[new_site_id] = int(old_ordinal)

        # migrate は「新グループへ旧 ordinal を引き継ぐ」目的だが、
        # stale グループは prune まで残るため、snapshot 不変条件として old も ordinal を持ち続ける。
        if new_ordinal is not None:
            mapping[old_site_id] = int(new_ordinal)
        else:
            # 末尾へ回す。`mapping[new_site_id]` を入れた後なので max は new を含む点に注意。
            mapping[old_site_id] = int(max(mapping.values(), default=0) + 1)

    def delete(self, op: str, site_id: str) -> None:
        """指定 site_id の ordinal を削除する。

        Parameters
        ----------
        op
            op 識別子。
        site_id
            削除対象の site_id。
        """

        op = identity_string(op, name="op")
        site_id = identity_string(site_id, name="site_id")
        mapping = self._by_op.get(op)
        if mapping is None:
            return
        mapping.pop(site_id, None)
        if not mapping:
            self._by_op.pop(op, None)

    def compact(self, op: str) -> None:
        """op の ordinal を 1..N の連番へ詰め直す（相対順は維持）。

        Parameters
        ----------
        op
            対象 op。
        """

        op = identity_string(op, name="op")
        mapping = self._by_op.get(op)
        if not mapping:
            self._by_op.pop(op, None)
            return
        self._compact_mapping_in_place(mapping)

    def as_dict(self) -> dict[str, dict[str, int]]:
        """内部辞書のコピーを返す。

        Returns
        -------
        dict[str, dict[str, int]]
            `op -> {site_id: ordinal}` のディープコピー。
        """

        return {op: dict(mapping) for op, mapping in self._by_op.items()}

    def replace(self, by_op: dict[str, dict[str, int]]) -> None:
        """検証済み ordinal のディープコピーで内部辞書を置き換える。

        Parameters
        ----------
        by_op
            `op -> {site_id: ordinal}` 形式の canonical 値。
        """

        self._by_op = {
            op: dict(mapping)
            for op, mapping in by_op.items()
        }

    @staticmethod
    def _compact_mapping_in_place(mapping: dict[str, int]) -> None:
        """site_id -> ordinal を 1..N の連番に詰め直す（in-place）。

        `ordinal` の昇順（同値は site_id の辞書順）で並べ、先頭から 1..N を振り直す。
        """

        def _sort_key(item: tuple[str, int]) -> tuple[int, str]:
            site_id, ordinal = item
            return ordinal, site_id

        # 相対順は ordinal を基準に保つ。タイブレークは site_id に寄せて決定性を確保する。
        ordered_site_ids = [site_id for site_id, _ in sorted(mapping.items(), key=_sort_key)]
        mapping.clear()
        for i, site_id in enumerate(ordered_site_ids, start=1):
            mapping[site_id] = i


__all__ = ["GroupOrdinals"]
