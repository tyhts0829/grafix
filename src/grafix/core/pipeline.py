"""
どこで: `src/grafix/core/pipeline.py`。
何を: user_draw が生成するシーンを正規化・スタイル解決・realize し、描画/出力に使える “最終形” を返す。
なぜ: interactive（GL 描画）と export（ヘッドレス出力）で共通のパイプラインを共有し、依存方向を単純化するため。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from grafix.core.layer import Layer, LayerStyleDefaults, resolve_layer_style
from grafix.core.parameters.layer_style import observe_and_apply_layer_style
from grafix.core.realize import GeometryCacheKey, RealizeSession
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.resource_budget import ensure_resource_usage
from grafix.core.scene import SceneItem, normalize_scene
from grafix.core.value_validation import (
    exact_integer,
    exact_string,
    finite_real,
    rgb01_tuple,
)


@dataclass(frozen=True, slots=True)
class RealizedLayer:
    """描画/出力のために realize 済みにした Layer 表現。"""

    layer: Layer
    realized: RealizedGeometry
    cache_key: GeometryCacheKey
    color: tuple[float, float, float]
    thickness: float

    def __post_init__(self) -> None:
        if not isinstance(self.layer, Layer):
            raise TypeError("RealizedLayer.layer は Layer である必要があります")
        if not isinstance(self.realized, RealizedGeometry):
            raise TypeError(
                "RealizedLayer.realized は RealizedGeometry である必要があります"
            )
        cache_key = self.cache_key
        if type(cache_key) is not tuple or len(cache_key) != 2:
            raise TypeError(
                "RealizedLayer.cache_key は (geometry_id, revision) tuple である必要があります"
            )
        geometry_id = exact_string(
            cache_key[0],
            name="RealizedLayer.cache_key.geometry_id",
        )
        revision = cache_key[1]
        if type(revision) is not tuple or len(revision) != 2:
            raise TypeError(
                "RealizedLayer.cache_key revision は2要素の tuple である必要があります"
            )
        normalized_key: GeometryCacheKey = (
            geometry_id,
            (
                exact_integer(
                    revision[0],
                    name="RealizedLayer.cache_key.primitive_revision",
                    minimum=0,
                ),
                exact_integer(
                    revision[1],
                    name="RealizedLayer.cache_key.effect_revision",
                    minimum=0,
                ),
            ),
        )
        if geometry_id != self.layer.geometry.id:
            raise ValueError(
                "RealizedLayer.cache_key geometry_id は Layer.geometry.id と"
                "一致する必要があります"
            )
        object.__setattr__(self, "cache_key", normalized_key)
        object.__setattr__(
            self,
            "color",
            rgb01_tuple(self.color, name="RealizedLayer.color"),
        )
        object.__setattr__(
            self,
            "thickness",
            finite_real(
                self.thickness,
                name="RealizedLayer.thickness",
                minimum=0.0,
                minimum_inclusive=False,
            ),
        )


def realize_scene(
    draw: Callable[[float], SceneItem],
    t: float,
    defaults: LayerStyleDefaults,
    *,
    session: RealizeSession | None = None,
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
    session : RealizeSession or None, optional
        複数フレームで共有する評価セッション。省略時はこの呼び出しだけが所有する。

    Returns
    -------
    list[RealizedLayer]
        realize 済みの Layer 列。
    """

    owned_session = session is None
    active_session = RealizeSession() if session is None else session
    try:
        scene = draw(t)
        layers = normalize_scene(scene)

        out: list[RealizedLayer] = []
        total_vertices = 0
        total_lines = 0
        total_bytes = 0
        # 各 layer を評価しないと scene 実測量は分からないため、新しい CPU cache
        # entry は aggregate 検査が完了するまで transaction 内に留める。
        with active_session.cache_transaction() as cache_transaction:
            for layer_index, layer in enumerate(layers):
                layer_label = layer.name or layer.site_id or f"Layer {layer_index + 1}"
                with active_session.profile_layer(layer_label):
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
                    # Geometry は L 側で concat 済みのためそのまま扱う。
                    realized, cache_key = active_session.realize_with_key(geometry)
                    total_vertices += int(realized.coords.shape[0])
                    total_lines += max(0, int(realized.offsets.size) - 1)
                    total_bytes += int(realized.byte_size)
                    ensure_resource_usage(
                        "scene aggregate",
                        vertices=total_vertices,
                        lines=total_lines,
                        byte_size=total_bytes,
                        budget=active_session.runtime_limits.scene,
                        hint=(
                            "layer 数、各 layer の密度、または final 出力設定を"
                            "見直してください"
                        ),
                    )
                    out.append(
                        RealizedLayer(
                            layer=resolved.layer,
                            realized=realized,
                            cache_key=cache_key,
                            color=color,
                            thickness=thickness,
                        )
                    )

            cache_transaction.commit()

        return out
    finally:
        if owned_session:
            active_session.close()
