# どこで: `src/grafix/api/layers.py`。
# 何を: Geometry を Layer 化する公開名前空間 L を提供する。
# なぜ: `G/E/P` と同じ “namespace + label” 体験で Layer を扱えるようにするため。

from __future__ import annotations

from typing import Sequence

from grafix.core.geometry import Geometry
from grafix.core.parameters import caller_site_id, current_param_store
from grafix.core.parameters.labels_ops import set_label
from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.layer import Layer


class LayerNamespace:
    """Geometry を Layer 化する名前空間。

    Notes
    -----
    `G/E/P` と同様に、`L(name="...")` で pending なラベルを持つ別インスタンスを返す。
    生成は `L.layer(..., color=..., thickness=...)` で行う。
    """

    def __call__(
        self,
        name: str | None = None,
    ) -> "LayerNamespace":
        if name is not None and not isinstance(name, str):
            raise TypeError(f"L(name=...) は str のみ受け付けます: {type(name)!r}")
        ns = LayerNamespace()
        ns._pending_name = name  # type: ignore[attr-defined]
        return ns

    def layer(
        self,
        geometry_or_list: Geometry | Sequence[Geometry],
        *,
        color: tuple[float, float, float] | None = None,
        thickness: float | None = None,
    ) -> list[Layer]:
        """単体/複数の Geometry から Layer を生成する。

        Parameters
        ----------
        geometry_or_list : Geometry or Sequence[Geometry]
            入力 Geometry または Geometry の列。
        color : tuple[float, float, float] or None, optional
            RGB 色。None の場合は既定値に委譲。
        thickness : float or None, optional
            線幅。None の場合は既定値に委譲。0 以下は拒否。

        Returns
        -------
        list[Layer]
            生成された Layer のリスト（長さ 1）。

        Raises
        ------
        TypeError
            Geometry 以外が渡された場合。
        ValueError
            thickness が 0 以下の場合、または空リストの場合。
        """

        resolved_name = self._pending_name

        if thickness is not None and thickness <= 0:
            raise ValueError("thickness は正の値である必要がある")

        # geometry_or_list を Geometry のリストに正規化する。
        geometries: list[Geometry]
        if isinstance(geometry_or_list, Geometry):
            geometries = [geometry_or_list]
        elif isinstance(geometry_or_list, Sequence):
            geometries = []
            for g in geometry_or_list:
                if not isinstance(g, Geometry):
                    raise TypeError(
                        f"L.layer には Geometry だけを渡してください: {type(g)!r}"
                    )
                geometries.append(g)
        else:
            raise TypeError(
                "L.layer は Geometry またはその列のみを受け付けます:"
                f" {type(geometry_or_list)!r}"
            )

        if not geometries:
            raise ValueError("L.layer に空の Geometry リストは渡せません")

        # site_id は「この Layer が生成された呼び出し箇所」を識別する安定 ID。
        # Layer style（line_thickness/line_color）の行は、この site_id をキーとして保存する。
        site_id = caller_site_id(skip=1)

        store = current_param_store()
        if store is not None and resolved_name is not None:
            set_label(store, op=LAYER_STYLE_OP, site_id=site_id, label=resolved_name)

        # 複数 Geometry は concat で 1 Layer にまとめる。
        if len(geometries) == 1:
            geometry = geometries[0]
        else:
            geometry = Geometry.create(op="concat", inputs=tuple(geometries), params={})

        return [
            Layer(
                geometry=geometry,
                site_id=site_id,
                color=color,
                thickness=thickness,
                name=resolved_name,
            )
        ]

    _pending_name: str | None = None


L = LayerNamespace()
"""Geometry を Layer 化する公開名前空間。"""

__all__ = ["L"]
