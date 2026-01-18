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


class GroupOrdinals:
    """op ごとの (site_id -> ordinal) を管理する。

    UI 上で「同じ op の複数 site」を見分けるための連番を、op 単位で保持する。
    値は純粋に表示用だが、追加・移設のたびに番号が大きく揺れないような挙動を意図している。

    Attributes
    ----------
    _by_op : dict[str, dict[str, int]]
        op -> {site_id: ordinal} の内部テーブル。
        キーは外部から渡された値を `str(...)` へ正規化して保持する。

    Notes
    -----
    - `as_dict` / `replace_from_dict` は永続化（例: JSON）用の変換を想定する。
    - ordinal の欠番を詰めて 1..N にしたい場合は `compact` / `compact_all` を呼ぶ。
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

        # 外部から渡る op / site_id は型が揺れてもよい前提で、内部キーは str に寄せる。
        mapping = self._by_op.get(str(op))
        if mapping is None:
            return None
        return mapping.get(str(site_id))

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

        op = str(op)
        site_id = str(site_id)
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

        op = str(op)
        old_site_id = str(old_site_id)
        new_site_id = str(new_site_id)

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

        op = str(op)
        site_id = str(site_id)
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

        op = str(op)
        mapping = self._by_op.get(op)
        if not mapping:
            self._by_op.pop(op, None)
            return
        self._compact_mapping_in_place(mapping)

    def compact_all(self) -> None:
        """すべての op について ordinal を 1..N に詰め直す。"""

        # 内部状態が壊れていても（例: 外部入力の混入）、ここで dict 以外や空を掃除しつつ詰め直す。
        for op in list(self._by_op.keys()):
            mapping = self._by_op.get(op)
            if not isinstance(mapping, dict) or not mapping:
                self._by_op.pop(op, None)
                continue
            self._compact_mapping_in_place(mapping)

    def as_dict(self) -> dict[str, dict[str, int]]:
        """内部辞書のコピーを返す。

        Returns
        -------
        dict[str, dict[str, int]]
            `op -> {site_id: ordinal}` のディープコピー。
        """

        return {op: dict(mapping) for op, mapping in self._by_op.items()}

    def replace_from_dict(self, by_op: object) -> None:
        """dict 由来の値で内部辞書を置き換える。

        JSON などから復元した値を受け取り、内部表現（str -> int）に正規化して格納する。
        不正な要素はスキップし、`by_op` 自体が dict でなければ空にリセットする。

        Parameters
        ----------
        by_op
            `op -> {site_id: ordinal}` 形式を期待するが、実際には object として受ける。
        """

        if not isinstance(by_op, dict):
            self._by_op = {}
            return

        out: dict[str, dict[str, int]] = {}
        for op, raw_mapping in by_op.items():
            if not isinstance(raw_mapping, dict):
                continue
            cleaned: dict[str, int] = {}
            for site_id, ordinal in raw_mapping.items():
                try:
                    # JSON 由来の値などを想定し、キーは str、ordinal は int に寄せる。
                    cleaned[str(site_id)] = int(ordinal)  # type: ignore[arg-type]
                except Exception:
                    continue
            if cleaned:
                out[str(op)] = cleaned
        self._by_op = out

    @staticmethod
    def _compact_mapping_in_place(mapping: dict[str, int]) -> None:
        """site_id -> ordinal を 1..N の連番に詰め直す（in-place）。

        `ordinal` の昇順（同値は site_id の辞書順）で並べ、先頭から 1..N を振り直す。
        """

        def _sort_key(item: tuple[str, int]) -> tuple[int, str]:
            site_id, ordinal = item
            try:
                ordinal_i = int(ordinal)
            except Exception:
                # ordinal が壊れていてもクラッシュさせず、先頭側に寄せる。
                ordinal_i = 0
            return ordinal_i, str(site_id)

        # 相対順は ordinal を基準に保つ。タイブレークは site_id に寄せて決定性を確保する。
        ordered_site_ids = [site_id for site_id, _ in sorted(mapping.items(), key=_sort_key)]
        mapping.clear()
        for i, site_id in enumerate(ordered_site_ids, start=1):
            mapping[str(site_id)] = int(i)


__all__ = ["GroupOrdinals"]
