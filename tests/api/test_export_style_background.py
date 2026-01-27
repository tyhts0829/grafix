from __future__ import annotations

from pathlib import Path

from grafix import G
from grafix.api import Export
from grafix.core.parameters import ParamStore
from grafix.core.parameters.style import style_key
from grafix.core.parameters.style_ops import ensure_style_entries
from grafix.core.parameters.ui_ops import update_state_from_ui


def test_export_uses_paramstore_background_color(monkeypatch, tmp_path: Path) -> None:
    import grafix.api.export as export_module

    store = ParamStore()
    ensure_style_entries(
        store,
        background_color_rgb01=(1.0, 1.0, 1.0),
        global_thickness=0.001,
        global_line_color_rgb01=(0.0, 0.0, 0.0),
    )

    bg_key = style_key("background_color")
    bg_meta = store.get_meta(bg_key)
    assert bg_meta is not None
    ok, _err = update_state_from_ui(store, bg_key, (0, 0, 0), meta=bg_meta)
    assert ok

    monkeypatch.setattr(export_module, "default_param_store_path", lambda *_a, **_k: tmp_path / "dummy.json")
    monkeypatch.setattr(export_module, "load_param_store", lambda _path: store)

    captured: dict[str, object] = {}

    def _fake_export_image(layers, path, *, canvas_size, background_color):
        captured["background_color"] = background_color
        return Path(path)

    monkeypatch.setattr(export_module, "export_image", _fake_export_image)

    def draw(_t: float):
        return G.line(
            activate=True,
            center=(5.0, 5.0, 0.0),
            anchor="left",
            length=5.0,
            angle=0.0,
        )

    exp = Export(
        draw,
        t=0.0,
        fmt="png",
        path=tmp_path / "out.png",
        canvas_size=(10, 10),
        background_color=(1.0, 1.0, 1.0),
    )

    assert exp.style.bg_color_rgb01 == (0.0, 0.0, 0.0)
    assert captured["background_color"] == (0.0, 0.0, 0.0)

