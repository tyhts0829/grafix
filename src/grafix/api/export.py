"""
どこで: `src/grafix/api/export.py`。
何を: ヘッドレス export の公開導線 `Export` を提供する（当面はスタブ）。
なぜ: 対話ウィンドウを立ち上げずに `draw(t)` の 1 フレーム出力を保存できる形を先に固定するため。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from grafix.core.layer import LayerStyleDefaults
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.persistence import default_param_store_path, load_param_store
from grafix.core.pipeline import RealizedLayer, realize_scene
from grafix.core.scene import SceneItem
from grafix.export.gcode import export_gcode
from grafix.export.image import export_image
from grafix.export.svg import export_svg


class Export:
    """`draw(t)` の 1 フレーム分をファイルへ書き出す。

    Notes
    -----
    現段階では API の骨格のみを提供し、各フォーマットの実出力は未実装とする。
    """

    def __init__(
        self,
        draw: Callable[[float], SceneItem],
        t: float,
        fmt: str,
        path: str | Path,
        *,
        canvas_size: tuple[int, int] = (800, 800),
        line_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
        line_thickness: float = 0.01,
        background_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        run_id: str | None = None,
    ) -> None:
        """export を実行する。

        Parameters
        ----------
        draw : Callable[[float], SceneItem]
            フレーム時刻 t を受け取り Geometry/Layer/Sequence を返すコールバック。
        t : float
            出力対象のフレーム時刻。
        fmt : str
            出力フォーマット。`"svg"`, `"image"`, `"gcode"` を想定する。
        path : str or Path
            出力先パス。
        canvas_size : tuple[int, int]
            キャンバス寸法（将来の出力で使用）。
        line_color : tuple[float, float, float]
            Layer の既定線色（0..1）。
        line_thickness : float
            Layer の既定線幅。
        background_color : tuple[float, float, float]
            背景色（0..1）。画像出力で使用する想定。
        run_id : str | None
            ParamStore の既定パス（読み込み元）の run_id suffix。
        """
        self.path = Path(path)
        self.fmt = str(fmt).lower().strip()

        defaults = LayerStyleDefaults(color=line_color, thickness=float(line_thickness))

        # headless export でも ParamStore の保存値（GUI で調整した値）を反映する。
        # これにより「コードに明示されていないパラメータ」も保存済みの UI 値で解決できる。
        store_path = default_param_store_path(draw, run_id=run_id)
        store = load_param_store(store_path)
        with parameter_context(store):
            self.layers: list[RealizedLayer] = realize_scene(draw, float(t), defaults)

        if self.fmt == "svg":
            export_svg(self.layers, self.path, canvas_size=canvas_size)
            return
        if self.fmt in {"image", "png"}:
            export_image(
                self.layers,
                self.path,
                canvas_size=canvas_size,
                background_color=background_color,
            )
            return
        if self.fmt in {"gcode", "g-code"}:
            export_gcode(self.layers, self.path, canvas_size=canvas_size)
            return

        raise ValueError(f"未対応の export fmt: {fmt!r}")
