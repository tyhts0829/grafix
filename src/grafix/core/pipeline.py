"""
どこで: `src/grafix/core/pipeline.py`。
何を: user_draw が生成するシーンを正規化・スタイル解決・realize し、描画/出力に使える “最終形” を返す。
なぜ: interactive（GL 描画）と export（ヘッドレス出力）で共通のパイプラインを共有し、依存方向を単純化するため。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from grafix.core.realize import realize
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.layer import Layer, LayerStyleDefaults, resolve_layer_style
from grafix.core.scene import SceneItem, normalize_scene
from grafix.core.parameters.layer_style import observe_and_apply_layer_style


@dataclass(frozen=True, slots=True)
class RealizedLayer:
    """描画/出力のために realize 済みにした Layer 表現。"""

    layer: Layer
    realized: RealizedGeometry
    color: tuple[float, float, float]
    thickness: float


def realize_scene(
    draw: Callable[[float], SceneItem],
    t: float,
    defaults: LayerStyleDefaults,
) -> list[RealizedLayer]:
    """1 フレーム分のシーンを realize して返す。

    Parameters
    ----------
    draw : Callable[[float], SceneItem]
        フレーム時刻 t を受け取り Geometry / Layer / Sequence を返すコールバック。
    t : float
        現在フレームの経過秒。
    defaults : LayerStyleDefaults
        スタイル欠損を埋める既定値。

    Returns
    -------
    list[RealizedLayer]
        realize 済みの Layer 列。
    """

    scene = draw(t)
    layers = normalize_scene(scene)

    out: list[RealizedLayer] = []
    for layer in layers:
        resolved = resolve_layer_style(layer, defaults)
        thickness, color = observe_and_apply_layer_style(
            layer_site_id=layer.site_id,
            layer_name=layer.name,
            base_line_thickness=float(resolved.thickness),
            base_line_color_rgb01=resolved.color,
            explicit_line_thickness=(layer.thickness is not None),
            explicit_line_color=(layer.color is not None),
        )

        geometry = resolved.layer.geometry
        # Geometry は L 側で concat 済みのためそのまま扱う
        realized = realize(geometry)
        out.append(
            RealizedLayer(
                layer=resolved.layer,
                realized=realized,
                color=color,
                thickness=thickness,
            )
        )

    return out
